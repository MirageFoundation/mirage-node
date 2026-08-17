#!/usr/bin/env python3
"""Self-delegate from the local validator account.

  scripts/stake.py 50000
  scripts/stake.py --stake-all-above 20000000 --yes

--stake-all-above N  Self-delegate every whole MIRAGE above N spendable
                     (minimum 1,000,000). With --yes this is cron-safe:
                     exit 0 when liquid is already at or below N.

The validator account pays relay gas. N cannot be below 1,000,000 MIRAGE.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import time
from typing import NoReturn

UMIRAGE_PER_MIRAGE = 1_000_000
MIN_KEEP_LIQUID_MIRAGE = 1_000_000
KEY_NAME = "validator"
CHAIN_ID = "mirage-1"
RPC_URL = "tcp://127.0.0.1:26657"
KEYRING = "test"
# Conservative MsgDelegate gas budget used only to keep the liquid floor
# intact after fees. The broadcast still uses --gas auto.
FEE_GAS_BUDGET = 1_000_000
GAS_ADJUSTMENT = 2.0


def die(msg: str, code: int = 1) -> NoReturn:
    print(msg, file=sys.stderr)
    sys.exit(code)


def run_cmd(cmd: list[str], timeout: int = 10) -> str:
    print(f"[stake] run: {' '.join(cmd)}")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        die(f"command timed out after {timeout}s: {' '.join(cmd)}")
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "").strip()
        die(f"command failed ({result.returncode}): {err}")
    return result.stdout.strip()


def find_miraged(root_dir: str) -> str:
    candidates = [
        os.path.join(root_dir, "blockchain", "miraged"),
        os.path.join(root_dir, "blockchain", "bin", "miraged"),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    die(f"miraged not found (tried {', '.join(candidates)})")


def load_min_gas_price_umirage(home: str) -> float:
    path = os.path.join(home, "config", "app.toml")
    if not os.path.isfile(path):
        die(f"app.toml not found: {path}")
    with open(path, encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.split("#", 1)[0].strip()
            if not line.startswith("minimum-gas-prices"):
                continue
            if "=" not in line:
                die(f"invalid minimum-gas-prices line in {path}: {raw_line.rstrip()}")
            value = line.split("=", 1)[1].strip().strip("\"'")
            parts = [p.strip() for p in value.split(",") if p.strip()]
            for part in parts:
                if part.endswith("umirage"):
                    number = part[: -len("umirage")].strip()
                    try:
                        price = float(number)
                    except ValueError:
                        die(f"invalid minimum-gas-prices amount in {path}: {part}")
                    if price <= 0:
                        die(f"minimum-gas-prices must be positive, got {price}")
                    return price
            die(f"minimum-gas-prices must include umirage in {path}: {value}")
    die(f"minimum-gas-prices missing in {path}")


def gas_price_flag(price: float) -> str:
    if price == int(price):
        return f"{int(price)}umirage"
    return f"{price}umirage"


def fee_reserve_um(gas_price: float) -> int:
    reserve = int(math.ceil(FEE_GAS_BUDGET * gas_price * GAS_ADJUSTMENT))
    if reserve <= 0:
        die(f"fee reserve computed as {reserve}; gas_price={gas_price}")
    return reserve


def surplus_stake_um(balance_um: int, keep_um: int, fee_um: int) -> int:
    """Whole-MIRAGE self-delegation that leaves keep_um + fee_um liquid."""
    if balance_um < 0 or keep_um < 0 or fee_um <= 0:
        die(f"invalid surplus inputs: balance={balance_um} keep={keep_um} fee={fee_um}")
    available = balance_um - keep_um - fee_um
    if available < UMIRAGE_PER_MIRAGE:
        return 0
    return (available // UMIRAGE_PER_MIRAGE) * UMIRAGE_PER_MIRAGE


def get_balance_um(bin_path: str, home: str, address: str) -> int:
    raw = run_cmd([bin_path, "query", "bank", "balances", address, "--node", RPC_URL, "--output", "json"])
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        die(f"bank balances: not JSON: {e}: {raw[:200]}")
    for bal in data.get("balances") or []:
        if bal.get("denom") == "umirage":
            try:
                return int(bal.get("amount", "0"))
            except (TypeError, ValueError):
                die(f"bank balances: invalid umirage amount: {bal}")
    return 0


def confirm_or_die(yes: bool) -> None:
    if yes:
        return
    if not sys.stdin.isatty():
        die("refusing to stake without --yes (stdin is not a tty)")
    try:
        answer = input("Type 'confirm' to proceed: ").strip()
    except (KeyboardInterrupt, EOFError):
        die("aborted")
    if answer != "confirm":
        die("aborted", code=0)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Self-delegate MIRAGE from the local validator account.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=("examples:\n" "  scripts/stake.py 50000\n" "  scripts/stake.py --stake-all-above 20000000 --yes\n"),
    )
    parser.add_argument(
        "amount",
        nargs="?",
        type=int,
        help="MIRAGE to self-delegate",
    )
    parser.add_argument(
        "-s",
        "--stake-all-above",
        type=int,
        metavar="N",
        help=f"self-delegate every whole MIRAGE above N liquid (minimum {MIN_KEEP_LIQUID_MIRAGE:,})",
    )
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="skip confirmation (needed for cron)",
    )
    args = parser.parse_args()
    if (args.amount is None) == (args.stake_all_above is None):
        parser.error("specify either AMOUNT or --stake-all-above N")
    if args.amount is not None and args.amount <= 0:
        parser.error("AMOUNT must be a positive integer")
    if args.stake_all_above is not None and args.stake_all_above < MIN_KEEP_LIQUID_MIRAGE:
        parser.error(f"--stake-all-above must be >= {MIN_KEEP_LIQUID_MIRAGE:,} MIRAGE")
    return args


def main() -> None:
    args = parse_args()

    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    bin_path = find_miraged(root_dir)
    home = os.path.expanduser("~/.mirage/node")
    if not os.path.isdir(home):
        die(f"node home not found: {home}")

    gas_price = load_min_gas_price_umirage(home)
    fee_um = fee_reserve_um(gas_price)
    print(f"[stake] gas_price={gas_price} fee_reserve_um={fee_um}")

    address = run_cmd([bin_path, "keys", "show", KEY_NAME, "--home", home, "--keyring-backend", KEYRING, "--address"])
    valoper = run_cmd(
        [
            bin_path,
            "keys",
            "show",
            KEY_NAME,
            "--home",
            home,
            "--keyring-backend",
            KEYRING,
            "--bech",
            "val",
            "--address",
        ]
    )
    print(f"[stake] key={KEY_NAME} address={address} valoper={valoper}")

    balance_um = get_balance_um(bin_path, home, address)
    print(f"[stake] liquid={balance_um / UMIRAGE_PER_MIRAGE:,.6f} MIRAGE ({balance_um} umirage)")

    if args.stake_all_above is not None:
        keep_um = args.stake_all_above * UMIRAGE_PER_MIRAGE
        amount_um = surplus_stake_um(balance_um, keep_um, fee_um)
        print(
            f"[stake] stake_all_above={args.stake_all_above} MIRAGE "
            f"surplus_um={amount_um} "
            f"({amount_um / UMIRAGE_PER_MIRAGE:,.0f} MIRAGE)"
        )
        if amount_um == 0:
            print(
                f"liquid {balance_um / UMIRAGE_PER_MIRAGE:,.6f} MIRAGE is at or below "
                f"--stake-all-above {args.stake_all_above:,} plus fee reserve "
                f"{fee_um / UMIRAGE_PER_MIRAGE:,.6f} MIRAGE; nothing to stake"
            )
            sys.exit(0)
        remaining_um = balance_um - amount_um
        print(f"\n{'─' * 40}")
        print(f"Stake all above: {args.stake_all_above:,} MIRAGE")
        print(f"Stake surplus: {amount_um // UMIRAGE_PER_MIRAGE:,} MIRAGE")
        print(f"Remaining before fee: {remaining_um / UMIRAGE_PER_MIRAGE:,.6f} MIRAGE")
        print(f"To validator: {valoper}")
        print(f"From: {address}")
        print(f"{'─' * 40}")
    else:
        amount_um = args.amount * UMIRAGE_PER_MIRAGE
        min_remain_um = MIN_KEEP_LIQUID_MIRAGE * UMIRAGE_PER_MIRAGE + fee_um
        needed = amount_um + min_remain_um
        if balance_um < needed:
            die(
                f"cannot stake {args.amount:,} MIRAGE: liquid "
                f"{balance_um / UMIRAGE_PER_MIRAGE:,.6f} MIRAGE, "
                f"need {needed / UMIRAGE_PER_MIRAGE:,.6f} "
                f"(keeps {MIN_KEEP_LIQUID_MIRAGE:,} MIRAGE plus fee reserve)"
            )
        print(f"\n{'─' * 40}")
        print(f"Stake: {args.amount:,} MIRAGE")
        print(f"To validator: {valoper}")
        print(f"From: {address}")
        print(f"{'─' * 40}")

    confirm_or_die(args.yes)
    amount_mirage = amount_um // UMIRAGE_PER_MIRAGE
    print(f"\nStaking {amount_mirage:,} MIRAGE...")

    tx_output = run_cmd(
        [
            bin_path,
            "tx",
            "staking",
            "delegate",
            valoper,
            f"{amount_um}umirage",
            "--from",
            KEY_NAME,
            "--home",
            home,
            "--keyring-backend",
            KEYRING,
            "--chain-id",
            CHAIN_ID,
            "--node",
            RPC_URL,
            "--broadcast-mode",
            "sync",
            "--yes",
            "--gas",
            "auto",
            "--gas-adjustment",
            str(GAS_ADJUSTMENT),
            "--gas-prices",
            gas_price_flag(gas_price),
            "--output",
            "json",
        ],
        timeout=15,
    )

    try:
        tx_data = json.loads(tx_output)
    except json.JSONDecodeError as e:
        die(f"tx response not JSON: {e}: {tx_output[:300]}")

    txhash = tx_data.get("txhash")
    code = int(tx_data.get("code", 0))
    if code != 0:
        die(f"transaction rejected (code={code}): {tx_output}")
    if not txhash:
        die(f"transaction submitted but missing txhash: {tx_output}")

    print(f"Transaction submitted: {txhash}")
    print("Waiting for confirmation...")
    time.sleep(6)

    query_output = run_cmd(
        [bin_path, "query", "tx", txhash, "--node", RPC_URL, "-o", "json"],
        timeout=10,
    )
    try:
        query_data = json.loads(query_output)
    except json.JSONDecodeError as e:
        die(f"tx query not JSON: {e}: {query_output[:300]}")
    query_code = int(query_data.get("code", 1))
    height = query_data.get("height", "?")
    if query_code != 0:
        die(f"delegation failed (code={query_code}) at height {height}: {query_output}")
    print(f"Staked {amount_mirage:,} MIRAGE at height {height}")


if __name__ == "__main__":
    main()
