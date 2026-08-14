"""
Message processing logic for the indexer.
"""

import logging
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
)
from indexer.address_utils import addr_from_pubkey, derive_owner_from_msg, derive_owner_from_dict
from indexer.params import get_vote_weight
from indexer.settings import (
    ALLOWED_DIRECTIONS,
    WEIGHTED_VOTES,
    COMMUNITY_VOTE_BASELINE,
    COMMUNITY_VOTE_MAX_TOPIC_VOTES,
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


class MessageProcessor:
    """Handles processing of all message types."""

    def __init__(self, db_manager, chain_client, log_yaml_fn, iso_timestamp_fn):
        self.db = db_manager
        self.chain = chain_client
        self.log_yaml = log_yaml_fn
        self.iso_timestamp = iso_timestamp_fn

    def process_core_message(self, type_url: str, value: bytes, tx_hash: str, ts: int, height: int):
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
            self._handle_delete(type_url, value, ts)
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

    def _handle_post(self, type_url: str, value: bytes, tx_hash: str, ts: int, height: int):
        """Handle MsgPost (with tag support)."""
        parsed = MsgPost()
        parsed.ParseFromString(value)
        msg_dict = MessageToDict(parsed, preserving_proto_field_name=True)
        owner = derive_owner_from_msg(msg_dict)
        relayer = str(msg_dict.get("authority", "") or "").strip().lower()

        topic = str(msg_dict.get("topic", "") or "")
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

        # No topic/title/content size gates here: those are consensus rules the chain has
        # already enforced. Re-checking them against current params would silently drop
        # committed posts whenever the params change, leaving the DB behind chain state.

        existing = self.db.get_post(txhash)

        # Denormalise root_topic/root_post_id so later consumers (e.g. vote routing)
        # can resolve them in a single lookup.
        if not target:
            # Root post: its own topic/id are the root.
            root_topic = (topic or "").strip() or None
            root_post_id = txhash
        else:
            # Comment: resolve root via the current posts table (may walk parents once
            # for legacy data, but is O(1) for new chains with populated root_* fields).
            root_topic, root_post_id = self.db.get_root_topic_for_post(target)

        self.db.upsert_post(
            txhash,
            owner,
            ts,
            topic,
            title,
            content,
            target,
            paid,
            relayer=relayer,
            tag=tag,
            root_topic=root_topic,
            root_post_id=root_post_id,
            media=media,
        )

        # Update user topic stats for new posts (not edits). Required projection: any
        # failure must abort the block rather than leave post_count silently short.
        # Auto-upvote also contributes +1 to net_votes so rebuild and live paths agree.
        if not existing and owner and root_topic:
            self.db.update_user_topic_stats(
                owner,
                root_topic,
                net_votes_delta=1,
                root_post_id=root_post_id,
                is_new_vote=True,
                post_increment=1,
            )
            logger.debug(
                "user_topic_stats post+auto_upvote owner=%s topic=%s tx=%s",
                owner,
                root_topic,
                txhash[:12],
            )

        # Increment comment_count for all ancestors when a new comment is indexed
        if not existing and target:
            try:
                self.db.increment_ancestor_comment_counts(target)
            except Exception:
                logger.exception("Failed to increment ancestor comment_counts for %s", txhash)
                raise

        # Update topic safety stats for root posts only, and only on first index —
        # replaying an already-indexed post must not double-count the tag.
        if not existing and not target:
            try:
                self.db.update_topic_content_stats(root_topic or topic, tag)
            except Exception:
                logger.exception("Failed to update topic_content_stats for %s", txhash)
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
        if not existing or existing[:4] != (topic, title, content, target):
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
                    "topic": topic,
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
            # Also reverse topic and author preferences if there was a previous vote.
            previous_vote = self.db.get_vote_by_owner_target(owner, target)
            prev_vote = 0.0
            if previous_vote:
                _, prev_vote, _ = previous_vote
            prev_direction = _vote_direction(prev_vote)
            root_topic, root_post_id = self.db.get_root_topic_for_post(target)

            if prev_direction != 0:
                reverse_topic_delta = -0.5 if prev_direction > 0 else 0.5
                reverse_author_delta = -1.0 if prev_direction > 0 else 1.0

                # Reverse topic preference - only for root posts, not comments
                is_root_post = root_post_id and target == root_post_id
                if root_topic and owner and is_root_post:
                    try:
                        self.db.update_preference(owner, "topic", root_topic, reverse_topic_delta, ts)
                        logger.debug(
                            "Reversed topic preference for cleared vote: owner=%s topic=%s delta=%s",
                            owner,
                            root_topic,
                            reverse_topic_delta,
                        )
                    except Exception as e:
                        logger.error(
                            "Error reversing topic preference for cleared vote %s: %s", txhash, e, exc_info=True
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
            # topic standing earned by a vote survives the vote being withdrawn.
            if owner and root_topic and prev_direction != 0:
                self.db.update_user_topic_stats(
                    owner,
                    root_topic,
                    net_votes_delta=-prev_direction,
                    root_post_id=root_post_id,
                    is_new_vote=False,
                )
                logger.debug(
                    "user_topic_stats net_votes cleared owner=%s topic=%s delta=%d tx=%s",
                    owner,
                    root_topic,
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
                    "topic": None,
                    "root_post_id": None,
                    "paid": bool(paid),
                },
            )
            return

        # Resolve root post/topic for this target (comments inherit topic from root).
        root_topic, root_post_id = self.db.get_root_topic_for_post(target)

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
        # - DOWNVOTES require topic standing (gated by activity factors)
        # This prevents outsiders from burying on-topic content while still allowing
        # positive signals to flow freely.
        user_weight = 0.0
        weight = COMMUNITY_VOTE_BASELINE
        topic_factor = 0.0
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

        if owner and root_topic and raw_direction != 0:
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
                    # DOWNVOTES: gated by topic activity (outsiders have no downvote power)
                    stats = self.db.get_user_topic_stats(owner, root_topic)
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
                        topic_factor = (
                            min(vote_count / COMMUNITY_VOTE_MAX_TOPIC_VOTES, 1.0)
                            if COMMUNITY_VOTE_MAX_TOPIC_VOTES > 0
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
                        combined = topic_factor * age_factor * root_factor * posts_factor
                        weight = COMMUNITY_VOTE_BASELINE + combined * (tier_max - COMMUNITY_VOTE_BASELINE)

                        factors = [
                            (topic_factor, f"topic_votes({vote_count}/{COMMUNITY_VOTE_MAX_TOPIC_VOTES})"),
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

                # Update user topic stats AFTER calculating (so current vote uses pre-vote stats).
                # net_votes tracks the standing signal, so a re-vote must apply the delta
                # against the previous direction rather than the raw new direction.
                is_new_vote = previous_vote is None
                prev_direction = _vote_direction(prev_vote)
                net_votes_delta = int(raw_direction) - prev_direction
                logger.debug(
                    "user_topic_stats vote owner=%s topic=%s prev=%d new=%d delta=%d new_vote=%s tx=%s",
                    owner,
                    root_topic,
                    prev_direction,
                    int(raw_direction),
                    net_votes_delta,
                    is_new_vote,
                    txhash[:12],
                )
                self.db.update_user_topic_stats(
                    owner,
                    root_topic,
                    net_votes_delta=net_votes_delta,
                    root_post_id=root_post_id,
                    is_new_vote=is_new_vote,
                )
            except Exception as e:
                logger.error("Error calculating vote weight for %s: %s", txhash, e, exc_info=True)
                raise

        # Update per-user topic preference weights for personalization.
        # Only update topic prefs when voting on ROOT posts, not comments.
        # Voting on a comment reflects opinion of the commenter, not the topic.
        is_root_post = root_post_id and target == root_post_id
        if owner and root_topic and is_root_post:
            try:
                new_delta = 0.5 if raw_direction > 0 else -0.5
                # If there was a previous vote and it's different, calculate the net delta
                if prev_vote != 0 and prev_vote != user_vote:
                    old_delta = 0.5 if prev_vote > 0 else -0.5
                    # Net effect: reverse old, apply new
                    net_delta = new_delta - old_delta
                    if net_delta != 0:
                        self.db.update_preference(owner, "topic", root_topic, net_delta, ts)
                elif prev_vote == 0:
                    # No previous vote, just apply the new delta
                    self.db.update_preference(owner, "topic", root_topic, new_delta, ts)
                # If prev_vote == user_vote, it's the same vote direction, no change needed
            except Exception as e:
                logger.error(
                    "Error updating topic preference for vote %s (owner=%s, topic=%s): %s",
                    txhash,
                    owner,
                    root_topic,
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
                "topic": root_topic,
                "target": target,
            },
            "result": {
                "user_vote": user_vote,
                "user_weight": round(user_weight, 3),
            },
        }

        # Add calculation details if we computed community vote
        if raw_direction != 0 and root_topic:
            if raw_direction > 0:
                # Upvotes: always full tier weight
                vote_log["calculation"] = {
                    "formula": "upvotes_always_full_weight",
                    "tier_max": round(tier_max, 2),
                    "weight": round(weight, 3),
                }
            else:
                # Downvotes: gated by topic activity
                vote_log["calculation"] = {
                    "formula": "(topic * age * roots * posts) * tier_max",
                    "tier_max": round(tier_max, 2),
                    "factors": {
                        "net_votes": f"{net_votes} (min: {COMMUNITY_VOTE_MIN_NET_VOTES})",
                        "topic": f"{vote_count}/{COMMUNITY_VOTE_MAX_TOPIC_VOTES} = {round(topic_factor, 2)}",
                        "age": f"{round(age_days, 1)}d/{COMMUNITY_VOTE_MATURITY_DAYS}d = {round(age_factor, 2)}",
                        "roots": f"{unique_root_posts}/{COMMUNITY_VOTE_MIN_ROOT_POSTS} = {round(root_factor, 2)}",
                        "posts": f"{post_count}/{COMMUNITY_VOTE_MAX_POSTS} = {round(posts_factor, 2)}",
                    },
                    "combined": round(topic_factor * age_factor * root_factor * posts_factor, 3),
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
        topic = str(msg_dict.get("topic", "") or "")
        logger.info("MsgEdit topic=%s", topic)
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
        existing_topic, _, _, existing_target, _, _, existing_created_at, _existing_media_raw = existing
        is_root = not bool(existing_target)

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
        # Root posts may update topic; comments must not carry topic.
        if is_root:
            new_topic = topic if topic else (existing_topic or "")
            new_title = title
            root_topic = (new_topic or "").strip().lower() or None
            root_post_id = override
        else:
            new_topic = ""
            new_title = ""
            # For comments, inherit root topic/id from target/override
            root_topic, root_post_id = self.db.get_root_topic_for_post(target or override)
        new_content = content
        if len(existing) <= 4:
            raise RuntimeError(f"Rejected edit {tx_hash}: stored post row missing paid flag")
        paid_flag = bool(existing[4])
        logger.info("MsgEdit upsert: override=%s new_topic=%s new_title=%s", override, new_topic, new_title)
        self.db.upsert_post(
            override,
            owner,
            int(existing_created_at) if existing_created_at else int(ts),
            new_topic,
            new_title,
            new_content,
            target,
            paid_flag,
            relayer=relayer,
            tag=tag,
            root_topic=root_topic,
            root_post_id=root_post_id,
            edited_at=int(ts),
            media=media,
        )

        # Recompute topic safety stats when root posts change
        if is_root:
            try:
                if existing_topic:
                    self.db.recompute_topic_content_stats(existing_topic)
                if new_topic and (existing_topic or "").lower() != (new_topic or "").lower():
                    self.db.recompute_topic_content_stats(new_topic)
            except Exception:
                logger.exception("Failed to recompute topic_content_stats for edit %s", tx_hash)
                raise

        # Vote and post standing is keyed by the topic the post carries now, so a
        # topic change has to carry the thread's existing attribution with it.
        if is_root and new_topic and (existing_topic or "").lower() != (new_topic or "").lower():
            self.db.reattribute_topic_stats(override, existing_topic or "", new_topic)

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
        """Handle MsgAnnotate — store agent overlay edit in agent_edits table."""
        try:
            parsed = MsgAnnotate()
            parsed.ParseFromString(value)
            agent = addr_from_pubkey(parsed.envelope_pubkey)
            if not agent:
                raise RuntimeError(f"Rejected annotate {tx_hash}: invalid envelope_pubkey")
            override = str(parsed.override or "").strip().lower()

            if not override or len(override) != 64:
                raise RuntimeError(f"Rejected annotate {tx_hash}: invalid override {override!r}")
            existing = self.db.get_post(override)
            if not existing:
                # As with votes, the chain does not require the override to exist.
                logger.warning("Skipping annotate %s: override %s is not in the index", tx_hash, override)
                return

            # Enforce agent tier
            agent_level = self.db.get_user_level(agent)
            if agent_level < 10:
                logger.warning("Rejected annotate %s: not agent tier (level=%d)", tx_hash, agent_level)
                return

            # Sentinel "." means no change (store None); empty string means clear
            SENTINEL = "."

            def resolve_field(val):
                if val == SENTINEL:
                    return None
                return val

            topic_raw = str(parsed.topic or "")
            title_raw = str(parsed.title or "")
            content_raw = str(parsed.content or "")
            tag_raw = str(parsed.tag or "")
            appendix_raw = str(parsed.appendix or "")

            topic = resolve_field(topic_raw)
            title = resolve_field(title_raw)
            content = resolve_field(content_raw)
            tag = resolve_field(tag_raw)
            if tag is not None:
                tag_norm = tag.strip().lower()
                tag = DatabaseManager._TAG_ALIASES.get(tag_norm, tag_norm)
                if tag != tag_norm:
                    logger.debug("Tag alias normalized on annotate: %s -> %s", tag_norm, tag)
            appendix = resolve_field(appendix_raw)

            # Media: ["."] means no change; [] means clear; list means replace
            raw_media = list(parsed.media or [])
            if len(raw_media) == 1 and raw_media[0] == SENTINEL:
                media = None
            else:
                media = raw_media

            logger.debug(
                "MsgAnnotate parsed: tx=%s agent=%s override=%s title_len=%d content_len=%d appendix_len=%d media_count=%d",
                tx_hash,
                agent,
                override,
                len(title_raw),
                len(content_raw),
                len(appendix_raw),
                len(raw_media),
            )

            # For comments (target present in DB), ignore topic/title overrides
            _, _, _, existing_target, _, _, _, _ = existing
            is_comment = bool(existing_target)
            if is_comment:
                topic = None
                title = None

            logger.info(
                "MsgAnnotate upsert: agent=%s override=%s topic=%s title=%s appendix=%s media_count=%s",
                agent,
                override,
                topic,
                title,
                appendix,
                len(media) if media is not None else "none",
            )

            self.db.upsert_agent_edit(
                post_txhash=override,
                agent_address=agent,
                edit_txhash=tx_hash,
                edited_at=int(ts),
                topic=topic,
                title=title,
                content=content,
                tag=tag,
                media=media,
                appendix=appendix,
            )

            self.log_yaml(
                "Agent annotate",
                {
                    "height": int(height),
                    "txhash": (tx_hash or "").lower(),
                    "timestamp": int(ts),
                    "time_iso": self.iso_timestamp(ts),
                    "agent": agent,
                    "override": override,
                    "is_comment": is_comment,
                },
            )
        except Exception as e:
            logger.error("Error handling MsgAnnotate %s: %s", tx_hash, e, exc_info=True)

            raise

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
            agents = []

            profile = self.chain.query_profile_full(addr)
            if profile is None:
                logger.warning("profile_absent set_username: skipping refresh for %s", addr)
                return
            if "username" not in profile:
                raise RuntimeError(f"missing username for {addr}")
            if "level" not in profile:
                raise RuntimeError(f"missing level for {addr}")
            if "enabled_agents" not in profile:
                raise RuntimeError(f"missing enabled_agents for {addr}")
            username = str(profile["username"])
            level = int(profile["level"])
            agents = profile["enabled_agents"]
            if not isinstance(agents, list):
                raise RuntimeError(f"invalid enabled_agents for {addr}")
            logger.debug("set_username profile loaded addr=%s agents=%d", addr, len(agents))

            old = self.db.get_profile(addr)
            self.db.upsert_profile(addr, username, level, ts)
            self.db.set_enabled_agents(addr, agents)

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
                        "enabled_agents": agents,
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
        """Query full profile via gRPC and replace enabled_agents in DB."""
        profile = self.chain.query_profile_full(addr)
        if profile is None:
            logger.warning("profile_absent enabled_agents: skipping refresh for %s", addr)
            return
        if "enabled_agents" not in profile:
            raise RuntimeError(f"missing enabled_agents for {addr}")
        agents = profile["enabled_agents"]
        if not isinstance(agents, list):
            raise RuntimeError(f"invalid enabled_agents for {addr}")
        logger.debug("refresh_enabled_agents addr=%s agents=%d", addr, len(agents))
        self.db.set_enabled_agents(addr, agents)
        self.db.update_profile_timestamp(addr, ts)
        self.log_yaml(
            "Updated enabled agents",
            {
                "address": addr,
                "timestamp": int(ts),
                "time_iso": self.iso_timestamp(ts),
                "agents": agents,
            },
        )

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

    def _refresh_followed_topics(self, addr: str, ts: int):
        """Query full profile via gRPC and replace followed_topics in DB."""
        profile = self.chain.query_profile_full(addr)
        if profile is None:
            logger.warning("profile_absent followed_topics: skipping refresh for %s", addr)
            return
        if "followed_topics" not in profile:
            raise RuntimeError(f"missing followed_topics for {addr}")
        topics = profile["followed_topics"]
        if not isinstance(topics, list):
            raise RuntimeError(f"invalid followed_topics for {addr}")
        logger.debug("refresh_followed_topics addr=%s topics=%d", addr, len(topics))
        self.db.set_followed_topics(addr, topics)
        self.db.update_profile_timestamp(addr, ts)
        self.log_yaml(
            "Updated followed topics",
            {
                "address": addr,
                "timestamp": int(ts),
                "time_iso": self.iso_timestamp(ts),
                "topics": topics,
            },
        )

    def _handle_enable_agent(self, type_url: str, value: bytes, ts: int):
        """Handle MsgEnableAgent."""
        try:
            parsed = MsgEnableAgent()
            parsed.ParseFromString(value)
            msg_dict = MessageToDict(parsed, preserving_proto_field_name=True)
            owner = msg_dict.get("target", "") or derive_owner_from_msg(msg_dict)
            if not owner:
                logger.warning("Rejected enable_agent: missing owner")
                return
            self._refresh_enabled_agents(owner, ts)
        except Exception as e:
            logger.error("Error handling MsgEnableAgent: %s", e, exc_info=True)

            raise

    def _handle_disable_agent(self, type_url: str, value: bytes, ts: int):
        """Handle MsgDisableAgent."""
        try:
            parsed = MsgDisableAgent()
            parsed.ParseFromString(value)
            msg_dict = MessageToDict(parsed, preserving_proto_field_name=True)
            owner = msg_dict.get("target", "") or derive_owner_from_msg(msg_dict)
            if not owner:
                logger.warning("Rejected disable_agent: missing owner")
                return
            self._refresh_enabled_agents(owner, ts)
        except Exception as e:
            logger.error("Error handling MsgDisableAgent: %s", e, exc_info=True)

            raise

    def _handle_set_agents(self, type_url: str, value: bytes, ts: int):
        """Handle MsgSetAgents."""
        try:
            parsed = MsgSetAgents()
            parsed.ParseFromString(value)
            msg_dict = MessageToDict(parsed, preserving_proto_field_name=True)
            owner = msg_dict.get("target", "") or derive_owner_from_msg(msg_dict)
            if not owner:
                logger.warning("Rejected set_agents: missing owner")
                return
            self._refresh_enabled_agents(owner, ts)
        except Exception as e:
            logger.error("Error handling MsgSetAgents: %s", e, exc_info=True)

            raise

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
        """Handle MsgFollowTopic."""
        try:
            parsed = MsgFollowTopic()
            parsed.ParseFromString(value)
            msg_dict = MessageToDict(parsed, preserving_proto_field_name=True)
            owner = derive_owner_from_msg(msg_dict)
            topic = str(msg_dict.get("topic", "")).strip().lower()

            if not owner or not topic:
                logger.warning("Rejected follow_topic: missing owner or topic")
                return

            removed = self.db.unblock_topics_matching(owner, topic)
            if removed > 0:
                logger.debug("Follow topic removed block(s): owner=%s topic=%s removed=%d", owner, topic, removed)
            self._refresh_followed_topics(owner, ts)
            self.log_yaml(
                "Follow topic",
                {"owner": owner, "topic": topic, "timestamp": int(ts), "time_iso": self.iso_timestamp(ts)},
            )
        except Exception as e:
            logger.error("Error handling MsgFollowTopic: %s", e, exc_info=True)

            raise

    def _handle_unfollow_topic(self, type_url: str, value: bytes, ts: int):
        """Handle MsgUnfollowTopic."""
        try:
            parsed = MsgUnfollowTopic()
            parsed.ParseFromString(value)
            msg_dict = MessageToDict(parsed, preserving_proto_field_name=True)
            owner = derive_owner_from_msg(msg_dict)
            topic = str(msg_dict.get("topic", "")).strip().lower()

            if not owner or not topic:
                logger.warning("Rejected unfollow_topic: missing owner or topic")
                return

            self._refresh_followed_topics(owner, ts)
            self.log_yaml(
                "Unfollow topic",
                {"owner": owner, "topic": topic, "timestamp": int(ts), "time_iso": self.iso_timestamp(ts)},
            )
        except Exception as e:
            logger.error("Error handling MsgUnfollowTopic: %s", e, exc_info=True)

            raise

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
            topic = str(msg_dict.get("topic", "")).strip().lower()

            if not owner or not topic:
                logger.warning("Rejected block_topic: missing owner or topic")
                return

            self.db.block_topic(owner, topic, blocked_at=int(ts))
            removed = self.db.unfollow_topics_matching(owner, topic)
            if removed > 0:
                logger.debug("Block topic removed follow(s): owner=%s pattern=%s removed=%d", owner, topic, removed)
            self.log_yaml(
                "Block topic",
                {"owner": owner, "topic": topic, "timestamp": int(ts), "time_iso": self.iso_timestamp(ts)},
            )
        except Exception as e:
            logger.error("Error handling MsgBlockTopic: %s", e, exc_info=True)

            raise

    def _handle_unblock_topic(self, type_url: str, value: bytes, ts: int):
        """Handle MsgUnblockTopic."""
        try:
            parsed = MsgUnblockTopic()
            parsed.ParseFromString(value)
            msg_dict = MessageToDict(parsed, preserving_proto_field_name=True)
            owner = derive_owner_from_msg(msg_dict)
            topic = str(msg_dict.get("topic", "")).strip().lower()

            if not owner or not topic:
                logger.warning("Rejected unblock_topic: missing owner or topic")
                return

            self.db.unblock_topic(owner, topic)
            self.log_yaml(
                "Unblock topic",
                {"owner": owner, "topic": topic, "timestamp": int(ts), "time_iso": self.iso_timestamp(ts)},
            )
        except Exception as e:
            logger.error("Error handling MsgUnblockTopic: %s", e, exc_info=True)

            raise

    def _handle_delete(self, type_url: str, value: bytes, ts: int):
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
            )
            self.log_yaml(
                "User subscribed",
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
            )
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
        except Exception as e:
            logger.error("Error handling update_params: %s", e, exc_info=True)

            raise

    def update_profile_level(self, addr: str, level: int, ts: int):
        """Update profile level from subscription events (EndBlock)."""
        try:
            updated = self.db.update_profile_level(addr, level, ts)
            if updated:
                logger.info("Updated profile level for %s to %d", addr, level)
            else:
                logger.warning("No profile found to update level for %s", addr)
        except Exception as e:
            logger.error("Error updating profile level for %s: %s", addr, e, exc_info=True)
            raise

    def update_profile_subscription(self, addr: str, level: int, subscription_expiry: int, ts: int):
        """Update profile level and subscription_expiry from renewal events (EndBlock)."""
        try:
            # Pass None for auto_renew to preserve the existing setting
            updated = self.db.update_profile_subscription(addr, level, subscription_expiry, None, ts)
            if updated:
                logger.info(
                    "Updated profile subscription for %s: level=%d, expiry=%d",
                    addr,
                    level,
                    subscription_expiry,
                )
            else:
                logger.warning("No profile found to update subscription for %s", addr)
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
