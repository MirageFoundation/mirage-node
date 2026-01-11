from __future__ import annotations

"""Chain parameter loading and cache using direct gRPC queries.

Params are loaded from the chain at startup and cached. The backend will
wait for the chain to be available before starting to serve requests.
"""

import logging
import threading
import time
from typing import Optional, Dict, Any

import grpc
from google.protobuf.json_format import MessageToDict

from node import require_runtime
from shared.datatypes import QueryParamsRequest, QueryParamsResponse

log = logging.getLogger(__name__)

_PARAMS_CACHE: Optional[Dict[str, Any]] = None
_LOCK = threading.Lock()

# ALL required integer params from chain - no defaults, MUST be present
# If any of these are missing, the backend WILL NOT START
_REQUIRED_INT_PARAMS = [
    # PoW params
    "min_difficulty",
    "pow_message_window",
    "pow_message_limit",
    "pow_calm_period_definition",
    "pow_calm_sequence_threshold",
    "pow_difficulty_allowance",
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
    "subscription_reserve_percent",
    # Relay fee params
    "relay_min_gas_price",
    "relay_max_gas_fee",
]

# Required float params
_REQUIRED_FLOAT_PARAMS = [
    "mint_dynamic_split",
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

    return result


def load_params(
    force: bool = False, max_retries: int = 60, retry_interval: float = 5.0
) -> Dict[str, Any]:
    """Load params from chain, waiting for chain to be available.

    Args:
        force: Force reload even if cached
        max_retries: Max attempts to connect to chain (default 60 = 2 minutes)
        retry_interval: Seconds between retries

    Raises:
        RuntimeError: If chain is not available after max_retries
    """
    global _PARAMS_CACHE
    with _LOCK:
        if _PARAMS_CACHE is not None and not force:
            return _PARAMS_CACHE

        rt = require_runtime()
        last_error = None

        for attempt in range(max_retries):
            try:
                params_dict = _query_core_params(rt.grpc_target)
                cache = _build_cache_from_params(params_dict)
                _PARAMS_CACHE = cache
                log.info(f"Loaded chain params: {cache}")
                return _PARAMS_CACHE
            except Exception as e:
                last_error = e
                if attempt < max_retries - 1:
                    log.warning(f"Failed to load chain params (attempt {attempt + 1}/{max_retries}): {e}")
                    time.sleep(retry_interval)

        raise RuntimeError(f"Failed to load chain params after {max_retries} attempts: {last_error}")


def _query_core_params(target: str, timeout: float = 5.0) -> Dict:
    """Query core module params over gRPC and return as dict."""

    def _deserialize(data: bytes) -> QueryParamsResponse:
        msg = QueryParamsResponse()
        msg.ParseFromString(data)
        return msg

    with grpc.insecure_channel(target) as channel:
        method = channel.unary_unary(
            "/mirage.core.v1.Query/Params",
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
