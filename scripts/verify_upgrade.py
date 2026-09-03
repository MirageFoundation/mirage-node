#!/usr/bin/env python3
"""Post-deploy verification for the v1.39.0 communities upgrade.

v1.39.0 is a consensus change: topics become communities, Agent is removed,
subscriptions stop using a relay reserve, and a creator pool is funded from
new subscription fees. The checks here prove the governed plan applied and
that the chain, indexer, and backend agree on the new parameters.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path("/opt/mirage")
if not ROOT.is_dir():
    ROOT = Path(__file__).resolve().parent.parent

VERSION = "v1.39.0"
UPGRADE_NAME = "v1.39.0"
RPC = "http://127.0.0.1:26657"
REST = "http://127.0.0.1:1317"
BACKEND = "http://127.0.0.1:80"
STATUS_DIR = Path("/root/.mirage/upgrade_tests")
passed = 0
failed = 0


def ok(message: str) -> None:
    global passed
    passed += 1
    print(f"  PASS  {message}")


def fail(message: str) -> None:
    global failed
    failed += 1
    print(f"  FAIL  {message}")


# Postflight runs this script while test_blockchain and test_backend are already
# hammering the same Caddy instance, so the shared rate limiter answers 429 to a
# burst that has nothing wrong with it. Retry those (and the transient gateway
# codes) with backoff, honouring Retry-After, then fail hard — a 429 that
# survives the whole budget is a real finding, a single one is scheduling noise.
_RETRY_STATUSES = (429, 502, 503, 504)
_MAX_ATTEMPTS = 6


def _retry_delay(error: urllib.error.HTTPError, attempt: int) -> float:
    retry_after = error.headers.get("Retry-After") if error.headers else None
    if retry_after:
        try:
            return min(15.0, max(0.5, float(retry_after)))
        except (TypeError, ValueError):
            pass
    return min(8.0, 0.5 * (2 ** (attempt - 1)))


def http_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                return json.loads(response.read().decode())
        except urllib.error.HTTPError as e:
            if e.code not in _RETRY_STATUSES or attempt == _MAX_ATTEMPTS:
                raise
            delay = _retry_delay(e, attempt)
            print(f"  DEBUG  {url} -> {e.code}, retry {attempt}/{_MAX_ATTEMPTS} in {delay:.1f}s")
            time.sleep(delay)
    raise RuntimeError(f"unreachable retry loop for {url}")


def http_status(url: str, method: str = "GET") -> int:
    body = b"{}" if method == "POST" else None
    req = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={"Accept": "application/json", "Content-Type": "application/json"},
    )
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                return int(response.status)
        except urllib.error.HTTPError as e:
            # A route check asserts on the status itself, so only the shared
            # limiter and gateway codes are retried; 410/403/404 are answers.
            if e.code not in _RETRY_STATUSES or attempt == _MAX_ATTEMPTS:
                return int(e.code)
            delay = _retry_delay(e, attempt)
            print(f"  DEBUG  {method} {url} -> {e.code}, retry {attempt}/{_MAX_ATTEMPTS} in {delay:.1f}s")
            time.sleep(delay)
    raise RuntimeError(f"unreachable retry loop for {url}")


def http_json_response(url: str, method: str = "GET", body: dict | None = None) -> tuple[int, object]:
    encoded = json.dumps(body or {}).encode() if method == "POST" else None
    req = urllib.request.Request(
        url,
        data=encoded,
        method=method,
        headers={"Accept": "application/json", "Content-Type": "application/json"},
    )
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                raw = response.read().decode()
                return int(response.status), json.loads(raw)
        except urllib.error.HTTPError as e:
            if e.code in _RETRY_STATUSES and attempt < _MAX_ATTEMPTS:
                delay = _retry_delay(e, attempt)
                print(f"  DEBUG  {method} {url} -> {e.code}, retry {attempt}/{_MAX_ATTEMPTS} in {delay:.1f}s")
                time.sleep(delay)
                continue
            raw = e.read().decode()
            try:
                payload: object = json.loads(raw)
            except json.JSONDecodeError:
                payload = {"raw": raw}
            return int(e.code), payload
    raise RuntimeError(f"unreachable retry loop for {url}")


def run(command: list[str]) -> str:
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"{' '.join(command)} failed: {(result.stderr or result.stdout).strip()}")
    return result.stdout


def check_versions() -> None:
    release = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    if release == VERSION:
        ok(f"VERSION={release}")
    else:
        fail(f"VERSION={release!r}, expected {VERSION}")

    frontend = (ROOT / "web/frontend/build/version.txt").read_text(encoding="utf-8").strip()
    if frontend == VERSION:
        ok(f"frontend version={frontend}")
    else:
        fail(f"frontend version={frontend!r}, expected {VERSION}")

    output = run([str(ROOT / "blockchain/bin/miraged"), "version", "--long"])
    reported = next((line.split(":", 1)[1].strip() for line in output.splitlines() if line.startswith("version:")), "")
    if reported.lstrip("v") == VERSION.lstrip("v"):
        ok(f"chain binary version={reported}")
    else:
        fail(f"chain binary version={reported!r}, expected {VERSION}")


def check_upgrade_applied() -> None:
    applied = http_json(f"{REST}/cosmos/upgrade/v1beta1/applied_plan/{UPGRADE_NAME}")
    height = int(applied.get("height") or applied.get("Height") or 0)
    if height > 0:
        ok(f"upgrade {UPGRADE_NAME} applied at height {height}")
    else:
        fail(f"no applied plan recorded for {UPGRADE_NAME}: {applied}")

    plan = http_json(f"{REST}/cosmos/upgrade/v1beta1/current_plan").get("plan")
    if plan:
        fail(f"a software-upgrade plan is still scheduled after the upgrade: {plan}")
    else:
        ok("no software-upgrade plan remains scheduled")


def check_params() -> None:
    params = http_json(f"{REST}/mirage/core/v1/params")["params"]
    if str(params.get("subscription_reserve_bps", "1")) == "0":
        ok("subscription_reserve_bps=0")
    else:
        fail(f"subscription_reserve_bps={params.get('subscription_reserve_bps')!r}")
    if str(params.get("subscription_creator_bps")) == "5000":
        ok("subscription_creator_bps=5000")
    else:
        fail(f"subscription_creator_bps={params.get('subscription_creator_bps')!r}")
    # The upgrade seeds 1000, but governance owns the value from then on and the
    # local rehearsal raises it so the suites do not spend a wallet's whole day.
    # What has to hold is that the parameter exists and is in the range the chain
    # accepts; pinning the default made a legitimately raised chain fail here.
    try:
        relay_limit = int(params["subscriber_daily_relay_limit"])
    except (KeyError, TypeError, ValueError):
        relay_limit = 0
    if 1 <= relay_limit <= 10000:
        ok(f"subscriber_daily_relay_limit={relay_limit}")
    else:
        fail(f"subscriber_daily_relay_limit={params.get('subscriber_daily_relay_limit')!r}")
    tiers = params.get("tiers") or []
    if len(tiers) == 3:
        ok("three subscription tiers (free/subscriber/admin)")
        try:
            free_cap = int((tiers[0] or {}).get("max_curation_memberships", -1))
            sub_cap = int((tiers[1] or {}).get("max_curation_memberships", -1))
            admin_cap = int((tiers[2] or {}).get("max_curation_memberships", -1))
            admin_fee = int((tiers[2] or {}).get("period_fee", -1))
            free_relays = int((tiers[0] or {}).get("max_daily_relays", -1))
            sub_relays = int((tiers[1] or {}).get("max_daily_relays", -1))
            admin_relays = int((tiers[2] or {}).get("max_daily_relays", -1))
        except (TypeError, ValueError):
            free_cap = sub_cap = admin_cap = admin_fee = -1
            free_relays = sub_relays = admin_relays = -1
        if free_cap == 0 and sub_cap == 10 and admin_cap == 1000 and admin_fee == 0:
            ok("curation membership caps free=0 subscriber=10 admin=1000")
        else:
            fail(
                f"curation membership caps unexpected: free={free_cap} "
                f"subscriber={sub_cap} admin={admin_cap} admin_fee={admin_fee}"
            )
        if free_relays == 0 and sub_relays == relay_limit and 1 <= admin_relays <= 10000:
            ok(f"daily relay caps free=0 subscriber={sub_relays} admin={admin_relays}")
        else:
            fail(f"daily relay caps unexpected: free={free_relays} " f"subscriber={sub_relays} admin={admin_relays}")
    else:
        fail(f"tier count={len(tiers)}")
    retired = {
        "max_community_title_length",
        "max_community_description_length",
        "max_curation_team_policy_length",
    }
    present = sorted(retired.intersection(params))
    if present:
        fail(f"retired community/curation params remain: {present}")
    else:
        ok("retired community metadata and team policy params are gone")
    try:
        desc_limit = int(params["max_curation_team_description_length"])
    except (KeyError, TypeError, ValueError):
        desc_limit = 0
    if desc_limit == 800:
        ok("max_curation_team_description_length=800")
    else:
        fail(f"max_curation_team_description_length={params.get('max_curation_team_description_length')!r}")
    if str(params.get("creator_epoch_seconds")) == "21600":
        ok("creator_epoch_seconds=21600")
    else:
        fail(f"creator_epoch_seconds={params.get('creator_epoch_seconds')!r}")


def check_preserved_params() -> None:
    snapshot_path = STATUS_DIR / "pre_upgrade_params.json"
    after_path = STATUS_DIR / "post_upgrade_params.json"
    if not snapshot_path.is_file():
        fail(f"pre-upgrade parameter snapshot missing: {snapshot_path}")
        return
    if not after_path.is_file():
        fail(f"post-upgrade parameter snapshot missing: {after_path}")
        return
    before = json.loads(snapshot_path.read_text(encoding="utf-8"))
    after = json.loads(after_path.read_text(encoding="utf-8"))
    if not isinstance(before, dict) or not isinstance(after, dict):
        fail("pre/post-upgrade parameter payload is not an object")
        return

    preserved = (
        "min_difficulty",
        "pow_message_window",
        "pow_message_limit",
        "pow_calm_period_definition",
        "pow_calm_sequence_threshold",
        "mint_interval",
        "mint_quantity",
        "block_hash_window",
        "pow_difficulty_allowance",
        "max_username_size",
        "min_username_size",
        "mint_dynamic_credit_cap",
        "mint_dynamic_split",
        "subscription_period",
        "relay_min_gas_price",
        "relay_max_gas_fee",
        "max_envelope_age",
        "pow_difficulty_step",
        "award_configs",
        "mint_floor_split",
    )
    aliases = {
        "max_community_size": ("max_community_size", "max_topic_size"),
        "min_community_size": ("min_community_size", "min_topic_size"),
    }
    mismatches = []
    for key in preserved:
        if key not in before or key not in after:
            mismatches.append(f"{key}: missing before={key in before} after={key in after}")
        elif before[key] != after[key]:
            mismatches.append(f"{key}: before={before[key]!r} after={after[key]!r}")
    for after_key, before_keys in aliases.items():
        before_key = next((key for key in before_keys if key in before), None)
        if before_key is None or after_key not in after:
            mismatches.append(
                f"{after_key}: missing before aliases={before_keys!r} after={after_key in after}"
            )
        elif before[before_key] != after[after_key]:
            mismatches.append(
                f"{after_key}: before {before_key}={before[before_key]!r} "
                f"after={after[after_key]!r}"
            )
    if mismatches:
        fail("governed v1.38 params changed during migration: " + "; ".join(mismatches))
    else:
        ok(f"all {len(preserved) + len(aliases)} retained governed params survived migration")


def check_params_reach_backend() -> None:
    db_url = os.environ.get("INDEXER_DB_URL", "").strip()
    if not db_url:
        fail("INDEXER_DB_URL missing from deployed environment")
        return
    import psycopg

    with psycopg.connect(db_url, connect_timeout=10) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT value FROM chain_stats WHERE key = 'chain_params'")
            row = cursor.fetchone()
    if row is None or not row[0]:
        fail("indexer chain_stats has no chain_params row")
        return
    stored = row[0] if isinstance(row[0], dict) else json.loads(row[0])
    if str(stored.get("subscription_reserve_bps", "1")) != "0":
        fail(f"indexed subscription_reserve_bps={stored.get('subscription_reserve_bps')!r}")
        return
    if str(stored.get("subscription_creator_bps")) != "5000":
        fail(f"indexed subscription_creator_bps={stored.get('subscription_creator_bps')!r}")
        return
    if str(stored.get("creator_epoch_seconds")) != "21600":
        fail(f"indexed creator_epoch_seconds={stored.get('creator_epoch_seconds')!r}")
        return
    ok("indexed chain_params carries v1.39.0 subscription and creator epoch params")


def check_legacy_mobile_routes() -> None:
    read_checks = (
        ("/api/get_topics?limit=1", lambda body: isinstance(body.get("topics"), list), "topics list"),
        ("/api/search_topics?q=ve&limit=1", lambda body: isinstance(body.get("topics"), list), "topic search"),
        ("/api/get_agents", lambda body: body == {"agents": []}, "disabled Agent directory"),
        (
            "/api/get_invite_codes",
            lambda body: body == {"codes": [], "total": 0, "available": 0},
            "empty invite codes",
        ),
        (
            "/api/rewards/summary",
            lambda body: body
            == {
                "disabled": True,
                "suspended": False,
                "daily_quests": [],
                "flash_quest": None,
                "pending_rewards": [],
                "seconds_until_reset": 0,
                "reward_multiplier": 1,
                "total_mirage": 0,
                "total_mirage_after_multiplier": 0,
                "pending_invite_codes": 0,
                "claiming_available": False,
                "debug": False,
            },
            "disabled rewards summary",
        ),
        (
            "/api/rewards/achievements",
            lambda body: body == {"achievements": []},
            "empty achievements",
        ),
        (
            "/api/referrals/precheck",
            lambda body: body == {"valid": False, "available": 0, "error": "referrals_retired"},
            "disabled referral precheck",
        ),
        (
            "/api/referrals/summary",
            lambda body: body
            == {
                "referrals": [],
                "total": 0,
                "period_start": 0,
                "period_end": 0,
                "limit": 50,
                "offset": 0,
                "has_more": False,
            },
            "empty referral summary",
        ),
        (
            "/api/referral/stats",
            lambda body: body
            == {
                "pending_total": 0,
                "paid_total": 0,
                "total_referrals": 0,
                "referral_tree": {"address": "", "children": []},
                "last_update_ts": 0,
                "next_update_ts": 0,
            },
            "empty referral stats",
        ),
    )
    for path, valid, label in read_checks:
        status, payload = http_json_response(f"{BACKEND}{path}")
        body = payload if isinstance(payload, dict) else {}
        if status == 200 and valid(body):
            ok(f"legacy mobile {label} available")
        else:
            fail(f"legacy mobile {label} status={status} payload={payload}")

    for path in (
        "/api/core/follow_topic",
        "/api/core/unfollow_topic",
        "/api/core/block_topic",
        "/api/core/unblock_topic",
    ):
        status, payload = http_json_response(f"{BACKEND}{path}", "POST", {})
        if status == 400 and not (isinstance(payload, dict) and payload.get("retired")):
            ok(f"POST {path} routed to validation without broadcast")
        else:
            fail(f"POST {path} status={status} payload={payload}, expected validation error")


def check_still_retired_routes() -> None:
    routes = (
        ("POST", "/api/core/enable_agent"),
        ("POST", "/api/core/disable_agent"),
        ("POST", "/api/core/set_agents"),
        ("POST", "/api/core/annotate"),
        ("POST", "/api/rewards/claim"),
        ("POST", "/api/admin/rewards/payout"),
        ("POST", "/api/referrals/precheck_opt_in"),
        ("POST", "/api/quests/claim"),
        ("POST", "/api/validate_invite_code"),
        ("POST", "/api/core/create_community"),
        ("POST", "/api/core/set_community_metadata"),
        ("POST", "/api/core/transfer_community"),
    )
    for method, path in routes:
        status, payload = http_json_response(f"{BACKEND}{path}", method, {})
        expected_label = path.rsplit("/", 1)[-1]
        retired_label = payload.get("retired") if isinstance(payload, dict) else None
        if status == 410 and retired_label == expected_label:
            ok(f"{method} {path} -> 410 retired={retired_label}")
        else:
            fail(
                f"{method} {path} status={status} retired={retired_label!r}, "
                f"expected 410 retired={expected_label!r}"
            )


def check_migration_state() -> None:
    db_url = os.environ.get("INDEXER_DB_URL", "").strip()
    if not db_url:
        fail("INDEXER_DB_URL missing from deployed environment")
        return
    import psycopg

    expected = (
        "v1.39.0_communities",
        "v1.39.0_curator_defined_communities",
        "v1.39.0_curator_tags",
        "v1.39.0_legacy_post_community",
        "v1.39.0_legacy_vote_standing",
        "v1.39.0_quota_admins",
        "v1.39.0_quota_paid_backfill",
        "v1.39.0_rename_topic_pref_type",
        "v1.39.0_repair_resurrected_posts",
        "v1.39.0_standing_rebuild",
        "v1.39.0_thread_lock_windows",
        "v1.39.0_was_subscriber_at_creation",
    )
    marker_keys = [f"migration_{key}" for key in expected]
    checksum_keys = [f"migration_{key}_checksum" for key in expected]
    with psycopg.connect(db_url, connect_timeout=10) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT key, value FROM meta WHERE key = ANY(%s)",
                (marker_keys + checksum_keys + ["migration_checksum_repin"],),
            )
            meta = {str(key): value for key, value in cursor.fetchall()}
            cursor.execute(
                "SELECT count(*) FROM profiles "
                "WHERE level = 10 OR reserve_funds <> 0 "
                "OR (level = 1 AND effective_paid = FALSE) "
                "OR (level = 0 AND effective_paid = TRUE)"
            )
            invalid_profiles = int(cursor.fetchone()[0])
            cursor.execute("SELECT count(*) FROM preferences WHERE pref_type = 'topic'")
            stale_preferences = int(cursor.fetchone()[0])
            cursor.execute(
                "SELECT tablename FROM pg_tables "
                "WHERE schemaname = 'public' "
                "AND tablename = ANY(%s)",
                (["topic_preferences", "topic_content_stats", "user_topic_stats"],),
            )
            stale_tables = sorted(str(row[0]) for row in cursor.fetchall())

    missing_markers = [key for key in marker_keys if not meta.get(key)]
    missing_checksums = [key for key in checksum_keys if not meta.get(key)]
    if missing_markers or missing_checksums:
        fail(
            f"v1.39 migration metadata incomplete: markers={missing_markers} "
            f"checksums={missing_checksums}"
        )
    else:
        ok(f"all {len(expected)} v1.39 indexer migrations and checksums are recorded")
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from indexer.migrations import _REPIN_RELEASE

    if meta.get("migration_checksum_repin") == _REPIN_RELEASE:
        ok(f"migration checksum repin marker={_REPIN_RELEASE}")
    else:
        fail(
            f"migration checksum repin marker={meta.get('migration_checksum_repin')!r} "
            f"expected={_REPIN_RELEASE!r}"
        )
    if invalid_profiles:
        fail(f"{invalid_profiles} profile(s) retain invalid Agent/reserve/subscriber state")
    else:
        ok("profiles contain no Agent, relay reserve, or inconsistent subscriber state")
    if stale_preferences or stale_tables:
        fail(
            f"legacy topic storage remains: pref_type rows={stale_preferences} "
            f"tables={stale_tables}"
        )
    else:
        ok("topic preferences and renamed topic tables were fully retired")


def check_retired_financial_state() -> None:
    db_url = os.environ.get("BACKEND_DB_URL", "").strip()
    if not db_url:
        fail("BACKEND_DB_URL missing from deployed environment")
        return
    import psycopg

    from web.backend.db import LEGACY_FINANCIAL_CHECKS, legacy_financial_evidence

    snapshot_path = STATUS_DIR / "pre_upgrade_financial.json"
    with psycopg.connect(db_url, connect_timeout=10) as connection:
        with connection.cursor() as cursor:
            present_counts = legacy_financial_evidence(cursor)
    required_tables = {table for table, _predicate in LEGACY_FINANCIAL_CHECKS}
    missing = sorted(required_tables - set(present_counts))
    if missing:
        fail(f"retired financial evidence tables were dropped: {missing}")
        return
    after = {table: int(present_counts.get(table, 0)) for table in required_tables}
    if snapshot_path.is_file():
        before = json.loads(snapshot_path.read_text(encoding="utf-8"))
        lost = [
            f"{table}: before={before.get(table, 0)} after={after[table]}"
            for table in required_tables
            if int(after[table]) < int(before.get(table, 0) or 0)
        ]
        if lost:
            fail("retired financial evidence shrank during upgrade: " + "; ".join(lost))
            return
        ok(
            "retired reward evidence preserved: "
            + ", ".join(f"{table}={after[table]}" for table in sorted(after))
        )
        return
    ok(
        "retired reward evidence tables retained: "
        + ", ".join(f"{table}={after[table]}" for table in sorted(after))
    )


def check_open_community_contract() -> None:
    slug = "v139-open-community-verification"
    community = http_json(f"{BACKEND}/api/communities/{slug}")
    if community.get("community") == slug:
        ok("valid unregistered community slug resolves")
    else:
        fail(f"community detail returned unexpected payload: {community}")
    retired = {
        "claimed",
        "title",
        "description",
        "founder",
        "original_founder",
        "current_founder",
        "original_team_id",
        "current_default_team_id",
        "default_count",
    }
    present = sorted(retired.intersection(community))
    if present:
        fail(f"retired community ownership fields remain: {present}")
    else:
        ok("community detail has no ownership or metadata fields")


def check_curation_tag_schema() -> None:
    """The tag schema has to exist on a real deploy, not just in a migration file.

    Without the column and the table the backend's tag precedence silently
    degrades to the author's own tag, which is exactly the failure the feature
    exists to prevent, and nothing else would surface it.
    """
    db_url = os.environ.get("INDEXER_DB_URL", "").strip()
    if not db_url:
        fail("INDEXER_DB_URL missing from deployed environment")
        return
    import psycopg

    with psycopg.connect(db_url, connect_timeout=10) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM information_schema.columns " "WHERE table_name='curation_teams' AND column_name='tag'"
            )
            has_column = cursor.fetchone() is not None
            cursor.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name='curation_post_tags' ORDER BY column_name"
            )
            tag_columns = {str(row[0]) for row in cursor.fetchall()}
            cursor.execute(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name='curation_locks' AND column_name='lock_windows'"
            )
            has_lock_windows = cursor.fetchone() is not None
    if has_column:
        ok("curation_teams.tag present")
    else:
        fail("curation_teams.tag missing")
    expected = {"community", "team_id", "target_txhash", "tag", "actor", "updated_height"}
    if expected.issubset(tag_columns):
        ok("curation_post_tags present")
    else:
        fail(f"curation_post_tags missing columns: {sorted(expected - tag_columns)}")
    # The chain keeps only the cut-off of the lock that is open now, so without
    # this column the closed windows have nowhere to live and unlocking a thread
    # republishes every reply the lock hid.
    if has_lock_windows:
        ok("curation_locks.lock_windows present")
    else:
        fail("curation_locks.lock_windows missing; unlocking would republish locked replies")

    for path in ("/api/core/set_curation_tag", "/api/core/set_curation_post_tag"):
        status = http_status(f"{BACKEND}{path}")
        if status == 404:
            fail(f"{path} is not registered")
        else:
            ok(f"{path} registered (status={status})")


def check_deleted_posts_stay_deleted() -> None:
    """A post the chain reports deleted must not be live in the index.

    `deleted_height` is only ever written from the chain's own PostMetadata, so a
    row carrying one while `deleted` is false is the projection contradicting the
    chain: a post its author removed is back in every feed. MsgEdit used to cause
    exactly that, because it re-upserted the post without the stored flag. The
    v1.39.0 repair migration restores these rows, so a surviving one means either
    the migration did not run or something reintroduced the resurrection.
    """
    db_url = os.environ.get("INDEXER_DB_URL", "").strip()
    if not db_url:
        fail("INDEXER_DB_URL missing from deployed environment")
        return
    import psycopg

    with psycopg.connect(db_url, connect_timeout=10) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM posts WHERE COALESCE(deleted, FALSE) = FALSE AND deleted_height IS NOT NULL"
            )
            revived = int(cursor.fetchone()[0])
    if revived:
        fail(f"{revived} post(s) the chain reports deleted are live in the index")
    else:
        ok("no deleted post was resurrected by an edit")


def check_legacy_history_reachable() -> None:
    """The pre-upgrade history must survive the upgrade in the scope the UI uses.

    Every post made before v1.39 is protocol 0, and the web client only ever
    requests scope=current. If current scope drops protocol-0 posts the entire
    archive silently disappears with no navigation path to it, and every other
    check here still passes because the rows are present in the database.
    """
    db_url = os.environ.get("INDEXER_DB_URL", "").strip()
    if not db_url:
        fail("INDEXER_DB_URL missing from deployed environment")
        return
    import psycopg

    with psycopg.connect(db_url, connect_timeout=10) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM posts WHERE protocol_version = 0 AND NOT deleted")
            legacy_rows = int(cursor.fetchone()[0])
            cursor.execute(
                "SELECT count(*) FROM posts WHERE protocol_version = 0 AND NOT deleted "
                "AND target IS NOT NULL AND target <> '' AND (community IS NULL OR community = '')"
            )
            orphan_comments = int(cursor.fetchone()[0])
            cursor.execute(
                "SELECT LOWER(community), LOWER(txhash) "
                "FROM posts p "
                "WHERE protocol_version = 0 AND NOT deleted "
                "AND COALESCE(target, '') = '' AND COALESCE(community, '') <> '' "
                "AND NOT EXISTS ("
                "  SELECT 1 FROM posts newer "
                "  WHERE LOWER(newer.community) = LOWER(p.community) "
                "  AND newer.protocol_version <> 0 AND NOT newer.deleted"
                ") "
                "ORDER BY created_at DESC LIMIT 1"
            )
            legacy_only_sample = cursor.fetchone()

    if not legacy_rows:
        ok("no legacy posts on this chain")
        return

    # A chain with history must not serve an empty default feed.
    feed = http_json(f"{BACKEND}/api/get_posts?scope=current&limit=5")
    served = feed.get("posts") if isinstance(feed, dict) else None
    if not served:
        fail(f"{legacy_rows} legacy posts exist but scope=current returns an empty feed")
    else:
        ok(f"scope=current serves posts with {legacy_rows} legacy rows present")

    # The count is over every eligible root, so if current scope were still
    # protocol-gated the pool would collapse to the handful of new posts.
    total = feed.get("total") if isinstance(feed, dict) else 0
    if not isinstance(total, int) or total < 1:
        fail(f"scope=current reports no eligible posts (total={total!r})")
    else:
        ok(f"scope=current candidate pool is {total} posts")

    legacy_feed = http_json(f"{BACKEND}/api/get_posts?scope=legacy&lens=raw&limit=5")
    legacy_served = legacy_feed.get("posts") if isinstance(legacy_feed, dict) else None
    versions = [post.get("protocol_version") for post in (legacy_served or [])]
    print(f"  DEBUG  scope=legacy count={len(versions)} protocol_version={versions!r}")
    if legacy_served and all(int(post.get("protocol_version", -1)) == 0 for post in legacy_served):
        ok("scope=legacy serves historical protocol-0 posts")
    else:
        fail(
            f"scope=legacy did not return protocol-0 history: "
            f"count={len(legacy_served or [])} protocol_version={versions!r}"
        )

    if legacy_only_sample:
        community, txhash = legacy_only_sample
        query = urllib.parse.urlencode(
            {
                "scope": "current",
                "lens": "raw",
                "community": community,
                "by": "newest",
                "limit": 100,
            }
        )
        community_feed = http_json(f"{BACKEND}/api/get_posts?{query}")
        current_ids = {
            str(post.get("post_id") or post.get("txhash") or "").lower()
            for post in (community_feed.get("posts") or [])
        }
        if txhash in current_ids:
            ok(f"scope=current includes protocol-0 history for [{community}]")
        else:
            fail(f"scope=current hid protocol-0 post {txhash} in [{community}]")
    else:
        ok("no legacy-only community available for unified current-scope probe")

    # The backfill is what puts legacy comments back into community feeds.
    if orphan_comments > legacy_rows // 100:
        fail(f"{orphan_comments} legacy comments still have no community (backfill did not run)")
    else:
        ok(f"legacy comment community backfill applied ({orphan_comments} unresolved)")


def comet_height() -> int:
    return int(http_json(f"{RPC}/status")["result"]["sync_info"]["latest_block_height"])


def check_progress() -> None:
    first = comet_height()
    time.sleep(8)
    second = comet_height()
    if second > first:
        ok(f"chain advancing past the halt: {first} -> {second}")
    else:
        fail(f"chain stalled at {second}")

    db_url = os.environ.get("INDEXER_DB_URL", "").strip()
    if not db_url:
        fail("INDEXER_DB_URL missing from deployed environment")
        return
    import psycopg

    def indexed_height() -> int:
        with psycopg.connect(db_url, connect_timeout=10) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT value FROM meta WHERE key = 'last_height'")
                row = cursor.fetchone()
        if row is None:
            raise RuntimeError("indexer meta.last_height is missing")
        return int(row[0])

    indexed_first = indexed_height()
    time.sleep(10)
    indexed_second = indexed_height()
    if indexed_second > indexed_first:
        ok(f"indexer advancing: {indexed_first} -> {indexed_second}")
    else:
        fail(f"indexer stalled at {indexed_second}")


def main() -> int:
    print(f"verify_upgrade.py for {VERSION} (consensus change: communities, no Agent, no relay reserve)")
    checks = (
        check_versions,
        check_upgrade_applied,
        check_params,
        check_preserved_params,
        check_params_reach_backend,
        check_legacy_mobile_routes,
        check_still_retired_routes,
        check_migration_state,
        check_retired_financial_state,
        check_open_community_contract,
        check_curation_tag_schema,
        check_deleted_posts_stay_deleted,
        check_legacy_history_reachable,
        check_progress,
    )
    for check in checks:
        try:
            check()
        except Exception as error:
            fail(f"{check.__name__}: {error}")
    print(f"\nResult: {passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
