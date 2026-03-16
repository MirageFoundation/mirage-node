from __future__ import annotations

"""Chain parameter loading and cache — reads from indexer DB (no gRPC).

Params are stored in the indexer's chain_stats table by the indexer on startup
and periodically refreshed. The backend reads them from the DB.
"""

import logging
import threading
import time
from typing import Optional, Dict, Any

from db import connect_db

log = logging.getLogger(__name__)

_PARAMS_CACHE: Optional[Dict[str, Any]] = None
_PARAMS_CACHE_TIME: float = 0.0
_PARAMS_CACHE_TTL: float = 300.0
_LOCK = threading.Lock()

_REQUIRED_INT_PARAMS = [
    "pow_base_bits",
    "pow_message_window",
    "pow_increase_threshold",
    "pow_calm_period_definition",
    "pow_calm_sequence_threshold",
    "pow_difficulty_grace_period",
    "block_hash_window",
    "mint_interval",
    "mint_quantity",
    "mint_dynamic_credit_cap",
    "max_username_size",
    "min_username_size",
    "max_topic_size",
    "min_topic_size",
    "subscription_period",
    "relay_min_gas_price",
    "relay_max_gas_fee",
    "max_envelope_age",
]

_REQUIRED_FLOAT_PARAMS = [
    "mint_dynamic_split",
    "pow_factor",
    "subscription_reserve_percent",
    "bridge_attestation_threshold",
]


def _build_cache_from_params(p: Dict) -> Dict[str, Any]:
    """Build cache dict from params, validating ALL required keys."""
    result: Dict[str, Any] = {}

    for key in _REQUIRED_INT_PARAMS:
        value = p.get(key)
        if value is None:
            raise RuntimeError(f"missing required chain param: {key}")
        try:
            result[key] = int(value)
        except (TypeError, ValueError):
            raise RuntimeError(f"invalid value for param {key}: {value}")

    for key in _REQUIRED_FLOAT_PARAMS:
        value = p.get(key)
        if value is None:
            raise RuntimeError(f"missing required chain param: {key}")
        try:
            result[key] = float(value)
        except (TypeError, ValueError):
            raise RuntimeError(f"invalid value for param {key}: {value}")

    tiers = p.get("tiers")
    if not tiers or not isinstance(tiers, list) or len(tiers) == 0:
        raise RuntimeError("missing or empty tiers in chain params")
    for idx, tier in enumerate(tiers):
        if "max_biography_length" not in tier:
            raise RuntimeError(f"missing max_biography_length in tier {idx}")
        try:
            tier["max_biography_length"] = int(tier["max_biography_length"])
        except (TypeError, ValueError):
            raise RuntimeError(f"invalid max_biography_length in tier {idx}: {tier.get('max_biography_length')}")
    result["tiers"] = tiers

    result["bridge_chains"] = p.get("bridge_chains") or []

    award_configs = p.get("award_configs")
    if not award_configs or not isinstance(award_configs, list) or len(award_configs) == 0:
        raise RuntimeError("missing or empty award_configs in chain params")
    result["award_configs"] = award_configs

    return result


def _query_params_from_db() -> Dict:
    """Read chain_params from indexer DB chain_stats table."""
    with connect_db(timeout=5.0, busy_timeout_ms=10000) as conn:
        cur = conn.cursor()
        cur.execute("SELECT value FROM chain_stats WHERE key = 'chain_params'")
        row = cur.fetchone()
        if row and row[0]:
            return row[0] if isinstance(row[0], dict) else {}
    return {}


def load_params(force: bool = False, max_retries: int = 360, retry_interval: float = 10.0) -> Dict[str, Any]:
    """Load params from indexer DB, waiting for indexer to populate them.

    Args:
        force: Force reload even if cached
        max_retries: Max attempts to read from DB (default 360 = 1 hour)
        retry_interval: Seconds between retries

    Raises:
        RuntimeError: If params not available after max_retries
    """
    global _PARAMS_CACHE, _PARAMS_CACHE_TIME
    with _LOCK:
        now = time.time()
        cache_valid = _PARAMS_CACHE is not None and (now - _PARAMS_CACHE_TIME) < _PARAMS_CACHE_TTL
        if cache_valid and not force:
            return _PARAMS_CACHE

        last_error = None

        for attempt in range(max_retries):
            try:
                params_dict = _query_params_from_db()
                if not params_dict:
                    raise RuntimeError("chain_params not yet available in indexer DB")
                cache = _build_cache_from_params(params_dict)
                _PARAMS_CACHE = cache
                _PARAMS_CACHE_TIME = time.time()
                log.info(f"Loaded chain params from indexer DB: {cache}")
                return _PARAMS_CACHE
            except Exception as e:
                last_error = e
                if attempt < max_retries - 1:
                    log.warning(f"Failed to load chain params (attempt {attempt + 1}/{max_retries}): {e}")
                    time.sleep(retry_interval)

        raise RuntimeError(f"Failed to load chain params after {max_retries} attempts: {last_error}")


def expect_params() -> Dict[str, Any]:
    """Get cached params. Raises if not loaded yet."""
    if _PARAMS_CACHE is None:
        raise RuntimeError("params cache uninitialized - indexer not available?")
    return _PARAMS_CACHE


__all__ = ["load_params", "expect_params"]
