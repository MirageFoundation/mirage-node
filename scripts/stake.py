#!/usr/bin/env python3
"""
Simple staking script for validators.
Usage: scripts/stake.py <amount_in_mirage>
"""

import sys
import os
import json
import subprocess
import time


def run_cmd(cmd, timeout=10):
    """Run command and return output."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode == 0:
            return result.stdout.strip()
        print(f"Error: {result.stderr}", file=sys.stderr)
        return None
    except subprocess.TimeoutExpired:
        print(f"Command timed out after {timeout}s", file=sys.stderr)
        return None
    except Exception as e:
        print(f"Command failed: {e}", file=sys.stderr)
        return None


def get_balance(bin_path, home, keyring, key_name, rpc_url):
    """Get account balance in uMIRAGE."""
    addr_output = run_cmd(
        [bin_path, "keys", "show", key_name, "--home", home, "--keyring-backend", keyring, "--address"]
    )
    if not addr_output:
        print("Failed to get validator address", file=sys.stderr)
        return None

    address = addr_output.strip()
    balance_output = run_cmd([bin_path, "query", "bank", "balances", address, "--node", rpc_url, "--output", "json"])
    if not balance_output:
        return None

    try:
        data = json.loads(balance_output)
        balances = data.get("balances", [])
        for bal in balances:
            if bal.get("denom") == "umirage":
                return int(bal.get("amount", 0))
        return 0
    except Exception as e:
        print(f"Failed to parse balance: {e}", file=sys.stderr)
        return None


def get_valoper_address(bin_path, home, keyring, key_name):
    """Get validator operator address."""
    valoper_output = run_cmd(
        [bin_path, "keys", "show", key_name, "--home", home, "--keyring-backend", keyring, "--bech", "val", "--address"]
    )
    if valoper_output:
        return valoper_output.strip()

    account_addr = run_cmd(
        [bin_path, "keys", "show", key_name, "--home", home, "--keyring-backend", keyring, "--address"]
    )
    if account_addr and account_addr.startswith("mirage1"):
        return f"miragevaloper{account_addr[7:]}"

    return None


def main():
    if len(sys.argv) != 2:
        print("Usage: scripts/stake.py <amount_in_mirage>", file=sys.stderr)
        sys.exit(1)

    try:
        amount_mirage = int(sys.argv[1])
        if amount_mirage <= 0:
            raise ValueError()
    except ValueError:
        print("Amount must be a positive integer", file=sys.stderr)
        sys.exit(1)

    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    bin_path = os.path.join(root_dir, "blockchain", "bin", "miraged")

    if not os.path.exists(bin_path):
        print(f"Binary not found: {bin_path}", file=sys.stderr)
        sys.exit(1)

    home = os.path.expanduser("~/.mirage/node")

    if not os.path.exists(home):
        print(f"Node home not found: {home}", file=sys.stderr)
        sys.exit(1)

    keyring = "test"
    rpc_url = "tcp://127.0.0.1:26657"
    chain_id = "mirage-1"

    print(f"Finding validator key in {home}...")
    keys_output = run_cmd([bin_path, "keys", "list", "--home", home, "--keyring-backend", keyring, "--output", "json"])
    if not keys_output:
        print("Failed to list keys", file=sys.stderr)
        sys.exit(1)

    try:
        keys = json.loads(keys_output)
        if not keys or len(keys) == 0:
            print("No keys found in keyring", file=sys.stderr)
            sys.exit(1)
        key_name = keys[0].get("name")
        if not key_name:
            print("Invalid key format", file=sys.stderr)
            sys.exit(1)
        print(f"Using key: {key_name}")
    except Exception as e:
        print(f"Failed to parse keys: {e}", file=sys.stderr)
        sys.exit(1)

    addr_output = run_cmd(
        [bin_path, "keys", "show", key_name, "--home", home, "--keyring-backend", keyring, "--address"]
    )
    if not addr_output:
        print("Failed to get address", file=sys.stderr)
        sys.exit(1)

    address = addr_output.strip()
    print(f"Address: {address}")

    print(f"Checking balance...")
    balance_um = get_balance(bin_path, home, keyring, key_name, rpc_url)

    if balance_um is None:
        print("Failed to query balance", file=sys.stderr)
        sys.exit(1)

    balance_mirage = balance_um / 1_000_000
    print(f"Current balance: {balance_mirage:,.2f} MIRAGE")

    if balance_mirage < 20:
        print(f"Insufficient balance. Need at least 20 MIRAGE, have {balance_mirage:,.2f} MIRAGE", file=sys.stderr)
        sys.exit(1)

    amount_um = amount_mirage * 1_000_000
    if amount_um > balance_um:
        print(f"Cannot stake {amount_mirage:,} MIRAGE. Balance: {balance_mirage:,.2f} MIRAGE", file=sys.stderr)
        sys.exit(1)

    valoper = get_valoper_address(bin_path, home, keyring, key_name)
    if not valoper:
        print("Failed to get validator operator address", file=sys.stderr)
        sys.exit(1)

    # Confirmation
    print(f"\n{'─' * 40}")
    print(f"Stake: {amount_mirage:,} MIRAGE")
    print(f"To validator: {valoper}")
    print(f"From: {address}")
    print(f"{'─' * 40}")
    
    try:
        confirm = input("Type 'confirm' to proceed: ").strip()
        if confirm != "confirm":
            print("Aborted.")
            sys.exit(0)
    except KeyboardInterrupt:
        print("\nAborted.")
        sys.exit(0)

    print(f"\nStaking {amount_mirage:,} MIRAGE...")

    tx_cmd = [
        bin_path,
        "tx",
        "staking",
        "delegate",
        valoper,
        f"{amount_um}umirage",
        "--from",
        key_name,
        "--home",
        home,
        "--keyring-backend",
        keyring,
        "--chain-id",
        chain_id,
        "--node",
        rpc_url,
        "--broadcast-mode",
        "sync",
        "--yes",
        "--gas",
        "auto",
        "--gas-adjustment",
        "2.0",
        "--gas-prices",
        "1.0umirage",
        "--output",
        "json",
    ]

    tx_output = run_cmd(tx_cmd, timeout=15)
    if not tx_output:
        print("Transaction failed", file=sys.stderr)
        sys.exit(1)

    try:
        tx_data = json.loads(tx_output)
        txhash = tx_data.get("txhash")
        code = tx_data.get("code", 0)

        if code != 0:
            print(f"Transaction rejected (code={code})", file=sys.stderr)
            print(tx_output, file=sys.stderr)
            sys.exit(1)

        print(f"Transaction submitted: {txhash}")
        print("Waiting for confirmation...")

        time.sleep(6)

        query_cmd = [bin_path, "query", "tx", txhash, "--node", rpc_url, "-o", "json"]
        query_output = run_cmd(query_cmd, timeout=10)

        if query_output:
            query_data = json.loads(query_output)
            query_code = query_data.get("code", 0)
            height = query_data.get("height", "?")

            if query_code == 0:
                print(f"✓ Staked {amount_mirage:,} MIRAGE at height {height}")
                sys.exit(0)
            else:
                print(f"Delegation failed (code={query_code})", file=sys.stderr)
                sys.exit(1)
        else:
            print(f"Transaction submitted but confirmation timeout: {txhash}", file=sys.stderr)
            sys.exit(1)

    except json.JSONDecodeError as e:
        print(f"Failed to parse transaction response: {e}", file=sys.stderr)
        print(tx_output, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
