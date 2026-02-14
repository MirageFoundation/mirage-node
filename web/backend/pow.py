from __future__ import annotations

"""Proof-of-Work helpers and canonical message base building.

IMPORTANT: These canonical functions do NOT include the authority field (tag 1).
Authority is set separately in the message by the backend to the validator/node address.
Canonical bytes only include envelope fields (2-6) and payload fields (100+).

Functions:
- uvarint(n): Encode unsigned varint (64-bit cap).
- canon_base_set_username(...), canon_base_post(...), canon_base_vote(...): Canon bytes.
- check_pow_target(digest, difficulty_steps, min_difficulty, pow_difficulty_step): Target-based PoW check.
- argon2_digest(base, last_block_hash, proof, ...): Argon2id digest.
- decode_b64(s): Base64 decode convenience.
"""

import base64
import math
from typing import Optional
import re as _re

try:
    from argon2.low_level import hash_secret_raw as _argon2_hash_raw, Type as _Argon2Type
except Exception:
    _argon2_hash_raw = None
    _Argon2Type = None

from shared import canon as canon_shared


def uvarint(n: int) -> bytes:
    n = int(n) & 0xFFFFFFFFFFFFFFFF
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            break
    return bytes(out)


def _hex_to_bytes(s: str) -> bytes:
    """Convert hex string to bytes, returning empty bytes on failure."""
    try:
        return bytes.fromhex(s.strip()) if s else b""
    except Exception:
        return b""


def canon_base_set_username(
    pub_dec: bytes,
    last_block_hash: str,
    difficulty: int,
    timestamp: int,
    target: str,
    username: str,
) -> bytes:
    return canon_shared.canon_base_set_username(
        pub_dec, _hex_to_bytes(last_block_hash), int(difficulty), int(timestamp), target, username
    )


def canon_base_post(
    pub_dec: bytes,
    last_block_hash: str,
    difficulty: int,
    timestamp: int,
    target: str,
    topic: str,
    title: str,
    content: str,
    tag: str = "",
) -> bytes:
    return canon_shared.canon_base_post(
        pub_dec, _hex_to_bytes(last_block_hash), int(difficulty), int(timestamp), target, topic, title, content, tag
    )


def canon_base_edit(
    pub_dec: bytes,
    last_block_hash: str,
    difficulty: int,
    timestamp: int,
    target: str,
    topic: str,
    title: str,
    content: str,
    tag: str,
    override: str,
) -> bytes:
    return canon_shared.canon_base_edit(
        pub_dec,
        _hex_to_bytes(last_block_hash),
        int(difficulty),
        int(timestamp),
        target,
        topic,
        title,
        content,
        tag,
        override,
    )


def canon_base_vote(
    pub_dec: bytes,
    last_block_hash: str,
    difficulty: int,
    timestamp: int,
    target: str,
    direction: int,
) -> bytes:
    return canon_shared.canon_base_vote(
        pub_dec, _hex_to_bytes(last_block_hash), int(difficulty), int(timestamp), target, int(direction)
    )


def canon_base_follow_moderator(
    pub_dec: bytes,
    last_block_hash: str,
    difficulty: int,
    timestamp: int,
    target: str,
    moderator: str,
) -> bytes:
    return canon_shared.canon_base_follow_moderator(
        pub_dec, _hex_to_bytes(last_block_hash), int(difficulty), int(timestamp), target, moderator
    )


def canon_base_unfollow_moderator(
    pub_dec: bytes,
    last_block_hash: str,
    difficulty: int,
    timestamp: int,
    target: str,
    moderator: str,
) -> bytes:
    return canon_shared.canon_base_unfollow_moderator(
        pub_dec, _hex_to_bytes(last_block_hash), int(difficulty), int(timestamp), target, moderator
    )


def canon_base_follow_user(
    pub_dec: bytes,
    last_block_hash: str,
    difficulty: int,
    timestamp: int,
    target: str,
    user: str,
) -> bytes:
    return canon_shared.canon_base_follow_user(
        pub_dec, _hex_to_bytes(last_block_hash), int(difficulty), int(timestamp), target, user
    )


def canon_base_unfollow_user(
    pub_dec: bytes,
    last_block_hash: str,
    difficulty: int,
    timestamp: int,
    target: str,
    user: str,
) -> bytes:
    return canon_shared.canon_base_unfollow_user(
        pub_dec, _hex_to_bytes(last_block_hash), int(difficulty), int(timestamp), target, user
    )


def canon_base_follow_topic(
    pub_dec: bytes,
    last_block_hash: str,
    difficulty: int,
    timestamp: int,
    target: str,
    topic: str,
) -> bytes:
    return canon_shared.canon_base_follow_topic(
        pub_dec, _hex_to_bytes(last_block_hash), int(difficulty), int(timestamp), target, topic
    )


def canon_base_unfollow_topic(
    pub_dec: bytes,
    last_block_hash: str,
    difficulty: int,
    timestamp: int,
    target: str,
    topic: str,
) -> bytes:
    return canon_shared.canon_base_unfollow_topic(
        pub_dec, _hex_to_bytes(last_block_hash), int(difficulty), int(timestamp), target, topic
    )


def canon_base_block_post(
    pub_dec: bytes,
    last_block_hash: str,
    difficulty: int,
    timestamp: int,
    target: str,
) -> bytes:
    return canon_shared.canon_base_block_post(
        pub_dec, _hex_to_bytes(last_block_hash), int(difficulty), int(timestamp), target
    )


def canon_base_unblock_post(
    pub_dec: bytes,
    last_block_hash: str,
    difficulty: int,
    timestamp: int,
    target: str,
) -> bytes:
    return canon_shared.canon_base_unblock_post(
        pub_dec, _hex_to_bytes(last_block_hash), int(difficulty), int(timestamp), target
    )


def canon_base_block_user(
    pub_dec: bytes,
    last_block_hash: str,
    difficulty: int,
    timestamp: int,
    target: str,
) -> bytes:
    return canon_shared.canon_base_block_user(
        pub_dec, _hex_to_bytes(last_block_hash), int(difficulty), int(timestamp), target
    )


def canon_base_unblock_user(
    pub_dec: bytes,
    last_block_hash: str,
    difficulty: int,
    timestamp: int,
    target: str,
) -> bytes:
    return canon_shared.canon_base_unblock_user(
        pub_dec, _hex_to_bytes(last_block_hash), int(difficulty), int(timestamp), target
    )


def canon_base_delete(
    pub_dec: bytes,
    last_block_hash: str,
    difficulty: int,
    timestamp: int,
    target: str,
) -> bytes:
    return canon_shared.canon_base_delete(
        pub_dec, _hex_to_bytes(last_block_hash), int(difficulty), int(timestamp), target
    )


def canon_base_send_tokens(
    pub_dec: bytes,
    last_block_hash: str,
    difficulty: int,
    timestamp: int,
    sender: str,
    target: str,
    amount: int,
) -> bytes:
    return canon_shared.canon_base_send_tokens(
        pub_dec, _hex_to_bytes(last_block_hash), int(difficulty), int(timestamp), sender, target, int(amount)
    )


def canon_base_report(
    pub_dec: bytes,
    last_block_hash: str,
    difficulty: int,
    timestamp: int,
    target: str,
    reason: str,
) -> bytes:
    return canon_shared.canon_base_report(
        pub_dec, _hex_to_bytes(last_block_hash), int(difficulty), int(timestamp), target, reason
    )


def canon_base_upgrade_level(
    pub_dec: bytes,
    last_block_hash: str,
    difficulty: int,
    timestamp: int,
    level: int,
) -> bytes:
    return canon_shared.canon_base_upgrade_level(
        pub_dec, _hex_to_bytes(last_block_hash), int(difficulty), int(timestamp), int(level)
    )


def canon_base_set_auto_renewal(
    pub_dec: bytes,
    last_block_hash: str,
    difficulty: int,
    timestamp: int,
    auto_renew: bool,
) -> bytes:
    return canon_shared.canon_base_set_auto_renewal(
        pub_dec, _hex_to_bytes(last_block_hash), int(difficulty), int(timestamp), bool(auto_renew)
    )


def canon_base_bridge_burn(
    pub_dec: bytes,
    last_block_hash: str,
    difficulty: int,
    timestamp: int,
    destination_chain: str,
    destination_address: str,
    amount: int,
) -> bytes:
    return canon_shared.canon_base_bridge_burn(
        pub_dec,
        _hex_to_bytes(last_block_hash),
        int(difficulty),
        int(timestamp),
        destination_chain,
        destination_address,
        int(amount),
    )


_BASE_DIFFICULTY_FACTOR = 1000
_MAX_SAFE_DIFFICULTY_FACTOR = (1 << 53) - 1


def _round_half_up(value: float) -> int:
    return int(math.floor(value + 0.5))


def _difficulty_factor(difficulty_steps: int, pow_difficulty_step: float) -> int | None:
    if difficulty_steps < 0:
        return None
    if not math.isfinite(pow_difficulty_step) or pow_difficulty_step <= 0 or pow_difficulty_step > 1:
        return None
    if difficulty_steps == 0:
        return _BASE_DIFFICULTY_FACTOR
    try:
        factor = _BASE_DIFFICULTY_FACTOR * math.pow(1.0 + pow_difficulty_step, float(difficulty_steps))
    except Exception:
        return _MAX_SAFE_DIFFICULTY_FACTOR
    if not math.isfinite(factor):
        return _MAX_SAFE_DIFFICULTY_FACTOR
    if factor > _MAX_SAFE_DIFFICULTY_FACTOR:
        return _MAX_SAFE_DIFFICULTY_FACTOR
    rounded = _round_half_up(factor)
    return max(_BASE_DIFFICULTY_FACTOR, rounded)


def check_pow_target(digest: bytes, difficulty_steps: int, min_difficulty: int, pow_difficulty_step: float) -> bool:
    """Check if the Argon2 digest meets the target-based difficulty.

    base_target = 2^(256 - min_difficulty)
    eff_target  = base_target * 1000 // (1000 * (1 + step)^difficulty_steps)
    Pass if int(digest) <= eff_target.
    """
    if min_difficulty <= 0 or min_difficulty > 256:
        return False
    factor = _difficulty_factor(difficulty_steps, pow_difficulty_step)
    if factor is None:
        return False
    base_target = 1 << (256 - min_difficulty)
    eff_target = base_target * _BASE_DIFFICULTY_FACTOR // factor
    return int.from_bytes(digest, "big") <= eff_target


def argon2_digest(
    base: bytes, last_block_hash: str, proof: int, *, time_cost: int = 1, memory_cost: int = 4096, parallelism: int = 1
) -> Optional[bytes]:
    if _argon2_hash_raw is None:
        return None
    try:
        try:
            salt = bytes.fromhex(last_block_hash.strip())
        except Exception:
            salt = last_block_hash.encode("utf-8")
        return _argon2_hash_raw(
            base + b":" + uvarint(int(proof)),
            salt,
            time_cost=time_cost,
            memory_cost=memory_cost,
            parallelism=parallelism,
            hash_len=32,
            type=_Argon2Type.ID,
        )
    except Exception:
        return None


def decode_b64(s: str) -> bytes:
    return base64.b64decode(s)


def decode_any(s: str) -> bytes:
    if not s:
        return b""
    t = s.strip()
    tl = t.lower()
    # Strip common prefixes
    if tl.startswith("0x"):
        t = t[2:]
        tl = t.lower()
    for pref in ("hex:", "hex/", "b64:", "base64:"):
        if tl.startswith(pref):
            t = t[len(pref) :]
            tl = t.lower()
    # Try hex
    if _re.fullmatch(r"(?i)[0-9a-f]+", t) and len(t) % 2 == 0 and len(t) >= 2:
        try:
            return bytes.fromhex(t)
        except Exception:
            pass
    # Base64 / URL-safe base64 with padding fix
    tt = t.replace("-", "+").replace("_", "/")
    pad = len(tt) % 4
    if pad:
        tt += "=" * (4 - pad)
    try:
        return base64.b64decode(tt)
    except Exception:
        try:
            return base64.urlsafe_b64decode(t)
        except Exception:
            return b""


__all__ = [
    "uvarint",
    "canon_base_set_username",
    "canon_base_post",
    "canon_base_edit",
    "canon_base_vote",
    "canon_base_follow_moderator",
    "canon_base_unfollow_moderator",
    "canon_base_follow_user",
    "canon_base_unfollow_user",
    "canon_base_follow_topic",
    "canon_base_unfollow_topic",
    "canon_base_block_post",
    "canon_base_unblock_post",
    "canon_base_block_user",
    "canon_base_unblock_user",
    "canon_base_report",
    "canon_base_delete",
    "canon_base_send_tokens",
    "canon_base_upgrade_level",
    "canon_base_set_auto_renewal",
    "canon_base_bridge_burn",
    "check_pow_target",
    "argon2_digest",
    "decode_b64",
    "decode_any",
    "normalize_compact_signature",
    "normalize_pubkey_compressed",
]


def _parse_der_compact(sig: bytes) -> bytes | None:
    try:
        if not sig or sig[0] != 0x30:
            return None
        idx = 1
        total_len = sig[idx]
        idx += 1
        if total_len + 2 != len(sig):
            # tolerate incorrect total_len; continue best-effort
            pass
        if sig[idx] != 0x02:
            return None
        idx += 1
        r_len = sig[idx]
        idx += 1
        r = sig[idx : idx + r_len]
        idx += r_len
        if sig[idx] != 0x02:
            return None
        idx += 1
        s_len = sig[idx]
        idx += 1
        s = sig[idx : idx + s_len]
        # remove leading zeros and left-pad to 32 bytes
        r = r.lstrip(b"\x00")[-32:]
        s = s.lstrip(b"\x00")[-32:]
        if len(r) > 32 or len(s) > 32:
            return None
        return (b"\x00" * (32 - len(r))) + r + (b"\x00" * (32 - len(s))) + s
    except Exception:
        return None


def normalize_compact_signature(sig: bytes) -> bytes | None:
    if not sig:
        return None
    if len(sig) == 64:
        # Enforce low-S per secp256k1 rules
        try:
            n = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
            r = sig[:32]
            s = sig[32:]
            s_int = int.from_bytes(s, "big")
            half_n = n // 2
            if s_int > half_n:
                s_int = n - s_int
                s = s_int.to_bytes(32, "big")
            return r + s
        except Exception:
            return sig
    if len(sig) == 65:
        # common recoverable format r||s||recId
        return sig[:64]
    if sig[0] == 0x30:
        got = _parse_der_compact(sig)
        if got is None:
            return None
        # low-S normalize
        try:
            n = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
            r = got[:32]
            s = got[32:]
            s_int = int.from_bytes(s, "big")
            half_n = n // 2
            if s_int > half_n:
                s_int = n - s_int
                s = s_int.to_bytes(32, "big")
            return r + s
        except Exception:
            return got
    return None


def normalize_pubkey_compressed(pub: bytes) -> bytes | None:
    try:
        if not pub:
            return None
        if len(pub) == 33 and pub[0] in (2, 3):
            return pub
        if len(pub) == 65 and pub[0] == 4:
            x = pub[1:33]
            y = pub[33:65]
            parity = y[-1] & 1
            prefix = 2 + parity  # 0x02 if even, 0x03 if odd
            return bytes([prefix]) + x
        return None
    except Exception:
        return None
