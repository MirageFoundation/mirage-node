#!/usr/bin/env python3
"""
Mirage RPC Attack Tests

Tests direct RPC interaction bypassing the backend.
The attacker uses their own address as authority and pays their own fees.

Run: conda activate mirage-node && python tests/attack_tests_rpc.py
"""
from __future__ import annotations

import argparse
import base64
import os
import sys
import time
import random
import string
import math
from dataclasses import dataclass, field
from typing import Optional, Tuple

import requests

# Make repo root importable
THIS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(THIS_DIR, ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from shared.client import (
    create_wallet_from_seed,
    sign_canonical,
)
from shared.canon import (
    canon_base_post,
    canon_base_vote,
    canon_signed_with_pow,
    canon_base_set_username,
    canon_base_delete,
    canon_base_follow_moderator,
    canon_base_unfollow_moderator,
    canon_base_edit,
    canon_base_send_tokens,
    canon_base_upgrade_level,
)
from google.protobuf.any_pb2 import Any as AnyPB
from cosmpy.protos.cosmos.tx.v1beta1.tx_pb2 import TxBody, TxRaw, AuthInfo, Fee, ModeInfo, SignerInfo
from cosmpy.protos.cosmos.tx.signing.v1beta1.signing_pb2 import SignMode
from cosmpy.protos.cosmos.base.v1beta1.coin_pb2 import Coin
from cosmpy.protos.cosmos.crypto.secp256k1.keys_pb2 import PubKey as SecpPubKey
from shared.datatypes import (
    MsgPost,
    MsgVote,
    MsgFollowModerator,
    MsgUnfollowModerator,
    MsgEdit,
    MsgDelete,
    MsgSetUsername,
    MsgSendTokens,
    MsgUpgradeLevel,
)

MIN_GAS_PRICE = 0.025
RPC_URL = ""
_POW_FACTOR: float | None = None

# Default RPC
DEFAULT_RPC = "http://127.0.0.1:26657"


def _now_ms() -> int:
    """Return current time as milliseconds since epoch."""
    return int(time.time() * 1000)


def _lb_bytes(lb_hex: str) -> bytes:
    """Convert last_block_hash hex to bytes."""
    try:
        return bytes.fromhex(lb_hex.strip())
    except Exception:
        return lb_hex.encode("utf-8")


@dataclass
class TestResult:
    name: str
    passed: bool
    status_code: Optional[int] = None
    response: Optional[dict] = None
    error: Optional[str] = None
    details: dict = field(default_factory=dict)


def _rand_str(n: int = 8) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))


def _rpc_get_latest_block_hash() -> str:
    try:
        with requests.get(f"{RPC_URL}/status", timeout=3.0) as r:
            r.raise_for_status()
            data = r.json()
        sync = (data.get("result") or {}).get("sync_info", {}) or {}
        raw = (sync.get("latest_block_hash") or "").strip()
        if not raw:
            raw = (((sync.get("latest_block_id") or {})).get("hash") or "").strip()
        if not raw:
            raise RuntimeError("empty hash from /status")
        if len(raw) == 64 and all(c in "0123456789abcdefABCDEF" for c in raw):
            return raw.lower()
        try:
            decoded = base64.b64decode(raw)
            hexed = decoded.hex()
            if len(hexed) == 64:
                return hexed
        except Exception:
            pass
        maybe = raw.strip().lower()
        if len(maybe) == 64 and all(c in "0123456789abcdef" for c in maybe):
            return maybe
        raise RuntimeError("unusable hash from /status")
    except Exception as e:
        raise RuntimeError(f"status error: {e}")


def _rpc_abci_uint64(key_name: str, timeout_s: float = 3.0) -> int:
    """Fetch a uint64 value from the core ABCI store."""
    import base64 as _b64
    import struct as _st

    if not RPC_URL:
        raise RuntimeError("RPC_URL not set")
    paths = ['"/store/core/key"', "/store/core/key"]
    key_bytes = key_name.encode("utf-8")
    datas = ["0x" + key_bytes.hex(), _b64.b64encode(key_bytes).decode("ascii")]
    for p in paths:
        for data_param in datas:
            try:
                with requests.get(
                    f"{RPC_URL}/abci_query",
                    params={"path": p, "data": data_param, "prove": "false"},
                    timeout=timeout_s,
                ) as r:
                    if r.status_code != 200:
                        continue
                    data = r.json()
                value_b64 = (((data or {}).get("result") or {}).get("response") or {}).get("value")
                if value_b64:
                    raw = _b64.b64decode(value_b64)
                    if len(raw) == 8:
                        return int(_st.unpack(">Q", raw)[0])
            except Exception:
                continue
    raise RuntimeError(f"unable to fetch {key_name} via ABCI")


def _rpc_get_current_pow_difficulty(timeout_s: float = 3.0) -> tuple[int, int]:
    """Return (current_difficulty, pow_base_bits) from on-chain state."""
    global _POW_FACTOR
    diff = _rpc_abci_uint64("current_difficulty", timeout_s)
    base_bits = _rpc_abci_uint64("pow_base_bits", timeout_s)
    _POW_FACTOR = _rpc_get_pow_factor(timeout_s)
    return diff, base_bits


def _rpc_get_pow_factor(timeout_s: float = 3.0) -> float:
    if not RPC_URL:
        raise RuntimeError("RPC_URL not set")
    # Prefer LCD if available
    lcd = RPC_URL
    if ":26657" in lcd:
        lcd = lcd.replace(":26657", ":1317")
    url = f"{lcd}/mirage/core/v1/params"
    with requests.get(url, timeout=timeout_s) as r:
        r.raise_for_status()
        data = r.json() or {}
    params = data.get("params") or {}
    if "pow_factor" not in params:
        raise RuntimeError("pow_factor missing from params")
    return float(params["pow_factor"])


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


def _compute_pow(
    base: bytes, difficulty_steps: int, pow_base_bits: int, last_block_hash: str, max_seconds: float = 20.0
) -> int:
    try:
        from argon2.low_level import hash_secret_raw as _argon2_hash_raw, Type as _Argon2Type
    except Exception as e:
        raise RuntimeError("argon2-cffi is required for PoW tests") from e
    if difficulty_steps < 0:
        raise ValueError("difficulty must be >= 0")
    if pow_base_bits <= 0 or pow_base_bits > 256:
        raise ValueError("pow_base_bits must be in [1, 256]")
    if _POW_FACTOR is None:
        raise ValueError("pow_factor missing")
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
        if _check_pow_target(digest, difficulty_steps, pow_base_bits, _POW_FACTOR):
            return proof
        if (time.perf_counter() - start) > max_seconds:
            raise TimeoutError(f"PoW mining exceeded {max_seconds:.1f}s")
        proof += 1


_BASE_DIFFICULTY_FACTOR = 1000
_MAX_SAFE_DIFFICULTY_FACTOR = (1 << 53) - 1


def _round_half_up(value: float) -> int:
    return int(math.floor(value + 0.5))


def _difficulty_factor(difficulty_steps: int, pow_factor: float) -> int | None:
    if difficulty_steps < 0:
        return None
    if not math.isfinite(pow_factor) or pow_factor <= 0 or pow_factor > 1:
        return None
    if difficulty_steps == 0:
        return _BASE_DIFFICULTY_FACTOR
    try:
        factor = _BASE_DIFFICULTY_FACTOR * math.pow(1.0 + pow_factor, float(difficulty_steps))
    except Exception:
        return _MAX_SAFE_DIFFICULTY_FACTOR
    if not math.isfinite(factor):
        return _MAX_SAFE_DIFFICULTY_FACTOR
    if factor > _MAX_SAFE_DIFFICULTY_FACTOR:
        return _MAX_SAFE_DIFFICULTY_FACTOR
    rounded = _round_half_up(factor)
    return max(_BASE_DIFFICULTY_FACTOR, rounded)


def _check_pow_target(digest: bytes, difficulty_steps: int, pow_base_bits: int, pow_factor: float) -> bool:
    """Target-based PoW check. difficulty is steps (0=base, 1=+step, 2=+step^2)."""
    if pow_base_bits <= 0 or pow_base_bits > 256:
        return False
    factor = _difficulty_factor(difficulty_steps, pow_factor)
    if factor is None:
        return False
    base_target = 1 << (256 - pow_base_bits)
    eff_target = base_target * _BASE_DIFFICULTY_FACTOR // factor
    return int.from_bytes(digest, "big") <= eff_target


def _build_tx_bytes(body_bytes: bytes, gas_limit: int, fee_payer: str) -> bytes:
    """Build transaction bytes with the specified fee payer (attacker's own address)."""
    import math

    fee_amt = int(math.ceil(gas_limit * MIN_GAS_PRICE))
    fee = Fee(gas_limit=gas_limit)
    fee.amount.extend([Coin(denom="umirage", amount=str(fee_amt))])
    fee.payer = fee_payer
    dummy_pubkey = b"\x02" + b"\x00" * 32
    pub_any = AnyPB()
    pub_any.Pack(SecpPubKey(key=dummy_pubkey))
    pub_any.type_url = "/cosmos.crypto.secp256k1.PubKey"
    mode = ModeInfo(single=ModeInfo.Single(mode=SignMode.SIGN_MODE_DIRECT))
    si = SignerInfo(public_key=pub_any, mode_info=mode, sequence=0)
    auth = AuthInfo(signer_infos=[si], fee=fee)
    return TxRaw(
        body_bytes=body_bytes, auth_info_bytes=auth.SerializeToString(), signatures=[b"\x00"]
    ).SerializeToString()


def _rpc_broadcast(any_msg: AnyPB, content_len: int, fee_payer: str) -> Tuple[str, int, str]:
    """Broadcast transaction to RPC."""
    body = TxBody(messages=[any_msg], memo="")
    body_bytes = body.SerializeToString()
    gas_limit = 200000 + content_len * 30
    tx_bytes = _build_tx_bytes(body_bytes, gas_limit, fee_payer)
    try:
        r = requests.get(f"{RPC_URL}/broadcast_tx_sync", params={"tx": "0x" + tx_bytes.hex()}, timeout=5.0)
        if r.status_code == 200:
            data = r.json() or {}
            res = data.get("result") or data
            txh = str(res.get("hash", "") or "").lower()
            code = int(res.get("code", 0) or 0)
            log = str(res.get("log", "") or "")
            return txh, code, log
        return "", 1, f"rpc status {r.status_code}"
    except Exception as e:
        return "", 1, str(e)


def _rpc_wait_tx_result(tx_hash: str, timeout_s: float = 15.0, interval_s: float = 0.5) -> Optional[dict]:
    url = f"{RPC_URL}/tx"
    deadline = time.perf_counter() + timeout_s
    last = None
    while time.perf_counter() < deadline:
        try:
            with requests.get(url, params={"hash": f"0x{tx_hash.upper()}", "prove": "false"}, timeout=3.0) as r:
                if r.status_code != 200:
                    time.sleep(interval_s)
                    continue
                data = r.json()
                res = (data or {}).get("result", {})
                height = int(res.get("height", 0) or 0)
                if height > 0:
                    code = int((res.get("tx_result") or {}).get("code", 0) or 0)
                    raw_log = str((res.get("tx_result") or {}).get("log", ""))
                    last = {
                        "found": True,
                        "tx_hash": tx_hash.lower(),
                        "height": height,
                        "code": code,
                        "raw_log": raw_log,
                        "success": (code == 0),
                    }
                    return last
                last = {"found": False}
        except Exception:
            pass
        time.sleep(interval_s)
    return last


def _broadcast_and_wait(any_msg: AnyPB, content_len: int, fee_payer: str) -> Tuple[str, dict]:
    """Broadcast and wait for transaction result."""
    txh, code, raw_log = _rpc_broadcast(any_msg, content_len, fee_payer)
    if code != 0:
        return txh, {"found": True, "code": code, "raw_log": raw_log, "success": False, "tx_hash": txh}
    if not txh:
        return "", {"found": False, "code": 1, "raw_log": "broadcast failed", "success": False}
    res = _rpc_wait_tx_result(txh)
    return txh, (res or {"found": False, "success": False})


def _estimate_gas_and_fee(content_len: int) -> tuple[int, int]:
    """Return (gas_limit, offered_fee_umirage)."""
    import math

    gas_limit = 200000 + int(content_len) * 30
    fee_amt = int(math.ceil(gas_limit * MIN_GAS_PRICE))
    return gas_limit, fee_amt


def _cli_get_balance(addr: str, denom: str = "umirage") -> Optional[int]:
    """Try to get balance via local CLI. Returns amount as int or None if not available."""
    try:
        import subprocess, json as _json

        cmd = [
            "miraged",
            "q",
            "bank",
            "balances",
            addr,
            "--node",
            RPC_URL,
            "-o",
            "json",
        ]
        out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, timeout=5.0)
        data = _json.loads(out.decode("utf-8", errors="ignore"))
        for c in data.get("balances") or []:
            if str(c.get("denom")) == denom:
                return int(c.get("amount") or 0)
        return 0
    except Exception:
        return None


def _broadcast_with_balance(any_msg: AnyPB, content_len: int, fee_payer: str, details: dict) -> tuple[str, dict]:
    """Broadcast and record balance/fee info in details."""
    gas_limit, offered_fee = _estimate_gas_and_fee(content_len)
    bal_before = _cli_get_balance(fee_payer)
    txh, res = _broadcast_and_wait(any_msg, content_len, fee_payer)
    bal_after = _cli_get_balance(fee_payer)
    details.setdefault("gas_limit", gas_limit)
    details.setdefault("min_gas_price", MIN_GAS_PRICE)
    details.setdefault("offered_fee", offered_fee)
    details.setdefault("fee_denom", "umirage")
    if bal_before is not None:
        details.setdefault("balance_before", bal_before)
    if bal_after is not None:
        details.setdefault("balance_after", bal_after)
    if bal_before is not None and bal_after is not None:
        # Actual deducted fee as observed (should equal offered_fee when success)
        actual = max(0, bal_before - bal_after)
        details.setdefault("fee_actual", actual)
    return txh, res


def _print_result(r: TestResult) -> None:
    status = "PASS" if r.passed else "FAIL"
    # Check if test uses PoW
    uses_pow = r.details.get("uses_pow", True) if r.details else True
    pow_tag = "[PoW]" if uses_pow else "[NO-PoW]"
    print(f"- {status}: {r.name} {pow_tag}", flush=True)

    # Print input parameters from details
    if r.details:
        print(f"  inputs:", flush=True)
        for k, v in r.details.items():
            if k in ("tx_hash", "uses_pow"):
                continue  # Skip these in inputs
            val = str(v) if v is not None else ""
            # Truncate long values
            if len(val) > 80:
                val = val[:77] + "..."
            print(f"    {k}: {val}", flush=True)

    if r.response:
        try:
            print(f"  outputs:", flush=True)
            txh = r.response.get("tx_hash", "")
            h = r.response.get("height")
            code = r.response.get("code")
            succ = r.response.get("success")
            raw_log = r.response.get("raw_log", "")
            print(f"    tx_hash: {txh}", flush=True)
            print(f"    height: {h}", flush=True)
            print(f"    code: {code}", flush=True)
            print(f"    success: {succ}", flush=True)
            if raw_log:
                print(f"    raw_log: {raw_log[:150]}", flush=True)
        except Exception:
            pass
    # If we captured balances/fees, show a concise summary here as well
    try:
        if r.details:
            bal_after = r.details.get("balance_after")
            fee_actual = r.details.get("fee_actual")
            offered_fee = r.details.get("offered_fee")
            if bal_after is not None or fee_actual is not None:
                print(f"  cost:", flush=True)
                if bal_after is not None:
                    print(f"    balance_after: {bal_after}", flush=True)
                if fee_actual is not None:
                    print(f"    fee_actual: {fee_actual}", flush=True)
                if offered_fee is not None:
                    print(f"    offered_fee: {offered_fee}", flush=True)
    except Exception:
        pass
    if r.error:
        print(f"  -> error: {r.error}", flush=True)
    print("", flush=True)


# ========================================
# POSITIVE TESTS (Direct RPC)
# ========================================


def pos_create_post(seed: str) -> Tuple[TestResult, Optional[str]]:
    """Create a new post via direct RPC (attacker pays own fees)."""
    name = "Create post"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        pub = wallet.public_key().public_key_bytes
        last = _rpc_get_latest_block_hash()
        diff, min_diff = _rpc_get_current_pow_difficulty()
        ts = _now_ms()
        topic = f"topic{_rand_str(5)}"
        title = f"Test Post {_rand_str(6)}"
        content = f"RPC post at {int(time.time())}"
        details = {
            "address": addr,
            "topic": topic,
            "title": title,
            "content": content,
            "pow_difficulty": diff,
            "uses_pow": True,
        }
        base = canon_base_post(pub, _lb_bytes(last), diff, ts, "", topic, title, content)
        proof = _compute_pow(base, diff, min_diff, last, max_seconds=15.0)
        signed = canon_signed_with_pow(base, int(proof))
        sig = sign_canonical(wallet, signed)
        msg = MsgPost()
        msg.authority = addr
        msg.envelope_pubkey = pub
        msg.envelope_block_hash = _lb_bytes(last)
        msg.envelope_difficulty = int(diff)
        msg.envelope_pow = int(proof)
        msg.envelope_timestamp = ts
        msg.envelope_signature = sig
        msg.target = ""
        msg.topic = topic
        msg.title = title
        msg.content = content
        any_msg = AnyPB()
        any_msg.type_url = "/mirage.core.v1.MsgPost"
        any_msg.value = msg.SerializeToString()
        txh, res = _broadcast_with_balance(any_msg, len(title) + len(content), addr, details)
        ok = bool(res.get("found")) and bool(res.get("success"))
        return TestResult(name=name, passed=ok, response=res, details=details), (txh if ok else None)
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e)), None


def pos_create_comment(seed: str, parent_tx: str) -> Tuple[TestResult, Optional[str]]:
    """Create a comment via direct RPC."""
    name = "Create comment"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        pub = wallet.public_key().public_key_bytes
        last = _rpc_get_latest_block_hash()
        diff, min_diff = _rpc_get_current_pow_difficulty()
        ts = _now_ms()
        content = f"RPC comment at {int(time.time())}"
        details = {
            "address": addr,
            "parent_tx": parent_tx,
            "content": content,
            "pow_difficulty": diff,
            "uses_pow": True,
        }
        base = canon_base_post(pub, _lb_bytes(last), diff, ts, parent_tx, "", "", content)
        proof = _compute_pow(base, diff, min_diff, last, max_seconds=15.0)
        signed = canon_signed_with_pow(base, int(proof))
        sig = sign_canonical(wallet, signed)
        msg = MsgPost()
        msg.authority = addr
        msg.envelope_pubkey = pub
        msg.envelope_block_hash = _lb_bytes(last)
        msg.envelope_difficulty = int(diff)
        msg.envelope_pow = int(proof)
        msg.envelope_timestamp = ts
        msg.envelope_signature = sig
        msg.target = parent_tx
        msg.topic = ""
        msg.title = ""
        msg.content = content
        any_msg = AnyPB()
        any_msg.type_url = "/mirage.core.v1.MsgPost"
        any_msg.value = msg.SerializeToString()
        txh, res = _broadcast_with_balance(any_msg, len(content), addr, details)
        ok = bool(res.get("found")) and bool(res.get("success"))
        return TestResult(name=name, passed=ok, response=res, details=details), (txh if ok else None)
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e)), None


def pos_vote(seed: str, target_tx: str, direction: int, label: str) -> TestResult:
    """Vote on a post via direct RPC."""
    name = label
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        pub = wallet.public_key().public_key_bytes
        last = _rpc_get_latest_block_hash()
        diff, min_diff = _rpc_get_current_pow_difficulty()
        ts = _now_ms()
        details = {
            "address": addr,
            "target": target_tx,
            "direction": direction,
            "pow_difficulty": diff,
            "uses_pow": True,
        }
        base = canon_base_vote(pub, _lb_bytes(last), diff, ts, target_tx, int(direction))
        proof = _compute_pow(base, diff, min_diff, last, max_seconds=12.0)
        signed = canon_signed_with_pow(base, int(proof))
        sig = sign_canonical(wallet, signed)
        msg = MsgVote()
        msg.authority = addr
        msg.envelope_pubkey = pub
        msg.envelope_block_hash = _lb_bytes(last)
        msg.envelope_difficulty = int(diff)
        msg.envelope_pow = int(proof)
        msg.envelope_timestamp = ts
        msg.envelope_signature = sig
        msg.target = target_tx
        msg.direction = int(direction)
        any_msg = AnyPB()
        any_msg.type_url = "/mirage.core.v1.MsgVote"
        any_msg.value = msg.SerializeToString()
        txh, res = _broadcast_with_balance(any_msg, len(target_tx), addr, details)
        ok = bool(res.get("found")) and bool(res.get("success"))
        return TestResult(name=name, passed=ok, response=res, details=details)
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


def pos_edit_post(seed: str, override_tx: str) -> TestResult:
    """Edit a post via direct RPC."""
    name = "Edit post"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        pub = wallet.public_key().public_key_bytes
        last = _rpc_get_latest_block_hash()
        diff, min_diff = _rpc_get_current_pow_difficulty()
        ts = _now_ms()
        content = f"RPC edited at {int(time.time())}"
        new_topic = f"topic{_rand_str(4)}"
        details = {
            "address": addr,
            "override": override_tx,
            "new_topic": new_topic,
            "new_content": content,
            "pow_difficulty": diff,
            "uses_pow": True,
        }
        base = canon_base_edit(pub, _lb_bytes(last), diff, ts, "", new_topic, "", content, "", override_tx)
        proof = _compute_pow(base, diff, min_diff, last, max_seconds=15.0)
        signed = canon_signed_with_pow(base, int(proof))
        sig = sign_canonical(wallet, signed)
        msg = MsgEdit()
        msg.authority = addr
        msg.envelope_pubkey = pub
        msg.envelope_block_hash = _lb_bytes(last)
        msg.envelope_difficulty = int(diff)
        msg.envelope_pow = int(proof)
        msg.envelope_timestamp = ts
        msg.envelope_signature = sig
        msg.target = ""
        msg.topic = new_topic
        msg.title = ""
        msg.content = content
        msg.override = override_tx
        any_msg = AnyPB()
        any_msg.type_url = "/mirage.core.v1.MsgEdit"
        any_msg.value = msg.SerializeToString()
        _txh, res = _broadcast_with_balance(any_msg, len(content), addr, details)
        ok = bool(res.get("found")) and bool(res.get("success"))
        return TestResult(name=name, passed=ok, response=res, details=details)
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


def pos_delete_post(seed: str, target_tx: str) -> TestResult:
    """Delete own post via direct RPC."""
    name = "Delete own post"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        pub = wallet.public_key().public_key_bytes
        last = _rpc_get_latest_block_hash()
        diff, min_diff = _rpc_get_current_pow_difficulty()
        ts = _now_ms()
        details = {
            "address": addr,
            "target": target_tx,
            "pow_difficulty": diff,
            "uses_pow": True,
        }
        base = canon_base_delete(pub, _lb_bytes(last), diff, ts, target_tx)
        proof = _compute_pow(base, diff, min_diff, last, max_seconds=15.0)
        signed = canon_signed_with_pow(base, int(proof))
        sig = sign_canonical(wallet, signed)
        msg = MsgDelete()
        msg.authority = addr
        msg.envelope_pubkey = pub
        msg.envelope_block_hash = _lb_bytes(last)
        msg.envelope_difficulty = int(diff)
        msg.envelope_pow = int(proof)
        msg.envelope_timestamp = ts
        msg.envelope_signature = sig
        msg.target = target_tx
        any_msg = AnyPB()
        any_msg.type_url = "/mirage.core.v1.MsgDelete"
        any_msg.value = msg.SerializeToString()
        _txh, res = _broadcast_with_balance(any_msg, len(target_tx), addr, details)
        ok = bool(res.get("found")) and bool(res.get("success"))
        return TestResult(name=name, passed=ok, response=res, details=details)
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


def pos_set_username(seed: str) -> TestResult:
    """Set username via direct RPC."""
    name = "Set username"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        pub = wallet.public_key().public_key_bytes
        last = _rpc_get_latest_block_hash()
        diff, min_diff = _rpc_get_current_pow_difficulty()
        ts = _now_ms()
        username = f"user-{_rand_str(4)}-{_rand_str(4)}"
        details = {
            "address": addr,
            "username": username,
            "pow_difficulty": diff,
            "uses_pow": True,
        }
        base = canon_base_set_username(pub, _lb_bytes(last), diff, ts, addr, username)
        proof = _compute_pow(base, diff, min_diff, last, max_seconds=12.0)
        signed = canon_signed_with_pow(base, int(proof))
        sig = sign_canonical(wallet, signed)
        msg = MsgSetUsername()
        msg.authority = addr
        msg.envelope_pubkey = pub
        msg.envelope_block_hash = _lb_bytes(last)
        msg.envelope_difficulty = int(diff)
        msg.envelope_pow = int(proof)
        msg.envelope_timestamp = ts
        msg.envelope_signature = sig
        msg.target = addr
        msg.username = username
        any_msg = AnyPB()
        any_msg.type_url = "/mirage.core.v1.MsgSetUsername"
        any_msg.value = msg.SerializeToString()
        _txh, res = _broadcast_with_balance(any_msg, len(username), addr, details)
        ok = bool(res.get("found")) and bool(res.get("success"))
        return TestResult(name=name, passed=ok, response=res, details=details)
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


def pos_follow_moderator(seed: str, moderator_addr: str) -> TestResult:
    """Follow moderator via direct RPC."""
    name = "Follow moderator"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        pub = wallet.public_key().public_key_bytes
        last = _rpc_get_latest_block_hash()
        diff, min_diff = _rpc_get_current_pow_difficulty()
        ts = _now_ms()
        details = {
            "address": addr,
            "moderator": moderator_addr,
            "pow_difficulty": diff,
            "uses_pow": True,
        }
        base = canon_base_follow_moderator(pub, _lb_bytes(last), diff, ts, addr, moderator_addr)
        proof = _compute_pow(base, diff, min_diff, last, max_seconds=12.0)
        signed = canon_signed_with_pow(base, int(proof))
        sig = sign_canonical(wallet, signed)
        msg = MsgFollowModerator()
        msg.authority = addr
        msg.envelope_pubkey = pub
        msg.envelope_block_hash = _lb_bytes(last)
        msg.envelope_difficulty = int(diff)
        msg.envelope_pow = int(proof)
        msg.envelope_timestamp = ts
        msg.envelope_signature = sig
        msg.target = addr
        msg.moderator = moderator_addr
        any_msg = AnyPB()
        any_msg.type_url = "/mirage.core.v1.MsgFollowModerator"
        any_msg.value = msg.SerializeToString()
        _txh, res = _broadcast_with_balance(any_msg, len(addr) + len(moderator_addr), addr, details)
        ok = bool(res.get("found")) and bool(res.get("success"))
        return TestResult(name=name, passed=ok, response=res, details=details)
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


def pos_unfollow_moderator(seed: str, moderator_addr: str) -> TestResult:
    """Unfollow moderator via direct RPC."""
    name = "Unfollow moderator"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        pub = wallet.public_key().public_key_bytes
        last = _rpc_get_latest_block_hash()
        diff, min_diff = _rpc_get_current_pow_difficulty()
        ts = _now_ms()
        details = {
            "address": addr,
            "moderator": moderator_addr,
            "pow_difficulty": diff,
            "uses_pow": True,
        }
        base = canon_base_unfollow_moderator(pub, _lb_bytes(last), diff, ts, addr, moderator_addr)
        proof = _compute_pow(base, diff, min_diff, last, max_seconds=12.0)
        signed = canon_signed_with_pow(base, int(proof))
        sig = sign_canonical(wallet, signed)
        msg = MsgUnfollowModerator()
        msg.authority = addr
        msg.envelope_pubkey = pub
        msg.envelope_block_hash = _lb_bytes(last)
        msg.envelope_difficulty = int(diff)
        msg.envelope_pow = int(proof)
        msg.envelope_timestamp = ts
        msg.envelope_signature = sig
        msg.target = addr
        msg.moderator = moderator_addr
        any_msg = AnyPB()
        any_msg.type_url = "/mirage.core.v1.MsgUnfollowModerator"
        any_msg.value = msg.SerializeToString()
        _txh, res = _broadcast_with_balance(any_msg, len(addr) + len(moderator_addr), addr, details)
        ok = bool(res.get("found")) and bool(res.get("success"))
        return TestResult(name=name, passed=ok, response=res, details=details)
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


# ========================================
# NEGATIVE TESTS (Attack scenarios)
# ========================================


def neg_post_oversize_content(seed: str) -> TestResult:
    """Try to post content exceeding tier limit."""
    name = "Post: oversize content rejected"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        pub = wallet.public_key().public_key_bytes
        last = _rpc_get_latest_block_hash()
        diff, min_diff = _rpc_get_current_pow_difficulty()
        ts = _now_ms()
        content = "x" * 1500
        topic = "topicok"
        title = "ok"
        details = {
            "address": addr,
            "topic": topic,
            "title": title,
            "content_len": len(content),
            "pow_difficulty": diff,
            "uses_pow": True,
        }
        base = canon_base_post(pub, _lb_bytes(last), diff, ts, "", topic, title, content)
        proof = _compute_pow(base, diff, min_diff, last, max_seconds=15.0)
        signed = canon_signed_with_pow(base, int(proof))
        sig = sign_canonical(wallet, signed)
        msg = MsgPost()
        msg.authority = addr
        msg.envelope_pubkey = pub
        msg.envelope_block_hash = _lb_bytes(last)
        msg.envelope_difficulty = int(diff)
        msg.envelope_pow = int(proof)
        msg.envelope_timestamp = ts
        msg.envelope_signature = sig
        msg.target = ""
        msg.topic = topic
        msg.title = title
        msg.content = content
        any_msg = AnyPB()
        any_msg.type_url = "/mirage.core.v1.MsgPost"
        any_msg.value = msg.SerializeToString()
        _txh, res = _broadcast_with_balance(any_msg, len(title) + len(content), addr, details)
        ok = bool(res.get("found")) and not bool(res.get("success"))
        return TestResult(name=name, passed=ok, response=res, details=details)
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


def neg_post_missing_topic(seed: str) -> TestResult:
    """Root post without topic should be rejected."""
    name = "Post: missing topic rejected"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        pub = wallet.public_key().public_key_bytes
        last = _rpc_get_latest_block_hash()
        diff, min_diff = _rpc_get_current_pow_difficulty()
        ts = _now_ms()
        title = "title"
        content = "content"
        details = {
            "address": addr,
            "topic": "(empty)",
            "title": title,
            "content": content,
            "pow_difficulty": diff,
            "uses_pow": True,
        }
        base = canon_base_post(pub, _lb_bytes(last), diff, ts, "", "", title, content)
        proof = _compute_pow(base, diff, min_diff, last, max_seconds=10.0)
        signed = canon_signed_with_pow(base, int(proof))
        sig = sign_canonical(wallet, signed)
        msg = MsgPost()
        msg.authority = addr
        msg.envelope_pubkey = pub
        msg.envelope_block_hash = _lb_bytes(last)
        msg.envelope_difficulty = int(diff)
        msg.envelope_pow = int(proof)
        msg.envelope_timestamp = ts
        msg.envelope_signature = sig
        msg.target = ""
        msg.topic = ""
        msg.title = title
        msg.content = content
        any_msg = AnyPB()
        any_msg.type_url = "/mirage.core.v1.MsgPost"
        any_msg.value = msg.SerializeToString()
        _txh, res = _broadcast_with_balance(any_msg, 20, addr, details)
        ok = bool(res.get("found")) and not bool(res.get("success"))
        return TestResult(name=name, passed=ok, response=res, details=details)
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


def neg_post_oversize_title(seed: str) -> TestResult:
    """Try to post title exceeding limit."""
    name = "Post: oversize title rejected"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        pub = wallet.public_key().public_key_bytes
        last = _rpc_get_latest_block_hash()
        diff, min_diff = _rpc_get_current_pow_difficulty()
        ts = _now_ms()
        # Title limit ~100-150 chars
        title = "t" * 200
        content = "ok"
        topic = "topicok"
        details = {
            "address": addr,
            "topic": topic,
            "title_len": len(title),
            "pow_difficulty": diff,
            "uses_pow": True,
        }
        base = canon_base_post(pub, _lb_bytes(last), diff, ts, "", topic, title, content)
        proof = _compute_pow(base, diff, min_diff, last, max_seconds=12.0)
        signed = canon_signed_with_pow(base, int(proof))
        sig = sign_canonical(wallet, signed)
        msg = MsgPost()
        msg.authority = addr
        msg.envelope_pubkey = pub
        msg.envelope_block_hash = _lb_bytes(last)
        msg.envelope_difficulty = int(diff)
        msg.envelope_pow = int(proof)
        msg.envelope_timestamp = ts
        msg.envelope_signature = sig
        msg.target = ""
        msg.topic = topic
        msg.title = title
        msg.content = content
        any_msg = AnyPB()
        any_msg.type_url = "/mirage.core.v1.MsgPost"
        any_msg.value = msg.SerializeToString()
        _txh, res = _broadcast_with_balance(any_msg, len(title) + len(content), addr, details)
        ok = bool(res.get("found")) and not bool(res.get("success"))
        return TestResult(name=name, passed=ok, response=res, details=details)
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


def neg_post_topic_invalid(seed: str, topic: str, label: str) -> TestResult:
    """Helper: root post with invalid topic format should be rejected."""
    name = f"Post: invalid topic ({label}) rejected"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        pub = wallet.public_key().public_key_bytes
        last = _rpc_get_latest_block_hash()
        diff, min_diff = _rpc_get_current_pow_difficulty()
        ts = _now_ms()
        title = "t"
        content = "c"
        details = {"address": addr, "topic": topic, "title": title, "content": content, "uses_pow": True}
        base = canon_base_post(pub, _lb_bytes(last), diff, ts, "", topic, title, content)
        proof = _compute_pow(base, diff, min_diff, last, max_seconds=10.0)
        signed = canon_signed_with_pow(base, int(proof))
        sig = sign_canonical(wallet, signed)
        msg = MsgPost()
        msg.authority = addr
        msg.envelope_pubkey = pub
        msg.envelope_block_hash = _lb_bytes(last)
        msg.envelope_difficulty = int(diff)
        msg.envelope_pow = int(proof)
        msg.envelope_timestamp = ts
        msg.envelope_signature = sig
        msg.target = ""
        msg.topic = topic
        msg.title = title
        msg.content = content
        any_msg = AnyPB()
        any_msg.type_url = "/mirage.core.v1.MsgPost"
        any_msg.value = msg.SerializeToString()
        _txh, res = _broadcast_with_balance(any_msg, len(title) + len(content), addr, details)
        ok = bool(res.get("found")) and not bool(res.get("success"))
        return TestResult(name=name, passed=ok, response=res, details=details)
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


def neg_comment_invalid_target(seed: str) -> TestResult:
    """Try to comment on invalid target hash."""
    name = "Comment: invalid target rejected"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        pub = wallet.public_key().public_key_bytes
        last = _rpc_get_latest_block_hash()
        diff, min_diff = _rpc_get_current_pow_difficulty()
        ts = _now_ms()
        invalid_target = "not-a-valid-hash"
        content = "hello"
        details = {"address": addr, "target": invalid_target, "content": content, "uses_pow": True}
        base = canon_base_post(pub, _lb_bytes(last), diff, ts, invalid_target, "", "", content)
        proof = _compute_pow(base, diff, min_diff, last, max_seconds=10.0)
        signed = canon_signed_with_pow(base, int(proof))
        sig = sign_canonical(wallet, signed)
        msg = MsgPost()
        msg.authority = addr
        msg.envelope_pubkey = pub
        msg.envelope_block_hash = _lb_bytes(last)
        msg.envelope_difficulty = int(diff)
        msg.envelope_pow = int(proof)
        msg.envelope_timestamp = ts
        msg.envelope_signature = sig
        msg.target = invalid_target
        msg.topic = ""
        msg.title = ""
        msg.content = content
        any_msg = AnyPB()
        any_msg.type_url = "/mirage.core.v1.MsgPost"
        any_msg.value = msg.SerializeToString()
        _txh, res = _broadcast_with_balance(any_msg, len(content), addr, details)
        ok = bool(res.get("found")) and not bool(res.get("success"))
        return TestResult(name=name, passed=ok, response=res, details=details)
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


def neg_comment_missing_content(seed: str, parent_tx: str) -> TestResult:
    """Comment without content should be rejected."""
    name = "Comment: missing content rejected"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        pub = wallet.public_key().public_key_bytes
        last = _rpc_get_latest_block_hash()
        diff, min_diff = _rpc_get_current_pow_difficulty()
        ts = _now_ms()
        content = ""
        details = {"address": addr, "parent": parent_tx, "content_len": len(content), "uses_pow": True}
        base = canon_base_post(pub, _lb_bytes(last), diff, ts, parent_tx, "", "", content)
        proof = _compute_pow(base, diff, min_diff, last, max_seconds=10.0)
        signed = canon_signed_with_pow(base, int(proof))
        sig = sign_canonical(wallet, signed)
        msg = MsgPost()
        msg.authority = addr
        msg.envelope_pubkey = pub
        msg.envelope_block_hash = _lb_bytes(last)
        msg.envelope_difficulty = int(diff)
        msg.envelope_pow = int(proof)
        msg.envelope_timestamp = ts
        msg.envelope_signature = sig
        msg.target = parent_tx
        msg.topic = ""
        msg.title = ""
        msg.content = content
        any_msg = AnyPB()
        any_msg.type_url = "/mirage.core.v1.MsgPost"
        any_msg.value = msg.SerializeToString()
        _txh, res = _broadcast_with_balance(any_msg, 0, addr, details)
        ok = bool(res.get("found")) and not bool(res.get("success"))
        return TestResult(name=name, passed=ok, response=res, details=details)
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


def neg_comment_with_topic(seed: str, parent_tx: str) -> TestResult:
    """Comment that incorrectly includes a topic should be rejected."""
    name = "Comment: topic provided rejected"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        pub = wallet.public_key().public_key_bytes
        last = _rpc_get_latest_block_hash()
        diff, min_diff = _rpc_get_current_pow_difficulty()
        ts = _now_ms()
        content = "c"
        details = {"address": addr, "parent": parent_tx, "topic": "wrong", "uses_pow": True}
        base = canon_base_post(pub, _lb_bytes(last), diff, ts, parent_tx, "wrong", "", content)
        proof = _compute_pow(base, diff, min_diff, last, max_seconds=10.0)
        signed = canon_signed_with_pow(base, int(proof))
        sig = sign_canonical(wallet, signed)
        msg = MsgPost()
        msg.authority = addr
        msg.envelope_pubkey = pub
        msg.envelope_block_hash = _lb_bytes(last)
        msg.envelope_difficulty = int(diff)
        msg.envelope_pow = int(proof)
        msg.envelope_timestamp = ts
        msg.envelope_signature = sig
        msg.target = parent_tx
        msg.topic = "wrong"
        msg.title = ""
        msg.content = content
        any_msg = AnyPB()
        any_msg.type_url = "/mirage.core.v1.MsgPost"
        any_msg.value = msg.SerializeToString()
        _txh, res = _broadcast_with_balance(any_msg, len(content), addr, details)
        ok = bool(res.get("found")) and not bool(res.get("success"))
        return TestResult(name=name, passed=ok, response=res, details=details)
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


def neg_invalid_pubkey_length(seed: str) -> TestResult:
    """Try to relay with invalid pubkey length."""
    name = "Relay: invalid pubkey rejected"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        pub = wallet.public_key().public_key_bytes
        bad_pub = pub[:20]
        last = _rpc_get_latest_block_hash()
        diff, min_diff = _rpc_get_current_pow_difficulty()
        ts = _now_ms()
        base = canon_base_post(pub, _lb_bytes(last), diff, ts, "", "topicok", "ok", "content")
        details = {"address": addr, "pubkey_len": len(bad_pub), "uses_pow": True}
        proof = _compute_pow(base, diff, min_diff, last, max_seconds=10.0)
        signed = canon_signed_with_pow(base, int(proof))
        sig = sign_canonical(wallet, signed)
        msg = MsgPost()
        msg.authority = addr
        msg.envelope_pubkey = bad_pub
        msg.envelope_block_hash = _lb_bytes(last)
        msg.envelope_difficulty = int(diff)
        msg.envelope_pow = int(proof)
        msg.envelope_timestamp = ts
        msg.envelope_signature = sig
        msg.target = ""
        msg.topic = "topicok"
        msg.title = "ok"
        msg.content = "content"
        any_msg = AnyPB()
        any_msg.type_url = "/mirage.core.v1.MsgPost"
        any_msg.value = msg.SerializeToString()
        _txh, res = _broadcast_with_balance(any_msg, 20, addr, details)
        ok = bool(res.get("found")) and not bool(res.get("success"))
        return TestResult(name=name, passed=ok, response=res, details=details)
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


def neg_invalid_last_block_hash(seed: str) -> TestResult:
    """Try to post with invalid last_block_hash format."""
    name = "PoW: invalid last_block_hash rejected"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        pub = wallet.public_key().public_key_bytes
        last = _rpc_get_latest_block_hash()
        diff, min_diff = _rpc_get_current_pow_difficulty()
        ts = _now_ms()
        bad_hash = "not-a-valid-hex-hash"
        base = canon_base_post(pub, _lb_bytes(last), diff, ts, "", "topicok", "ok", "content")
        details = {"address": addr, "bad_hash": bad_hash, "uses_pow": True}
        proof = _compute_pow(base, diff, min_diff, last, max_seconds=10.0)
        signed = canon_signed_with_pow(base, int(proof))
        sig = sign_canonical(wallet, signed)
        msg = MsgPost()
        msg.authority = addr
        msg.envelope_pubkey = pub
        msg.envelope_block_hash = bad_hash.encode("utf-8")
        msg.envelope_difficulty = int(diff)
        msg.envelope_pow = int(proof)
        msg.envelope_timestamp = ts
        msg.envelope_signature = sig
        msg.target = ""
        msg.topic = "topicok"
        msg.title = "ok"
        msg.content = "content"
        any_msg = AnyPB()
        any_msg.type_url = "/mirage.core.v1.MsgPost"
        any_msg.value = msg.SerializeToString()
        _txh, res = _broadcast_with_balance(any_msg, 20, addr, details)
        ok = bool(res.get("found")) and not bool(res.get("success"))
        return TestResult(name=name, passed=ok, response=res, details=details)
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


# ========================================
# SUBSCRIBER TESTS (NO PoW)
# ========================================
def sub_pos_post_no_pow(seed: str) -> Tuple[TestResult, Optional[str]]:
    """Subscriber creates a post without PoW."""
    name = "Subscriber: create post without PoW"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        pub = wallet.public_key().public_key_bytes
        last = _rpc_get_latest_block_hash()
        ts = _now_ms()
        topic = f"topic{_rand_str(4)}"
        title = "okay"
        content = f"sub content at {int(time.time())}"
        details = {"address": addr, "topic": topic, "title": title, "content": content, "uses_pow": False}
        base = canon_base_post(pub, _lb_bytes(last), 0, ts, "", topic, title, content)
        signed = canon_signed_with_pow(base, 0)
        sig = sign_canonical(wallet, signed)
        msg = MsgPost()
        msg.authority = addr
        msg.envelope_pubkey = pub
        msg.envelope_block_hash = _lb_bytes(last)
        msg.envelope_difficulty = 0
        msg.envelope_pow = 0
        msg.envelope_timestamp = ts
        msg.envelope_signature = sig
        msg.target = ""
        msg.topic = topic
        msg.title = title
        msg.content = content
        any_msg = AnyPB()
        any_msg.type_url = "/mirage.core.v1.MsgPost"
        any_msg.value = msg.SerializeToString()
        txh, res = _broadcast_with_balance(any_msg, len(title) + len(content), addr, details)
        ok = bool(res.get("found")) and bool(res.get("success"))
        return TestResult(name=name, passed=ok, response=res, details=details), (txh if ok else None)
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e)), None


def sub_pos_vote_no_pow(seed: str, target_tx: str, direction: int, label: str) -> TestResult:
    """Subscriber votes without PoW."""
    name = f"Subscriber: {label}"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        pub = wallet.public_key().public_key_bytes
        last = _rpc_get_latest_block_hash()
        ts = _now_ms()
        details = {"address": addr, "target": target_tx, "direction": int(direction), "uses_pow": False}
        base = canon_base_vote(pub, _lb_bytes(last), 0, ts, target_tx, int(direction))
        signed = canon_signed_with_pow(base, 0)
        sig = sign_canonical(wallet, signed)
        msg = MsgVote()
        msg.authority = addr
        msg.envelope_pubkey = pub
        msg.envelope_block_hash = _lb_bytes(last)
        msg.envelope_difficulty = 0
        msg.envelope_pow = 0
        msg.envelope_timestamp = ts
        msg.envelope_signature = sig
        msg.target = target_tx
        msg.direction = int(direction)
        any_msg = AnyPB()
        any_msg.type_url = "/mirage.core.v1.MsgVote"
        any_msg.value = msg.SerializeToString()
        _txh, res = _broadcast_with_balance(any_msg, len(target_tx), addr, details)
        ok = bool(res.get("found")) and bool(res.get("success"))
        return TestResult(name=name, passed=ok, response=res, details=details)
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


# ========================================
# TOKENS / UPGRADE HELPERS AND TESTS
# ========================================
def rpc_send_tokens(seed_from: str, to_addr: str, amount: int) -> TestResult:
    """Send tokens via MsgSendTokens (PoW)."""
    name = f"Send tokens: {amount} to {to_addr[:10]}..."
    try:
        wallet = create_wallet_from_seed(seed_from)
        sender = str(wallet.address())
        pub = wallet.public_key().public_key_bytes
        last = _rpc_get_latest_block_hash()
        diff, min_diff = _rpc_get_current_pow_difficulty()
        ts = _now_ms()
        details = {"sender": sender, "target": to_addr, "amount": amount, "uses_pow": True}
        base = canon_base_send_tokens(pub, _lb_bytes(last), diff, ts, sender, to_addr, int(amount))
        proof = _compute_pow(base, diff, min_diff, last, max_seconds=10.0)
        signed = canon_signed_with_pow(base, int(proof))
        sig = sign_canonical(wallet, signed)
        msg = MsgSendTokens()
        msg.authority = sender
        msg.envelope_pubkey = pub
        msg.envelope_block_hash = _lb_bytes(last)
        msg.envelope_difficulty = int(diff)
        msg.envelope_pow = int(proof)
        msg.envelope_timestamp = ts
        msg.envelope_signature = sig
        msg.sender = sender
        msg.target = to_addr
        msg.amount = int(amount)
        any_msg = AnyPB()
        any_msg.type_url = "/mirage.core.v1.MsgSendTokens"
        any_msg.value = msg.SerializeToString()
        _txh, res = _broadcast_with_balance(any_msg, len(sender) + len(to_addr), sender, details)
        ok = bool(res.get("found")) and bool(res.get("success"))
        return TestResult(name=name, passed=ok, response=res, details=details)
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


def rpc_upgrade_level(seed: str, level: int) -> TestResult:
    """Upgrade subscription level via MsgUpgradeLevel (no PoW)."""
    name = f"Upgrade to level {level}"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        pub = wallet.public_key().public_key_bytes
        last = _rpc_get_latest_block_hash()
        # Use wall-clock ms for envelope_timestamp (no PoW for upgrade_level)
        ts_ms = int(time.time() * 1000)
        details = {"address": addr, "level": int(level), "uses_pow": False}
        base = canon_base_upgrade_level(pub, bytes.fromhex(last), 0, ts_ms, int(level))
        signed = canon_signed_with_pow(base, 0)
        sig = sign_canonical(wallet, signed)
        msg = MsgUpgradeLevel()
        msg.authority = addr
        msg.envelope_pubkey = pub
        msg.envelope_block_hash = bytes.fromhex(last)
        msg.envelope_difficulty = 0
        msg.envelope_pow = 0
        msg.envelope_timestamp = ts_ms
        msg.envelope_signature = sig
        msg.level = int(level)
        any_msg = AnyPB()
        any_msg.type_url = "/mirage.core.v1.MsgUpgradeLevel"
        any_msg.value = msg.SerializeToString()
        _txh, res = _broadcast_with_balance(any_msg, 1, addr, details)
        ok = bool(res.get("found")) and bool(res.get("success"))
        return TestResult(name=name, passed=ok, response=res, details=details)
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


def neg_invalid_signature(seed: str) -> TestResult:
    """Try to relay with tampered signature."""
    name = "Relay: invalid signature rejected"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        pub = wallet.public_key().public_key_bytes
        last = _rpc_get_latest_block_hash()
        diff, min_diff = _rpc_get_current_pow_difficulty()
        ts = _now_ms()
        topic = "topicok"
        title = "ok"
        content = "content"
        details = {
            "address": addr,
            "topic": topic,
            "title": title,
            "content": content,
            "signature_tampered": True,
            "uses_pow": True,
        }
        base = canon_base_post(pub, _lb_bytes(last), diff, ts, "", topic, title, content)
        proof = _compute_pow(base, diff, min_diff, last, max_seconds=15.0)
        signed = canon_signed_with_pow(base, int(proof))
        sig = bytearray(sign_canonical(wallet, signed))
        sig[0] ^= 0xFF
        msg = MsgPost()
        msg.authority = addr
        msg.envelope_pubkey = pub
        msg.envelope_block_hash = _lb_bytes(last)
        msg.envelope_difficulty = int(diff)
        msg.envelope_pow = int(proof)
        msg.envelope_signature = bytes(sig)
        msg.target = ""
        msg.topic = topic
        msg.title = title
        msg.content = content
        any_msg = AnyPB()
        any_msg.type_url = "/mirage.core.v1.MsgPost"
        any_msg.value = msg.SerializeToString()
        _txh, res = _broadcast_with_balance(any_msg, 20, addr, details)
        ok = bool(res.get("found")) and not bool(res.get("success"))
        return TestResult(name=name, passed=ok, response=res, details=details)
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


def neg_insufficient_pow(seed: str) -> TestResult:
    """Try to post with insufficient PoW difficulty."""
    name = "PoW: insufficient difficulty rejected"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        pub = wallet.public_key().public_key_bytes
        last = _rpc_get_latest_block_hash()
        diff, min_diff = _rpc_get_current_pow_difficulty()
        ts = _now_ms()
        low_diff = max(1, diff - 5)
        topic = "topicok"
        title = "ok"
        content = "content"
        details = {
            "address": addr,
            "topic": topic,
            "title": title,
            "content": content,
            "declared_diff": low_diff,
            "required_diff": diff,
            "uses_pow": True,
        }
        base = canon_base_post(pub, _lb_bytes(last), low_diff, ts, "", topic, title, content)
        proof = _compute_pow(base, low_diff, min_diff, last, max_seconds=10.0)
        signed = canon_signed_with_pow(base, int(proof))
        sig = sign_canonical(wallet, signed)
        msg = MsgPost()
        msg.authority = addr
        msg.envelope_pubkey = pub
        msg.envelope_block_hash = _lb_bytes(last)
        msg.envelope_difficulty = int(low_diff)
        msg.envelope_pow = int(proof)
        msg.envelope_timestamp = ts
        msg.envelope_signature = sig
        msg.target = ""
        msg.topic = topic
        msg.title = title
        msg.content = content
        any_msg = AnyPB()
        any_msg.type_url = "/mirage.core.v1.MsgPost"
        any_msg.value = msg.SerializeToString()
        _txh, res = _broadcast_with_balance(any_msg, 20, addr, details)
        ok = bool(res.get("found")) and not bool(res.get("success"))
        return TestResult(name=name, passed=ok, response=res, details=details)
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


def neg_vote_invalid_target(seed: str) -> TestResult:
    """Try to vote on invalid target."""
    name = "Vote: invalid target rejected"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        pub = wallet.public_key().public_key_bytes
        last = _rpc_get_latest_block_hash()
        diff, min_diff = _rpc_get_current_pow_difficulty()
        ts = _now_ms()
        invalid_target = "short"
        direction = 1
        details = {
            "address": addr,
            "target": invalid_target,
            "direction": direction,
            "pow_difficulty": diff,
            "uses_pow": True,
        }
        base = canon_base_vote(pub, _lb_bytes(last), diff, ts, invalid_target, direction)
        proof = _compute_pow(base, diff, min_diff, last, max_seconds=12.0)
        signed = canon_signed_with_pow(base, int(proof))
        sig = sign_canonical(wallet, signed)
        msg = MsgVote()
        msg.authority = addr
        msg.envelope_pubkey = pub
        msg.envelope_block_hash = _lb_bytes(last)
        msg.envelope_difficulty = int(diff)
        msg.envelope_pow = int(proof)
        msg.envelope_timestamp = ts
        msg.envelope_signature = sig
        msg.target = invalid_target
        msg.direction = direction
        any_msg = AnyPB()
        any_msg.type_url = "/mirage.core.v1.MsgVote"
        any_msg.value = msg.SerializeToString()
        _txh, res = _broadcast_with_balance(any_msg, len(invalid_target), addr, details)
        ok = bool(res.get("found")) and not bool(res.get("success"))
        return TestResult(name=name, passed=ok, response=res, details=details)
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


def neg_delete_not_owner(seed: str, foreign_post_tx: str) -> TestResult:
    """Try to delete someone else's post."""
    name = "Delete: not owner rejected"
    try:
        wallet = create_wallet_from_seed(seed)
        addr = str(wallet.address())
        pub = wallet.public_key().public_key_bytes
        last = _rpc_get_latest_block_hash()
        diff, min_diff = _rpc_get_current_pow_difficulty()
        ts = _now_ms()
        details = {
            "address": addr,
            "target": foreign_post_tx,
            "pow_difficulty": diff,
            "uses_pow": True,
        }
        base = canon_base_delete(pub, _lb_bytes(last), diff, ts, foreign_post_tx)
        proof = _compute_pow(base, diff, min_diff, last, max_seconds=15.0)
        signed = canon_signed_with_pow(base, int(proof))
        sig = sign_canonical(wallet, signed)
        msg = MsgDelete()
        msg.authority = addr
        msg.envelope_pubkey = pub
        msg.envelope_block_hash = _lb_bytes(last)
        msg.envelope_difficulty = int(diff)
        msg.envelope_pow = int(proof)
        msg.envelope_timestamp = ts
        msg.envelope_signature = sig
        msg.target = foreign_post_tx
        any_msg = AnyPB()
        any_msg.type_url = "/mirage.core.v1.MsgDelete"
        any_msg.value = msg.SerializeToString()
        _txh, res = _broadcast_with_balance(any_msg, len(foreign_post_tx), addr, details)
        ok = bool(res.get("found")) and not bool(res.get("success"))
        return TestResult(name=name, passed=ok, response=res, details=details)
    except Exception as e:
        return TestResult(name=name, passed=False, error=str(e))


def main() -> int:
    parser = argparse.ArgumentParser(description="Mirage RPC Attack Tests - Direct chain interaction")
    parser.add_argument("--rpc", default=DEFAULT_RPC, help="Tendermint RPC URL (default: http://127.0.0.1:26657)")
    parser.add_argument("--seed-free", required=True, help="Mnemonic seed for free user wallet")
    parser.add_argument("--seed-subscriber", required=True, help="Mnemonic seed for subscriber wallet")
    args = parser.parse_args()

    global RPC_URL
    RPC_URL = str(args.rpc).rstrip("/")

    free_seed = args.seed_free
    sub_seed = args.seed_subscriber

    try:
        w_free = create_wallet_from_seed(free_seed)
        w_sub = create_wallet_from_seed(sub_seed)
        print(f"RPC: {RPC_URL}")
        print(f"Free wallet: {w_free.address()}")
        print(f"Subscriber wallet: {w_sub.address()}")
    except Exception as e:
        print(f"Failed to create wallets: {e}")
        return 2

    results = []

    # POSITIVE TESTS
    # Note: Positive tests require a funded account. The subscriber wallet has funds.
    # For direct RPC, the user pays their own fees (unlike backend where validator pays).
    funded_seed = sub_seed  # Use subscriber seed which has funds

    print("\n" + "=" * 60)
    print("POSITIVE TESTS (RPC)")
    print("=" * 60)

    r_post, post_tx = pos_create_post(funded_seed)
    results.append(r_post)
    _print_result(r_post)

    if post_tx:
        r = pos_vote(funded_seed, post_tx, 0, "Clear vote")
        results.append(r)
        _print_result(r)

        r = pos_vote(funded_seed, post_tx, -1, "Downvote post")
        results.append(r)
        _print_result(r)

        r = pos_vote(funded_seed, post_tx, 1, "Upvote post")
        results.append(r)
        _print_result(r)

        r_c, comment_tx = pos_create_comment(funded_seed, post_tx)
        results.append(r_c)
        _print_result(r_c)

        time.sleep(2)
        r = pos_edit_post(funded_seed, post_tx)
        results.append(r)
        _print_result(r)

        time.sleep(2)
        r = pos_delete_post(funded_seed, post_tx)
        results.append(r)
        _print_result(r)

    r = pos_set_username(funded_seed)
    results.append(r)
    _print_result(r)

    addr_funded = str(w_sub.address())
    r = pos_follow_moderator(funded_seed, addr_funded)
    results.append(r)
    _print_result(r)

    r = pos_unfollow_moderator(funded_seed, addr_funded)
    results.append(r)
    _print_result(r)

    # NEGATIVE TESTS
    # These tests should be rejected by the chain, so we use the funded seed
    print("\n" + "=" * 60)
    print("NEGATIVE TESTS (RPC)")
    print("=" * 60)

    r = neg_post_oversize_content(funded_seed)
    results.append(r)
    _print_result(r)

    r = neg_post_oversize_title(funded_seed)
    results.append(r)
    _print_result(r)

    r = neg_post_missing_topic(funded_seed)
    results.append(r)
    _print_result(r)

    # Topic invalid format variants
    for topic_val, label in [
        ("topic-bad", "hyphen"),
        ("TopicUpper", "uppercase"),
        ("topic bad", "space"),
        ("topic_bad", "underscore"),
        ("to", "too short"),
    ]:
        r = neg_post_topic_invalid(funded_seed, topic_val, label)
        results.append(r)
        _print_result(r)

    r = neg_comment_invalid_target(funded_seed)
    results.append(r)
    _print_result(r)

    if post_tx:
        r = neg_comment_missing_content(funded_seed, post_tx)
        results.append(r)
        _print_result(r)
        r = neg_comment_with_topic(funded_seed, post_tx)
        results.append(r)
        _print_result(r)

    r = neg_invalid_pubkey_length(funded_seed)
    results.append(r)
    _print_result(r)

    r = neg_invalid_last_block_hash(funded_seed)
    results.append(r)
    _print_result(r)

    r = neg_invalid_signature(funded_seed)
    results.append(r)
    _print_result(r)

    r = neg_insufficient_pow(funded_seed)
    results.append(r)
    _print_result(r)

    r = neg_vote_invalid_target(funded_seed)
    results.append(r)
    _print_result(r)

    # Create a post by the funded user, then try to delete with a different seed
    # For cross-user deletion test, we need two different users
    # Since free_seed has no funds, we'll create a post and try to delete with free_seed
    # But free_seed can't pay fees, so this test will fail for "insufficient funds" not "not owner"
    # For now, skip this test or mark it as expected behavior
    print("  (Skipping cross-user deletion test - requires two funded accounts)")
    # r_other, other_post_tx = pos_create_post(funded_seed)
    # if other_post_tx:
    #     r = neg_delete_not_owner(free_seed, other_post_tx)  # This would fail for insufficient funds
    #     results.append(r)
    #     _print_result(r)

    # SUMMARY
    print("\n" + "=" * 60)
    passed = sum(1 for r in results if r.passed)
    failed = [r for r in results if not r.passed]
    print(f"PASSED: {passed}/{len(results)}")
    if failed:
        print(f"FAILED: {len(failed)}")
        for r in failed:
            print(f"  - {r.name}")
    print("=" * 60)

    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
