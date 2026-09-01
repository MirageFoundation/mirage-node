"""
Message processing logic for the indexer.
"""

import json
import logging
import re
import time
from typing import Optional
from google.protobuf.json_format import MessageToDict
from shared.datatypes import (
    MsgPost,
    MsgEdit,
    MsgVote,
    MsgSetUsername,
    MsgSetBiography,
    MsgEnableAgent,
    MsgDisableAgent,
    MsgSetAgents,
    MsgFollowUser,
    MsgUnfollowUser,
    MsgFollowTopic,
    MsgUnfollowTopic,
    MsgBlockPost,
    MsgUnblockPost,
    MsgBlockUser,
    MsgUnblockUser,
    MsgBlockTopic,
    MsgUnblockTopic,
    MsgDelete,
    MsgDeleteUser,
    MsgSetLevel,
    MsgSubscribe,
    MsgSetAutoRenewal,
    MsgUpdateParams,
    MsgAward,
    MsgAnnotate,
    MsgJoinCommunity,
    MsgLeaveCommunity,
    MsgCreateCommunity,
    MsgCreateCurationTeam,
    MsgSetCurationTeamProfile,
    MsgInviteCurator,
    MsgRevokeCuratorInvite,
    MsgAcceptCuratorInvite,
    MsgDeclineCuratorInvite,
    MsgLeaveCurationTeam,
    MsgRemoveCurator,
    MsgTransferCurationTeam,
    MsgDeleteCurationTeam,
    MsgSetCurationPreference,
    MsgSetCurationPostHidden,
    MsgSetCurationUserHidden,
    MsgSetCurationThreadLocked,
    MsgSetCurationSubscriberOnly,
    MsgSetCurationTag,
    MsgSetCurationPostTag,
    MsgClaimCreatorRewards,
    MsgBlockCommunity,
    MsgUnblockCommunity,
    MsgSendTokens,
)
from indexer.address_utils import addr_from_pubkey, derive_owner_from_msg, derive_owner_from_dict
from indexer.params import get_vote_weight
from indexer.settings import (
    ALLOWED_DIRECTIONS,
    WEIGHTED_VOTES,
    COMMUNITY_VOTE_BASELINE,
    COMMUNITY_VOTE_MAX_COMMUNITY_VOTES,
    COMMUNITY_VOTE_MIN_NET_VOTES,
    IGNORE_DELETIONS,
    COMMUNITY_VOTE_MATURITY_DAYS,
    COMMUNITY_VOTE_MIN_ROOT_POSTS,
    COMMUNITY_VOTE_MAX_POSTS,
    COMMUNITY_VOTE_BOOST_MULTIPLIER,
)
from indexer.database import DatabaseManager
import re
from urllib.parse import urlparse

# Regex to match @username mentions (not preceded by a word character)
_MENTION_RE = re.compile(r"(?<!\w)@([A-Za-z0-9-]+)")
# Patterns for stripping code blocks/inline code before mention extraction
_FENCED_CODE_RE = re.compile(r"```[\s\S]*?```")
_INLINE_CODE_RE = re.compile(r"`[^`]+`")

logger = logging.getLogger(__name__)


def derive_from_content(label: str, fn, *args, default=None):
    """Run a derivation over attacker-controlled content. Never raises.

    Post content, titles and media URLs are arbitrary bytes chosen by whoever
    paid for the transaction. Anything computed FROM them — thumbnail URLs,
    mention parsing — is cosmetic enrichment, and no cosmetic value is worth
    what an escaping exception costs: the offending block is already on chain,
    so every node replays it and every node dies at the same height, forever,
    including a fresh node syncing from genesis. One post took down the whole
    network's indexing on 2026-08-11 (height 6754167, a nested markdown link
    that made urlsplit raise) exactly this way.

    This is not a fallback that hides a bug. It is the same rule `_handle_vote`
    already applies to an unindexed vote target ("raising here would let anyone
    halt every indexer on the network with one junk target"), applied to the
    other half of the untrusted surface. The failure is logged with a full
    traceback, so a derivation bug is loud — it just isn't fatal.

    Deliberately NOT for state writes. DB writes, projections and counters must
    still fail hard: a silently-skipped write yields a wrong index, which is
    worse than a stopped one. Pass only pure functions of untrusted input here.
    """
    try:
        return fn(*args)
    except Exception:
        logger.exception("[derive] %s failed on untrusted content; indexing continues without it", label)
        return default


def _parse_mentions(content: str) -> list[str]:
    """Extract lowercased @usernames from post content. Pure, no I/O."""
    # Strip fenced code blocks and inline code so @mentions inside code are ignored
    stripped = _FENCED_CODE_RE.sub("", content)
    stripped = _INLINE_CODE_RE.sub("", stripped)
    return list({m.lower() for m in _MENTION_RE.findall(stripped)})


def _vote_direction(value) -> int:
    """Normalize a stored vote value (float) to a direction in {-1, 0, 1}."""
    v = float(value or 0.0)
    if v > 0:
        return 1
    if v < 0:
        return -1
    return 0


def attr_text(raw) -> str:
    """Return an event attribute as text.

    CometBFT types EventAttribute.Key/.Value as `string` (v0.38+; this chain is on
    v0.39.3), so /block_results returns them as plain text and there is nothing to
    decode. Attempting base64 on a `str` is a shape guess rather than a decode: it
    succeeds on any plain value that happens to be well-formed base64 with valid
    UTF-8 bytes and silently returns something else. Proposal id "1401" decodes that
    way, and the int() that follows then raises inside the block transaction, which
    rolls the block back and re-fails on every restart forever.

    Only genuine `bytes` are decoded, which is a type difference rather than a guess.
    """
    if raw is None:
        return ""
    if isinstance(raw, bytes):
        return raw.decode("utf-8")
    return str(raw)


TYPE_URL_TO_PROTO = {
    "/mirage.core.v1.MsgPost": MsgPost,
    "/mirage.core.v1.MsgEdit": MsgEdit,
    "/mirage.core.v1.MsgAnnotate": MsgAnnotate,
    "/mirage.core.v1.MsgVote": MsgVote,
    "/mirage.core.v1.MsgSetUsername": MsgSetUsername,
    "/mirage.core.v1.MsgSetBiography": MsgSetBiography,
    "/mirage.core.v1.MsgEnableAgent": MsgEnableAgent,
    "/mirage.core.v1.MsgDisableAgent": MsgDisableAgent,
    "/mirage.core.v1.MsgSetAgents": MsgSetAgents,
    "/mirage.core.v1.MsgFollowUser": MsgFollowUser,
    "/mirage.core.v1.MsgUnfollowUser": MsgUnfollowUser,
    "/mirage.core.v1.MsgFollowTopic": MsgFollowTopic,
    "/mirage.core.v1.MsgUnfollowTopic": MsgUnfollowTopic,
    "/mirage.core.v1.MsgBlockPost": MsgBlockPost,
    "/mirage.core.v1.MsgUnblockPost": MsgUnblockPost,
    "/mirage.core.v1.MsgBlockUser": MsgBlockUser,
    "/mirage.core.v1.MsgUnblockUser": MsgUnblockUser,
    "/mirage.core.v1.MsgBlockTopic": MsgBlockTopic,
    "/mirage.core.v1.MsgUnblockTopic": MsgUnblockTopic,
    "/mirage.core.v1.MsgDelete": MsgDelete,
    "/mirage.core.v1.MsgDeleteUser": MsgDeleteUser,
    "/mirage.core.v1.MsgSetLevel": MsgSetLevel,
    "/mirage.core.v1.MsgSubscribe": MsgSubscribe,
    "/mirage.core.v1.MsgSetAutoRenewal": MsgSetAutoRenewal,
    "/mirage.core.v1.MsgUpdateParams": MsgUpdateParams,
    "/mirage.core.v1.MsgAward": MsgAward,
    "/mirage.core.v1.MsgJoinCommunity": MsgJoinCommunity,
    "/mirage.core.v1.MsgLeaveCommunity": MsgLeaveCommunity,
    "/mirage.core.v1.MsgCreateCommunity": MsgCreateCommunity,
    "/mirage.core.v1.MsgBlockCommunity": MsgBlockCommunity,
    "/mirage.core.v1.MsgUnblockCommunity": MsgUnblockCommunity,
    "/mirage.core.v1.MsgCreateCurationTeam": MsgCreateCurationTeam,
    "/mirage.core.v1.MsgSetCurationTeamProfile": MsgSetCurationTeamProfile,
    "/mirage.core.v1.MsgInviteCurator": MsgInviteCurator,
    "/mirage.core.v1.MsgRevokeCuratorInvite": MsgRevokeCuratorInvite,
    "/mirage.core.v1.MsgAcceptCuratorInvite": MsgAcceptCuratorInvite,
    "/mirage.core.v1.MsgDeclineCuratorInvite": MsgDeclineCuratorInvite,
    "/mirage.core.v1.MsgLeaveCurationTeam": MsgLeaveCurationTeam,
    "/mirage.core.v1.MsgRemoveCurator": MsgRemoveCurator,
    "/mirage.core.v1.MsgTransferCurationTeam": MsgTransferCurationTeam,
    "/mirage.core.v1.MsgDeleteCurationTeam": MsgDeleteCurationTeam,
    "/mirage.core.v1.MsgSetCurationPreference": MsgSetCurationPreference,
    "/mirage.core.v1.MsgSetCurationPostHidden": MsgSetCurationPostHidden,
    "/mirage.core.v1.MsgSetCurationUserHidden": MsgSetCurationUserHidden,
    "/mirage.core.v1.MsgSetCurationThreadLocked": MsgSetCurationThreadLocked,
    "/mirage.core.v1.MsgSetCurationSubscriberOnly": MsgSetCurationSubscriberOnly,
    "/mirage.core.v1.MsgSetCurationTag": MsgSetCurationTag,
    "/mirage.core.v1.MsgSetCurationPostTag": MsgSetCurationPostTag,
    "/mirage.core.v1.MsgClaimCreatorRewards": MsgClaimCreatorRewards,
    # SendTokens is relayed like any other user message and the handler spends a
    # daily quota unit for it (deductRelayGasFee in module.go), so the quota
    # projection has to see it.
    "/mirage.core.v1.MsgSendTokens": MsgSendTokens,
}


_TYPE_URL_PREFIX = "/mirage.core.v1.Msg"


def type_url_to_tx_type(type_url: str) -> str:
    """Map a protobuf type_url to a short tx_type string for tx_index.

    E.g. '/mirage.core.v1.MsgSetUsername' -> 'set_username'
    """
    if not type_url or not type_url.startswith(_TYPE_URL_PREFIX):
        return "unknown"
    # Strip prefix to get e.g. 'SetUsername'
    camel = type_url[len(_TYPE_URL_PREFIX) :]
    if not camel:
        return "unknown"
    # CamelCase -> snake_case
    parts: list[str] = []
    buf: list[str] = []
    for ch in camel:
        if ch.isupper() and buf:
            parts.append("".join(buf).lower())
            buf = [ch]
        else:
            buf.append(ch)
    if buf:
        parts.append("".join(buf).lower())
    return "_".join(parts)


_MIRAGE_ADDRESS_RE = re.compile(r"^mirage1[qpzry9x8gf2tvdw0s3jn54khce6mua7l]{38}$")


def relayer_from_message(type_url: str, value: bytes) -> str:
    """Relaying node address from a core message's authority field.

    Every core message carries the relaying validator in ``authority`` (never
    the user, whose address is derived from ``envelope_pubkey``), and it is
    covered by the relayer's outer signature. Returns "" for a type this build
    does not know, which is a missing attribution rather than a wrong one.
    """
    proto_cls = TYPE_URL_TO_PROTO.get(type_url)
    if proto_cls is None:
        return ""
    try:
        parsed = proto_cls()
        parsed.ParseFromString(value)
    except Exception:
        return ""
    authority = str(getattr(parsed, "authority", "") or "").strip().lower()
    # Network tags are projected before message-specific processing, so this
    # bound is also a database safety boundary. In particular, an oversized
    # authority must never reach the LOWER(relayer) btree index and wedge the
    # indexer on the same block forever.
    if not _MIRAGE_ADDRESS_RE.fullmatch(authority):
        return ""
    return authority


class MessageProcessor:
    """Handles processing of all message types."""

    def __init__(self, db_manager, chain_client, log_yaml_fn, iso_timestamp_fn):
        self.db = db_manager
        self.chain = chain_client
        self.log_yaml = log_yaml_fn
        self.iso_timestamp = iso_timestamp_fn

    def process_core_message(
        self,
        type_url: str,
        value: bytes,
        tx_hash: str,
        ts: int,
        height: int,
        events: list | None = None,
    ):
        """Process a core message."""
        if type_url == "/mirage.core.v1.MsgPost":
            self._handle_post(type_url, value, tx_hash, ts, height)
        elif type_url == "/mirage.core.v1.MsgEdit":
            self._handle_edit(type_url, value, tx_hash, ts, height)
        elif type_url == "/mirage.core.v1.MsgAnnotate":
            self._handle_annotate(type_url, value, tx_hash, ts, height)
        elif type_url == "/mirage.core.v1.MsgVote":
            self._handle_vote(type_url, value, tx_hash, ts, height)
        elif type_url == "/mirage.core.v1.MsgSetUsername":
            self._handle_set_username(type_url, value, ts)
        elif type_url == "/mirage.core.v1.MsgSetBiography":
            self._handle_set_biography(type_url, value, ts)
        elif type_url == "/mirage.core.v1.MsgEnableAgent":
            self._handle_enable_agent(type_url, value, ts)
        elif type_url == "/mirage.core.v1.MsgDisableAgent":
            self._handle_disable_agent(type_url, value, ts)
        elif type_url == "/mirage.core.v1.MsgSetAgents":
            self._handle_set_agents(type_url, value, ts)
        elif type_url == "/mirage.core.v1.MsgFollowUser":
            self._handle_follow_user(type_url, value, ts)
        elif type_url == "/mirage.core.v1.MsgUnfollowUser":
            self._handle_unfollow_user(type_url, value, ts)
        elif type_url == "/mirage.core.v1.MsgFollowTopic":
            self._handle_follow_topic(type_url, value, ts)
        elif type_url == "/mirage.core.v1.MsgUnfollowTopic":
            self._handle_unfollow_topic(type_url, value, ts)
        elif type_url == "/mirage.core.v1.MsgBlockPost":
            self._handle_block_post(type_url, value, ts)
        elif type_url == "/mirage.core.v1.MsgUnblockPost":
            self._handle_unblock_post(type_url, value, ts)
        elif type_url == "/mirage.core.v1.MsgBlockUser":
            self._handle_block_user(type_url, value, ts)
        elif type_url == "/mirage.core.v1.MsgUnblockUser":
            self._handle_unblock_user(type_url, value, ts)
        elif type_url == "/mirage.core.v1.MsgBlockTopic":
            self._handle_block_topic(type_url, value, ts)
        elif type_url == "/mirage.core.v1.MsgUnblockTopic":
            self._handle_unblock_topic(type_url, value, ts)
        elif type_url == "/mirage.core.v1.MsgDelete":
            self._handle_delete(type_url, value, ts, height)
        elif type_url == "/mirage.core.v1.MsgDeleteUser":
            self._handle_delete_user(type_url, value, ts)
        elif type_url == "/mirage.core.v1.MsgSetLevel":
            self._handle_set_level(type_url, value, ts)
        elif type_url == "/mirage.core.v1.MsgSubscribe":
            self._handle_subscribe(type_url, value, ts)
        elif type_url == "/mirage.core.v1.MsgSetAutoRenewal":
            self._handle_set_auto_renewal(type_url, value, ts)
        elif type_url == "/mirage.core.v1.MsgUpdateParams":
            self._handle_update_params(type_url, value, ts)
        elif type_url == "/mirage.core.v1.MsgAward":
            self._handle_award(type_url, value, tx_hash, ts, height)
        elif type_url == "/mirage.core.v1.MsgJoinCommunity":
            self._handle_join_community(type_url, value, ts, height)
        elif type_url == "/mirage.core.v1.MsgLeaveCommunity":
            self._handle_leave_community(type_url, value, ts, height)
        elif type_url == "/mirage.core.v1.MsgCreateCommunity":
            self._handle_create_community(type_url, value, ts, height)
        elif type_url == "/mirage.core.v1.MsgBlockCommunity":
            self._handle_block_community(type_url, value, ts)
        elif type_url == "/mirage.core.v1.MsgUnblockCommunity":
            self._handle_unblock_community(type_url, value, ts)
        elif type_url == "/mirage.core.v1.MsgClaimCreatorRewards":
            self._handle_claim_creator_rewards(type_url, value, tx_hash, ts, height)
        elif type_url in (
            "/mirage.core.v1.MsgCreateCurationTeam",
            "/mirage.core.v1.MsgSetCurationTeamProfile",
            "/mirage.core.v1.MsgInviteCurator",
            "/mirage.core.v1.MsgRevokeCuratorInvite",
            "/mirage.core.v1.MsgAcceptCuratorInvite",
            "/mirage.core.v1.MsgDeclineCuratorInvite",
            "/mirage.core.v1.MsgLeaveCurationTeam",
            "/mirage.core.v1.MsgRemoveCurator",
            "/mirage.core.v1.MsgTransferCurationTeam",
            "/mirage.core.v1.MsgDeleteCurationTeam",
            "/mirage.core.v1.MsgSetCurationPreference",
            "/mirage.core.v1.MsgSetCurationPostHidden",
            "/mirage.core.v1.MsgSetCurationUserHidden",
            "/mirage.core.v1.MsgSetCurationThreadLocked",
            "/mirage.core.v1.MsgSetCurationSubscriberOnly",
            "/mirage.core.v1.MsgSetCurationTag",
            "/mirage.core.v1.MsgSetCurationPostTag",
        ):
            # Curation state is projected from the block's events in
            # process_curation_events(), which carries the committed final state
            # and also covers the expiry/governance transitions that never arrive
            # as a user message. Projecting the payload here as well would be a
            # second, divergent implementation of the same rules.
            logger.debug("[curation] message decoded type_url=%s height=%s tx=%s", type_url, height, tx_hash)
        elif type_url in (
            "/mirage.core.v1.MsgSetCommunityMetadata",
            "/mirage.core.v1.MsgTransferCommunity",
        ):
            logger.info(
                "[community] historical retired message decoded type_url=%s height=%s tx=%s", type_url, height, tx_hash
            )
        elif type_url == "/mirage.core.v1.MsgSendTokens":
            pass
        elif type_url == "/mirage.core.v1.MsgBridgeBurn":
            # Bridge removed in v1.31.0; keep decode-noop for historical txs on reindex.
            pass
        elif type_url == "/mirage.core.v1.MsgBridgeAttest":
            pass
        elif type_url == "/mirage.core.v1.MsgBridgeMinted":
            pass
        elif type_url == "/mirage.core.v1.MsgBridgeAttestBurned":
            pass
        elif type_url == "/mirage.core.v1.MsgBridgeAttestMinted":
            pass
        else:
            # A type this build does not know can only come from a chain upgrade
            # that shipped ahead of the indexer. Halting here would take the whole
            # platform down and, worse, make the block permanently unprojectable
            # on every restart. Skip loudly instead: the operator upgrades the
            # indexer and replays the range.
            logger.error(
                "unhandled_message_type type_url=%s height=%s tx=%s SKIPPED - "
                "this build cannot index it; upgrade the indexer and replay this height",
                type_url,
                height,
                tx_hash,
            )

    def refresh_message_signer_runtime(self, type_url: str, value: bytes) -> None:
        """Refresh quota state after a successful user message may consume it.

        A type with no mapping is one this build does not decode at all, which
        covers retired messages replayed from history and authority-only messages
        that never spend a user's quota. process_core_message has already logged
        the loud unhandled_message_type line for anything genuinely unknown, one
        call before this one, so there is nothing to add here by repeating it —
        and nothing to gain by raising: the quota number is a projection of chain
        state that the next mapped message re-reads anyway, whereas halting makes
        the block unprojectable on every restart and takes the platform down with
        it. That is the same trade process_core_message documents for itself.
        """
        proto_cls = TYPE_URL_TO_PROTO.get(type_url)
        if proto_cls is None:
            logger.debug("[quota] no mapping for %s; nothing to refresh", type_url)
            return
        parsed = proto_cls()
        parsed.ParseFromString(value)
        owner = derive_owner_from_msg(MessageToDict(parsed, preserving_proto_field_name=True))
        if not owner:
            return
        with self.db._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COALESCE(effective_paid, FALSE), COALESCE(level, 0)
                    FROM profiles WHERE LOWER(owner)=LOWER(%s)
                    """,
                    (owner,),
                )
                row = cur.fetchone()
        if not row:
            return
        # Relay-quota tiers: paid subscribers and admins (max_daily_relays > 0).
        if not (bool(row[0]) or int(row[1] or 0) >= 100):
            return
        self.update_subscription_runtime(owner)

    def update_subscription_runtime(self, owner: str) -> None:
        """Project absolute quota and renewal state for an existing profile."""
        runtime = self.chain.query_subscription_runtime(owner)
        self.db.update_subscription_runtime(owner, runtime)
        logger.debug(
            "[quota] refreshed signer=%s used=%s epoch=%s renewal_warning=%s",
            owner,
            runtime["quota_used"],
            runtime["quota_epoch"],
            runtime["renewal_warning_sent"],
        )

    def _handle_post(self, type_url: str, value: bytes, tx_hash: str, ts: int, height: int):
        """Handle MsgPost (with tag support)."""
        parsed = MsgPost()
        parsed.ParseFromString(value)
        msg_dict = MessageToDict(parsed, preserving_proto_field_name=True)
        owner = derive_owner_from_msg(msg_dict)
        relayer = str(msg_dict.get("authority", "") or "").strip().lower()

        community = str(msg_dict.get("community", "") or "")
        protocol_version = int(msg_dict.get("protocol_version", 0) or 0)
        title = str(msg_dict.get("title", "") or "")
        content = str(msg_dict.get("content", "") or "")
        target = str(msg_dict.get("target", "") or "").lower()
        raw_tag = str(msg_dict.get("tag", "") or "")
        tag_norm = raw_tag.strip().lower()
        tag = DatabaseManager._TAG_ALIASES.get(tag_norm, tag_norm)
        if tag != tag_norm:
            logger.debug("Tag alias normalized on post: %s -> %s", tag_norm, tag)
        media = list(msg_dict.get("media", []) or [])
        logger.debug("MsgPost media count=%d tx=%s", len(media), (tx_hash or "")[:12])

        txhash = (tx_hash or "").lower()
        # Derive paid flag: true if no PoW used (subscribers). Malformed envelope
        # difficulty/pow on a consensus-accepted tx is a projection invariant.
        paid = not (
            int(msg_dict.get("envelope_difficulty", 0) or 0) > 0 or int(msg_dict.get("envelope_pow", 0) or 0) > 0
        )

        # No community/title/content size gates here: those are consensus rules the chain has
        # already enforced. Re-checking them against current params would silently drop
        # committed posts whenever the params change, leaving the DB behind chain state.

        existing = self.db.get_post(txhash)

        # Denormalise root_community/root_post_id so later consumers (e.g. vote routing)
        # can resolve them in a single lookup.
        if not target:
            # Root post: its own community/id are the root.
            root_community = (community or "").strip() or None
            root_post_id = txhash
        else:
            # Comment: resolve root via the current posts table (may walk parents once
            # for legacy data, but is O(1) for new chains with populated root_* fields).
            root_community, root_post_id = self.db.get_root_community_for_post(target)
            # A comment's MsgPost carries no community of its own; it lives in the
            # one its root was posted in. Without this the column stays empty and
            # the comment falls out of community feeds and the tag precedence
            # rules, both of which key off it.
            if not community.strip() and root_community:
                community = root_community

        self.db.upsert_post(
            txhash,
            owner,
            ts,
            community,
            title,
            content,
            target,
            paid,
            relayer=relayer,
            tag=tag,
            root_community=root_community,
            root_post_id=root_post_id,
            media=media,
            protocol_version=protocol_version,
        )
        if protocol_version == 1:
            metadata = self.chain.query_post_metadata(txhash)
            if metadata["author"] != owner:
                raise RuntimeError(
                    f"PostMetadata author mismatch for {txhash}: message={owner} metadata={metadata['author']}"
                )
            self.db.update_post_protocol_metadata(txhash, metadata)

        # Update user community stats for new posts (not edits). Required projection: any
        # failure must abort the block rather than leave post_count silently short.
        # Auto-upvote also contributes +1 to net_votes so rebuild and live paths agree.
        if not existing and owner and root_community:
            self.db.update_user_community_stats(
                owner,
                root_community,
                net_votes_delta=1,
                root_post_id=root_post_id,
                is_new_vote=True,
                post_increment=1,
            )
            logger.debug(
                "user_community_stats post+auto_upvote owner=%s community=%s tx=%s",
                owner,
                root_community,
                txhash[:12],
            )

        # Increment comment_count for all ancestors when a new comment is indexed
        if not existing and target:
            try:
                self.db.increment_ancestor_comment_counts(target)
            except Exception:
                logger.exception("Failed to increment ancestor comment_counts for %s", txhash)
                raise

        # Update community safety stats for root posts only, and only on first index —
        # replaying an already-indexed post must not double-count the tag.
        if not existing and not target:
            try:
                self.db.update_community_content_stats(root_community or community, tag)
            except Exception:
                logger.exception("Failed to update community_content_stats for %s", txhash)
                raise

        if owner:
            autohash = f"auto_{txhash}"
            # Auto-upvote: preference is always 1.0, community is weighted by tier
            community_weight = 1.0
            if WEIGHTED_VOTES:
                profile = self.db.get_profile(owner)
                level = profile[1] if profile else 0
                community_weight = get_vote_weight(level)
            self.db.upsert_auto_vote(autohash, owner, ts, txhash, paid, 1.0, community_weight)

        # Thumbnail discovery for root posts only. Purely deterministic URL derivation —
        # no network I/O, so every node computes the same value from the same block.
        if not target:
            # Derivation is total (see derive_from_content); the DB write below
            # is a state write and still fails hard.
            thumb = None
            if media:
                thumb = derive_from_content("thumbnail(media)", self.discover_post_thumbnail, media[0])
            if not thumb:
                # LEGACY (v1.11): First-line media URL extraction for posts created before v1.12.0.
                # Remove after March 2026 when all old posts have been migrated or expired.
                thumb = derive_from_content("thumbnail(content)", self.discover_post_thumbnail, content)
            logger.debug("thumb derived tx=%s thumb=%s", txhash[:12], thumb)
            if thumb:
                self.db.update_post_thumbnail(txhash, thumb)

        # existing shape may differ; always log insert/update
        if not existing or existing[:4] != (community, title, content, target):
            action = "insert" if not existing else "update"
            self.log_yaml(
                "Stored post",
                {
                    "action": action,
                    "height": int(height),
                    "txhash": txhash,
                    "timestamp": int(ts),
                    "time_iso": self.iso_timestamp(ts),
                    "owner": owner,
                    "relayer": relayer,
                    "community": community,
                    "title": title,
                    "content": content,
                    "target": target,
                    "paid": bool(paid),
                },
            )

        # Extract @mentions from content for new posts
        if not existing and owner and content:
            try:
                self._extract_and_store_mentions(content, txhash, owner, ts)
            except Exception:
                logger.exception("Failed to extract mentions for post %s", txhash)
                raise

        # Push notifications handled by backend (indexer must not write backend tables)

    def _extract_and_store_mentions(self, content: str, post_txhash: str, mentioner_address: str, ts: int):
        """Parse @username mentions from content and store them in the mentions table.

        - Strips code blocks and inline code before matching
        - Resolves usernames to addresses via profiles table
        - Skips self-mentions (mentioner == mentioned)
        - Deduplicates via DB UNIQUE constraint
        """
        if not content or not post_txhash or not mentioner_address:
            return
        # Parsing runs over attacker-controlled text, so it is total; everything
        # below it (resolution + inserts) is state work and still fails hard.
        raw_usernames = derive_from_content("mentions", _parse_mentions, content, default=[])
        if not raw_usernames:
            return

        # Resolve usernames to addresses
        username_to_addr = self.db.resolve_usernames_to_addresses(raw_usernames)
        if not username_to_addr:
            logger.debug("No valid usernames resolved for mentions in %s", post_txhash)
            return

        # Filter out self-mentions
        mentioner_lower = mentioner_address.lower()
        mentioned_addresses = [addr for addr in username_to_addr.values() if addr.lower() != mentioner_lower]
        if not mentioned_addresses:
            return

        self.db.insert_mentions(post_txhash, mentioner_address, mentioned_addresses, ts)
        logger.info(
            "Stored %d mention(s) for post %s: %s",
            len(mentioned_addresses),
            post_txhash,
            [u for u, a in username_to_addr.items() if a.lower() != mentioner_lower],
        )

    def _handle_vote(self, type_url: str, value: bytes, tx_hash: str, ts: int, height: int):
        """Handle MsgVote."""
        parsed = MsgVote()
        parsed.ParseFromString(value)
        msg_dict = MessageToDict(parsed, preserving_proto_field_name=True)
        owner = derive_owner_from_msg(msg_dict)
        relayer = str(msg_dict.get("authority", "") or "").strip().lower()
        payload = {
            "target": msg_dict.get("target", ""),
            "direction": int(msg_dict.get("direction", 0) or 0),
        }

        target = str(payload.get("target", "")).lower()
        raw_direction = payload.get("direction")
        paid = not (
            int(msg_dict.get("envelope_difficulty", 0) or 0) > 0 or int(msg_dict.get("envelope_pow", 0) or 0) > 0
        )
        txhash = (tx_hash or "").lower()

        # The chain does not constrain direction, so an out-of-range value reaches
        # the indexer with code=0. Skip it rather than project a vote weight the
        # rest of the schema has no meaning for.
        if raw_direction not in ALLOWED_DIRECTIONS:
            logger.warning("Skipping vote %s: direction %r is out of range", txhash, raw_direction)
            return

        # The chain accepts a vote without checking that its target exists, so an
        # unindexed target is an expected on-chain state, not an indexer failure:
        # the post may sit in a recorded history gap, or never have existed at all.
        # Skipping keeps the projection consistent; raising here would let anyone
        # halt every indexer on the network with one junk target.
        if not self.db.post_exists(target):
            logger.warning("Skipping vote %s: target %s is not in the index", txhash, target)
            return

        if raw_direction == 0:
            # Neutral/clearing vote - zero-out this voter's vote and weight
            # for this target, but keep an audit record.
            # Also reverse community and author preferences if there was a previous vote.
            previous_vote = self.db.get_vote_by_owner_target(owner, target)
            prev_vote = 0.0
            if previous_vote:
                _, prev_vote, _ = previous_vote
            prev_direction = _vote_direction(prev_vote)
            root_community, root_post_id = self.db.get_root_community_for_post(target)

            if prev_direction != 0:
                reverse_community_delta = -0.5 if prev_direction > 0 else 0.5
                reverse_author_delta = -1.0 if prev_direction > 0 else 1.0

                # Reverse community preference - only for root posts, not comments
                is_root_post = root_post_id and target == root_post_id
                if root_community and owner and is_root_post:
                    try:
                        self.db.update_preference(owner, "community", root_community, reverse_community_delta, ts)
                        logger.debug(
                            "Reversed community preference for cleared vote: owner=%s community=%s delta=%s",
                            owner,
                            root_community,
                            reverse_community_delta,
                        )
                    except Exception as e:
                        logger.error(
                            "Error reversing community preference for cleared vote %s: %s", txhash, e, exc_info=True
                        )
                        raise

                # Reverse author preference
                try:
                    post_owner = self.db.get_post_owner(target)
                    if post_owner:
                        target_author = post_owner.strip().lower()
                        if target_author and owner.lower() != target_author:
                            self.db.update_preference(owner, "author", target_author, reverse_author_delta, ts)
                            logger.debug(
                                "Reversed author preference for cleared vote: owner=%s author=%s delta=%s",
                                owner,
                                target_author,
                                reverse_author_delta,
                            )
                except Exception as e:
                    logger.error("Error reversing author preference for cleared vote %s: %s", txhash, e, exc_info=True)
                    raise

            # Reverse the cleared vote's contribution to net_votes. Without this the
            # community standing earned by a vote survives the vote being withdrawn.
            if owner and root_community and prev_direction != 0:
                self.db.update_user_community_stats(
                    owner,
                    root_community,
                    net_votes_delta=-prev_direction,
                    root_post_id=root_post_id,
                    is_new_vote=False,
                )
                logger.debug(
                    "user_community_stats net_votes cleared owner=%s community=%s delta=%d tx=%s",
                    owner,
                    root_community,
                    -prev_direction,
                    txhash[:12],
                )

            self.db.upsert_vote(txhash, owner, ts, target, 0.0, 0.0, paid, relayer=relayer)
            self.log_yaml(
                "Stored vote",
                {
                    "height": int(height),
                    "txhash": txhash,
                    "timestamp": int(ts),
                    "time_iso": self.iso_timestamp(ts),
                    "owner": owner,
                    "relayer": relayer,
                    "target": target,
                    "user_vote": 0.0,
                    "user_weight": 0.0,
                    "weight": 0.0,
                    "previous_vote": prev_vote,
                    "community": None,
                    "root_post_id": None,
                    "paid": bool(paid),
                },
            )
            return

        # Resolve root post/community for this target (comments inherit community from root).
        root_community, root_post_id = self.db.get_root_community_for_post(target)

        # Get the author of the target post for author preference tracking
        target_author = None
        try:
            post_owner = self.db.get_post_owner(target)
            if post_owner:
                target_author = post_owner.strip().lower()
        except Exception as e:
            logger.error("Error getting post author for vote %s: %s", txhash, e, exc_info=True)

            raise

        # user_vote: simple -1/0/+1, no weighting (for personal recommendations)
        user_vote = float(raw_direction)

        # Check for previous vote to handle vote changes correctly
        previous_vote = self.db.get_vote_by_owner_target(owner, target)
        prev_vote = previous_vote[1] if previous_vote else 0.0
        logger.info(
            "Vote processing: owner=%s target=%s new_direction=%s previous_vote_exists=%s prev_vote_value=%s",
            owner[:12] if owner else None,
            target[:12] if target else None,
            raw_direction,
            previous_vote is not None,
            prev_vote,
        )

        # Calculate user_weight based on vote direction:
        # - UPVOTES always count at full tier weight (1.0 for free, higher for subscribers)
        # - DOWNVOTES require community standing (gated by activity factors)
        # This prevents outsiders from burying on-community content while still allowing
        # positive signals to flow freely.
        user_weight = 0.0
        weight = COMMUNITY_VOTE_BASELINE
        community_factor = 0.0
        age_factor = 0.0
        root_factor = 0.0
        posts_factor = 0.0
        tier_max = 1.0
        age_days = 0.0
        vote_count = 0
        net_votes = 0
        unique_root_posts = 0
        post_count = 0
        limiting_factor = None

        if owner and root_community and raw_direction != 0:
            try:
                # Get account tier for weight ceiling
                profile = self.db.get_profile(owner)
                level = profile[1] if profile and len(profile) > 1 else 0
                tier_max = get_vote_weight(level) if WEIGHTED_VOTES else 1.0

                if raw_direction > 0:
                    # UPVOTES: always count at full tier weight
                    weight = tier_max
                    user_weight = weight
                    limiting_factor = "upvote_always_full"
                else:
                    # DOWNVOTES: gated by community activity (outsiders have no downvote power)
                    stats = self.db.get_user_community_stats(owner, root_community)
                    vote_count, net_votes, unique_root_posts, post_count = stats or (0, 0, 0, 0)

                    created_at = profile[2] if profile and len(profile) > 2 else 0
                    if created_at and created_at > 0:
                        age_days = max(0, (ts - created_at) / 86400)
                    else:
                        age_days = COMMUNITY_VOTE_MATURITY_DAYS

                    if net_votes < COMMUNITY_VOTE_MIN_NET_VOTES:
                        weight = COMMUNITY_VOTE_BASELINE
                        limiting_factor = f"net_votes({net_votes})<{COMMUNITY_VOTE_MIN_NET_VOTES}"
                    else:
                        community_factor = (
                            min(vote_count / COMMUNITY_VOTE_MAX_COMMUNITY_VOTES, 1.0)
                            if COMMUNITY_VOTE_MAX_COMMUNITY_VOTES > 0
                            else 1.0
                        )
                        age_factor = (
                            min(age_days / COMMUNITY_VOTE_MATURITY_DAYS, 1.0)
                            if COMMUNITY_VOTE_MATURITY_DAYS > 0
                            else 1.0
                        )
                        root_factor = (
                            min(unique_root_posts / COMMUNITY_VOTE_MIN_ROOT_POSTS, 1.0)
                            if COMMUNITY_VOTE_MIN_ROOT_POSTS > 0
                            else 1.0
                        )
                        posts_factor = (
                            min(post_count / COMMUNITY_VOTE_MAX_POSTS, 1.0) if COMMUNITY_VOTE_MAX_POSTS > 0 else 1.0
                        )
                        combined = community_factor * age_factor * root_factor * posts_factor
                        weight = COMMUNITY_VOTE_BASELINE + combined * (tier_max - COMMUNITY_VOTE_BASELINE)

                        factors = [
                            (community_factor, f"community_votes({vote_count}/{COMMUNITY_VOTE_MAX_COMMUNITY_VOTES})"),
                            (age_factor, f"age({age_days:.0f}d/{COMMUNITY_VOTE_MATURITY_DAYS}d)"),
                            (root_factor, f"roots({unique_root_posts}/{COMMUNITY_VOTE_MIN_ROOT_POSTS})"),
                            (posts_factor, f"posts({post_count}/{COMMUNITY_VOTE_MAX_POSTS})"),
                        ]
                        min_factor = min(f[0] for f in factors)
                        if min_factor < 1.0:
                            limiting_factor = " & ".join(f[1] for f in factors if f[0] == min_factor)

                    # Apply boost multiplier to portion above baseline (for downvotes with standing)
                    if weight > COMMUNITY_VOTE_BASELINE and COMMUNITY_VOTE_BOOST_MULTIPLIER > 1:
                        above_baseline = weight - COMMUNITY_VOTE_BASELINE
                        weight = COMMUNITY_VOTE_BASELINE + (above_baseline * COMMUNITY_VOTE_BOOST_MULTIPLIER)

                    user_weight = weight * raw_direction  # negative for downvotes

                # Update user community stats AFTER calculating (so current vote uses pre-vote stats).
                # net_votes tracks the standing signal, so a re-vote must apply the delta
                # against the previous direction rather than the raw new direction.
                is_new_vote = previous_vote is None
                prev_direction = _vote_direction(prev_vote)
                net_votes_delta = int(raw_direction) - prev_direction
                logger.debug(
                    "user_community_stats vote owner=%s community=%s prev=%d new=%d delta=%d new_vote=%s tx=%s",
                    owner,
                    root_community,
                    prev_direction,
                    int(raw_direction),
                    net_votes_delta,
                    is_new_vote,
                    txhash[:12],
                )
                self.db.update_user_community_stats(
                    owner,
                    root_community,
                    net_votes_delta=net_votes_delta,
                    root_post_id=root_post_id,
                    is_new_vote=is_new_vote,
                )
            except Exception as e:
                logger.error("Error calculating vote weight for %s: %s", txhash, e, exc_info=True)
                raise

        # Update per-user community preference weights for personalization.
        # Only update community prefs when voting on ROOT posts, not comments.
        # Voting on a comment reflects opinion of the commenter, not the community.
        is_root_post = root_post_id and target == root_post_id
        if owner and root_community and is_root_post:
            try:
                new_delta = 0.5 if raw_direction > 0 else -0.5
                # If there was a previous vote and it's different, calculate the net delta
                if prev_vote != 0 and prev_vote != user_vote:
                    old_delta = 0.5 if prev_vote > 0 else -0.5
                    # Net effect: reverse old, apply new
                    net_delta = new_delta - old_delta
                    if net_delta != 0:
                        self.db.update_preference(owner, "community", root_community, net_delta, ts)
                elif prev_vote == 0:
                    # No previous vote, just apply the new delta
                    self.db.update_preference(owner, "community", root_community, new_delta, ts)
                # If prev_vote == user_vote, it's the same vote direction, no change needed
            except Exception as e:
                logger.error(
                    "Error updating community preference for vote %s (owner=%s, community=%s): %s",
                    txhash,
                    owner,
                    root_community,
                    e,
                    exc_info=True,
                )
                raise

        # Update per-user author preference weights for personalization.
        if owner and target_author and owner.lower() != target_author:
            try:
                new_delta = 1.0 if raw_direction > 0 else -1.0
                if prev_vote != 0 and prev_vote != user_vote:
                    old_delta = 1.0 if prev_vote > 0 else -1.0
                    net_delta = new_delta - old_delta
                    if net_delta != 0:
                        self.db.update_preference(owner, "author", target_author, net_delta, ts)
                elif prev_vote == 0:
                    self.db.update_preference(owner, "author", target_author, new_delta, ts)
            except Exception as e:
                logger.error(
                    "Error updating author preference for vote %s (owner=%s, author=%s): %s",
                    txhash,
                    owner,
                    target_author,
                    e,
                    exc_info=True,
                )
                raise

        # Persist both the user vote and the weighted contribution.
        self.db.upsert_vote(txhash, owner, ts, target, user_vote, user_weight, paid, relayer=relayer)

        # Build detailed vote log
        vote_log = {
            "owner": owner,
            "relayer": relayer,
            "txhash": txhash,
            "vote": {
                "direction": int(raw_direction),
                "community": root_community,
                "target": target,
            },
            "result": {
                "user_vote": user_vote,
                "user_weight": round(user_weight, 3),
            },
        }

        # Add calculation details if we computed community vote
        if raw_direction != 0 and root_community:
            if raw_direction > 0:
                # Upvotes: always full tier weight
                vote_log["calculation"] = {
                    "formula": "upvotes_always_full_weight",
                    "tier_max": round(tier_max, 2),
                    "weight": round(weight, 3),
                }
            else:
                # Downvotes: gated by community activity
                vote_log["calculation"] = {
                    "formula": "(community * age * roots * posts) * tier_max",
                    "tier_max": round(tier_max, 2),
                    "factors": {
                        "net_votes": f"{net_votes} (min: {COMMUNITY_VOTE_MIN_NET_VOTES})",
                        "community": f"{vote_count}/{COMMUNITY_VOTE_MAX_COMMUNITY_VOTES} = {round(community_factor, 2)}",
                        "age": f"{round(age_days, 1)}d/{COMMUNITY_VOTE_MATURITY_DAYS}d = {round(age_factor, 2)}",
                        "roots": f"{unique_root_posts}/{COMMUNITY_VOTE_MIN_ROOT_POSTS} = {round(root_factor, 2)}",
                        "posts": f"{post_count}/{COMMUNITY_VOTE_MAX_POSTS} = {round(posts_factor, 2)}",
                    },
                    "combined": round(community_factor * age_factor * root_factor * posts_factor, 3),
                    "weight": round(weight, 3),
                }
            if limiting_factor:
                vote_log["calculation"]["limiting"] = limiting_factor

        self.log_yaml("Stored vote", vote_log)

    def _handle_edit(self, type_url: str, value: bytes, tx_hash: str, ts: int, height: int):
        """Handle MsgEdit."""
        parsed = MsgEdit()
        parsed.ParseFromString(value)
        msg_dict = MessageToDict(parsed, preserving_proto_field_name=True)
        logger.info("MsgEdit msg_dict: %s", msg_dict)
        owner = derive_owner_from_msg(msg_dict)
        relayer = str(msg_dict.get("authority", "") or "").strip().lower()
        override = str(msg_dict.get("override", "") or "").strip().lower()
        target = str(msg_dict.get("target", "") or "").strip().lower()
        # MsgEdit carries the slug as `community`; reading the retired `community` key
        # made every value empty, so a root's community edit was dropped from the
        # index and never triggered the standing re-attribution below.
        community = str(msg_dict.get("community", "") or "")
        logger.info("MsgEdit community=%s", community)
        title = str(msg_dict.get("title", "") or "")
        content = str(msg_dict.get("content", "") or "")
        raw_tag = str(msg_dict.get("tag", "") or "")
        tag_norm = raw_tag.strip().lower()
        tag = DatabaseManager._TAG_ALIASES.get(tag_norm, tag_norm)
        if tag != tag_norm:
            logger.debug("Tag alias normalized on edit: %s -> %s", tag_norm, tag)

        # Must reference an existing post/comment
        if not override or len(override) != 64:
            raise RuntimeError(f"Rejected edit {tx_hash}: invalid override {override!r}")
        existing = self.db.get_post(override)
        if not existing:
            # As with votes, the chain does not require the override to exist.
            logger.warning("Skipping edit %s: override %s is not in the index", tx_hash, override)
            return

        # Enforce ownership: only the original owner can edit (admins cannot).
        # Foreign edits are an accepted indexer visibility boundary — leave index unchanged.
        db_owner = self.db.get_post_owner(override)
        if not db_owner or db_owner.lower() != (owner or "").lower():
            logger.warning("Rejected edit %s: owner mismatch", tx_hash)
            return

        # Determine if root (target empty in DB); enforce target immutability
        (
            existing_community,
            _,
            _,
            existing_target,
            _,
            _,
            existing_created_at,
            _existing_media_raw,
            existing_deleted,
        ) = existing
        is_root = not bool(existing_target)

        # A soft delete is terminal — the chain has no undelete message. The chain
        # does not store post bodies either, so it accepts an edit naming a deleted
        # post and leaves the decision here. upsert_post writes the deleted flag
        # from its argument, which defaults to False, so applying the edit would
        # clear it and republish a post its author had removed. The standing stays
        # retracted, because delete_post recomputed it from the canonical tables
        # and an edit applies no delta, so the row also reappears in the canonical
        # vote definition while user_community_stats stays short. Same visibility
        # boundary as a foreign edit: leave the index alone.
        if existing_deleted:
            logger.warning("Rejected edit %s: post %s is deleted", tx_hash, override)
            return

        # Target immutability: the chain never compares the supplied target against
        # the stored one, so a mismatch is user-reachable. Leave the index unchanged,
        # the same visibility boundary a foreign edit gets.
        if target and (existing_target or "").lower() != target.lower():
            logger.warning(
                "Rejected edit %s: target mismatch (supplied=%s stored=%s)", tx_hash, target, existing_target
            )
            return
        target = existing_target or ""

        media = list(msg_dict.get("media", []) or [])
        logger.debug("MsgEdit media count=%d override=%s", len(media), override)

        # Apply update: preserve created_at, set edited_at
        # Root posts may update community; comments must not carry community.
        if is_root:
            new_community = community if community else (existing_community or "")
            new_title = title
            root_community = (new_community or "").strip().lower() or None
            root_post_id = override
        else:
            new_community = ""
            new_title = ""
            # For comments, inherit root community/id from target/override
            root_community, root_post_id = self.db.get_root_community_for_post(target or override)
        new_content = content
        if len(existing) <= 4:
            raise RuntimeError(f"Rejected edit {tx_hash}: stored post row missing paid flag")
        paid_flag = bool(existing[4])
        logger.info("MsgEdit upsert: override=%s new_community=%s new_title=%s", override, new_community, new_title)
        self.db.upsert_post(
            override,
            owner,
            int(existing_created_at) if existing_created_at else int(ts),
            new_community,
            new_title,
            new_content,
            target,
            paid_flag,
            relayer=relayer,
            tag=tag,
            root_community=root_community,
            root_post_id=root_post_id,
            edited_at=int(ts),
            media=media,
        )

        # Recompute community safety stats when root posts change
        if is_root:
            try:
                if existing_community:
                    self.db.recompute_community_content_stats(existing_community)
                if new_community and (existing_community or "").lower() != (new_community or "").lower():
                    self.db.recompute_community_content_stats(new_community)
            except Exception:
                logger.exception("Failed to recompute community_content_stats for edit %s", tx_hash)
                raise

        # Vote and post standing is keyed by the community the post carries now, so a
        # community change has to carry the thread's existing attribution with it.
        if is_root and new_community and (existing_community or "").lower() != (new_community or "").lower():
            self.db.reattribute_community_stats(override, existing_community or "", new_community)

        # Recompute thumbnail on root edits (content change). Deterministic derivation only.
        if is_root:
            thumb = derive_from_content("thumbnail(edit)", self.discover_post_thumbnail, content)
            logger.debug("thumb recomputed on edit override=%s thumb=%s", override, thumb)
            self.db.update_post_thumbnail(override, thumb)

        # Re-extract @mentions on edit (delete old, insert new)
        if owner and content:
            try:
                self.db.delete_mentions_for_post(override)
                self._extract_and_store_mentions(content, override, owner, ts)
            except Exception:
                logger.exception("Failed to re-extract mentions for edit %s", tx_hash)
                raise

        # Log update
        self.log_yaml(
            "Edited post",
            {
                "height": int(height),
                "txhash": (tx_hash or "").lower(),
                "timestamp": int(ts),
                "time_iso": self.iso_timestamp(ts),
                "owner": owner,
                "relayer": relayer,
                "override": override,
                "is_root": bool(is_root),
            },
        )

    def _handle_annotate(self, type_url: str, value: bytes, tx_hash: str, ts: int, height: int):
        logger.debug("historical_annotate ignored type_url=%s tx=%s", type_url, tx_hash)

    def _handle_award(self, type_url: str, value: bytes, tx_hash: str, ts: int, height: int):
        """Handle MsgAward — store one award per owner+target."""
        try:
            parsed = MsgAward()
            parsed.ParseFromString(value)
            msg_dict = MessageToDict(parsed, preserving_proto_field_name=True)
            owner = derive_owner_from_msg(msg_dict)
            relayer = str(msg_dict.get("authority", "") or "").strip().lower()
            target = str(msg_dict.get("target", "")).strip().lower()
            award_type = str(msg_dict.get("award_type", "")).strip()

            if not owner or not target or not award_type:
                raise RuntimeError(
                    f"Award {tx_hash}: missing fields owner={owner!r} target={target!r} type={award_type!r}"
                )

            user_level = self.db.get_profile_level(owner) or 0
            is_admin = user_level >= 100

            burned_amount = 0
            if not is_admin:
                award_configs = self._get_award_configs()
                for ac in award_configs:
                    if ac.get("name") == award_type:
                        burned_amount = int(ac.get("cost", 0))
                        break

            try:
                with self.db._connect() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            INSERT INTO awards (owner, target, award_type, burned_amount, created_at, relayer)
                            VALUES (%s, %s, %s, %s, %s, %s)
                            ON CONFLICT (LOWER(owner), LOWER(target)) DO NOTHING
                            """,
                            (owner.lower(), target, award_type, burned_amount, ts, relayer),
                        )
                        if cur.rowcount == 0:
                            logger.info("Award %s: duplicate owner=%s target=%s, skipped", tx_hash, owner, target)
                            return
            except Exception as e:
                logger.error("Award %s: DB error: %s", tx_hash, e, exc_info=True)
                raise

            self.log_yaml(
                "Stored award",
                {
                    "txhash": tx_hash,
                    "owner": owner,
                    "relayer": relayer,
                    "target": target,
                    "award_type": award_type,
                    "burned": burned_amount,
                    "admin": is_admin,
                },
            )

            target_author = self.db.get_post_owner(target)

            # Push notifications handled by backend (indexer must not write backend tables)
        except Exception as e:
            logger.error("Error handling MsgAward %s: %s", tx_hash, e, exc_info=True)

            raise

    def _get_award_configs(self) -> list:
        """Get award configs from cached chain params. Missing params fail hard."""
        from indexer.params import get_award_configs

        return get_award_configs()

    def _load_chain_profile(self, addr: str) -> Optional[dict]:
        """Fetch the authoritative chain profile via gRPC.

        Returns None only when the chain reports no profile (deleted account).
        A malformed or empty response still fails hard — that is a bug or an
        outage, not a deleted user.
        """
        profile = self.chain.query_profile_full(addr)
        if profile is None:
            return None
        if not isinstance(profile, dict) or not profile:
            raise RuntimeError(f"empty profile response for {addr}")
        return profile

    def _handle_set_username(self, type_url: str, value: bytes, ts: int):
        """Handle MsgSetUsername."""
        try:
            parsed = MsgSetUsername()
            parsed.ParseFromString(value)
            msg_dict = MessageToDict(parsed, preserving_proto_field_name=True)
            msg = {
                "target": msg_dict.get("target", ""),
                "username": msg_dict.get("username", ""),
            }

            addr = str(msg.get("target") or msg.get("owner", ""))
            if not addr:
                return
            username = str(msg.get("username", ""))

            level = 0

            profile = self.chain.query_profile_full(addr)
            if profile is None:
                logger.warning("profile_absent set_username: skipping refresh for %s", addr)
                return
            if "username" not in profile:
                raise RuntimeError(f"missing username for {addr}")
            if "level" not in profile:
                raise RuntimeError(f"missing level for {addr}")
            username = str(profile["username"])
            level = int(profile["level"])
            logger.debug("set_username profile loaded addr=%s", addr)

            old = self.db.get_profile(addr)
            self.db.upsert_profile(addr, username, level, ts)

            new_tuple = (username, level)
            if not old or old != new_tuple:
                self.log_yaml(
                    "Stored username",
                    {
                        "address": addr,
                        "timestamp": int(ts),
                        "time_iso": self.iso_timestamp(ts),
                        "username": username,
                        "level": level,
                    },
                )
        except Exception as e:
            logger.error("Error handling MsgSetUsername: %s", e, exc_info=True)

            raise

    def _handle_set_biography(self, type_url: str, value: bytes, ts: int):
        """Handle MsgSetBiography — update biography in profiles table."""
        try:
            parsed = MsgSetBiography()
            parsed.ParseFromString(value)
            msg_dict = MessageToDict(parsed, preserving_proto_field_name=True)

            addr = str(msg_dict.get("target", ""))
            if not addr:
                raise RuntimeError("Rejected set_biography: missing target")
            # Authoritative biography comes from chain state after the tx applied.
            profile_data = self._load_chain_profile(addr)
            if profile_data is None:
                logger.warning("profile_absent set_biography: skipping refresh for %s", addr)
                return
            biography = str(profile_data.get("biography", "") or "")

            self.db.update_profile_biography(addr, biography, ts)
            self.log_yaml(
                "Updated biography",
                {
                    "address": addr,
                    "timestamp": int(ts),
                    "time_iso": self.iso_timestamp(ts),
                    "biography_len": len(biography),
                },
            )
        except Exception as e:
            logger.error("Error handling MsgSetBiography: %s", e, exc_info=True)

            raise

    def _refresh_enabled_agents(self, addr: str, ts: int):
        """Agents were removed in v1.39.0. Keep the helper so absent-profile tests stay no-ops."""
        profile = self.chain.query_profile_full(addr)
        if profile is None:
            logger.warning("profile_absent enabled_agents: skipping refresh for %s", addr)
        return

    def _refresh_followed_users(self, addr: str, ts: int):
        """Query full profile via gRPC and replace followed_users in DB."""
        profile = self.chain.query_profile_full(addr)
        if profile is None:
            logger.warning("profile_absent followed_users: skipping refresh for %s", addr)
            return
        if "followed_users" not in profile:
            raise RuntimeError(f"missing followed_users for {addr}")
        users = profile["followed_users"]
        if not isinstance(users, list):
            raise RuntimeError(f"invalid followed_users for {addr}")
        logger.debug("refresh_followed_users addr=%s users=%d", addr, len(users))
        self.db.set_followed_users(addr, users)
        self.db.update_profile_timestamp(addr, ts)
        self.log_yaml(
            "Updated followed users",
            {
                "address": addr,
                "timestamp": int(ts),
                "time_iso": self.iso_timestamp(ts),
                "users": users,
            },
        )

    def _refresh_joined_communities(self, addr: str, ts: int):
        """Query full profile via gRPC and replace joined communities in DB."""
        profile = self.chain.query_profile_full(addr)
        if profile is None:
            logger.warning("profile_absent joined_communities: skipping refresh for %s", addr)
            return
        if "joined_communities" not in profile:
            raise RuntimeError(f"missing joined_communities for {addr}")
        communities = profile["joined_communities"]
        if not isinstance(communities, list):
            raise RuntimeError(f"invalid joined_communities for {addr}")
        logger.debug("refresh_joined_communities addr=%s communities=%d", addr, len(communities))
        self.db.set_joined_communities(addr, communities)
        self.db.update_profile_timestamp(addr, ts)
        self.log_yaml(
            "Updated joined communities",
            {
                "address": addr,
                "timestamp": int(ts),
                "time_iso": self.iso_timestamp(ts),
                "communities": communities,
            },
        )

    def _handle_enable_agent(self, type_url: str, value: bytes, ts: int):
        logger.debug("historical_agent_msg ignored type_url=%s", type_url)

    def _handle_disable_agent(self, type_url: str, value: bytes, ts: int):
        logger.debug("historical_agent_msg ignored type_url=%s", type_url)

    def _handle_set_agents(self, type_url: str, value: bytes, ts: int):
        logger.debug("historical_agent_msg ignored type_url=%s", type_url)

    def _handle_follow_user(self, type_url: str, value: bytes, ts: int):
        """Handle MsgFollowUser."""
        try:
            parsed = MsgFollowUser()
            parsed.ParseFromString(value)
            msg_dict = MessageToDict(parsed, preserving_proto_field_name=True)
            owner = derive_owner_from_msg(msg_dict)
            user = str(msg_dict.get("user", "")).strip().lower()

            if not owner or not user:
                logger.warning("Rejected follow_user: missing owner or user")
                return

            self.db.unblock_user(owner, user)
            logger.debug("Follow user removed block: owner=%s user=%s", owner, user)
            self._refresh_followed_users(owner, ts)
            self.log_yaml(
                "Follow user",
                {"owner": owner, "user": user, "timestamp": int(ts), "time_iso": self.iso_timestamp(ts)},
            )
        except Exception as e:
            logger.error("Error handling MsgFollowUser: %s", e, exc_info=True)

            raise

    def _handle_unfollow_user(self, type_url: str, value: bytes, ts: int):
        """Handle MsgUnfollowUser."""
        try:
            parsed = MsgUnfollowUser()
            parsed.ParseFromString(value)
            msg_dict = MessageToDict(parsed, preserving_proto_field_name=True)
            owner = derive_owner_from_msg(msg_dict)
            user = str(msg_dict.get("user", "")).strip().lower()

            if not owner or not user:
                logger.warning("Rejected unfollow_user: missing owner or user")
                return

            self._refresh_followed_users(owner, ts)
            self.log_yaml(
                "Unfollow user",
                {"owner": owner, "user": user, "timestamp": int(ts), "time_iso": self.iso_timestamp(ts)},
            )
        except Exception as e:
            logger.error("Error handling MsgUnfollowUser: %s", e, exc_info=True)

            raise

    def _handle_follow_topic(self, type_url: str, value: bytes, ts: int):
        """Historical MsgFollowTopic: write LIVE_DEFAULT join on reindex."""
        parsed = MsgFollowTopic()
        parsed.ParseFromString(value)
        msg_dict = MessageToDict(parsed, preserving_proto_field_name=True)
        owner = derive_owner_from_msg(msg_dict)
        community = str(msg_dict.get("community", "") or msg_dict.get("community", "")).strip().lower()
        if not owner or not community:
            return
        removed = self.db.unblock_communities_matching(owner, community)
        if removed > 0:
            logger.debug("Follow community removed block(s): owner=%s community=%s removed=%d", owner, community, removed)
        self.db.join_community(owner, community)

    def _handle_unfollow_topic(self, type_url: str, value: bytes, ts: int):
        parsed = MsgUnfollowTopic()
        parsed.ParseFromString(value)
        msg_dict = MessageToDict(parsed, preserving_proto_field_name=True)
        owner = derive_owner_from_msg(msg_dict)
        community = str(msg_dict.get("community", "") or msg_dict.get("community", "")).strip().lower()
        if not owner or not community:
            return
        self.db.leave_community(owner, community)

    def _handle_block_post(self, type_url: str, value: bytes, ts: int):
        """Handle MsgBlockPost."""
        try:
            parsed = MsgBlockPost()
            parsed.ParseFromString(value)
            msg_dict = MessageToDict(parsed, preserving_proto_field_name=True)
            owner = derive_owner_from_msg(msg_dict)
            target = str(msg_dict.get("target", "")).strip().lower()

            if not owner or not target:
                logger.warning("Rejected block_post: missing owner or target")
                return

            self.db.block_post(owner, target, blocked_at=int(ts))
            self.log_yaml(
                "Block post",
                {"owner": owner, "target": target, "timestamp": int(ts), "time_iso": self.iso_timestamp(ts)},
            )
        except Exception as e:
            logger.error("Error handling MsgBlockPost: %s", e, exc_info=True)

            raise

    def _handle_unblock_post(self, type_url: str, value: bytes, ts: int):
        """Handle MsgUnblockPost."""
        try:
            parsed = MsgUnblockPost()
            parsed.ParseFromString(value)
            msg_dict = MessageToDict(parsed, preserving_proto_field_name=True)
            owner = derive_owner_from_msg(msg_dict)
            target = str(msg_dict.get("target", "")).strip().lower()

            if not owner or not target:
                logger.warning("Rejected unblock_post: missing owner or target")
                return

            self.db.unblock_post(owner, target)
            self.log_yaml(
                "Unblock post",
                {"owner": owner, "target": target, "timestamp": int(ts), "time_iso": self.iso_timestamp(ts)},
            )
        except Exception as e:
            logger.error("Error handling MsgUnblockPost: %s", e, exc_info=True)

            raise

    def _handle_block_user(self, type_url: str, value: bytes, ts: int):
        """Handle MsgBlockUser."""
        try:
            parsed = MsgBlockUser()
            parsed.ParseFromString(value)
            msg_dict = MessageToDict(parsed, preserving_proto_field_name=True)
            owner = derive_owner_from_msg(msg_dict)
            target = str(msg_dict.get("target", "")).strip().lower()

            if not owner or not target:
                logger.warning("Rejected block_user: missing owner or target")
                return

            self.db.block_user(owner, target, blocked_at=int(ts))
            self.db.unfollow_user(owner, target)
            logger.debug("Block user removed follow: owner=%s target=%s", owner, target)
            self.log_yaml(
                "Block user",
                {"owner": owner, "target": target, "timestamp": int(ts), "time_iso": self.iso_timestamp(ts)},
            )
        except Exception as e:
            logger.error("Error handling MsgBlockUser: %s", e, exc_info=True)

            raise

    def _handle_unblock_user(self, type_url: str, value: bytes, ts: int):
        """Handle MsgUnblockUser."""
        try:
            parsed = MsgUnblockUser()
            parsed.ParseFromString(value)
            msg_dict = MessageToDict(parsed, preserving_proto_field_name=True)
            owner = derive_owner_from_msg(msg_dict)
            target = str(msg_dict.get("target", "")).strip().lower()

            if not owner or not target:
                logger.warning("Rejected unblock_user: missing owner or target")
                return

            self.db.unblock_user(owner, target)
            self.log_yaml(
                "Unblock user",
                {"owner": owner, "target": target, "timestamp": int(ts), "time_iso": self.iso_timestamp(ts)},
            )
        except Exception as e:
            logger.error("Error handling MsgUnblockUser: %s", e, exc_info=True)

            raise

    def _handle_block_topic(self, type_url: str, value: bytes, ts: int):
        """Handle MsgBlockTopic."""
        try:
            parsed = MsgBlockTopic()
            parsed.ParseFromString(value)
            msg_dict = MessageToDict(parsed, preserving_proto_field_name=True)
            owner = derive_owner_from_msg(msg_dict)
            community = str(msg_dict.get("community", "")).strip().lower()

            if not owner or not community:
                logger.warning("Rejected block_community: missing owner or community")
                return

            self.db.block_community(owner, community, blocked_at=int(ts))
            removed = self.db.leave_communities_matching(owner, community)
            if removed > 0:
                logger.debug("Block community removed follow(s): owner=%s pattern=%s removed=%d", owner, community, removed)
            self.log_yaml(
                "Block community",
                {"owner": owner, "community": community, "timestamp": int(ts), "time_iso": self.iso_timestamp(ts)},
            )
        except Exception as e:
            logger.error("Error handling MsgBlockTopic: %s", e, exc_info=True)

            raise

    def _handle_block_community(self, type_url: str, value: bytes, ts: int):
        parsed = MsgBlockCommunity()
        parsed.ParseFromString(value)
        msg_dict = MessageToDict(parsed, preserving_proto_field_name=True)
        owner = derive_owner_from_msg(msg_dict)
        community = str(msg_dict.get("community", "")).strip().lower()
        if not owner or not community:
            logger.warning("Rejected block_community: missing owner or community")
            return
        # Blocking is a read filter, not a membership change: the chain's
        # AddBlockedCommunity leaves joins untouched, so the indexer must not
        # drop them either or its view diverges from chain state.
        self.db.block_community(owner, community, blocked_at=int(ts))
        logger.info("block_community owner=%s community=%s", owner, community)

    def _handle_unblock_community(self, type_url: str, value: bytes, ts: int):
        parsed = MsgUnblockCommunity()
        parsed.ParseFromString(value)
        msg_dict = MessageToDict(parsed, preserving_proto_field_name=True)
        owner = derive_owner_from_msg(msg_dict)
        community = str(msg_dict.get("community", "")).strip().lower()
        if not owner or not community:
            logger.warning("Rejected unblock_community: missing owner or community")
            return
        self.db.unblock_community(owner, community)
        logger.info("unblock_community owner=%s community=%s", owner, community)

    def _handle_unblock_topic(self, type_url: str, value: bytes, ts: int):
        """Handle MsgUnblockTopic."""
        try:
            parsed = MsgUnblockTopic()
            parsed.ParseFromString(value)
            msg_dict = MessageToDict(parsed, preserving_proto_field_name=True)
            owner = derive_owner_from_msg(msg_dict)
            community = str(msg_dict.get("community", "")).strip().lower()

            if not owner or not community:
                logger.warning("Rejected unblock_community: missing owner or community")
                return

            self.db.unblock_community(owner, community)
            self.log_yaml(
                "Unblock community",
                {"owner": owner, "community": community, "timestamp": int(ts), "time_iso": self.iso_timestamp(ts)},
            )
        except Exception as e:
            logger.error("Error handling MsgUnblockTopic: %s", e, exc_info=True)

            raise

    def _handle_delete(self, type_url: str, value: bytes, ts: int, height: int):
        """Handle MsgDelete.

        Security model (enforced HERE, not on-chain):
        - Governance (authority = governance module address): can delete any post
        - Admin (user level >= 100): can delete any post
        - Regular user: can only delete their own posts

        The blockchain accepts Delete messages from anyone (they just pay gas),
        but this indexer enforces the actual authorization. Invalid deletes are
        rejected here and have no effect - the attacker just wasted gas.
        """
        # Governance module address (deterministic, derived from "gov" module name)
        GOV_MODULE_ADDRESS = "mirage10d07y265gmmuvt4z0w9aw880jnsr700jvealeg"

        try:
            parsed = MsgDelete()
            parsed.ParseFromString(value)
            msg_dict = MessageToDict(parsed, preserving_proto_field_name=True)
            owner = derive_owner_from_dict(msg_dict)
            target = str(msg_dict.get("target", "")).strip().lower()

            if not owner or not target:
                logger.warning("Rejected delete: missing owner or target")
                return

            # Check if deletions are disabled by node config
            if IGNORE_DELETIONS:
                logger.info("Ignoring delete for target %s (IGNORE_DELETIONS=True)", target)
                return

            # Check authorization: governance > admin > owner
            is_governance = owner.lower() == GOV_MODULE_ADDRESS.lower()
            deleter_level = self.db.get_user_level(owner) if not is_governance else 0
            is_admin = deleter_level >= 100

            if is_governance:
                # Governance can delete any post
                rows_affected = self.db.delete_post(target, None)
                if rows_affected > 0:
                    self.log_yaml(
                        "Delete post (GOVERNANCE)",
                        {
                            "target": target,
                            "timestamp": int(ts),
                            "time_iso": self.iso_timestamp(ts),
                        },
                    )
                else:
                    logger.warning("Governance delete rejected: target %s not found", target)
            elif is_admin:
                # Admin (level >= 100) can delete any post
                rows_affected = self.db.delete_post(target, None)
                if rows_affected > 0:
                    self.log_yaml(
                        "Delete post (ADMIN)",
                        {
                            "admin": owner,
                            "admin_level": deleter_level,
                            "target": target,
                            "timestamp": int(ts),
                            "time_iso": self.iso_timestamp(ts),
                        },
                    )
                else:
                    logger.warning("Admin delete rejected: target %s not found", target)
            else:
                # Regular user: must own the post
                rows_affected = self.db.delete_post(target, owner)
                if rows_affected > 0:
                    self.log_yaml(
                        "Delete post",
                        {
                            "owner": owner,
                            "target": target,
                            "timestamp": int(ts),
                            "time_iso": self.iso_timestamp(ts),
                        },
                    )
                else:
                    logger.warning("Delete rejected: target %s not found or not owned by %s", target, owner)
            if rows_affected > 0:
                with self.db._connect() as conn:
                    with conn.cursor() as cur:
                        cur.execute("SELECT protocol_version FROM posts WHERE LOWER(txhash)=LOWER(%s)", (target,))
                        row = cur.fetchone()
                if row and int(row[0]) == 1:
                    metadata = self.chain.query_post_metadata(target)
                    if int(metadata["deleted_height"]) <= 0:
                        raise RuntimeError(f"PostMetadata did not report deletion for {target} at height {height}")
                    self.db.update_post_protocol_metadata(target, metadata)
        except Exception as e:
            logger.error("Error handling MsgDelete: %s", e, exc_info=True)

            raise

    def _handle_delete_user(self, type_url: str, value: bytes, ts: int):
        """Handle MsgDeleteUser - soft-delete the user's profile.

        On-chain authorization (self or governance) is already enforced by the
        blockchain module. The indexer just marks the profile as deleted while
        preserving the row for historical post attribution.
        """
        try:
            parsed = MsgDeleteUser()
            parsed.ParseFromString(value)
            msg_dict = MessageToDict(parsed, preserving_proto_field_name=True)
            target = str(msg_dict.get("target", "")).strip().lower()

            if not target:
                logger.warning("Rejected delete_user: missing target")
                return

            rows = self.db.soft_delete_profile(target, ts)
            if rows > 0:
                self.log_yaml(
                    "Delete user (soft-delete)",
                    {
                        "target": target,
                        "timestamp": int(ts),
                        "time_iso": self.iso_timestamp(ts),
                    },
                )
            else:
                logger.warning("DeleteUser: profile not found or already deleted for %s", target)
        except Exception as e:
            logger.error("Error handling MsgDeleteUser: %s", e, exc_info=True)

            raise

    def _handle_set_level(self, type_url: str, value: bytes, ts: int):
        """Handle MsgSetLevel."""
        try:
            parsed = MsgSetLevel()
            parsed.ParseFromString(value)
            msg_dict = MessageToDict(parsed, preserving_proto_field_name=True)
            target = str(msg_dict.get("target", "")).strip().lower()
            level = int(msg_dict.get("level", 0) or 0)

            if not target:
                logger.warning("Rejected set_level: missing target")
                return

            existing = self.db.get_profile(target)

            if existing:
                self.db.upsert_profile(target, existing[0], level, ts)
                self.log_yaml(
                    "Set user level",
                    {
                        "target": target,
                        "old_level": existing[1] if existing else 0,
                        "new_level": level,
                        "timestamp": int(ts),
                        "time_iso": self.iso_timestamp(ts),
                    },
                )
            else:
                self.db.upsert_profile(target, None, level, ts)
                self.log_yaml(
                    "Set user level (new profile)",
                    {
                        "target": target,
                        "level": level,
                        "timestamp": int(ts),
                        "time_iso": self.iso_timestamp(ts),
                    },
                )
            # Admins use the relay-quota path (max_daily_relays > 0) without
            # EffectivePaid, so project quota as soon as level is appointed.
            if level >= 100:
                self.update_subscription_runtime(target)
        except Exception as e:
            logger.error("Error handling set_level: %s", e, exc_info=True)

            raise

    def _handle_subscribe(self, type_url: str, value: bytes, ts: int):
        """Handle MsgSubscribe (self or gift subscription)."""
        try:
            parsed = MsgSubscribe()
            parsed.ParseFromString(value)
            msg_dict = MessageToDict(parsed, preserving_proto_field_name=True)
            owner = str(msg_dict.get("target", "")).strip().lower()
            if owner:
                logger.debug("Subscribe target: owner=%s", owner)
            else:
                owner = derive_owner_from_msg(msg_dict)
            requested_level = int(msg_dict.get("level", 0) or 0)

            if not owner:
                raise RuntimeError("Rejected subscribe: could not derive owner")

            profile_data = self._load_chain_profile(owner)
            if profile_data is None:
                logger.warning("profile_absent subscribe: skipping refresh for %s", owner)
                return
            level = int(profile_data.get("level", requested_level))
            subscription_expiry = int(profile_data.get("subscription_expiry", 0) or 0)
            auto_renew = bool(profile_data.get("auto_renew", False))
            username = profile_data.get("username") or None
            created_at = int(profile_data.get("created_at", 0) or 0)
            biography = profile_data.get("biography", "") or ""
            avatar = profile_data.get("avatar", "") or ""
            banner = profile_data.get("banner", "") or ""
            flair = profile_data.get("flair", "") or ""
            reserve_funds = int(profile_data.get("reserve_funds", 0) or 0)
            effective_paid = bool(profile_data.get("effective_paid", False))

            self.db.upsert_profile_full(
                owner,
                username,
                level,
                created_at,
                subscription_expiry,
                auto_renew,
                biography,
                avatar,
                banner,
                flair,
                ts,
                reserve_funds=reserve_funds,
                effective_paid=effective_paid,
            )
            self.db.update_subscription_runtime(owner, self.chain.query_subscription_runtime(owner))
            self.log_yaml(
                "User subscribed",
                {
                    "owner": owner,
                    "level": level,
                    "effective_paid": effective_paid,
                    "subscription_expiry": subscription_expiry,
                    "auto_renew": auto_renew,
                    "timestamp": int(ts),
                    "time_iso": self.iso_timestamp(ts),
                },
            )
        except Exception as e:
            logger.error("Error handling subscribe: %s", e, exc_info=True)

            raise

    def _handle_set_auto_renewal(self, type_url: str, value: bytes, ts: int):
        """Handle MsgSetAutoRenewal (user-initiated auto_renew toggle)."""
        try:
            parsed = MsgSetAutoRenewal()
            parsed.ParseFromString(value)
            msg_dict = MessageToDict(parsed, preserving_proto_field_name=True)
            # For MsgSetAutoRenewal, derive owner from envelope_pubkey
            owner = derive_owner_from_msg(msg_dict)
            requested_flag = bool(msg_dict.get("auto_renew", False))

            if not owner:
                raise RuntimeError("Rejected set_auto_renewal: could not derive owner")

            profile_data = self._load_chain_profile(owner)
            if profile_data is None:
                logger.warning("profile_absent set_auto_renewal: skipping refresh for %s", owner)
                return
            level = int(profile_data.get("level", 0) or 0)
            subscription_expiry = int(profile_data.get("subscription_expiry", 0) or 0)
            auto_renew = bool(profile_data.get("auto_renew", requested_flag))
            username = profile_data.get("username") or None
            created_at = int(profile_data.get("created_at", 0) or 0)
            biography = profile_data.get("biography", "") or ""
            avatar = profile_data.get("avatar", "") or ""
            banner = profile_data.get("banner", "") or ""
            flair = profile_data.get("flair", "") or ""
            reserve_funds = int(profile_data.get("reserve_funds", 0) or 0)
            effective_paid = bool(profile_data.get("effective_paid", False))

            self.db.upsert_profile_full(
                owner,
                username,
                level,
                created_at,
                subscription_expiry,
                auto_renew,
                biography,
                avatar,
                banner,
                flair,
                ts,
                reserve_funds=reserve_funds,
                effective_paid=effective_paid,
            )
            self.db.update_subscription_runtime(owner, self.chain.query_subscription_runtime(owner))
            self.log_yaml(
                "User set auto_renewal",
                {
                    "owner": owner,
                    "level": level,
                    "subscription_expiry": subscription_expiry,
                    "auto_renew": auto_renew,
                    "timestamp": int(ts),
                    "time_iso": self.iso_timestamp(ts),
                },
            )
        except Exception as e:
            logger.error("Error handling set_auto_renewal: %s", e, exc_info=True)

            raise

    def _handle_update_params(self, type_url: str, value: bytes, ts: int):
        """Handle MsgUpdateParams (governance parameter changes)."""
        try:
            parsed = MsgUpdateParams()
            parsed.ParseFromString(value)
            from indexer.params import load_params as load_chain_params, get_raw_params

            load_chain_params(self.chain.grpc_target, force=True)
            raw = get_raw_params()
            if raw:
                self.db.set_chain_stat("chain_params", raw, int(ts))
                logger.info("Params updated via MsgUpdateParams: chain_params stored")
            self._store_creator_schedule(int(ts))
        except Exception as e:
            logger.error("Error handling update_params: %s", e, exc_info=True)

            raise

    def _refresh_subscription_projection(self, addr: str, ts: int) -> dict:
        profile = self._load_chain_profile(addr)
        if profile is None:
            raise RuntimeError(f"subscription event references missing profile {addr}")
        self.db.upsert_profile_full(
            profile["owner"],
            profile["username"],
            profile["level"],
            profile["created_at"],
            profile["subscription_expiry"],
            profile["auto_renew"],
            profile["biography"],
            profile["avatar"],
            profile["banner"],
            profile["flair"],
            ts,
            reserve_funds=profile["reserve_funds"],
            effective_paid=profile["effective_paid"],
        )
        runtime = self.chain.query_subscription_runtime(addr)
        self.db.update_subscription_runtime(addr, runtime)
        logger.info(
            "[quota] projected address=%s paid=%s used=%s renewal_warning=%s",
            addr,
            profile["effective_paid"],
            runtime["quota_used"],
            runtime["renewal_warning_sent"],
        )
        return profile

    def update_profile_level(self, addr: str, level: int, ts: int):
        """Update profile level from subscription events (EndBlock)."""
        try:
            profile = self._refresh_subscription_projection(addr, ts)
            if int(profile["level"]) != int(level):
                raise RuntimeError(
                    f"subscription expiry level mismatch for {addr}: event={level} chain={profile['level']}"
                )
        except Exception as e:
            logger.error("Error updating profile level for %s: %s", addr, e, exc_info=True)
            raise

    def update_profile_subscription(self, addr: str, level: int, subscription_expiry: int, ts: int):
        """Update profile level and subscription_expiry from renewal events (EndBlock)."""
        try:
            profile = self._refresh_subscription_projection(addr, ts)
            if int(profile["level"]) != int(level) or int(profile["subscription_expiry"]) != int(subscription_expiry):
                raise RuntimeError(
                    f"subscription renewal mismatch for {addr}: "
                    f"event=({level},{subscription_expiry}) "
                    f"chain=({profile['level']},{profile['subscription_expiry']})"
                )
        except Exception as e:
            logger.error("Error updating profile subscription for %s: %s", addr, e, exc_info=True)
            raise

    # ------------------------------
    # Thumbnail discovery helpers
    # ------------------------------
    # LEGACY (v1.11): First-line media URL extraction for posts created before v1.12.0.
    # Remove after March 2026 when all old posts have been migrated or expired.
    @staticmethod
    def _extract_first_url(text: str) -> str:
        if not text:
            return ""
        m = re.search(r"https?://[^\s<>'\"]+", text)
        return m.group(0) if m else ""

    @staticmethod
    def _is_raster_image_url(raw: str) -> bool:
        try:
            u = urlparse(raw)
            p = u.path.lower()
            host = (u.hostname or "").lower()
            if host.endswith("imagedelivery.net"):
                # Cloudflare Images direct URLs rarely have an extension, treat as images
                return True
            return any(p.endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".avif"))
        except Exception:
            return False

    @staticmethod
    def _extract_stream_uid(url: str) -> str | None:
        try:
            if not url:
                return None
            u = urlparse(url)
            host = (u.hostname or "").lower()
            path = (u.path or "").strip("/")
            if host.endswith("videodelivery.net"):
                # Patterns: /{uid}/manifest/video.m3u8, /{uid}/manifest/..., /{uid}/video/...
                parts = path.split("/")
                if parts and re.fullmatch(r"[a-z0-9]+", parts[0]):
                    return parts[0]
            if host.endswith("cloudflarestream.com"):
                # customer-xxx.cloudflarestream.com/{uid}/iframe
                parts = path.split("/")
                if parts and re.fullmatch(r"[a-z0-9]+", parts[0]):
                    return parts[0]
        except Exception:
            return None
        return None

    @staticmethod
    def _bunny_stream_thumbnail(url: str) -> str | None:
        """Derive the Bunny Stream poster URL from a playlist URL, else None.

        Bunny Stream delivers HLS at https://{host}.b-cdn.net/{guid}/playlist.m3u8
        and the auto-generated poster at /{guid}/thumbnail.jpg on the same host.
        Mirrors the frontend getVideoThumbnailUrl() so feed/card previews match.
        Image pull zones are also *.b-cdn.net but are handled earlier as direct
        raster URLs, so only the /{guid}/playlist.m3u8 shape reaches here.
        """
        try:
            u = urlparse(url or "")
            host = (u.hostname or "").lower()
            if not host.endswith(".b-cdn.net"):
                return None
            m = re.match(r"^/([^/]+)/playlist\.m3u8$", u.path or "")
            if not m:
                return None
            return f"{u.scheme}://{u.hostname}/{m.group(1)}/thumbnail.jpg"
        except Exception:
            return None

    @staticmethod
    def _extract_youtube_video_id(url: str) -> str | None:
        try:
            if not url:
                return None
            u = urlparse(url)
            host = (u.hostname or "").lower()
            # youtube.com/watch?v=VIDEO_ID
            if host in ("www.youtube.com", "youtube.com", "m.youtube.com"):
                if u.path == "/watch":
                    from urllib.parse import parse_qs

                    qs = parse_qs(u.query)
                    v = qs.get("v")
                    if v and v[0]:
                        return v[0]
                # youtube.com/embed/VIDEO_ID or youtube.com/v/VIDEO_ID
                if u.path.startswith("/embed/") or u.path.startswith("/v/"):
                    parts = u.path.split("/")
                    if len(parts) >= 3 and parts[2]:
                        return parts[2].split("?")[0]
                # youtube.com/shorts/VIDEO_ID
                if u.path.startswith("/shorts/"):
                    parts = u.path.split("/")
                    if len(parts) >= 3 and parts[2]:
                        return parts[2].split("?")[0]
            # youtu.be/VIDEO_ID
            if host in ("youtu.be", "www.youtu.be"):
                path = (u.path or "").strip("/")
                if path:
                    return path.split("/")[0].split("?")[0]
        except Exception:
            return None
        return None

    def discover_post_thumbnail(self, content: str) -> str | None:
        """Derive a thumbnail URL for root post content, or None.

        Deterministic and offline: the thumbnail is derived from the post's own text and
        never fetched. Fetching would make the indexed value depend on whatever a
        third-party host served at index time, and would let a post author point the
        indexer at hosts of their choosing. Unknown URL shapes yield no thumbnail.
        """
        first = self._extract_first_url(content or "")
        if not first:
            logger.debug("[thumb] no URL found in content")
            return None
        try:
            scheme = urlparse(first).scheme
        except ValueError:
            # urlsplit raises on a malformed authority — an unbalanced "[" or "]"
            # reads as a broken IPv6 literal. Nested markdown links produce this
            # ("[a [b](https://)](https://)https://..." matches through the "]").
            # Post content is untrusted: an unparseable URL is an unknown shape,
            # not an indexer fault. Anything else here halts indexing chain-wide,
            # since every node replays the same block.
            logger.warning("[thumb] unparseable first URL, no thumbnail: %r", first)
            return None
        if scheme not in ("http", "https"):
            logger.debug("[thumb] first URL not http(s): %s", first)
            return None
        # Direct image
        if self._is_raster_image_url(first):
            logger.debug("[thumb] using direct raster URL: %s", first)
            return first
        # Cloudflare Stream video -> derive thumbnail
        uid = self._extract_stream_uid(first)
        if uid:
            # Use 1-second mark; the service accepts time param
            logger.debug("[thumb] derived cloudflare stream thumb for uid=%s", uid)
            return f"https://videodelivery.net/{uid}/thumbnails/thumbnail.jpg?time=1s"
        # Bunny Stream video -> derive thumbnail
        bunny_thumb = self._bunny_stream_thumbnail(first)
        if bunny_thumb:
            logger.debug("[thumb] derived bunny stream thumb: %s", bunny_thumb)
            return bunny_thumb
        # YouTube video -> derive thumbnail
        yt_id = self._extract_youtube_video_id(first)
        if yt_id:
            logger.debug("[thumb] derived youtube thumb for video_id=%s", yt_id)
            return f"https://img.youtube.com/vi/{yt_id}/hqdefault.jpg"
        logger.debug("[thumb] no deterministic thumbnail for %s", first)
        return None

    @staticmethod
    def extract_inner_anys(parsed) -> list:
        """Extract the inner Any messages carried by a decoded MsgSubmitProposal.

        gov v1 carries them in `messages`; gov v1beta1 carries a single `content` Any.
        The caller decides which proto version to parse with, so accept either shape.
        """
        messages = getattr(parsed, "messages", None)
        if messages is not None:
            return list(messages)
        content = getattr(parsed, "content", None)
        if content is not None and getattr(content, "type_url", ""):
            return [content]
        return []

    def _handle_join_community(self, type_url: str, value: bytes, ts: int, height: int):
        parsed = MsgJoinCommunity()
        parsed.ParseFromString(value)
        msg_dict = MessageToDict(parsed, preserving_proto_field_name=True)
        owner = derive_owner_from_msg(msg_dict)
        slug = str(msg_dict.get("community", "")).strip().lower()
        if not owner or not slug:
            return
        with self.db._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO community_curation_preferences(owner, community, mode, pinned_team_id, updated_height)
                    VALUES(%s, %s, 0, NULL, %s)
                    ON CONFLICT (owner, community) DO UPDATE SET updated_height = EXCLUDED.updated_height
                    """,
                    (owner, slug, int(height)),
                )
        logger.info("join_community owner=%s community=%s height=%s", owner, slug, height)

    def _handle_leave_community(self, type_url: str, value: bytes, ts: int, height: int):
        parsed = MsgLeaveCommunity()
        parsed.ParseFromString(value)
        msg_dict = MessageToDict(parsed, preserving_proto_field_name=True)
        owner = derive_owner_from_msg(msg_dict)
        slug = str(msg_dict.get("community", "")).strip().lower()
        if not owner or not slug:
            return
        with self.db._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM community_curation_preferences WHERE LOWER(owner)=LOWER(%s) AND community=%s",
                    (owner, slug),
                )
        logger.info("leave_community owner=%s community=%s height=%s", owner, slug, height)

    def _sync_curation_team(self, community: str, team_id: int, height: int) -> None:
        team = self.chain.query_curation_team(community, team_id)
        members = self.chain.query_curation_team_members(community, team_id)
        member_addresses = {member["address"] for member in members}
        if team["deleted_height"] == 0 and team["owner"] not in member_addresses:
            raise RuntimeError(f"live team owner is absent from roster: {community}/{team_id}")
        with self.db._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO curation_teams(
                        community, team_id, owner, name, normalized_name, description,
                        subscriber_only, tag, subscriber_count, created_height, created_order, deleted_height
                    ) VALUES(%s,%s,%s,%s,LOWER(TRIM(%s)),%s,%s,%s,%s,%s,%s,NULLIF(%s,0))
                    ON CONFLICT (community, team_id) DO UPDATE SET
                        owner=EXCLUDED.owner,
                        name=EXCLUDED.name,
                        normalized_name=EXCLUDED.normalized_name,
                        description=EXCLUDED.description,
                        subscriber_only=EXCLUDED.subscriber_only,
                        tag=EXCLUDED.tag,
                        subscriber_count=EXCLUDED.subscriber_count,
                        created_height=EXCLUDED.created_height,
                        created_order=EXCLUDED.created_order,
                        deleted_height=EXCLUDED.deleted_height
                    """,
                    (
                        team["community"],
                        team["team_id"],
                        team["owner"],
                        team["name"],
                        team["name"],
                        team["description"],
                        team["subscriber_only"],
                        team["tag"],
                        team["subscriber_count"],
                        team["created_height"],
                        team["created_order"],
                        team["deleted_height"],
                    ),
                )
                if members:
                    cur.executemany(
                        """
                        INSERT INTO curation_team_curators(
                            community, team_id, curator, accepted_order, joined_height
                        ) VALUES(%s,%s,%s,%s,%s)
                        ON CONFLICT(community, team_id, curator) DO UPDATE SET
                            accepted_order=EXCLUDED.accepted_order
                        """,
                        [
                            (community, int(team_id), member["address"], member["accepted_order"], int(height))
                            for member in members
                        ],
                    )
                    cur.execute(
                        """
                        DELETE FROM curation_team_curators
                        WHERE community=%s AND team_id=%s AND NOT (curator=ANY(%s))
                        """,
                        (community, int(team_id), [member["address"] for member in members]),
                    )
                else:
                    cur.execute(
                        "DELETE FROM curation_team_curators WHERE community=%s AND team_id=%s",
                        (community, int(team_id)),
                    )
                if team["deleted_height"]:
                    cur.execute(
                        """
                        UPDATE curation_team_invitations
                        SET status=2, resolved_height=%s
                        WHERE community=%s AND team_id=%s AND status=0
                        """,
                        (int(height), community, int(team_id)),
                    )
        logger.info(
            "[curation] projected team community=%s team_id=%s members=%s subscribers=%s deleted=%s",
            community,
            team_id,
            len(members),
            team["subscriber_count"],
            bool(team["deleted_height"]),
        )

    def process_curation_events(self, events: list, height: int, tx_hash: str = "") -> None:
        """Refresh absolute team state changed by tx or block-level events."""
        team_events = {
            "curation_team_created",
            "curation_team_profile_updated",
            "curation_team_subscriber_count_changed",
            "curation_team_owner_changed",
            "curation_team_deleted",
            "curator_joined",
            "curator_left",
            "curator_removed",
            "curation_subscriber_only_changed",
            "curation_tag_changed",
        }
        touched: set[tuple[str, int]] = set()
        for event_type, attrs in self.decode_events(events):
            community = str(attrs.get("community", "")).strip().lower()
            raw_team_id = attrs.get("team_id")
            if event_type in team_events:
                if not community or raw_team_id is None:
                    raise RuntimeError(f"{event_type} event missing community/team_id at height {height}")
                try:
                    team_id = int(raw_team_id)
                except (TypeError, ValueError) as e:
                    raise RuntimeError(f"{event_type} event has invalid team_id {raw_team_id!r}") from e
                if team_id <= 0:
                    raise RuntimeError(f"{event_type} event has non-positive team_id {team_id}")
                touched.add((community, team_id))
                continue

            invitation_statuses = {
                "curator_invited": 0,
                "curator_invitation_revoked": 2,
                "curator_invitation_accepted": 1,
                "curator_invitation_declined": 3,
            }
            if event_type in invitation_statuses:
                if not community or raw_team_id is None:
                    raise RuntimeError(f"{event_type} event missing community/team_id")
                team_id = int(raw_team_id)
                invitee = str(attrs.get("target", "")).strip().lower()
                inviter = str(attrs.get("inviter", "")).strip().lower()
                if not invitee:
                    raise RuntimeError(f"{event_type} event missing target")
                status = invitation_statuses[event_type]
                with self.db._connect() as conn:
                    with conn.cursor() as cur:
                        if status == 0:
                            if not inviter:
                                raise RuntimeError(f"{event_type} event missing inviter")
                            cur.execute(
                                """
                                INSERT INTO curation_team_invitations(
                                    community, team_id, invitee, inviter, status,
                                    created_height, resolved_height
                                ) VALUES(%s,%s,%s,%s,0,%s,NULL)
                                ON CONFLICT(community, team_id, invitee) DO UPDATE SET
                                    inviter=EXCLUDED.inviter,
                                    status=0,
                                    created_height=EXCLUDED.created_height,
                                    resolved_height=NULL
                                """,
                                (community, team_id, invitee, inviter, int(height)),
                            )
                        else:
                            cur.execute(
                                """
                                UPDATE curation_team_invitations
                                SET status=%s, resolved_height=%s
                                WHERE community=%s AND team_id=%s AND invitee=%s AND status=0
                                """,
                                (status, int(height), community, team_id, invitee),
                            )
                            if cur.rowcount != 1:
                                cur.execute(
                                    """
                                    SELECT status FROM curation_team_invitations
                                    WHERE community=%s AND team_id=%s AND invitee=%s
                                    """,
                                    (community, team_id, invitee),
                                )
                                existing = cur.fetchone()
                                if not existing or int(existing[0]) != status:
                                    raise RuntimeError(f"{event_type} has no pending invitation row")
                continue

            # Membership also changes without a MsgJoin/LeaveCommunity: accepting a
            # curator invite auto-joins, and the gov curator/preference messages
            # execute at EndBlock. Those paths only surface as these events.
            if event_type in ("community_joined", "community_left"):
                owner = str(attrs.get("address", "")).strip().lower()
                if not owner or not community:
                    raise RuntimeError(f"{event_type} event missing address/community at height {height}")
                with self.db._connect() as conn:
                    with conn.cursor() as cur:
                        if event_type == "community_joined":
                            cur.execute(
                                """
                                INSERT INTO community_curation_preferences(
                                    owner, community, mode, pinned_team_id, updated_height
                                ) VALUES(%s,%s,0,NULL,%s)
                                ON CONFLICT(owner, community) DO UPDATE SET
                                    updated_height=EXCLUDED.updated_height
                                """,
                                (owner, community, int(height)),
                            )
                        else:
                            cur.execute(
                                """
                                DELETE FROM community_curation_preferences
                                WHERE LOWER(owner)=LOWER(%s) AND community=%s
                                """,
                                (owner, community),
                            )
                logger.info(
                    "[curation] %s owner=%s community=%s height=%s",
                    event_type,
                    owner,
                    community,
                    height,
                )
                continue

            if event_type == "community_preference_changed":
                owner = str(attrs.get("owner", "")).strip().lower()
                if not owner or not community or "new_mode" not in attrs or "new_team_id" not in attrs:
                    raise RuntimeError(f"{event_type} event missing final state")
                mode = int(attrs["new_mode"])
                team_id = int(attrs["new_team_id"])
                if mode not in (0, 1, 2) or (mode == 1) != (team_id > 0):
                    raise RuntimeError("community_preference_changed event has malformed mode/team")
                with self.db._connect() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            INSERT INTO community_curation_preferences(
                                owner, community, mode, pinned_team_id, updated_height
                            ) VALUES(%s,%s,%s,NULLIF(%s,0),%s)
                            ON CONFLICT(owner, community) DO UPDATE SET
                                mode=EXCLUDED.mode,
                                pinned_team_id=EXCLUDED.pinned_team_id,
                                updated_height=EXCLUDED.updated_height
                            """,
                            (owner, community, mode, team_id, int(height)),
                        )
                logger.info(
                    "[curation] projected preference owner=%s community=%s mode=%s team_id=%s height=%s",
                    owner,
                    community,
                    mode,
                    team_id,
                    height,
                )
                continue

            moderation_events = {
                "curation_post_hidden": ("curation_hidden_posts", "target_txhash", "hidden"),
                "curation_user_hidden": ("curation_hidden_users", "target_user", "hidden"),
            }
            if event_type in moderation_events:
                if not community or raw_team_id is None or "target" not in attrs:
                    raise RuntimeError(f"{event_type} event missing final state")
                table, column, active_key = moderation_events[event_type]
                team_id = int(raw_team_id)
                target = str(attrs["target"]).strip().lower()
                active = str(attrs.get(active_key, "")).lower() == "true"
                actor = str(attrs.get("actor", "")).strip().lower()
                with self.db._connect() as conn:
                    with conn.cursor() as cur:
                        if active:
                            if not actor:
                                raise RuntimeError(f"{event_type} event missing actor")
                            cur.execute(
                                f"""
                                INSERT INTO {table}(community, team_id, {column}, actor, updated_height)
                                VALUES(%s,%s,%s,%s,%s)
                                ON CONFLICT(community, team_id, {column}) DO UPDATE SET
                                    actor=EXCLUDED.actor, updated_height=EXCLUDED.updated_height
                                """,
                                (community, team_id, target, actor, int(height)),
                            )
                        else:
                            cur.execute(
                                f"DELETE FROM {table} WHERE community=%s AND team_id=%s AND {column}=%s",
                                (community, team_id, target),
                            )
                continue

            if event_type == "curation_post_tag_changed":
                if not community or raw_team_id is None or "target" not in attrs or "cleared" not in attrs:
                    raise RuntimeError("curation_post_tag_changed event missing final state")
                team_id = int(raw_team_id)
                target = str(attrs["target"]).strip().lower()
                cleared = str(attrs["cleared"]).lower() == "true"
                # An empty tag is a decision, not an absence, so only `cleared`
                # removes the row.
                tag = str(attrs.get("tag", ""))
                actor = str(attrs.get("actor", "")).strip().lower()
                with self.db._connect() as conn:
                    with conn.cursor() as cur:
                        if cleared:
                            cur.execute(
                                "DELETE FROM curation_post_tags "
                                "WHERE community=%s AND team_id=%s AND target_txhash=%s",
                                (community, team_id, target),
                            )
                        else:
                            if not actor:
                                raise RuntimeError("curation_post_tag_changed event missing actor")
                            cur.execute(
                                """
                                INSERT INTO curation_post_tags(
                                    community, team_id, target_txhash, tag, actor, updated_height
                                ) VALUES(%s,%s,%s,%s,%s,%s)
                                ON CONFLICT(community, team_id, target_txhash) DO UPDATE SET
                                    tag=EXCLUDED.tag,
                                    actor=EXCLUDED.actor,
                                    updated_height=EXCLUDED.updated_height
                                """,
                                (community, team_id, target, tag, actor, int(height)),
                            )
                continue

            if event_type == "curation_thread_locked":
                if not community or raw_team_id is None or "target" not in attrs or "locked" not in attrs:
                    raise RuntimeError("curation_thread_locked event missing final state")
                team_id = int(raw_team_id)
                target = str(attrs["target"]).strip().lower()
                locked = str(attrs["locked"]).lower() == "true"
                # The chain only keeps the cut-off of the window that is open
                # right now, so the event has to carry both ends of the window a
                # lock closes. Without them the history below cannot be rebuilt.
                for required in ("lock_sequence", "unlock_sequence", "actor"):
                    if not attrs.get(required):
                        raise RuntimeError(f"curation_thread_locked event missing {required}")
                lock_sequence = int(attrs["lock_sequence"])
                unlock_sequence = int(attrs["unlock_sequence"])
                with self.db._connect() as conn:
                    with conn.cursor() as cur:
                        if locked:
                            # lock_windows is deliberately absent from the UPDATE:
                            # the closed history has to survive a re-lock.
                            cur.execute(
                                """
                                INSERT INTO curation_locks(
                                    community, team_id, root_txhash, lock_sequence,
                                    lock_windows, actor, updated_height
                                ) VALUES(%s,%s,%s,%s,'[]'::jsonb,%s,%s)
                                ON CONFLICT(community, team_id, root_txhash) DO UPDATE SET
                                    lock_sequence=EXCLUDED.lock_sequence,
                                    actor=EXCLUDED.actor,
                                    updated_height=EXCLUDED.updated_height
                                """,
                                (
                                    community,
                                    team_id,
                                    target,
                                    lock_sequence,
                                    attrs["actor"],
                                    int(height),
                                ),
                            )
                        else:
                            # A window with nothing posted inside it carries no
                            # information, so only a real stretch is recorded.
                            if unlock_sequence > lock_sequence:
                                # Upsert rather than update: an indexer that
                                # started after the lock never saw the row, and
                                # the event carries both ends of the window
                                # precisely so it can still record it.
                                window = json.dumps([[lock_sequence, unlock_sequence]])
                                cur.execute(
                                    """
                                    INSERT INTO curation_locks(
                                        community, team_id, root_txhash, lock_sequence,
                                        lock_windows, actor, updated_height
                                    ) VALUES(%s,%s,%s,NULL,%s::jsonb,%s,%s)
                                    ON CONFLICT(community, team_id, root_txhash) DO UPDATE SET
                                        lock_windows=curation_locks.lock_windows || EXCLUDED.lock_windows,
                                        lock_sequence=NULL,
                                        actor=EXCLUDED.actor,
                                        updated_height=EXCLUDED.updated_height
                                    """,
                                    (
                                        community,
                                        team_id,
                                        target,
                                        window,
                                        attrs["actor"],
                                        int(height),
                                    ),
                                )
                            else:
                                cur.execute(
                                    """
                                    UPDATE curation_locks
                                    SET lock_sequence=NULL,
                                        actor=%s,
                                        updated_height=%s
                                    WHERE community=%s AND team_id=%s AND root_txhash=%s
                                    """,
                                    (
                                        attrs["actor"],
                                        int(height),
                                        community,
                                        team_id,
                                        target,
                                    ),
                                )
                            # An unlocked thread with no history left is the same
                            # as never having been locked.
                            cur.execute(
                                """
                                DELETE FROM curation_locks
                                WHERE community=%s AND team_id=%s AND root_txhash=%s
                                  AND lock_sequence IS NULL
                                  AND lock_windows='[]'::jsonb
                                """,
                                (community, team_id, target),
                            )
                        logger.debug(
                            "[lock] projected community=%s team=%s root=%s locked=%s window=(%s,%s]",
                            community,
                            team_id,
                            target[:12],
                            locked,
                            lock_sequence,
                            unlock_sequence,
                        )
        for community, team_id in sorted(touched):
            self._sync_curation_team(community, team_id, height)
        if touched:
            logger.debug(
                "[curation] projected event teams height=%s tx=%s count=%s",
                height,
                tx_hash,
                len(touched),
            )

    def sync_creator_epoch(self, epoch_id: int, height: int) -> None:
        epoch = self.chain.query_creator_epoch(epoch_id)
        if epoch is None:
            raise RuntimeError(f"creator epoch {epoch_id} disappeared at height {height}")
        missing_amounts = [
            field
            for field in ("pool", "engager_slice", "allocated_total", "claimed_total")
            if not epoch[field]
        ]
        if missing_amounts:
            raise RuntimeError(
                f"creator epoch {epoch_id} omitted required amount fields: {', '.join(missing_amounts)}"
            )
        accruals = self.chain.query_creator_epoch_accruals(epoch_id)
        for accrual in accruals:
            if accrual["epoch_id"] != epoch_id:
                raise RuntimeError(
                    f"creator epoch {epoch_id} query returned accrual for epoch {accrual['epoch_id']}"
                )
        with self.db._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO creator_epochs(
                        epoch_id, pool, status, phase, gross_records, active_engagers,
                        engager_slice, allocated_total, claimed_total, finalized_epoch,
                        claim_window_days, claim_deadline_epoch, settlement_cursor,
                        partial_actor, partial_count, prune_pending, prune_complete,
                        updated_height
                    ) VALUES(
                        %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
                    )
                    ON CONFLICT(epoch_id) DO UPDATE SET
                        pool=EXCLUDED.pool,
                        status=EXCLUDED.status,
                        phase=EXCLUDED.phase,
                        gross_records=EXCLUDED.gross_records,
                        active_engagers=EXCLUDED.active_engagers,
                        engager_slice=EXCLUDED.engager_slice,
                        allocated_total=EXCLUDED.allocated_total,
                        claimed_total=EXCLUDED.claimed_total,
                        finalized_epoch=EXCLUDED.finalized_epoch,
                        claim_window_days=EXCLUDED.claim_window_days,
                        claim_deadline_epoch=EXCLUDED.claim_deadline_epoch,
                        settlement_cursor=EXCLUDED.settlement_cursor,
                        partial_actor=EXCLUDED.partial_actor,
                        partial_count=EXCLUDED.partial_count,
                        prune_pending=EXCLUDED.prune_pending,
                        prune_complete=EXCLUDED.prune_complete,
                        updated_height=EXCLUDED.updated_height
                    """,
                    (
                        epoch["epoch_id"],
                        epoch["pool"],
                        epoch["status"],
                        epoch["phase"],
                        epoch["gross_records"],
                        epoch["active_engagers"],
                        epoch["engager_slice"],
                        epoch["allocated_total"],
                        epoch["claimed_total"],
                        epoch["finalized_epoch"],
                        epoch["claim_window_days"],
                        epoch["claim_deadline_epoch"],
                        epoch["settlement_cursor"],
                        epoch["partial_actor"],
                        epoch["partial_count"],
                        epoch["prune_pending"],
                        epoch["prune_complete"],
                        int(height),
                    ),
                )
                creators = [accrual["creator"] for accrual in accruals]
                if accruals:
                    cur.executemany(
                        """
                        INSERT INTO creator_accruals(
                            creator, epoch_id, earned, claimed, claim_deadline_epoch,
                            claimed_height, claimed_txhash
                        ) VALUES(%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT(creator, epoch_id) DO UPDATE SET
                            earned=EXCLUDED.earned,
                            claimed=EXCLUDED.claimed,
                            claim_deadline_epoch=EXCLUDED.claim_deadline_epoch,
                            claimed_height=EXCLUDED.claimed_height,
                            claimed_txhash=EXCLUDED.claimed_txhash
                        """,
                        [
                            (
                                accrual["creator"],
                                epoch_id,
                                accrual["earned"],
                                accrual["claimed"],
                                epoch["claim_deadline_epoch"],
                                accrual["claimed_height"],
                                accrual["claimed_txhash"],
                            )
                            for accrual in accruals
                        ],
                    )
                    cur.execute(
                        "DELETE FROM creator_accruals WHERE epoch_id=%s AND NOT (creator=ANY(%s))",
                        (epoch_id, creators),
                    )
                else:
                    cur.execute("DELETE FROM creator_accruals WHERE epoch_id=%s", (epoch_id,))
        logger.info(
            "creator epoch projected epoch=%s status=%s accruals=%s height=%s",
            epoch_id,
            epoch["status"],
            len(accruals),
            height,
        )

    def process_creator_events(self, events: list, height: int) -> None:
        """Project terminal creator epoch snapshots emitted during finalization."""
        terminal_events = {"creator_epoch_claimable", "creator_epoch_expired"}
        epochs: set[int] = set()
        reset_attrs = None
        for event_type, attrs in self.decode_events(events):
            if event_type == "creator_epoch_reset_completed":
                reset_attrs = attrs
                continue
            if event_type not in terminal_events:
                continue
            raw_epoch = attrs.get("epoch")
            if raw_epoch is None:
                raise RuntimeError(f"{event_type} event missing epoch at height {height}")
            epoch = int(raw_epoch)
            if epoch < 0:
                raise RuntimeError(f"{event_type} event has negative epoch {epoch}")
            epochs.add(epoch)
        if reset_attrs is not None:
            self._reset_creator_projection(reset_attrs, height)
        for epoch in sorted(epochs):
            self.sync_creator_epoch(epoch, height)

    def _store_creator_schedule(self, ts: int, attrs: dict | None = None) -> None:
        if self.chain is not None:
            schedule = self.chain.query_creator_schedule()
        elif attrs is not None:
            if "clock" in attrs:
                current_epoch = int(attrs["clock"])
            else:
                current_epoch = int(attrs["current_epoch"])
            schedule = {
                "origin_epoch": int(attrs["origin_epoch"]),
                "origin_unix": int(attrs["origin_unix"]),
                "epoch_seconds": int(attrs["epoch_seconds"]),
                "current_epoch": current_epoch,
                "pending_epoch_seconds": 0,
                "reset_in_progress": False,
            }
        else:
            raise RuntimeError("creator schedule query has no chain client or event attributes")
        self.db.set_chain_stat("creator_schedule", schedule, int(ts))
        logger.info(
            "creator schedule stored origin_epoch=%s origin_unix=%s epoch_seconds=%s clock=%s",
            schedule["origin_epoch"],
            schedule["origin_unix"],
            schedule["epoch_seconds"],
            schedule["current_epoch"],
        )

    def _reset_creator_projection(self, attrs: dict, height: int) -> None:
        for field in ("origin_epoch", "origin_unix", "epoch_seconds"):
            if field not in attrs:
                raise RuntimeError(f"creator_epoch_reset_completed missing {field} at height {height}")
        with self.db._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM creator_epochs")
                cur.execute("DELETE FROM creator_accruals")
                cur.execute("DELETE FROM creator_claims")
                cur.execute("DELETE FROM creator_target_earnings")
                cur.execute("DELETE FROM subscription_tranches")
        self._store_creator_schedule(int(time.time()), attrs)
        logger.info(
            "creator projection reset origin_epoch=%s epoch_seconds=%s height=%s",
            attrs["origin_epoch"],
            attrs["epoch_seconds"],
            height,
        )

    def _handle_create_community(self, type_url: str, value: bytes, ts: int, height: int):
        parsed = MsgCreateCommunity()
        parsed.ParseFromString(value)
        msg_dict = MessageToDict(parsed, preserving_proto_field_name=True)
        owner = derive_owner_from_msg(msg_dict)
        slug = str(msg_dict.get("community", "")).strip().lower()
        if not owner or not slug:
            raise RuntimeError("historical MsgCreateCommunity is missing signer/community")
        self._sync_curation_team(slug, 1, height)
        logger.info("[community] historical create projected as ordinary team owner=%s community=%s", owner, slug)

    def _handle_claim_creator_rewards(self, type_url: str, value: bytes, tx_hash: str, ts: int, height: int):
        parsed = MsgClaimCreatorRewards()
        parsed.ParseFromString(value)
        msg_dict = MessageToDict(parsed, preserving_proto_field_name=True)
        owner = derive_owner_from_msg(msg_dict)
        epochs = [int(x) for x in (msg_dict.get("epoch_ids") or [])]
        if not owner or not epochs:
            raise RuntimeError("claim_creator_rewards is missing owner or epoch_ids")
        for epoch in epochs:
            self.sync_creator_epoch(epoch, height)
        logger.info("claim_creator_rewards owner=%s epochs=%s tx=%s height=%s", owner, epochs, tx_hash, height)

    @staticmethod
    def extract_proposal_id(attrs: dict) -> int | None:
        """Extract proposal_id from event attributes with multiple fallback names."""
        pid = attrs.get("proposal_id") or attrs.get("proposalID") or attrs.get("proposal-id") or attrs.get("proposalId")
        if pid is None:
            return None
        try:
            return int(pid)
        except (TypeError, ValueError) as e:
            # Deliberately fatal: skipping the event would advance the checkpoint past
            # a governance action that was never projected. Named explicitly so the
            # operator sees the offending value instead of a bare int() traceback.
            raise RuntimeError(f"Governance event carried an unparseable proposal_id {pid!r}") from e

    @staticmethod
    def decode_events(events: list) -> list[tuple[str, dict]]:
        """Decode Tendermint events."""
        decoded = []
        if not events:
            return []

        for event in events or []:
            ev_type = event.get("type", "") if isinstance(event, dict) else "NOT_DICT"
            attrs: dict[str, str] = {}
            event_attrs = event.get("attributes", []) if isinstance(event, dict) else []

            for attr in event_attrs or []:
                if not isinstance(attr, dict):
                    continue
                key = attr_text(attr.get("key"))
                val = attr_text(attr.get("value"))
                if key and val:
                    attrs[key] = val

            decoded.append((ev_type, attrs))

        return decoded

    def extract_passed_proposals(self, events: list) -> list[int]:
        """Extract passed proposal IDs from events."""
        ids: set[int] = set()
        decoded_events = self.decode_events(events)
        for ev_type, attrs in decoded_events:
            pid = self.extract_proposal_id(attrs)
            if pid is None:
                continue

            status = (
                attrs.get("proposal_status")
                or attrs.get("proposalStatus")
                or attrs.get("status")
                or attrs.get("proposal-status")
            )
            result = (
                attrs.get("proposal_result")
                or attrs.get("proposalResult")
                or attrs.get("result")
                or attrs.get("proposal-result")
            )

            if ev_type in (
                "proposal_passed",
                "proposal_executed",
                "cosmos.gov.v1beta1.EventProposalPassed",
                "cosmos.gov.v1.EventProposalPassed",
            ):
                ids.add(pid)
                continue

            if ev_type in ("active_proposal",):
                if result in ("proposal_passed", "passed") or status in (
                    "PROPOSAL_STATUS_PASSED",
                    "PROPOSAL_STATUS_EXECUTED",
                    "passed",
                    "executed",
                ):
                    ids.add(pid)
                continue

            if ev_type in (
                "proposal",
                "cosmos.gov.v1beta1.EventProposalStatusChanged",
                "cosmos.gov.v1.EventProposalStatusChanged",
            ):
                if status in ("PROPOSAL_STATUS_PASSED", "PROPOSAL_STATUS_EXECUTED", "passed", "executed") or result in (
                    "proposal_passed",
                    "passed",
                ):
                    ids.add(pid)

        return sorted(ids)
