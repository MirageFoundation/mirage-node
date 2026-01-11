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


def write_priv_validator(home: str, priv_seed: bytes, pubkey: bytes) -> None:
    cfg_dir = os.path.join(home, "config")
    os.makedirs(cfg_dir, exist_ok=True)
    out_path = os.path.join(cfg_dir, "priv_validator_key.json")
    if os.path.exists(out_path):
        raise FileExistsError(f"{out_path} already exists")
    priv_bytes = priv_seed + pubkey  # 32 + 32
    data = {
        "address": tm_address_from_pub(pubkey),
        "pub_key": {"type": "tendermint/PubKeyEd25519", "value": base64.b64encode(pubkey).decode("ascii")},
        "priv_key": {"type": "tendermint/PrivKeyEd25519", "value": base64.b64encode(priv_bytes).decode("ascii")},
    }
    with open(out_path, "w") as f:
        json.dump(data, f, indent=2)
    os.chmod(out_path, 0o600)


def main():
    home = None
    for i, a in enumerate(sys.argv):
        if a == "--home" and i + 1 < len(sys.argv):
            home = sys.argv[i + 1]
    if not home:
        print("Usage: derive_consensus_key.py --home /root/.mirage/main", file=sys.stderr)
        sys.exit(1)

    # Read mnemonic from stdin
    mnemonic = sys.stdin.read().strip()
    if not mnemonic:
        print("Empty mnemonic on stdin", file=sys.stderr)
        sys.exit(1)
    # Parse CLI arguments: [passphrase] [index]
    passphrase = sys.argv[1] if len(sys.argv) > 1 else ""
    idx = 0
    if len(sys.argv) > 2:
        try:
            idx = int(sys.argv[2])
        except ValueError:
            print("Derivation index must be an integer", file=sys.stderr)
            sys.exit(1)
        if idx < 0:
            print("Derivation index must be >= 0", file=sys.stderr)
            sys.exit(1)

    # Path: m/44'/118'/1'/i'
    path = f"m/44'/118'/1'/{idx}'"
    seed = to_seed(mnemonic, passphrase=passphrase)
    sk, _ = slip10_ed25519_derive(seed, path)
    pk = ed25519_pub_from_seed(sk)

    try:
        write_priv_validator(home, sk, pk)
    except FileExistsError as e:
        print(str(e), file=sys.stderr)
        sys.exit(2)

    print("Derived consensus key at", path)


if __name__ == "__main__":
    main()


