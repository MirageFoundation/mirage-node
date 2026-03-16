from __future__ import annotations

"""Chain query helpers — reads from indexer DB (no gRPC/RPC).

Functions:
- get_difficulty_info(): Difficulty state from chain_stats DB.
- get_latest_block_hash(): Latest block hash from recent_blocks DB.
- get_current_pow_difficulty(): Current dynamic PoW difficulty.
- get_recent_block_hashes(): Recent block hashes for validation.
- is_valid_recent_block_hash(): Check if hash is in recent window.
- get_block_time_seconds(): Read consensus timeout_commit from config.
- is_node_catching_up(): True if indexer state indicates lag.
- classify_reject(raw_log): Parse common reject reasons from logs.
"""

import json
import re
import time
from typing import Any, Dict, Optional

from db import connect_db


_DIFFICULTY_CACHE: Optional[Dict[str, Any]] = None
_DIFFICULTY_CACHE_TIME: float = 0.0
_DIFFICULTY_CACHE_TTL: float = 5.0


def get_difficulty_info(timeout: float = 3.0, *, force: bool = False) -> Dict[str, Any]:
    """Get difficulty state from indexer DB chain_stats.

    Falls back to querying the difficulty_history table if chain_stats is empty.
    """
    global _DIFFICULTY_CACHE, _DIFFICULTY_CACHE_TIME

    now = time.monotonic()
    if not force and _DIFFICULTY_CACHE is not None and (now - _DIFFICULTY_CACHE_TIME) < _DIFFICULTY_CACHE_TTL:
        return _DIFFICULTY_CACHE

    info: Dict[str, Any] = {
        "current_difficulty": 0,
        "previous_difficulty": 0,
        "last_change_height": 0,
        "pow_message_count": 0,
        "consecutive_low_usage": 0,
        "latest_block_hash": "",
        "current_height": 0,
    }

    with connect_db(timeout=3.0, busy_timeout_ms=5000) as conn:
        cur = conn.cursor()

        # Primary source: chain_stats.difficulty_info
        cur.execute("SELECT value FROM chain_stats WHERE key = 'difficulty_info'")
        diff_row = cur.fetchone()
        if diff_row and isinstance(diff_row[0], dict):
            info.update(diff_row[0])

        # Fallback: difficulty_history table (most recent)
        if not info.get("current_height"):
            cur.execute("SELECT height, difficulty, msg_count FROM difficulty_history ORDER BY height DESC LIMIT 1")
            row = cur.fetchone()
            if row:
                info["current_height"] = int(row[0])
                info["current_difficulty"] = int(row[1])
                info["pow_message_count"] = int(row[2]) if row[2] is not None else 0

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

    return int(expect_params()["pow_base_bits"])


def get_pow_factor() -> float:
    from params import expect_params

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
    recent = get_recent_block_hashes(timeout_s)
    return block_hash.upper() in [h.upper() for h in recent]


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


def is_node_catching_up(timeout_s: int = 2) -> bool:
    """Check if indexer is behind — uses indexer_state to detect lag.

    Returns True if:
    - Last processed time is >30s ago (time-based lag), OR
    - Indexer is >10 blocks behind chain head (height-based lag), OR
    - Indexer state is unavailable
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

            last_ts = int(state.get("last_processed_time", 0) or 0)
            last_height = int(state.get("last_processed_height", 0) or 0)
            chain_head = int(state.get("chain_head_height", 0) or 0)

            if not last_ts:
                result = True
            else:
                time_lag = int(time.time()) - last_ts > 30
                height_lag = chain_head > 0 and (chain_head - last_height) > 10
                result = time_lag or height_lag
    except Exception:
        result = True

    _CATCHING_UP_CACHE = result
    _CATCHING_UP_CACHE_TIME = now
    return result


def get_indexer_health() -> Dict[str, Any]:
    """Return indexer health metrics for monitoring."""
    try:
        with connect_db(timeout=3.0, busy_timeout_ms=5000) as conn:
            cur = conn.cursor()
            cur.execute("SELECT key, value, updated_at FROM indexer_state")
            rows = {r[0]: {"value": r[1], "updated_at": r[2]} for r in cur.fetchall()}
            return {
                "last_processed_height": int(rows.get("last_processed_height", {}).get("value", 0) or 0),
                "last_processed_time": int(rows.get("last_processed_time", {}).get("value", 0) or 0),
                "chain_head_height": int(rows.get("chain_head_height", {}).get("value", 0) or 0),
                "catching_up": is_node_catching_up(),
                "lag_seconds": int(time.time()) - int(rows.get("last_processed_time", {}).get("value", 0) or 0),
            }
    except Exception as e:
        return {"error": str(e), "catching_up": True}


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
    except Exception:
        pass

    if not raw.strip():
        out["message"] = "chain returned empty error log for this transaction"
    return out


def get_connected_peers(timeout_s: int = 2) -> list[Dict[str, str]]:
    """Get connected peers from indexer DB chain_stats (if available)."""
    try:
        with connect_db(timeout=3.0, busy_timeout_ms=5000) as conn:
            cur = conn.cursor()
            cur.execute("SELECT value FROM chain_stats WHERE key = 'validators'")
            row = cur.fetchone()
            if row and row[0]:
                validators = row[0] if isinstance(row[0], list) else []
                return [{"ip": "", "moniker": v.get("moniker", "")} for v in validators if v.get("moniker")]
    except Exception:
        pass
    return []


__all__ = [
    "get_difficulty_info",
    "get_latest_block_hash",
    "get_recent_block_hashes",
    "is_valid_recent_block_hash",
    "get_current_pow_difficulty",
    "get_pow_factor",
    "get_pow_base_bits",
    "get_block_time_seconds",
    "is_node_catching_up",
    "classify_reject",
    "get_connected_peers",
    "get_indexer_health",
]
