#!/usr/bin/env python3
"""Quick send 200 MIRAGE to satoshi and God."""

import getpass
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHAIN_ID = "mirage-1"

RECIPIENTS = [
    # ("satoshi", "mirage1u4lcw3x32mwweh3utg66fynt5g0p2zclnp5n5q", 200),
    ("God", "mirage1venw2fdw8wx8mux4gglqjctwwttvw6f2y04qhw", 200),
]


def get_miraged():
    p = ROOT / "blockchain" / "bin" / "miraged"
    return str(p) if p.exists() else "miraged"


def main():
    bin_path = get_miraged()
    rpc = input("RPC URL [tcp://mirage.vote:26657]: ").strip() or "tcp://mirage.vote:26657"

    print("\nWill send:")
    for name, addr, amount in RECIPIENTS:
        print(f"  {amount} MIRAGE -> {name} ({addr})")
    print()

    seed = getpass.getpass("Seed phrase: ").strip()
    if not seed:
        print("No seed provided.")
        sys.exit(1)

    with tempfile.TemporaryDirectory() as home:
        # Import key
        proc = subprocess.run(
            [bin_path, "keys", "add", "sender", "--home", home, "--keyring-backend", "test", "--recover"],
            input=seed + "\n",
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            print(f"Failed to import key: {proc.stderr}")
            sys.exit(1)

        # Get sender address
        proc = subprocess.run(
            [bin_path, "keys", "show", "sender", "--home", home, "--keyring-backend", "test", "--address"],
            capture_output=True,
            text=True,
        )
        from_addr = proc.stdout.strip()
        print(f"\nSending from: {from_addr}\n")

        for name, to_addr, amount in RECIPIENTS:
            amount_u = amount * 1_000_000
            cmd = [
                bin_path,
                "tx",
                "bank",
                "send",
                from_addr,
                to_addr,
                f"{amount_u}umirage",
                "--from",
                "sender",
                "--home",
                home,
                "--keyring-backend",
                "test",
                "--chain-id",
                CHAIN_ID,
                "--node",
                rpc,
                "--broadcast-mode",
                "sync",
                "--yes",
                "--gas",
                "200000",
                "--gas-prices",
                "1.0umirage",
                "--output",
                "json",
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if proc.returncode != 0:
                print(f"[FAIL] {name}: {proc.stderr}")
                continue
            try:
                data = json.loads(proc.stdout)
                if data.get("code", 0) != 0:
                    print(f"[FAIL] {name}: {data.get('raw_log', 'error')}")
                else:
                    print(f"[OK] {name}: {data.get('txhash')}")
                    time.sleep(3)  # Wait for tx to be included in block
            except:
                print(f"[FAIL] {name}: {proc.stdout}")

    print("\nDone.")


if __name__ == "__main__":
    main()
