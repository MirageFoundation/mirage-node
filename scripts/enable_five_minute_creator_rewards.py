#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROPOSAL = ROOT / "scripts" / "proposals" / "proposal_enable_five_minute_creator_rewards.json"
RESET_COMMAND = "conda activate mirage-node && python scripts/reset_local_testnet.py --latest"
PARAMS_URL = "http://127.0.0.1:1317/mirage/core/v1/params"
LIABILITY_URL = "http://127.0.0.1:1317/mirage/core/v1/creator/liability"


def fail(message: str) -> None:
    raise RuntimeError(f"{message}\nReset first with: {RESET_COMMAND}")


def run(command: list[str]) -> str:
    result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"command failed: {' '.join(command)}\n{detail}")
    return result.stdout.strip()


def get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=10) as response:
        return json.load(response)


def verify_local_container() -> None:
    if run(["docker", "inspect", "--format", "{{.State.Running}}", "mirage"]) != "true":
        raise RuntimeError("local mirage container is not running")
    hostname = run(["docker", "exec", "mirage", "hostname"])
    if hostname != "testnet":
        raise RuntimeError(f"refusing non-local container hostname: {hostname!r}")


def verify_empty_creator_state() -> None:
    params = get_json(PARAMS_URL).get("params") or {}
    if int(params.get("creator_epoch_seconds", 0)) != 86400:
        fail("creator_epoch_seconds is not the clean-reset daily value")

    liability = get_json(LIABILITY_URL)
    if int(liability.get("liability", "0")) != 0:
        fail("creator reward liability is not empty")

    query = (
        "SELECT "
        "(SELECT COUNT(*) FROM creator_epochs) + "
        "(SELECT COUNT(*) FROM creator_accruals) + "
        "(SELECT COUNT(*) FROM subscription_tranches);"
    )
    count = run(
        [
            "docker",
            "exec",
            "mirage",
            "bash",
            "-lc",
            'set -a; for f in /root/.mirage/env/*.env; do . "$f"; done; ' 'set +a; psql "$INDEXER_DB_URL" -Atqc "$1"',
            "five-minute-reward-check",
            query,
        ]
    )
    if int(count) != 0:
        fail(f"creator reward projection contains {count} existing rows")


def verify_applied() -> None:
    expected = {
        "creator_epoch_seconds": 300,
        "subscription_period": 60,
        "subscription_early_renewal_days": 0,
        "max_subscription_periods_per_purchase": 1,
    }
    params = get_json(PARAMS_URL).get("params") or {}
    actual = {key: int(params.get(key, -1)) for key in expected}
    if actual != expected:
        raise RuntimeError(f"proposal did not apply expected params: {actual}")


def main() -> int:
    verify_local_container()
    verify_empty_creator_state()
    print("Local creator reward state is empty; submitting guarded proposal.")
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "submit_proposal.py"),
            "local",
            str(PROPOSAL),
            "--no-confirm",
        ],
        cwd=ROOT,
    )
    if result.returncode != 0:
        return result.returncode
    verify_applied()
    now = int(time.time())
    next_boundary = ((now // 300) + 1) * 300
    print(f"Five-minute creator rewards enabled. Next UTC boundary: {next_boundary}.")
    print("Returning to daily rewards requires a local reset.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
