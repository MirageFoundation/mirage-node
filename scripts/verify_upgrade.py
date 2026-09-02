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


def http_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as response:
        return json.loads(response.read().decode())


def http_status(url: str) -> int:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return int(response.status)
    except urllib.error.HTTPError as e:
        return int(e.code)


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


def check_gone_routes() -> None:
    for path in (
        "/api/get_topics",
        "/api/core/follow_topic",
        "/api/core/unfollow_topic",
        "/api/core/block_topic",
        "/api/core/unblock_topic",
        "/api/core/enable_agent",
        "/api/core/disable_agent",
        "/api/core/set_agents",
        "/api/core/create_community",
        "/api/core/set_community_metadata",
        "/api/core/transfer_community",
    ):
        status = http_status(f"{BACKEND}{path}")
        if status == 410:
            ok(f"{path} -> 410")
        else:
            fail(f"{path} status={status}, expected 410")


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
        check_params_reach_backend,
        check_gone_routes,
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
