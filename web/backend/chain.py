from __future__ import annotations

"""Chain query helpers — reads from indexer DB (no gRPC/RPC).

Functions:
- get_difficulty_info(): Difficulty state from chain_stats DB.
- get_latest_block_hash(): Latest block hash from recent_blocks DB.
- get_current_pow_difficulty(): Current dynamic PoW difficulty.
- get_recent_block_hashes(): Recent block hashes for validation.
- is_valid_recent_block_hash(): Check if hash is in recent window.
- get_block_time_seconds(): Read consensus timeout_commit from config.
- max_envelope_future_skew_seconds(): Ante handler's future-timestamp allowance.
- is_node_catching_up(): True if the node/indexer pair is too far behind to relay.
- classify_reject(raw_log): Parse common reject reasons from logs.
"""

import json
import re
import time
from typing import Any, Dict, Optional

from db import connect_db
from error_utils import IndexerUnavailable
from logging_utils import logger
from params import expect_params


_DIFFICULTY_CACHE: Optional[Dict[str, Any]] = None
_DIFFICULTY_CACHE_TIME: float = 0.0
_DIFFICULTY_CACHE_TTL: float = 5.0

# Written together by the indexer from one GetDifficulty response; a subset means
# the row is mid-write or stale, not that the missing values are zero.
_REQUIRED_DIFFICULTY_KEYS = ("current_difficulty", "previous_difficulty", "last_change_height", "current_height")


def get_difficulty_info(timeout: float = 3.0, *, force: bool = False) -> Dict[str, Any]:
    """Get difficulty state from indexer DB chain_stats.

    The indexer writes every field of difficulty_info in one shot from the chain's
    GetDifficulty query (indexer/chain_client.py:323), so a missing or partial row
    means the indexer has not populated it — not that difficulty is zero. Raising
    keeps a PoW precheck from being computed against a difficulty nobody asserted.
    """
    global _DIFFICULTY_CACHE, _DIFFICULTY_CACHE_TIME

    now = time.monotonic()
    if not force and _DIFFICULTY_CACHE is not None and (now - _DIFFICULTY_CACHE_TIME) < _DIFFICULTY_CACHE_TTL:
        return _DIFFICULTY_CACHE

    with connect_db(timeout=3.0, busy_timeout_ms=5000) as conn:
        cur = conn.cursor()

        cur.execute("SELECT value FROM chain_stats WHERE key = 'difficulty_info'")
        diff_row = cur.fetchone()
        if not diff_row or not isinstance(diff_row[0], dict):
            raise IndexerUnavailable("chain_stats.difficulty_info missing from indexer DB")
        info: Dict[str, Any] = dict(diff_row[0])

        missing = [k for k in _REQUIRED_DIFFICULTY_KEYS if k not in info]
        if missing:
            raise IndexerUnavailable(f"chain_stats.difficulty_info incomplete, missing {missing}")

        # Latest block hash from recent_blocks
        cur.execute("SELECT height, hash FROM recent_blocks ORDER BY height DESC LIMIT 1")
        brow = cur.fetchone()
        if brow:
            info["latest_block_hash"] = str(brow[1]) if brow[1] else ""
            if brow[0] and int(brow[0]) > int(info.get("current_height", 0) or 0):
                info["current_height"] = int(brow[0])

    _DIFFICULTY_CACHE = info
    _DIFFICULTY_CACHE_TIME = now
    return info


def get_latest_block_hash(timeout_s: int = 5) -> str:
    """Get latest block hash from indexer DB."""
    with connect_db(timeout=3.0, busy_timeout_ms=5000) as conn:
        cur = conn.cursor()
        cur.execute("SELECT hash FROM recent_blocks ORDER BY height DESC LIMIT 1")
        row = cur.fetchone()
        if row and row[0]:
            raw = str(row[0]).strip()
            if raw and re.fullmatch(r"[0-9A-Fa-f]{64}", raw):
                return raw
    raise RuntimeError("no recent block hash available in indexer DB")


def get_current_pow_difficulty() -> int:
    info = get_difficulty_info()
    return int(info["current_difficulty"])


def get_pow_base_bits() -> int:
    from params import expect_params

    # Legacy key name preserved by indexer/params.py alias injection.
    return int(expect_params()["pow_base_bits"])


def get_pow_factor() -> float:
    from params import expect_params

    # Legacy key name preserved by indexer/params.py alias injection.
    return float(expect_params()["pow_factor"])


_RECENT_BLOCK_HASHES: list[str] = []
_RECENT_HASHES_TIME: float = 0.0
_RECENT_HASHES_TTL: float = 3.0


def _get_block_hash_window() -> int:
    from params import expect_params

    return int(expect_params()["block_hash_window"])


def get_recent_block_hashes(timeout_s: int = 5) -> list[str]:
    """Get recent block hashes from indexer DB."""
    global _RECENT_BLOCK_HASHES, _RECENT_HASHES_TIME

    now = time.monotonic()
    if _RECENT_BLOCK_HASHES and (now - _RECENT_HASHES_TIME) < _RECENT_HASHES_TTL:
        return _RECENT_BLOCK_HASHES

    window = _get_block_hash_window()
    with connect_db(timeout=3.0, busy_timeout_ms=5000) as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT hash FROM recent_blocks ORDER BY height DESC LIMIT %s",
            (window,),
        )
        hashes = [str(r[0]).strip().upper() for r in cur.fetchall() if r[0]]

    if not hashes:
        raise RuntimeError("no recent block hashes in indexer DB")

    _RECENT_BLOCK_HASHES = hashes
    _RECENT_HASHES_TIME = now
    return _RECENT_BLOCK_HASHES


def is_valid_recent_block_hash(block_hash: str, timeout_s: int = 5) -> bool:
    if not block_hash or not re.fullmatch(r"[0-9A-Fa-f]{64}", block_hash):
        return False
    upper = block_hash.upper()
    recent = get_recent_block_hashes(timeout_s)
    if upper in recent:
        return True
    # Cache may be stale — force refresh and retry once
    global _RECENT_BLOCK_HASHES, _RECENT_HASHES_TIME
    _RECENT_HASHES_TIME = 0.0
    recent = get_recent_block_hashes(timeout_s)
    return upper in recent


_BLOCK_TIME_CACHE: Optional[int] = None


def get_block_time_seconds() -> int:
    global _BLOCK_TIME_CACHE
    if _BLOCK_TIME_CACHE is not None:
        return _BLOCK_TIME_CACHE

    from shared.config import get_config

    cfg = get_config()
    raw = cfg.get("consensus", "timeout_commit")
    if raw is None or str(raw).strip() == "":
        raise RuntimeError("timeout_commit missing in config (consensus.timeout_commit)")
    val = str(raw).strip().lower()
    if val.endswith("ms"):
        num = float(val[:-2])
        if num <= 0:
            raise RuntimeError("timeout_commit must be > 0")
        _BLOCK_TIME_CACHE = max(1, int(round(num / 1000.0)))
        return _BLOCK_TIME_CACHE
    if val.endswith("s"):
        num = float(val[:-1])
        if num <= 0:
            raise RuntimeError("timeout_commit must be > 0")
        _BLOCK_TIME_CACHE = max(1, int(round(num)))
        return _BLOCK_TIME_CACHE
    raise RuntimeError("timeout_commit must include units (e.g., '5s' or '500ms')")


_CATCHING_UP_CACHE: Optional[bool] = None
_CATCHING_UP_CACHE_TIME: float = 0.0
_CATCHING_UP_CACHE_TTL: float = 5.0


def max_envelope_future_skew_seconds() -> int:
    """How far ahead of block time the chain accepts an envelope timestamp.

    Mirrors validateEnvelopeTimestamp in blockchain/app/ante_metasig.go: half of
    max_envelope_age, clamped to [5s, 30s]. Keep the two in step — a relay that
    accepts a wider window just forwards txs the ante handler will reject.
    """
    max_age = int(expect_params()["max_envelope_age"])
    return min(max(max_age // 2, 5), 30)


def is_node_catching_up(timeout_s: int = 2) -> bool:
    """Check if the node/indexer pair is too far behind to relay writes.

    Returns True if:
    - Last processed time is >30s ago (time-based lag), OR
    - Indexer is >10 blocks behind chain head (height-based lag), OR
    - The newest committed block is older than the ante handler's future-skew
      allowance (the node trails the network), OR
    - The indexer has not processed anything yet

    Raises IndexerUnavailable if the DB cannot be read. An outage is not sync lag:
    reporting it as lag told clients to retry against a node that had no data at
    all, and hid the outage from every caller (M-6).
    """
    global _CATCHING_UP_CACHE, _CATCHING_UP_CACHE_TIME

    now = time.monotonic()
    if _CATCHING_UP_CACHE is not None and (now - _CATCHING_UP_CACHE_TIME) < _CATCHING_UP_CACHE_TTL:
        return _CATCHING_UP_CACHE

    try:
        with connect_db(timeout=3.0, busy_timeout_ms=5000) as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT key, value FROM indexer_state WHERE key IN ('last_processed_time', 'last_processed_height', 'chain_head_height')"
            )
            state = {r[0]: r[1] for r in cur.fetchall()}
            cur.execute("SELECT MAX(block_time) FROM recent_blocks")
            row = cur.fetchone()
            head_block_time = int((row[0] if row else 0) or 0)
    except Exception as e:
        raise IndexerUnavailable(f"indexer_state unreadable: {e}") from e

    last_ts = int(state.get("last_processed_time", 0) or 0)
    last_height = int(state.get("last_processed_height", 0) or 0)
    chain_head = int(state.get("chain_head_height", 0) or 0)

    if not last_ts:
        result = True
    else:
        time_lag = int(time.time()) - last_ts > 30
        height_lag = chain_head > 0 and (chain_head - last_height) > 10
        # A node trailing the network keeps committing blocks and reports
        # catching_up=False, so neither check above fires — but simulate runs
        # against that stale block time, and every relayed write past this window
        # is rejected as "envelope_timestamp in future" (val1 fell 21 blocks
        # behind during a disk stall on 2026-08-06 and dropped six posts).
        # block_time is 0 only for rows written before the column existed.
        head_stale = False
        if head_block_time:
            head_stale_s = int(time.time()) - head_block_time
            skew_limit_s = max_envelope_future_skew_seconds()
            head_stale = head_stale_s > skew_limit_s
            if head_stale:
                logger().warning(
                    "node_catching_up: newest block is %ds old (limit %ds), height=%d — node trails the network",
                    head_stale_s,
                    skew_limit_s,
                    last_height,
                )
        result = time_lag or height_lag or head_stale

    _CATCHING_UP_CACHE = result
    _CATCHING_UP_CACHE_TIME = now
    return result


def get_indexer_health() -> Dict[str, Any]:
    """Return indexer health metrics for monitoring.

    Raises IndexerUnavailable rather than returning {"error": ..., "catching_up":
    True}: a monitor that cannot reach the DB must see a failure, not a node that
    merely looks like it is syncing (M-6).
    """
    try:
        with connect_db(timeout=3.0, busy_timeout_ms=5000) as conn:
            cur = conn.cursor()
            cur.execute("SELECT key, value, updated_at FROM indexer_state")
            rows = {r[0]: {"value": r[1], "updated_at": r[2]} for r in cur.fetchall()}
    except Exception as e:
        raise IndexerUnavailable(f"indexer_state unreadable: {e}") from e

    return {
        "last_processed_height": int(rows.get("last_processed_height", {}).get("value", 0) or 0),
        "last_processed_time": int(rows.get("last_processed_time", {}).get("value", 0) or 0),
        "chain_head_height": int(rows.get("chain_head_height", {}).get("value", 0) or 0),
        "catching_up": is_node_catching_up(),
        "lag_seconds": int(time.time()) - int(rows.get("last_processed_time", {}).get("value", 0) or 0),
    }


def classify_reject(raw_log: str) -> Dict[str, Any]:
    """Classify a chain broadcast rejection into a safe, user-facing message."""
    raw = "" if raw_log is None else str(raw_log)
    msg = raw.lower()
    out: Dict[str, Any] = {"reason": "rejected", "message": "transaction rejected"}
    try:
        m = re.search(r"out of gas.*?gaswanted:\s*(\d+).*?gasused:\s*(\d+)", msg)
        if m:
            out.update(
                {
                    "reason": "out_of_gas",
                    "gas_provided": int(m.group(1)),
                    "gas_required": int(m.group(2)),
                    "message": "out of gas",
                }
            )
            return out
        m = re.search(r"needs\s*(\d+)([a-z]+).*?has\s*(\d+)([a-z]+)", msg)
        if m:
            need_amt, need_den = int(m.group(1)), m.group(2)
            have_amt, have_den = int(m.group(3)), m.group(4)
            out.update(
                {
                    "reason": "payer_insufficient_funds",
                    "need": need_amt,
                    "have": have_amt,
                    "denom": need_den if need_den == have_den else need_den,
                    "message": "fee payer insufficient funds",
                }
            )
            return out
        m = re.search(r"invalid relay fields.*?gas used: ['\"]?(\d+)", msg)
        if m:
            out.update(
                {
                    "reason": "invalid_relay_fields",
                    "gas_used": int(m.group(1)),
                    "message": "invalid relay fields",
                }
            )
            return out
        if "gift rejected" in msg and "level" in msg:
            out.update(
                {
                    "reason": "gift_rejected_higher_tier",
                    "message": "gift rejected: recipient has a higher tier than requested",
                }
            )
            return out
        if "insufficient balance" in msg:
            out.update({"reason": "insufficient_balance", "message": "insufficient balance"})
            return out
    except Exception:
        pass

    if not raw.strip():
        out["message"] = "chain returned empty error log for this transaction"
    return out


def get_connected_peers(timeout_s: int = 2) -> list[Dict[str, str]]:
    """Get connected peers from indexer DB chain_stats."""
    with connect_db(timeout=3.0, busy_timeout_ms=5000) as conn:
        cur = conn.cursor()
        cur.execute("SELECT value FROM chain_stats WHERE key = 'connected_peers'")
        row = cur.fetchone()
        if not row or row[0] is None:
            raise RuntimeError("connected_peers missing in indexer DB")
        if not isinstance(row[0], list):
            raise RuntimeError("connected_peers invalid format in indexer DB")
        peers = []
        for p in row[0]:
            if not isinstance(p, dict):
                raise RuntimeError("connected_peers entry invalid")
            ip = str(p.get("ip", "") or "").strip()
            moniker = str(p.get("moniker", "") or "").strip()
            if not ip and not moniker:
                continue
            peers.append({"ip": ip, "moniker": moniker})
        return peers


__all__ = [
    "get_difficulty_info",
    "get_latest_block_hash",
    "get_recent_block_hashes",
    "is_valid_recent_block_hash",
    "get_current_pow_difficulty",
    "get_pow_factor",
    "get_pow_base_bits",
    "get_block_time_seconds",
    "max_envelope_future_skew_seconds",
    "is_node_catching_up",
    "classify_reject",
    "get_connected_peers",
    "get_indexer_health",
]
