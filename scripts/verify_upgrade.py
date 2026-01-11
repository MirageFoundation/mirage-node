#!/usr/bin/env python3
"""
Verify Mirage Node Upgrade (v1.7.8+)

Checks:
1. Node Health: RPC reachable, not catching up (optional warn)
2. Chain State: Tier pricing (10/20/30 MIRAGE) & subscription period (30 days)
3. Directory Structure:
   - ~/.mirage/node/ exists (new home)
   - ~/.mirage/postgres/ exists (new postgres location)
   - ~/.mirage/main/ is absent OR is a symlink (migration done)
   - ~/.mirage/node/logs/ is absent (Go log rotation removed)
4. Logging: Cronolog is writing to ~/.mirage/logs/node/miraged-YYYY-MM-DD.log
"""

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
        str(Path(__file__).resolve().parents[1] / "blockchain" / "miraged"),  # repo checkout
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
    parser = argparse.ArgumentParser(description="Verify Mirage Node Upgrade Status")
    parser.add_argument("--node", default="http://127.0.0.1:26657", help="CometBFT RPC endpoint")
    args = parser.parse_args()

    rpc = args.node.rstrip("/")
    miraged = _find_miraged()
    home_dir = Path.home() / ".mirage"
    
    failures: list[str] = []
    warnings: list[str] = []

    print(f"=== Verifying Upgrade Status ({datetime.now().isoformat()}) ===\n")

    # 1. Directory Structure (v1.7.8 restructuring)
    print("-> Checking directory structure...")
    node_dir = home_dir / "node"
    main_dir = home_dir / "main"
    postgres_dir = home_dir / "postgres"

    if node_dir.is_dir() and not node_dir.is_symlink():
        print("   [OK] ~/.mirage/node/ exists")
    else:
        failures.append("~/.mirage/node/ directory missing or is symlink")

    if postgres_dir.is_dir():
        print("   [OK] ~/.mirage/postgres/ exists")
    else:
        failures.append("~/.mirage/postgres/ directory missing")

    if not main_dir.exists():
        print("   [OK] ~/.mirage/main/ is absent (clean migration)")
    elif main_dir.is_symlink():
        target = main_dir.readlink()
        print(f"   [OK] ~/.mirage/main/ is a symlink -> {target}")
    else:
        failures.append("~/.mirage/main/ exists and is NOT a symlink (migration incomplete?)")

    # 2. Go Logs Removal (v1.7.7 cleanup)
    old_logs = node_dir / "logs"
    if old_logs.exists():
        failures.append(f"Unexpected Go logs dir exists: {old_logs}")
    else:
        print("   [OK] Go logs dir absent (cleanup successful)")

    # 3. Cronolog Logging
    print("\n-> Checking logging...")
    utc_day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    cronolog_file = home_dir / "logs" / "node" / f"miraged-{utc_day}.log"
    if not cronolog_file.exists():
        failures.append(f"Expected cronolog file missing: {cronolog_file}")
    else:
        size = cronolog_file.stat().st_size
        if size > 0:
            print(f"   [OK] Log file present and active: {cronolog_file.name} ({size} bytes)")
        else:
            failures.append(f"Cronolog file exists but is empty: {cronolog_file}")

    # 4. Chain State & Health
    print("\n-> Checking chain state...")
    try:
        status = _http_get_json(f"{rpc}/status")
        latest = status.get("result", {}).get("sync_info", {}).get("latest_block_height", "")
        catching = status.get("result", {}).get("sync_info", {}).get("catching_up", False)
        
        print(f"   [OK] RPC reachable (Height: {latest})")
        if catching:
            warnings.append("Node is catching up (syncing)")
        
        # Check params
        params = _run_json([miraged, "q", "core", "params", "--node", rpc, "-o", "json"])
        p = params.get("params", params)
        
        # Subscription period
        sub_period = _as_int(p.get("subscription_period"))
        if sub_period == 43200:
            print("   [OK] Subscription period: 43200 (30 days)")
        else:
            failures.append(f"subscription_period expected 43200, got {sub_period}")

        # Tier fees
        tiers = p.get("tiers") or []
        if len(tiers) >= 4:
            t1 = _as_int(tiers[1].get("period_fee"))
            t2 = _as_int(tiers[2].get("period_fee"))
            t3 = _as_int(tiers[3].get("period_fee"))
            
            if t1 == 10_000_000 and t2 == 20_000_000 and t3 == 30_000_000:
                print("   [OK] Tier fees: 10/20/30 MIRAGE")
            else:
                failures.append(f"Tier fees mismatch: {t1}/{t2}/{t3} (expected 10M/20M/30M)")
        else:
            failures.append(f"Tiers config incomplete (len={len(tiers)})")

    except Exception as e:
        failures.append(f"Chain check failed: {e}")

    print("\n=== Summary ===")
    if warnings:
        for w in warnings:
            print(f"[WARN] {w}")
    
    if failures:
        print("[FAIL] Verification failed with errors:")
        for f in failures:
            print(f"  - {f}")
        return 1
    
    print("[PASS] All checks passed successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
