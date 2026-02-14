#!/usr/bin/env python3
"""
Mirage Backend Attack Tests

Tests both positive (sanity) and negative (attack) scenarios against the backend API.
Uses conda environment: mirage-node

Run: conda activate mirage-node && python tests/attack_tests_backend.py --backend http://127.0.0.1:80
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import math
import random
import string
from dataclasses import dataclass, field
from typing import Optional, Tuple, List
from time import sleep

import requests

# Make repo root importable
THIS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(THIS_DIR, ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from shared.client import (  # noqa: E402
    create_wallet_from_seed,
    get_status,
    get_user_status,
    sign_canonical,
    get_username_from_address,
)
from shared.canon import (  # noqa: E402
    canon_base_set_username as _canon_base_set_username_raw,
    canon_base_post as _canon_base_post_raw,
    canon_base_vote as _canon_base_vote_raw,
    canon_base_send_tokens as _canon_base_send_tokens_raw,
    canon_signed_with_pow,
    canon_base_delete as _canon_base_delete_raw,
    canon_base_follow_moderator as _canon_base_follow_moderator_raw,
    canon_base_unfollow_moderator as _canon_base_unfollow_moderator_raw,
    canon_base_edit as _canon_base_edit_raw,
    canon_base_report as _canon_base_report_raw,
)

# Defaults
DEFAULT_BACKEND = "http://127.0.0.1:80"


@dataclass
class TestResult:
    name: str
    passed: bool
    status_code: Optional[int] = None
    response: Optional[dict] = None
    error: Optional[str] = None
    details: dict = field(default_factory=dict)


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode("utf-8")


def _rand_str(n: int = 8) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))


def _now_ms() -> int:
    return int(time.time() * 1000)


def _lb_bytes(lb_hex: str) -> bytes:
    try:
        return bytes.fromhex(lb_hex.strip())
    except Exception:
        return lb_hex.encode("utf-8")


_LAST_CANON_TS: Optional[int] = None


def _record_ts(ts: int) -> int:
    global _LAST_CANON_TS
    _LAST_CANON_TS = int(ts)
    return _LAST_CANON_TS


def canon_base_post(
    pubkey: bytes,
    last_block_hash_hex: str,
    difficulty: int,
    target: str,
    topic: str,
    title: str,
    content: str,
    tag: str = "",
    pow_val: int = 0,
    timestamp: Optional[int] = None,
    media: list[str] | None = None,
) -> bytes:
    ts = _record_ts(_now_ms() if timestamp is None else int(timestamp))
    return _canon_base_post_raw(
        pubkey,
        _lb_bytes(last_block_hash_hex),
        int(difficulty),
        ts,
        target,
        topic,
        title,
        content,
        tag,
        pow_val,
        media=media,
    )


def canon_base_set_username(
    pubkey: bytes,
    last_block_hash_hex: str,
    difficulty: int,
    target: str,
    username: str,
    timestamp: Optional[int] = None,
) -> bytes:
    ts = _record_ts(_now_ms() if timestamp is None else int(timestamp))
    return _canon_base_set_username_raw(pubkey, _lb_bytes(last_block_hash_hex), int(difficulty), ts, target, username)


def canon_base_vote(
    pubkey: bytes,
    last_block_hash_hex: str,
    difficulty: int,
    target: str,
    direction: int,
    timestamp: Optional[int] = None,
) -> bytes:
    ts = _record_ts(_now_ms() if timestamp is None else int(timestamp))
    return _canon_base_vote_raw(pubkey, _lb_bytes(last_block_hash_hex), int(difficulty), ts, target, int(direction))


def canon_base_follow_moderator(
    pubkey: bytes,
    last_block_hash_hex: str,
    difficulty: int,
    target: str,
    moderator: str,
    timestamp: Optional[int] = None,
) -> bytes:
    ts = _record_ts(_now_ms() if timestamp is None else int(timestamp))
    return _canon_base_follow_moderator_raw(
        pubkey, _lb_bytes(last_block_hash_hex), int(difficulty), ts, target, moderator
    )


def canon_base_unfollow_moderator(
    pubkey: bytes,
    last_block_hash_hex: str,
    difficulty: int,
    target: str,
    moderator: str,
    timestamp: Optional[int] = None,
) -> bytes:
    ts = _record_ts(_now_ms() if timestamp is None else int(timestamp))
    return _canon_base_unfollow_moderator_raw(
        pubkey, _lb_bytes(last_block_hash_hex), int(difficulty), ts, target, moderator
    )


def canon_base_edit(
    pubkey: bytes,
    last_block_hash_hex: str,
    difficulty: int,
    target: str,
    topic: str,
    title: str,
    content: str,
    override: str,
    tag: str = "",
    timestamp: Optional[int] = None,
) -> bytes:
    ts = _record_ts(_now_ms() if timestamp is None else int(timestamp))
    return _canon_base_edit_raw(
        pubkey, _lb_bytes(last_block_hash_hex), int(difficulty), ts, target, topic, title, content, tag, override
    )


def canon_base_delete(
    pubkey: bytes,
    last_block_hash_hex: str,
    difficulty: int,
    target: str,
    timestamp: Optional[int] = None,
) -> bytes:
    ts = _record_ts(_now_ms() if timestamp is None else int(timestamp))
    return _canon_base_delete_raw(pubkey, _lb_bytes(last_block_hash_hex), int(difficulty), ts, target)


def canon_base_report(
    pubkey: bytes,
    last_block_hash_hex: str,
    difficulty: int,
    target: str,
    reason: str,
    timestamp: Optional[int] = None,
) -> bytes:
    ts = _record_ts(_now_ms() if timestamp is None else int(timestamp))
    return _canon_base_report_raw(pubkey, _lb_bytes(last_block_hash_hex), int(difficulty), ts, target, reason)


def canon_base_send_tokens(
    pubkey: bytes,
    last_block_hash_hex: str,
    difficulty: int,
    sender: str,
    target: str,
    amount: int,
    timestamp: Optional[int] = None,
) -> bytes:
    ts = _record_ts(_now_ms() if timestamp is None else int(timestamp))
    return _canon_base_send_tokens_raw(
        pubkey, _lb_bytes(last_block_hash_hex), int(difficulty), ts, sender, target, int(amount)
    )


def build_canon_post(
    pubkey: bytes,
    last_block_hash_hex: str,
    difficulty: int,
    target: str,
    topic: str,
    title: str,
    content: str,
    tag: str = "",
    pow_val: int = 0,
    timestamp: Optional[int] = None,
    media: list[str] | None = None,
) -> tuple[bytes, int]:
    ts = _now_ms() if timestamp is None else int(timestamp)
    base = canon_base_post(
        pubkey,
        last_block_hash_hex,
        int(difficulty),
        target,
        topic,
        title,
        content,
        tag,
        pow_val,
        timestamp=ts,
        media=media,
    )
    return base, ts


def build_canon_set_username(
    pubkey: bytes,
    last_block_hash_hex: str,
    difficulty: int,
    target: str,
    username: str,
    timestamp: Optional[int] = None,
) -> tuple[bytes, int]:
    ts = _now_ms() if timestamp is None else int(timestamp)
    base = canon_base_set_username(pubkey, last_block_hash_hex, int(difficulty), target, username, timestamp=ts)
    return base, ts


def build_canon_vote(
    pubkey: bytes,
    last_block_hash_hex: str,
    difficulty: int,
    target: str,
    direction: int,
    timestamp: Optional[int] = None,
) -> tuple[bytes, int]:
    ts = _now_ms() if timestamp is None else int(timestamp)
    base = canon_base_vote(pubkey, last_block_hash_hex, int(difficulty), target, int(direction), timestamp=ts)
    return base, ts


def build_canon_follow(
    pubkey: bytes,
    last_block_hash_hex: str,
    difficulty: int,
    target: str,
    moderator: str,
    timestamp: Optional[int] = None,
) -> tuple[bytes, int]:
    ts = _now_ms() if timestamp is None else int(timestamp)
    base = canon_base_follow_moderator(pubkey, last_block_hash_hex, int(difficulty), target, moderator, timestamp=ts)
    return base, ts


def build_canon_unfollow(
    pubkey: bytes,
    last_block_hash_hex: str,
    difficulty: int,
    target: str,
    moderator: str,
    timestamp: Optional[int] = None,
) -> tuple[bytes, int]:
    ts = _now_ms() if timestamp is None else int(timestamp)
    base = canon_base_unfollow_moderator(pubkey, last_block_hash_hex, int(difficulty), target, moderator, timestamp=ts)
    return base, ts


def build_canon_edit(
    pubkey: bytes,
    last_block_hash_hex: str,
    difficulty: int,
    target: str,
    topic: str,
    title: str,
    content: str,
    override: str,
    tag: str = "",
    timestamp: Optional[int] = None,
) -> tuple[bytes, int]:
    ts = _now_ms() if timestamp is None else int(timestamp)
    base = canon_base_edit(
        pubkey, last_block_hash_hex, int(difficulty), target, topic, title, content, override, tag=tag, timestamp=ts
    )
    return base, ts


def build_canon_delete(
    pubkey: bytes,
    last_block_hash_hex: str,
    difficulty: int,
    target: str,
    timestamp: Optional[int] = None,
) -> tuple[bytes, int]:
    ts = _now_ms() if timestamp is None else int(timestamp)
    base = canon_base_delete(pubkey, last_block_hash_hex, int(difficulty), target, timestamp=ts)
    return base, ts


def build_canon_report(
    pubkey: bytes,
    last_block_hash_hex: str,
    difficulty: int,
    target: str,
    reason: str,
    timestamp: Optional[int] = None,
) -> tuple[bytes, int]:
    ts = _now_ms() if timestamp is None else int(timestamp)
    base = canon_base_report(pubkey, last_block_hash_hex, int(difficulty), target, reason, timestamp=ts)
    return base, ts


def build_canon_send_tokens(
    pubkey: bytes,
    last_block_hash_hex: str,
    difficulty: int,
    sender: str,
    target: str,
    amount: int,
    timestamp: Optional[int] = None,
) -> tuple[bytes, int]:
    ts = _now_ms() if timestamp is None else int(timestamp)
    base = canon_base_send_tokens(
        pubkey, last_block_hash_hex, int(difficulty), sender, target, int(amount), timestamp=ts
    )
    return base, ts


def _post_json(url: str, payload: dict, timeout: float = 30.0) -> Tuple[int, dict]:
    # Auto-inject the last canonical timestamp if caller omitted it.
    if isinstance(payload, dict) and "timestamp" not in payload and _LAST_CANON_TS is not None:
        payload = dict(payload)
        payload["timestamp"] = _LAST_CANON_TS
    r = requests.post(url, json=payload, timeout=timeout)
    ct = r.headers.get("content-type", "")
    if "application/json" in ct:
        try:
            return r.status_code, r.json()
        except Exception:
            pass
    return r.status_code, {"status": r.status_code, "text": r.text[:300]}


def _get_json(url: str, params: dict | None = None, timeout: float = 10.0) -> Tuple[int, dict]:
    r = requests.get(url, params=params or {}, timeout=timeout)
    ct = r.headers.get("content-type", "")
    if "application/json" in ct:
        try:
            return r.status_code, r.json()
        except Exception:
            pass
    return r.status_code, {"status": r.status_code, "text": r.text[:300]}


def _get_post_votes(backend: str, owner: str, post_tx: str) -> int:
    """Fetch current vote total for a specific post owned by owner."""
    try:
        code, resp = _get_json(
            f"{backend}/api/get_user_posts", {"owner": owner, "address": owner, "limit": 50, "page": 1}
        )
        if code != 200:
            return 0
        posts = (resp or {}).get("posts") or []
        for p in posts:
            if str(p.get("post_id", "")).lower() == str(post_tx).lower():
                return int(p.get("votes", 0) or 0)
        return 0
    except Exception:
        return 0


def _get_post_media(backend: str, owner: str, post_tx: str) -> Optional[list]:
    """Fetch media array for a specific post owned by owner."""
    try:
        code, resp = _get_json(
            f"{backend}/api/get_user_posts", {"owner": owner, "address": owner, "limit": 50, "page": 1}
        )
        if code != 200:
            return None
        posts = (resp or {}).get("posts") or []
        for p in posts:
            if str(p.get("post_id", "")).lower() == str(post_tx).lower():
                return p.get("media")
        return None
    except Exception:
        return None


def _neg_post_topic_invalid(backend: str, seed: str, topic: str, name: str) -> TestResult:
    """Helper: root post with invalid topic should be rejected."""
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        last, diff, min_diff, _ = _fetch_params(backend, addr)
        pub = wallet.public_key().public_key_bytes
        title = "t"
        content = "c"
        base, ts_ms = build_canon_post(pub, last, diff, "", topic, title, content)
        proof = _compute_pow(base, diff, min_diff, last)
        signed = canon_signed_with_pow(base, int(proof))
        sig = sign_canonical(wallet, signed)
        payload = {
            "pubkey": _b64(pub),
            "signature": _b64(sig),
            "last_block_hash": last,
            "timestamp": ts_ms,
            "pow_difficulty": int(diff),
            "pow": int(proof),
            "target": "",
            "topic": topic,
            "title": title,
            "content": content,
        }
        code, resp = _post_json(f"{backend}/api/core/post", payload)
        # Consider it rejected if HTTP >=400 OR tx response has height==0 (not accepted)
        height = (resp or {}).get("height", 0) if isinstance(resp, dict) else 0
        passed = (code >= 400) or (isinstance(height, int) and height <= 0)
        return TestResult(name=name, passed=passed, status_code=code, response=resp, details={"topic": topic})
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


def _expect_fail(resp: dict, status: int, substrings: list[str] | None = None) -> bool:
    if status < 400:
        return False
    if not substrings:
        return True
    txt = json.dumps(resp).lower()
    return any(s.lower() in txt for s in substrings if s)


def wait_tx_result(backend: str, tx_hash: str, timeout_s: float = 15.0, interval_s: float = 0.5) -> Optional[dict]:
    deadline = time.perf_counter() + timeout_s
    url = f"{backend}/api/get_tx_status"
    params = {"hash": tx_hash}
    last = None
    while time.perf_counter() < deadline:
        try:
            r = requests.get(url, params=params, timeout=3.0)
            if r.status_code == 200:
                data = r.json()
                last = data
                if bool(data.get("found")):
                    return data
        except Exception:
            pass
        time.sleep(interval_s)
    return last


def is_post_indexed(backend: str, owner_addr: str, tx_hash: str) -> bool:
    try:
        r = requests.get(f"{backend}/api/get_user_posts", params={"owner": owner_addr, "limit": 50}, timeout=5.0)
        if r.status_code != 200:
            return False
        data = r.json()
        posts = data.get("posts") or []
        h = (tx_hash or "").lower()
        return any((p or {}).get("post_id", "").lower() == h for p in posts)
    except Exception:
        return False


def wait_post_indexed(
    backend: str, owner_addr: str, tx_hash: str, timeout_s: float = 15.0, interval_s: float = 0.5
) -> bool:
    deadline = time.perf_counter() + timeout_s
    while time.perf_counter() < deadline:
        if is_post_indexed(backend, owner_addr, tx_hash):
            return True
        time.sleep(interval_s)
    return False


def _fetch_params(backend: str, address: Optional[str]) -> Tuple[str, int, int, Optional[int]]:
    st = get_status(backend, address=address)
    last_block_hash = str(st.get("last_block_hash", "") or "")
    pow_difficulty = int(st.get("pow_difficulty", 0) or 0)
    pow_base_bits = int(st.get("pow_base_bits", 0) or 0)
    global _POW_FACTOR
    _POW_FACTOR = float(st["pow_factor"])
    balance = int(st["balance"]) if "balance" in st and st["balance"] is not None else None
    return last_block_hash, pow_difficulty, pow_base_bits, balance


def _fetch_foreign_post_id(backend: str, exclude_owner: str) -> Optional[str]:
    try:
        r = requests.get(f"{backend}/api/get_posts", params={"limit": 50}, timeout=5.0)
        if r.status_code != 200:
            return None
        data = r.json()
        posts = data.get("posts") or []
        for p in posts:
            owner = str((p or {}).get("owner", "")).lower()
            pid = str((p or {}).get("post_id", "")).lower()
            if owner and pid and owner != exclude_owner.lower():
                return pid
        return None
    except Exception:
        return None


def _compute_pow(
    base: bytes,
    difficulty: int,
    pow_base_bits: int,
    last_block_hash: str,
    max_seconds: float = 30.0,
    pow_factor: float | None = None,
) -> int:
    try:
        from argon2.low_level import hash_secret_raw as _argon2_hash_raw, Type as _Argon2Type
    except Exception as e:
        raise RuntimeError("argon2-cffi is required for PoW tests") from e
    if difficulty < 0:
        raise ValueError("difficulty must be >= 0")
    if pow_base_bits <= 0 or pow_base_bits > 256:
        raise ValueError("pow_base_bits must be in [1, 256]")
    if pow_factor is None:
        if _POW_FACTOR is None:
            raise ValueError("pow_factor missing")
        pow_factor = _POW_FACTOR

    try:
        salt = bytes.fromhex(last_block_hash.strip())
    except Exception:
        salt = last_block_hash.encode("utf-8")

    start = time.perf_counter()
    proof = 0
    while True:
        digest = _argon2_hash_raw(
            base + b":" + _uvarint(proof),
            salt,
            time_cost=1,
            memory_cost=4096,
            parallelism=1,
            hash_len=32,
            type=_Argon2Type.ID,
        )
        if _check_pow_target(digest, difficulty, pow_base_bits, pow_factor):
            return proof
        if (time.perf_counter() - start) > max_seconds:
            raise TimeoutError(f"PoW mining exceeded {max_seconds:.1f}s")
        proof += 1


def _uvarint(n: int) -> bytes:
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


_BASE_DIFFICULTY_FACTOR = 1000
_MAX_SAFE_DIFFICULTY_FACTOR = (1 << 53) - 1
_POW_FACTOR: float | None = None


def _round_half_up(value: float) -> int:
    return int(math.floor(value + 0.5))


def _difficulty_factor(difficulty: int, pow_factor: float) -> int | None:
    if difficulty < 0:
        return None
    if not math.isfinite(pow_factor) or pow_factor <= 0 or pow_factor > 1:
        return None
    if difficulty == 0:
        return _BASE_DIFFICULTY_FACTOR
    try:
        factor = _BASE_DIFFICULTY_FACTOR * math.pow(1.0 + pow_factor, float(difficulty))
    except Exception:
        return _MAX_SAFE_DIFFICULTY_FACTOR
    if not math.isfinite(factor):
        return _MAX_SAFE_DIFFICULTY_FACTOR
    if factor > _MAX_SAFE_DIFFICULTY_FACTOR:
        return _MAX_SAFE_DIFFICULTY_FACTOR
    rounded = _round_half_up(factor)
    return max(_BASE_DIFFICULTY_FACTOR, rounded)


def _check_pow_target(digest: bytes, difficulty: int, pow_base_bits: int, pow_factor: float) -> bool:
    """Target-based PoW check. difficulty is steps (0=base, 1=+step, 2=+step^2)."""
    if pow_base_bits <= 0 or pow_base_bits > 256:
        return False
    factor = _difficulty_factor(difficulty, pow_factor)
    if factor is None:
        return False
    base_target = 1 << (256 - pow_base_bits)
    eff_target = base_target * _BASE_DIFFICULTY_FACTOR // factor
    return int.from_bytes(digest, "big") <= eff_target


def _print_result(r: TestResult) -> None:
    status = "PASS" if r.passed else "FAIL"
    extra = f" (HTTP {r.status_code})" if r.status_code is not None else ""
    print(f"  {status}: {r.name}{extra}", flush=True)

    # Print details if available
    if r.details:
        separator_printed = False
        output_keys = {"tx_hash", "height", "code", "success", "votes", "raw_log", "found"}
        for k, v in r.details.items():
            if not separator_printed and k in output_keys:
                print(f"       ---", flush=True)
                separator_printed = True
            val = str(v) if v is not None else ""
            print(f"       {k}: {val}", flush=True)

    # For rejections (HTTP >= 400), always show the backend error body
    if (r.status_code is not None and r.status_code >= 400) or not r.passed:
        if r.response:
            try:
                print(f"       response: {json.dumps(r.response)[:200]}", flush=True)
            except Exception:
                print(f"       response: {str(r.response)[:200]}", flush=True)
        if r.error:
            print(f"       error: {r.error}", flush=True)
    # Blank line between tests for readability
    print("", flush=True)


# Poll for username to appear after set_username tx.
def _wait_username(
    backend: str, addr: str, expected: Optional[str], timeout_s: float = 45.0, interval_s: float = 1.0
) -> Optional[str]:
    deadline = time.perf_counter() + timeout_s
    last = None
    while time.perf_counter() < deadline:
        try:
            un = get_username_from_address(backend, addr) or ""
            last = un
            if expected is None:
                if un:
                    return un
            else:
                if un == expected:
                    return un
        except Exception:
            pass
        time.sleep(interval_s)
    return last


# ========================================
# POSITIVE TESTS (Sanity checks)
# ========================================


def pos_create_post(backend: str, seed: str) -> Tuple[TestResult, Optional[str]]:
    """Create a new top-level post."""
    name = "Create post"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        last, diff, min_diff, bal = _fetch_params(backend, addr)
        pub = wallet.public_key().public_key_bytes

        title = f"Test Post {_rand_str(6)}"
        content = f"This is test content created at {int(time.time())}"
        topic = f"topic{_rand_str(5)}"

        base, ts_ms = build_canon_post(pub, last, diff, "", topic, title, content)
        proof = _compute_pow(base, diff, min_diff, last)
        signed = canon_signed_with_pow(base, int(proof))
        sig = sign_canonical(wallet, signed)

        payload = {
            "pubkey": _b64(pub),
            "signature": _b64(sig),
            "last_block_hash": last,
            "timestamp": ts_ms,
            "pow_difficulty": int(diff),
            "pow": int(proof),
            "target": "",
            "topic": topic,
            "title": title,
            "content": content,
        }

        code, resp = _post_json(f"{backend}/api/core/post", payload)

        details = {
            "address": addr,
            "title": title,
            "content": content,
            "topic": topic,
            "pow_difficulty": diff,
            "balance": bal,
        }

        if code != 200 or "tx_hash" not in resp:
            return TestResult(name=name, passed=False, status_code=code, response=resp, details=details), None

        txh = str(resp.get("tx_hash"))
        details["tx_hash"] = txh

        res = wait_tx_result(backend, txh, timeout_s=15.0)
        ok = bool(res) and bool(res.get("found")) and bool(res.get("success"))

        if ok:
            details["height"] = res.get("height")
            wait_post_indexed(backend, addr, txh, timeout_s=15.0)
            try:
                votes_now = _get_post_votes(backend, addr, txh)
                details["votes"] = votes_now
            except Exception:
                pass

        return TestResult(name=name, passed=ok, status_code=code, response=res or resp, details=details), (
            txh if ok else None
        )
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e)), None


def pos_create_post_with_tag(backend: str, seed: str, tag: str) -> Tuple[TestResult, Optional[str]]:
    """Create a new top-level post with a specific content tag."""
    name = f"Create post with tag '{tag}'"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        last, diff, min_diff, bal = _fetch_params(backend, addr)
        pub = wallet.public_key().public_key_bytes

        title = f"Test Post {_rand_str(6)}"
        content = f"Tagged content ({tag}) created at {int(time.time())}"
        topic = f"topic{_rand_str(5)}"

        base, ts_ms = build_canon_post(pub, last, diff, "", topic, title, content, tag=tag)
        proof = _compute_pow(base, diff, min_diff, last)
        signed = canon_signed_with_pow(base, int(proof))
        sig = sign_canonical(wallet, signed)

        payload = {
            "pubkey": _b64(pub),
            "signature": _b64(sig),
            "last_block_hash": last,
            "timestamp": ts_ms,
            "pow_difficulty": int(diff),
            "pow": int(proof),
            "target": "",
            "topic": topic,
            "title": title,
            "content": content,
            "tag": tag,
        }

        code, resp = _post_json(f"{backend}/api/core/post", payload)

        details = {
            "address": addr,
            "tag": tag,
            "topic": topic,
            "pow_difficulty": diff,
            "balance": bal,
        }

        if code != 200 or "tx_hash" not in resp:
            return TestResult(name=name, passed=False, status_code=code, response=resp, details=details), None

        txh = str(resp.get("tx_hash"))
        details["tx_hash"] = txh

        res = wait_tx_result(backend, txh, timeout_s=15.0)
        ok = bool(res) and bool(res.get("found")) and bool(res.get("success"))

        if ok:
            details["height"] = res.get("height")

        return TestResult(name=name, passed=ok, status_code=code, response=res or resp, details=details), (
            txh if ok else None
        )
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e)), None


def pos_create_posts_all_valid_tags(backend: str, seed: str) -> List[TestResult]:
    """Create posts with all valid content tags."""
    valid_tags = ["", "sensitive", "porn", "gore", "violence", "death"]
    results = []
    for tag in valid_tags:
        r, _ = pos_create_post_with_tag(backend, seed, tag)
        results.append(r)
    return results


def pos_create_post_with_media(backend: str, seed: str) -> Tuple[TestResult, Optional[str]]:
    """Create a post with media array (v1.12.0)."""
    name = "Create post with media"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        last, diff, min_diff, bal = _fetch_params(backend, addr)
        pub = wallet.public_key().public_key_bytes

        title = f"Media Post {_rand_str(6)}"
        content = f"Media content created at {int(time.time())}"
        topic = f"topic{_rand_str(5)}"
        media = [
            f"https://example.com/{_rand_str(6)}.jpg",
            f"https://example.com/{_rand_str(6)}.png",
        ]

        base, ts_ms = build_canon_post(pub, last, diff, "", topic, title, content, media=media)
        proof = _compute_pow(base, diff, min_diff, last)
        signed = canon_signed_with_pow(base, int(proof))
        sig = sign_canonical(wallet, signed)

        payload = {
            "pubkey": _b64(pub),
            "signature": _b64(sig),
            "last_block_hash": last,
            "timestamp": ts_ms,
            "pow_difficulty": int(diff),
            "pow": int(proof),
            "target": "",
            "topic": topic,
            "title": title,
            "content": content,
            "tag": "",
            "media": media,
        }

        code, resp = _post_json(f"{backend}/api/core/post", payload)

        details = {
            "address": addr,
            "topic": topic,
            "media_count": len(media),
            "media_expected": media,
            "balance": bal,
        }
        if code != 200 or "tx_hash" not in resp:
            return TestResult(name=name, passed=False, status_code=code, response=resp, details=details), None

        txh = str(resp.get("tx_hash"))
        details["tx_hash"] = txh

        res = wait_tx_result(backend, txh, timeout_s=15.0)
        ok = bool(res) and bool(res.get("found")) and bool(res.get("success"))
        if ok:
            wait_post_indexed(backend, addr, txh, timeout_s=15.0)
            media_val = _get_post_media(backend, addr, txh)
            ok = media_val == media
            details["media_received"] = media_val

        return TestResult(name=name, passed=ok, status_code=code, response=res or resp, details=details), (
            txh if ok else None
        )
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e)), None


def pos_create_comment(backend: str, seed: str, parent_tx: str) -> Tuple[TestResult, Optional[str]]:
    """Create a comment on an existing post."""
    name = "Create comment"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        last, diff, min_diff, _ = _fetch_params(backend, addr)
        pub = wallet.public_key().public_key_bytes

        content = f"Comment at {int(time.time())}"

        base = canon_base_post(pub, last, diff, parent_tx, "", "", content)
        proof = _compute_pow(base, diff, min_diff, last)
        signed = canon_signed_with_pow(base, int(proof))
        sig = sign_canonical(wallet, signed)

        payload = {
            "pubkey": _b64(pub),
            "signature": _b64(sig),
            "last_block_hash": last,
            "pow_difficulty": int(diff),
            "pow": int(proof),
            "target": parent_tx,
            "topic": "",
            "title": "",
            "content": content,
        }

        code, resp = _post_json(f"{backend}/api/core/post", payload)

        details = {
            "parent": parent_tx,
            "content": content,
        }

        if code != 200 or "tx_hash" not in resp:
            return TestResult(name=name, passed=False, status_code=code, response=resp, details=details), None

        txh = str(resp.get("tx_hash"))
        details["tx_hash"] = txh

        res = wait_tx_result(backend, txh, timeout_s=15.0)
        ok = bool(res) and bool(res.get("found")) and bool(res.get("success"))
        if ok:
            details["height"] = res.get("height")

        return TestResult(name=name, passed=ok, status_code=code, response=res or resp, details=details), (
            txh if ok else None
        )
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e)), None


def neg_comment_missing_content(backend: str, seed: str, parent_tx: str) -> TestResult:
    """Comment without content should be rejected."""
    name = "Comment: missing content rejected"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        last, diff, min_diff, _ = _fetch_params(backend, addr)
        pub = wallet.public_key().public_key_bytes

        content = ""
        base = canon_base_post(pub, last, diff, parent_tx, "", "", content)
        proof = _compute_pow(base, diff, min_diff, last)
        signed = canon_signed_with_pow(base, int(proof))
        sig = sign_canonical(wallet, signed)

        payload = {
            "pubkey": _b64(pub),
            "signature": _b64(sig),
            "last_block_hash": last,
            "pow_difficulty": int(diff),
            "pow": int(proof),
            "target": parent_tx,
            "topic": "",
            "title": "",
            "content": content,
        }
        code, resp = _post_json(f"{backend}/api/core/post", payload)
        details = {"parent": parent_tx, "content_len": len(content)}
        return TestResult(name=name, passed=(code == 400), status_code=code, response=resp, details=details)
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


def pos_vote_upvote(backend: str, seed: str, target_tx: str) -> TestResult:
    """Upvote a post."""
    name = "Upvote post"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        last, diff, min_diff, _ = _fetch_params(backend, addr)
        pub = wallet.public_key().public_key_bytes

        base = canon_base_vote(pub, last, diff, target_tx, 1)
        proof = _compute_pow(base, diff, min_diff, last)
        signed = canon_signed_with_pow(base, int(proof))
        sig = sign_canonical(wallet, signed)

        payload = {
            "pubkey": _b64(pub),
            "signature": _b64(sig),
            "last_block_hash": last,
            "pow_difficulty": int(diff),
            "pow": int(proof),
            "target": target_tx,
            "direction": 1,
        }

        code, resp = _post_json(f"{backend}/api/core/vote", payload)

        # Verify vote total increased appropriately will be done by caller or here via helper
        details = {
            "target": target_tx,
            "direction": 1,
        }

        if code != 200 or "tx_hash" not in resp:
            return TestResult(name=name, passed=False, status_code=code, response=resp, details=details)

        txh = str(resp.get("tx_hash"))
        details["tx_hash"] = txh

        res = wait_tx_result(backend, txh, timeout_s=15.0)
        ok = bool(res) and bool(res.get("found")) and bool(res.get("success"))
        if ok:
            details["height"] = res.get("height")
            # verify votes increased to +1 relative to clear step
            try:
                addr = str(wallet.address())
                votes_now = _get_post_votes(backend, addr, target_tx)
                details["votes"] = votes_now
            except Exception:
                pass

        return TestResult(name=name, passed=ok, status_code=code, response=res or resp, details=details)
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


def pos_vote_downvote(backend: str, seed: str, target_tx: str) -> TestResult:
    """Downvote a post."""
    name = "Downvote post"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        last, diff, min_diff, _ = _fetch_params(backend, addr)
        pub = wallet.public_key().public_key_bytes

        base = canon_base_vote(pub, last, diff, target_tx, -1)
        proof = _compute_pow(base, diff, min_diff, last)
        signed = canon_signed_with_pow(base, int(proof))
        sig = sign_canonical(wallet, signed)

        payload = {
            "pubkey": _b64(pub),
            "signature": _b64(sig),
            "last_block_hash": last,
            "pow_difficulty": int(diff),
            "pow": int(proof),
            "target": target_tx,
            "direction": -1,
        }

        code, resp = _post_json(f"{backend}/api/core/vote", payload)

        details = {
            "target": target_tx,
            "direction": -1,
        }

        if code != 200 or "tx_hash" not in resp:
            return TestResult(name=name, passed=False, status_code=code, response=resp, details=details)

        txh = str(resp.get("tx_hash"))
        details["tx_hash"] = txh

        res = wait_tx_result(backend, txh, timeout_s=15.0)
        ok = bool(res) and bool(res.get("found")) and bool(res.get("success"))
        if ok:
            details["height"] = res.get("height")
            try:
                addr = str(wallet.address())
                votes_now = _get_post_votes(backend, addr, target_tx)
                details["votes"] = votes_now
            except Exception:
                pass

        return TestResult(name=name, passed=ok, status_code=code, response=res or resp, details=details)
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


def pos_vote_clear(backend: str, seed: str, target_tx: str) -> TestResult:
    """Clear existing vote (direction=0)."""
    name = "Clear vote"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        last, diff, min_diff, _ = _fetch_params(backend, addr)
        pub = wallet.public_key().public_key_bytes

        base = canon_base_vote(pub, last, diff, target_tx, 0)
        proof = _compute_pow(base, diff, min_diff, last)
        signed = canon_signed_with_pow(base, int(proof))
        sig = sign_canonical(wallet, signed)

        payload = {
            "pubkey": _b64(pub),
            "signature": _b64(sig),
            "last_block_hash": last,
            "pow_difficulty": int(diff),
            "pow": int(proof),
            "target": target_tx,
            "direction": 0,
        }

        code, resp = _post_json(f"{backend}/api/core/vote", payload)
        details = {"target": target_tx, "direction": 0}
        if code != 200 or "tx_hash" not in resp:
            return TestResult(name=name, passed=False, status_code=code, response=resp, details=details)

        txh = str(resp.get("tx_hash"))
        details["tx_hash"] = txh
        res = wait_tx_result(backend, txh, timeout_s=15.0)
        ok = bool(res) and bool(res.get("found")) and bool(res.get("success"))
        if ok:
            details["height"] = res.get("height")
            try:
                votes_now = _get_post_votes(backend, addr, target_tx)
                details["votes"] = votes_now
            except Exception:
                pass
        return TestResult(name=name, passed=ok, status_code=code, response=res or resp, details=details)
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


def pos_edit_post(backend: str, seed: str, override_tx: str) -> TestResult:
    """Edit an existing post."""
    name = "Edit post"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())

        # Wait for the post to be indexed first
        if not wait_post_indexed(backend, addr, override_tx, timeout_s=15.0):
            return TestResult(name=name, passed=False, error="post not indexed yet", details={"override": override_tx})

        last, diff, min_diff, _ = _fetch_params(backend, addr)
        pub = wallet.public_key().public_key_bytes

        new_content = f"Edited content at {int(time.time())}"
        new_topic = f"topic{_rand_str(4)}"

        base = canon_base_edit(pub, last, diff, "", new_topic, "", new_content, override_tx)
        proof = _compute_pow(base, diff, min_diff, last)
        signed = canon_signed_with_pow(base, int(proof))
        sig = sign_canonical(wallet, signed)

        payload = {
            "pubkey": _b64(pub),
            "signature": _b64(sig),
            "last_block_hash": last,
            "pow_difficulty": int(diff),
            "pow": int(proof),
            "target": "",
            "topic": new_topic,
            "title": "",
            "content": new_content,
            "override": override_tx,
        }

        code, resp = _post_json(f"{backend}/api/core/edit", payload)

        details = {
            "override": override_tx,
            "new_content": new_content[:40],
            "new_topic": new_topic,
        }

        if code != 200 or "tx_hash" not in resp:
            return TestResult(name=name, passed=False, status_code=code, response=resp, details=details)

        txh = str(resp.get("tx_hash"))
        details["tx_hash"] = txh

        res = wait_tx_result(backend, txh, timeout_s=15.0)
        ok = bool(res) and bool(res.get("found")) and bool(res.get("success"))
        if ok:
            details["height"] = res.get("height")

        return TestResult(name=name, passed=ok, status_code=code, response=res or resp, details=details)
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


def pos_delete_post(backend: str, seed: str, target_tx: str) -> TestResult:
    """Delete own post."""
    name = "Delete own post"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        last, diff, min_diff, _ = _fetch_params(backend, addr)
        pub = wallet.public_key().public_key_bytes

        base = canon_base_delete(pub, last, diff, target_tx)
        proof = _compute_pow(base, diff, min_diff, last)
        signed = canon_signed_with_pow(base, int(proof))
        sig = sign_canonical(wallet, signed)

        payload = {
            "pubkey": _b64(pub),
            "signature": _b64(sig),
            "last_block_hash": last,
            "pow_difficulty": int(diff),
            "pow": int(proof),
            "target": target_tx,
        }

        code, resp = _post_json(f"{backend}/api/core/delete_post", payload)

        details = {
            "address": addr,
            "target": target_tx,
            "pow_difficulty": diff,
            "last_block_hash": last,
        }

        if code != 200 or "tx_hash" not in resp:
            return TestResult(name=name, passed=False, status_code=code, response=resp, details=details)

        txh = str(resp.get("tx_hash"))
        details["tx_hash"] = txh

        res = wait_tx_result(backend, txh, timeout_s=15.0)
        ok = bool(res) and bool(res.get("found")) and bool(res.get("success"))
        if ok:
            details["height"] = res.get("height")

        return TestResult(name=name, passed=ok, status_code=code, response=res or resp, details=details)
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


def pos_set_username(backend: str, seed: str) -> TestResult:
    """Set a username."""
    name = "Set username"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        last, diff, min_diff, _ = _fetch_params(backend, addr)
        pub = wallet.public_key().public_key_bytes

        # Allow hyphens + lowercase alphanumeric
        username = f"user-{_rand_str(4)}-{_rand_str(4)}"

        base, ts_ms = build_canon_set_username(pub, last, diff, addr, username)
        proof = _compute_pow(base, diff, min_diff, last)
        signed = canon_signed_with_pow(base, int(proof))
        sig = sign_canonical(wallet, signed)

        payload = {
            "pubkey": _b64(pub),
            "signature": _b64(sig),
            "last_block_hash": last,
            "timestamp": ts_ms,
            "pow_difficulty": int(diff),
            "pow": int(proof),
            "username": username,
        }

        code, resp = _post_json(f"{backend}/api/core/set_username", payload)

        details = {
            "username": username,
        }

        if code != 200 or "tx_hash" not in resp:
            return TestResult(name=name, passed=False, status_code=code, response=resp, details=details)

        txh = str(resp.get("tx_hash"))
        details["tx_hash"] = txh

        res = wait_tx_result(backend, txh, timeout_s=15.0)
        ok = bool(res) and bool(res.get("found")) and bool(res.get("success"))
        if ok:
            details["height"] = res.get("height")

        # Verify final username stored on chain (via backend).
        # For FREE user, chain prefixes with "Anon-".
        try:
            expected = f"Anon-{username}"
            final_un = _wait_username(backend, addr, expected)
            details["final_username"] = final_un
            if final_un != expected:
                return TestResult(name=name, passed=False, status_code=code, response=res or resp, details=details)
        except Exception:
            pass
        return TestResult(name=name, passed=ok, status_code=code, response=res or resp, details=details)
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


def pos_follow_moderator(backend: str, seed: str, moderator_addr: str) -> TestResult:
    """Follow a moderator."""
    name = "Follow moderator"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        last, diff, min_diff, _ = _fetch_params(backend, addr)
        pub = wallet.public_key().public_key_bytes

        base, ts_ms = build_canon_follow(pub, last, diff, addr, moderator_addr)
        proof = _compute_pow(base, diff, min_diff, last)
        signed = canon_signed_with_pow(base, int(proof))
        sig = sign_canonical(wallet, signed)

        payload = {
            "pubkey": _b64(pub),
            "signature": _b64(sig),
            "last_block_hash": last,
            "timestamp": ts_ms,
            "pow_difficulty": int(diff),
            "pow": int(proof),
            "target": addr,
            "moderator": moderator_addr,
        }

        code, resp = _post_json(f"{backend}/api/core/follow_moderator", payload)

        details = {
            "moderator": moderator_addr,
        }

        if code != 200 or "tx_hash" not in resp:
            return TestResult(name=name, passed=False, status_code=code, response=resp, details=details)

        txh = str(resp.get("tx_hash"))
        details["tx_hash"] = txh

        res = wait_tx_result(backend, txh, timeout_s=15.0)
        ok = bool(res) and bool(res.get("found")) and bool(res.get("success"))
        if ok:
            details["height"] = res.get("height")

        return TestResult(name=name, passed=ok, status_code=code, response=res or resp, details=details)
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


def pos_unfollow_moderator(backend: str, seed: str, moderator_addr: str) -> TestResult:
    """Unfollow a moderator."""
    name = "Unfollow moderator"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        last, diff, min_diff, _ = _fetch_params(backend, addr)
        pub = wallet.public_key().public_key_bytes

        base, ts_ms = build_canon_unfollow(pub, last, diff, addr, moderator_addr)
        proof = _compute_pow(base, diff, min_diff, last)
        signed = canon_signed_with_pow(base, int(proof))
        sig = sign_canonical(wallet, signed)

        payload = {
            "pubkey": _b64(pub),
            "signature": _b64(sig),
            "last_block_hash": last,
            "timestamp": ts_ms,
            "pow_difficulty": int(diff),
            "pow": int(proof),
            "target": addr,
            "moderator": moderator_addr,
        }

        code, resp = _post_json(f"{backend}/api/core/unfollow_moderator", payload)

        details = {
            "moderator": moderator_addr,
        }

        if code != 200 or "tx_hash" not in resp:
            return TestResult(name=name, passed=False, status_code=code, response=resp, details=details)

        txh = str(resp.get("tx_hash"))
        details["tx_hash"] = txh

        res = wait_tx_result(backend, txh, timeout_s=15.0)
        ok = bool(res) and bool(res.get("found")) and bool(res.get("success"))
        if ok:
            details["height"] = res.get("height")

        return TestResult(name=name, passed=ok, status_code=code, response=res or resp, details=details)
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


def pos_report_post(backend: str, seed: str, target_tx: str) -> TestResult:
    """Report a post (stored in local DB, not on chain)."""
    name = "Report post"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        last, diff, min_diff, _ = _fetch_params(backend, addr)
        pub = wallet.public_key().public_key_bytes

        reason = "Test report"

        # Report has its own canonical base (no direction)
        base = canon_base_report(pub, last, diff, target_tx, reason)
        proof = _compute_pow(base, diff, min_diff, last)
        signed = canon_signed_with_pow(base, int(proof))
        sig = sign_canonical(wallet, signed)

        payload = {
            "pubkey": _b64(pub),
            "signature": _b64(sig),
            "last_block_hash": last,
            "pow_difficulty": int(diff),
            "pow": int(proof),
            "target": target_tx,
            "reason": reason,
        }

        code, resp = _post_json(f"{backend}/api/core/report", payload)

        details = {
            "address": addr,
            "target": target_tx,
            "reason": reason,
            "pow_difficulty": diff,
            "last_block_hash": last,
        }

        # Report returns success directly, not tx_hash
        ok = code == 200 and bool(resp.get("success"))

        return TestResult(name=name, passed=ok, status_code=code, response=resp, details=details)
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


# ========================================
# SUBSCRIPTION TESTS
# ========================================


def pos_upgrade_to_level(backend: str, seed: str, level: int = 1) -> TestResult:
    """Upgrade subscription level using tokens (no PoW)."""
    name = f"Upgrade to level {level}"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        last, diff, min_diff, _ = _fetch_params(backend, addr)
        pub = wallet.public_key().public_key_bytes

        # No PoW for upgrade_level
        from shared.canon import canon_base_upgrade_level as _canon_upgrade

        ts_ms = int(time.time() * 1000)
        base = _canon_upgrade(pub, bytes.fromhex(last), 0, ts_ms, int(level))
        signed = canon_signed_with_pow(base, 0)
        sig = sign_canonical(wallet, signed)
        payload = {
            "pubkey": _b64(pub),
            "signature": _b64(sig),
            "last_block_hash": last,
            "pow_difficulty": 0,
            "pow": 0,
            "timestamp": ts_ms,
            "level": int(level),
        }
        code, resp = _post_json(f"{backend}/api/core/upgrade_level", payload)
        return TestResult(name=name, passed=(code == 200 and "tx_hash" in resp), status_code=code, response=resp)
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


def neg_upgrade_insufficient_funds(backend: str, seed: str, level: int) -> TestResult:
    """Attempt to upgrade with an account that lacks sufficient funds."""
    name = f"Upgrade to level {level}: insufficient funds rejected"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        last, _diff, _min_diff, _ = _fetch_params(backend, addr)
        pub = wallet.public_key().public_key_bytes
        from shared.canon import canon_base_upgrade_level as _canon_upgrade

        ts_ms = int(time.time() * 1000)
        base = _canon_upgrade(pub, bytes.fromhex(last), 0, ts_ms, int(level))
        signed = canon_signed_with_pow(base, 0)
        sig = sign_canonical(wallet, signed)
        payload = {
            "pubkey": _b64(pub),
            "signature": _b64(sig),
            "last_block_hash": last,
            "pow_difficulty": 0,
            "pow": 0,
            "timestamp": ts_ms,
            "level": int(level),
        }
        code, resp = _post_json(f"{backend}/api/core/upgrade_level", payload)
        # Expect backend balance precheck
        passed = _expect_fail(resp, code, ["insufficient balance"])
        return TestResult(name=name, passed=passed, status_code=code, response=resp)
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


def neg_upgrade_invalid_level(backend: str, seed: str, level: int = 100) -> TestResult:
    """Attempt to upgrade to an invalid level."""
    name = f"Upgrade to level {level}: invalid level rejected"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        last, _diff, _min_diff, _ = _fetch_params(backend, addr)
        pub = wallet.public_key().public_key_bytes
        from shared.canon import canon_base_upgrade_level as _canon_upgrade

        ts_ms = int(time.time() * 1000)
        base = _canon_upgrade(pub, bytes.fromhex(last), 0, ts_ms, int(level))
        signed = canon_signed_with_pow(base, 0)
        sig = sign_canonical(wallet, signed)
        payload = {
            "pubkey": _b64(pub),
            "signature": _b64(sig),
            "last_block_hash": last,
            "pow_difficulty": 0,
            "pow": 0,
            "timestamp": ts_ms,
            "level": int(level),
        }
        code, resp = _post_json(f"{backend}/api/core/upgrade_level", payload)
        passed = _expect_fail(resp, code, ["invalid level"])
        return TestResult(name=name, passed=passed, status_code=code, response=resp)
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


def neg_subscriber_pow_post(backend: str, seed: str) -> TestResult:
    """As a subscriber, attempting to include PoW should be rejected by backend."""
    name = "Subscriber: PoW not allowed rejected"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        last, diff, min_diff, _ = _fetch_params(backend, addr)
        pub = wallet.public_key().public_key_bytes

        base = canon_base_post(pub, last, diff, "", "topicok", "ok", "content")
        proof = _compute_pow(base, diff, min_diff, last)
        signed = canon_signed_with_pow(base, int(proof))
        sig = sign_canonical(wallet, signed)
        payload = {
            "pubkey": _b64(pub),
            "signature": _b64(sig),
            "last_block_hash": last,
            "pow_difficulty": int(diff),
            "pow": int(proof),
            "target": "",
            "topic": "topicok",
            "title": "ok",
            "content": "content",
        }
        code, resp = _post_json(f"{backend}/api/core/post", payload)
        return TestResult(name=name, passed=(code == 400), status_code=code, response=resp)
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


def pos_subscriber_post_no_pow(backend: str, seed: str) -> Tuple[TestResult, Optional[str]]:
    """As a subscriber, create a post without PoW (allowed)."""
    name = "Subscriber: create post without PoW"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        last, diff, min_diff, _ = _fetch_params(backend, addr)
        pub = wallet.public_key().public_key_bytes

        topic = f"topic{_rand_str(4)}"
        title = "okay"
        content = f"sub content at {int(time.time())}"

        base = canon_base_post(pub, last, 0, "", topic, title, content)
        signed = canon_signed_with_pow(base, 0)
        sig = sign_canonical(wallet, signed)
        payload = {
            "pubkey": _b64(pub),
            "signature": _b64(sig),
            # Provide last_block_hash so backend uses it as nonce and the signature matches
            "last_block_hash": last,
            "pow_difficulty": 0,
            "pow": 0,
            "target": "",
            "topic": topic,
            "title": title,
            "content": content,
        }
        code, resp = _post_json(f"{backend}/api/core/post", payload)
        details = {"topic": topic, "title": title, "content": content}
        if code != 200 or "tx_hash" not in resp:
            return TestResult(name=name, passed=False, status_code=code, response=resp, details=details), None
        txh = str(resp.get("tx_hash"))
        details["tx_hash"] = txh
        res = wait_tx_result(backend, txh, timeout_s=15.0)
        ok = bool(res) and bool(res.get("found")) and bool(res.get("success"))
        if ok:
            details["height"] = res.get("height")
        return TestResult(name=name, passed=ok, status_code=code, response=res or resp, details=details), (
            txh if ok else None
        )
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e)), None


def sub_pos_vote(backend: str, seed: str, target_tx: str, direction: int, label: str) -> TestResult:
    """Subscriber vote without PoW."""
    name = f"Subscriber: {label}"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        last, _diff, _min_diff, _ = _fetch_params(backend, addr)
        pub = wallet.public_key().public_key_bytes
        base = canon_base_vote(pub, last, 0, target_tx, int(direction))
        signed = canon_signed_with_pow(base, 0)
        sig = sign_canonical(wallet, signed)
        payload = {
            "pubkey": _b64(pub),
            "signature": _b64(sig),
            "last_block_hash": last,
            "pow_difficulty": 0,
            "pow": 0,
            "target": target_tx,
            "direction": int(direction),
        }
        code, resp = _post_json(f"{backend}/api/core/vote", payload)
        details = {"target": target_tx, "direction": int(direction)}
        if code != 200 or "tx_hash" not in resp:
            return TestResult(name=name, passed=False, status_code=code, response=resp, details=details)
        txh = str(resp.get("tx_hash"))
        details["tx_hash"] = txh
        res = wait_tx_result(backend, txh, timeout_s=15.0)
        ok = bool(res) and bool(res.get("found")) and bool(res.get("success"))
        if ok:
            details["height"] = res.get("height")
        return TestResult(name=name, passed=ok, status_code=code, response=res or resp, details=details)
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


def sub_pos_create_comment(backend: str, seed: str, parent_tx: str) -> Tuple[TestResult, Optional[str]]:
    """Subscriber creates a comment without PoW."""
    name = "Subscriber: create comment"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        last, _diff, _min_diff, _ = _fetch_params(backend, addr)
        pub = wallet.public_key().public_key_bytes
        content = f"sub comment at {int(time.time())}"
        base = canon_base_post(pub, last, 0, parent_tx, "", "", content)
        signed = canon_signed_with_pow(base, 0)
        sig = sign_canonical(wallet, signed)
        payload = {
            "pubkey": _b64(pub),
            "signature": _b64(sig),
            "last_block_hash": last,
            "pow_difficulty": 0,
            "pow": 0,
            "target": parent_tx,
            "topic": "",
            "title": "",
            "content": content,
        }
        code, resp = _post_json(f"{backend}/api/core/post", payload)
        details = {"parent": parent_tx, "content": content}
        if code != 200 or "tx_hash" not in resp:
            return TestResult(name=name, passed=False, status_code=code, response=resp, details=details), None
        txh = str(resp.get("tx_hash"))
        details["tx_hash"] = txh
        res = wait_tx_result(backend, txh, timeout_s=15.0)
        ok = bool(res) and bool(res.get("found")) and bool(res.get("success"))
        if ok:
            details["height"] = res.get("height")
        return TestResult(name=name, passed=ok, status_code=code, response=res or resp, details=details), (
            txh if ok else None
        )
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e)), None


def sub_pos_edit_post(backend: str, seed: str, override_tx: str) -> TestResult:
    """Subscriber edits own post without PoW."""
    name = "Subscriber: edit post"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        if not wait_post_indexed(backend, addr, override_tx, timeout_s=15.0):
            return TestResult(name=name, passed=False, error="post not indexed yet", details={"override": override_tx})
        last, _diff, _min_diff, _ = _fetch_params(backend, addr)
        pub = wallet.public_key().public_key_bytes
        new_content = f"Sub edited at {int(time.time())}"
        new_topic = f"topic{_rand_str(4)}"
        base = canon_base_edit(pub, last, 0, "", new_topic, "", new_content, override_tx)
        signed = canon_signed_with_pow(base, 0)
        sig = sign_canonical(wallet, signed)
        payload = {
            "pubkey": _b64(pub),
            "signature": _b64(sig),
            "last_block_hash": last,
            "pow_difficulty": 0,
            "pow": 0,
            "target": "",
            "topic": new_topic,
            "title": "",
            "content": new_content,
            "override": override_tx,
        }
        code, resp = _post_json(f"{backend}/api/core/edit", payload)
        details = {"override": override_tx, "new_content": new_content[:40], "new_topic": new_topic}
        if code != 200 or "tx_hash" not in resp:
            return TestResult(name=name, passed=False, status_code=code, response=resp, details=details)
        txh = str(resp.get("tx_hash"))
        details["tx_hash"] = txh
        res = wait_tx_result(backend, txh, timeout_s=15.0)
        ok = bool(res) and bool(res.get("found")) and bool(res.get("success"))
        if ok:
            details["height"] = res.get("height")
        return TestResult(name=name, passed=ok, status_code=code, response=res or resp, details=details)
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


def sub_pos_delete_post(backend: str, seed: str, target_tx: str) -> TestResult:
    """Subscriber deletes own post without PoW."""
    name = "Subscriber: delete own post"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        last, _diff, _min_diff, _ = _fetch_params(backend, addr)
        pub = wallet.public_key().public_key_bytes
        base = canon_base_delete(pub, last, 0, target_tx)
        signed = canon_signed_with_pow(base, 0)
        sig = sign_canonical(wallet, signed)
        payload = {
            "pubkey": _b64(pub),
            "signature": _b64(sig),
            "last_block_hash": last,
            "pow_difficulty": 0,
            "pow": 0,
            "target": target_tx,
        }
        code, resp = _post_json(f"{backend}/api/core/delete_post", payload)
        details = {"target": target_tx}
        if code != 200 or "tx_hash" not in resp:
            return TestResult(name=name, passed=False, status_code=code, response=resp, details=details)
        txh = str(resp.get("tx_hash"))
        details["tx_hash"] = txh
        res = wait_tx_result(backend, txh, timeout_s=15.0)
        ok = bool(res) and bool(res.get("found")) and bool(res.get("success"))
        if ok:
            details["height"] = res.get("height")
        return TestResult(name=name, passed=ok, status_code=code, response=res or resp, details=details)
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


def sub_pos_set_username(backend: str, seed: str) -> TestResult:
    """Subscriber sets username without PoW."""
    name = "Subscriber: set username"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        last, _diff, _min_diff, _ = _fetch_params(backend, addr)
        pub = wallet.public_key().public_key_bytes
        # Allow hyphens + lowercase alphanumeric
        username = f"sub-{_rand_str(4)}-{_rand_str(4)}"
        base, ts_ms = build_canon_set_username(pub, last, 0, addr, username)
        signed = canon_signed_with_pow(base, 0)
        sig = sign_canonical(wallet, signed)
        payload = {
            "pubkey": _b64(pub),
            "signature": _b64(sig),
            "last_block_hash": last,
            "timestamp": ts_ms,
            "pow_difficulty": 0,
            "pow": 0,
            "username": username,
        }
        code, resp = _post_json(f"{backend}/api/core/set_username", payload)
        details = {"username": username}
        if code != 200 or "tx_hash" not in resp:
            return TestResult(name=name, passed=False, status_code=code, response=resp, details=details)
        txh = str(resp.get("tx_hash"))
        details["tx_hash"] = txh
        res = wait_tx_result(backend, txh, timeout_s=15.0)
        ok = bool(res) and bool(res.get("found")) and bool(res.get("success"))
        if ok:
            details["height"] = res.get("height")
        # Verify subscriber username has no "Anon-" prefix
        try:
            final_un = _wait_username(backend, addr, username)
            details["final_username"] = final_un
            if final_un != username:
                return TestResult(name=name, passed=False, status_code=code, response=res or resp, details=details)
        except Exception:
            pass
        return TestResult(name=name, passed=ok, status_code=code, response=res or resp, details=details)
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


def sub_pos_follow_moderator(backend: str, seed: str, moderator_addr: str) -> TestResult:
    """Subscriber follow moderator without PoW."""
    name = "Subscriber: follow moderator"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        last, _diff, _min_diff, _ = _fetch_params(backend, addr)
        pub = wallet.public_key().public_key_bytes
        base = canon_base_follow_moderator(pub, last, 0, addr, moderator_addr)
        signed = canon_signed_with_pow(base, 0)
        sig = sign_canonical(wallet, signed)
        payload = {
            "pubkey": _b64(pub),
            "signature": _b64(sig),
            "last_block_hash": last,
            "pow_difficulty": 0,
            "pow": 0,
            "target": addr,
            "moderator": moderator_addr,
        }
        code, resp = _post_json(f"{backend}/api/core/follow_moderator", payload)
        if code != 200 or "tx_hash" not in resp:
            return TestResult(
                name=name, passed=False, status_code=code, response=resp, details={"moderator": moderator_addr}
            )
        txh = str(resp.get("tx_hash"))
        res = wait_tx_result(backend, txh, timeout_s=15.0)
        ok = bool(res) and bool(res.get("found")) and bool(res.get("success"))
        return TestResult(
            name=name,
            passed=ok,
            status_code=code,
            response=res or resp,
            details={"moderator": moderator_addr, "tx_hash": txh, "height": (res or {}).get("height")},
        )
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


def sub_pos_unfollow_moderator(backend: str, seed: str, moderator_addr: str) -> TestResult:
    """Subscriber unfollow moderator without PoW."""
    name = "Subscriber: unfollow moderator"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        last, _diff, _min_diff, _ = _fetch_params(backend, addr)
        pub = wallet.public_key().public_key_bytes
        base = canon_base_unfollow_moderator(pub, last, 0, addr, moderator_addr)
        signed = canon_signed_with_pow(base, 0)
        sig = sign_canonical(wallet, signed)
        payload = {
            "pubkey": _b64(pub),
            "signature": _b64(sig),
            "last_block_hash": last,
            "pow_difficulty": 0,
            "pow": 0,
            "target": addr,
            "moderator": moderator_addr,
        }
        code, resp = _post_json(f"{backend}/api/core/unfollow_moderator", payload)
        if code != 200 or "tx_hash" not in resp:
            return TestResult(
                name=name, passed=False, status_code=code, response=resp, details={"moderator": moderator_addr}
            )
        txh = str(resp.get("tx_hash"))
        res = wait_tx_result(backend, txh, timeout_s=15.0)
        ok = bool(res) and bool(res.get("found")) and bool(res.get("success"))
        return TestResult(
            name=name,
            passed=ok,
            status_code=code,
            response=res or resp,
            details={"moderator": moderator_addr, "tx_hash": txh, "height": (res or {}).get("height")},
        )
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


def neg_subscriber_pow_vote(backend: str, seed: str, target_tx: str, direction: int, label: str) -> TestResult:
    name = f"Subscriber: PoW not allowed ({label}) rejected"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        last, diff, min_diff, _ = _fetch_params(backend, addr)
        pub = wallet.public_key().public_key_bytes
        base = canon_base_vote(pub, last, diff, target_tx, int(direction))
        proof = _compute_pow(base, diff, min_diff, last)
        signed = canon_signed_with_pow(base, int(proof))
        sig = sign_canonical(wallet, signed)
        payload = {
            "pubkey": _b64(pub),
            "signature": _b64(sig),
            "last_block_hash": last,
            "pow_difficulty": int(diff),
            "pow": int(proof),
            "target": target_tx,
            "direction": int(direction),
        }
        code, resp = _post_json(f"{backend}/api/core/vote", payload)
        passed = _expect_fail(resp, code, ["pow not allowed for subscribers"])
        return TestResult(name=name, passed=passed, status_code=code, response=resp)
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


def neg_subscriber_pow_edit(backend: str, seed: str, override_tx: str) -> TestResult:
    name = "Subscriber: PoW not allowed (edit) rejected"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        last, diff, min_diff, _ = _fetch_params(backend, addr)
        pub = wallet.public_key().public_key_bytes
        base = canon_base_edit(pub, last, diff, "", "topicok", "", "c", override_tx)
        proof = _compute_pow(base, diff, min_diff, last)
        signed = canon_signed_with_pow(base, int(proof))
        sig = sign_canonical(wallet, signed)
        payload = {
            "pubkey": _b64(pub),
            "signature": _b64(sig),
            "last_block_hash": last,
            "pow_difficulty": int(diff),
            "pow": int(proof),
            "target": "",
            "topic": "topicok",
            "title": "",
            "content": "c",
            "override": override_tx,
        }
        code, resp = _post_json(f"{backend}/api/core/edit", payload)
        passed = _expect_fail(resp, code, ["pow not allowed for subscribers"])
        return TestResult(name=name, passed=passed, status_code=code, response=resp)
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


def neg_subscriber_pow_set_username(backend: str, seed: str) -> TestResult:
    name = "Subscriber: PoW not allowed (set username) rejected"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        last, diff, min_diff, _ = _fetch_params(backend, addr)
        pub = wallet.public_key().public_key_bytes
        username = f"subpow{_rand_str(6)}"
        base = canon_base_set_username(pub, last, diff, addr, username)
        proof = _compute_pow(base, diff, min_diff, last)
        signed = canon_signed_with_pow(base, int(proof))
        sig = sign_canonical(wallet, signed)
        payload = {
            "pubkey": _b64(pub),
            "signature": _b64(sig),
            "last_block_hash": last,
            "pow_difficulty": int(diff),
            "pow": int(proof),
            "username": username,
        }
        code, resp = _post_json(f"{backend}/api/core/set_username", payload)
        passed = _expect_fail(resp, code, ["pow not allowed for subscribers"])
        return TestResult(name=name, passed=passed, status_code=code, response=resp)
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


def neg_subscriber_pow_send_tokens(backend: str, seed: str) -> TestResult:
    name = "Subscriber: PoW not allowed (send tokens) rejected"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        last, diff, min_diff, _ = _fetch_params(backend, addr)
        pub = wallet.public_key().public_key_bytes
        amount = 1
        base, ts_ms = build_canon_send_tokens(pub, last, int(diff), addr, addr, amount)
        proof = _compute_pow(base, int(diff), min_diff, last)
        signed = canon_signed_with_pow(base, int(proof))
        sig = sign_canonical(wallet, signed)
        payload = {
            "pubkey": _b64(pub),
            "signature": _b64(sig),
            "last_block_hash": last,
            "timestamp": ts_ms,
            "pow_difficulty": int(diff),
            "pow": int(proof),
            "target": addr,
            "amount": amount,
        }
        code, resp = _post_json(f"{backend}/api/core/send_tokens", payload)
        passed = _expect_fail(resp, code, ["pow not allowed for subscribers"])
        return TestResult(name=name, passed=passed, status_code=code, response=resp)
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


def neg_subscriber_pow_follow(backend: str, seed: str, moderator_addr: str) -> TestResult:
    name = "Subscriber: PoW not allowed (follow) rejected"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        last, diff, min_diff, _ = _fetch_params(backend, addr)
        pub = wallet.public_key().public_key_bytes
        base = canon_base_follow_moderator(pub, last, int(diff), addr, moderator_addr)
        proof = _compute_pow(base, diff, min_diff, last)
        signed = canon_signed_with_pow(base, int(proof))
        sig = sign_canonical(wallet, signed)
        payload = {
            "pubkey": _b64(pub),
            "signature": _b64(sig),
            "last_block_hash": last,
            "pow_difficulty": int(diff),
            "pow": int(proof),
            "target": addr,
            "moderator": moderator_addr,
        }
        code, resp = _post_json(f"{backend}/api/core/follow_moderator", payload)
        passed = _expect_fail(resp, code, ["pow not allowed for subscribers"])
        return TestResult(name=name, passed=passed, status_code=code, response=resp)
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


def neg_subscriber_pow_unfollow(backend: str, seed: str, moderator_addr: str) -> TestResult:
    name = "Subscriber: PoW not allowed (unfollow) rejected"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        last, diff, min_diff, _ = _fetch_params(backend, addr)
        pub = wallet.public_key().public_key_bytes
        base = canon_base_unfollow_moderator(pub, last, int(diff), addr, moderator_addr)
        proof = _compute_pow(base, diff, min_diff, last)
        signed = canon_signed_with_pow(base, int(proof))
        sig = sign_canonical(wallet, signed)
        payload = {
            "pubkey": _b64(pub),
            "signature": _b64(sig),
            "last_block_hash": last,
            "pow_difficulty": int(diff),
            "pow": int(proof),
            "target": addr,
            "moderator": moderator_addr,
        }
        code, resp = _post_json(f"{backend}/api/core/unfollow_moderator", payload)
        passed = _expect_fail(resp, code, ["pow not allowed for subscribers"])
        return TestResult(name=name, passed=passed, status_code=code, response=resp)
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


# ========================================
# SUBSCRIBER NEGATIVE TESTS (No PoW)
# ========================================


def sub_neg_delete_not_owner(backend: str, seed: str, foreign_post_tx: str) -> TestResult:
    """Subscriber tries to delete someone else's post (should be forbidden)."""
    name = "Subscriber: delete not owner rejected"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        last, _diff, _min_diff, _ = _fetch_params(backend, addr)
        pub = wallet.public_key().public_key_bytes
        base = canon_base_delete(pub, last, 0, foreign_post_tx)
        signed = canon_signed_with_pow(base, 0)
        sig = sign_canonical(wallet, signed)
        payload = {
            "pubkey": _b64(pub),
            "signature": _b64(sig),
            "last_block_hash": last,
            "pow_difficulty": 0,
            "pow": 0,
            "target": foreign_post_tx,
        }
        code, resp = _post_json(f"{backend}/api/core/delete_post", payload)
        passed = _expect_fail(resp, code, ["forbidden"])
        return TestResult(
            name=name, passed=passed, status_code=code, response=resp, details={"target": foreign_post_tx}
        )
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


def sub_neg_comment_with_topic(backend: str, seed: str, parent_tx: str) -> TestResult:
    """Subscriber comment should not include topic."""
    name = "Subscriber: comment with topic rejected"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        last, _diff, _min_diff, _ = _fetch_params(backend, addr)
        pub = wallet.public_key().public_key_bytes
        base = canon_base_post(pub, last, 0, parent_tx, "wrong", "", "c")
        signed = canon_signed_with_pow(base, 0)
        sig = sign_canonical(wallet, signed)
        payload = {
            "pubkey": _b64(pub),
            "signature": _b64(sig),
            "last_block_hash": last,
            "pow_difficulty": 0,
            "pow": 0,
            "target": parent_tx,
            "topic": "wrong",
            "title": "",
            "content": "c",
        }
        code, resp = _post_json(f"{backend}/api/core/post", payload)
        passed = _expect_fail(resp, code, ["comments must not include topic"])
        return TestResult(name=name, passed=passed, status_code=code, response=resp)
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


def sub_neg_comment_missing_content(backend: str, seed: str, parent_tx: str) -> TestResult:
    """Subscriber comment must have content."""
    name = "Subscriber: comment missing content rejected"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        last, _diff, _min_diff, _ = _fetch_params(backend, addr)
        pub = wallet.public_key().public_key_bytes
        base = canon_base_post(pub, last, 0, parent_tx, "", "", "")
        signed = canon_signed_with_pow(base, 0)
        sig = sign_canonical(wallet, signed)
        payload = {
            "pubkey": _b64(pub),
            "signature": _b64(sig),
            "last_block_hash": last,
            "pow_difficulty": 0,
            "pow": 0,
            "target": parent_tx,
            "topic": "",
            "title": "",
            "content": "",
        }
        code, resp = _post_json(f"{backend}/api/core/post", payload)
        passed = _expect_fail(resp, code, ["comment content required"])
        return TestResult(name=name, passed=passed, status_code=code, response=resp)
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


def sub_neg_post_missing_topic(backend: str, seed: str) -> TestResult:
    """Subscriber root post must include a topic."""
    name = "Subscriber: post missing topic rejected"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        last, _diff, _min_diff, _ = _fetch_params(backend, addr)
        pub = wallet.public_key().public_key_bytes
        base = canon_base_post(pub, last, 0, "", "", "t", "c")
        signed = canon_signed_with_pow(base, 0)
        sig = sign_canonical(wallet, signed)
        payload = {
            "pubkey": _b64(pub),
            "signature": _b64(sig),
            "last_block_hash": last,
            "pow_difficulty": 0,
            "pow": 0,
            "target": "",
            "topic": "",
            "title": "t",
            "content": "c",
        }
        code, resp = _post_json(f"{backend}/api/core/post", payload)
        passed = _expect_fail(resp, code, ["topic required for root posts"])
        return TestResult(name=name, passed=passed, status_code=code, response=resp)
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


def sub_neg_vote_invalid_target(backend: str, seed: str) -> TestResult:
    """Subscriber vote invalid target rejected."""
    name = "Subscriber: vote invalid target rejected"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        last, _diff, _min_diff, _ = _fetch_params(backend, addr)
        pub = wallet.public_key().public_key_bytes
        invalid = "short"
        base = canon_base_vote(pub, last, 0, invalid, 1)
        signed = canon_signed_with_pow(base, 0)
        sig = sign_canonical(wallet, signed)
        payload = {
            "pubkey": _b64(pub),
            "signature": _b64(sig),
            "last_block_hash": last,
            "pow_difficulty": 0,
            "pow": 0,
            "target": invalid,
            "direction": 1,
        }
        code, resp = _post_json(f"{backend}/api/core/vote", payload)
        passed = _expect_fail(resp, code, ["invalid target"])
        return TestResult(name=name, passed=passed, status_code=code, response=resp, details={"target": invalid})
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


# ========================================
# NEGATIVE TESTS (Attack scenarios)
# ========================================


def neg_post_oversize_content(backend: str, seed: str) -> TestResult:
    """Try to post content exceeding tier limit."""
    name = "Post: oversize content rejected"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        last, diff, min_diff, _ = _fetch_params(backend, addr)
        pub = wallet.public_key().public_key_bytes

        # Free tier limit is typically 1000 chars
        content = "x" * 1500
        topic = "topicok"
        title = "ok"

        base = canon_base_post(pub, last, diff, "", topic, title, content)
        proof = _compute_pow(base, diff, min_diff, last)
        signed = canon_signed_with_pow(base, int(proof))
        sig = sign_canonical(wallet, signed)

        payload = {
            "pubkey": _b64(pub),
            "signature": _b64(sig),
            "last_block_hash": last,
            "pow_difficulty": int(diff),
            "pow": int(proof),
            "target": "",
            "topic": topic,
            "title": title,
            "content": content,
        }

        code, resp = _post_json(f"{backend}/api/core/post", payload)

        details = {"content_len": len(content)}

        # Expect specific backend message
        expected = [f"content exceeds limit"]
        if _expect_fail(resp, code, expected):
            return TestResult(name=name, passed=True, status_code=code, response=resp, details=details)

        # If accepted, check DeliverTx
        if "tx_hash" in resp:
            txh = str(resp.get("tx_hash"))
            details["tx_hash"] = txh
            res = wait_tx_result(backend, txh, timeout_s=10.0)
            # Should fail at chain level
            passed = bool(res) and bool(res.get("found")) and not bool(res.get("success"))
            return TestResult(name=name, passed=passed, status_code=code, response=res or resp, details=details)

        return TestResult(name=name, passed=False, status_code=code, response=resp, details=details)
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


def neg_post_media_not_list(backend: str, seed: str) -> TestResult:
    """Media must be a list."""
    name = "Post: media not list rejected"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        last, diff, min_diff, _ = _fetch_params(backend, addr)
        pub = wallet.public_key().public_key_bytes

        topic = "topicok"
        title = "ok"
        content = "content"

        base = canon_base_post(pub, last, diff, "", topic, title, content)
        proof = _compute_pow(base, diff, min_diff, last)
        signed = canon_signed_with_pow(base, int(proof))
        sig = sign_canonical(wallet, signed)

        payload = {
            "pubkey": _b64(pub),
            "signature": _b64(sig),
            "last_block_hash": last,
            "timestamp": _now_ms(),
            "pow_difficulty": int(diff),
            "pow": int(proof),
            "target": "",
            "topic": topic,
            "title": title,
            "content": content,
            "media": "https://example.com/x.jpg",
        }
        code, resp = _post_json(f"{backend}/api/core/post", payload)
        passed = _expect_fail(resp, code, ["media must be a list"])
        return TestResult(name=name, passed=passed, status_code=code, response=resp)
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


def neg_post_media_over_limit(backend: str, seed: str) -> TestResult:
    """Reject media arrays over the max length."""
    name = "Post: media count over limit rejected"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        last, diff, min_diff, _ = _fetch_params(backend, addr)
        pub = wallet.public_key().public_key_bytes

        topic = "topicok"
        title = "ok"
        content = "content"
        media = [f"https://example.com/{i}.jpg" for i in range(11)]

        base, ts_ms = build_canon_post(pub, last, diff, "", topic, title, content, media=media)
        proof = _compute_pow(base, diff, min_diff, last)
        signed = canon_signed_with_pow(base, int(proof))
        sig = sign_canonical(wallet, signed)

        payload = {
            "pubkey": _b64(pub),
            "signature": _b64(sig),
            "last_block_hash": last,
            "timestamp": ts_ms,
            "pow_difficulty": int(diff),
            "pow": int(proof),
            "target": "",
            "topic": topic,
            "title": title,
            "content": content,
            "media": media,
        }
        code, resp = _post_json(f"{backend}/api/core/post", payload)
        passed = _expect_fail(resp, code, ["media exceeds limit"])
        return TestResult(name=name, passed=passed, status_code=code, response=resp, details={"count": len(media)})
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


def neg_post_media_non_https(backend: str, seed: str) -> TestResult:
    """Reject non-https media URLs."""
    name = "Post: media non-https rejected"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        last, diff, min_diff, _ = _fetch_params(backend, addr)
        pub = wallet.public_key().public_key_bytes

        topic = "topicok"
        title = "ok"
        content = "content"
        media = ["http://example.com/x.jpg"]

        base, ts_ms = build_canon_post(pub, last, diff, "", topic, title, content, media=media)
        proof = _compute_pow(base, diff, min_diff, last)
        signed = canon_signed_with_pow(base, int(proof))
        sig = sign_canonical(wallet, signed)

        payload = {
            "pubkey": _b64(pub),
            "signature": _b64(sig),
            "last_block_hash": last,
            "timestamp": ts_ms,
            "pow_difficulty": int(diff),
            "pow": int(proof),
            "target": "",
            "topic": topic,
            "title": title,
            "content": content,
            "media": media,
        }
        code, resp = _post_json(f"{backend}/api/core/post", payload)
        passed = _expect_fail(resp, code, ["must use https://"])
        return TestResult(name=name, passed=passed, status_code=code, response=resp, details={"media": media})
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


def neg_post_media_item_too_long(backend: str, seed: str) -> TestResult:
    """Reject media URLs exceeding max length."""
    name = "Post: media item too long rejected"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        last, diff, min_diff, _ = _fetch_params(backend, addr)
        pub = wallet.public_key().public_key_bytes

        topic = "topicok"
        title = "ok"
        content = "content"
        media = ["https://example.com/" + ("a" * 2050)]

        base, ts_ms = build_canon_post(pub, last, diff, "", topic, title, content, media=media)
        proof = _compute_pow(base, diff, min_diff, last)
        signed = canon_signed_with_pow(base, int(proof))
        sig = sign_canonical(wallet, signed)

        payload = {
            "pubkey": _b64(pub),
            "signature": _b64(sig),
            "last_block_hash": last,
            "timestamp": ts_ms,
            "pow_difficulty": int(diff),
            "pow": int(proof),
            "target": "",
            "topic": topic,
            "title": title,
            "content": content,
            "media": media,
        }
        code, resp = _post_json(f"{backend}/api/core/post", payload)
        passed = _expect_fail(resp, code, ["exceeds length limit"])
        return TestResult(name=name, passed=passed, status_code=code, response=resp, details={"len": len(media[0])})
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


def neg_post_oversize_title(backend: str, seed: str) -> TestResult:
    """Try to post title exceeding limit."""
    name = "Post: oversize title rejected"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        last, diff, min_diff, _ = _fetch_params(backend, addr)
        pub = wallet.public_key().public_key_bytes

        # Title limit is typically 100-150 chars
        title = "t" * 200
        content = "ok"
        topic = "topicok"

        base = canon_base_post(pub, last, diff, "", topic, title, content)
        proof = _compute_pow(base, diff, min_diff, last)
        signed = canon_signed_with_pow(base, int(proof))
        sig = sign_canonical(wallet, signed)

        payload = {
            "pubkey": _b64(pub),
            "signature": _b64(sig),
            "last_block_hash": last,
            "pow_difficulty": int(diff),
            "pow": int(proof),
            "target": "",
            "topic": topic,
            "title": title,
            "content": content,
        }

        code, resp = _post_json(f"{backend}/api/core/post", payload)

        details = {"title_len": len(title)}

        if _expect_fail(resp, code, ["title exceeds limit"]):
            return TestResult(name=name, passed=True, status_code=code, response=resp, details=details)

        if "tx_hash" in resp:
            txh = str(resp.get("tx_hash"))
            details["tx_hash"] = txh
            res = wait_tx_result(backend, txh, timeout_s=10.0)
            passed = bool(res) and bool(res.get("found")) and not bool(res.get("success"))
            return TestResult(name=name, passed=passed, status_code=code, response=res or resp, details=details)

        return TestResult(name=name, passed=False, status_code=code, response=resp, details=details)
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


def neg_post_missing_topic(backend: str, seed: str) -> TestResult:
    """Root post without topic should be rejected by backend."""
    name = "Post: missing topic rejected"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        last, diff, min_diff, _ = _fetch_params(backend, addr)
        pub = wallet.public_key().public_key_bytes
        title = "title"
        content = "content"
        base = canon_base_post(pub, last, diff, "", "", title, content)
        proof = _compute_pow(base, diff, min_diff, last)
        signed = canon_signed_with_pow(base, int(proof))
        sig = sign_canonical(wallet, signed)
        payload = {
            "pubkey": _b64(pub),
            "signature": _b64(sig),
            "last_block_hash": last,
            "pow_difficulty": int(diff),
            "pow": int(proof),
            "target": "",
            "topic": "",
            "title": title,
            "content": content,
        }
        code, resp = _post_json(f"{backend}/api/core/post", payload)
        return TestResult(name=name, passed=(code == 400), status_code=code, response=resp)
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


def neg_post_invalid_tag(backend: str, seed: str, tag: str, label: str) -> TestResult:
    """Post with invalid content tag should be rejected."""
    name = f"Post: invalid tag ({label}) rejected"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        last, diff, min_diff, _ = _fetch_params(backend, addr)
        pub = wallet.public_key().public_key_bytes
        title = f"Test Post {_rand_str(6)}"
        content = f"Content with invalid tag at {int(time.time())}"
        topic = f"topic{_rand_str(5)}"

        base, ts_ms = build_canon_post(pub, last, diff, "", topic, title, content, tag=tag)
        proof = _compute_pow(base, diff, min_diff, last)
        signed = canon_signed_with_pow(base, int(proof))
        sig = sign_canonical(wallet, signed)

        payload = {
            "pubkey": _b64(pub),
            "signature": _b64(sig),
            "last_block_hash": last,
            "timestamp": ts_ms,
            "pow_difficulty": int(diff),
            "pow": int(proof),
            "target": "",
            "topic": topic,
            "title": title,
            "content": content,
            "tag": tag,
        }

        code, resp = _post_json(f"{backend}/api/core/post", payload)

        details = {"tag": tag, "label": label}

        # Expect 400 with "invalid tag" error
        if code == 400 and _expect_fail(resp, code, ["invalid tag", "invalid content tag"]):
            return TestResult(name=name, passed=True, status_code=code, response=resp, details=details)

        # If tx was submitted, it should fail on-chain
        if "tx_hash" in resp:
            txh = str(resp.get("tx_hash"))
            details["tx_hash"] = txh
            res = wait_tx_result(backend, txh, timeout_s=10.0)
            passed = bool(res) and bool(res.get("found")) and not bool(res.get("success"))
            return TestResult(name=name, passed=passed, status_code=code, response=res or resp, details=details)

        return TestResult(name=name, passed=False, status_code=code, response=resp, details=details)
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


def neg_comment_with_topic(backend: str, seed: str, parent_tx: str) -> TestResult:
    """Comment that incorrectly includes a topic should be rejected."""
    name = "Comment: topic provided rejected"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        last, diff, min_diff, _ = _fetch_params(backend, addr)
        pub = wallet.public_key().public_key_bytes
        base = canon_base_post(pub, last, diff, parent_tx, "wrong", "", "c")
        proof = _compute_pow(base, diff, min_diff, last)
        signed = canon_signed_with_pow(base, int(proof))
        sig = sign_canonical(wallet, signed)
        payload = {
            "pubkey": _b64(pub),
            "signature": _b64(sig),
            "last_block_hash": last,
            "pow_difficulty": int(diff),
            "pow": int(proof),
            "target": parent_tx,
            "topic": "wrong",
            "title": "",
            "content": "c",
        }
        code, resp = _post_json(f"{backend}/api/core/post", payload)
        return TestResult(name=name, passed=(code == 400), status_code=code, response=resp)
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


def neg_comment_invalid_target(backend: str, seed: str) -> TestResult:
    """Try to comment on invalid target hash."""
    name = "Comment: invalid target rejected"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        last, diff, min_diff, _ = _fetch_params(backend, addr)
        pub = wallet.public_key().public_key_bytes

        invalid_target = "not-a-valid-hash"
        content = "hello"

        base = canon_base_post(pub, last, diff, invalid_target, "", "", content)
        proof = _compute_pow(base, diff, min_diff, last)
        signed = canon_signed_with_pow(base, int(proof))
        sig = sign_canonical(wallet, signed)

        payload = {
            "pubkey": _b64(pub),
            "signature": _b64(sig),
            "last_block_hash": last,
            "pow_difficulty": int(diff),
            "pow": int(proof),
            "target": invalid_target,
            "topic": "",
            "title": "",
            "content": content,
        }

        code, resp = _post_json(f"{backend}/api/core/post", payload)

        details = {"target": invalid_target}

        if _expect_fail(resp, code, ["invalid target"]):
            return TestResult(name=name, passed=True, status_code=code, response=resp, details=details)

        if "tx_hash" in resp:
            txh = str(resp.get("tx_hash"))
            details["tx_hash"] = txh
            res = wait_tx_result(backend, txh, timeout_s=10.0)
            passed = bool(res) and bool(res.get("found")) and not bool(res.get("success"))
            return TestResult(name=name, passed=passed, status_code=code, response=res or resp, details=details)

        return TestResult(name=name, passed=False, status_code=code, response=resp, details=details)
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


def neg_invalid_pubkey_length(backend: str, seed: str) -> TestResult:
    """Try to relay with invalid pubkey length."""
    name = "Relay: invalid pubkey rejected"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        last, diff, min_diff, _ = _fetch_params(backend, addr)
        pub = wallet.public_key().public_key_bytes

        # Truncate pubkey
        bad_pub = pub[:20]

        base = canon_base_post(pub, last, diff, "", "topicok", "ok", "content")
        proof = _compute_pow(base, diff, min_diff, last)
        signed = canon_signed_with_pow(base, int(proof))
        sig = sign_canonical(wallet, signed)

        payload = {
            "pubkey": _b64(bad_pub),
            "signature": _b64(sig),
            "last_block_hash": last,
            "pow_difficulty": int(diff),
            "pow": int(proof),
            "target": "",
            "topic": "topicok",
            "title": "ok",
            "content": "content",
        }

        code, resp = _post_json(f"{backend}/api/core/post", payload)

        details = {"pubkey_len": len(bad_pub)}

        # Expect invalid relay fields (bad pubkey length)
        passed = _expect_fail(resp, code, ["invalid relay fields"])
        return TestResult(name=name, passed=passed, status_code=code, response=resp, details=details)
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


def neg_tampered_signature(backend: str, seed: str) -> TestResult:
    """Try to relay with tampered signature."""
    name = "Relay: tampered signature rejected"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        last, diff, min_diff, _ = _fetch_params(backend, addr)
        pub = wallet.public_key().public_key_bytes

        base = canon_base_post(pub, last, diff, "", "topicok", "ok", "content")
        proof = _compute_pow(base, diff, min_diff, last)
        signed = canon_signed_with_pow(base, int(proof))
        sig = sign_canonical(wallet, signed)

        # Tamper with signature
        bad_sig = bytearray(sig)
        bad_sig[0] ^= 0xFF
        bad_sig = bytes(bad_sig)

        payload = {
            "pubkey": _b64(pub),
            "signature": _b64(bad_sig),
            "last_block_hash": last,
            "pow_difficulty": int(diff),
            "pow": int(proof),
            "target": "",
            "topic": "topicok",
            "title": "ok",
            "content": "content",
        }

        code, resp = _post_json(f"{backend}/api/core/post", payload)

        details = {}
        if _expect_fail(resp, code, ["invalid signature"]):
            return TestResult(name=name, passed=True, status_code=code, response=resp, details=details)

        if "tx_hash" in resp:
            txh = str(resp.get("tx_hash"))
            details["tx_hash"] = txh
            res = wait_tx_result(backend, txh, timeout_s=10.0)
            passed = bool(res) and bool(res.get("found")) and not bool(res.get("success"))
            return TestResult(name=name, passed=passed, status_code=code, response=res or resp, details=details)

        return TestResult(name=name, passed=False, status_code=code, response=resp, details=details)
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


def neg_insufficient_pow(backend: str, seed: str) -> TestResult:
    """Try to post with insufficient PoW difficulty."""
    name = "PoW: insufficient difficulty rejected"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        last, diff, min_diff, _ = _fetch_params(backend, addr)
        pub = wallet.public_key().public_key_bytes

        # Use difficulty lower than required
        low_diff = max(1, diff - 5)

        base, ts_ms = build_canon_post(pub, last, low_diff, "", "topicok", "ok", "content")
        proof = _compute_pow(base, low_diff, min_diff, last)
        signed = canon_signed_with_pow(base, int(proof))
        sig = sign_canonical(wallet, signed)

        payload = {
            "pubkey": _b64(pub),
            "signature": _b64(sig),
            "last_block_hash": last,
            "timestamp": ts_ms,
            "pow_difficulty": int(low_diff),
            "pow": int(proof),
            "target": "",
            "topic": "topicok",
            "title": "ok",
            "content": "content",
        }

        code, resp = _post_json(f"{backend}/api/core/post", payload)

        details = {"declared_diff": low_diff, "required_diff": diff}

        passed = _expect_fail(resp, code, ["insufficient pow"])
        return TestResult(name=name, passed=passed, status_code=code, response=resp, details=details)
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


def neg_missing_pow_free_user(backend: str, seed: str) -> TestResult:
    """Free user attempts to post without PoW - must be rejected by backend."""
    name = "PoW: missing for free user rejected"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        last, diff, min_diff, _ = _fetch_params(backend, addr)
        pub = wallet.public_key().public_key_bytes
        # Build base but do not compute PoW, set difficulty/proof to 0
        base = canon_base_post(pub, last, max(1, diff), "", "topicok", "ok", "content")
        signed = canon_signed_with_pow(base, 0)
        sig = sign_canonical(wallet, signed)
        payload = {
            "pubkey": _b64(pub),
            "signature": _b64(sig),
            "last_block_hash": last,
            "pow_difficulty": 0,
            "pow": 0,
            "target": "",
            "topic": "topicok",
            "title": "ok",
            "content": "content",
        }
        code, resp = _post_json(f"{backend}/api/core/post", payload)
        return TestResult(name=name, passed=(code == 400), status_code=code, response=resp)
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


def neg_invalid_last_block_hash(backend: str, seed: str) -> TestResult:
    """Try to post with invalid last_block_hash format."""
    name = "PoW: invalid last_block_hash rejected"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        last, diff, min_diff, _ = _fetch_params(backend, addr)
        pub = wallet.public_key().public_key_bytes

        # Use invalid hash format
        bad_hash = "not-a-valid-hex-hash"

        # Still compute PoW with real hash so we don't fail on that
        base = canon_base_post(pub, last, diff, "", "topicok", "ok", "content")
        proof = _compute_pow(base, diff, min_diff, last)
        signed = canon_signed_with_pow(base, int(proof))
        sig = sign_canonical(wallet, signed)

        payload = {
            "pubkey": _b64(pub),
            "signature": _b64(sig),
            "last_block_hash": bad_hash,  # Invalid hash
            "pow_difficulty": int(diff),
            "pow": int(proof),
            "target": "",
            "topic": "topicok",
            "title": "ok",
            "content": "content",
        }

        code, resp = _post_json(f"{backend}/api/core/post", payload)

        details = {"bad_hash": bad_hash}

        passed = _expect_fail(resp, code, ["invalid last_block_hash"])
        return TestResult(name=name, passed=passed, status_code=code, response=resp, details=details)
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


def neg_delete_not_owner(backend: str, seed: str) -> TestResult:
    """Try to delete someone else's post."""
    name = "Delete: not owner rejected"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())

        # Find a post by someone else
        foreign_post = _fetch_foreign_post_id(backend, addr)
        if not foreign_post:
            # Skip this test if no foreign posts exist (single-user testnet)
            return TestResult(name=name, passed=True, details={"skipped": "no foreign post found"})

        last, diff, min_diff, _ = _fetch_params(backend, addr)
        pub = wallet.public_key().public_key_bytes

        base = canon_base_delete(pub, last, diff, foreign_post)
        proof = _compute_pow(base, diff, min_diff, last)
        signed = canon_signed_with_pow(base, int(proof))
        sig = sign_canonical(wallet, signed)

        payload = {
            "pubkey": _b64(pub),
            "signature": _b64(sig),
            "last_block_hash": last,
            "pow_difficulty": int(diff),
            "pow": int(proof),
            "target": foreign_post,
        }

        code, resp = _post_json(f"{backend}/api/core/delete_post", payload)

        details = {"target": foreign_post}

        if code >= 400:
            return TestResult(name=name, passed=True, status_code=code, response=resp, details=details)

        if "tx_hash" in resp:
            txh = str(resp.get("tx_hash"))
            details["tx_hash"] = txh
            res = wait_tx_result(backend, txh, timeout_s=10.0)
            # Should fail - not owner
            passed = bool(res) and bool(res.get("found")) and not bool(res.get("success"))
            return TestResult(name=name, passed=passed, status_code=code, response=res or resp, details=details)

        return TestResult(name=name, passed=False, status_code=code, response=resp, details=details)
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


def neg_delete_not_owner_with_tx(backend: str, seed: str, foreign_post_tx: str) -> TestResult:
    """Try to delete a specific foreign post."""
    name = "Delete: not owner rejected"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        last, diff, min_diff, _ = _fetch_params(backend, addr)
        pub = wallet.public_key().public_key_bytes
        base = canon_base_delete(pub, last, diff, foreign_post_tx)
        proof = _compute_pow(base, diff, min_diff, last)
        signed = canon_signed_with_pow(base, int(proof))
        sig = sign_canonical(wallet, signed)
        payload = {
            "pubkey": _b64(pub),
            "signature": _b64(sig),
            "last_block_hash": last,
            "pow_difficulty": int(diff),
            "pow": int(proof),
            "target": foreign_post_tx,
        }
        code, resp = _post_json(f"{backend}/api/core/delete_post", payload)
        details = {"target": foreign_post_tx}
        if code >= 400:
            return TestResult(name=name, passed=True, status_code=code, response=resp, details=details)
        if "tx_hash" in resp:
            txh = str(resp.get("tx_hash"))
            details["tx_hash"] = txh
            res = wait_tx_result(backend, txh, timeout_s=10.0)
            passed = bool(res) and bool(res.get("found")) and not bool(res.get("success"))
            return TestResult(name=name, passed=passed, status_code=code, response=res or resp, details=details)
        return TestResult(name=name, passed=False, status_code=code, response=resp, details=details)
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


def neg_vote_invalid_target(backend: str, seed: str) -> TestResult:
    """Try to vote on invalid target."""
    name = "Vote: invalid target rejected"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        last, diff, min_diff, _ = _fetch_params(backend, addr)
        pub = wallet.public_key().public_key_bytes

        invalid_target = "short"

        base = canon_base_vote(pub, last, diff, invalid_target, 1)
        proof = _compute_pow(base, diff, min_diff, last)
        signed = canon_signed_with_pow(base, int(proof))
        sig = sign_canonical(wallet, signed)

        payload = {
            "pubkey": _b64(pub),
            "signature": _b64(sig),
            "last_block_hash": last,
            "pow_difficulty": int(diff),
            "pow": int(proof),
            "target": invalid_target,
            "direction": 1,
        }

        code, resp = _post_json(f"{backend}/api/core/vote", payload)

        details = {"target": invalid_target}

        if code >= 400:
            return TestResult(name=name, passed=True, status_code=code, response=resp, details=details)

        if "tx_hash" in resp:
            txh = str(resp.get("tx_hash"))
            details["tx_hash"] = txh
            res = wait_tx_result(backend, txh, timeout_s=10.0)
            passed = bool(res) and bool(res.get("found")) and not bool(res.get("success"))
            return TestResult(name=name, passed=passed, status_code=code, response=res or resp, details=details)

        return TestResult(name=name, passed=False, status_code=code, response=resp, details=details)
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


def neg_report_reason_too_long(backend: str, seed: str) -> TestResult:
    """Try to report with reason exceeding limit."""
    name = "Report: reason too long rejected"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        last, diff, min_diff, _ = _fetch_params(backend, addr)
        pub = wallet.public_key().public_key_bytes

        target = "f" * 64  # Valid format but non-existent
        reason = "r" * 500  # Too long

        base = canon_base_vote(pub, last, diff, target, 0)
        proof = _compute_pow(base, diff, min_diff, last)
        signed = canon_signed_with_pow(base, int(proof))
        sig = sign_canonical(wallet, signed)

        payload = {
            "pubkey": _b64(pub),
            "signature": _b64(sig),
            "last_block_hash": last,
            "pow_difficulty": int(diff),
            "pow": int(proof),
            "target": target,
            "reason": reason,
        }

        code, resp = _post_json(f"{backend}/api/core/report", payload)

        details = {"reason_len": len(reason)}

        passed = _expect_fail(resp, code, ["reason too long"])
        return TestResult(name=name, passed=passed, status_code=code, response=resp, details=details)
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


def neg_send_tokens_invalid(backend: str, seed: str) -> TestResult:
    """Try to send tokens with invalid target."""
    name = "SendTokens: invalid target rejected"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        last, diff, min_diff, _ = _fetch_params(backend, addr)
        pub = wallet.public_key().public_key_bytes

        # Build a valid envelope with PoW, but invalid target format to trigger the target validation
        amount = 1
        base, ts_ms = build_canon_send_tokens(pub, last, int(diff), addr, "not-an-address", amount)
        proof = _compute_pow(base, int(diff), min_diff, last)
        signed = canon_signed_with_pow(base, int(proof))
        sig = sign_canonical(wallet, signed)
        payload = {
            "pubkey": _b64(pub),
            "signature": _b64(sig),
            "last_block_hash": last,
            "timestamp": ts_ms,
            "pow_difficulty": int(diff),
            "pow": int(proof),
            "target": "not-an-address",
            "amount": amount,
        }

        code, resp = _post_json(f"{backend}/api/core/send_tokens", payload)

        details = {"target": "not-an-address", "amount": amount}

        passed = _expect_fail(resp, code, ["target must be a valid mirage1 address", "invalid target"])
        return TestResult(name=name, passed=passed, status_code=code, response=resp, details=details)
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


def neg_send_tokens_insufficient_funds(backend: str, seed: str) -> TestResult:
    """Try to send a huge amount to a valid address - should fail."""
    name = "SendTokens: insufficient funds rejected"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        last, diff, min_diff, _ = _fetch_params(backend, addr)
        pub = wallet.public_key().public_key_bytes

        # Use own address as valid target, compute proper PoW envelope
        amount = 10_000_000_000  # 10,000 MIRAGE (likely > balance)
        base, ts_ms = build_canon_send_tokens(pub, last, int(diff), addr, addr, amount)
        proof = _compute_pow(base, int(diff), min_diff, last)
        signed = canon_signed_with_pow(base, int(proof))
        sig = sign_canonical(wallet, signed)
        payload = {
            "pubkey": _b64(pub),
            "signature": _b64(sig),
            "last_block_hash": last,
            "timestamp": ts_ms,
            "pow_difficulty": int(diff),
            "pow": int(proof),
            "target": addr,
            "amount": amount,
        }
        code, resp = _post_json(f"{backend}/api/core/send_tokens", payload)
        expected = ["insufficient balance"]
        passed = _expect_fail(resp, code, expected)
        return TestResult(
            name=name,
            passed=passed,
            status_code=code,
            response=resp,
            details={"target": addr, "amount": payload["amount"]},
        )
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


def neg_username_invalid(backend: str, seed: str, username: str, label: str) -> TestResult:
    """Try to set username with invalid format."""
    name = f"SetUsername: {label} rejected"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        last, diff, min_diff, _ = _fetch_params(backend, addr)
        pub = wallet.public_key().public_key_bytes
        base = canon_base_set_username(pub, last, diff, addr, username)
        proof = _compute_pow(base, diff, min_diff, last)
        signed = canon_signed_with_pow(base, int(proof))
        sig = sign_canonical(wallet, signed)
        payload = {
            "pubkey": _b64(pub),
            "signature": _b64(sig),
            "last_block_hash": last,
            "pow_difficulty": int(diff),
            "pow": int(proof),
            "username": username,
        }
        code, resp = _post_json(f"{backend}/api/core/set_username", payload)
        # Expect specific error depending on label
        expected = []
        if label in ("space", "dot", "symbol", "emoji"):
            expected = ["invalid username format"]
        passed = _expect_fail(resp, code, expected or ["invalid"])
        return TestResult(name=name, passed=passed, status_code=code, response=resp, details={"username": username})
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


def pos_free_username_prefixed(backend: str, seed_free: str) -> TestResult:
    """Free user sets username without Anon-, chain should prefix with 'Anon-'."""
    name = "Free: username is prefixed by Anon-"
    try:
        wallet = create_wallet_from_seed(seed_free)
        addr = str(wallet.address())
        last, diff, min_diff, _ = _fetch_params(backend, addr)
        pub = wallet.public_key().public_key_bytes
        desired = f"free-{_rand_str(6)}"
        base, ts_ms = build_canon_set_username(pub, last, diff, addr, desired)
        proof = _compute_pow(base, diff, min_diff, last)
        signed = canon_signed_with_pow(base, int(proof))
        sig = sign_canonical(wallet, signed)
        payload = {
            "pubkey": _b64(pub),
            "signature": _b64(sig),
            "last_block_hash": last,
            "timestamp": ts_ms,
            "pow_difficulty": int(diff),
            "pow": int(proof),
            "username": desired,
        }
        code, resp = _post_json(f"{backend}/api/core/set_username", payload)
        details = {"requested": desired}
        if code != 200 or "tx_hash" not in resp:
            return TestResult(name=name, passed=False, status_code=code, response=resp, details=details)
        txh = str(resp.get("tx_hash"))
        res = wait_tx_result(backend, txh, timeout_s=15.0)
        ok = bool(res) and bool(res.get("found")) and bool(res.get("success"))
        if not ok:
            return TestResult(name=name, passed=False, status_code=code, response=res or resp, details=details)
        final_un = _wait_username(backend, addr, f"Anon-{desired}")
        details["final_username"] = final_un
        return TestResult(
            name=name, passed=(final_un == f"Anon-{desired}"), status_code=code, response=res or resp, details=details
        )
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


def pos_free_username_prefixed_once(backend: str, seed_free: str) -> TestResult:
    """Free user sets username with Anon- prefix; chain should not double-prefix."""
    name = "Free: username prefixed only once"
    try:
        wallet = create_wallet_from_seed(seed_free)
        addr = str(wallet.address())
        last, diff, min_diff, _ = _fetch_params(backend, addr)
        pub = wallet.public_key().public_key_bytes
        requested = f"anon-{_rand_str(6)}"
        base, ts_ms = build_canon_set_username(pub, last, diff, addr, requested)
        proof = _compute_pow(base, diff, min_diff, last)
        signed = canon_signed_with_pow(base, int(proof))
        sig = sign_canonical(wallet, signed)
        payload = {
            "pubkey": _b64(pub),
            "signature": _b64(sig),
            "last_block_hash": last,
            "timestamp": ts_ms,
            "pow_difficulty": int(diff),
            "pow": int(proof),
            "username": requested,
        }
        code, resp = _post_json(f"{backend}/api/core/set_username", payload)
        details = {"requested": requested}
        if code != 200 or "tx_hash" not in resp:
            return TestResult(name=name, passed=False, status_code=code, response=resp, details=details)
        txh = str(resp.get("tx_hash"))
        res = wait_tx_result(backend, txh, timeout_s=15.0)
        ok = bool(res) and bool(res.get("found")) and bool(res.get("success"))
        if not ok:
            return TestResult(name=name, passed=False, status_code=code, response=res or resp, details=details)
        final_un = _wait_username(backend, addr, None)
        details["final_username"] = final_un
        # Expect chain to normalize to capitalized 'Anon-' and not double-prefix
        expected = f"Anon-{requested[len('anon-'):]}"
        return TestResult(
            name=name, passed=(final_un == expected), status_code=code, response=res or resp, details=details
        )
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


def neg_edit_root_missing_topic(backend: str, seed: str, override_tx: str) -> TestResult:
    """Attempt to edit a root post with missing topic - must be rejected."""
    name = "Edit: missing topic for root rejected"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        last, diff, min_diff, _ = _fetch_params(backend, addr)
        pub = wallet.public_key().public_key_bytes
        base = canon_base_edit(pub, last, diff, "", "", "", "edit", override_tx)
        proof = _compute_pow(base, diff, min_diff, last)
        signed = canon_signed_with_pow(base, int(proof))
        sig = sign_canonical(wallet, signed)
        payload = {
            "pubkey": _b64(pub),
            "signature": _b64(sig),
            "last_block_hash": last,
            "pow_difficulty": int(diff),
            "pow": int(proof),
            "target": "",
            "topic": "",
            "title": "",
            "content": "edit",
            "override": override_tx,
        }
        code, resp = _post_json(f"{backend}/api/core/edit", payload)
        return TestResult(name=name, passed=(code == 400), status_code=code, response=resp)
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


def neg_edit_comment_with_topic(backend: str, seed: str, override_tx: str, parent_tx: str) -> TestResult:
    """Attempt to edit a comment but include a topic - must be rejected."""
    name = "Edit: comment with topic rejected"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        last, diff, min_diff, _ = _fetch_params(backend, addr)
        pub = wallet.public_key().public_key_bytes
        base = canon_base_edit(pub, last, diff, parent_tx, "bad", "", "c", override_tx)
        proof = _compute_pow(base, diff, min_diff, last)
        signed = canon_signed_with_pow(base, int(proof))
        sig = sign_canonical(wallet, signed)
        payload = {
            "pubkey": _b64(pub),
            "signature": _b64(sig),
            "last_block_hash": last,
            "pow_difficulty": int(diff),
            "pow": int(proof),
            "target": parent_tx,
            "topic": "bad",
            "title": "",
            "content": "c",
            "override": override_tx,
        }
        code, resp = _post_json(f"{backend}/api/core/edit", payload)
        return TestResult(name=name, passed=(code == 400), status_code=code, response=resp)
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


def neg_username_too_short(backend: str, seed: str) -> TestResult:
    """Try to set username that's too short."""
    name = "SetUsername: too short rejected"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        last, diff, min_diff, _ = _fetch_params(backend, addr)
        pub = wallet.public_key().public_key_bytes

        username = "ab"  # Too short (min 3)

        base = canon_base_set_username(pub, last, diff, addr, username)
        proof = _compute_pow(base, diff, min_diff, last)
        signed = canon_signed_with_pow(base, int(proof))
        sig = sign_canonical(wallet, signed)

        payload = {
            "pubkey": _b64(pub),
            "signature": _b64(sig),
            "last_block_hash": last,
            "pow_difficulty": int(diff),
            "pow": int(proof),
            "username": username,
        }

        code, resp = _post_json(f"{backend}/api/core/set_username", payload)

        details = {"username": username, "len": len(username)}

        if _expect_fail(resp, code, ["username too short"]):
            return TestResult(name=name, passed=True, status_code=code, response=resp, details=details)

        if "tx_hash" in resp:
            txh = str(resp.get("tx_hash"))
            details["tx_hash"] = txh
            res = wait_tx_result(backend, txh, timeout_s=10.0)
            passed = bool(res) and bool(res.get("found")) and not bool(res.get("success"))
            return TestResult(name=name, passed=passed, status_code=code, response=res or resp, details=details)

        return TestResult(name=name, passed=False, status_code=code, response=resp, details=details)
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


def neg_username_too_long(backend: str, seed: str) -> TestResult:
    """Try to set username that's too long."""
    name = "SetUsername: too long rejected"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        last, diff, min_diff, _ = _fetch_params(backend, addr)
        pub = wallet.public_key().public_key_bytes

        username = "u" * 200  # Too long (max 64)

        base = canon_base_set_username(pub, last, diff, addr, username)
        proof = _compute_pow(base, diff, min_diff, last)
        signed = canon_signed_with_pow(base, int(proof))
        sig = sign_canonical(wallet, signed)

        payload = {
            "pubkey": _b64(pub),
            "signature": _b64(sig),
            "last_block_hash": last,
            "pow_difficulty": int(diff),
            "pow": int(proof),
            "username": username,
        }

        code, resp = _post_json(f"{backend}/api/core/set_username", payload)

        details = {"username_len": len(username)}

        if _expect_fail(resp, code, ["username too long"]):
            return TestResult(name=name, passed=True, status_code=code, response=resp, details=details)

        if "tx_hash" in resp:
            txh = str(resp.get("tx_hash"))
            details["tx_hash"] = txh
            res = wait_tx_result(backend, txh, timeout_s=10.0)
            passed = bool(res) and bool(res.get("found")) and not bool(res.get("success"))
            return TestResult(name=name, passed=passed, status_code=code, response=res or resp, details=details)

        return TestResult(name=name, passed=False, status_code=code, response=resp, details=details)
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


# ========================================
# AUTHORIZATION ATTACK TESTS
# ========================================


def neg_edit_foreign_post_free(backend: str, seed: str, foreign_post_tx: str) -> TestResult:
    """Free user tries to edit someone else's post - should be forbidden."""
    name = "Edit: free user edit foreign post rejected"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        last, diff, min_diff, _ = _fetch_params(backend, addr)
        pub = wallet.public_key().public_key_bytes

        new_content = f"Hacked content at {int(time.time())}"
        new_topic = f"topic{_rand_str(4)}"

        base = canon_base_edit(pub, last, diff, "", new_topic, "", new_content, foreign_post_tx)
        proof = _compute_pow(base, diff, min_diff, last)
        signed = canon_signed_with_pow(base, int(proof))
        sig = sign_canonical(wallet, signed)

        payload = {
            "pubkey": _b64(pub),
            "signature": _b64(sig),
            "last_block_hash": last,
            "pow_difficulty": int(diff),
            "pow": int(proof),
            "target": "",
            "topic": new_topic,
            "title": "",
            "content": new_content,
            "override": foreign_post_tx,
        }

        code, resp = _post_json(f"{backend}/api/core/edit", payload)
        passed = _expect_fail(resp, code, ["forbidden"])
        return TestResult(
            name=name, passed=passed, status_code=code, response=resp, details={"override": foreign_post_tx}
        )
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


def neg_edit_foreign_post_subscriber(backend: str, seed: str, foreign_post_tx: str) -> TestResult:
    """Subscriber tries to edit someone else's post - should be forbidden."""
    name = "Edit: subscriber edit foreign post rejected"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        last, _diff, _min_diff, _ = _fetch_params(backend, addr)
        pub = wallet.public_key().public_key_bytes

        new_content = f"Hacked content at {int(time.time())}"
        new_topic = f"topic{_rand_str(4)}"

        base = canon_base_edit(pub, last, 0, "", new_topic, "", new_content, foreign_post_tx)
        signed = canon_signed_with_pow(base, 0)
        sig = sign_canonical(wallet, signed)

        payload = {
            "pubkey": _b64(pub),
            "signature": _b64(sig),
            "last_block_hash": last,
            "pow_difficulty": 0,
            "pow": 0,
            "target": "",
            "topic": new_topic,
            "title": "",
            "content": new_content,
            "override": foreign_post_tx,
        }

        code, resp = _post_json(f"{backend}/api/core/edit", payload)
        passed = _expect_fail(resp, code, ["forbidden"])
        return TestResult(
            name=name, passed=passed, status_code=code, response=resp, details={"override": foreign_post_tx}
        )
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


def neg_edit_foreign_comment_free(backend: str, seed: str, foreign_comment_tx: str, parent_tx: str) -> TestResult:
    """Free user tries to edit someone else's comment - should be forbidden."""
    name = "Edit: free user edit foreign comment rejected"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        last, diff, min_diff, _ = _fetch_params(backend, addr)
        pub = wallet.public_key().public_key_bytes

        new_content = f"Hacked comment at {int(time.time())}"

        base = canon_base_edit(pub, last, diff, parent_tx, "", "", new_content, foreign_comment_tx)
        proof = _compute_pow(base, diff, min_diff, last)
        signed = canon_signed_with_pow(base, int(proof))
        sig = sign_canonical(wallet, signed)

        payload = {
            "pubkey": _b64(pub),
            "signature": _b64(sig),
            "last_block_hash": last,
            "pow_difficulty": int(diff),
            "pow": int(proof),
            "target": parent_tx,
            "topic": "",
            "title": "",
            "content": new_content,
            "override": foreign_comment_tx,
        }

        code, resp = _post_json(f"{backend}/api/core/edit", payload)
        passed = _expect_fail(resp, code, ["forbidden"])
        return TestResult(
            name=name,
            passed=passed,
            status_code=code,
            response=resp,
            details={"override": foreign_comment_tx, "parent": parent_tx},
        )
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


def neg_edit_foreign_comment_subscriber(backend: str, seed: str, foreign_comment_tx: str, parent_tx: str) -> TestResult:
    """Subscriber tries to edit someone else's comment - should be forbidden."""
    name = "Edit: subscriber edit foreign comment rejected"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        last, _diff, _min_diff, _ = _fetch_params(backend, addr)
        pub = wallet.public_key().public_key_bytes

        new_content = f"Hacked comment at {int(time.time())}"

        base = canon_base_edit(pub, last, 0, parent_tx, "", "", new_content, foreign_comment_tx)
        signed = canon_signed_with_pow(base, 0)
        sig = sign_canonical(wallet, signed)

        payload = {
            "pubkey": _b64(pub),
            "signature": _b64(sig),
            "last_block_hash": last,
            "pow_difficulty": 0,
            "pow": 0,
            "target": parent_tx,
            "topic": "",
            "title": "",
            "content": new_content,
            "override": foreign_comment_tx,
        }

        code, resp = _post_json(f"{backend}/api/core/edit", payload)
        passed = _expect_fail(resp, code, ["forbidden"])
        return TestResult(
            name=name,
            passed=passed,
            status_code=code,
            response=resp,
            details={"override": foreign_comment_tx, "parent": parent_tx},
        )
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


def neg_set_username_foreign(backend: str, seed: str, foreign_addr: str) -> TestResult:
    """Try to set username for someone else's address - should fail due to signature mismatch."""
    name = "SetUsername: foreign address rejected"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        last, diff, min_diff, _ = _fetch_params(backend, addr)
        pub = wallet.public_key().public_key_bytes

        username = f"hacked-{_rand_str(4)}"

        base = canon_base_set_username(pub, last, diff, foreign_addr, username)
        proof = _compute_pow(base, diff, min_diff, last)
        signed = canon_signed_with_pow(base, int(proof))
        sig = sign_canonical(wallet, signed)

        payload = {
            "pubkey": _b64(pub),
            "signature": _b64(sig),
            "last_block_hash": last,
            "pow_difficulty": int(diff),
            "pow": int(proof),
            "username": username,
        }

        code, resp = _post_json(f"{backend}/api/core/set_username", payload)

        if code >= 400:
            return TestResult(name=name, passed=True, status_code=code, response=resp, details={"target": foreign_addr})

        if "tx_hash" in resp:
            txh = str(resp.get("tx_hash"))
            res = wait_tx_result(backend, txh, timeout_s=10.0)
            passed = bool(res) and bool(res.get("found")) and not bool(res.get("success"))
            return TestResult(
                name=name, passed=passed, status_code=code, response=res or resp, details={"target": foreign_addr}
            )

        return TestResult(name=name, passed=False, status_code=code, response=resp, details={"target": foreign_addr})
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


# ========================================
# REPLAY ATTACK TESTS
# ========================================


def neg_replay_old_signature(backend: str, seed: str) -> TestResult:
    """Try to reuse an old signature with new content - should fail (PoW or signature)."""
    name = "Replay: old signature with new content rejected"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        last, diff, min_diff, _ = _fetch_params(backend, addr)
        pub = wallet.public_key().public_key_bytes

        topic = f"topic{_rand_str(4)}"
        title = "Original"
        content = "Original content"

        base = canon_base_post(pub, last, diff, "", topic, title, content)
        proof = _compute_pow(base, diff, min_diff, last)
        signed = canon_signed_with_pow(base, int(proof))
        sig = sign_canonical(wallet, signed)

        new_content = "Hacked content"
        payload = {
            "pubkey": _b64(pub),
            "signature": _b64(sig),
            "last_block_hash": last,
            "pow_difficulty": int(diff),
            "pow": int(proof),
            "target": "",
            "topic": topic,
            "title": title,
            "content": new_content,
        }

        code, resp = _post_json(f"{backend}/api/core/post", payload)
        # PoW check happens before signature check, so either error is acceptable
        passed = _expect_fail(resp, code, ["invalid signature", "insufficient pow"])
        return TestResult(name=name, passed=passed, status_code=code, response=resp)
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


def neg_replay_old_block_hash(backend: str, seed: str) -> TestResult:
    """Try to reuse signature with old last_block_hash - tests block hash window."""
    name = "Replay: old last_block_hash within window allowed"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        pub = wallet.public_key().public_key_bytes
        last_old, diff_old, min_diff_old, _ = _fetch_params(backend, addr)

        topic = f"topic{_rand_str(4)}"
        title = "Test"
        content = "Content"

        base_old = canon_base_post(pub, last_old, diff_old, "", topic, title, content)
        proof_old = _compute_pow(base_old, diff_old, min_diff_old, last_old)
        signed_old = canon_signed_with_pow(base_old, int(proof_old))
        sig_old = sign_canonical(wallet, signed_old)

        sleep(2)
        last_new, diff_new, _min_diff_new, _ = _fetch_params(backend, addr)

        payload = {
            "pubkey": _b64(pub),
            "signature": _b64(sig_old),
            "last_block_hash": last_old,
            "pow_difficulty": int(diff_old),
            "pow": int(proof_old),
            "target": "",
            "topic": topic,
            "title": title,
            "content": content,
        }

        code, resp = _post_json(f"{backend}/api/core/post", payload)

        # Within the block hash window (typically 100+ blocks), reuse is allowed
        # This test verifies the system handles recent block hashes correctly
        if code == 200 and "tx_hash" in resp:
            txh = str(resp.get("tx_hash"))
            res = wait_tx_result(backend, txh, timeout_s=10.0)
            passed = bool(res) and bool(res.get("found")) and bool(res.get("success"))
            return TestResult(name=name, passed=passed, status_code=code, response=res or resp)
        elif code >= 400:
            # If rejected due to stale hash (outside window), that's also valid
            passed = _expect_fail(resp, code, ["invalid last_block_hash"])
            return TestResult(name=name, passed=passed, status_code=code, response=resp)
        return TestResult(name=name, passed=False, status_code=code, response=resp)
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


def neg_pow_proof_reuse(backend: str, seed: str) -> TestResult:
    """Try to reuse PoW proof from one message in another - should fail."""
    name = "PoW: proof reuse rejected"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        last, diff, min_diff, _ = _fetch_params(backend, addr)
        pub = wallet.public_key().public_key_bytes

        topic1 = f"topic{_rand_str(4)}"
        title1 = "First"
        content1 = "First content"

        base1 = canon_base_post(pub, last, diff, "", topic1, title1, content1)
        proof1 = _compute_pow(base1, diff, min_diff, last)
        signed1 = canon_signed_with_pow(base1, int(proof1))
        sig1 = sign_canonical(wallet, signed1)

        topic2 = f"topic{_rand_str(4)}"
        title2 = "Second"
        content2 = "Second content"

        base2 = canon_base_post(pub, last, diff, "", topic2, title2, content2)
        signed2 = canon_signed_with_pow(base2, int(proof1))
        sig2 = sign_canonical(wallet, signed2)

        payload = {
            "pubkey": _b64(pub),
            "signature": _b64(sig2),
            "last_block_hash": last,
            "pow_difficulty": int(diff),
            "pow": int(proof1),
            "target": "",
            "topic": topic2,
            "title": title2,
            "content": content2,
        }

        code, resp = _post_json(f"{backend}/api/core/post", payload)
        passed = _expect_fail(resp, code, ["insufficient pow"])
        return TestResult(name=name, passed=passed, status_code=code, response=resp)
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


# ========================================
# DELETED POST ATTACK TESTS
# ========================================


def neg_edit_deleted_post(backend: str, seed: str, deleted_post_tx: str) -> TestResult:
    """Try to edit a deleted post - backend precheck or chain should handle."""
    name = "Edit: deleted post handled"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        last, diff, min_diff, _ = _fetch_params(backend, addr)
        pub = wallet.public_key().public_key_bytes

        new_content = f"Edit deleted at {int(time.time())}"
        new_topic = f"topic{_rand_str(4)}"

        base = canon_base_edit(pub, last, diff, "", new_topic, "", new_content, deleted_post_tx)
        proof = _compute_pow(base, diff, min_diff, last)
        signed = canon_signed_with_pow(base, int(proof))
        sig = sign_canonical(wallet, signed)

        payload = {
            "pubkey": _b64(pub),
            "signature": _b64(sig),
            "last_block_hash": last,
            "pow_difficulty": int(diff),
            "pow": int(proof),
            "target": "",
            "topic": new_topic,
            "title": "",
            "content": new_content,
            "override": deleted_post_tx,
        }

        code, resp = _post_json(f"{backend}/api/core/edit", payload)
        # Soft delete: chain may allow edit, indexer filters display. Either behavior is valid.
        if code >= 400:
            passed = _expect_fail(resp, code, ["override not found", "forbidden", "deleted"])
        else:
            passed = True
        return TestResult(
            name=name, passed=passed, status_code=code, response=resp, details={"override": deleted_post_tx}
        )
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


def neg_vote_deleted_post(backend: str, seed: str, deleted_post_tx: str) -> TestResult:
    """Try to vote on a deleted post - soft delete allows chain ops, indexer filters."""
    name = "Vote: deleted post handled"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        last, diff, min_diff, _ = _fetch_params(backend, addr)
        pub = wallet.public_key().public_key_bytes

        base = canon_base_vote(pub, last, diff, deleted_post_tx, 1)
        proof = _compute_pow(base, diff, min_diff, last)
        signed = canon_signed_with_pow(base, int(proof))
        sig = sign_canonical(wallet, signed)

        payload = {
            "pubkey": _b64(pub),
            "signature": _b64(sig),
            "last_block_hash": last,
            "pow_difficulty": int(diff),
            "pow": int(proof),
            "target": deleted_post_tx,
            "direction": 1,
        }

        code, resp = _post_json(f"{backend}/api/core/vote", payload)

        # Soft delete: chain may allow vote, indexer filters display. Either behavior is valid.
        if code >= 400:
            return TestResult(
                name=name, passed=True, status_code=code, response=resp, details={"target": deleted_post_tx}
            )

        if "tx_hash" in resp:
            txh = str(resp.get("tx_hash"))
            res = wait_tx_result(backend, txh, timeout_s=10.0)
            # Either success or failure is acceptable for soft-deleted posts
            passed = bool(res) and bool(res.get("found"))
            return TestResult(
                name=name, passed=passed, status_code=code, response=res or resp, details={"target": deleted_post_tx}
            )

        return TestResult(name=name, passed=False, status_code=code, response=resp, details={"target": deleted_post_tx})
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


def neg_comment_deleted_post(backend: str, seed: str, deleted_post_tx: str) -> TestResult:
    """Try to comment on a deleted post - soft delete allows chain ops, indexer filters."""
    name = "Comment: deleted post handled"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        last, diff, min_diff, _ = _fetch_params(backend, addr)
        pub = wallet.public_key().public_key_bytes

        content = f"Comment on deleted at {int(time.time())}"

        base = canon_base_post(pub, last, diff, deleted_post_tx, "", "", content)
        proof = _compute_pow(base, diff, min_diff, last)
        signed = canon_signed_with_pow(base, int(proof))
        sig = sign_canonical(wallet, signed)

        payload = {
            "pubkey": _b64(pub),
            "signature": _b64(sig),
            "last_block_hash": last,
            "pow_difficulty": int(diff),
            "pow": int(proof),
            "target": deleted_post_tx,
            "topic": "",
            "title": "",
            "content": content,
        }

        code, resp = _post_json(f"{backend}/api/core/post", payload)

        # Soft delete: chain may allow comment, indexer filters display. Either behavior is valid.
        if code >= 400:
            return TestResult(
                name=name, passed=True, status_code=code, response=resp, details={"target": deleted_post_tx}
            )

        if "tx_hash" in resp:
            txh = str(resp.get("tx_hash"))
            res = wait_tx_result(backend, txh, timeout_s=10.0)
            # Either success or failure is acceptable for soft-deleted posts
            passed = bool(res) and bool(res.get("found"))
            return TestResult(
                name=name, passed=passed, status_code=code, response=res or resp, details={"target": deleted_post_tx}
            )

        return TestResult(name=name, passed=False, status_code=code, response=resp, details={"target": deleted_post_tx})
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


# ========================================
# RACE CONDITION / RAPID OPERATION TESTS
# ========================================


def neg_rapid_multiple_edits(backend: str, seed: str, post_tx: str) -> TestResult:
    """Try rapid multiple edits - should handle gracefully."""
    name = "Race: rapid multiple edits handled"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        last, diff, min_diff, _ = _fetch_params(backend, addr)
        pub = wallet.public_key().public_key_bytes

        results = []
        for i in range(3):
            new_content = f"Rapid edit {i} at {int(time.time())}"
            new_topic = f"topic{_rand_str(4)}"

            base = canon_base_edit(pub, last, diff, "", new_topic, "", new_content, post_tx)
            proof = _compute_pow(base, diff, min_diff, last)
            signed = canon_signed_with_pow(base, int(proof))
            sig = sign_canonical(wallet, signed)

            payload = {
                "pubkey": _b64(pub),
                "signature": _b64(sig),
                "last_block_hash": last,
                "pow_difficulty": int(diff),
                "pow": int(proof),
                "target": "",
                "topic": new_topic,
                "title": "",
                "content": new_content,
                "override": post_tx,
            }

            code, resp = _post_json(f"{backend}/api/core/edit", payload)
            results.append((code, resp))
            sleep(0.1)

        passed = all(code >= 400 or (code == 200 and "tx_hash" in resp) for code, resp in results)
        return TestResult(name=name, passed=passed, status_code=results[0][0], response=results[0][1])
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


def neg_rapid_multiple_votes(backend: str, seed: str, post_tx: str) -> TestResult:
    """Try rapid multiple votes - should handle gracefully."""
    name = "Race: rapid multiple votes handled"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        last, diff, min_diff, _ = _fetch_params(backend, addr)
        pub = wallet.public_key().public_key_bytes

        results = []
        directions = [1, -1, 0, 1]
        for direction in directions:
            base = canon_base_vote(pub, last, diff, post_tx, direction)
            proof = _compute_pow(base, diff, min_diff, last)
            signed = canon_signed_with_pow(base, int(proof))
            sig = sign_canonical(wallet, signed)

            payload = {
                "pubkey": _b64(pub),
                "signature": _b64(sig),
                "last_block_hash": last,
                "pow_difficulty": int(diff),
                "pow": int(proof),
                "target": post_tx,
                "direction": direction,
            }

            code, resp = _post_json(f"{backend}/api/core/vote", payload)
            results.append((code, resp))
            sleep(0.1)

        passed = all(code >= 400 or (code == 200 and "tx_hash" in resp) for code, resp in results)
        return TestResult(name=name, passed=passed, status_code=results[0][0], response=results[0][1])
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


# ========================================
# CROSS-MESSAGE TYPE ATTACK TESTS
# ========================================


def neg_edit_wrong_target_type(backend: str, seed: str, comment_tx: str, parent_tx: str) -> TestResult:
    """Try to edit a comment as if it were a root post (wrong target type)."""
    name = "Edit: comment as root post handled"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        last, diff, min_diff, _ = _fetch_params(backend, addr)
        pub = wallet.public_key().public_key_bytes

        new_content = f"Wrong edit at {int(time.time())}"
        new_topic = f"topic{_rand_str(4)}"

        base = canon_base_edit(pub, last, diff, "", new_topic, "", new_content, comment_tx)
        proof = _compute_pow(base, diff, min_diff, last)
        signed = canon_signed_with_pow(base, int(proof))
        sig = sign_canonical(wallet, signed)

        payload = {
            "pubkey": _b64(pub),
            "signature": _b64(sig),
            "last_block_hash": last,
            "pow_difficulty": int(diff),
            "pow": int(proof),
            "target": "",
            "topic": new_topic,
            "title": "",
            "content": new_content,
            "override": comment_tx,
        }

        code, resp = _post_json(f"{backend}/api/core/edit", payload)

        # Chain may allow or reject editing comment with root post params
        if code >= 400:
            return TestResult(name=name, passed=True, status_code=code, response=resp, details={"override": comment_tx})

        if "tx_hash" in resp:
            txh = str(resp.get("tx_hash"))
            res = wait_tx_result(backend, txh, timeout_s=10.0)
            # Either success or failure is acceptable behavior
            passed = bool(res) and bool(res.get("found"))
            return TestResult(
                name=name, passed=passed, status_code=code, response=res or resp, details={"override": comment_tx}
            )

        return TestResult(name=name, passed=False, status_code=code, response=resp, details={"override": comment_tx})
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


def neg_edit_vote_as_post(backend: str, seed: str, vote_tx: str) -> TestResult:
    """Try to edit a vote transaction hash as if it were a post - should fail."""
    name = "Edit: vote txhash as post rejected"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        last, diff, min_diff, _ = _fetch_params(backend, addr)
        pub = wallet.public_key().public_key_bytes

        new_content = f"Edit vote as post at {int(time.time())}"
        new_topic = f"topic{_rand_str(4)}"

        base = canon_base_edit(pub, last, diff, "", new_topic, "", new_content, vote_tx)
        proof = _compute_pow(base, diff, min_diff, last)
        signed = canon_signed_with_pow(base, int(proof))
        sig = sign_canonical(wallet, signed)

        payload = {
            "pubkey": _b64(pub),
            "signature": _b64(sig),
            "last_block_hash": last,
            "pow_difficulty": int(diff),
            "pow": int(proof),
            "target": "",
            "topic": new_topic,
            "title": "",
            "content": new_content,
            "override": vote_tx,
        }

        code, resp = _post_json(f"{backend}/api/core/edit", payload)
        passed = _expect_fail(resp, code, ["override not found", "forbidden"])
        return TestResult(name=name, passed=passed, status_code=code, response=resp, details={"override": vote_tx})
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


# ========================================
# SUBSCRIBER RESERVE DEPLETION STRESS TEST
# ========================================


def sub_stress_reserve_downgrade(
    backend: str, seed: str, max_posts: int = 200, content_len: int = 1200, wait_after_zero_s: float = 6.0
) -> TestResult:
    """Subscriber hammers posts to deplete reserve funds. Pass when auto-downgraded to level 0 after reserve <= 0."""
    name = "Subscriber: reserve depletion triggers downgrade"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())

        # Ensure user is a subscriber
        status = get_user_status(backend, addr)
        level = int(status.get("user_level") or 0)
        if level < 1:
            up = pos_upgrade_to_level(backend, seed, level=1)
            # do not require success here; we will poll actual level
            _print_result(up)
            time.sleep(2)

        status = get_user_status(backend, addr)
        level = int(status.get("user_level") or 0)
        reserve = int(status.get("reserve_funds") or 0)

        print(f"  Subscriber start: level={level} reserve_funds={reserve}")

        downgraded = False
        details = {"start_level": level, "start_reserve": reserve, "iterations": 0}

        for i in range(1, max_posts + 1):
            # Build larger content to increase gas usage
            topic = f"topic{_rand_str(4)}"
            title = "okay"
            content = ("x" * max(16, content_len))[:content_len]

            # Submit subscriber post without PoW
            last, _diff, _min_diff, _ = _fetch_params(backend, addr)
            pub = wallet.public_key().public_key_bytes
            base = canon_base_post(pub, last, 0, "", topic, title, content)
            signed = canon_signed_with_pow(base, 0)
            sig = sign_canonical(wallet, signed)
            payload = {
                "pubkey": _b64(pub),
                "signature": _b64(sig),
                "last_block_hash": last,
                "pow_difficulty": 0,
                "pow": 0,
                "target": "",
                "topic": topic,
                "title": title,
                "content": content,
            }
            code, resp = _post_json(f"{backend}/api/core/post", payload)
            if code != 200 or "tx_hash" not in resp:
                return TestResult(name=name, passed=False, status_code=code, response=resp, details=details)
            txh = str(resp.get("tx_hash"))
            res = wait_tx_result(backend, txh, timeout_s=15.0)
            if not (res and res.get("found") and res.get("success")):
                return TestResult(name=name, passed=False, status_code=code, response=res or resp, details=details)

            # After each tx, fetch reserve and level
            status = get_user_status(backend, addr)
            level = int(status.get("user_level") or 0)
            reserve = int(status.get("reserve_funds") or 0)
            details["iterations"] = i
            details["last_tx"] = txh
            details["reserve"] = reserve
            details["level"] = level
            print(f"  iter={i} reserve_funds={reserve} level={level}")

            if reserve <= 0:
                # Give the chain a moment to process downgrade if asynchronous
                t_end = time.time() + wait_after_zero_s
                while time.time() < t_end:
                    status2 = get_user_status(backend, addr)
                    lvl2 = int(status2.get("user_level") or 0)
                    res2 = int(status2.get("reserve_funds") or 0)
                    print(f"    check: reserve_funds={res2} level={lvl2}")
                    if lvl2 == 0:
                        downgraded = True
                        details["final_level"] = lvl2
                        details["final_reserve"] = res2
                        break
                    time.sleep(1.0)
                break

        return TestResult(
            name=name, passed=downgraded, status_code=200, response={"downgraded": downgraded}, details=details
        )
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


def main() -> int:
    parser = argparse.ArgumentParser(description="Mirage Backend Attack Tests")
    parser.add_argument("--backend", default=DEFAULT_BACKEND, help=f"Backend URL (default: {DEFAULT_BACKEND})")
    parser.add_argument("--seed-free", required=True, help="Mnemonic seed for free user wallet")
    parser.add_argument("--seed-subscriber", required=True, help="Mnemonic seed for subscriber wallet")
    args = parser.parse_args()

    backend = str(args.backend).rstrip("/")
    seed_free = args.seed_free
    seed_sub = args.seed_subscriber

    print(f"Backend: {backend}")
    try:
        w_free = create_wallet_from_seed(seed_free)
        addr_free = str(w_free.address())
        last_f, diff_f, min_diff_f, bal_f = _fetch_params(backend, addr_free)
        print(f"FREE addr: {addr_free} | balance: {bal_f} | pow_difficulty: {diff_f} | last_block_hash: {last_f}")
        w_sub = create_wallet_from_seed(seed_sub)
        addr_sub = str(w_sub.address())
        last_s, diff_s, min_diff_s, bal_s = _fetch_params(backend, addr_sub)
        print(f"SUB  addr: {addr_sub} | balance: {bal_s} | pow_difficulty: {diff_s} | last_block_hash: {last_s}")
    except Exception as e:
        print(f"Failed to init: {e}")
        return 2

    all_results: List[TestResult] = []
    foreign_post_tx: Optional[str] = None

    # ========================================
    # POSITIVE TESTS
    # ========================================
    print("\n" + "=" * 60)
    print("POSITIVE TESTS (Sanity)")
    print("=" * 60)

    # Create a post (FREE user)
    r, post_tx = pos_create_post(backend, seed_free)
    all_results.append(r)
    _print_result(r)

    # Create a post with media (FREE user)
    r, media_post_tx = pos_create_post_with_media(backend, seed_free)
    all_results.append(r)
    _print_result(r)
    media_expected = (r.details or {}).get("media_expected") if hasattr(r, "details") else None

    if post_tx:
        # Clear any existing vote (direction=0)
        r = pos_vote_clear(backend, seed_free, post_tx)
        all_results.append(r)
        _print_result(r)

        # Vote on it (downvote)
        r = pos_vote_downvote(backend, seed_free, post_tx)
        all_results.append(r)
        _print_result(r)

        # Vote on it (upvote)
        r = pos_vote_upvote(backend, seed_free, post_tx)
        all_results.append(r)
        _print_result(r)

        # Comment on it
        r, comment_tx = pos_create_comment(backend, seed_free, post_tx)
        all_results.append(r)
        _print_result(r)

        # Negative edit tests are run later in the NEGATIVE TESTS section
        # Edit the post
        sleep(4)
        r = pos_edit_post(backend, seed_free, post_tx)
        all_results.append(r)
        _print_result(r)

    if media_post_tx:
        # Edit the media post and ensure media is preserved
        sleep(4)
        r = pos_edit_post(backend, seed_free, media_post_tx)
        all_results.append(r)
        _print_result(r)
        if r.passed and media_expected is not None:
            media_val = _get_post_media(backend, addr_free, media_post_tx)
            ok = media_val == media_expected
            r_media = TestResult(
                name="Edit preserves media",
                passed=ok,
                details={"expected": media_expected, "received": media_val},
            )
            all_results.append(r_media)
            _print_result(r_media)

        # Report the post
        r = pos_report_post(backend, seed_free, post_tx)
        all_results.append(r)
        _print_result(r)

        # Delete the post (do this last!)
        sleep(4)
        r = pos_delete_post(backend, seed_free, post_tx)
        all_results.append(r)
        _print_result(r)

    # Set username (FREE)
    r = pos_set_username(backend, seed_free)
    all_results.append(r)
    _print_result(r)
    # Free username prefix behavior
    r = pos_free_username_prefixed(backend, seed_free)
    all_results.append(r)
    _print_result(r)
    r = pos_free_username_prefixed_once(backend, seed_free)
    all_results.append(r)
    _print_result(r)

    # Follow/unfollow self as moderator
    r = pos_follow_moderator(backend, seed_free, addr_free)
    all_results.append(r)
    _print_result(r)

    r = pos_unfollow_moderator(backend, seed_free, addr_free)
    all_results.append(r)
    _print_result(r)

    # Create another post for negative tests
    r2, test_post_tx = pos_create_post(backend, seed_free)
    _print_result(r2)
    if not r2.passed:
        print(f"  Warning: Could not create test post: {r2.error or r2.response}")

    # Test all valid content tags
    print("\n  --- Content Tag Tests (valid tags) ---")
    tag_results = pos_create_posts_all_valid_tags(backend, seed_free)
    for r in tag_results:
        all_results.append(r)
        _print_result(r)

    # ========================================
    # NEGATIVE TESTS
    # ========================================
    print("\n" + "=" * 60)
    print("NEGATIVE TESTS (Attack scenarios)")
    print("=" * 60)

    neg_tests = [
        neg_post_oversize_content,
        neg_post_oversize_title,
        neg_post_media_not_list,
        neg_post_media_over_limit,
        neg_post_media_non_https,
        neg_post_media_item_too_long,
        neg_missing_pow_free_user,
        # Topic format invalid cases
        # Root post with hyphen in topic
        lambda backend, seed: _neg_post_topic_invalid(
            backend, seed, "topic-bad", "Post: invalid topic (hyphen) rejected"
        ),
        lambda backend, seed: _neg_post_topic_invalid(
            backend, seed, "TopicUpper", "Post: invalid topic (uppercase) rejected"
        ),
        lambda backend, seed: _neg_post_topic_invalid(
            backend, seed, "topic bad", "Post: invalid topic (space) rejected"
        ),
        lambda backend, seed: _neg_post_topic_invalid(
            backend, seed, "topic_bad", "Post: invalid topic (underscore) rejected"
        ),
        lambda backend, seed: _neg_post_topic_invalid(backend, seed, "to", "Post: invalid topic (too short) rejected"),
        neg_comment_invalid_target,
        neg_invalid_pubkey_length,
        neg_tampered_signature,
        neg_insufficient_pow,
        neg_invalid_last_block_hash,
        (
            (lambda backend, seed: neg_delete_not_owner_with_tx(backend, seed, foreign_post_tx))
            if "foreign_post_tx" in locals() and foreign_post_tx
            else neg_delete_not_owner
        ),
        neg_vote_invalid_target,
        neg_report_reason_too_long,
        neg_send_tokens_invalid,
        neg_send_tokens_insufficient_funds,
        # Username invalid format cases
        lambda backend, seed: neg_username_invalid(backend, seed, "user name", "space"),
        lambda backend, seed: neg_username_invalid(backend, seed, "user.", "dot"),
        lambda backend, seed: neg_username_invalid(backend, seed, "user@", "symbol"),
        lambda backend, seed: neg_username_invalid(backend, seed, "🙂user", "emoji"),
        neg_username_too_short,
        neg_username_too_long,
        # Content tag invalid cases
        lambda backend, seed: neg_post_invalid_tag(backend, seed, "invalid", "unknown tag"),
        lambda backend, seed: neg_post_invalid_tag(backend, seed, "SENSITIVE", "uppercase"),
        lambda backend, seed: neg_post_invalid_tag(backend, seed, "nsfw", "nsfw instead of sensitive"),
        lambda backend, seed: neg_post_invalid_tag(backend, seed, "adult", "adult instead of porn"),
        lambda backend, seed: neg_post_invalid_tag(backend, seed, "blood", "blood instead of gore"),
        lambda backend, seed: neg_post_invalid_tag(backend, seed, "Porn", "mixed case"),
    ]

    for test_fn in neg_tests:
        if test_fn is neg_comment_invalid_target:
            r = test_fn(backend, seed_free)
        else:
            r = test_fn(backend, seed_free)
        all_results.append(r)
        _print_result(r)

    # Additional permutations that depend on a valid parent post
    if test_post_tx:
        sleep(4)
        # Negative edit: root missing topic
        r = neg_edit_root_missing_topic(backend, seed_free, test_post_tx)
        all_results.append(r)
        _print_result(r)

        r = neg_comment_missing_content(backend, seed_free, test_post_tx)
        all_results.append(r)
        _print_result(r)

        r = neg_comment_with_topic(backend, seed_free, test_post_tx)
        all_results.append(r)
        _print_result(r)

        # Create a comment to serve as edit target
        print("  (Creating comment for negative edit tests: Edit: comment with topic rejected)")
        rc, test_comment_tx = pos_create_comment(backend, seed_free, test_post_tx)
        all_results.append(rc)
        _print_result(rc)
        if test_comment_tx:
            r = neg_edit_comment_with_topic(backend, seed_free, test_comment_tx, test_post_tx)
            all_results.append(r)
            _print_result(r)

            # Note: neg_edit_foreign_comment tests are done in subscriber section
            # where we have comments owned by different users

            # Cross-message type attack: edit comment as root post
            r = neg_edit_wrong_target_type(backend, seed_free, test_comment_tx, test_post_tx)
            all_results.append(r)
            _print_result(r)

        # Authorization attacks: edit foreign post
        if foreign_post_tx:
            r = neg_edit_foreign_post_free(backend, seed_free, foreign_post_tx)
            all_results.append(r)
            _print_result(r)

        # Race condition tests
        r = neg_rapid_multiple_edits(backend, seed_free, test_post_tx)
        all_results.append(r)
        _print_result(r)

        r = neg_rapid_multiple_votes(backend, seed_free, test_post_tx)
        all_results.append(r)
        _print_result(r)

        # Create a post to delete for deleted post attack tests
        print("  (Creating post for deleted post attack tests)")
        r_del, del_post_tx = pos_create_post(backend, seed_free)
        all_results.append(r_del)
        _print_result(r_del)
        if del_post_tx:
            sleep(2)
            r_del_act = pos_delete_post(backend, seed_free, del_post_tx)
            all_results.append(r_del_act)
            _print_result(r_del_act)
            sleep(2)

            r = neg_edit_deleted_post(backend, seed_free, del_post_tx)
            all_results.append(r)
            _print_result(r)

            r = neg_vote_deleted_post(backend, seed_free, del_post_tx)
            all_results.append(r)
            _print_result(r)

            r = neg_comment_deleted_post(backend, seed_free, del_post_tx)
            all_results.append(r)
            _print_result(r)

        # Create a vote to test editing vote as post
        if test_post_tx:
            r_vote = pos_vote_upvote(backend, seed_free, test_post_tx)
            all_results.append(r_vote)
            _print_result(r_vote)
            if r_vote.details.get("tx_hash"):
                vote_tx = r_vote.details.get("tx_hash")
                r = neg_edit_vote_as_post(backend, seed_free, vote_tx)
                all_results.append(r)
                _print_result(r)

    # Root post missing topic
    r = neg_post_missing_topic(backend, seed_free)
    all_results.append(r)
    _print_result(r)

    # Replay attacks
    r = neg_replay_old_signature(backend, seed_free)
    all_results.append(r)
    _print_result(r)

    r = neg_replay_old_block_hash(backend, seed_free)
    all_results.append(r)
    _print_result(r)

    r = neg_pow_proof_reuse(backend, seed_free)
    all_results.append(r)
    _print_result(r)

    # Authorization: set username for foreign address
    try:
        w_foreign = create_wallet_from_seed(seed_sub)
        addr_foreign = str(w_foreign.address())
        r = neg_set_username_foreign(backend, seed_free, addr_foreign)
        all_results.append(r)
        _print_result(r)
    except Exception:
        pass

    # ========================================
    # SUBSCRIBER TESTS
    # ========================================
    print("\n" + "=" * 60)
    print("SUBSCRIBER TESTS (Level 1)")
    print("=" * 60)
    r = pos_upgrade_to_level(backend, seed_sub, level=1)
    all_results.append(r)
    _print_result(r)

    # Create a foreign post (by subscriber) for authorization tests
    print("  (Creating foreign post by subscriber for authorization tests)")
    try:
        r_foreign, foreign_post_tx = pos_subscriber_post_no_pow(backend, seed_sub)
        all_results.append(r_foreign)
        _print_result(r_foreign)
    except Exception as _e:
        print(f"  Warning: Could not create foreign post: {_e}")

    # Negative upgrade attempts with FREE account (insufficient funds)
    for lvl in (1, 2, 3):
        r = neg_upgrade_insufficient_funds(backend, seed_free, level=lvl)
        all_results.append(r)
        _print_result(r)
    # Invalid level
    r = neg_upgrade_invalid_level(backend, seed_free, level=100)
    all_results.append(r)
    _print_result(r)
    # As subscriber, PoW should be rejected
    r = neg_subscriber_pow_post(backend, seed_sub)
    all_results.append(r)
    _print_result(r)
    # As subscriber, post without PoW should succeed
    r_sub, sub_post_tx = pos_subscriber_post_no_pow(backend, seed_sub)
    all_results.append(r_sub)
    _print_result(r_sub)
    if sub_post_tx:
        # Subscriber votes without PoW
        r = sub_pos_vote(backend, seed_sub, sub_post_tx, 0, "clear vote")
        all_results.append(r)
        _print_result(r)
        r = sub_pos_vote(backend, seed_sub, sub_post_tx, -1, "downvote")
        all_results.append(r)
        _print_result(r)
        r = sub_pos_vote(backend, seed_sub, sub_post_tx, 1, "upvote")
        all_results.append(r)
        _print_result(r)
        # Subscriber comment
        rc, sub_comment_tx = sub_pos_create_comment(backend, seed_sub, sub_post_tx)
        all_results.append(rc)
        _print_result(rc)
        # Subscriber edit and delete - wait for indexer to catch up
        print("  (Waiting for post to be indexed...)")
        indexed = wait_post_indexed(backend, addr_sub, sub_post_tx, timeout_s=45.0)
        if indexed:
            r = sub_pos_edit_post(backend, seed_sub, sub_post_tx)
            all_results.append(r)
            _print_result(r)
            sleep(4)
            r = sub_pos_delete_post(backend, seed_sub, sub_post_tx)
            all_results.append(r)
            _print_result(r)
        else:
            print("  SKIP: Subscriber: edit post (indexer timeout)")
            print("  SKIP: Subscriber: delete own post (indexer timeout)")
        # Subscriber PoW should be rejected across endpoints
        # Note: sub_post_tx may be deleted, so PoW rejection tests use it anyway (deleted or not)
        r = neg_subscriber_pow_vote(backend, seed_sub, sub_post_tx, 1, "vote")
        all_results.append(r)
        _print_result(r)
        # For edit, wait for foreign_post_tx to be indexed
        if foreign_post_tx:
            indexed = wait_post_indexed(backend, addr_sub, foreign_post_tx, timeout_s=45.0)
            if indexed:
                r = neg_subscriber_pow_edit(backend, seed_sub, foreign_post_tx)
                all_results.append(r)
                _print_result(r)
            else:
                print("  SKIP: Subscriber: PoW not allowed (edit) rejected (indexer timeout)")
        # Subscriber negative invariants (no PoW)
        r = sub_neg_comment_with_topic(backend, seed_sub, sub_post_tx)
        all_results.append(r)
        _print_result(r)
        r = sub_neg_comment_missing_content(backend, seed_sub, sub_post_tx)
        all_results.append(r)
        _print_result(r)
        r = sub_neg_post_missing_topic(backend, seed_sub)
        all_results.append(r)
        _print_result(r)
        r = sub_neg_vote_invalid_target(backend, seed_sub)
        all_results.append(r)
        _print_result(r)
        if "post_tx" in locals() and post_tx:
            r = sub_neg_delete_not_owner(backend, seed_sub, post_tx)
            all_results.append(r)
            _print_result(r)

            # Authorization attacks: subscriber edit foreign post
            r = neg_edit_foreign_post_subscriber(backend, seed_sub, post_tx)
            all_results.append(r)
            _print_result(r)

            # Create a comment by free user for subscriber to try editing
            print("  (Creating comment by free user for subscriber authorization test)")
            rc_free, free_comment_tx = pos_create_comment(backend, seed_free, post_tx)
            all_results.append(rc_free)
            _print_result(rc_free)
            if free_comment_tx:
                r = neg_edit_foreign_comment_subscriber(backend, seed_sub, free_comment_tx, post_tx)
                all_results.append(r)
                _print_result(r)

        # Test free user trying to edit subscriber's comment
        if foreign_post_tx:
            print("  (Creating comment by subscriber for free user authorization test)")
            rc_sub2, sub_comment_tx2 = sub_pos_create_comment(backend, seed_sub, foreign_post_tx)
            all_results.append(rc_sub2)
            _print_result(rc_sub2)
            if sub_comment_tx2:
                r = neg_edit_foreign_comment_free(backend, seed_free, sub_comment_tx2, foreign_post_tx)
                all_results.append(r)
                _print_result(r)

    # Subscriber set username without PoW
    r = sub_pos_set_username(backend, seed_sub)
    all_results.append(r)
    _print_result(r)
    # Subscriber follow/unfollow without PoW
    r = sub_pos_follow_moderator(backend, seed_sub, addr_sub)
    all_results.append(r)
    _print_result(r)
    r = sub_pos_unfollow_moderator(backend, seed_sub, addr_sub)
    all_results.append(r)
    _print_result(r)
    # Subscriber PoW should be rejected for set_username, send_tokens, follow/unfollow
    r = neg_subscriber_pow_set_username(backend, seed_sub)
    all_results.append(r)
    _print_result(r)
    r = neg_subscriber_pow_send_tokens(backend, seed_sub)
    all_results.append(r)
    _print_result(r)
    r = neg_subscriber_pow_follow(backend, seed_sub, addr_sub)
    all_results.append(r)
    _print_result(r)
    r = neg_subscriber_pow_unfollow(backend, seed_sub, addr_sub)
    all_results.append(r)
    _print_result(r)

    # ========================================
    # RUN: RESERVE DEPLETION STRESS TEST
    # ========================================
    print("\n" + "=" * 60)
    print("SUBSCRIBER RESERVE DEPLETION STRESS TEST")
    print("=" * 60)
    r = sub_stress_reserve_downgrade(backend, seed_sub, max_posts=200, content_len=1500)
    all_results.append(r)
    _print_result(r)

    # ========================================
    # SUMMARY
    # ========================================
    print("\n" + "=" * 60)
    passed = sum(1 for r in all_results if r.passed)
    failed = [r for r in all_results if not r.passed]
    print(f"PASSED: {passed}/{len(all_results)}")
    if failed:
        print(f"FAILED: {len(failed)}")
        for r in failed:
            print(f"  - {r.name}")
    print("=" * 60)

    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
