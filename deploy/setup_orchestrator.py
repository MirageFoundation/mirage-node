#!/usr/bin/env python3
"""
Orchestrator setup - imports Solana wallet from mnemonic.

Usage: python3 deploy/setup_orchestrator.py
"""

import getpass
import hashlib
import json
import os
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

# BIP39 English wordlist (2048 words)
BIP39_WORDLIST_URL = "https://raw.githubusercontent.com/bitcoin/bips/master/bip-0039/english.txt"
_BIP39_WORDS = None

ORCHESTRATOR_HOME = Path.home() / ".mirage" / "orchestrator"
KEYPAIR_PATH = ORCHESTRATOR_HOME / "solana-keypair.json"
MIN_SOL_BALANCE = 0.1  # Minimum SOL required


def get_bip39_wordlist() -> list[str]:
    """Load BIP39 English wordlist."""
    global _BIP39_WORDS
    if _BIP39_WORDS is None:
        # Try local cache first
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
    """Validate BIP39 mnemonic. Returns (is_valid, error_message)."""
    words = mnemonic.strip().lower().split()
    
    if len(words) != 12:
        return False, f"Expected 12 words, got {len(words)}"
    
    try:
        wordlist = get_bip39_wordlist()
    except Exception as e:
        # If we can't fetch wordlist, skip validation
        print(f"    Warning: Could not fetch BIP39 wordlist: {e}")
        return True, ""
    
    for i, word in enumerate(words):
        if word not in wordlist:
            return False, f"Word {i+1} '{word}' is not a valid BIP39 word"
    
    # Checksum validation (simplified - just check word validity for now)
    return True, ""


def mnemonic_to_seed(mnemonic: str, passphrase: str = "") -> bytes:
    """Derive seed from BIP39 mnemonic using PBKDF2."""
    password = mnemonic.encode("utf-8")
    salt = ("mnemonic" + passphrase).encode("utf-8")
    return hashlib.pbkdf2_hmac("sha512", password, salt, 2048, 64)


def create_solana_keypair(mnemonic: str, path: Path) -> str:
    """Create Solana keypair from mnemonic. Returns base58 address."""
    seed = mnemonic_to_seed(mnemonic.strip().lower())
    
    # Use first 32 bytes as ed25519 seed
    signing_key = SigningKey(seed[:32])
    verify_key = signing_key.verify_key
    
    # Solana keypair format: [32-byte seed, 32-byte pubkey]
    keypair = list(seed[:32]) + list(bytes(verify_key))
    
    # Save keypair
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(keypair, f)
    os.chmod(path, 0o600)
    
    return base58.b58encode(bytes(verify_key)).decode()


def get_solana_balance(address: str, rpc_url: str) -> float | None:
    """Get SOL balance for address. Returns None on error."""
    try:
        resp = requests.post(
            rpc_url,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getBalance",
                "params": [address],
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if "result" in data and "value" in data["result"]:
            lamports = data["result"]["value"]
            return lamports / 1_000_000_000  # Convert lamports to SOL
    except Exception as e:
        print(f"    Warning: Could not check balance: {e}")
    return None


def main():
    print("==> Orchestrator Solana Wallet Setup")
    print()
    
    ORCHESTRATOR_HOME.mkdir(parents=True, exist_ok=True)
    
    if KEYPAIR_PATH.exists():
        print(f"    Keypair already exists: {KEYPAIR_PATH}")
        confirm = input("    Overwrite? [y/N]: ").strip().lower()
        if confirm != "y":
            print("    Aborted.")
            return 0
        print()
    
    # Get RPC URL from env or use default
    rpc_url = os.environ.get("ORCHESTRATOR_SOLANA_RPC", "https://api.mainnet-beta.solana.com")
    
    # Prompt for mnemonic
    mnemonic = getpass.getpass("Enter 12-word Solana mnemonic: ")
    
    # Validate
    valid, error = validate_mnemonic(mnemonic)
    if not valid:
        print(f"ERROR: {error}")
        return 1
    
    print("    ✓ Mnemonic valid")
    
    # Create keypair
    address = create_solana_keypair(mnemonic, KEYPAIR_PATH)
    print(f"    ✓ Keypair saved: {KEYPAIR_PATH}")
    print()
    print("=" * 50)
    print("SOLANA WALLET IMPORTED")
    print("=" * 50)
    print()
    print(f"  Address: {address}")
    print(f"  Keypair: {KEYPAIR_PATH}")
    print()
    
    # Check balance
    print("==> Checking balance...")
    balance = get_solana_balance(address, rpc_url)
    
    if balance is not None:
        print(f"    Balance: {balance:.4f} SOL")
        
        if balance < MIN_SOL_BALANCE:
            print()
            print("=" * 50)
            print("WAITING FOR FUNDING")
            print("=" * 50)
            print(f"Minimum required: {MIN_SOL_BALANCE} SOL")
            print()
            print(f"Send SOL to: {address}")
            print()
            print("Checking every 30 seconds... (Ctrl+C to skip)")
            print("=" * 50)
            
            try:
                while True:
                    time.sleep(30)
                    balance = get_solana_balance(address, rpc_url)
                    if balance is not None:
                        print(f"    Balance: {balance:.4f} SOL")
                        if balance >= MIN_SOL_BALANCE:
                            print("==> Funding complete!")
                            break
            except KeyboardInterrupt:
                print()
                print("    Skipped funding wait.")
    
    print()
    print("=" * 50)
    print("SETUP COMPLETE")
    print("=" * 50)
    print()
    print("The orchestrator will use this wallet for Solana transactions.")
    print("Make sure it has enough SOL for transaction fees (~0.1 SOL).")
    print()
    
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n    Aborted.")
        sys.exit(0)
