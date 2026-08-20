#!/usr/bin/env python3
"""Post-deploy verification for the v1.38.0 mint floor upgrade.

v1.38.0 is a consensus change: the mint interval splits 20% equally across
bonded validators, 10% by relay credits alone, and 70% by stake. The checks here
prove the governed plan actually applied and that the new split is the one the
chain and the backend are running on. Nothing else belongs in this file — the
release-time policy of the signed manifest is release_verify.py's job.
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

VERSION = "v1.38.0"
UPGRADE_NAME = "v1.38.0"
WANT_FLOOR_SPLIT = 0.20
WANT_DYNAMIC_SPLIT = 0.10
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

    # v1.36.0 shipped a binary reporting v1.36.0-1-gd783da08 with every suite
    # green, because the tag had moved onto an existing commit. This is the check
    # that caught it.
    output = run([str(ROOT / "blockchain/bin/miraged"), "version", "--long"])
    reported = next((line.split(":", 1)[1].strip() for line in output.splitlines() if line.startswith("version:")), "")
    if reported.lstrip("v") == VERSION.lstrip("v"):
        ok(f"chain binary version={reported}")
    else:
        fail(f"chain binary version={reported!r}, expected {VERSION}")


def check_upgrade_applied() -> None:
    """The governed plan must have applied and cleared, not merely been scheduled."""
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


def check_mint_split_params() -> None:
    """The handler must have written the live split; a wrong value mints wrong forever."""
    params = http_json(f"{REST}/mirage/core/v1/params")["params"]

    floor = float(params["mint_floor_split"])
    dynamic = float(params["mint_dynamic_split"])
    if abs(floor - WANT_FLOOR_SPLIT) < 1e-9:
        ok(f"mint_floor_split={floor}")
    else:
        fail(f"mint_floor_split={floor}, expected {WANT_FLOOR_SPLIT}")
    if abs(dynamic - WANT_DYNAMIC_SPLIT) < 1e-9:
        ok(f"mint_dynamic_split={dynamic}")
    else:
        fail(f"mint_dynamic_split={dynamic}, expected {WANT_DYNAMIC_SPLIT}")

    # The stake pool is the remainder, so a sum above 1 would mint past
    # mint_quantity on every interval.
    if floor + dynamic <= 1:
        ok(f"stake pool is {round((1 - floor - dynamic) * 100, 4)}% of each interval")
    else:
        fail(f"mint_floor_split + mint_dynamic_split = {floor + dynamic} exceeds 1")

    # The upgrade changes how the mint is divided, not how much is minted.
    interval = int(params["mint_interval"])
    quantity = int(params["mint_quantity"])
    if interval > 0 and quantity > 0:
        ok(f"mint_interval={interval} mint_quantity={quantity} umirage")
    else:
        fail(f"mint_interval={interval} mint_quantity={quantity} must both be positive")


def check_params_reach_backend() -> None:
    """The backend reads params from the indexer DB and fails hard on a missing float.

    mint_floor_split is a new field, so if the indexer's descriptor did not pick
    it up the backend would refuse to start. Assert it landed in the row the
    backend actually reads rather than inferring it from the chain query.
    """
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
    if "mint_floor_split" not in stored:
        fail(f"indexed chain_params has no mint_floor_split: {sorted(stored)[:12]}...")
        return
    indexed = float(stored["mint_floor_split"])
    if abs(indexed - WANT_FLOOR_SPLIT) < 1e-9:
        ok(f"indexed chain_params carries mint_floor_split={indexed}")
    else:
        fail(f"indexed mint_floor_split={indexed}, expected {WANT_FLOOR_SPLIT}")


def check_backend_mint_split() -> None:
    """The running backend process must refresh to the indexed upgrade values."""
    deadline = time.monotonic() + 90
    last = None
    while time.monotonic() < deadline:
        try:
            last = http_json(f"{BACKEND}/api/get_chain_config")
            floor = float(last["mint_floor_split"])
            dynamic = float(last["mint_dynamic_split"])
            if abs(floor - WANT_FLOOR_SPLIT) < 1e-9 and abs(dynamic - WANT_DYNAMIC_SPLIT) < 1e-9:
                ok(f"backend reports mint split floor={floor} dynamic={dynamic}")
                return
        except Exception as error:
            last = {"error": str(error)}
        time.sleep(5)
    fail(f"backend did not report floor={WANT_FLOOR_SPLIT} dynamic={WANT_DYNAMIC_SPLIT}: {last}")


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
    print(f"verify_upgrade.py for {VERSION} (consensus change: mint splits 20% floor / 10% work / 70% stake)")
    checks = (
        check_versions,
        check_upgrade_applied,
        check_mint_split_params,
        check_params_reach_backend,
        check_backend_mint_split,
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
