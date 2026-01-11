#!/usr/bin/env python3
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import urllib.request


def _http_get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "mirage-verify/1.0"})
    with urllib.request.urlopen(req, timeout=5) as resp:
        data = resp.read()
    return json.loads(data.decode("utf-8"))


def _find_miraged() -> str:
    candidates = [
        "/opt/mirage/blockchain/miraged",  # inside container
        str(Path(__file__).resolve().parents[1] / "blockchain" / "miraged"),  # repo checkout with built binary
        "miraged",
    ]
    for c in candidates:
        if c == "miraged":
            return c
        if os.path.exists(c) and os.access(c, os.X_OK):
            return c
    return "miraged"


def _run_json(cmd: list[str]) -> dict:
    p = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if p.returncode != 0:
        raise RuntimeError(f"command failed ({p.returncode}): {' '.join(cmd)}\n{p.stderr}".strip())
    return json.loads(p.stdout)


def _as_int(v) -> int:
    if isinstance(v, int):
        return v
    if isinstance(v, str):
        v = v.strip()
        if v.isdigit():
            return int(v)
    if isinstance(v, float):
        return int(v)
    raise ValueError(f"not an int: {v!r}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify v1.7.7-tier-pricing upgrade applied correctly")
    parser.add_argument("--node", default="http://127.0.0.1:26657", help="CometBFT RPC endpoint (http URL)")
    args = parser.parse_args()

    rpc = args.node.rstrip("/")
    miraged = _find_miraged()

    failures: list[str] = []

    # 1) RPC reachable
    try:
        status = _http_get_json(f"{rpc}/status")
        latest = status.get("result", {}).get("sync_info", {}).get("latest_block_height", "")
        catching_up = status.get("result", {}).get("sync_info", {}).get("catching_up", None)
        print(f"[OK] RPC reachable: height={latest} catching_up={catching_up}")
    except Exception as e:
        failures.append(f"RPC not reachable at {rpc}: {e}")

    # 2) On-chain params match expected (subscription_period + tier fees)
    try:
        params = _run_json([miraged, "q", "core", "params", "--node", rpc, "-o", "json"])
        p = params.get("params", params)  # tolerate different wrappers
        sub_period = _as_int(p.get("subscription_period"))
        if sub_period != 43200:
            failures.append(f"subscription_period expected 43200, got {sub_period}")
        else:
            print("[OK] subscription_period = 43200")

        tiers = p.get("tiers") or []
        if len(tiers) < 4:
            failures.append(f"tiers expected >= 4 entries, got {len(tiers)}")
        else:
            t1 = _as_int(tiers[1].get("period_fee"))
            t2 = _as_int(tiers[2].get("period_fee"))
            t3 = _as_int(tiers[3].get("period_fee"))
            if t1 != 10_000_000:
                failures.append(f"tier1 period_fee expected 10000000, got {t1}")
            if t2 != 20_000_000:
                failures.append(f"tier2 period_fee expected 20000000, got {t2}")
            if t3 != 30_000_000:
                failures.append(f"tier3 period_fee expected 30000000, got {t3}")
            if not failures:
                print("[OK] tier fees = 10/20/30 MIRAGE per 30 days (umirage: 10/20/30 million)")
    except Exception as e:
        failures.append(f"failed to query/parse core params: {e}")

    # 3) No Go-rotated logs directory
    data_dir = Path.home() / ".mirage"
    main_logs = data_dir / "main" / "logs"
    if main_logs.exists():
        failures.append(f"unexpected Go logs dir exists: {main_logs}")
    else:
        print(f"[OK] Go logs dir absent: {main_logs}")

    # 4) Cronolog output exists (best-effort)
    utc_day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    cronolog_file = data_dir / "logs" / "node" / f"miraged-{utc_day}.log"
    if not cronolog_file.exists():
        failures.append(f"expected cronolog file missing: {cronolog_file}")
    else:
        size = cronolog_file.stat().st_size
        if size <= 0:
            failures.append(f"cronolog file empty: {cronolog_file}")
        else:
            print(f"[OK] cronolog file present: {cronolog_file} ({size} bytes)")

    if failures:
        print("\nFAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1

    print("\nSUCCESS: v1.7.7-tier-pricing verification passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

