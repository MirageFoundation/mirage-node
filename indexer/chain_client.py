"""
Chain client for HTTP, gRPC, and WebSocket operations.
"""

import base64
import json
import logging
import time
import requests
import websocket
import grpc
from datetime import datetime, timezone
import urllib.parse as _up
from cosmpy.protos.cosmos.gov.v1beta1 import query_pb2 as gov_query_pb2
from cosmpy.protos.cosmos.gov.v1beta1 import query_pb2_grpc as gov_query_pb2_grpc
from indexer.settings import (
    HTTP_TIMEOUT_SHORT,
    HTTP_TIMEOUT_MEDIUM,
    HTTP_TIMEOUT_LONG,
    GRPC_TIMEOUT,
    WS_PING_INTERVAL,
    WS_PING_TIMEOUT,
    WS_RECONNECT_DELAY,
)

logger = logging.getLogger(__name__)


class ChainClient:
    """Handles all chain communication (HTTP, gRPC, WebSocket)."""

    def __init__(self, jsonrpc_url: str):
        self.jsonrpc_url = jsonrpc_url
        self.ws_url = jsonrpc_url.replace("http://", "ws://") + "/websocket"
        self.grpc_target = self._derive_grpc_target(jsonrpc_url)

    @staticmethod
    def _derive_grpc_target(jsonrpc_url: str) -> str:
        """Derive gRPC target from RPC URL (same host, port 9090)."""
        base_rpc = jsonrpc_url
        for path in ["/block_results", "/block", "/status", "/abci_query"]:
            if path in base_rpc:
                base_rpc = base_rpc.replace(path, "")
        if "://" in base_rpc:
            protocol, rest = base_rpc.split("://", 1)
            if ":" in rest:
                host, _ = rest.rsplit(":", 1)
                return f"{host}:9090"
            else:
                return f"{rest}:9090"
        else:
            return base_rpc.replace(":26657", ":9090")

    @staticmethod
    def _derive_rest_url(jsonrpc_url: str) -> str:
        """Derive REST API URL from RPC URL (same host, port 1317)."""
        base_rpc = jsonrpc_url
        for path in ["/block_results", "/block", "/status", "/abci_query"]:
            if path in base_rpc:
                base_rpc = base_rpc.replace(path, "")
        parsed = _up.urlparse(base_rpc)
        if not parsed.scheme:
            raise ValueError(f"RPC URL missing scheme: {jsonrpc_url}")
        if not parsed.hostname:
            raise ValueError(f"RPC URL missing host: {jsonrpc_url}")
        return f"{parsed.scheme}://{parsed.hostname}:1317"

    def get_status(self) -> dict:
        """Get chain status."""
        r = requests.get(f"{self.jsonrpc_url}/status", timeout=HTTP_TIMEOUT_SHORT)
        r.raise_for_status()
        return r.json()

    def get_net_info(self) -> dict:
        """Get network info (connected peers)."""
        r = requests.get(f"{self.jsonrpc_url}/net_info", timeout=HTTP_TIMEOUT_SHORT)
        r.raise_for_status()
        return r.json()

    def get_current_height(self) -> int:
        """Get current block height."""
        data = self.get_status()
        return int(data["result"]["sync_info"]["latest_block_height"])

    def get_earliest_height(self) -> int:
        """Get earliest block height retained by the node (for pruned nodes)."""
        data = self.get_status()
        try:
            return int(data["result"]["sync_info"]["earliest_block_height"])
        except Exception:
            # Fallback: if field missing, assume 1
            return 1

    def get_block(self, height: int) -> dict:
        """Get block data."""
        r = requests.get(f"{self.jsonrpc_url}/block", params={"height": str(height)}, timeout=HTTP_TIMEOUT_MEDIUM)
        r.raise_for_status()
        return r.json()

    def get_block_results(self, height: int) -> dict:
        """Get block results (txs_results with codes/events)."""
        r = requests.get(
            f"{self.jsonrpc_url}/block_results",
            params={"height": str(height)},
            timeout=HTTP_TIMEOUT_MEDIUM,
        )
        r.raise_for_status()
        return r.json()

    def abci_query(self, path: str, data: str, timeout: int = HTTP_TIMEOUT_SHORT) -> dict:
        """Perform ABCI query."""
        r = requests.get(
            f"{self.jsonrpc_url}/abci_query",
            params={"path": path, "data": data},
            timeout=timeout,
        )
        r.raise_for_status()
        return r.json()

    def query_profile_full(self, addr: str, timeout: int = GRPC_TIMEOUT) -> dict:
        """Query full profile (including per-entry lists) via gRPC."""
        from shared.datatypes import QueryProfileRequest, QueryProfileResponse

        with grpc.insecure_channel(self.grpc_target) as channel:
            method = channel.unary_unary(
                "/mirage.core.v1.Query/GetProfile",
                request_serializer=QueryProfileRequest.SerializeToString,
                response_deserializer=QueryProfileResponse.FromString,
            )
            resp = method(QueryProfileRequest(address=str(addr).lower()), timeout=timeout)

        profile = {
            "owner": str(resp.owner),
            "username": str(resp.username),
            "level": int(resp.level),
            "created_at": int(resp.created_at),
            "subscription_expiry": int(resp.subscription_expiry),
            "auto_renew": bool(resp.auto_renew),
            "reserve_funds": int(resp.reserve_funds),
            "biography": str(resp.biography),
            "avatar": str(resp.avatar),
            "banner": str(resp.banner),
            "flair": str(resp.flair),
            "enabled_agents": list(resp.enabled_agents),
            "followed_users": list(resp.followed_users),
            "followed_topics": list(resp.followed_topics),
            "blocked_users": list(resp.blocked_users),
            "blocked_posts": list(resp.blocked_posts),
            "blocked_topics": list(resp.blocked_topics),
        }
        logger.debug(
            "query_profile_full grpc addr=%s agents=%d users=%d topics=%d",
            addr,
            len(profile["enabled_agents"]),
            len(profile["followed_users"]),
            len(profile["followed_topics"]),
        )
        return profile

    def list_profiles_subspace(self) -> list[dict]:
        """
        List all profiles stored in the chain KV.
        Tries ABCI subspace query first, falls back to REST API pagination.
        Returns list of dicts: { owner, username, level, subscription_expiry, auto_renew, biography, avatar, banner, flair }
        """
        # Try ABCI subspace query first
        try:
            results = self._list_profiles_via_abci()
            if results:
                logger.info("Fetched %d profiles via ABCI subspace", len(results))
                return results
        except Exception as e:
            logger.debug("ABCI subspace query failed: %s, trying REST API", e)

        # Fall back to REST API
        results = self._list_profiles_via_rest()
        logger.info("Fetched %d profiles via REST API", len(results))
        return results

    def _list_profiles_via_abci(self) -> list[dict]:
        """List profiles via ABCI subspace query."""
        prefix = "profiles/".encode()
        data_hex = prefix.hex()
        path = _up.quote('"/store/core/subspace"')
        resp = self.abci_query(path, f"0x{data_hex}", timeout=HTTP_TIMEOUT_LONG)

        response = ((resp or {}).get("result") or {}).get("response") or {}
        kvs = response.get("kvs") or response.get("Kvs") or []
        results: list[dict] = []

        for kv in kvs:
            key_b64 = kv.get("key")
            val_b64 = kv.get("value")
            if not key_b64 or not val_b64:
                continue
            key_bytes = base64.b64decode(key_b64)
            key_str = key_bytes.decode("utf-8", errors="ignore")
            if not key_str.startswith("profiles/"):
                continue
            owner = key_str.split("/", 1)[1]
            value_json = base64.b64decode(val_b64).decode("utf-8", errors="ignore")
            try:
                prof = json.loads(value_json)
                prof["owner"] = owner
                results.append(prof)
            except Exception:
                continue
        return results

    def _list_profiles_via_rest(self) -> list[dict]:
        """List profiles via REST API with pagination."""
        rest_url = self._derive_rest_url(self.jsonrpc_url)
        profiles: list[dict] = []
        next_key: str | None = None

        while True:
            url = f"{rest_url}/mirage/core/v1/profiles?pagination.limit=5000"
            if next_key:
                url += f"&pagination.key={_up.quote(next_key)}"

            r = requests.get(url, timeout=HTTP_TIMEOUT_LONG)
            r.raise_for_status()
            data = r.json()

            page_profiles = data.get("profiles", [])
            profiles.extend(page_profiles)

            pagination = data.get("pagination") or {}
            next_key = pagination.get("next_key")
            if not next_key:
                break

        return profiles

    def fetch_proposal_messages(self, proposal_id: int, type_url_to_proto: dict) -> list[dict]:
        """Fetch proposal messages via gRPC v1beta1, falling back to REST v1 for multi-message proposals."""
        try:
            return self._fetch_proposal_messages_grpc(proposal_id, type_url_to_proto)
        except RuntimeError as e:
            if "not exactly one" not in str(e):
                raise
            logger.info(
                "Proposal %s has multiple messages — falling back to REST gov/v1",
                proposal_id,
            )
            return self._fetch_proposal_messages_rest(proposal_id, type_url_to_proto)

    def _fetch_proposal_messages_grpc(self, proposal_id: int, type_url_to_proto: dict) -> list[dict]:
        """Fetch proposal via gRPC v1beta1 (single-message proposals only)."""
        try:
            with grpc.insecure_channel(self.grpc_target) as channel:
                stub = gov_query_pb2_grpc.QueryStub(channel)
                req = gov_query_pb2.QueryProposalRequest(proposal_id=proposal_id)
                resp = stub.Proposal(req, timeout=GRPC_TIMEOUT)
                if not resp or not resp.proposal:
                    raise RuntimeError(f"Proposal {proposal_id} not found")

                proposal = resp.proposal
                messages: list[dict] = []

                if hasattr(proposal, "messages") and proposal.messages:
                    for msg_any in proposal.messages:
                        if not msg_any.type_url or not msg_any.value:
                            continue
                        if msg_any.type_url not in type_url_to_proto:
                            continue
                        messages.append(
                            {
                                "type_url": msg_any.type_url,
                                "value": base64.b64encode(msg_any.value).decode("ascii"),
                            }
                        )
                elif hasattr(proposal, "content") and proposal.content:
                    content = proposal.content
                    if content.type_url and content.value:
                        if content.type_url in type_url_to_proto:
                            messages.append(
                                {
                                    "type_url": content.type_url,
                                    "value": base64.b64encode(content.value).decode("ascii"),
                                }
                            )

                if not messages:
                    raise RuntimeError(
                        f"Proposal {proposal_id} has no trackable messages (may contain only governance-only messages like MsgMintTokens or MsgBurnTokens)"
                    )

                return messages
        except Exception as e:
            raise RuntimeError(f"Failed to fetch proposal {proposal_id} messages: {e}") from e

    def _fetch_proposal_messages_rest(self, proposal_id: int, type_url_to_proto: dict) -> list[dict]:
        """Fetch proposal via REST gov/v1 and convert JSON messages to protobuf bytes."""
        from google.protobuf import json_format

        rest_url = self._derive_rest_url(self.jsonrpc_url)
        url = f"{rest_url}/cosmos/gov/v1/proposals/{proposal_id}"
        r = requests.get(url, timeout=HTTP_TIMEOUT_MEDIUM)
        r.raise_for_status()
        data = r.json()

        proposal = data.get("proposal") or {}
        raw_messages = proposal.get("messages") or []
        if not raw_messages:
            raise RuntimeError(
                f"Proposal {proposal_id} has no trackable messages (may contain only governance-only messages like MsgMintTokens or MsgBurnTokens)"
            )

        messages: list[dict] = []
        for msg_json in raw_messages:
            type_url = msg_json.get("@type", "")
            if type_url not in type_url_to_proto:
                continue
            proto_cls = type_url_to_proto[type_url]
            fields = {k: v for k, v in msg_json.items() if k != "@type" and v is not None}
            msg = json_format.ParseDict(fields, proto_cls())
            serialized = msg.SerializeToString()
            messages.append(
                {
                    "type_url": type_url,
                    "value": base64.b64encode(serialized).decode("ascii"),
                }
            )

        if not messages:
            raise RuntimeError(
                f"Proposal {proposal_id} has no trackable messages (may contain only governance-only messages like MsgMintTokens or MsgBurnTokens)"
            )

        logger.info(
            "REST gov/v1 resolved proposal %s: %d message(s)",
            proposal_id,
            len(messages),
        )
        return messages

    @staticmethod
    def parse_header_time(ts_str: str) -> int:
        """Parse block header timestamp to Unix timestamp."""
        if not ts_str:
            raise RuntimeError("Missing timestamp in block header")
        base = ts_str.split(".")[0].rstrip("Z")
        return int(datetime.strptime(base, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp())

    @staticmethod
    def iso_timestamp(ts: int) -> str:
        """Convert Unix timestamp to ISO format."""
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def create_websocket_app(self, on_open, on_message, on_error, on_close):
        """Create WebSocket app."""
        return websocket.WebSocketApp(
            self.ws_url,
            on_open=on_open,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
        )

    @staticmethod
    def run_websocket_forever(ws, running: bool):
        """Run WebSocket forever with ping/pong."""
        ws.run_forever(ping_interval=WS_PING_INTERVAL, ping_timeout=WS_PING_TIMEOUT)

    def wait_for_rpc_ready(self) -> bool:
        """Wait for RPC to be ready."""
        try:
            r = requests.get(f"{self.jsonrpc_url}/status", timeout=HTTP_TIMEOUT_SHORT)
            return r.ok
        except Exception:
            return False

    def get_current_difficulty(self) -> int:
        """Get current PoW difficulty steps via gRPC."""
        info = self.get_difficulty_info()
        return int(info.get("current_difficulty", 0))

    def get_difficulty_info(self) -> dict:
        """Get full PoW difficulty state via gRPC."""
        try:
            from shared.datatypes import QueryDifficultyRequest, QueryDifficultyResponse

            with grpc.insecure_channel(self.grpc_target) as channel:
                method = channel.unary_unary(
                    "/mirage.core.v1.Query/GetDifficulty",
                    request_serializer=QueryDifficultyRequest.SerializeToString,
                    response_deserializer=QueryDifficultyResponse.FromString,
                )
                resp = method(QueryDifficultyRequest(), timeout=GRPC_TIMEOUT)
                return {
                    "current_difficulty": int(resp.current_difficulty),
                    "previous_difficulty": int(resp.previous_difficulty),
                    "last_change_height": int(resp.last_change_height),
                    "pow_message_count": int(resp.pow_message_count) if resp.pow_message_count else 0,
                    "consecutive_low_usage": int(resp.consecutive_low_usage) if resp.consecutive_low_usage else 0,
                    "latest_block_hash": str(resp.latest_block_hash or "").lower(),
                    "current_height": int(resp.current_height),
                }
        except Exception as e:
            logger.error("Failed to query difficulty info: %s", e)
            raise

    def get_total_supply(self) -> int:
        """Get total supply of umirage tokens via gRPC."""
        try:
            from cosmpy.protos.cosmos.bank.v1beta1 import query_pb2 as bank_query_pb2
            from cosmpy.protos.cosmos.bank.v1beta1 import query_pb2_grpc as bank_query_pb2_grpc

            with grpc.insecure_channel(self.grpc_target) as channel:
                stub = bank_query_pb2_grpc.QueryStub(channel)
                req = bank_query_pb2.QuerySupplyOfRequest(denom="umirage")
                resp = stub.SupplyOf(req, timeout=GRPC_TIMEOUT)
                amt = (resp.amount.amount if resp and resp.amount else "0") or "0"
                return int(amt)
        except Exception as e:
            logger.warning("Failed to query total supply: %s", e)
            return 0

    def get_tx_size_cost_per_byte(self) -> int:
        """Get auth param tx_size_cost_per_byte via gRPC."""
        try:
            from cosmpy.protos.cosmos.auth.v1beta1 import query_pb2 as auth_query_pb2
            from cosmpy.protos.cosmos.auth.v1beta1 import query_pb2_grpc as auth_query_pb2_grpc

            with grpc.insecure_channel(self.grpc_target) as channel:
                stub = auth_query_pb2_grpc.QueryStub(channel)
                req = auth_query_pb2.QueryParamsRequest()
                resp = stub.Params(req, timeout=GRPC_TIMEOUT)
                params = getattr(resp, "params", None)
                value = getattr(params, "tx_size_cost_per_byte", 0) if params is not None else 0
                v = int(value or 0)
                return v if v > 0 else 0
        except Exception as e:
            logger.warning("Failed to query tx_size_cost_per_byte: %s", e)
            return 0

    def get_balance(self, address: str) -> int:
        """Get umirage balance for a specific address via gRPC."""
        if not address:
            return 0
        try:
            from cosmpy.protos.cosmos.bank.v1beta1 import query_pb2 as bank_query_pb2
            from cosmpy.protos.cosmos.bank.v1beta1 import query_pb2_grpc as bank_query_pb2_grpc

            with grpc.insecure_channel(self.grpc_target) as channel:
                stub = bank_query_pb2_grpc.QueryStub(channel)
                req = bank_query_pb2.QueryBalanceRequest(address=str(address), denom="umirage")
                resp = stub.Balance(req, timeout=GRPC_TIMEOUT)
                amt = (resp.balance.amount if resp and resp.balance else "0") or "0"
                return int(amt)
        except Exception as e:
            logger.warning("Failed to query balance for %s: %s", address, e)
            return 0
