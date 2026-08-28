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
    # The upgrade seeds 250, but governance owns the value from then on and the
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
    if len(tiers) == 2:
        ok("two subscription tiers")
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
    if desc_limit == 4000:
        ok("max_curation_team_description_length=4000")
    else:
        fail(f"max_curation_team_description_length={params.get('max_curation_team_description_length')!r}")


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
    ok("indexed chain_params carries v1.39.0 subscription params")


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
