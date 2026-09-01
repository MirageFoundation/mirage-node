from __future__ import annotations

"""Chain parameter loading and cache — reads from indexer DB (no gRPC).

Params are stored in the indexer's chain_stats table by the indexer on startup
and periodically refreshed. The backend reads them from the DB.
"""

import logging
import threading
import time
from typing import Optional, Dict, Any

import psycopg

from db import connect_db

log = logging.getLogger(__name__)

_PARAMS_CACHE: Optional[Dict[str, Any]] = None
_PARAMS_LOADED_AT: float = 0.0
_LOCK = threading.Lock()

# How long a loaded param set is served before it is re-read. load_params() used
# to run exactly once at startup and cache unconditionally, and force=True was
# never called anywhere, so a governance change to block_hash_window, pow_base_bits
# or the tier limits stayed invisible until the process restarted — including the
# hash window this backend serves to clients, which is the coupling the comment in
# chain.py says it is protecting.
PARAMS_REFRESH_SECONDS = 60

_REQUIRED_INT_PARAMS = [
    # Some PoW keys keep pre-v1.11 names; see indexer/params.py::_PARAMS_LEGACY_NAME_ALIASES.
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
    "max_community_size",
    "min_community_size",
    "subscription_period",
    "relay_min_gas_price",
    "relay_max_gas_fee",
    "max_envelope_age",
    "subscription_reserve_bps",
    "subscription_creator_bps",
    "subscriber_daily_relay_limit",
    "max_subscription_periods_per_purchase",
    "subscription_early_renewal_days",
]

_REQUIRED_FLOAT_PARAMS = [
    "mint_dynamic_split",
    "mint_floor_split",
    "pow_factor",
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
        for key in (
            "max_biography_length",
            "max_curation_memberships",
            "max_daily_relays",
        ):
            if key not in tier:
                raise RuntimeError(f"missing {key} in tier {idx}")
            try:
                tier[key] = int(tier[key])
            except (TypeError, ValueError):
                raise RuntimeError(f"invalid {key} in tier {idx}: {tier.get(key)}")
    result["tiers"] = tiers

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
    global _PARAMS_CACHE, _PARAMS_LOADED_AT
    with _LOCK:
        if _PARAMS_CACHE is not None and not force:
            return _PARAMS_CACHE

        last_error = None

        for attempt in range(max_retries):
            try:
                params_dict = _query_params_from_db()
                if not params_dict:
                    raise RuntimeError("chain_params not yet available in indexer DB")
                cache = _build_cache_from_params(params_dict)
                _PARAMS_CACHE = cache
                _PARAMS_LOADED_AT = time.monotonic()
                # Count at info, values at debug: the full set is long and dumping it
                # on every start bloats logs that get shared when debugging (L-8).
                log.info(f"Loaded {len(cache)} chain params from indexer DB")
                log.debug(f"Chain params: {cache}")
                return _PARAMS_CACHE
            except psycopg.errors.InsufficientPrivilege as e:
                # The retry loop exists to wait for the indexer to populate
                # chain_params. A missing grant is not a race that resolves: it
                # spent an hour logging identical warnings while the node served
                # the maintenance page, and the operator saw a mute failed
                # install. Say what is wrong, once, and stop.
                raise RuntimeError(
                    "the read-only indexer role cannot read the indexer DB: "
                    f"{e}. Grant it SELECT on schema public in the indexer database "
                    "(see ensure_local_postgres_dbs in deploy/entrypoint.sh); no "
                    "amount of waiting will fix this."
                ) from e
            except Exception as e:
                last_error = e
                if attempt < max_retries - 1:
                    log.warning(f"Failed to load chain params (attempt {attempt + 1}/{max_retries}): {e}")
                    time.sleep(retry_interval)

        raise RuntimeError(f"Failed to load chain params after {max_retries} attempts: {last_error}")


def expect_params() -> Dict[str, Any]:
    """Get cached params, re-reading them once the cache is older than the TTL.

    A refresh that fails keeps serving the values already loaded rather than
    failing the request. That is not a fallback masking a bug: the previous
    behaviour was to serve this same set forever, so a transient indexer blip
    leaves the backend no worse off than it was, while a 503 on every relay route
    would be a new and much larger failure. The attempt is logged either way.
    """
    global _PARAMS_LOADED_AT
    if _PARAMS_CACHE is None:
        raise RuntimeError("params cache uninitialized - indexer not available?")
    if time.monotonic() - _PARAMS_LOADED_AT >= PARAMS_REFRESH_SECONDS:
        try:
            # One attempt, no retry sleep: this runs on the request path.
            load_params(force=True, max_retries=1)
        except Exception as e:  # noqa: BLE001
            # Back off for a full interval. Without this a broken indexer would be
            # re-queried by every request instead of once per TTL.
            _PARAMS_LOADED_AT = time.monotonic()
            log.warning(f"Chain param refresh failed, serving cached values: {e}")
    return _PARAMS_CACHE


__all__ = ["load_params", "expect_params"]
