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
import re as _re
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
from net_tag import request_memo
from shared.client import der_to_compact_sig

_log = _logging.getLogger("tx")
_TX_SIZE_COST_PER_BYTE: Optional[int] = None

# Unordered-tx TTL (~2 minutes). SDK default max is 10 minutes.
_UNORDERED_TTL_NS = 120 * 1_000_000_000
# Ante overhead after C-1: sig verify + unordered nonce (~2240) + existing ante.
_ANTE_GAS = 20_000
_TX_HASH_RE = _re.compile(r"[0-9A-F]{64}")
# A payout's search window is the unordered TTL; this bounds it in blocks so a
# bad cursor can never turn reconciliation into an unbounded scan.
_MAX_SCAN_BLOCKS = 500


def estimate_total_gas_limit(
    body_bytes: bytes,
    content_len: int,
    *,
    include_request_memo: bool = True,
) -> int:
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
        signed_body = _prepare_signed_body(
            body_bytes,
            _unique_timeout_ns(),
            include_request_memo=include_request_memo,
        )
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


def build_tx_bytes(body_bytes: bytes, gas_limit: int, *, zero_fee: bool = False) -> bytes:
    """Build a signed unordered relay TxRaw. Gas payer = validator (must have signed)."""
    rt = require_runtime()
    tx_bytes, _timeout_ns = build_signed_tx(
        body_bytes,
        gas_limit,
        privkey_bytes=rt.validator_privkey_bytes,
        pubkey_bytes=rt.validator_pubkey_bytes,
        account_number=int(rt.validator_account_number),
        fee_payer=rt.validator_payer_addr,
        zero_fee=zero_fee,
    )
    return tx_bytes


def build_signed_tx(
    body_bytes: bytes,
    gas_limit: int,
    *,
    privkey_bytes: bytes,
    pubkey_bytes: bytes,
    account_number: int,
    fee_payer: str = "",
    include_request_memo: bool = True,
    zero_fee: bool = False,
) -> Tuple[bytes, int]:
    """Sign an unordered tx with an explicit signer.

    Returns (tx_bytes, timeout_ns). The timeout is what makes a rebroadcast of
    the identical bytes safe: past it the tx can never be included, so a payout
    that is still not on chain after the timeout is definitively dead.
    """
    if int(gas_limit) <= 0:
        raise RuntimeError("gas_limit must be > 0")
    if not privkey_bytes or not pubkey_bytes:
        raise RuntimeError("build_signed_tx requires a signer key pair")
    rt = require_runtime()
    min_gas_price = min_gas_price_umirage()
    fee_amt = 0 if zero_fee else int(_math.ceil(int(gas_limit) * min_gas_price))
    fee = Fee(gas_limit=int(gas_limit))
    if fee_amt > 0:
        fee.amount.extend([Coin(denom="umirage", amount=str(fee_amt))])
    if fee_payer:
        fee.payer = fee_payer

    pub_any = AnyPB()
    pub_any.Pack(_secp_pubkey(pubkey_bytes))
    pub_any.type_url = "/cosmos.crypto.secp256k1.PubKey"
    mode = ModeInfo(single=ModeInfo.Single(mode=SignMode.SIGN_MODE_DIRECT))
    # Unordered txs require sequence=0.
    si = SignerInfo(public_key=pub_any, mode_info=mode, sequence=0)
    auth = AuthInfo(signer_infos=[si], fee=fee)
    auth_bytes = auth.SerializeToString()

    timeout_ns = _unique_timeout_ns()
    signed_body = _prepare_signed_body(
        body_bytes,
        timeout_ns,
        include_request_memo=include_request_memo,
    )

    sign_doc = SignDoc(
        body_bytes=signed_body,
        auth_info_bytes=auth_bytes,
        chain_id=rt.chain_id,
        account_number=int(account_number),
    )
    sig = _sign_sign_doc(privkey_bytes, sign_doc.SerializeToString())

    _log.info(
        "build_tx gas_limit=%d fee_amt=%d timeout_ns=%d chain_id=%s account_number=%d sig_len=%d",
        gas_limit,
        fee_amt,
        timeout_ns,
        rt.chain_id,
        int(account_number),
        len(sig),
    )
    tx_bytes = TxRaw(body_bytes=signed_body, auth_info_bytes=auth_bytes, signatures=[sig]).SerializeToString()
    return tx_bytes, timeout_ns


def bank_send_body_bytes(from_address: str, to_address: str, amount: int) -> bytes:
    """Serialize a TxBody carrying a single cosmos bank MsgSend of umirage."""
    from cosmpy.protos.cosmos.bank.v1beta1.tx_pb2 import MsgSend
    from cosmpy.protos.cosmos.tx.v1beta1.tx_pb2 import TxBody

    if int(amount) <= 0:
        raise RuntimeError("bank send amount must be > 0")
    msg = MsgSend(from_address=from_address, to_address=to_address)
    msg.amount.extend([Coin(denom="umirage", amount=str(int(amount)))])
    any_msg = AnyPB()
    any_msg.Pack(msg)
    any_msg.type_url = "/cosmos.bank.v1beta1.MsgSend"
    return TxBody(messages=[any_msg], memo="").SerializeToString()


def chain_head() -> Tuple[int, float]:
    """Latest committed height and its block time (unix seconds)."""
    body = _rpc_get("/status", {})
    sync = ((body.get("result") or {}).get("sync_info")) or {}
    height = int(sync.get("latest_block_height") or 0)
    if height <= 0:
        raise RuntimeError(f"chain_head missing height: {str(body)[:200]}")
    return height, _parse_block_time(str(sync.get("latest_block_time") or ""))


def resolve_tx_by_scan(tx_hash: str, scan_from: int, timeout_at: int) -> Tuple[str, Optional[int], int]:
    """Find an unordered tx by scanning the blocks it could appear in.

    Transaction indexing is off on every Mirage node, so a hash lookup is not
    available. An unordered tx can only be included in a block whose time is at
    or before its timeout, which makes the search window finite.

    Returns (verdict, code, scanned_to) where verdict is:
    - "found": the tx is in a block; code is its DeliverTx result
    - "expired": every block up to the timeout is scanned and it is not there
    - "pending": the window is still open
    """
    digest = str(tx_hash or "").strip().upper()
    if not _TX_HASH_RE.fullmatch(digest):
        raise RuntimeError(f"resolve_tx_by_scan invalid hash: {tx_hash!r}")
    if int(scan_from) <= 0:
        raise RuntimeError(f"resolve_tx_by_scan invalid scan_from: {scan_from}")

    head, _head_time = chain_head()
    scanned_to = int(scan_from) - 1
    for height in range(int(scan_from), head + 1):
        if height - int(scan_from) >= _MAX_SCAN_BLOCKS:
            return "pending", None, scanned_to
        block_time, txs = _fetch_block(height)
        for index, raw in enumerate(txs):
            try:
                tx_bytes = _b64.b64decode(raw, validate=True)
            except Exception as exc:
                raise RuntimeError(f"block {height} tx {index} is not valid base64") from exc
            if _hashlib.sha256(tx_bytes).hexdigest().upper() == digest:
                return "found", _tx_result_code(height, index), height
        scanned_to = height
        if block_time > float(timeout_at):
            return "expired", None, scanned_to
    return "pending", None, scanned_to


def _fetch_block(height: int) -> Tuple[float, list]:
    body = _rpc_get("/block", {"height": str(int(height))})
    block = ((body.get("result") or {}).get("block")) or {}
    header = block.get("header") or {}
    data = block.get("data") or {}
    txs = data.get("txs") or []
    if not isinstance(txs, list) or any(not isinstance(tx, str) for tx in txs):
        raise RuntimeError(f"block {height} has malformed txs")
    return _parse_block_time(str(header.get("time") or "")), txs


def _tx_result_code(height: int, index: int) -> int:
    body = _rpc_get("/block_results", {"height": str(int(height))})
    results = ((body.get("result") or {}).get("txs_results")) or []
    if index >= len(results):
        raise RuntimeError(f"block_results {height} has no tx at index {index}")
    result = results[index]
    if not isinstance(result, dict) or "code" not in result:
        raise RuntimeError(f"block_results {height} tx {index} has no explicit code")
    code = result["code"]
    if not isinstance(code, int) or isinstance(code, bool):
        raise RuntimeError(f"block_results {height} tx {index} code is not an integer: {code!r}")
    return code


def _rpc_get(path: str, params: dict) -> dict:
    url = f"{require_runtime().rpc_url}{path}"
    try:
        resp = _requests.get(url, params=params, timeout=10)
    except Exception as e:
        raise RuntimeError(f"rpc {path} connection failed: {e}")
    if resp.status_code != 200:
        raise RuntimeError(f"rpc {path} http {resp.status_code}: {resp.text[:300]}")
    try:
        body = resp.json()
    except Exception as e:
        raise RuntimeError(f"rpc {path} invalid json: {e}")
    if body.get("error"):
        raise RuntimeError(f"rpc {path} error: {str(body['error'])[:300]}")
    return body


def _parse_block_time(value: str) -> float:
    """Parse a CometBFT RFC3339 timestamp (nanosecond precision) to unix seconds."""
    raw = str(value or "").strip()
    if not raw:
        raise RuntimeError("block time missing")
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    if "." in raw:
        head, rest = raw.split(".", 1)
        frac, _, tail = rest.partition("+")
        raw = f"{head}.{frac[:6]}+{tail}" if tail else f"{head}.{frac[:6]}"
    from datetime import datetime, timezone

    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise RuntimeError(f"invalid block time: {value!r}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


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


def build_and_broadcast_tx(body_bytes: bytes, gas_limit: int, *, zero_fee: bool = False) -> Tuple[str, int, int, str]:
    """Sign a relay tx and broadcast; rebuild once on unordered-nonce collision."""
    last: Tuple[str, int, int, str] = ("", 1, 0, "build_and_broadcast_tx: no attempt")
    for attempt in range(2):
        tx_bytes = build_tx_bytes(body_bytes, gas_limit, zero_fee=zero_fee)
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
    expected_hash = _hashlib.sha256(tx_bytes).hexdigest().lower()
    api_url = require_runtime().api_url
    url = f"{api_url}/cosmos/tx/v1beta1/txs"

    _log.info("broadcast_tx %s len=%d %s", expected_hash, len(tx_bytes), _extract_auth_hex(tx_bytes))

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
    tx_resp = body.get("tx_response")
    if not isinstance(tx_resp, dict):
        raise RuntimeError(f"broadcast_tx missing tx_response: {str(body)[:300]}")
    if "code" not in tx_resp:
        raise RuntimeError(f"broadcast_tx missing explicit code: {str(body)[:300]}")
    code = tx_resp["code"]
    if not isinstance(code, int) or isinstance(code, bool):
        raise RuntimeError(f"broadcast_tx code is not an integer: {code!r}")
    raw_log = str(tx_resp.get("raw_log", "") or "")
    height = int(tx_resp.get("height", 0) or 0)
    response_hash = str(tx_resp.get("txhash", "") or "").strip().lower()
    if not _TX_HASH_RE.fullmatch(response_hash.upper()):
        raise RuntimeError(f"broadcast_tx missing or invalid txhash: {response_hash!r}")
    if response_hash != expected_hash:
        raise RuntimeError(f"broadcast_tx hash mismatch expected={expected_hash} got={response_hash}")
    _log.info("broadcast %s code=%d resp=%s", response_hash, code, str(body)[:500])
    return response_hash, code, height, raw_log


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


def _append_memo(body_bytes: bytes, memo: str) -> bytes:
    """Append TxBody field 2 (memo) as raw wire bytes.

    Same technique as _append_unordered_timeout. Every body builder uses
    memo="" and proto3 omits empty strings, so field 2 is absent from body_bytes
    and appending cannot duplicate it.
    """
    if not memo:
        return body_bytes
    raw = memo.encode("ascii")
    # field 2, wire type 2 (length-delimited)
    return body_bytes + b"\x12" + _encode_varint(len(raw)) + raw


def _prepare_signed_body(
    body_bytes: bytes,
    timeout_ns: int,
    *,
    include_request_memo: bool = True,
) -> bytes:
    """Body as it will be signed: messages, then memo, then unordered/timeout.

    The single place the relay's network tag enters a transaction. The gas
    estimator's size probe and the real signing path both go through here and
    both take the memo from the same per-request cache, so the memo cannot be
    charged for but missing, or present but uncharged. The bodies are not byte
    equal — each build draws a fresh timeout — but the memo contributes the same
    bytes to every one of them, which is the part the size accounting depends
    on. Field order stays canonical at 1, 2, 4, 5.
    """
    memo = request_memo() if include_request_memo else ""
    return _append_unordered_timeout(_append_memo(body_bytes, memo), timeout_ns)


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


def _secp_pubkey(pubkey_bytes: Optional[bytes] = None):
    from cosmpy.protos.cosmos.crypto.secp256k1.keys_pb2 import PubKey as SecpPubKey

    return SecpPubKey(key=pubkey_bytes if pubkey_bytes is not None else require_runtime().validator_pubkey_bytes)


__all__ = [
    "estimate_total_gas_limit",
    "build_tx_bytes",
    "build_signed_tx",
    "bank_send_body_bytes",
    "build_and_broadcast_tx",
    "simulate_gas",
    "broadcast_tx",
    "chain_head",
    "resolve_tx_by_scan",
    "load_tx_size_cost_per_byte",
]
