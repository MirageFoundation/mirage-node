#!/usr/bin/env python3
"""
Hermes IBC relayer setup for Mirage <-> Osmosis.

Usage: python3 deploy/setup_hermes.py [--create-new-channel]
"""

import argparse
import getpass
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

try:
    import requests
except ImportError:
    print("Missing dependency: requests")
    print("Install with: pip install requests")
    sys.exit(1)

HERMES_VERSION = "v1.13.2"
HERMES_HOME = Path.home() / ".mirage" / "hermes"
ROOT_DIR = Path(__file__).resolve().parent.parent

# Minimum balances
MIN_MIRAGE = 1_000_000  # 1 MIRAGE
MIN_OSMO = 100_000_000  # 100 OSMO

# BIP39 wordlist
BIP39_WORDLIST_URL = "https://raw.githubusercontent.com/bitcoin/bips/master/bip-0039/english.txt"
_BIP39_WORDS = None


def get_bip39_wordlist() -> list[str]:
    global _BIP39_WORDS
    if _BIP39_WORDS is None:
        cache_path = Path("/tmp/bip39_english.txt")
        if cache_path.exists():
            _BIP39_WORDS = cache_path.read_text().strip().split("\n")
        else:
            try:
                resp = requests.get(BIP39_WORDLIST_URL, timeout=10)
                resp.raise_for_status()
                _BIP39_WORDS = resp.text.strip().split("\n")
                cache_path.write_text(resp.text)
            except Exception:
                _BIP39_WORDS = []
    return _BIP39_WORDS


def validate_mnemonic(mnemonic: str) -> tuple[bool, str]:
    words = mnemonic.strip().lower().split()
    if len(words) != 12:
        return False, f"Expected 12 words, got {len(words)}"

    wordlist = get_bip39_wordlist()
    if wordlist:
        for i, word in enumerate(words):
            if word not in wordlist:
                return False, f"Word {i+1} '{word}' is not a valid BIP39 word"
    return True, ""


def run(cmd: list[str], capture: bool = False, check: bool = True) -> subprocess.CompletedProcess:
    """Run a command."""
    return subprocess.run(cmd, capture_output=capture, text=True, check=check)


def get_hermes_version() -> str | None:
    """Get installed hermes version."""
    try:
        result = run(["hermes", "version"], capture=True, check=False)
        match = re.search(r"v\d+\.\d+\.\d+", result.stdout + result.stderr)
        return match.group(0) if match else None
    except FileNotFoundError:
        return None


def install_hermes():
    """Install hermes binary."""
    print(f"    Installing Hermes {HERMES_VERSION}...")
    url = f"https://github.com/informalsystems/hermes/releases/download/{HERMES_VERSION}/hermes-{HERMES_VERSION}-x86_64-unknown-linux-gnu.tar.gz"

    with tempfile.TemporaryDirectory() as tmpdir:
        tarball = Path(tmpdir) / "hermes.tar.gz"
        resp = requests.get(url, timeout=60)
        resp.raise_for_status()
        tarball.write_bytes(resp.content)

        with tarfile.open(tarball, "r:gz") as tar:
            tar.extractall(tmpdir)

        hermes_bin = Path(tmpdir) / "hermes"
        shutil.move(str(hermes_bin), "/usr/local/bin/hermes")
        os.chmod("/usr/local/bin/hermes", 0o755)

    print(f"    Installed: {get_hermes_version()}")


def hermes_cmd(args: list[str], capture: bool = False) -> subprocess.CompletedProcess:
    """Run hermes command with config."""
    config = HERMES_HOME / "config.toml"
    return run(["hermes", "--config", str(config)] + args, capture=capture, check=False)


def get_balance(chain: str, denom: str) -> int:
    """Get balance for relayer key on chain."""
    result = hermes_cmd(["keys", "balance", "--chain", chain, "--key-name", "relayer"], capture=True)
    match = re.search(rf"(\d+)\s+{denom}", result.stdout + result.stderr)
    return int(match.group(1)) if match else 0


def get_address(chain: str, prefix: str) -> str | None:
    """Get relayer address on chain."""
    result = hermes_cmd(["keys", "list", "--chain", chain], capture=True)
    match = re.search(rf"{prefix}[a-z0-9]+", result.stdout + result.stderr)
    return match.group(0) if match else None


def find_osmosis_channel() -> tuple[str | None, str | None]:
    """Find existing IBC channel to Osmosis. Returns (mirage_channel, osmosis_channel)."""
    result = hermes_cmd(["query", "channels", "--chain", "mirage-1"], capture=True)
    channels = re.findall(r"channel-\d+", result.stdout + result.stderr)

    for chan in channels:
        # Get channel info
        chan_result = hermes_cmd(
            ["query", "channel", "end", "--chain", "mirage-1", "--port", "transfer", "--channel", chan], capture=True
        )
        output = chan_result.stdout + chan_result.stderr

        if "state: Open" not in output:
            continue

        # Get connection ID
        conn_match = re.search(r"connection-\d+", output)
        if not conn_match:
            continue
        conn_id = conn_match.group(0)

        # Get client ID from connection
        conn_result = hermes_cmd(
            ["query", "connection", "end", "--chain", "mirage-1", "--connection", conn_id], capture=True
        )
        client_match = re.search(r"07-tendermint-\d+", conn_result.stdout + conn_result.stderr)
        if not client_match:
            continue
        client_id = client_match.group(0)

        # Check if client is for osmosis-1
        client_result = hermes_cmd(
            ["query", "client", "state", "--chain", "mirage-1", "--client", client_id], capture=True
        )
        if "osmosis-1" in client_result.stdout + client_result.stderr:
            # Found it - get counterparty channel
            counterparty_match = re.findall(r"channel-\d+", output)
            osmosis_chan = counterparty_match[-1] if len(counterparty_match) > 1 else None
            return chan, osmosis_chan

    return None, None


def start_hermes_tmux() -> bool:
    """Start hermes in tmux. Returns True if started."""
    # Check if tmux session exists
    result = run(["tmux", "has-session", "-t", "mirage"], capture=True, check=False)
    if result.returncode != 0:
        return False

    # Kill existing hermes window
    run(["tmux", "kill-window", "-t", "mirage:hermes"], capture=True, check=False)

    # Create new window
    log_dir = Path.home() / ".mirage" / "logs" / "hermes"
    log_dir.mkdir(parents=True, exist_ok=True)

    run(["tmux", "new-window", "-t", "mirage", "-n", "hermes", "-c", "/opt/mirage"])
    cmd = f'hermes --config "{HERMES_HOME}/config.toml" start 2>&1 | tee >(cronolog "{log_dir}/hermes-%Y-%m-%d.log")'
    run(["tmux", "send-keys", "-t", "mirage:hermes", cmd, "C-m"])

    time.sleep(2)
    result = run(["pgrep", "-f", "hermes start"], capture=True, check=False)
    return result.returncode == 0


def main():
    parser = argparse.ArgumentParser(description="Hermes IBC relayer setup")
    parser.add_argument(
        "--create-new-channel", action="store_true", help="Allow creation of a NEW IBC channel (use with caution!)"
    )
    args = parser.parse_args()

    print("==> Hermes IBC Relayer Setup")
    print()

    # Create directories
    HERMES_HOME.mkdir(parents=True, exist_ok=True)
    (HERMES_HOME / "keys").mkdir(exist_ok=True)
    print(f"    ✓ Hermes home: {HERMES_HOME}")

    # Get mnemonic
    print()
    mnemonic = getpass.getpass("Enter 12-word mnemonic: ")

    valid, error = validate_mnemonic(mnemonic)
    if not valid:
        print(f"ERROR: {error}")
        return 1
    print("    ✓ Mnemonic valid (12 words)")

    # Check/install hermes
    print()
    print(f"==> Checking Hermes {HERMES_VERSION}...")
    installed = get_hermes_version()
    if installed != HERMES_VERSION:
        print(f"    Current: {installed or 'not installed'}")
        install_hermes()
    else:
        print(f"    Already at {HERMES_VERSION}")

    # Render config
    print()
    print("==> Configuring Hermes...")
    template = ROOT_DIR / "deploy" / "templates" / "hermes" / "config.toml"
    if not template.exists():
        print(f"ERROR: Template not found: {template}")
        return 1

    os.environ["HERMES_KEY_STORE_FOLDER"] = str(HERMES_HOME / "keys")
    result = run(
        ["python3", str(ROOT_DIR / "deploy" / "render_template.py"), str(template), str(HERMES_HOME / "config.toml")],
        check=False,
    )
    if result.returncode != 0:
        print("ERROR: Failed to render config")
        return 1

    # Import keys
    print()
    print("==> Importing keys...")

    with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
        f.write(mnemonic)
        mnemonic_file = f.name

    try:
        print("    Adding mirage-1 key...")
        result = hermes_cmd(
            [
                "keys",
                "add",
                "--chain",
                "mirage-1",
                "--key-name",
                "relayer",
                "--hd-path",
                "m/44'/118'/0'/0/0",
                "--mnemonic-file",
                mnemonic_file,
                "--overwrite",
            ]
        )
        if result.returncode != 0:
            print("ERROR: Failed to add mirage-1 key")
            return 1

        print("    Adding osmosis-1 key...")
        result = hermes_cmd(
            [
                "keys",
                "add",
                "--chain",
                "osmosis-1",
                "--key-name",
                "relayer",
                "--hd-path",
                "m/44'/118'/0'/0/0",
                "--mnemonic-file",
                mnemonic_file,
                "--overwrite",
            ]
        )
        if result.returncode != 0:
            print("ERROR: Failed to add osmosis-1 key")
            return 1
    finally:
        os.unlink(mnemonic_file)

    # Get addresses
    mirage_addr = get_address("mirage-1", "mirage1")
    osmo_addr = get_address("osmosis-1", "osmo1")

    print()
    print("=" * 50)
    print("RELAYER ADDRESSES")
    print("=" * 50)
    print()
    print(f"  Mirage:  {mirage_addr}")
    print(f"  Osmosis: {osmo_addr}")
    print()
    print("=" * 50)
    print()
    print("These addresses need to be funded:")
    print("  - Mirage:  at least 1 MIRAGE")
    print("  - Osmosis: at least 100 OSMO")
    print()

    confirm = input("Continue with setup? [y/N]: ").strip().lower()
    if confirm != "y":
        print("Aborted.")
        return 0

    # Check balances
    print()
    print("==> Checking balances...")
    mirage_bal = get_balance("mirage-1", "umirage")
    osmo_bal = get_balance("osmosis-1", "uosmo")
    print(f"    Mirage:  {mirage_bal} umirage")
    print(f"    Osmosis: {osmo_bal} uosmo")

    # Wait for funding
    if mirage_bal < MIN_MIRAGE or osmo_bal < MIN_OSMO:
        print()
        print("=" * 50)
        print("WAITING FOR FUNDING")
        print("=" * 50)
        print(f"Minimum: 1 MIRAGE ({MIN_MIRAGE} umirage), 100 OSMO ({MIN_OSMO} uosmo)")
        print()
        print(f"Send to: Mirage={mirage_addr}")
        print(f"         Osmosis={osmo_addr}")
        print()
        print("Checking every 30 seconds... (Ctrl+C to abort)")
        print("=" * 50)

        try:
            while mirage_bal < MIN_MIRAGE or osmo_bal < MIN_OSMO:
                time.sleep(30)
                mirage_bal = get_balance("mirage-1", "umirage")
                osmo_bal = get_balance("osmosis-1", "uosmo")
                print(f"    Mirage: {mirage_bal} | Osmosis: {osmo_bal}")
        except KeyboardInterrupt:
            print()
            print("    Skipped funding wait.")

    print("==> Funding complete!")

    # Find or create channel
    print()
    print("==> Checking for existing IBC channel to Osmosis...")
    mirage_channel, osmosis_channel = find_osmosis_channel()

    if mirage_channel:
        print(f"    Found: {mirage_channel} <-> {osmosis_channel}")
    else:
        print()
        print("    " + "=" * 50)
        print("    NO CHANNEL FOUND")
        print("    " + "=" * 50)

        if not args.create_new_channel:
            print()
            print("    No IBC channel to Osmosis exists.")
            print()
            print("    To create one, run with: --create-new-channel")
            print()
            print("    WARNING: Only do this if no channel exists!")
            print("    Creating duplicates breaks the Osmosis asset list.")
            return 1

        print()
        print("    WARNING: You are about to CREATE A NEW IBC CHANNEL.")
        print("    Only do this if no channel exists or clients expired.")
        print()
        confirm = input("    Type 'CREATE' to proceed: ").strip()
        if confirm != "CREATE":
            print("    Aborted.")
            return 1

        print()
        print("==> Creating new IBC channel (2-3 minutes)...")
        result = hermes_cmd(
            [
                "create",
                "channel",
                "--a-chain",
                "mirage-1",
                "--b-chain",
                "osmosis-1",
                "--a-port",
                "transfer",
                "--b-port",
                "transfer",
                "--new-client-connection",
                "--yes",
            ]
        )

        if result.returncode != 0:
            print("ERROR: Failed to create channel")
            return 1

        # Try to find the new channel
        mirage_channel, osmosis_channel = find_osmosis_channel()
        if not mirage_channel:
            mirage_channel = "channel-?"
            osmosis_channel = "channel-?"

        print()
        print("    NEW CHANNEL CREATED")
        print(f"    Mirage: {mirage_channel}")
        print(f"    Osmosis: {osmosis_channel}")
        print()
        print("    ACTION REQUIRED: Update Osmosis asset list!")
        print("    1. Fork github.com/osmosis-labs/assetlists")
        print("    2. Update path to: transfer/{osmosis_channel}/umirage")
        print("    3. Submit PR")

    # Start hermes
    print()
    print("==> Starting Hermes relayer...")

    # Kill existing
    run(["pkill", "-f", "hermes start"], check=False)
    time.sleep(1)

    if start_hermes_tmux():
        print("    Hermes running in tmux window 'hermes'")
        service_mode = "tmux"
    else:
        print()
        print("    Hermes configured! Restart container to start relayer.")
        print("    Run: docker restart mirage")
        service_mode = "pending"

    # Summary
    print()
    print("=" * 50)
    print("SETUP COMPLETE")
    print("=" * 50)
    print()
    print(f"IBC Channel: {mirage_channel} <-> {osmosis_channel}")
    print()
    if service_mode == "tmux":
        print("Relayer running in tmux window 'hermes'")
        print("  View: tmux select-window -t mirage:hermes")
    else:
        print("Relayer configured but NOT running.")
        print("  Start: docker restart mirage")
    print()
    print("Test IBC transfer:")
    print(
        f"  miraged tx ibc-transfer transfer transfer {mirage_channel} <OSMO_ADDR> 1000000umirage --from <KEY> --chain-id mirage-1 --fees 50000umirage"
    )
    print()

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n    Aborted.")
        sys.exit(0)
