#!/usr/bin/env python3
"""
Orchestrator setup - imports or generates Solana wallet.

Usage: python3 deploy/setup_orchestrator.py
"""

import getpass
import hashlib
import json
import os
import secrets
import subprocess
import sys
import time
from pathlib import Path

try:
    import base58
    import requests
    from nacl.signing import SigningKey
except ImportError as e:
    print(f"Missing dependency: {e}")
    print("Install with: pip install base58 pynacl requests")
    sys.exit(1)

# Constants
BIP39_WORDLIST_URL = "https://raw.githubusercontent.com/bitcoin/bips/master/bip-0039/english.txt"
_BIP39_WORDS = None

MIRAGED_BIN = Path("/opt/mirage/blockchain/bin/miraged")
NODE_HOME = Path.home() / ".mirage" / "node"
ORCHESTRATOR_HOME = Path.home() / ".mirage" / "orchestrator"
ORCHESTRATOR_REGISTRY = Path.home() / ".orchestrator"
KEYPAIR_PATH = ORCHESTRATOR_HOME / "solana-keypair.json"
MIN_SOL_BALANCE = 0.1
VALOPER_PREFIX = "miragevaloper1"

# Box drawing
LINE = "─" * 58
BOX_TOP = "┌" + LINE + "┐"
BOX_BOT = "└" + LINE + "┘"
BOX_MID = "│"


def box(title: str) -> None:
    """Print a section header."""
    print()
    print(BOX_TOP)
    print(f"│ {title:<56} │")
    print(BOX_BOT)


def info(label: str, value: str) -> None:
    """Print a labeled value."""
    print(f"  {label:<20} {value}")


def ok(msg: str) -> None:
    """Print success message."""
    print(f"  [ok] {msg}")


def err(msg: str) -> None:
    """Print error message."""
    print(f"  [error] {msg}")


def warn(msg: str) -> None:
    """Print warning message."""
    print(f"  [warn] {msg}")


# ─────────────────────────────────────────────────────────────────────────────
# Chain queries
# ─────────────────────────────────────────────────────────────────────────────


def get_local_validator_address() -> str | None:
    """Get validator address from local node keyring."""
    if not MIRAGED_BIN.exists() or not NODE_HOME.exists():
        return None
    try:
        result = subprocess.run(
            [
                str(MIRAGED_BIN),
                "keys",
                "show",
                "validator",
                "--home",
                str(NODE_HOME),
                "--keyring-backend",
                "test",
                "--bech",
                "val",
                "-a",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            addr = result.stdout.strip()
            if addr.startswith(VALOPER_PREFIX):
                return addr
    except Exception:
        pass
    return None


def get_validator_stake(valoper: str) -> int | None:
    """Get validator's staked tokens from chain."""
    if not MIRAGED_BIN.exists() or not NODE_HOME.exists():
        return None
    try:
        result = subprocess.run(
            [
                str(MIRAGED_BIN),
                "q",
                "staking",
                "validator",
                valoper,
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
            validator = data.get("validator", data)
            tokens = validator.get("tokens")
            if tokens:
                return int(tokens)
    except Exception:
        pass
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Solana
# ─────────────────────────────────────────────────────────────────────────────


def get_solana_balance(address: str, rpc_url: str) -> float | None:
    """Get SOL balance for address."""
    try:
        resp = requests.post(
            rpc_url,
            json={"jsonrpc": "2.0", "id": 1, "method": "getBalance", "params": [address]},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if "result" in data and "value" in data["result"]:
            return data["result"]["value"] / 1_000_000_000
    except Exception:
        pass
    return None


# ─────────────────────────────────────────────────────────────────────────────
# BIP39 / Key derivation
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
    """Validate BIP39 mnemonic."""
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


def generate_mnemonic() -> str:
    """Generate a new 12-word BIP39 mnemonic."""
    wordlist = get_bip39_wordlist()
    entropy = secrets.token_bytes(16)
    checksum = hashlib.sha256(entropy).digest()[0] >> 4
    entropy_int = int.from_bytes(entropy, "big")
    combined = (entropy_int << 4) | checksum
    words = []
    for i in range(12):
        shift = (11 - i) * 11
        index = (combined >> shift) & 0x7FF
        words.append(wordlist[index])
    return " ".join(words)


def mnemonic_to_seed(mnemonic: str, passphrase: str = "") -> bytes:
    """Derive seed from BIP39 mnemonic using PBKDF2."""
    password = mnemonic.encode("utf-8")
    salt = ("mnemonic" + passphrase).encode("utf-8")
    return hashlib.pbkdf2_hmac("sha512", password, salt, 2048, 64)


def derive_slip10_ed25519(seed: bytes, path: list[int]) -> bytes:
    """Derive ed25519 key using SLIP-10."""
    import hmac

    I = hmac.new(b"ed25519 seed", seed, hashlib.sha512).digest()
    key, chain_code = I[:32], I[32:]
    for index in path:
        data = b"\x00" + key + index.to_bytes(4, "big")
        I = hmac.new(chain_code, data, hashlib.sha512).digest()
        key, chain_code = I[:32], I[32:]
    return key


def mnemonic_to_pubkey(mnemonic: str) -> str:
    """Derive Solana public key from mnemonic without saving."""
    seed = mnemonic_to_seed(mnemonic.strip().lower())
    HARDENED = 0x80000000
    derivation_path = [44 | HARDENED, 501 | HARDENED, 0 | HARDENED, 0 | HARDENED]
    private_key_seed = derive_slip10_ed25519(seed, derivation_path)
    signing_key = SigningKey(private_key_seed)
    verify_key = signing_key.verify_key
    return base58.b58encode(bytes(verify_key)).decode()


def create_solana_keypair(mnemonic: str, path: Path) -> str:
    """Create Solana keypair from mnemonic (Phantom-compatible BIP44)."""
    seed = mnemonic_to_seed(mnemonic.strip().lower())
    HARDENED = 0x80000000
    derivation_path = [44 | HARDENED, 501 | HARDENED, 0 | HARDENED, 0 | HARDENED]
    private_key_seed = derive_slip10_ed25519(seed, derivation_path)
    signing_key = SigningKey(private_key_seed)
    verify_key = signing_key.verify_key
    keypair = list(private_key_seed) + list(bytes(verify_key))
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(keypair, f)
    os.chmod(path, 0o600)
    return base58.b58encode(bytes(verify_key)).decode()


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────


def main():
    box("ORCHESTRATOR SETUP")

    # ── Step 1: Detect validator ──────────────────────────────────────────────
    print()
    print("  Detecting local validator...")
    validator = get_local_validator_address()
    if not validator:
        err("Could not detect validator address")
        print()
        print("  This script must be run on a node with a configured validator.")
        print("  Ensure miraged keyring has a 'validator' key at ~/.mirage/node/")
        return 1
    ok(f"Validator: {validator}")

    # ── Step 2: Get validator stake ───────────────────────────────────────────
    print()
    print("  Querying validator stake...")
    stake = get_validator_stake(validator)
    if stake is None:
        err("Could not query validator stake from chain")
        print()
        print("  Ensure the node is running and synced.")
        return 1
    ok(f"Stake: {stake:,} umirage")

    # ── Step 3: Check existing keypair ────────────────────────────────────────
    ORCHESTRATOR_HOME.mkdir(parents=True, exist_ok=True)

    if KEYPAIR_PATH.exists():
        print()
        warn(f"Keypair exists: {KEYPAIR_PATH}")
        confirm = input("  Overwrite? [y/N]: ").strip().lower()
        if confirm != "y":
            print("  Aborted.")
            return 0

    # ── Step 4: Import or generate wallet ─────────────────────────────────────
    box("SOLANA WALLET")
    print()
    print("  [i] Import existing mnemonic")
    print("  [g] Generate new wallet")
    print()
    choice = input("  Select [i/g]: ").strip().lower()

    if choice == "g":
        try:
            mnemonic = generate_mnemonic()
            pubkey = mnemonic_to_pubkey(mnemonic)
        except Exception as e:
            err(f"Failed to generate wallet: {e}")
            return 1

        box("SAVE THIS INFORMATION")
        print()
        print(f"  Seed phrase: {mnemonic}")
        print(f"  Public key:  {pubkey}")
        print()
        print(f"  Derivation:  BIP44 (Phantom-compatible)")
        print()
        print(f"  Fund this wallet with at least {MIN_SOL_BALANCE} SOL to cover transaction fees.")
        print(f"  You can import the seed into Phantom to check balance or send funds.")
        print()
        print(BOX_TOP)
        print("│ WARNING                                                  │")
        print("│   - This is the ONLY time the seed phrase will be shown  │")
        print("│   - Write it down and store it securely                  │")
        print("│   - Do NOT reuse for other orchestrator nodes            │")
        print(BOX_BOT)
        print()
        confirm = input("  Saved the seed phrase? [y/N]: ").strip().lower()
        if confirm != "y":
            print("  Aborted.")
            return 1
    else:
        print()
        print("  NOTE: This mnemonic must be UNIQUE to this node.")
        print()
        mnemonic = getpass.getpass("  Enter 12-word mnemonic: ")
        valid, error = validate_mnemonic(mnemonic)
        if not valid:
            err(error)
            return 1
        ok("Mnemonic valid")

    # ── Step 5: Create keypair ────────────────────────────────────────────────
    address = create_solana_keypair(mnemonic, KEYPAIR_PATH)
    ok(f"Keypair saved: {KEYPAIR_PATH}")

    # ── Step 6: Check balance ─────────────────────────────────────────────────
    rpc_url = os.environ.get("ORCHESTRATOR_SOLANA_RPC", "https://api.mainnet-beta.solana.com")
    print()
    print("  Checking Solana balance...")
    balance = get_solana_balance(address, rpc_url)

    if balance is not None:
        ok(f"Balance: {balance:.4f} SOL")
        if balance < MIN_SOL_BALANCE:
            print()
            warn(f"Low balance (min {MIN_SOL_BALANCE} SOL recommended)")
            print(f"  Send SOL to: {address}")
            print()
            print("  Waiting for funding... (Ctrl+C to skip)")
            try:
                while True:
                    time.sleep(30)
                    balance = get_solana_balance(address, rpc_url)
                    if balance is not None:
                        print(f"  Balance: {balance:.4f} SOL")
                        if balance >= MIN_SOL_BALANCE:
                            ok("Funding complete")
                            break
            except KeyboardInterrupt:
                print()
                warn("Skipped funding wait")
    else:
        warn("Could not check balance")

    # ── Step 7: Save config ───────────────────────────────────────────────────
    ORCHESTRATOR_REGISTRY.mkdir(parents=True, exist_ok=True)
    config_path = ORCHESTRATOR_REGISTRY / f"{validator}.json"
    config = {
        "orchestratorPubkey": address,
        "mirageValidator": validator,
        "stake": stake,
    }
    config_json = json.dumps(config, indent=2)
    with open(config_path, "w") as f:
        f.write(config_json)
        f.write("\n")
    os.chmod(config_path, 0o600)

    # ── Step 8: Start orchestrator ────────────────────────────────────────────
    box("STARTING ORCHESTRATOR")
    print()
    
    orchestrator_bin = "/opt/mirage/blockchain/bin/orchestrator"
    if not Path(orchestrator_bin).exists():
        warn(f"Orchestrator binary not found at {orchestrator_bin}")
        print("  Run deploy to build the orchestrator binary.")
        return 1
    
    # Kill any existing orchestrator
    print("  Stopping existing orchestrator...")
    subprocess.run(["pkill", "-TERM", "-f", "blockchain/bin/orchestrator"], 
                   capture_output=True)
    time.sleep(1)
    
    # Start orchestrator in tmux
    print("  Starting orchestrator in tmux...")
    logs_dir = "/var/log/mirage/orchestrator"
    Path(logs_dir).mkdir(parents=True, exist_ok=True)
    
    result = subprocess.run(
        ["tmux", "send-keys", "-t", "mirage:orchestrator", 
         f"{orchestrator_bin} 2>&1 | tee >(cronolog \"{logs_dir}/orchestrator-%Y-%m-%d.log\")", "C-m"],
        capture_output=True
    )
    
    if result.returncode == 0:
        ok("Orchestrator started")
    else:
        # tmux window might not exist, try creating it
        subprocess.run(["tmux", "new-window", "-t", "mirage", "-n", "orchestrator"], capture_output=True)
        subprocess.run(
            ["tmux", "send-keys", "-t", "mirage:orchestrator",
             f"{orchestrator_bin} 2>&1 | tee >(cronolog \"{logs_dir}/orchestrator-%Y-%m-%d.log\")", "C-m"],
            capture_output=True
        )
        ok("Orchestrator started (new window)")
    
    print()
    print("  View logs: tmux attach -t mirage:orchestrator")
    print()

    # ── Done ──────────────────────────────────────────────────────────────────
    box("SETUP COMPLETE")
    print()
    print(f"  Config saved: {config_path}")
    print()
    
    # Also save to .mirage/orchestrator for convenience
    mirage_orchestrator_dir = Path.home() / ".mirage" / "orchestrator"
    mirage_orchestrator_dir.mkdir(parents=True, exist_ok=True)
    mirage_config_path = mirage_orchestrator_dir / "validator-config.json"
    with open(mirage_config_path, "w") as f:
        f.write(config_json)
        f.write("\n")
    
    box("VALIDATOR REGISTRATION")
    print()
    print("  Send this config to the bridge administrator:")
    print()
    print(config_json)
    print()
    print(f"  Also saved to: {mirage_config_path}")
    print()
    print(BOX_TOP)
    print("│ NEXT STEPS                                               │")
    print("│                                                          │")
    print("│ 1. Copy the JSON above (or from the saved file)          │")
    print("│ 2. Send it to the bridge administrator                   │")
    print("│ 3. They will add it to: scripts/validators/<name>.json   │")
    print("│ 4. They will run: bun run bridge:validators              │")
    print("│                                                          │")
    print("│ Your orchestrator will NOT work until registered!        │")
    print(BOX_BOT)
    print()

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n  Aborted.")
        sys.exit(0)
