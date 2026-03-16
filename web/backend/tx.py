from __future__ import annotations

"""Transaction helpers: gas estimation, building, and DB-queued broadcasting.

Functions:
- estimate_total_gas_limit(body_bytes, content_len): Heuristic gas estimator.
- build_tx_bytes(body_bytes, gas_limit): Construct TxRaw bytes with payer.
- simulate_gas(tx_bytes): Returns 0 (simulation handled by indexer if needed).
- broadcast_tx(tx_bytes): Insert into pending_txs DB queue; returns (tx_hash, code, height, raw_log).
"""

from typing import Tuple, Optional
import hashlib as _hashlib
import math as _math
import time as _time

from google.protobuf.any_pb2 import Any as AnyPB
from cosmpy.protos.cosmos.tx.v1beta1.tx_pb2 import TxBody, AuthInfo, Fee, TxRaw, SignerInfo, ModeInfo
from cosmpy.protos.cosmos.tx.signing.v1beta1.signing_pb2 import SignMode
from cosmpy.protos.cosmos.base.v1beta1.coin_pb2 import Coin

from node import min_gas_price_umirage, require_runtime
from db import connect_db

_TX_SIZE_COST_PER_BYTE: Optional[int] = None


def estimate_total_gas_limit(body_bytes: bytes, content_len: int) -> int:
    base_required = 0
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

    gas_guess = max(base_required, 1)
    for _ in range(2):
        size_gas = tx_size_ppb * _txraw_len(int(gas_guess))
        store_gas = 1000 + 2000 + (30 * max(0, int(content_len)))
        new_gas = base_required + size_gas + store_gas + 1024
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
    return TxRaw(
        body_bytes=body_bytes, auth_info_bytes=auth.SerializeToString(), signatures=[b"\x00"]
    ).SerializeToString()


def simulate_gas(tx_bytes: bytes) -> int:
    """Skip simulation — gas is estimated heuristically. Indexer may re-simulate."""
    return 0


def broadcast_tx(tx_bytes: bytes) -> Tuple[str, int, int, str]:
    """Insert transaction into pending_txs DB queue for indexer to broadcast.

    The tx_hash is computed deterministically from the transaction bytes.
    """
    tx_hash = _hashlib.sha256(tx_bytes).hexdigest().lower()
    try:
        with connect_db(timeout=5.0, busy_timeout_ms=10000) as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO pending_txs(tx_bytes, tx_hash, status, created_at)
                VALUES(%s, %s, 'pending', %s)
                """,
                (tx_bytes, tx_hash, int(_time.time())),
            )
        return tx_hash, 0, 0, ""
    except Exception as e:
        return tx_hash, 1, 0, str(e)


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
