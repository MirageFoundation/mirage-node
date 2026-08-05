from __future__ import annotations

"""Transaction helpers: gas estimation, building, and direct broadcasting.

C-1: outer Cosmos txs are unordered and signed with the validator key so the
gas payer proves consent. The Cosmos Fee field is the gas payment.
"""

from typing import Tuple, Optional
import base64 as _b64
import hashlib as _hashlib
import logging as _logging
import math as _math
import os as _os
import random as _random
import time as _time
import requests as _requests

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from google.protobuf.any_pb2 import Any as AnyPB
from google.protobuf.timestamp_pb2 import Timestamp
from cosmpy.protos.cosmos.tx.v1beta1.tx_pb2 import AuthInfo, Fee, TxRaw, SignerInfo, ModeInfo, SignDoc
from cosmpy.protos.cosmos.tx.signing.v1beta1.signing_pb2 import SignMode
from cosmpy.protos.cosmos.base.v1beta1.coin_pb2 import Coin

from node import min_gas_price_umirage, require_runtime
from db import connect_db
from shared.client import der_to_compact_sig

_log = _logging.getLogger("tx")
_TX_SIZE_COST_PER_BYTE: Optional[int] = None

# Unordered-tx TTL (~2 minutes). SDK default max is 10 minutes.
_UNORDERED_TTL_NS = 120 * 1_000_000_000
# Ante overhead after C-1: sig verify + unordered nonce (~2240) + existing ante.
_ANTE_GAS = 20_000


def estimate_total_gas_limit(body_bytes: bytes, content_len: int) -> int:
    """Heuristic gas estimator (uniform across message types)."""
    ante_gas = _ANTE_GAS
    tx_size_ppb = _get_tx_size_cost_per_byte()
    min_gas_price = min_gas_price_umirage()

    def _txraw_len(gas_lim: int) -> int:
        # Size estimate only — use a 64-byte placeholder signature matching real txs.
        fee_amt = int(_math.ceil(gas_lim * min_gas_price))
        fee = Fee(gas_limit=int(gas_lim))
        fee.amount.extend([Coin(denom="umirage", amount=str(fee_amt))])
        fee.payer = require_runtime().validator_payer_addr
        pub_any = AnyPB()
        pub_any.Pack(_secp_pubkey())
        pub_any.type_url = "/cosmos.crypto.secp256k1.PubKey"
        mode = ModeInfo(single=ModeInfo.Single(mode=SignMode.SIGN_MODE_DIRECT))
        si = SignerInfo(public_key=pub_any, mode_info=mode, sequence=0)
        auth = AuthInfo(signer_infos=[si], fee=fee)
        signed_body = _append_unordered_timeout(body_bytes, _unique_timeout_ns())
        tx_raw = TxRaw(
            body_bytes=signed_body,
            auth_info_bytes=auth.SerializeToString(),
            signatures=[b"\x00" * 64],
        )
        return len(tx_raw.SerializeToString())

    gas_guess = max(ante_gas, 1)
    for _ in range(3):
        size_gas = tx_size_ppb * _txraw_len(int(gas_guess))
        msg_gas = 1000 + 2000 + (30 * max(0, int(content_len)))
        raw = ante_gas + size_gas + msg_gas
        new_gas = int(_math.ceil(raw * 1.10))  # 10% safety margin
        if new_gas % 64 != 0:
            new_gas = ((new_gas + 63) // 64) * 64
        if abs(new_gas - gas_guess) <= 1:
            gas_guess = new_gas
            break
        gas_guess = new_gas
    return int(gas_guess)


def build_tx_bytes(body_bytes: bytes, gas_limit: int) -> bytes:
    """Build a signed unordered relay TxRaw. Gas payer = validator (must have signed)."""
    if int(gas_limit) <= 0:
        raise RuntimeError("gas_limit must be > 0")
    rt = require_runtime()
    min_gas_price = min_gas_price_umirage()
    fee_amt = int(_math.ceil(int(gas_limit) * min_gas_price))
    fee = Fee(gas_limit=int(gas_limit))
    fee.amount.extend([Coin(denom="umirage", amount=str(fee_amt))])
    fee.payer = rt.validator_payer_addr

    pub_any = AnyPB()
    pub_any.Pack(_secp_pubkey())
    pub_any.type_url = "/cosmos.crypto.secp256k1.PubKey"
    mode = ModeInfo(single=ModeInfo.Single(mode=SignMode.SIGN_MODE_DIRECT))
    # Unordered txs require sequence=0.
    si = SignerInfo(public_key=pub_any, mode_info=mode, sequence=0)
    auth = AuthInfo(signer_infos=[si], fee=fee)
    auth_bytes = auth.SerializeToString()

    timeout_ns = _unique_timeout_ns()
    signed_body = _append_unordered_timeout(body_bytes, timeout_ns)

    sign_doc = SignDoc(
        body_bytes=signed_body,
        auth_info_bytes=auth_bytes,
        chain_id=rt.chain_id,
        account_number=int(rt.validator_account_number),
    )
    sig = _sign_sign_doc(rt.validator_privkey_bytes, sign_doc.SerializeToString())

    _log.info(
        "build_tx gas_limit=%d fee_amt=%d timeout_ns=%d chain_id=%s account_number=%d sig_len=%d",
        gas_limit,
        fee_amt,
        timeout_ns,
        rt.chain_id,
        rt.validator_account_number,
        len(sig),
    )
    return TxRaw(body_bytes=signed_body, auth_info_bytes=auth_bytes, signatures=[sig]).SerializeToString()


def simulate_gas(tx_bytes: bytes) -> int:
    """Simulate gas via REST (tx service).

    Returns gas_used on success. Any HTTP error is treated as a hard failure.
    """
    rt = require_runtime()
    url = f"{rt.api_url}/cosmos/tx/v1beta1/simulate"
    payload = {"tx_bytes": _b64.b64encode(tx_bytes).decode()}
    try:
        resp = _requests.post(url, json=payload, timeout=10)
    except Exception as e:
        raise RuntimeError(f"simulate_gas connection failed: {e}")
    if resp.status_code != 200:
        raise RuntimeError(f"simulate_gas http {resp.status_code}: {resp.text[:500]}")
    try:
        body = resp.json()
    except Exception as e:
        raise RuntimeError(f"simulate_gas invalid json: {e}")
    gas_info = body.get("gas_info") or {}
    gas_used = gas_info.get("gas_used") or gas_info.get("gas_wanted")
    if gas_used is None or str(gas_used).strip() == "":
        raise RuntimeError(f"simulate_gas missing gas_used: {str(body)[:200]}")
    return int(gas_used)


def build_and_broadcast_tx(body_bytes: bytes, gas_limit: int) -> Tuple[str, int, int, str]:
    """Sign a relay tx and broadcast; rebuild once on unordered-nonce collision."""
    last: Tuple[str, int, int, str] = ("", 1, 0, "build_and_broadcast_tx: no attempt")
    for attempt in range(2):
        tx_bytes = build_tx_bytes(body_bytes, gas_limit)
        last = _broadcast_once(tx_bytes)
        tx_hash, code, height, raw_log = last
        if code == 0:
            return last
        if "already used timeout" not in raw_log.lower():
            return last
        _log.warning(
            "unordered nonce collision on broadcast (attempt %d); rebuilding tx: %s",
            attempt + 1,
            raw_log[:200],
        )
    return last


def broadcast_tx(tx_bytes: bytes) -> Tuple[str, int, int, str]:
    """Broadcast an already-built TxRaw via REST.

    Prefer build_and_broadcast_tx for relay txs so unordered-nonce collisions
    can be retried with a fresh timeout_timestamp.
    """
    return _broadcast_once(tx_bytes)


def _broadcast_once(tx_bytes: bytes) -> Tuple[str, int, int, str]:
    tx_hash = _hashlib.sha256(tx_bytes).hexdigest().lower()
    api_url = require_runtime().api_url
    url = f"{api_url}/cosmos/tx/v1beta1/txs"

    _log.info("broadcast_tx %s len=%d %s", tx_hash, len(tx_bytes), _extract_auth_hex(tx_bytes))

    payload = {
        "tx_bytes": _b64.b64encode(tx_bytes).decode(),
        "mode": "BROADCAST_MODE_SYNC",
    }
    try:
        resp = _requests.post(url, json=payload, timeout=10)
    except Exception as e:
        raise RuntimeError(f"broadcast_tx connection failed: {e}")
    if resp.status_code != 200:
        raise RuntimeError(f"broadcast_tx http {resp.status_code}: {resp.text[:500]}")
    try:
        body = resp.json()
    except Exception as e:
        raise RuntimeError(f"broadcast_tx invalid json: {e}")
    tx_resp = body.get("tx_response") or {}
    code = int(tx_resp.get("code", 0) or 0)
    raw_log = str(tx_resp.get("raw_log", "") or "")
    height = int(tx_resp.get("height", 0) or 0)
    resp_hash = str(tx_resp.get("txhash", "") or "").strip().lower()
    if resp_hash:
        tx_hash = resp_hash
    _log.info("broadcast %s code=%d resp=%s", tx_hash, code, str(body)[:500])
    return tx_hash, code, height, raw_log


def _unique_timeout_ns() -> int:
    """Return a unique Unix-nano timeout within the unordered TTL window."""
    now = _time.time_ns()
    # Mix pid + random so gunicorn workers don't collide on the same ns.
    cand = now + _UNORDERED_TTL_NS + ((_os.getpid() & 0xFFFF) << 16) + _random.getrandbits(16)
    max_ns = now + 9 * 60 * 1_000_000_000  # stay under SDK DefaultMaxTimeoutDuration (10m)
    if cand > max_ns:
        cand = max_ns - _random.getrandbits(20)
    if cand <= now:
        cand = now + _UNORDERED_TTL_NS + _random.getrandbits(20)
    return int(cand)


def _encode_varint(n: int) -> bytes:
    if n < 0:
        raise ValueError("varint must be non-negative")
    out = bytearray()
    while n > 0x7F:
        out.append((n & 0x7F) | 0x80)
        n >>= 7
    out.append(n & 0x7F)
    return bytes(out)


def _append_unordered_timeout(body_bytes: bytes, timeout_ns: int) -> bytes:
    """Append TxBody fields 4 (unordered=true) and 5 (timeout_timestamp).

    cosmpy's TxBody proto is older and lacks these fields; we append wire bytes.
    """
    # field 4, wire type 0 (varint), value 1 (true)
    unordered = b"\x20\x01"
    ts = Timestamp()
    ts.seconds = timeout_ns // 1_000_000_000
    ts.nanos = int(timeout_ns % 1_000_000_000)
    ts_bytes = ts.SerializeToString()
    # field 5, wire type 2 (length-delimited)
    timeout = b"\x2a" + _encode_varint(len(ts_bytes)) + ts_bytes
    return body_bytes + unordered + timeout


def _sign_sign_doc(privkey_bytes: bytes, sign_doc_bytes: bytes) -> bytes:
    priv_key_int = int.from_bytes(privkey_bytes, "big")
    priv_key = ec.derive_private_key(priv_key_int, ec.SECP256K1(), default_backend())
    sig_der = priv_key.sign(sign_doc_bytes, ec.ECDSA(hashes.SHA256()))
    sig = der_to_compact_sig(sig_der)
    if len(sig) != 64:
        raise RuntimeError(f"outer signature must be 64 bytes, got {len(sig)}")
    return sig


def _extract_auth_hex(tx_bytes: bytes) -> str:
    """Extract auth_info_bytes hex from TxRaw for diagnostic logging."""
    try:
        raw = TxRaw()
        raw.ParseFromString(tx_bytes)
        auth = AuthInfo()
        auth.ParseFromString(raw.auth_info_bytes)
        return f"gas={auth.fee.gas_limit} fee_hex={raw.auth_info_bytes.hex()[:120]}"
    except Exception as e:
        return f"parse_err={e}"


def _get_tx_size_cost_per_byte() -> int:
    """Return cached tx_size_cost_per_byte loaded at startup."""
    if _TX_SIZE_COST_PER_BYTE is None:
        raise RuntimeError("tx_size_cost_per_byte not loaded - call load_tx_size_cost_per_byte at startup")
    return _TX_SIZE_COST_PER_BYTE


def load_tx_size_cost_per_byte() -> int:
    """Load tx_size_cost_per_byte once at startup from chain_stats."""
    global _TX_SIZE_COST_PER_BYTE
    if _TX_SIZE_COST_PER_BYTE is not None:
        return _TX_SIZE_COST_PER_BYTE
    with connect_db(timeout=3.0, busy_timeout_ms=5000) as conn:
        cur = conn.cursor()
        cur.execute("SELECT value FROM chain_stats WHERE key = 'tx_size_cost_per_byte'")
        row = cur.fetchone()
        if row and row[0] is not None:
            v = int(row[0])
            if v > 0:
                _TX_SIZE_COST_PER_BYTE = v
                return v
    raise RuntimeError("tx_size_cost_per_byte missing in indexer DB")


def _secp_pubkey():
    from cosmpy.protos.cosmos.crypto.secp256k1.keys_pb2 import PubKey as SecpPubKey

    return SecpPubKey(key=require_runtime().validator_pubkey_bytes)


__all__ = [
    "estimate_total_gas_limit",
    "build_tx_bytes",
    "build_and_broadcast_tx",
    "simulate_gas",
    "broadcast_tx",
    "load_tx_size_cost_per_byte",
]
