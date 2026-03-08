from __future__ import annotations

"""Chain parameter loading and cache using direct gRPC queries.

Params are loaded from the chain at startup and cached. The backend will
wait for the chain to be available before starting to serve requests.
"""

import logging
import threading
import time
from typing import Optional, Dict, Any

from google.protobuf.json_format import MessageToDict

from node import get_grpc_channel
from shared.datatypes import QueryParamsRequest, QueryParamsResponse

log = logging.getLogger(__name__)

_PARAMS_CACHE: Optional[Dict[str, Any]] = None
_PARAMS_CACHE_TIME: float = 0.0
_PARAMS_CACHE_TTL: float = 300.0  # 5 minutes - auto-refresh after chain upgrades
_LOCK = threading.Lock()

# ALL required integer params from chain - no defaults, MUST be present
# If any of these are missing, the backend WILL NOT START
_REQUIRED_INT_PARAMS = [
    # PoW params
    "pow_base_bits",
    "pow_message_window",
    "pow_increase_threshold",
    "pow_calm_period_definition",
    "pow_calm_sequence_threshold",
    "pow_difficulty_grace_period",
    "block_hash_window",
    # Minting params
    "mint_interval",
    "mint_quantity",
    "mint_dynamic_credit_cap",
    # Username/topic limits
    "max_username_size",
    "min_username_size",
    "max_topic_size",
    "min_topic_size",
    # Subscription params
    "subscription_period",
    # Relay fee params
    "relay_min_gas_price",
    "relay_max_gas_fee",
    # Envelope replay protection
    "max_envelope_age",
]

# Required float params
_REQUIRED_FLOAT_PARAMS = [
    "mint_dynamic_split",
    "pow_factor",
    "subscription_reserve_percent",
    "bridge_attestation_threshold",
]


def _build_cache_from_params(p: Dict) -> Dict[str, Any]:
    """Build cache dict from params, validating ALL required keys."""
    result: Dict[str, Any] = {}

    # Required int params - fail hard if missing
    for key in _REQUIRED_INT_PARAMS:
        value = p.get(key)
        if value is None:
            raise RuntimeError(f"missing required chain param: {key}")
        try:
            result[key] = int(value)
        except (TypeError, ValueError):
            raise RuntimeError(f"invalid value for param {key}: {value}")

    # Required float params - fail hard if missing
    for key in _REQUIRED_FLOAT_PARAMS:
        value = p.get(key)
        if value is None:
            raise RuntimeError(f"missing required chain param: {key}")
        try:
            result[key] = float(value)
        except (TypeError, ValueError):
            raise RuntimeError(f"invalid value for param {key}: {value}")

    # Tiers - MUST be present and non-empty
    tiers = p.get("tiers")
    if not tiers or not isinstance(tiers, list) or len(tiers) == 0:
        raise RuntimeError("missing or empty tiers in chain params")
    result["tiers"] = tiers

    # Bridge chains - optional, defaults to empty list
    result["bridge_chains"] = p.get("bridge_chains") or []

    # Award configs - MUST be present and non-empty
    award_configs = p.get("award_configs")
    if not award_configs or not isinstance(award_configs, list) or len(award_configs) == 0:
        raise RuntimeError("missing or empty award_configs in chain params")
    result["award_configs"] = award_configs

    return result


def load_params(force: bool = False, max_retries: int = 360, retry_interval: float = 10.0) -> Dict[str, Any]:
    """Load params from chain, waiting for chain to be available.

    Args:
        force: Force reload even if cached
        max_retries: Max attempts to connect to chain (default 360 = 1 hour)
        retry_interval: Seconds between retries

    Raises:
        RuntimeError: If chain is not available after max_retries
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
                params_dict = _query_core_params()
                cache = _build_cache_from_params(params_dict)
                _PARAMS_CACHE = cache
                _PARAMS_CACHE_TIME = time.time()
                log.info(f"Loaded chain params: {cache}")
                return _PARAMS_CACHE
            except Exception as e:
                last_error = e
                if attempt < max_retries - 1:
                    log.warning(f"Failed to load chain params (attempt {attempt + 1}/{max_retries}): {e}")
                    time.sleep(retry_interval)

        raise RuntimeError(f"Failed to load chain params after {max_retries} attempts: {last_error}")


def _query_core_params(timeout: float = 5.0) -> Dict:
    """Query core module params over gRPC and return as dict."""

    def _deserialize(data: bytes) -> QueryParamsResponse:
        msg = QueryParamsResponse()
        msg.ParseFromString(data)
        return msg

    ch = get_grpc_channel()
    method = ch.unary_unary(
        "/mirage.core.v1.Query/GetParams",
        request_serializer=lambda msg: msg.SerializeToString(),
        response_deserializer=_deserialize,
    )
    resp = method(QueryParamsRequest(), timeout=timeout)
    return MessageToDict(
        resp.params,
        preserving_proto_field_name=True,
        always_print_fields_with_no_presence=True,
    )


def expect_params() -> Dict[str, Any]:
    """Get cached params. Raises if not loaded yet."""
    if _PARAMS_CACHE is None:
        raise RuntimeError("params cache uninitialized - chain not available?")
    return _PARAMS_CACHE


__all__ = ["load_params", "expect_params"]
