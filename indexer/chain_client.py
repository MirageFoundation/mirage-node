"""
Chain client for HTTP, gRPC, and WebSocket operations.
"""

import base64
import logging
import time
import requests
import websocket
import grpc
from datetime import datetime, timezone
from typing import Optional
from indexer.settings import (
    BALANCE_BATCH_DEADLINE,
    HTTP_TIMEOUT_SHORT,
    HTTP_TIMEOUT_MEDIUM,
    GRPC_TIMEOUT,
    WS_PING_INTERVAL,
    WS_PING_TIMEOUT,
    WS_RECONNECT_DELAY,
)

logger = logging.getLogger(__name__)

# Messages the indexer is responsible for projecting. Anything outside this prefix
# belongs to cosmos modules and is deliberately not indexed.
CORE_TYPE_URL_PREFIX = "/mirage.core.v1."

# Profile listing pages are far larger than a normal point query, so they get
# their own (longer) budget instead of the 3s GRPC_TIMEOUT.
# The chain caps a page at keeper.MaxProfilesQueryLimit (100); asking for more
# is silently clamped server-side.
PROFILES_PAGE_LIMIT = 100
PROFILES_PAGE_TIMEOUT = 30
PROFILES_SYNC_DEADLINE = 120.0
STAKING_PAGE_LIMIT = 100
STAKING_MAX_PAGES = 100

# Delay between block_results polls when waiting for the expected tx count.
BLOCK_RESULTS_RETRY_DELAY = 0.25


class ChainClient:
    """Handles all chain communication (HTTP, gRPC, WebSocket)."""

    def __init__(self, jsonrpc_url: str):
        self.jsonrpc_url = jsonrpc_url
        self.ws_url = jsonrpc_url.replace("http://", "ws://") + "/websocket"
        self.grpc_target = self._derive_grpc_target(jsonrpc_url)
        self._profile_cache: dict[str, Optional[dict]] | None = None

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
        raw = (((data or {}).get("result") or {}).get("sync_info") or {}).get("earliest_block_height")
        if raw is None:
            raise RuntimeError("/status is missing sync_info.earliest_block_height")
        try:
            earliest = int(raw)
        except (TypeError, ValueError) as e:
            raise RuntimeError(f"/status returned unparseable earliest_block_height {raw!r}") from e
        logger.debug("get_earliest_height earliest=%d", earliest)
        return earliest

    def get_chain_id(self) -> str:
        """Return node_info.network from /status. Fails hard if missing."""
        data = self.get_status()
        network = (((data or {}).get("result") or {}).get("node_info") or {}).get("network")
        if not network:
            raise RuntimeError("/status is missing node_info.network")
        logger.debug("get_chain_id chain_id=%s", network)
        return str(network)

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

    def get_block_results_matching(self, height: int, expected_tx_count: int, deadline_s: float = 15.0) -> dict:
        """
        Get block results for `height`, retrying until the node reports exactly
        `expected_tx_count` tx results. Guards against a node that has committed
        the block but not yet exposed complete results.
        """
        expected = int(expected_tx_count)
        started = time.monotonic()
        deadline = started + float(deadline_s)
        attempt = 0
        got: int | None = None

        while True:
            attempt += 1
            data = self.get_block_results(height)
            txs = ((data or {}).get("result") or {}).get("txs_results")
            if txs is None:
                # A missing list is only equivalent to "no txs" when none are expected.
                if expected == 0:
                    logger.debug(
                        "get_block_results_matching height=%s expected=0 txs_results=null attempt=%d matched",
                        height,
                        attempt,
                    )
                    return data
                got = None
            else:
                got = len(txs)
                if got == expected:
                    logger.debug(
                        "get_block_results_matching height=%s expected=%d attempt=%d matched",
                        height,
                        expected,
                        attempt,
                    )
                    return data

            elapsed = time.monotonic() - started
            if elapsed >= float(deadline_s):
                raise RuntimeError(
                    f"block_results for height {height} never reached expected tx count: "
                    f"expected={expected} got={'missing' if got is None else got} "
                    f"attempts={attempt} elapsed={elapsed:.2f}s"
                )
            logger.debug(
                "get_block_results_matching height=%s expected=%d got=%s attempt=%d elapsed=%.2fs retrying",
                height,
                expected,
                "missing" if got is None else got,
                attempt,
                elapsed,
            )
            time.sleep(min(BLOCK_RESULTS_RETRY_DELAY, max(0.0, deadline - time.monotonic())))

    def abci_query(self, path: str, data: str, timeout: int = HTTP_TIMEOUT_SHORT) -> dict:
        """Perform ABCI query."""
        r = requests.get(
            f"{self.jsonrpc_url}/abci_query",
            params={"path": path, "data": data},
            timeout=timeout,
        )
        r.raise_for_status()
        return r.json()

    def begin_block_profile_cache(self) -> None:
        """Memoise profile reads for the duration of one block.

        These reads happen inside the block's PostgreSQL transaction, so each one
        holds row locks for up to GRPC_TIMEOUT. A block packed with profile-mutating
        transactions from the same accounts would otherwise pay that cost once per
        transaction. Every read returns chain HEAD regardless of which height is being
        projected, so collapsing repeats within a block returns the same answer the
        second call would have given, without the node advancing underneath it.
        """
        self._profile_cache: dict[str, Optional[dict]] | None = {}

    def end_block_profile_cache(self) -> None:
        """Drop the per-block memo so the next block reads fresh chain state."""
        self._profile_cache = None

    def query_profile_full(self, addr: str, timeout: int = GRPC_TIMEOUT) -> Optional[dict]:
        """Query full profile (including per-entry lists) via gRPC.

        Returns None when the chain has no profile for `addr`. That is a normal
        post-consensus state, not a failure: the block being projected can
        predate a `MsgDeleteUser`, so by the time the indexer reads chain state
        the profile is already gone. Callers skip the refresh in that case.

        Only NOT_FOUND maps to None. Every other status still raises, so a real
        node or transport failure keeps aborting the block instead of being
        silently recorded as "user has nothing".
        """
        from shared.datatypes import QueryProfileRequest, QueryProfileResponse

        key = str(addr).lower()
        if self._profile_cache is not None and key in self._profile_cache:
            return self._profile_cache[key]

        with grpc.insecure_channel(self.grpc_target) as channel:
            method = channel.unary_unary(
                "/mirage.core.v1.Query/GetProfile",
                request_serializer=QueryProfileRequest.SerializeToString,
                response_deserializer=QueryProfileResponse.FromString,
            )
            try:
                resp = method(QueryProfileRequest(address=key), timeout=timeout)
            except grpc.RpcError as e:
                if e.code() == grpc.StatusCode.NOT_FOUND:
                    logger.warning("profile_absent grpc addr=%s (no chain profile; account deleted)", addr)
                    if self._profile_cache is not None:
                        self._profile_cache[key] = None
                    return None
                raise

        profile = self._profile_to_dict(resp)
        if self._profile_cache is not None:
            self._profile_cache[key] = profile
        logger.debug(
            "query_profile_full grpc addr=%s agents=%d users=%d topics=%d",
            addr,
            len(profile["enabled_agents"]),
            len(profile["followed_users"]),
            len(profile["followed_topics"]),
        )
        return profile

    @staticmethod
    def _profile_to_dict(resp) -> dict:
        """Convert a mirage.core.v1.QueryProfileResponse message to a plain dict."""
        return {
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

    def list_profiles_paginated(self) -> list[dict]:
        """
        List every profile via /mirage.core.v1.Query/GetProfiles, walking the
        pagination cursor until it is exhausted. Returns dicts with the same
        shape as query_profile_full.
        """
        from shared.datatypes import QueryProfilesRequest, QueryProfilesResponse

        started = time.monotonic()
        deadline = started + PROFILES_SYNC_DEADLINE
        results: list[dict] = []
        seen: set[str] = set()
        next_key = b""
        page = 0

        with grpc.insecure_channel(self.grpc_target) as channel:
            method = channel.unary_unary(
                "/mirage.core.v1.Query/GetProfiles",
                request_serializer=QueryProfilesRequest.SerializeToString,
                response_deserializer=QueryProfilesResponse.FromString,
            )
            while True:
                if time.monotonic() >= deadline:
                    raise RuntimeError(
                        f"GetProfiles pagination exceeded {PROFILES_SYNC_DEADLINE}s "
                        f"after {page} page(s) / {len(results)} profile(s)"
                    )

                req = QueryProfilesRequest()
                req.pagination.key = next_key
                req.pagination.limit = PROFILES_PAGE_LIMIT
                try:
                    resp = method(req, timeout=PROFILES_PAGE_TIMEOUT)
                except grpc.RpcError as e:
                    raise RuntimeError(f"GetProfiles gRPC failed on page {page + 1}: {e}") from e

                page += 1
                page_new = 0
                for prof in resp.profiles:
                    owner = str(prof.owner).strip().lower()
                    if not owner:
                        raise RuntimeError(f"GetProfiles page {page} returned a profile with an empty owner")
                    if owner in seen:
                        continue
                    seen.add(owner)
                    results.append(self._profile_to_dict(prof))
                    page_new += 1

                next_key = bytes(resp.pagination.next_key)
                logger.debug(
                    "list_profiles_paginated page=%d returned=%d new=%d total=%d next_key=%s",
                    page,
                    len(resp.profiles),
                    page_new,
                    len(results),
                    next_key.hex() or "<end>",
                )
                if not next_key:
                    break

        logger.info(
            "Fetched %d profiles via gRPC GetProfiles in %d page(s) (%.1fs)",
            len(results),
            page,
            time.monotonic() - started,
        )
        return results

    def list_profiles_subspace(self) -> list[dict]:
        """Alias for list_profiles_paginated."""
        return self.list_profiles_paginated()

    def fetch_proposal_messages(self, proposal_id: int, type_url_to_proto: dict) -> list[dict]:
        """Fetch proposal messages via cosmos.gov.v1.Query/Proposal gRPC."""
        from cosmpy.protos.cosmos.gov.v1 import query_pb2 as gov_query_pb2
        from cosmpy.protos.cosmos.gov.v1 import query_pb2_grpc as gov_query_pb2_grpc

        try:
            with grpc.insecure_channel(self.grpc_target) as channel:
                stub = gov_query_pb2_grpc.QueryStub(channel)
                resp = stub.Proposal(
                    gov_query_pb2.QueryProposalRequest(proposal_id=int(proposal_id)),
                    timeout=GRPC_TIMEOUT,
                )
        except grpc.RpcError as e:
            raise RuntimeError(f"gov v1 Query/Proposal failed for proposal {proposal_id}: {e}") from e

        raw_messages = list(resp.proposal.messages)
        messages = self._filter_trackable_anys(raw_messages, type_url_to_proto)
        logger.debug(
            "fetch_proposal_messages proposal_id=%s messages=%d trackable=%d",
            proposal_id,
            len(raw_messages),
            len(messages),
        )

        if not raw_messages:
            # v1 proposals wrapping a legacy v1beta1 content are exposed with an
            # empty messages list; the content Any is only visible on v1beta1.
            messages = self._fetch_legacy_proposal_content(proposal_id, type_url_to_proto)

        if not messages:
            raise RuntimeError(
                f"Proposal {proposal_id} has no trackable messages (may contain only governance-only messages like MsgMintTokens or MsgBurnTokens)"
            )

        logger.info("gov v1 gRPC resolved proposal %s: %d message(s)", proposal_id, len(messages))
        return messages

    def _fetch_legacy_proposal_content(self, proposal_id: int, type_url_to_proto: dict) -> list[dict]:
        """Fetch the legacy content Any via cosmos.gov.v1beta1.Query/Proposal gRPC."""
        from cosmpy.protos.cosmos.gov.v1beta1 import query_pb2 as gov_beta_query_pb2
        from cosmpy.protos.cosmos.gov.v1beta1 import query_pb2_grpc as gov_beta_query_pb2_grpc

        try:
            with grpc.insecure_channel(self.grpc_target) as channel:
                stub = gov_beta_query_pb2_grpc.QueryStub(channel)
                resp = stub.Proposal(
                    gov_beta_query_pb2.QueryProposalRequest(proposal_id=int(proposal_id)),
                    timeout=GRPC_TIMEOUT,
                )
        except grpc.RpcError as e:
            raise RuntimeError(f"gov v1beta1 Query/Proposal failed for proposal {proposal_id}: {e}") from e

        content = resp.proposal.content
        raw_messages = [content] if content.type_url else []
        messages = self._filter_trackable_anys(raw_messages, type_url_to_proto)
        logger.debug(
            "fetch_proposal_messages v1beta1 proposal_id=%s messages=%d trackable=%d",
            proposal_id,
            len(raw_messages),
            len(messages),
        )
        return messages

    @staticmethod
    def _filter_trackable_anys(anys, type_url_to_proto: dict) -> list[dict]:
        """Keep only the Anys the indexer knows how to decode, as base64 payloads.

        A core message that is not in the map would be dropped here while the block
        still advanced its checkpoint, recording a governance action as applied when
        it was never projected. Since the map is maintained by hand and the dispatcher
        it has to mirror is a separate if/elif chain, that drift is caught here rather
        than trusted: an untracked core message is fatal.

        Everything else — cosmos gov, upgrade, bank — is deliberately not the indexer's
        business, which is the same rule _process_tx applies to ordinary transactions.
        """
        untracked = sorted(
            {
                any_msg.type_url
                for any_msg in anys
                if any_msg.type_url.startswith(CORE_TYPE_URL_PREFIX) and any_msg.type_url not in type_url_to_proto
            }
        )
        if untracked:
            raise RuntimeError(f"proposal carries core message type(s) the indexer cannot project: {untracked}")

        return [
            {
                "type_url": any_msg.type_url,
                "value": base64.b64encode(any_msg.value).decode("ascii"),
            }
            for any_msg in anys
            if any_msg.type_url in type_url_to_proto
        ]

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
        from cosmpy.protos.cosmos.bank.v1beta1 import query_pb2 as bank_query_pb2
        from cosmpy.protos.cosmos.bank.v1beta1 import query_pb2_grpc as bank_query_pb2_grpc

        try:
            with grpc.insecure_channel(self.grpc_target) as channel:
                stub = bank_query_pb2_grpc.QueryStub(channel)
                req = bank_query_pb2.QuerySupplyOfRequest(denom="umirage")
                resp = stub.SupplyOf(req, timeout=GRPC_TIMEOUT)
                amt = resp.amount.amount or "0"
                supply = int(amt)
        except Exception as e:
            raise RuntimeError(f"Failed to query total supply of umirage: {e}") from e
        logger.debug("get_total_supply supply=%d", supply)
        return supply

    def get_tx_size_cost_per_byte(self) -> int:
        """Get auth param tx_size_cost_per_byte via gRPC."""
        from cosmpy.protos.cosmos.auth.v1beta1 import query_pb2 as auth_query_pb2
        from cosmpy.protos.cosmos.auth.v1beta1 import query_pb2_grpc as auth_query_pb2_grpc

        try:
            with grpc.insecure_channel(self.grpc_target) as channel:
                stub = auth_query_pb2_grpc.QueryStub(channel)
                req = auth_query_pb2.QueryParamsRequest()
                resp = stub.Params(req, timeout=GRPC_TIMEOUT)
                value = int(resp.params.tx_size_cost_per_byte)
        except Exception as e:
            raise RuntimeError(f"Failed to query auth param tx_size_cost_per_byte: {e}") from e
        logger.debug("get_tx_size_cost_per_byte value=%d", value)
        return value

    def get_balance(self, address: str) -> int:
        """Get umirage balance for a specific address via gRPC."""
        if not address:
            raise RuntimeError("get_balance requires a non-empty address")

        from cosmpy.protos.cosmos.bank.v1beta1 import query_pb2 as bank_query_pb2
        from cosmpy.protos.cosmos.bank.v1beta1 import query_pb2_grpc as bank_query_pb2_grpc

        try:
            with grpc.insecure_channel(self.grpc_target) as channel:
                stub = bank_query_pb2_grpc.QueryStub(channel)
                req = bank_query_pb2.QueryBalanceRequest(address=str(address), denom="umirage")
                resp = stub.Balance(req, timeout=GRPC_TIMEOUT)
                balance = int(resp.balance.amount or "0")
        except Exception as e:
            raise RuntimeError(f"Failed to query umirage balance for {address}: {e}") from e
        logger.debug("get_balance address=%s balance=%d", address, balance)
        return balance

    def get_staked_balance(self, address: str) -> int:
        """Get delegated plus unbonding umirage for a delegator via gRPC."""
        if not address:
            raise RuntimeError("get_staked_balance requires a non-empty address")

        from cosmpy.protos.cosmos.base.query.v1beta1.pagination_pb2 import PageRequest
        from cosmpy.protos.cosmos.staking.v1beta1 import query_pb2 as staking_query_pb2
        from cosmpy.protos.cosmos.staking.v1beta1 import query_pb2_grpc as staking_query_pb2_grpc

        try:
            with grpc.insecure_channel(self.grpc_target) as channel:
                stub = staking_query_pb2_grpc.QueryStub(channel)
                total = 0
                next_key = b""
                for _ in range(STAKING_MAX_PAGES):
                    req = staking_query_pb2.QueryDelegatorDelegationsRequest(
                        delegator_addr=str(address),
                        pagination=PageRequest(key=next_key, limit=STAKING_PAGE_LIMIT),
                    )
                    resp = stub.DelegatorDelegations(req, timeout=GRPC_TIMEOUT)
                    for delegation in resp.delegation_responses:
                        if delegation.balance.denom != "umirage":
                            raise RuntimeError(f"unexpected staking denom {delegation.balance.denom!r}")
                        total += int(delegation.balance.amount or "0")
                    next_key = bytes(resp.pagination.next_key)
                    if not next_key:
                        break
                else:
                    raise RuntimeError(f"delegations exceeded {STAKING_MAX_PAGES} pages")

                next_key = b""
                for _ in range(STAKING_MAX_PAGES):
                    req = staking_query_pb2.QueryDelegatorUnbondingDelegationsRequest(
                        delegator_addr=str(address),
                        pagination=PageRequest(key=next_key, limit=STAKING_PAGE_LIMIT),
                    )
                    resp = stub.DelegatorUnbondingDelegations(req, timeout=GRPC_TIMEOUT)
                    total += sum(
                        int(entry.balance or "0")
                        for unbonding in resp.unbonding_responses
                        for entry in unbonding.entries
                    )
                    next_key = bytes(resp.pagination.next_key)
                    if not next_key:
                        break
                else:
                    raise RuntimeError(f"unbonding delegations exceeded {STAKING_MAX_PAGES} pages")
        except Exception as e:
            raise RuntimeError(f"Failed to query staked umirage for {address}: {e}") from e

        logger.debug("get_staked_balance address=%s balance=%d", address, total)
        return total

    def get_balances_batch(self, addresses: list[str], timeout: float | None = None) -> dict[str, int]:
        """
        Get umirage balances for many addresses over a single gRPC channel.
        Any failure raises — callers must never persist a zero they did not read.
        """
        from cosmpy.protos.cosmos.bank.v1beta1 import query_pb2 as bank_query_pb2
        from cosmpy.protos.cosmos.bank.v1beta1 import query_pb2_grpc as bank_query_pb2_grpc

        per_call_timeout = GRPC_TIMEOUT if timeout is None else float(timeout)
        balances: dict[str, int] = {}

        # Per-call timeouts bound each request but not the batch, so a block touching
        # many distinct addresses had no overall budget: N addresses could stall the
        # indexer for N * per_call_timeout. The deadline below is what the caller
        # actually waits on, and exceeding it raises rather than returning a partial
        # map, because a balance the indexer did not read must never be persisted.
        deadline = time.monotonic() + BALANCE_BATCH_DEADLINE

        with grpc.insecure_channel(self.grpc_target) as channel:
            stub = bank_query_pb2_grpc.QueryStub(channel)
            for address in addresses:
                if not address:
                    raise RuntimeError("get_balances_batch received an empty address")
                key = str(address).lower()
                if key in balances:
                    continue
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RuntimeError(
                        f"get_balances_batch exceeded its {BALANCE_BATCH_DEADLINE}s budget after "
                        f"{len(balances)} of {len(addresses)} address(es)"
                    )
                try:
                    req = bank_query_pb2.QueryBalanceRequest(address=str(address), denom="umirage")
                    resp = stub.Balance(req, timeout=min(per_call_timeout, remaining))
                    balances[key] = int(resp.balance.amount or "0")
                except Exception as e:
                    raise RuntimeError(f"Failed to query umirage balance for {address}: {e}") from e

        logger.debug("get_balances_batch requested=%d resolved=%d", len(addresses), len(balances))
        return balances
