from __future__ import annotations

"""Transaction helpers: gas estimation, building, and direct broadcasting.

Functions:
- estimate_total_gas_limit(body_bytes, content_len): Heuristic gas estimator.
- build_tx_bytes(body_bytes, gas_limit): Construct TxRaw bytes with payer.
- simulate_gas(tx_bytes): Simulate via REST; returns gas_used.
- broadcast_tx(tx_bytes): Broadcast via REST; returns (tx_hash, code, height, raw_log).
"""

from typing import Tuple, Optional
import base64 as _b64
import hashlib as _hashlib
import logging as _logging
import math as _math
import requests as _requests

from google.protobuf.any_pb2 import Any as AnyPB
from cosmpy.protos.cosmos.tx.v1beta1.tx_pb2 import TxBody, AuthInfo, Fee, TxRaw, SignerInfo, ModeInfo
from cosmpy.protos.cosmos.tx.signing.v1beta1.signing_pb2 import SignMode
from cosmpy.protos.cosmos.base.v1beta1.coin_pb2 import Coin

from node import min_gas_price_umirage, require_runtime
from db import connect_db

_log = _logging.getLogger("tx")
_TX_SIZE_COST_PER_BYTE: Optional[int] = None


def estimate_total_gas_limit(body_bytes: bytes, content_len: int, extra_gas: int = 0) -> int:
    """Heuristic gas estimator.

    extra_gas: additional gas for handlers that do more KV work than a single
    write (e.g. MsgSetUsername does claim+release+profile update → extra ~2000).
    """
    # Fixed ante overhead: account lookup, balance read/write, nonce read/write,
    # difficulty read, auth-params read, etc.  ~11-12k empirically.
    ante_gas = 12_000
    tx_size_ppb = _get_tx_size_cost_per_byte()
    min_gas_price = min_gas_price_umirage()

    def _txraw_len(gas_lim: int) -> int:
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
        tx_raw = TxRaw(body_bytes=body_bytes, auth_info_bytes=auth.SerializeToString(), signatures=[b"\x00"])
        return len(tx_raw.SerializeToString())

    gas_guess = max(ante_gas, 1)
    for _ in range(3):
        size_gas = tx_size_ppb * _txraw_len(int(gas_guess))
        msg_gas = 1000 + 2000 + (30 * max(0, int(content_len))) + int(extra_gas)
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
    if int(gas_limit) <= 0:
        raise RuntimeError("gas_limit must be > 0")
    min_gas_price = min_gas_price_umirage()
    fee_amt = int(_math.ceil(int(gas_limit) * min_gas_price))
    fee = Fee(gas_limit=int(gas_limit))
    fee.amount.extend([Coin(denom="umirage", amount=str(fee_amt))])
    fee.payer = require_runtime().validator_payer_addr

    pub_any = AnyPB()
    pub_any.Pack(_secp_pubkey())
    pub_any.type_url = "/cosmos.crypto.secp256k1.PubKey"
    mode = ModeInfo(single=ModeInfo.Single(mode=SignMode.SIGN_MODE_DIRECT))
    si = SignerInfo(public_key=pub_any, mode_info=mode, sequence=0)
    auth = AuthInfo(signer_infos=[si], fee=fee)
    auth_bytes = auth.SerializeToString()
    fee_bytes = fee.SerializeToString()
    _log.info(
        "build_tx gas_limit=%d fee_amt=%d fee_hex=%s auth_hex=%s",
        gas_limit,
        fee_amt,
        fee_bytes.hex(),
        auth_bytes.hex(),
    )
    return TxRaw(body_bytes=body_bytes, auth_info_bytes=auth_bytes, signatures=[b"\x00"]).SerializeToString()


def simulate_gas(tx_bytes: bytes) -> int:
    """Simulate gas via REST (tx service). Returns gas_used."""
    rt = require_runtime()
    url = f"{rt.api_url}/cosmos/tx/v1beta1/simulate"
    payload = {"tx_bytes": _b64.b64encode(tx_bytes).decode()}
    try:
        resp = _requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
    except Exception as e:
        raise RuntimeError(f"simulate_gas failed: {e}")
    try:
        body = resp.json()
    except Exception as e:
        raise RuntimeError(f"simulate_gas invalid json: {e}")
    gas_info = body.get("gas_info") or {}
    gas_used = gas_info.get("gas_used") or gas_info.get("gas_wanted")
    if gas_used is None or str(gas_used).strip() == "":
        raise RuntimeError(f"simulate_gas missing gas_used: {str(body)[:200]}")
    try:
        return int(gas_used)
    except Exception as e:
        raise RuntimeError(f"simulate_gas invalid gas_used: {gas_used} ({e})")


def broadcast_tx(tx_bytes: bytes) -> Tuple[str, int, int, str]:
    """Broadcast transaction via REST (tx service).

    Returns (tx_hash, code, height, raw_log).
    """
    tx_hash = _hashlib.sha256(tx_bytes).hexdigest().lower()
    api_url = require_runtime().api_url
    url = f"{api_url}/cosmos/tx/v1beta1/txs"

    _log.info("broadcast_tx %s len=%d %s", tx_hash, len(tx_bytes), _extract_auth_hex(tx_bytes))

    try:
        payload = {
            "tx_bytes": _b64.b64encode(tx_bytes).decode(),
            "mode": "BROADCAST_MODE_SYNC",
        }
        resp = _requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        body = resp.json()
        tx_resp = body.get("tx_response") or {}
        code = int(tx_resp.get("code", 0) or 0)
        raw_log = str(tx_resp.get("raw_log", "") or "")
        height = int(tx_resp.get("height", 0) or 0)
        resp_hash = str(tx_resp.get("txhash", "") or "").strip().lower()
        if resp_hash:
            tx_hash = resp_hash
        _log.info("broadcast %s code=%d resp=%s", tx_hash, code, str(body)[:500])
        return tx_hash, code, height, raw_log
    except Exception as e:
        _log.error("broadcast %s failed: %s", tx_hash, e)
        return tx_hash, 1, 0, str(e)


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
    "simulate_gas",
    "broadcast_tx",
    "load_tx_size_cost_per_byte",
]
