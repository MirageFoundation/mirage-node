#!/usr/bin/env python3
import os
import sys
import hmac
import hashlib
import json
import base64
import binascii
from typing import Tuple, List

from mnemonic import Mnemonic
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization


def to_seed(mnemonic: str, passphrase: str = "") -> bytes:
    m = Mnemonic("english")
    return m.to_seed(mnemonic, passphrase=passphrase)


def hmac_sha512(key: bytes, data: bytes) -> bytes:
    return hmac.new(key, data, hashlib.sha512).digest()


def parse_path(path: str) -> List[int]:
    if not path.startswith("m/"):
        raise ValueError("Invalid path")
    elems = path[2:].split("/")
    result = []
    for e in elems:
        if not e.endswith("'"):
            raise ValueError("All path components must be hardened for ed25519 (e.g., 44', 118', 1', i')")
        n = int(e[:-1])
        if n < 0:
            raise ValueError("Negative index in path")
        result.append(0x80000000 | n)
    return result


def slip10_ed25519_derive(seed: bytes, path: str) -> Tuple[bytes, bytes]:
    I = hmac_sha512(b"ed25519 seed", seed)
    k = I[:32]
    c = I[32:]
    for idx in parse_path(path):
        data = b"\x00" + k + idx.to_bytes(4, "big")
        I = hmac_sha512(c, data)
        k = I[:32]
        c = I[32:]
    return k, c


def ed25519_pub_from_seed(seed32: bytes) -> bytes:
    priv = ed25519.Ed25519PrivateKey.from_private_bytes(seed32)
    pub = priv.public_key()
    pub_raw = pub.public_bytes(encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw)
    return pub_raw


def tm_address_from_pub(pubkey32: bytes) -> str:
    sha = hashlib.sha256(pubkey32).digest()
    addr = sha[:20]
    return binascii.hexlify(addr).upper().decode("ascii")


def write_priv_validator(home: str, priv_seed: bytes, pubkey: bytes, force: bool = False) -> bool:
    """Write priv_validator_key.json. Returns True if written, False if skipped."""
    cfg_dir = os.path.join(home, "config")
    os.makedirs(cfg_dir, exist_ok=True)
    out_path = os.path.join(cfg_dir, "priv_validator_key.json")
    if os.path.exists(out_path) and not force:
        return False
    priv_bytes = priv_seed + pubkey  # 32 + 32
    data = {
        "address": tm_address_from_pub(pubkey),
        "pub_key": {"type": "tendermint/PubKeyEd25519", "value": base64.b64encode(pubkey).decode("ascii")},
        "priv_key": {"type": "tendermint/PrivKeyEd25519", "value": base64.b64encode(priv_bytes).decode("ascii")},
    }
    with open(out_path, "w") as f:
        json.dump(data, f, indent=2)
    os.chmod(out_path, 0o600)
    return True


def main():
    import argparse
    import os

    # Node home is always ~/.mirage/node (hardcoded)
    home = os.path.join(os.environ.get("HOME", "/root"), ".mirage", "node")

    parser = argparse.ArgumentParser(description="Derive consensus key from mnemonic")
    parser.add_argument("--passphrase", default="", help="BIP39 passphrase (optional)")
    parser.add_argument("--index", type=int, default=0, help="Derivation index (default: 0)")
    parser.add_argument("--force", action="store_true", help="Overwrite existing key file")
    args = parser.parse_args()

    passphrase = args.passphrase
    idx = args.index

    if idx < 0:
        print("Derivation index must be >= 0", file=sys.stderr)
        sys.exit(1)

    # Read mnemonic: from stdin if piped, otherwise prompt
    if sys.stdin.isatty():
        import getpass

        mnemonic = getpass.getpass("Enter 12-word mnemonic: ").strip()
    else:
        mnemonic = sys.stdin.read().strip()
    if not mnemonic:
        print("Empty mnemonic", file=sys.stderr)
        sys.exit(1)

    # Path: m/44'/118'/1'/i'
    path = f"m/44'/118'/1'/{idx}'"
    seed = to_seed(mnemonic, passphrase=passphrase)
    sk, _ = slip10_ed25519_derive(seed, path)
    pk = ed25519_pub_from_seed(sk)

    # Always print the derived key
    pk_b64 = base64.b64encode(pk).decode("ascii")
    print(f"Path: {path}")
    print(f"Pubkey: {pk_b64}")

    # Write file (skip if exists and no --force)
    out_path = os.path.join(home, "config", "priv_validator_key.json")
    if write_priv_validator(home, sk, pk, force=args.force):
        print(f"Written: {out_path}")
    else:
        print(f"Skipped: {out_path} already exists (use --force to overwrite)")


if __name__ == "__main__":
    main()
