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

from shared.datatypes import QueryParamsRequest, QueryParamsResponse

log = logging.getLogger(__name__)

_PARAMS_CACHE: dict[str, Any] | None = None
_LOCK = threading.Lock()


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
    return MessageToDict(
        resp.params,
        preserving_proto_field_name=True,
        always_print_fields_with_no_presence=True,
    )


def _build_cache_from_params(p: dict) -> dict[str, Any]:
    """Build cache dict from params, deriving validation limits from tiers."""
    result: dict[str, Any] = {}

    # Required params - fail hard if missing
    required_int = [
        "max_username_size",
        "min_username_size",
        "max_topic_size",
        "min_topic_size",
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

    # Derive content/title limits from tiers:
    # - Max values come from highest tier (so we accept content up to that limit)
    # - Min values are 0 for content (comments can be empty-ish), 3 for titles
    max_title = 0
    max_content = 0
    for tier in tiers:
        t_title = int(tier.get("max_title_length", 0) or 0)
        t_content = int(tier.get("max_content_length", 0) or 0)
        if t_title > max_title:
            max_title = t_title
        if t_content > max_content:
            max_content = t_content

    if max_title == 0:
        raise RuntimeError("all tiers have max_title_length=0")
    if max_content == 0:
        raise RuntimeError("all tiers have max_content_length=0")

    result["max_title_size"] = max_title
    result["max_content_size"] = max_content
    # Min title size: chain doesn't explicitly define this, but root posts require titles
    # Use 1 as minimum (empty title = invalid)
    result["min_title_size"] = 1
    # Min content size: 0 (content can be empty for certain cases)
    result["min_content_size"] = 0

    # Build vote weight lookup: {level: weight}
    vote_weights = {i: float(t.get("vote_weight", 1.0)) for i, t in enumerate(tiers)}
    vote_weights[100] = vote_weights[len(tiers) - 1]  # admin = highest tier
    result["vote_weights"] = vote_weights

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
    global _PARAMS_CACHE
    with _LOCK:
        if _PARAMS_CACHE is not None and not force:
            return _PARAMS_CACHE

        last_error = None

        for attempt in range(max_retries):
            try:
                params_dict = _query_core_params(grpc_target)
                cache = _build_cache_from_params(params_dict)
                _PARAMS_CACHE = cache
                log.info("Loaded chain params for indexer: %s", cache)
                return _PARAMS_CACHE
            except Exception as e:
                last_error = e
                if attempt < max_retries - 1:
                    log.warning("Failed to load chain params (attempt %d/%d): %s", attempt + 1, max_retries, e)
                    time.sleep(retry_interval)

        raise RuntimeError(f"Failed to load chain params after {max_retries} attempts: {last_error}")


def expect_params() -> dict[str, Any]:
    """Get cached params. Raises if not loaded yet."""
    if _PARAMS_CACHE is None:
        raise RuntimeError("indexer params cache uninitialized - call load_params first")
    return _PARAMS_CACHE


def get_max_topic_size() -> int:
    """Get max topic size from chain params."""
    return expect_params()["max_topic_size"]


def get_min_topic_size() -> int:
    """Get min topic size from chain params."""
    return expect_params()["min_topic_size"]


def get_max_username_size() -> int:
    """Get max username size from chain params."""
    return expect_params()["max_username_size"]


def get_min_username_size() -> int:
    """Get min username size from chain params."""
    return expect_params()["min_username_size"]


def get_max_title_size() -> int:
    """Get max title size (from highest tier)."""
    return expect_params()["max_title_size"]


def get_min_title_size() -> int:
    """Get min title size."""
    return expect_params()["min_title_size"]


def get_max_content_size() -> int:
    """Get max content size (from highest tier)."""
    return expect_params()["max_content_size"]


def get_min_content_size() -> int:
    """Get min content size."""
    return expect_params()["min_content_size"]


def get_vote_weight(level: int) -> float:
    """Get vote weight for tier level. Cached at startup."""
    weights = expect_params()["vote_weights"]
    if level not in weights:
        raise ValueError(f"Unknown tier level: {level}")
    return weights[level]


def get_award_configs() -> list:
    """Get award configs from chain params."""
    return expect_params().get("award_configs", [])


__all__ = [
    "load_params",
    "expect_params",
    "get_max_topic_size",
    "get_min_topic_size",
    "get_max_username_size",
    "get_min_username_size",
    "get_max_title_size",
    "get_min_title_size",
    "get_max_content_size",
    "get_min_content_size",
    "get_vote_weight",
    "get_award_configs",
]
