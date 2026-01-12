#!/usr/bin/env python3
"""
Verify Mirage Node Upgrade (v1.8.0-economics)

Checks:
1. Node Health: RPC reachable, not catching up (optional warn)
2. Economics Parameters (v1.8.0):
   - RelayMinGasPrice: 5000 (umirage per gas)
   - RelayMaxGasFee: 500,000,000 (500 MIRAGE cap)
   - SubscriptionReservePercent: 80%
   - MintQuantity: 350,000,000 (350 MIRAGE per 10min)
   - Tier fees: 100B/200B/300B umirage ($1/$2/$3 per month)
3. Governance Parameters:
   - min_deposit: 500B umirage ($5)
   - expedited_min_deposit: 1T umirage ($10)
4. Node Config:
   - minimum-gas-prices = "5000umirage" in app.toml
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
    parser = argparse.ArgumentParser(description="Verify v1.8.0-economics Upgrade Status")
    parser.add_argument("--node", default="http://127.0.0.1:26657", help="CometBFT RPC endpoint")
    parser.add_argument("--home", default=str(Path.home() / ".mirage"), help="Mirage home directory")
    args = parser.parse_args()

    rpc = args.node.rstrip("/")
    miraged = _find_miraged()
    home_dir = Path(args.home)

    failures: list[str] = []
    warnings: list[str] = []

    print(f"=== Verifying v1.8.0-economics Upgrade ({datetime.now().isoformat()}) ===\n")

    # 1. Node Health
    print("-> Checking node health...")
    try:
        status = _http_get_json(f"{rpc}/status")
        latest = status.get("result", {}).get("sync_info", {}).get("latest_block_height", "")
        catching = status.get("result", {}).get("sync_info", {}).get("catching_up", False)

        print(f"   [OK] RPC reachable (Height: {latest})")
        if catching:
            warnings.append("Node is catching up (syncing)")
    except Exception as e:
        failures.append(f"RPC check failed: {e}")

    # 2. Core Economics Parameters
    print("\n-> Checking core economics parameters...")
    try:
        params = _run_json([miraged, "q", "core", "params", "--node", rpc, "-o", "json"])
        p = params.get("params", params)

        # RelayMinGasPrice: 5000
        relay_min = _as_int(p.get("relay_min_gas_price"))
        if relay_min == 5000:
            print(f"   [OK] RelayMinGasPrice: {relay_min}")
        else:
            failures.append(f"RelayMinGasPrice expected 5000, got {relay_min}")

        # RelayMaxGasFee: 500,000,000
        relay_max = _as_int(p.get("relay_max_gas_fee"))
        if relay_max == 500_000_000:
            print(f"   [OK] RelayMaxGasFee: {relay_max:,} (500 MIRAGE)")
        else:
            failures.append(f"RelayMaxGasFee expected 500,000,000, got {relay_max}")

        # SubscriptionReservePercent: 80
        reserve_pct = _as_int(p.get("subscription_reserve_percent"))
        if reserve_pct == 80:
            print(f"   [OK] SubscriptionReservePercent: {reserve_pct}%")
        else:
            failures.append(f"SubscriptionReservePercent expected 80, got {reserve_pct}")

        # MintQuantity: 350,000,000
        mint_qty = _as_int(p.get("mint_quantity"))
        if mint_qty == 350_000_000:
            print(f"   [OK] MintQuantity: {mint_qty:,} (350 MIRAGE per 10min)")
        else:
            failures.append(f"MintQuantity expected 350,000,000, got {mint_qty}")

        # Tier fees: 100B/200B/300B
        tiers = p.get("tiers") or []
        if len(tiers) >= 4:
            t1 = _as_int(tiers[1].get("period_fee"))
            t2 = _as_int(tiers[2].get("period_fee"))
            t3 = _as_int(tiers[3].get("period_fee"))

            expected_t1 = 100_000_000_000  # 100B
            expected_t2 = 200_000_000_000  # 200B
            expected_t3 = 300_000_000_000  # 300B

            if t1 == expected_t1 and t2 == expected_t2 and t3 == expected_t3:
                print(f"   [OK] Tier fees: {t1//1e9:.0f}B/{t2//1e9:.0f}B/{t3//1e9:.0f}B ($1/$2/$3)")
            else:
                failures.append(f"Tier fees mismatch: {t1}/{t2}/{t3} (expected {expected_t1}/{expected_t2}/{expected_t3})")
        else:
            failures.append(f"Tiers config incomplete (len={len(tiers)})")

    except Exception as e:
        failures.append(f"Core params check failed: {e}")

    # 3. Governance Parameters
    print("\n-> Checking governance parameters...")
    try:
        gov_params = _run_json([miraged, "q", "gov", "params", "--node", rpc, "-o", "json"])
        gp = gov_params.get("params", gov_params)

        # min_deposit: 500B
        min_deposit = gp.get("min_deposit", [])
        min_amt = 0
        for d in min_deposit:
            if d.get("denom") == "umirage":
                min_amt = _as_int(d.get("amount"))
                break

        expected_min = 500_000_000_000  # 500B
        if min_amt == expected_min:
            print(f"   [OK] min_deposit: {min_amt//1e9:.0f}B umirage ($5)")
        else:
            failures.append(f"min_deposit expected {expected_min}, got {min_amt}")

        # expedited_min_deposit: 1T
        exp_deposit = gp.get("expedited_min_deposit", [])
        exp_amt = 0
        for d in exp_deposit:
            if d.get("denom") == "umirage":
                exp_amt = _as_int(d.get("amount"))
                break

        expected_exp = 1_000_000_000_000  # 1T
        if exp_amt == expected_exp:
            print(f"   [OK] expedited_min_deposit: {exp_amt//1e12:.0f}T umirage ($10)")
        else:
            failures.append(f"expedited_min_deposit expected {expected_exp}, got {exp_amt}")

    except Exception as e:
        failures.append(f"Gov params check failed: {e}")

    # 4. Node Config (app.toml)
    print("\n-> Checking node config...")
    app_toml = home_dir / "node" / "config" / "app.toml"
    if app_toml.exists():
        content = app_toml.read_text()
        if 'minimum-gas-prices = "5000umirage"' in content:
            print('   [OK] minimum-gas-prices = "5000umirage"')
        elif "5000umirage" in content:
            print('   [OK] minimum-gas-prices contains 5000umirage')
        else:
            failures.append('app.toml: minimum-gas-prices must be "5000umirage"')
    else:
        warnings.append(f"app.toml not found at {app_toml}")

    print("\n=== Summary ===")
    if warnings:
        for w in warnings:
            print(f"[WARN] {w}")

    if failures:
        print("[FAIL] Verification failed with errors:")
        for f in failures:
            print(f"  - {f}")
        return 1

    print("[PASS] All v1.8.0-economics checks passed successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
