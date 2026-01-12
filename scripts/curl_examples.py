#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import sys
import time
from typing import Any, Dict, Tuple

import requests

try:
    from argon2.low_level import hash_secret_raw as _argon2_hash_raw, Type as _Argon2Type
except Exception:
    _argon2_hash_raw = None
    _Argon2Type = None

from cosmpy.aerial.wallet import LocalWallet
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.backends import default_backend

from shared.canon import (
    canon_signed_with_pow,
    uvarint,
    canon_base_set_username,
    canon_base_post,
    canon_base_edit,
    canon_base_vote,
    canon_base_follow_moderator,
    canon_base_unfollow_moderator,
    canon_base_follow_user,
    canon_base_unfollow_user,
    canon_base_follow_topic,
    canon_base_unfollow_topic,
    canon_base_block_post,
    canon_base_unblock_post,
    canon_base_block_user,
    canon_base_unblock_user,
    canon_base_delete,
    canon_base_send_tokens,
    canon_base_upgrade_level,
    canon_base_set_auto_renewal,
    canon_base_report,
)


def _die(msg: str, code: int = 1) -> None:
    print(f"error: {msg}", file=sys.stderr)
    raise SystemExit(code)


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def _hex_to_bytes(s: str) -> bytes:
    t = (s or "").strip().lower()
    if t.startswith("0x"):
        t = t[2:]
    if len(t) % 2 != 0:
        _die("last_block_hash must be even-length hex")
    try:
        return bytes.fromhex(t)
    except Exception:
        _die("last_block_hash must be hex")
        return b""


def _count_leading_zero_bits(b: bytes) -> int:
    total = 0
    for by in b:
        if by == 0:
            total += 8
            continue
        for i in range(7, -1, -1):
            if ((by >> i) & 1) == 0:
                total += 1
            else:
                return total
    return total


def _argon2id_digest(password: bytes, salt: bytes) -> bytes:
    if _argon2_hash_raw is None:
        _die("argon2-cffi is required (missing argon2.low_level.hash_secret_raw)")
    return _argon2_hash_raw(
        password,
        salt,
        time_cost=1,
        memory_cost=4096,
        parallelism=1,
        hash_len=32,
        type=_Argon2Type.ID,
    )


def compute_pow(base: bytes, difficulty_bits: int, last_block_hash_hex: str, *, max_seconds: float) -> int:
    if difficulty_bits <= 0:
        _die("compute_pow called with difficulty_bits <= 0")
    salt = _hex_to_bytes(last_block_hash_hex)
    start = time.time()
    proof = 0
    while True:
        if (time.time() - start) > max_seconds:
            _die(f"pow timeout after {max_seconds:.1f}s (difficulty={difficulty_bits})")
        password = base + b":" + uvarint(int(proof))
        digest = _argon2id_digest(password, salt)
        if _count_leading_zero_bits(digest) >= int(difficulty_bits):
            return int(proof)
        proof += 1


def sign_compact_64(privkey32: bytes, signed_bytes: bytes) -> bytes:
    priv_key_int = int.from_bytes(privkey32, "big")
    priv_key = ec.derive_private_key(priv_key_int, ec.SECP256K1(), default_backend())
    sig_der = priv_key.sign(signed_bytes, ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(sig_der)

    # low-S normalize
    n = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
    half_n = n // 2
    if s > half_n:
        s = n - s

    r_b = r.to_bytes(32, "big")
    s_b = s.to_bytes(32, "big")
    return r_b + s_b


def _get_json(url: str, *, timeout: float = 10.0) -> dict:
    try:
        r = requests.get(url, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        _die(f"GET {url} failed: {e}")
        return {}


def _api_base_from_args(api_base: str | None, node_domain: str | None) -> str:
    if api_base and api_base.strip():
        return api_base.strip().rstrip("/")
    if node_domain and node_domain.strip():
        nd = node_domain.strip().rstrip("/")
        if nd.startswith("http://") or nd.startswith("https://"):
            return f"{nd}/api"
        return f"https://{nd}/api"
    _die("must provide either --api-base or --node-domain")
    return ""


def _wallet_from_mnemonic(mnemonic: str) -> Tuple[LocalWallet, str, bytes, bytes]:
    w = LocalWallet.from_mnemonic(mnemonic, prefix="mirage")
    addr = str(w.address()).lower()
    pub = bytes(w.public_key().public_key_bytes)
    priv = bytes(w.signer().private_key_bytes)
    if len(pub) != 33:
        _die(f"expected 33-byte compressed pubkey, got {len(pub)} bytes")
    if len(priv) != 32:
        _die(f"expected 32-byte privkey, got {len(priv)} bytes")
    return w, addr, pub, priv


def _get_user_level(api_base: str, address: str) -> int:
    data = _get_json(f"{api_base}/get_user_status?address={address}")
    try:
        return int(data.get("user_level", 0) or 0)
    except Exception:
        return 0


def _get_pow_params(api_base: str, address: str) -> Tuple[str, int]:
    data = _get_json(f"{api_base}/get_parameters?address={address}")
    last = str(data.get("last_block_hash", "") or "").strip().lower()
    diff = int(data.get("pow_difficulty", 0) or 0)
    if not last:
        _die("get_parameters returned empty last_block_hash")
    if diff <= 0:
        _die("get_parameters returned non-positive pow_difficulty")
    return last, diff


def build_meta_signed_request(
    api_base: str,
    *,
    mnemonic: str,
    base_bytes: bytes,
    timestamp_ms: int,
    last_block_hash: str,
    message_fields: Dict[str, Any],
    force_pow: bool,
    force_no_pow: bool,
    require_pow: bool,
    pow_max_seconds: float,
) -> Dict[str, Any]:
    _, addr, pub, priv = _wallet_from_mnemonic(mnemonic)
    ts_ms = int(timestamp_ms)
    lb = str(last_block_hash or "").strip().lower()
    if not lb:
        _die("last_block_hash is required")

    if require_pow and force_no_pow:
        _die("this operation requires PoW, but --force-no-pow was set")

    use_pow = False
    if require_pow:
        use_pow = True
    elif force_pow:
        use_pow = True
    elif force_no_pow:
        use_pow = False
    else:
        level = _get_user_level(api_base, addr)
        is_paid = level >= 1
        use_pow = not is_paid

    if use_pow:
        # Difficulty MUST match what's encoded in base_bytes tag 4
        difficulty = int(message_fields.get("pow_difficulty") or 0)
        if difficulty <= 0:
            _die("pow_difficulty must be > 0 when PoW is enabled")
        proof = compute_pow(base_bytes, difficulty, lb, max_seconds=pow_max_seconds)
    else:
        difficulty = 0
        proof = 0

    signed = canon_signed_with_pow(base_bytes, int(proof))
    sig64 = sign_compact_64(priv, signed)

    out: Dict[str, Any] = {
        "pubkey": _b64(pub),
        "signature": _b64(sig64),
        "last_block_hash": lb,
        "timestamp": ts_ms,
        "pow_difficulty": int(difficulty),
        "pow": int(proof),
        **{k: v for k, v in message_fields.items() if k not in ("pow",)},
    }
    return out


def main() -> None:
    p = argparse.ArgumentParser(description="Generate Mirage meta-signed JSON payloads for curl/RN testing.")
    p.add_argument("--api-base", default="", help="Example: https://mirage.vote/api")
    p.add_argument("--node-domain", default="", help="Example: mirage.vote (implies https://<domain>/api)")
    p.add_argument("--mnemonic", required=True, help="BIP39 mnemonic (never send to backend)")
    p.add_argument("--pow-max-seconds", type=float, default=60.0, help="Fail if PoW takes longer than this")
    p.add_argument("--force-pow", action="store_true", help="Force PoW even if user is paid (not accepted by most endpoints)")
    p.add_argument("--force-no-pow", action="store_true", help="Force no PoW even if user is free (will fail on-chain)")

    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("set-username")
    sp.add_argument("--username", required=True)
    sp.add_argument("--referrer", default="")

    sp = sub.add_parser("post")
    sp.add_argument("--topic", required=True)
    sp.add_argument("--title", required=True)
    sp.add_argument("--content", required=True)
    sp.add_argument("--tag", default="")

    sp = sub.add_parser("comment")
    sp.add_argument("--parent", required=True, help="Parent post txhash (64 hex)")
    sp.add_argument("--content", required=True)

    sp = sub.add_parser("edit")
    sp.add_argument("--override", required=True, help="Txhash being edited")
    sp.add_argument("--target", default="", help="Parent txhash if editing a comment, else empty")
    sp.add_argument("--topic", default="", help="Required for root posts, must be empty for comments")
    sp.add_argument("--title", default="")
    sp.add_argument("--content", default="")
    sp.add_argument("--tag", default="")

    sp = sub.add_parser("vote")
    sp.add_argument("--target", required=True, help="Post txhash (64 hex)")
    sp.add_argument("--direction", type=int, required=True, choices=[-1, 0, 1])

    sp = sub.add_parser("follow-moderator")
    sp.add_argument("--moderator", required=True)

    sp = sub.add_parser("unfollow-moderator")
    sp.add_argument("--moderator", required=True)

    sp = sub.add_parser("follow-user")
    sp.add_argument("--user", required=True)

    sp = sub.add_parser("unfollow-user")
    sp.add_argument("--user", required=True)

    sp = sub.add_parser("follow-topic")
    sp.add_argument("--topic", required=True)

    sp = sub.add_parser("unfollow-topic")
    sp.add_argument("--topic", required=True)

    sp = sub.add_parser("block-post")
    sp.add_argument("--target", required=True, help="Post txhash (64 hex)")

    sp = sub.add_parser("unblock-post")
    sp.add_argument("--target", required=True, help="Post txhash (64 hex)")

    sp = sub.add_parser("block-user")
    sp.add_argument("--target", required=True, help="mirage1... address")

    sp = sub.add_parser("unblock-user")
    sp.add_argument("--target", required=True, help="mirage1... address")

    sp = sub.add_parser("delete-post")
    sp.add_argument("--target", required=True, help="Post/comment txhash (64 hex)")

    sp = sub.add_parser("send-tokens")
    sp.add_argument("--target", required=True, help="Recipient address (mirage1...)")
    sp.add_argument("--amount", type=int, required=True, help="Amount in umirage")

    sp = sub.add_parser("upgrade-level")
    sp.add_argument("--level", type=int, required=True, choices=[1, 2, 3])

    sp = sub.add_parser("set-auto-renewal")
    sp.add_argument("--auto-renew", required=True, choices=["true", "false"])

    sp = sub.add_parser("report")
    sp.add_argument("--target", required=True, help="Txhash being reported (64 hex)")
    sp.add_argument("--reason", required=True)

    args = p.parse_args()
    api_base = _api_base_from_args(args.api_base, args.node_domain)

    _, addr, pub, _priv = _wallet_from_mnemonic(args.mnemonic)
    ts_ms = int(time.time() * 1000)
    last_block_hash, chain_diff = _get_pow_params(api_base, addr)
    last_block_hash_bytes = _hex_to_bytes(last_block_hash)

    def _common_flags(require_pow: bool) -> Dict[str, Any]:
        return dict(
            api_base=api_base,
            mnemonic=args.mnemonic,
            force_pow=bool(args.force_pow),
            force_no_pow=bool(args.force_no_pow),
            require_pow=require_pow,
            pow_max_seconds=float(args.pow_max_seconds),
        )

    cmd = args.cmd

    if cmd == "set-username":
        payload = build_meta_signed_request(
            base_bytes=canon_base_set_username(pub, last_block_hash_bytes, int(chain_diff), ts_ms, addr, args.username),
            timestamp_ms=ts_ms,
            last_block_hash=last_block_hash,
            message_fields={
                **{k: v for k, v in {"username": args.username, "referrer": (args.referrer or "").strip().lower()}.items() if v},
                "pow_difficulty": int(chain_diff),
            },
            **_common_flags(require_pow=False),
        )
    elif cmd == "post":
        payload = build_meta_signed_request(
            base_bytes=canon_base_post(pub, last_block_hash_bytes, int(chain_diff), ts_ms, "", args.topic, args.title, args.content, args.tag),
            timestamp_ms=ts_ms,
            last_block_hash=last_block_hash,
            message_fields={"target": "", "topic": args.topic, "title": args.title, "content": args.content, "tag": args.tag, "pow_difficulty": int(chain_diff)},
            **_common_flags(require_pow=False),
        )
    elif cmd == "comment":
        payload = build_meta_signed_request(
            base_bytes=canon_base_post(pub, last_block_hash_bytes, int(chain_diff), ts_ms, args.parent, "", "", args.content, ""),
            timestamp_ms=ts_ms,
            last_block_hash=last_block_hash,
            message_fields={"target": args.parent, "topic": "", "title": "", "content": args.content, "tag": "", "pow_difficulty": int(chain_diff)},
            **_common_flags(require_pow=False),
        )
    elif cmd == "edit":
        payload = build_meta_signed_request(
            base_bytes=canon_base_edit(pub, last_block_hash_bytes, int(chain_diff), ts_ms, args.target or "", args.topic or "", args.title or "", args.content or "", args.tag or "", args.override),
            timestamp_ms=ts_ms,
            last_block_hash=last_block_hash,
            message_fields={
                "target": args.target or "",
                "topic": args.topic or "",
                "title": args.title or "",
                "content": args.content or "",
                "tag": args.tag or "",
                "override": args.override,
                "pow_difficulty": int(chain_diff),
            },
            **_common_flags(require_pow=False),
        )
    elif cmd == "vote":
        payload = build_meta_signed_request(
            base_bytes=canon_base_vote(pub, last_block_hash_bytes, int(chain_diff), ts_ms, args.target, int(args.direction)),
            timestamp_ms=ts_ms,
            last_block_hash=last_block_hash,
            message_fields={"target": args.target, "direction": int(args.direction), "pow_difficulty": int(chain_diff)},
            **_common_flags(require_pow=False),
        )
    elif cmd == "follow-moderator":
        payload = build_meta_signed_request(
            base_bytes=canon_base_follow_moderator(pub, last_block_hash_bytes, int(chain_diff), ts_ms, addr, args.moderator),
            timestamp_ms=ts_ms,
            last_block_hash=last_block_hash,
            message_fields={"moderator": args.moderator, "pow_difficulty": int(chain_diff)},
            **_common_flags(require_pow=False),
        )
    elif cmd == "unfollow-moderator":
        payload = build_meta_signed_request(
            base_bytes=canon_base_unfollow_moderator(pub, last_block_hash_bytes, int(chain_diff), ts_ms, addr, args.moderator),
            timestamp_ms=ts_ms,
            last_block_hash=last_block_hash,
            message_fields={"moderator": args.moderator, "pow_difficulty": int(chain_diff)},
            **_common_flags(require_pow=False),
        )
    elif cmd == "follow-user":
        payload = build_meta_signed_request(
            base_bytes=canon_base_follow_user(pub, last_block_hash_bytes, int(chain_diff), ts_ms, addr, args.user),
            timestamp_ms=ts_ms,
            last_block_hash=last_block_hash,
            message_fields={"target": addr, "user": args.user, "pow_difficulty": int(chain_diff)},
            **_common_flags(require_pow=False),
        )
    elif cmd == "unfollow-user":
        payload = build_meta_signed_request(
            base_bytes=canon_base_unfollow_user(pub, last_block_hash_bytes, int(chain_diff), ts_ms, addr, args.user),
            timestamp_ms=ts_ms,
            last_block_hash=last_block_hash,
            message_fields={"target": addr, "user": args.user, "pow_difficulty": int(chain_diff)},
            **_common_flags(require_pow=False),
        )
    elif cmd == "follow-topic":
        payload = build_meta_signed_request(
            base_bytes=canon_base_follow_topic(pub, last_block_hash_bytes, int(chain_diff), ts_ms, addr, args.topic.lower()),
            timestamp_ms=ts_ms,
            last_block_hash=last_block_hash,
            message_fields={"target": addr, "topic": args.topic.lower(), "pow_difficulty": int(chain_diff)},
            **_common_flags(require_pow=False),
        )
    elif cmd == "unfollow-topic":
        payload = build_meta_signed_request(
            base_bytes=canon_base_unfollow_topic(pub, last_block_hash_bytes, int(chain_diff), ts_ms, addr, args.topic.lower()),
            timestamp_ms=ts_ms,
            last_block_hash=last_block_hash,
            message_fields={"target": addr, "topic": args.topic.lower(), "pow_difficulty": int(chain_diff)},
            **_common_flags(require_pow=False),
        )
    elif cmd == "block-post":
        payload = build_meta_signed_request(
            base_bytes=canon_base_block_post(pub, last_block_hash_bytes, int(chain_diff), ts_ms, args.target.lower()),
            timestamp_ms=ts_ms,
            last_block_hash=last_block_hash,
            message_fields={"target": args.target.lower(), "pow_difficulty": int(chain_diff)},
            **_common_flags(require_pow=False),
        )
    elif cmd == "unblock-post":
        payload = build_meta_signed_request(
            base_bytes=canon_base_unblock_post(pub, last_block_hash_bytes, int(chain_diff), ts_ms, args.target.lower()),
            timestamp_ms=ts_ms,
            last_block_hash=last_block_hash,
            message_fields={"target": args.target.lower(), "pow_difficulty": int(chain_diff)},
            **_common_flags(require_pow=False),
        )
    elif cmd == "block-user":
        payload = build_meta_signed_request(
            base_bytes=canon_base_block_user(pub, last_block_hash_bytes, int(chain_diff), ts_ms, args.target.lower()),
            timestamp_ms=ts_ms,
            last_block_hash=last_block_hash,
            message_fields={"target": args.target.lower(), "pow_difficulty": int(chain_diff)},
            **_common_flags(require_pow=False),
        )
    elif cmd == "unblock-user":
        payload = build_meta_signed_request(
            base_bytes=canon_base_unblock_user(pub, last_block_hash_bytes, int(chain_diff), ts_ms, args.target.lower()),
            timestamp_ms=ts_ms,
            last_block_hash=last_block_hash,
            message_fields={"target": args.target.lower(), "pow_difficulty": int(chain_diff)},
            **_common_flags(require_pow=False),
        )
    elif cmd == "delete-post":
        payload = build_meta_signed_request(
            base_bytes=canon_base_delete(pub, last_block_hash_bytes, int(chain_diff), ts_ms, args.target.lower()),
            timestamp_ms=ts_ms,
            last_block_hash=last_block_hash,
            message_fields={"target": args.target.lower(), "pow_difficulty": int(chain_diff)},
            **_common_flags(require_pow=False),
        )
    elif cmd == "send-tokens":
        payload = build_meta_signed_request(
            base_bytes=canon_base_send_tokens(pub, last_block_hash_bytes, int(chain_diff), ts_ms, addr, args.target.lower(), int(args.amount)),
            timestamp_ms=ts_ms,
            last_block_hash=last_block_hash,
            message_fields={"target": args.target.lower(), "amount": int(args.amount), "pow_difficulty": int(chain_diff)},
            **_common_flags(require_pow=False),
        )
    elif cmd == "upgrade-level":
        payload = build_meta_signed_request(
            base_bytes=canon_base_upgrade_level(pub, last_block_hash_bytes, 0, ts_ms, int(args.level)),
            timestamp_ms=ts_ms,
            last_block_hash=last_block_hash,
            message_fields={"level": int(args.level), "pow_difficulty": 0},
            force_pow=False,
            force_no_pow=True,
            require_pow=False,
            pow_max_seconds=float(args.pow_max_seconds),
        )
    elif cmd == "set-auto-renewal":
        auto = str(args.auto_renew).lower() == "true"
        payload = build_meta_signed_request(
            base_bytes=canon_base_set_auto_renewal(pub, last_block_hash_bytes, 0, ts_ms, bool(auto)),
            timestamp_ms=ts_ms,
            last_block_hash=last_block_hash,
            message_fields={"auto_renew": bool(auto), "pow_difficulty": 0},
            force_pow=False,
            force_no_pow=True,
            require_pow=False,
            pow_max_seconds=float(args.pow_max_seconds),
        )
    elif cmd == "report":
        # As implemented in backend: report requires PoW fields (no paid-user bypass).
        payload = build_meta_signed_request(
            base_bytes=canon_base_report(pub, last_block_hash_bytes, int(chain_diff), ts_ms, args.target.lower(), args.reason),
            timestamp_ms=ts_ms,
            last_block_hash=last_block_hash,
            message_fields={"target": args.target.lower(), "reason": args.reason, "pow_difficulty": int(chain_diff)},
            **_common_flags(require_pow=True),
        )
    else:
        _die(f"unknown command: {cmd}")

    sys.stdout.write(json.dumps(payload, separators=(",", ":"), ensure_ascii=False))
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()


