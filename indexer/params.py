"""Chain parameter loading for the indexer.

Params are loaded from the chain at startup via gRPC.
The indexer will NOT start if params cannot be loaded.

NO HARDCODED VALUES - everything comes from chain.
"""

import logging
import threading
import time
from typing import Any

import grpc
from google.protobuf.json_format import MessageToDict

from shared.datatypes import Params, QueryParamsRequest, QueryParamsResponse

log = logging.getLogger(__name__)

_PARAMS_CACHE: dict[str, Any] | None = None
_LOCK = threading.Lock()


_PARAMS_LEGACY_NAME_ALIASES = {
    # new proto name (source of truth) -> legacy name still consumed by
    # web/backend, web/frontend, agent docs, and older tests. Kept as a
    # read-through alias so the v1.11.0 rename doesn't require a coordinated
    # rename across the entire Python + JS surface.
    "min_difficulty": "pow_base_bits",
    "pow_message_limit": "pow_increase_threshold",
    "pow_difficulty_allowance": "pow_difficulty_grace_period",
    "pow_difficulty_step": "pow_factor",
}

_PARAMS_PROTO_FIELD_NAMES = {f.name for f in Params.DESCRIPTOR.fields}
_MISSING_ALIAS_SOURCE_FIELDS = [k for k in _PARAMS_LEGACY_NAME_ALIASES if k not in _PARAMS_PROTO_FIELD_NAMES]
if _MISSING_ALIAS_SOURCE_FIELDS:
    raise RuntimeError(
        f"Params alias source field(s) missing from shared.datatypes Params descriptor: {_MISSING_ALIAS_SOURCE_FIELDS}"
    )


def _query_core_params(grpc_target: str, timeout: float = 5.0) -> dict:
    """Query core module params over gRPC and return as dict."""

    def _deserialize(data: bytes) -> QueryParamsResponse:
        msg = QueryParamsResponse()
        msg.ParseFromString(data)
        return msg

    with grpc.insecure_channel(grpc_target) as channel:
        method = channel.unary_unary(
            "/mirage.core.v1.Query/GetParams",
            request_serializer=lambda msg: msg.SerializeToString(),
            response_deserializer=_deserialize,
        )
        resp = method(QueryParamsRequest(), timeout=timeout)
    result = MessageToDict(
        resp.params,
        preserving_proto_field_name=True,
        always_print_fields_with_no_presence=True,
    )
    for new_name, legacy_name in _PARAMS_LEGACY_NAME_ALIASES.items():
        if new_name in result and legacy_name not in result:
            result[legacy_name] = result[new_name]
    return result


def _build_cache_from_params(p: dict) -> dict[str, Any]:
    """Build cache dict from params, deriving validation limits from tiers."""
    result: dict[str, Any] = {}

    # Required params - fail hard if missing
    required_int = [
        "max_username_size",
        "min_username_size",
        "max_community_size",
        "min_community_size",
    ]
    for key in required_int:
        value = p.get(key)
        if value is None:
            raise RuntimeError(f"missing required chain param: {key}")
        result[key] = int(value)

    # Tiers - MUST be present and non-empty
    tiers = p.get("tiers")
    if not tiers or not isinstance(tiers, list) or len(tiers) == 0:
        raise RuntimeError("missing or empty tiers in chain params")
    result["tiers"] = tiers

    result["tier_vote_weights"] = [float(t.get("vote_weight", 1.0)) for t in tiers]

    # Award configs
    award_configs = p.get("award_configs")
    if not award_configs or not isinstance(award_configs, list):
        award_configs = []
    result["award_configs"] = award_configs

    return result


def load_params(
    grpc_target: str, force: bool = False, max_retries: int = 60, retry_interval: float = 5.0
) -> dict[str, Any]:
    """Load params from chain, waiting for chain to be available.

    Args:
        grpc_target: gRPC endpoint (e.g., "localhost:9090")
        force: Force reload even if cached
        max_retries: Max attempts to connect to chain
        retry_interval: Seconds between retries

    Raises:
        RuntimeError: If chain is not available after max_retries
    """
    global _PARAMS_CACHE, _RAW_PARAMS
    with _LOCK:
        if _PARAMS_CACHE is not None and not force:
            return _PARAMS_CACHE

        last_error = None

        for attempt in range(max_retries):
            try:
                params_dict = _query_core_params(grpc_target)
                cache = _build_cache_from_params(params_dict)
                _PARAMS_CACHE = cache
                _RAW_PARAMS = params_dict
                log.info("Loaded chain params for indexer: %s", cache)
                return _PARAMS_CACHE
            except Exception as e:
                last_error = e
                if attempt < max_retries - 1:
                    log.warning("Failed to load chain params (attempt %d/%d): %s", attempt + 1, max_retries, e)
                    time.sleep(retry_interval)

        raise RuntimeError(f"Failed to load chain params after {max_retries} attempts: {last_error}")


_RAW_PARAMS: dict[str, Any] | None = None


def expect_params() -> dict[str, Any]:
    """Get cached params. Raises if not loaded yet."""
    if _PARAMS_CACHE is None:
        raise RuntimeError("indexer params cache uninitialized - call load_params first")
    return _PARAMS_CACHE


def get_raw_params() -> dict[str, Any]:
    """Get the params dict loaded from gRPC for chain_stats persistence.

    Note: this includes compatibility aliases injected by _query_core_params()
    so downstream legacy consumers keep working during field-name transitions.
    """
    if _RAW_PARAMS is None:
        raise RuntimeError("raw params not loaded - call load_params first")
    return _RAW_PARAMS


def get_max_community_size() -> int:
    """Get max community size from chain params."""
    return expect_params()["max_community_size"]


def get_min_community_size() -> int:
    """Get min community size from chain params."""
    return expect_params()["min_community_size"]


def get_max_username_size() -> int:
    """Get max username size from chain params."""
    return expect_params()["max_username_size"]


def get_min_username_size() -> int:
    """Get min username size from chain params."""
    return expect_params()["min_username_size"]


def level_to_tier_index(level: int) -> int:
    """Map a user level to a tier index, mirroring the chain's LevelToTierIndex.

    The chain accepts ANY level >= LevelAdminMin (100) as admin, not just 100
    exactly (blockchain/x/core/types/params.go:70-83). An exact-match lookup here
    raises on a level the chain considers valid, which aborts the block and wedges
    the indexer permanently, so this must stay a range check.
    """
    if level == 0:
        return 0
    if level == 1:
        return 1
    if level >= 100:
        return 2
    return -1


def get_vote_weight(level: int) -> float:
    """Get vote weight for a user level. Cached at startup."""
    weights = expect_params()["tier_vote_weights"]
    idx = level_to_tier_index(int(level))
    if idx < 0 or idx >= len(weights):
        raise ValueError(f"Unknown tier level: {level}")
    return weights[idx]


def get_award_configs() -> list:
    """Get award configs from chain params."""
    return expect_params().get("award_configs", [])


__all__ = [
    "load_params",
    "expect_params",
    "get_raw_params",
    "get_max_community_size",
    "get_min_community_size",
    "get_max_username_size",
    "get_min_username_size",
    "get_vote_weight",
    "level_to_tier_index",
    "get_award_configs",
]
