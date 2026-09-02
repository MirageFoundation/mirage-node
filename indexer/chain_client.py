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

# Core messages governance can execute that move no state the indexer projects.
# Mint/burn change balances and supply, which are re-read from the block's bank
# events and the supply sample; punish changes validator state, which is re-read
# from the validator sample. They have no decoder because there is nothing to
# decode them for — so they must be excluded from the untracked-is-fatal check
# below, which otherwise makes any proposal carrying one permanently
# unprojectable and crash-loops the indexer on that block.
GOVERNANCE_ONLY_TYPE_URLS = frozenset(
    {
        f"{CORE_TYPE_URL_PREFIX}MsgMintTokens",
        f"{CORE_TYPE_URL_PREFIX}MsgBurnTokens",
        f"{CORE_TYPE_URL_PREFIX}MsgPunishValidator",
    }
)

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
            "query_profile_full grpc addr=%s users=%d communities=%d",
            addr,
            len(profile["followed_users"]),
            len(profile["joined_communities"]),
        )
        return profile

    def query_curation_team(self, community: str, team_id: int, timeout: int = GRPC_TIMEOUT) -> dict:
        """Read one committed curator team. Missing or malformed state is fatal."""
        from shared.datatypes import QueryCurationTeamRequest, QueryCurationTeamResponse

        slug = str(community).strip().lower()
        if not slug or int(team_id) <= 0:
            raise RuntimeError("query_curation_team requires community and positive team_id")
        with grpc.insecure_channel(self.grpc_target) as channel:
            method = channel.unary_unary(
                "/mirage.core.v1.Query/CurationTeam",
                request_serializer=QueryCurationTeamRequest.SerializeToString,
                response_deserializer=QueryCurationTeamResponse.FromString,
            )
            try:
                resp = method(QueryCurationTeamRequest(community=slug, team_id=int(team_id)), timeout=timeout)
            except grpc.RpcError as e:
                raise RuntimeError(f"CurationTeam gRPC failed for {slug}/{team_id}: {e}") from e
        team = resp.team
        if str(team.community).strip().lower() != slug or int(team.team_id) != int(team_id):
            raise RuntimeError(f"CurationTeam returned the wrong team for {slug}/{team_id}")
        result = {
            "community": slug,
            "team_id": int(team.team_id),
            "owner": str(team.owner).strip().lower(),
            "name": str(team.name),
            "description": str(team.description),
            "subscriber_only": bool(team.subscriber_only),
            "tag": str(team.tag),
            "subscriber_count": int(team.subscriber_count),
            "created_height": int(team.created_height),
            "created_order": int(team.created_order),
            "deleted_height": int(team.deleted_height),
        }
        if not result["owner"] or not result["name"] or result["created_order"] <= 0:
            raise RuntimeError(f"CurationTeam returned incomplete state for {slug}/{team_id}")
        logger.debug(
            "[curation] team grpc community=%s team_id=%s deleted_height=%s subscribers=%s",
            slug,
            team_id,
            result["deleted_height"],
            result["subscriber_count"],
        )
        return result

    def query_curation_team_members(
        self, community: str, team_id: int, timeout: int = GRPC_TIMEOUT
    ) -> list[dict]:
        """Read the complete accepted roster for a team."""
        from shared.datatypes import QueryCurationTeamMembersRequest, QueryCurationTeamMembersResponse

        slug = str(community).strip().lower()
        next_key = b""
        members: list[dict] = []
        seen: set[str] = set()
        with grpc.insecure_channel(self.grpc_target) as channel:
            method = channel.unary_unary(
                "/mirage.core.v1.Query/CurationTeamMembers",
                request_serializer=QueryCurationTeamMembersRequest.SerializeToString,
                response_deserializer=QueryCurationTeamMembersResponse.FromString,
            )
            for page in range(100):
                req = QueryCurationTeamMembersRequest(community=slug, team_id=int(team_id))
                req.pagination.key = next_key
                req.pagination.limit = 100
                try:
                    resp = method(req, timeout=timeout)
                except grpc.RpcError as e:
                    raise RuntimeError(f"CurationTeamMembers gRPC failed for {slug}/{team_id}: {e}") from e
                for member in resp.members:
                    address = str(member.address).strip().lower()
                    order = int(member.accepted_order)
                    if not address or order <= 0:
                        raise RuntimeError(f"CurationTeamMembers returned malformed member for {slug}/{team_id}")
                    if address in seen:
                        raise RuntimeError(f"CurationTeamMembers returned duplicate {address} for {slug}/{team_id}")
                    seen.add(address)
                    members.append({"address": address, "accepted_order": order})
                next_key = bytes(resp.pagination.next_key)
                if not next_key:
                    break
            else:
                raise RuntimeError(f"CurationTeamMembers exceeded 100 pages for {slug}/{team_id}")
        logger.debug("[curation] members grpc community=%s team_id=%s count=%s", slug, team_id, len(members))
        return members

    def list_all_curation_teams(
        self, *, include_deleted: bool = True, timeout: int = PROFILES_PAGE_TIMEOUT
    ) -> list[dict]:
        """Read every team for indexer startup/backfill."""
        from shared.datatypes import QueryAllCurationTeamsRequest, QueryAllCurationTeamsResponse

        next_key = b""
        teams: list[dict] = []
        seen: set[tuple[str, int]] = set()
        with grpc.insecure_channel(self.grpc_target) as channel:
            method = channel.unary_unary(
                "/mirage.core.v1.Query/AllCurationTeams",
                request_serializer=QueryAllCurationTeamsRequest.SerializeToString,
                response_deserializer=QueryAllCurationTeamsResponse.FromString,
            )
            for page in range(10000):
                req = QueryAllCurationTeamsRequest(include_deleted=bool(include_deleted))
                req.pagination.key = next_key
                req.pagination.limit = 100
                try:
                    resp = method(req, timeout=timeout)
                except grpc.RpcError as e:
                    raise RuntimeError(f"AllCurationTeams gRPC failed on page {page + 1}: {e}") from e
                for team in resp.teams:
                    community = str(team.community).strip().lower()
                    team_id = int(team.team_id)
                    key = (community, team_id)
                    if not community or team_id <= 0 or key in seen:
                        raise RuntimeError(f"AllCurationTeams returned malformed/duplicate team {key}")
                    seen.add(key)
                    teams.append(
                        {
                            "community": community,
                            "team_id": team_id,
                            "owner": str(team.owner).strip().lower(),
                            "name": str(team.name),
                            "description": str(team.description),
                            "subscriber_only": bool(team.subscriber_only),
                            "tag": str(team.tag),
                            "subscriber_count": int(team.subscriber_count),
                            "created_height": int(team.created_height),
                            "created_order": int(team.created_order),
                            "deleted_height": int(team.deleted_height),
                        }
                    )
                next_key = bytes(resp.pagination.next_key)
                if not next_key:
                    break
            else:
                raise RuntimeError("AllCurationTeams exceeded 10000 pages")
        logger.info("[curation] fetched %d teams via AllCurationTeams", len(teams))
        return teams

    def query_community_preference(
        self, owner: str, community: str, timeout: int = GRPC_TIMEOUT
    ) -> dict:
        """Read stored and effective preference state from the committed chain."""
        from shared.datatypes import QueryCommunityPreferenceRequest, QueryCommunityPreferenceResponse

        address = str(owner).strip().lower()
        slug = str(community).strip().lower()
        if not address or not slug:
            raise RuntimeError("query_community_preference requires owner and community")
        with grpc.insecure_channel(self.grpc_target) as channel:
            method = channel.unary_unary(
                "/mirage.core.v1.Query/CommunityPreference",
                request_serializer=QueryCommunityPreferenceRequest.SerializeToString,
                response_deserializer=QueryCommunityPreferenceResponse.FromString,
            )
            try:
                resp = method(QueryCommunityPreferenceRequest(owner=address, community=slug), timeout=timeout)
            except grpc.RpcError as e:
                if e.code() == grpc.StatusCode.NOT_FOUND:
                    return {"joined": False}
                raise RuntimeError(f"CommunityPreference gRPC failed for {address}/{slug}: {e}") from e
        mode = int(resp.stored.mode)
        pinned_team_id = int(resp.stored.pinned_team_id)
        if mode not in (0, 1, 2) or (mode == 1) != (pinned_team_id > 0):
            raise RuntimeError(f"CommunityPreference returned malformed state for {address}/{slug}")
        return {
            "joined": True,
            "mode": mode,
            "pinned_team_id": pinned_team_id if mode == 1 else None,
            "effective_mode": int(resp.effective_mode),
            "effective_team_id": int(resp.effective_team_id),
        }

    def query_post_metadata(self, txhash: str, timeout: int = GRPC_TIMEOUT) -> dict:
        """Read required protocol-1 post metadata."""
        from shared.datatypes import QueryPostMetadataRequest, QueryPostMetadataResponse

        target = str(txhash).strip().lower()
        if len(target) != 64:
            raise RuntimeError("query_post_metadata requires a 64-character tx hash")
        with grpc.insecure_channel(self.grpc_target) as channel:
            method = channel.unary_unary(
                "/mirage.core.v1.Query/PostMetadata",
                request_serializer=QueryPostMetadataRequest.SerializeToString,
                response_deserializer=QueryPostMetadataResponse.FromString,
            )
            try:
                resp = method(QueryPostMetadataRequest(txhash=target), timeout=timeout)
            except grpc.RpcError as e:
                raise RuntimeError(f"PostMetadata gRPC failed for {target}: {e}") from e
        metadata = resp.metadata
        result = {
            "author": str(metadata.author).strip().lower(),
            "parent_hash": str(metadata.parent_hash).strip().lower(),
            "root_hash": str(metadata.root_hash).strip().lower(),
            "community": str(metadata.community).strip().lower(),
            "global_sequence": int(metadata.global_sequence),
            "created_height": int(metadata.created_height),
            "created_epoch": int(metadata.created_epoch),
            "was_subscriber_at_creation": bool(metadata.was_subscriber_at_creation),
            "deleted_height": int(metadata.deleted_height),
            "deleted_epoch": int(metadata.deleted_epoch),
        }
        if (
            not result["author"]
            or len(result["root_hash"]) != 64
            or not result["community"]
            or result["global_sequence"] <= 0
            or result["created_height"] <= 0
        ):
            raise RuntimeError(f"PostMetadata returned incomplete state for {target}")
        logger.debug(
            "[curation] post metadata grpc tx=%s sequence=%s community=%s was_subscriber=%s",
            target[:12],
            result["global_sequence"],
            result["community"],
            result["was_subscriber_at_creation"],
        )
        return result

    def query_creator_epoch(self, epoch_id: int, timeout: int = GRPC_TIMEOUT) -> dict | None:
        """Read one creator epoch, returning None only when it does not exist."""
        from shared.datatypes import QueryCreatorEpochRequest, QueryCreatorEpochResponse

        epoch = int(epoch_id)
        with grpc.insecure_channel(self.grpc_target) as channel:
            method = channel.unary_unary(
                "/mirage.core.v1.Query/CreatorEpoch",
                request_serializer=QueryCreatorEpochRequest.SerializeToString,
                response_deserializer=QueryCreatorEpochResponse.FromString,
            )
            try:
                resp = method(QueryCreatorEpochRequest(epoch_id=epoch), timeout=timeout)
            except grpc.RpcError as e:
                if e.code() == grpc.StatusCode.NOT_FOUND:
                    return None
                raise RuntimeError(f"CreatorEpoch gRPC failed for {epoch}: {e}") from e
        value = resp.epoch
        return {
            "epoch_id": int(value.epoch_id),
            "pool": str(value.pool),
            "status": int(value.status),
            "phase": int(value.phase),
            "gross_records": int(value.gross_records),
            "active_engagers": int(value.active_engagers),
            "engager_slice": str(value.engager_slice),
            "allocated_total": str(value.allocated_total),
            "claimed_total": str(value.claimed_total),
            "finalized_epoch": int(value.finalized_epoch) or None,
            "claim_window_days": int(value.claim_window_days) or None,
            "claim_deadline_unix": int(value.claim_deadline_unix) or None,
            "start_unix": int(value.start_unix) or None,
            "end_unix": int(value.end_unix) or None,
            "settlement_cursor": bytes(value.settlement_cursor) or None,
            "partial_actor": str(value.partial_actor or "") or None,
            "partial_count": int(value.partial_count),
            "prune_pending": bool(value.prune_pending),
            "prune_complete": bool(value.prune_complete),
        }

    def query_creator_epoch_accruals(self, epoch_id: int) -> list[dict]:
        """Read every creator accrual for one epoch with bounded pagination."""
        from shared.datatypes import (
            PageRequest,
            QueryCreatorEpochAccrualsRequest,
            QueryCreatorEpochAccrualsResponse,
        )

        epoch = int(epoch_id)
        next_key = b""
        out: list[dict] = []
        seen: set[str] = set()
        with grpc.insecure_channel(self.grpc_target) as channel:
            method = channel.unary_unary(
                "/mirage.core.v1.Query/CreatorEpochAccruals",
                request_serializer=QueryCreatorEpochAccrualsRequest.SerializeToString,
                response_deserializer=QueryCreatorEpochAccrualsResponse.FromString,
            )
            for _ in range(1001):
                try:
                    resp = method(
                        QueryCreatorEpochAccrualsRequest(
                            epoch_id=epoch,
                            pagination=PageRequest(key=next_key, limit=1000),
                        ),
                        timeout=30,
                    )
                except grpc.RpcError as e:
                    raise RuntimeError(f"CreatorEpochAccruals gRPC failed for {epoch}: {e}") from e
                for value in resp.accruals:
                    creator = str(value.creator).strip().lower()
                    if not creator or creator in seen:
                        raise RuntimeError(f"CreatorEpochAccruals returned duplicate or empty creator for epoch {epoch}")
                    if not value.amount or not value.claimed_amount:
                        raise RuntimeError(f"CreatorEpochAccruals returned incomplete amounts for {creator} epoch {epoch}")
                    seen.add(creator)
                    out.append(
                        {
                            "creator": creator,
                            "epoch_id": int(value.epoch),
                            "earned": str(value.amount),
                            "claimed": str(value.claimed_amount),
                            "claimed_height": int(value.claimed_height) or None,
                            "claimed_txhash": str(value.claimed_txhash or "") or None,
                        }
                    )
                next_key = bytes(resp.pagination.next_key) if resp.HasField("pagination") else b""
                if not next_key:
                    return out
        raise RuntimeError(f"CreatorEpochAccruals exceeded 1001 pages for epoch {epoch}")

    def query_creator_epoch_targets(self, epoch_id: int) -> list[dict]:
        """Read the per-post earning breakdown for one epoch."""
        from shared.datatypes import (
            PageRequest,
            QueryCreatorEpochTargetsRequest,
            QueryCreatorEpochTargetsResponse,
        )

        epoch = int(epoch_id)
        next_key = b""
        out: list[dict] = []
        seen: set[str] = set()
        with grpc.insecure_channel(self.grpc_target) as channel:
            method = channel.unary_unary(
                "/mirage.core.v1.Query/CreatorEpochTargets",
                request_serializer=QueryCreatorEpochTargetsRequest.SerializeToString,
                response_deserializer=QueryCreatorEpochTargetsResponse.FromString,
            )
            for _ in range(1001):
                try:
                    resp = method(
                        QueryCreatorEpochTargetsRequest(
                            epoch_id=epoch,
                            pagination=PageRequest(key=next_key, limit=1000),
                        ),
                        timeout=30,
                    )
                except grpc.RpcError as e:
                    raise RuntimeError(f"CreatorEpochTargets gRPC failed for {epoch}: {e}") from e
                for value in resp.earnings:
                    target = str(value.target).strip().lower()
                    creator = str(value.creator).strip().lower()
                    if not target or target in seen:
                        raise RuntimeError(f"CreatorEpochTargets returned duplicate or empty target for epoch {epoch}")
                    if not creator:
                        raise RuntimeError(f"CreatorEpochTargets returned empty creator for {target} epoch {epoch}")
                    if not value.amount:
                        raise RuntimeError(f"CreatorEpochTargets returned incomplete amount for {target} epoch {epoch}")
                    seen.add(target)
                    out.append(
                        {
                            "epoch_id": int(value.epoch_id),
                            "target_txhash": target,
                            "creator": creator,
                            "upvote_units": int(value.upvote_units),
                            "direct_reply_units": int(value.direct_reply_units),
                            "amount": str(value.amount),
                        }
                    )
                next_key = bytes(resp.pagination.next_key) if resp.HasField("pagination") else b""
                if not next_key:
                    return out
        raise RuntimeError(f"CreatorEpochTargets exceeded 1001 pages for epoch {epoch}")

    def query_creator_schedule(self, timeout: int = GRPC_TIMEOUT) -> dict:
        """Read the live creator-epoch grid."""
        from shared.datatypes import QueryCreatorScheduleRequest, QueryCreatorScheduleResponse

        with grpc.insecure_channel(self.grpc_target) as channel:
            method = channel.unary_unary(
                "/mirage.core.v1.Query/CreatorSchedule",
                request_serializer=QueryCreatorScheduleRequest.SerializeToString,
                response_deserializer=QueryCreatorScheduleResponse.FromString,
            )
            try:
                resp = method(QueryCreatorScheduleRequest(), timeout=timeout)
            except grpc.RpcError as e:
                raise RuntimeError(f"CreatorSchedule gRPC failed: {e}") from e
        epoch_seconds = int(resp.epoch_seconds)
        if epoch_seconds < 300 or 86400 % epoch_seconds != 0:
            raise RuntimeError(f"CreatorSchedule returned invalid epoch_seconds={epoch_seconds}")
        return {
            "origin_epoch": int(resp.origin_epoch),
            "origin_unix": int(resp.origin_unix),
            "epoch_seconds": epoch_seconds,
            "current_epoch": int(resp.current_epoch),
        }

    def query_subscription_runtime(self, address: str, timeout: int = GRPC_TIMEOUT) -> dict:
        """Read quota and renewal-warning state required by bootstrap."""
        from shared.datatypes import (
            QuerySubscriberQuotaRequest,
            QuerySubscriberQuotaResponse,
            QuerySubscriptionRenewalRequest,
            QuerySubscriptionRenewalResponse,
        )

        owner = str(address).strip().lower()
        if not owner:
            raise RuntimeError("query_subscription_runtime requires address")
        with grpc.insecure_channel(self.grpc_target) as channel:
            quota_method = channel.unary_unary(
                "/mirage.core.v1.Query/SubscriberQuota",
                request_serializer=QuerySubscriberQuotaRequest.SerializeToString,
                response_deserializer=QuerySubscriberQuotaResponse.FromString,
            )
            renewal_method = channel.unary_unary(
                "/mirage.core.v1.Query/SubscriptionRenewal",
                request_serializer=QuerySubscriptionRenewalRequest.SerializeToString,
                response_deserializer=QuerySubscriptionRenewalResponse.FromString,
            )
            try:
                quota = quota_method(QuerySubscriberQuotaRequest(address=owner), timeout=timeout)
                renewal = renewal_method(QuerySubscriptionRenewalRequest(address=owner), timeout=timeout)
            except grpc.RpcError as e:
                raise RuntimeError(f"subscription runtime gRPC failed for {owner}: {e}") from e
        # No renewal schedule (free / appointed admin / cleared) → NULL schedule
        # columns. warning_sent stays false (column is NOT NULL). Do not invent
        # expiry=0; bootstrap used to treat that as a real warning.
        if renewal.HasField("state"):
            renewal_expiry = int(renewal.state.expiry)
            renewal_next_attempt = int(renewal.state.next_attempt_unix)
            renewal_last_attempt_epoch = int(renewal.state.last_attempt_epoch)
            renewal_warning_sent = bool(renewal.state.warning_sent)
        else:
            renewal_expiry = None
            renewal_next_attempt = None
            renewal_last_attempt_epoch = None
            renewal_warning_sent = False
        result = {
            "quota_epoch": int(quota.epoch),
            "quota_limit": int(quota.limit),
            "quota_used": int(quota.used),
            "quota_remaining": int(quota.remaining),
            "quota_reset_at": int(quota.reset_at),
            "renewal_expiry": renewal_expiry,
            "renewal_next_attempt": renewal_next_attempt,
            "renewal_last_attempt_epoch": renewal_last_attempt_epoch,
            "renewal_warning_sent": renewal_warning_sent,
        }
        if result["quota_limit"] < result["quota_used"] or result["quota_remaining"] != (
            result["quota_limit"] - result["quota_used"]
        ):
            raise RuntimeError(f"SubscriberQuota returned inconsistent values for {owner}")
        logger.debug(
            "[quota] grpc address=%s used=%s limit=%s renewal_expiry=%s",
            owner,
            result["quota_used"],
            result["quota_limit"],
            result["renewal_expiry"],
        )
        return result

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
            "effective_paid": bool(resp.effective_paid),
            "followed_users": list(resp.followed_users),
            "joined_communities": list(resp.joined_communities),
            "blocked_users": list(resp.blocked_users),
            "blocked_posts": list(resp.blocked_posts),
            "blocked_communities": list(resp.blocked_communities),
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
        GOVERNANCE_ONLY_TYPE_URLS is exempt: those are known to carry no projected
        state, so dropping them is the intended outcome rather than silent drift.
        """
        untracked = sorted(
            {
                any_msg.type_url
                for any_msg in anys
                if any_msg.type_url.startswith(CORE_TYPE_URL_PREFIX)
                and any_msg.type_url not in type_url_to_proto
                and any_msg.type_url not in GOVERNANCE_ONLY_TYPE_URLS
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
