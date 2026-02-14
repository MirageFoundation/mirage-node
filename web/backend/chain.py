from __future__ import annotations

"""Chain query helpers using gRPC.

Functions:
- get_difficulty_info(): Full difficulty state via gRPC Query/Difficulty.
- get_latest_block_hash(): Latest block hash via gRPC Query/Difficulty.
- get_current_pow_difficulty(): Current dynamic PoW difficulty via gRPC.
- get_recent_block_hashes(): Recent block hashes for validation.
- is_valid_recent_block_hash(): Check if hash is in recent window.
- get_block_time_seconds(): Read consensus timeout_commit from config.
- is_node_catching_up(timeout_s=2): True if RPC /status reports catching_up.
- classify_reject(raw_log): Parse common reject reasons from logs.
"""

import json
import re
import time
from typing import Any, Dict, Optional


from google.protobuf.json_format import MessageToDict

from node import require_runtime, get_grpc_channel
from shared.datatypes import QueryDifficultyRequest, QueryDifficultyResponse


# Cache for difficulty info — short TTL so callers don't pay gRPC cost every request
_DIFFICULTY_CACHE: Optional[Dict[str, Any]] = None
_DIFFICULTY_CACHE_HEIGHT: int = 0
_DIFFICULTY_CACHE_TIME: float = 0.0
_DIFFICULTY_CACHE_TTL: float = 5.0  # seconds


def _query_difficulty(timeout: float = 3.0) -> Dict[str, Any]:
    """Query difficulty info via gRPC."""

    def _deserialize(data: bytes) -> QueryDifficultyResponse:
        msg = QueryDifficultyResponse()
        msg.ParseFromString(data)
        return msg

    ch = get_grpc_channel()
    method = ch.unary_unary(
        "/mirage.core.v1.Query/GetDifficulty",
        request_serializer=lambda msg: msg.SerializeToString(),
        response_deserializer=_deserialize,
    )
    resp = method(QueryDifficultyRequest(), timeout=timeout)
    return MessageToDict(resp, preserving_proto_field_name=True, always_print_fields_with_no_presence=True)


def get_difficulty_info(timeout: float = 3.0, *, force: bool = False) -> Dict[str, Any]:
    """Get full difficulty state from chain via gRPC.

    Returns dict with:
    - current_difficulty: int
    - previous_difficulty: int
    - last_change_height: int
    - pow_message_count: int
    - consecutive_low_usage: int
    - latest_block_hash: str (hex, lowercase)
    - current_height: int

    Results are cached for _DIFFICULTY_CACHE_TTL seconds. Pass force=True to bypass.
    """
    global _DIFFICULTY_CACHE, _DIFFICULTY_CACHE_HEIGHT, _DIFFICULTY_CACHE_TIME

    now = time.monotonic()
    if not force and _DIFFICULTY_CACHE is not None and (now - _DIFFICULTY_CACHE_TIME) < _DIFFICULTY_CACHE_TTL:
        return _DIFFICULTY_CACHE

    info = _query_difficulty(timeout)
    height = int(info.get("current_height", 0))

    _DIFFICULTY_CACHE = info
    _DIFFICULTY_CACHE_HEIGHT = height
    _DIFFICULTY_CACHE_TIME = now

    return info


def get_latest_block_hash(timeout_s: int = 5) -> str:
    """Get latest block hash via Tendermint RPC /status (hard fail, no fallbacks)."""
    import urllib.request as _url

    rpc = require_runtime().rpc_url
    url = f"{rpc}/status"
    with _url.urlopen(url, timeout=timeout_s) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    raw = (data.get("result", {}).get("sync_info", {}).get("latest_block_hash", "") or "").strip()
    if not raw or not re.fullmatch(r"[0-9A-Fa-f]{64}", raw):
        raise RuntimeError("unexpected latest_block_hash format from RPC")
    return raw


def get_current_pow_difficulty() -> int:
    """Get current PoW difficulty factor via gRPC Query/Difficulty."""
    info = get_difficulty_info()
    return int(info["current_difficulty"])


def get_min_difficulty() -> int:
    """Get min_difficulty (base target bits) from chain params."""
    from params import expect_params
    return int(expect_params()["min_difficulty"])


# Cache for recent block hashes
_RECENT_BLOCK_HASHES: list[str] = []


def _get_block_hash_window() -> int:
    """Get block_hash_window from chain params (cached at startup)."""
    from params import expect_params

    return int(expect_params()["block_hash_window"])


def get_recent_block_hashes(timeout_s: int = 5) -> list[str]:
    """Get the last N block hashes (matching chain's block_hash_window param) via Tendermint RPC only."""
    import urllib.request as _url

    global _RECENT_BLOCK_HASHES

    window = _get_block_hash_window()
    rpc = require_runtime().rpc_url

    # Latest height and hash from /status
    url = f"{rpc}/status"
    with _url.urlopen(url, timeout=timeout_s) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    latest_height = int((data.get("result", {}).get("sync_info", {}).get("latest_block_height", 0)) or 0)
    latest_hash = (data.get("result", {}).get("sync_info", {}).get("latest_block_hash", "") or "").strip().upper()

    if not latest_height or not latest_hash or not re.fullmatch(r"[0-9A-Fa-f]{64}", latest_hash):
        # Hard fail: no caches, no fallbacks
        raise RuntimeError("unable to fetch latest block height/hash from RPC")

    # If cache already up-to-date
    if _RECENT_BLOCK_HASHES and _RECENT_BLOCK_HASHES[0].upper() == latest_hash:
        return _RECENT_BLOCK_HASHES

    # Fetch recent blocks via /block?height=
    hashes: list[str] = []
    for i in range(window):
        h = latest_height - i
        if h < 1:
            break
        url = f"{rpc}/block?height={h}"
        with _url.urlopen(url, timeout=2) as resp:
            bdata = json.loads(resp.read().decode("utf-8"))
        block_hash = (bdata.get("result", {}).get("block_id", {}).get("hash", "") or "").strip().upper()
        if block_hash and re.fullmatch(r"[0-9A-Fa-f]{64}", block_hash):
            hashes.append(block_hash)
        else:
            break

    if not hashes:
        raise RuntimeError("failed to fetch recent block hashes from RPC")

    _RECENT_BLOCK_HASHES = hashes
    return _RECENT_BLOCK_HASHES


def is_valid_recent_block_hash(block_hash: str, timeout_s: int = 5) -> bool:
    """Check if block_hash is within the recent block hash window."""
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
_CATCHING_UP_CACHE_TTL: float = 5.0  # seconds


def is_node_catching_up(timeout_s: int = 2) -> bool:
    global _CATCHING_UP_CACHE, _CATCHING_UP_CACHE_TIME
    import urllib.request as _url

    now = time.monotonic()
    if _CATCHING_UP_CACHE is not None and (now - _CATCHING_UP_CACHE_TIME) < _CATCHING_UP_CACHE_TTL:
        return _CATCHING_UP_CACHE

    url = f"{require_runtime().rpc_url}/status"
    try:
        with _url.urlopen(url, timeout=timeout_s) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        val = data.get("result", {}).get("sync_info", {}).get("catching_up", True)
        if isinstance(val, str):
            result = val.strip().lower() == "true"
        else:
            result = bool(val)
    except Exception:
        # Treat unknown as catching up to be safe
        result = True

    _CATCHING_UP_CACHE = result
    _CATCHING_UP_CACHE_TIME = now
    return result


def classify_reject(raw_log: str) -> Dict[str, Any]:
    """Classify a chain broadcast rejection into a safe, user-facing message.

    Returns a dict with at least 'reason' and 'message' keys.
    The 'message' is always a sanitized string safe to return to clients.
    Raw chain logs are never included (they are logged server-side by callers).
    """
    raw = "" if raw_log is None else str(raw_log)
    msg = raw.lower()
    out: Dict[str, Any] = {"reason": "rejected", "message": "transaction rejected"}
    try:
        import re as _re

        m = _re.search(r"out of gas.*?gaswanted:\s*(\d+).*?gasused:\s*(\d+)", msg)
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
        m = _re.search(r"needs\s*(\d+)([a-z]+).*?has\s*(\d+)([a-z]+)", msg)
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
        m = _re.search(r"invalid relay fields.*?gas used: ['\"]?(\d+)", msg)
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

    # If the raw log is empty, note that explicitly.
    if not raw.strip():
        out["message"] = "chain returned empty error log for this transaction"
    return out


def get_connected_peers(timeout_s: int = 2) -> list[Dict[str, str]]:
    import urllib.request as _url
    import ipaddress as _ipa
    import time

    # Cache validator monikers (60 second TTL)
    cache_key = "_validator_moniker_cache"
    cache_time_key = "_validator_cache_time"
    cache_ttl = 60.0

    if not hasattr(get_connected_peers, cache_key):
        setattr(get_connected_peers, cache_key, None)
        setattr(get_connected_peers, cache_time_key, 0.0)

    current_time = time.time()
    cache_time = getattr(get_connected_peers, cache_time_key)
    validator_cache = getattr(get_connected_peers, cache_key)

    # Refresh validator cache if expired
    if validator_cache is None or (current_time - cache_time) >= cache_ttl:
        validator_cache = {}
        try:
            from bank import get_all_validators

            for v in get_all_validators():
                pubkey = v.get("consensus_pubkey", "")
                moniker = v.get("moniker", "")
                if pubkey and moniker:
                    validator_cache[pubkey] = moniker
            setattr(get_connected_peers, cache_key, validator_cache)
            setattr(get_connected_peers, cache_time_key, current_time)
        except Exception:
            pass

    # Get peers from net_info
    url = f"{require_runtime().rpc_url}/net_info"
    with _url.urlopen(url, timeout=timeout_s) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    peers_data = ((data or {}).get("result") or {}).get("peers") or []

    results: list[Dict[str, str]] = []
    seen_ips = set()

    for p in peers_data:
        remote_ip = str((p or {}).get("remote_ip", "")).strip()
        if not remote_ip:
            continue

        try:
            # Validate IP
            _ipa.ip_address(remote_ip)
        except Exception:
            continue

        if remote_ip not in seen_ips:
            seen_ips.add(remote_ip)

            # Query peer's RPC to get validator pubkey and match to on-chain moniker
            moniker = ""
            try:
                peer_rpc = f"http://{remote_ip}:26657"
                peer_url = f"{peer_rpc}/status"
                with _url.urlopen(peer_url, timeout=2) as peer_resp:
                    peer_data = json.loads(peer_resp.read().decode("utf-8"))

                validator_info = ((peer_data or {}).get("result") or {}).get("validator_info") or {}
                pubkey = validator_info.get("pub_key", {}).get("value", "")

                if pubkey and validator_cache:
                    moniker = validator_cache.get(pubkey, "")
            except Exception:
                pass

            results.append({"ip": remote_ip, "moniker": moniker})

    return results


__all__ = [
    "get_difficulty_info",
    "get_latest_block_hash",
    "get_recent_block_hashes",
    "is_valid_recent_block_hash",
    "get_current_pow_difficulty",
    "get_block_time_seconds",
    "is_node_catching_up",
    "classify_reject",
    "get_connected_peers",
]
