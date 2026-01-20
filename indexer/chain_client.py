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
from google.protobuf.json_format import MessageToDict
from cosmpy.protos.cosmos.tx.v1beta1.tx_pb2 import TxRaw, TxBody
from cosmpy.protos.cosmos.gov.v1beta1.tx_pb2 import MsgSubmitProposal
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
        for path in ["/block_results", "/block", "/status", "/abci_query", "/tx_search"]:
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
        for path in ["/block_results", "/block", "/status", "/abci_query", "/tx_search"]:
            if path in base_rpc:
                base_rpc = base_rpc.replace(path, "")
        if "://" in base_rpc:
            protocol, rest = base_rpc.split("://", 1)
            if ":" in rest:
                host, _ = rest.rsplit(":", 1)
                return f"http://{host}:1317"
            else:
                return f"http://{rest}:1317"
        else:
            return base_rpc.replace(":26657", ":1317")

    def get_status(self) -> dict:
        """Get chain status."""
        r = requests.get(f"{self.jsonrpc_url}/status", timeout=HTTP_TIMEOUT_SHORT)
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

    def list_profiles_subspace(self) -> list[dict]:
        """
        List all profiles stored in the chain KV.
        Tries ABCI subspace query first, falls back to REST API pagination.
        Returns list of dicts: { owner, username, level, subscription_expiry, auto_renew, is_moderator, biography, avatar, banner }
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
            url = f"{rest_url}/mirage/core/v1/profiles?pagination.limit=500"
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

    def tx_search(self, query: str, page: int = 1, per_page: int = 100, order_by: str = "asc") -> dict:
        """Search transactions."""
        base_rpc = self._strip_rpc_paths(self.jsonrpc_url)
        tx_search_url = f"{base_rpc}/tx_search"
        r = requests.get(
            tx_search_url,
            params={"query": query, "page": str(page), "per_page": str(per_page), "order_by": order_by},
            timeout=HTTP_TIMEOUT_LONG,
        )
        r.raise_for_status()
        return r.json()

    @staticmethod
    def _strip_rpc_paths(url: str, paths: list[str] | None = None) -> str:
        """Strip RPC endpoint paths from URL."""
        if paths is None:
            paths = ["/block_results", "/block", "/status", "/abci_query", "/tx_search"]
        base = url
        for path in paths:
            if path in base:
                base = base.replace(path, "")
        return base

    def fetch_proposal_messages(self, proposal_id: int, type_url_to_proto: dict) -> list[dict]:
        """Fetch proposal messages from gRPC, handling both v1beta1 (content) and v1 (messages) formats."""
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
                        f"Proposal {proposal_id} has no trackable messages (may contain only governance-only messages like MsgMintTo)"
                    )

                return messages
        except Exception as e:
            raise RuntimeError(f"Failed to fetch proposal {proposal_id} messages: {e}") from e

    def fetch_submit_proposal_messages_via_tx_search(
        self, proposal_id: int, decode_events_fn, extract_proposal_id_fn, extract_inner_messages_fn
    ) -> list[dict]:
        """
        Resolve proposal messages by searching the Tendermint RPC for the submit tx.
        This avoids REST/ABCI dependencies and works during catch-up when cache is missing.
        """
        base_rpc = self._strip_rpc_paths(self.jsonrpc_url)
        tx_search_url = f"{base_rpc}/tx_search"

        queries = [
            f"proposal_id='{proposal_id}'",
            f"proposal_id={proposal_id}",
            f"submit_proposal.proposal_id='{proposal_id}'",
            f"submit_proposal.proposal_id={proposal_id}",
            f"cosmos.gov.v1.EventSubmitProposal.proposal_id='{proposal_id}'",
            f"cosmos.gov.v1.EventSubmitProposal.proposal_id={proposal_id}",
            f"cosmos.gov.v1beta1.EventSubmitProposal.proposal_id='{proposal_id}'",
            f"cosmos.gov.v1beta1.EventSubmitProposal.proposal_id={proposal_id}",
            "message.action='/cosmos.gov.v1.MsgSubmitProposal'",
            "message.action='/cosmos.gov.v1beta1.MsgSubmitProposal'",
            "message.action='submit_proposal'",
        ]

        max_pages = 10
        for q in queries:
            pages_to_search = max_pages if "message.action=" in q else 1
            for page in range(1, pages_to_search + 1):
                try:
                    resp = requests.get(
                        tx_search_url,
                        params={"query": q, "page": str(page), "per_page": "100", "order_by": "asc"},
                        timeout=HTTP_TIMEOUT_LONG,
                    )
                    if resp.status_code != 200:
                        continue
                    data = resp.json()
                    if not data:
                        continue
                    result_obj = data.get("result")
                    if not result_obj:
                        continue
                    txs = result_obj.get("txs", [])
                    if not txs:
                        continue

                    for tx_entry in txs:
                        if "message.action=" in q or "message.action" in q:
                            tx_result = tx_entry.get("tx_result")
                            if not tx_result:
                                continue
                            events = tx_result.get("events", [])
                            found_match = False
                            try:
                                for ev_type, attrs in decode_events_fn(events):
                                    pid = extract_proposal_id_fn(attrs)
                                    if pid is not None and pid == proposal_id:
                                        found_match = True
                                        break
                                if not found_match:
                                    continue
                            except Exception:
                                continue

                        tx_b64 = tx_entry.get("tx")
                        if not tx_b64:
                            continue
                        raw_tx_bytes = base64.b64decode(tx_b64)
                        tx_raw = TxRaw()
                        tx_raw.ParseFromString(raw_tx_bytes)
                        tx_body = TxBody()
                        tx_body.ParseFromString(tx_raw.body_bytes)

                        for any_msg in tx_body.messages:
                            if any_msg.type_url in (
                                "/cosmos.gov.v1beta1.MsgSubmitProposal",
                                "/cosmos.gov.v1.MsgSubmitProposal",
                            ):
                                parsed = MsgSubmitProposal()
                                parsed.ParseFromString(any_msg.value)
                                inner_msgs = extract_inner_messages_fn(parsed)
                                messages: list[dict] = []
                                for inner in inner_msgs:
                                    if not inner.type_url:
                                        raise RuntimeError("Inner message missing type_url in tx_search result")
                                    if not inner.value:
                                        raise RuntimeError("Inner message missing value in tx_search result")
                                    messages.append(
                                        {
                                            "type_url": inner.type_url,
                                            "value": base64.b64encode(inner.value).decode("ascii"),
                                        }
                                    )
                                if messages:
                                    return messages
                except Exception:
                    continue

        raise RuntimeError(f"Submit tx not found for proposal {proposal_id}")

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
        """Get current PoW difficulty via gRPC."""
        info = self.get_difficulty_info()
        return info.get("difficulty", 10)

    def get_difficulty_info(self) -> dict:
        """Get current PoW difficulty and message count via gRPC."""
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
                    "difficulty": int(resp.current_difficulty) if resp.current_difficulty else 10,
                    "msg_count": int(resp.pow_message_count) if resp.pow_message_count else 0,
                }
        except Exception as e:
            logger.warning("Failed to query difficulty info: %s", e)
            return {"difficulty": 10, "msg_count": 0}

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
