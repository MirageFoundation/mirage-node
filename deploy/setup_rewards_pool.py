#!/usr/bin/env python3
"""
Rewards Pool setup - imports wallet for reward distribution.

Usage: python3 deploy/setup_rewards_pool.py [--force]

This script sets up the rewards_pool key in the node keyring, which is used
by the RewardDistributor to send quest rewards to users.
"""

import argparse
import getpass
import json
import os
import subprocess
import sys
from pathlib import Path

try:
    import requests
except ImportError:
    print("Missing dependency: requests")
    print("Install with: pip install requests")
    sys.exit(1)

# Constants
BIP39_WORDLIST_URL = "https://raw.githubusercontent.com/bitcoin/bips/master/bip-0039/english.txt"
_BIP39_WORDS = None

MIRAGED_BIN = Path("/opt/mirage/blockchain/bin/miraged")
NODE_HOME = Path.home() / ".mirage" / "node"
ENV_DIR = Path.home() / ".mirage" / "env"
BACKEND_ENV = ENV_DIR / "backend.env"
KEYRING_BACKEND = "test"
KEY_NAME = "rewards_pool"

# 1 MIRAGE = 1,000,000 umirage
UMIRAGE_PER_MIRAGE = 1_000_000
MIN_MIRAGE_BALANCE = 1000

# ANSI color codes
YELLOW = "\033[33m"
RED = "\033[31m"
GREEN = "\033[32m"
RESET = "\033[0m"

# Box drawing (68 chars wide to fit addresses)
LINE = "─" * 68
BOX_TOP = "┌" + LINE + "┐"
BOX_BOT = "└" + LINE + "┘"


def strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from text."""
    import re
    return re.sub(r'\033\[[0-9;]*m', '', text)


def visual_width(text: str) -> int:
    """Get visual width of text (accounting for emojis taking 2 chars)."""
    import unicodedata
    stripped = strip_ansi(text)
    width = 0
    for char in stripped:
        # Check if character is a wide character (like emojis)
        if unicodedata.east_asian_width(char) in ('F', 'W'):
            width += 2
        else:
            width += 1
    return width


def pad_title(title: str, target_width: int = 66) -> str:
    """Pad title to target width, accounting for ANSI codes and emojis."""
    visual_len = visual_width(title)
    padding_needed = max(0, target_width - visual_len)
    return title + " " * padding_needed


def box(title: str) -> None:
    """Print a section header."""
    print()
    print(BOX_TOP)
    print(f"│ {pad_title(title)} │")
    print(BOX_BOT)


def print_box(title: str, lines: list[str]) -> None:
    """
    Print a formatted box with title and content lines.

    Args:
        title: Box title (can include emoji/color codes)
        lines: List of content lines (will be auto-wrapped/padded)
    """
    print()
    print(BOX_TOP)
    print(f"│ {pad_title(title)} │")
    print("│" + " " * 68 + "│")
    for line in lines:
        if line == "":
            print("│" + " " * 68 + "│")
        else:
            # Auto-wrap long lines
            max_len = 66
            if len(line) <= max_len:
                print(f"│ {line:<66} │")
            else:
                # Wrap long lines
                words = line.split()
                current_line = ""
                for word in words:
                    test_line = f"{current_line} {word}".strip() if current_line else word
                    if len(test_line) <= max_len:
                        current_line = test_line
                    else:
                        if current_line:
                            print(f"│ {current_line:<66} │")
                        current_line = word
                if current_line:
                    print(f"│ {current_line:<66} │")
    print(BOX_BOT)


def info(label: str, value: str) -> None:
    """Print a labeled value."""
    print(f"  {label:<20} {value}")


def ok(msg: str) -> None:
    """Print success message (green)."""
    print(f"  {GREEN}✅{RESET} {msg}")


def err(msg: str) -> None:
    """Print error message (red)."""
    print(f"  {RED}❌{RESET} {msg}")


def warn(msg: str) -> None:
    """Print warning message (yellow)."""
    print(f"  {YELLOW}⚠️{RESET} {msg}")


def format_mirage(umirage: int) -> str:
    """Format umirage as MIRAGE with commas."""
    mirage = umirage / UMIRAGE_PER_MIRAGE
    if mirage == int(mirage):
        return f"{int(mirage):,} MIRAGE"
    return f"{mirage:,.2f} MIRAGE"


# ─────────────────────────────────────────────────────────────────────────────
# BIP39 validation
# ─────────────────────────────────────────────────────────────────────────────


def get_bip39_wordlist() -> list[str]:
    """Load BIP39 English wordlist."""
    global _BIP39_WORDS
    if _BIP39_WORDS is None:
        cache_path = Path("/tmp/bip39_english.txt")
        if cache_path.exists():
            _BIP39_WORDS = cache_path.read_text().strip().split("\n")
        else:
            resp = requests.get(BIP39_WORDLIST_URL, timeout=10)
            resp.raise_for_status()
            _BIP39_WORDS = resp.text.strip().split("\n")
            cache_path.write_text(resp.text)
    return _BIP39_WORDS


def validate_mnemonic(mnemonic: str) -> tuple[bool, str]:
    """Validate BIP39 mnemonic (12 words)."""
    words = mnemonic.strip().lower().split()
    if len(words) != 12:
        return False, f"Expected 12 words, got {len(words)}"
    try:
        wordlist = get_bip39_wordlist()
        for i, word in enumerate(words):
            if word not in wordlist:
                return False, f"Word {i+1} '{word}' is not a valid BIP39 word"
    except Exception:
        pass  # Skip validation if wordlist unavailable
    return True, ""


# ─────────────────────────────────────────────────────────────────────────────
# Chain queries
# ─────────────────────────────────────────────────────────────────────────────


def key_exists(key_name: str) -> bool:
    """Check if a key exists in the keyring."""
    if not MIRAGED_BIN.exists() or not NODE_HOME.exists():
        return False
    try:
        result = subprocess.run(
            [
                str(MIRAGED_BIN),
                "keys",
                "show",
                key_name,
                "--home",
                str(NODE_HOME),
                "--keyring-backend",
                KEYRING_BACKEND,
                "-a",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except Exception:
        return False


def get_key_address(key_name: str) -> str | None:
    """Get the address for a key in the keyring."""
    if not MIRAGED_BIN.exists() or not NODE_HOME.exists():
        return None
    try:
        result = subprocess.run(
            [
                str(MIRAGED_BIN),
                "keys",
                "show",
                key_name,
                "--home",
                str(NODE_HOME),
                "--keyring-backend",
                KEYRING_BACKEND,
                "-a",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            addr = result.stdout.strip()
            if addr.startswith("mirage1"):
                return addr
    except Exception:
        pass
    return None


def get_balance(address: str) -> int | None:
    """Get balance in umirage for an address."""
    if not MIRAGED_BIN.exists() or not NODE_HOME.exists():
        return None
    try:
        result = subprocess.run(
            [
                str(MIRAGED_BIN),
                "q",
                "bank",
                "balance",
                address,
                "umirage",
                "--home",
                str(NODE_HOME),
                "--node",
                "tcp://127.0.0.1:26657",
                "-o",
                "json",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            # Handle both wrapped and unwrapped response formats
            balance = data.get("balance", data)
            amount = balance.get("amount", "0")
            return int(amount)
    except Exception:
        pass
    return None


def derive_address_from_mnemonic(mnemonic: str) -> str | None:
    """
    Derive the address from a mnemonic without importing it.
    Uses a temporary keyring location to avoid polluting the real keyring.
    """
    if not MIRAGED_BIN.exists():
        return None

    import tempfile
    import shutil

    temp_home = Path(tempfile.mkdtemp(prefix="mirage_derive_"))
    try:
        # Create the key in a temp location
        result = subprocess.run(
            [
                str(MIRAGED_BIN),
                "keys",
                "add",
                "temp_derive",
                "--recover",
                "--home",
                str(temp_home),
                "--keyring-backend",
                "test",
            ],
            input=mnemonic + "\n",
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return None

        # Get the address
        result = subprocess.run(
            [
                str(MIRAGED_BIN),
                "keys",
                "show",
                "temp_derive",
                "--home",
                str(temp_home),
                "--keyring-backend",
                "test",
                "-a",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    finally:
        # Clean up temp directory
        shutil.rmtree(temp_home, ignore_errors=True)

    return None


def delete_key(key_name: str) -> tuple[bool, str | None]:
    """
    Delete a key from the keyring.
    Returns (success, error message or None).
    """
    if not MIRAGED_BIN.exists():
        return False, "miraged binary not found"

    result = subprocess.run(
        [
            str(MIRAGED_BIN),
            "keys",
            "delete",
            key_name,
            "--home",
            str(NODE_HOME),
            "--keyring-backend",
            KEYRING_BACKEND,
            "--yes",
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )

    if result.returncode != 0:
        error = result.stderr or result.stdout or "Unknown error"
        return False, error
    return True, None


def import_key(key_name: str, mnemonic: str) -> tuple[bool, str | None]:
    """
    Import a key from mnemonic into the keyring.
    Returns (success, address or error).
    """
    if not MIRAGED_BIN.exists():
        return False, "miraged binary not found"

    NODE_HOME.mkdir(parents=True, exist_ok=True)

    result = subprocess.run(
        [
            str(MIRAGED_BIN),
            "keys",
            "add",
            key_name,
            "--recover",
            "--home",
            str(NODE_HOME),
            "--keyring-backend",
            KEYRING_BACKEND,
        ],
        input=mnemonic + "\n",
        capture_output=True,
        text=True,
        timeout=30,
    )

    if result.returncode != 0:
        error = result.stderr or result.stdout or "Unknown error"
        return False, error

    # Get the address
    address = get_key_address(key_name)
    if address:
        return True, address
    return False, "Key imported but could not retrieve address"


def set_backend_env(key: str, value: str) -> None:
    """Set a key=value in backend.env."""
    ENV_DIR.mkdir(parents=True, exist_ok=True)

    if BACKEND_ENV.exists():
        content = BACKEND_ENV.read_text()
        lines = content.split("\n")
        new_lines = []
        found = False
        for line in lines:
            if line.startswith(f"{key}="):
                new_lines.append(f"{key}={value}")
                found = True
            else:
                new_lines.append(line)
        if not found:
            new_lines.append(f"{key}={value}")
        BACKEND_ENV.write_text("\n".join(new_lines))
    else:
        BACKEND_ENV.write_text(f"{key}={value}\n")


def get_backend_env(key: str) -> str | None:
    """Get a value from backend.env."""
    if not BACKEND_ENV.exists():
        return None
    content = BACKEND_ENV.read_text()
    for line in content.split("\n"):
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1]
    return None


def update_backend_env(address: str) -> bool:
    """Update REWARDS_POOL_ADDRESS in backend.env."""
    set_backend_env("REWARDS_POOL_ADDRESS", address)
    return True


# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────


def configure_backend(address: str) -> None:
    """Interactive configuration of backend.env settings."""
    box("CONFIGURE BACKEND")
    print()

    changed = False

    # Ask about address
    current_address = get_backend_env("REWARDS_POOL_ADDRESS")
    if current_address == address:
        print(f"  REWARDS_POOL_ADDRESS = {address}")
    else:
        print(f"  REWARDS_POOL_ADDRESS = {current_address or '(not set)'}")
        print(f"  New address: {address}")
    confirm = input("  Update address? [Y/n]: ").strip().lower()
    if confirm != "n":
        set_backend_env("REWARDS_POOL_ADDRESS", address)
        ok("REWARDS_POOL_ADDRESS updated")
        changed = True
    else:
        print("  Skipped.")

    # Ask about quests
    print()
    current_quests = get_backend_env("QUESTS_ENABLED") or "false"
    default_quests = "Y/n" if current_quests == "true" else "y/N"
    confirm = input(f"  Enable quests? [{default_quests}]: ").strip().lower()
    if current_quests == "true":
        # Currently enabled, default to keep enabled
        new_value = "false" if confirm == "n" else "true"
    else:
        # Currently disabled, default to keep disabled
        new_value = "true" if confirm == "y" else "false"
    if new_value != current_quests:
        set_backend_env("QUESTS_ENABLED", new_value)
        ok(f"QUESTS_ENABLED={new_value}")
        changed = True

    # Ask about payouts
    print()
    current_payouts = get_backend_env("PAYOUTS_ENABLED") or "false"
    default_payouts = "Y/n" if current_payouts == "true" else "y/N"
    confirm = input(f"  Enable payouts? [{default_payouts}]: ").strip().lower()
    if current_payouts == "true":
        # Currently enabled, default to keep enabled
        new_value = "false" if confirm == "n" else "true"
    else:
        # Currently disabled, default to keep disabled
        new_value = "true" if confirm == "y" else "false"
    if new_value != current_payouts:
        set_backend_env("PAYOUTS_ENABLED", new_value)
        ok(f"PAYOUTS_ENABLED={new_value}")
        changed = True

    print()
    if changed:
        ok(f"Configuration saved to {BACKEND_ENV}")
        print()
        warn("Restart the backend service to apply changes")
    else:
        print("  No changes made.")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Set up the rewards pool wallet for quest reward distribution.",
        epilog="The rewards_pool key is used by the backend to send MIRAGE rewards to users.",
    )
    parser.add_argument("--force", "-f", action="store_true", help="Delete existing key and import a new one")
    parser.add_argument(
        "--config", "-c", action="store_true", help="Configure backend.env for existing key (enable quests/payouts)"
    )
    args = parser.parse_args()

    # ── Handle --config mode ───────────────────────────────────────────────────
    if args.config:
        box("REWARDS POOL CONFIG")
        print()
        print("  Checking for existing key...")

        if not MIRAGED_BIN.exists():
            err(f"miraged not found at {MIRAGED_BIN}")
            return 1

        if not key_exists(KEY_NAME):
            err(f"No '{KEY_NAME}' key found. Run without --config to set up first.")
            return 1

        address = get_key_address(KEY_NAME)
        if not address:
            err("Could not retrieve address from key")
            return 1

        ok(f"Key found: {address}")

        print()
        print("  Querying balance...")
        balance = get_balance(address)
        if balance is not None:
            info("Balance:", format_mirage(balance))
        else:
            warn("Could not query balance")

        configure_backend(address)
        return 0

    box("REWARDS POOL SETUP")

    # ── Check prerequisites ────────────────────────────────────────────────────
    print()
    print("  Checking prerequisites...")

    if not MIRAGED_BIN.exists():
        err(f"miraged not found at {MIRAGED_BIN}")
        print()
        print("  Run deploy to build the miraged binary first.")
        return 1
    ok("miraged binary found")

    # ── Check if key already exists ────────────────────────────────────────────
    print()
    print(f"  Checking for existing '{KEY_NAME}' key...")

    if key_exists(KEY_NAME):
        address = get_key_address(KEY_NAME)
        if not address:
            err("Key exists but could not retrieve address")
            return 1

        ok(f"Key exists: {KEY_NAME}")
        info("Address:", address)

        print()
        print("  Querying balance...")
        balance = get_balance(address)
        if balance is not None:
            info("Balance:", format_mirage(balance))
        else:
            warn("Could not query balance (is the node running?)")

        if not args.force:
            # Check if env is configured
            print()
            if BACKEND_ENV.exists():
                content = BACKEND_ENV.read_text()
                if f"REWARDS_POOL_ADDRESS={address}" in content:
                    ok("backend.env already configured")
                elif "REWARDS_POOL_ADDRESS=" in content:
                    warn("backend.env has different REWARDS_POOL_ADDRESS")
                    print(f"  Update {BACKEND_ENV} if needed")
                else:
                    warn("REWARDS_POOL_ADDRESS not in backend.env")
                    confirm = input("  Add to backend.env? [Y/n]: ").strip().lower()
                    if confirm != "n":
                        update_backend_env(address)
                        ok(f"Updated {BACKEND_ENV}")

            balance_str = format_mirage(balance) if balance is not None else None
            lines = [
                f"Address: {address}",
            ]
            if balance_str:
                lines.append(f"Balance: {balance_str}")
            lines.extend(
                [
                    "",
                    "Use --force to replace with a different seed phrase.",
                ]
            )
            print_box(f"{GREEN}✅{RESET} EXISTING KEY - NO CHANGES MADE", lines)
            print()
            return 0

        # --force: Will replace after getting new seed
        print()
        warn("--force specified, will replace existing key")
        existing_key = True
    else:
        ok("No existing key found")
        existing_key = False

    # ── Import wallet ──────────────────────────────────────────────────────────
    box("IMPORT REWARDS POOL WALLET")
    print()
    print("  Enter the seed phrase for the rewards pool wallet.")
    print("  This wallet will be used to send quest rewards to users.")
    print()

    mnemonic = getpass.getpass("  Enter 12-word mnemonic: ")
    valid, error = validate_mnemonic(mnemonic)
    if not valid:
        err(error)
        return 1
    ok("Mnemonic format valid")

    # ── Derive address and check balance BEFORE importing ──────────────────────
    print()
    print("  Deriving address from mnemonic...")
    address = derive_address_from_mnemonic(mnemonic)
    if not address:
        err("Could not derive address from mnemonic")
        return 1
    ok(f"Address: {address}")

    print()
    print("  Querying balance...")
    balance = get_balance(address)

    if balance is not None:
        info("Balance:", format_mirage(balance))
        mirage_balance = balance / UMIRAGE_PER_MIRAGE

        if mirage_balance < MIN_MIRAGE_BALANCE:
            min_str = f"{MIN_MIRAGE_BALANCE:,} MIRAGE"
            print_box(
                f"{YELLOW}⚠️{RESET} LOW BALANCE WARNING",
                [
                    f"Current balance: {format_mirage(balance)}",
                    f"Minimum recommended: {min_str}",
                    "",
                    "The wallet needs to be funded before rewards can be distributed.",
                    "You can continue setup now and fund later, or fund first and run",
                    "this script again.",
                ]
            )
            print()
            confirm = input("  Continue with low balance? [y/N]: ").strip().lower()
            if confirm != "y":
                print()
                print("  Aborted. Fund the wallet and run this script again.")
                print(f"  Send MIRAGE to: {address}")
                return 0
    else:
        warn("Could not query balance (is the node running?)")
        print()
        confirm = input("  Continue anyway? [y/N]: ").strip().lower()
        if confirm != "y":
            print("  Aborted.")
            return 0

    # ── Delete existing key if --force ───────────────────────────────────────────
    if existing_key:
        print()
        print(f"  Removing existing '{KEY_NAME}' key...")
        success, error = delete_key(KEY_NAME)
        if not success:
            err(f"Failed to delete key: {error}")
            return 1
        ok("Old key removed")

    # ── Import the key ─────────────────────────────────────────────────────────
    print()
    print(f"  Importing key '{KEY_NAME}' to keyring...")

    success, result = import_key(KEY_NAME, mnemonic)
    if not success:
        err(f"Failed to import key: {result}")
        return 1
    ok(f"Key imported: {result}")

    # ── Summary ────────────────────────────────────────────────────────────────
    box("KEY IMPORTED")
    print()
    info("Key name:", KEY_NAME)
    info("Address:", address)
    if balance is not None:
        info("Balance:", format_mirage(balance))

    # ── Configure backend ─────────────────────────────────────────────────────
    configure_backend(address)

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n  Aborted.")
        sys.exit(0)
