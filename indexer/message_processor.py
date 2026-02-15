"""
Message processing logic for the indexer.
"""

import base64
import json
import logging
from google.protobuf.json_format import MessageToDict
from cosmpy.protos.cosmos.gov.v1beta1.tx_pb2 import MsgSubmitProposal
from shared.datatypes import (
    MsgPost,
    MsgEdit,
    MsgVote,
    MsgSetUsername,
    MsgFollowModerator,
    MsgUnfollowModerator,
    MsgFollowUser,
    MsgUnfollowUser,
    MsgFollowTopic,
    MsgUnfollowTopic,
    MsgBlockPost,
    MsgUnblockPost,
    MsgBlockUser,
    MsgUnblockUser,
    MsgDelete,
    MsgSetLevel,
    MsgUpgradeLevel,
    MsgSetAutoRenewal,
    MsgBridgeBurn,
    MsgBridgeAttestBurned,
    MsgBridgeAttestMinted,
)
from indexer.address_utils import derive_owner_from_msg, derive_owner_from_dict
from indexer.params import (
    get_max_topic_size,
    get_max_content_size,
    get_min_content_size,
    get_max_title_size,
    get_min_title_size,
    get_max_username_size,
    get_min_username_size,
    get_vote_weight,
)
from indexer.settings import (
    ALLOWED_DIRECTIONS,
    HTTP_TIMEOUT_SHORT,
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
from indexer.quest_tracker import QuestTracker
import re
import socket
import ipaddress
import requests
from urllib.parse import urlparse, urljoin
from bs4 import BeautifulSoup  # type: ignore
from io import BytesIO
from PIL import Image  # type: ignore

# Regex to match @username mentions (not preceded by a word character)
_MENTION_RE = re.compile(r"(?<!\w)@([A-Za-z0-9-]+)")
# Patterns for stripping code blocks/inline code before mention extraction
_FENCED_CODE_RE = re.compile(r"```[\s\S]*?```")
_INLINE_CODE_RE = re.compile(r"`[^`]+`")

logger = logging.getLogger(__name__)

TYPE_URL_TO_PROTO = {
    "/mirage.core.v1.MsgPost": MsgPost,
    "/mirage.core.v1.MsgEdit": MsgEdit,
    "/mirage.core.v1.MsgVote": MsgVote,
    "/mirage.core.v1.MsgSetUsername": MsgSetUsername,
    "/mirage.core.v1.MsgFollowModerator": MsgFollowModerator,
    "/mirage.core.v1.MsgUnfollowModerator": MsgUnfollowModerator,
    "/mirage.core.v1.MsgFollowUser": MsgFollowUser,
    "/mirage.core.v1.MsgUnfollowUser": MsgUnfollowUser,
    "/mirage.core.v1.MsgFollowTopic": MsgFollowTopic,
    "/mirage.core.v1.MsgUnfollowTopic": MsgUnfollowTopic,
    "/mirage.core.v1.MsgBlockPost": MsgBlockPost,
    "/mirage.core.v1.MsgUnblockPost": MsgUnblockPost,
    "/mirage.core.v1.MsgBlockUser": MsgBlockUser,
    "/mirage.core.v1.MsgUnblockUser": MsgUnblockUser,
    "/mirage.core.v1.MsgDelete": MsgDelete,
    "/mirage.core.v1.MsgSetLevel": MsgSetLevel,
    "/mirage.core.v1.MsgUpgradeLevel": MsgUpgradeLevel,
    "/mirage.core.v1.MsgSetAutoRenewal": MsgSetAutoRenewal,
    "/mirage.core.v1.MsgBridgeBurn": MsgBridgeBurn,
    "/mirage.core.v1.MsgBridgeAttestBurned": MsgBridgeAttestBurned,
    "/mirage.core.v1.MsgBridgeAttestMinted": MsgBridgeAttestMinted,
}


class MessageProcessor:
    """Handles processing of all message types."""

    def __init__(self, db_manager, chain_client, log_yaml_fn, iso_timestamp_fn):
        self.db = db_manager
        self.chain = chain_client
        self.log_yaml = log_yaml_fn
        self.iso_timestamp = iso_timestamp_fn
        self.quest_tracker = QuestTracker(db_manager)

    def process_core_message(self, type_url: str, value: bytes, tx_hash: str, ts: int, height: int):
        """Process a core message."""
        if type_url == "/mirage.core.v1.MsgPost":
            self._handle_post(type_url, value, tx_hash, ts, height)
        elif type_url == "/mirage.core.v1.MsgEdit":
            self._handle_edit(type_url, value, tx_hash, ts, height)
        elif type_url == "/mirage.core.v1.MsgVote":
            self._handle_vote(type_url, value, tx_hash, ts, height)
        elif type_url == "/mirage.core.v1.MsgSetUsername":
            self._handle_set_username(type_url, value, ts)
        elif type_url == "/mirage.core.v1.MsgFollowModerator":
            self._handle_follow_moderator(type_url, value, ts)
        elif type_url == "/mirage.core.v1.MsgUnfollowModerator":
            self._handle_unfollow_moderator(type_url, value, ts)
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
        elif type_url == "/mirage.core.v1.MsgDelete":
            self._handle_delete(type_url, value, ts)
        elif type_url == "/mirage.core.v1.MsgSetLevel":
            self._handle_set_level(type_url, value, ts)
        elif type_url == "/mirage.core.v1.MsgUpgradeLevel":
            self._handle_upgrade_level(type_url, value, ts)
        elif type_url == "/mirage.core.v1.MsgSetAutoRenewal":
            self._handle_set_auto_renewal(type_url, value, ts)
        elif type_url == "/mirage.core.v1.MsgSendTokens":
            pass
        # Bridge messages - index for status queries
        elif type_url == "/mirage.core.v1.MsgBridgeBurn":
            self._handle_bridge_burn(type_url, value, tx_hash, ts, height)
        elif type_url == "/mirage.core.v1.MsgBridgeAttestBurned":
            self._handle_bridge_attest_burned(type_url, value, tx_hash, ts, height)
        elif type_url == "/mirage.core.v1.MsgBridgeAttestMinted":
            self._handle_bridge_attest_minted(type_url, value, tx_hash, ts, height)
        else:
            raise RuntimeError(f"Unhandled message type {type_url}")

    def _handle_post(self, type_url: str, value: bytes, tx_hash: str, ts: int, height: int):
        """Handle MsgPost (with tag support)."""
        parsed = MsgPost()
        parsed.ParseFromString(value)
        msg_dict = MessageToDict(parsed, preserving_proto_field_name=True)
        owner = derive_owner_from_msg(msg_dict)

        topic = str(msg_dict.get("topic", "") or "")
        title = str(msg_dict.get("title", "") or "")
        content = str(msg_dict.get("content", "") or "")
        target = str(msg_dict.get("target", "") or "").lower()
        tag = str(msg_dict.get("tag", "") or "")
        media = list(msg_dict.get("media", []) or [])
        logger.debug("MsgPost media count=%d tx=%s", len(media), (tx_hash or "")[:12])

        txhash = (tx_hash or "").lower()
        # Derive paid flag: true if no PoW used (subscribers)
        try:
            paid = not (
                int(msg_dict.get("envelope_difficulty", 0) or 0) > 0 or int(msg_dict.get("envelope_pow", 0) or 0) > 0
            )
        except Exception:
            paid = True

        reason = None
        max_topic = get_max_topic_size()
        if len(topic) > max_topic:
            reason = f"invalid topic length {len(topic)} > {max_topic}"

        if not reason:
            if target:
                # Comments don't require titles
                pass
            else:
                min_title = get_min_title_size()
                max_title = get_max_title_size()
                if not (min_title <= len(title) <= max_title):
                    reason = f"invalid title length {len(title)}"

        if not reason:
            min_content = get_min_content_size()
            max_content = get_max_content_size()
            if not (min_content <= len(content) <= max_content):
                reason = f"invalid content length {len(content)}"

        if reason:
            logger.warning("Rejected post %s: %s", txhash, reason)
            return

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
            tag=tag,
            root_topic=root_topic,
            root_post_id=root_post_id,
            media=media,
        )

        # Update user topic stats for new posts (not edits)
        if not existing and owner and root_topic:
            try:
                self.db.update_user_topic_stats(owner, root_topic, 0, root_post_id, is_new_vote=False, post_increment=1)
            except Exception:
                logger.exception("Failed to update user_topic_stats post_count for %s", txhash)

        # Increment comment_count for all ancestors when a new comment is indexed
        if not existing and target:
            try:
                self.db.increment_ancestor_comment_counts(target)
            except Exception:
                logger.exception("Failed to increment ancestor comment_counts for %s", txhash)

        # Update topic safety stats for root posts only
        try:
            if not target:
                self.db.update_topic_content_stats(root_topic or topic, tag)
        except Exception:
            logger.exception("Failed to update topic_content_stats for %s", txhash)

        if owner:
            autohash = f"auto_{txhash}"
            # Auto-upvote: preference is always 1.0, community is weighted by tier
            community_weight = 1.0
            if WEIGHTED_VOTES:
                profile = self.db.get_profile(owner)
                level = profile[1] if profile else 0
                community_weight = get_vote_weight(level)
            self.db.upsert_auto_vote(autohash, owner, ts, txhash, paid, 1.0, community_weight)

        # Thumbnail discovery for root posts only
        try:
            if not target:
                # v1.12.0: prefer media[0] for thumbnail if available
                thumb = None
                if media:
                    thumb = self.discover_post_thumbnail(media[0])
                if not thumb:
                    # LEGACY (v1.11): First-line media URL extraction for posts created before v1.12.0.
                    # Remove after March 2026 when all old posts have been migrated or expired.
                    thumb = self.discover_post_thumbnail(content)
                if thumb:
                    self.db.update_post_thumbnail(txhash, thumb)
        except Exception:
            # Do not fail indexing if thumbnail discovery fails
            pass

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
                    "topic": topic,
                    "title": title,
                    "content": content,
                    "target": target,
                    "paid": bool(paid),
                },
            )

        # Track quest progress for new posts/comments (not edits)
        if not existing and owner:
            try:
                # Determine action type: root post or comment
                action_type = "comment" if target else "post"
                self.quest_tracker.update_progress(
                    owner,
                    action_type,
                    ts,
                    topic=root_topic,
                    content_length=len(content),
                    root_post_id=root_post_id,
                )
                # Also track unique_topic_post for root posts
                if not target and root_topic:
                    self.quest_tracker.update_progress(
                        owner,
                        "unique_topic_post",
                        ts,
                        topic=root_topic,
                        content_length=len(content),
                    )
            except Exception as e:
                logger.warning("Quest progress tracking failed for post %s: %s", txhash, e)

        # Extract @mentions from content for new posts
        if not existing and owner and content:
            try:
                self._extract_and_store_mentions(content, txhash, owner, ts)
            except Exception:
                logger.exception("Failed to extract mentions for post %s", txhash)

    def _extract_and_store_mentions(self, content: str, post_txhash: str, mentioner_address: str, ts: int):
        """Parse @username mentions from content and store them in the mentions table.

        - Strips code blocks and inline code before matching
        - Resolves usernames to addresses via profiles table
        - Skips self-mentions (mentioner == mentioned)
        - Deduplicates via DB UNIQUE constraint
        """
        if not content or not post_txhash or not mentioner_address:
            return
        # Strip fenced code blocks and inline code so @mentions inside code are ignored
        stripped = _FENCED_CODE_RE.sub("", content)
        stripped = _INLINE_CODE_RE.sub("", stripped)

        raw_usernames = list({m.lower() for m in _MENTION_RE.findall(stripped)})
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
        payload = {
            "target": msg_dict.get("target", ""),
            "direction": int(msg_dict.get("direction", 0) or 0),
        }

        target = str(payload.get("target", "")).lower()
        raw_direction = payload.get("direction")
        try:
            paid = not (
                int(msg_dict.get("envelope_difficulty", 0) or 0) > 0 or int(msg_dict.get("envelope_pow", 0) or 0) > 0
            )
        except Exception:
            paid = True
        txhash = (tx_hash or "").lower()

        if raw_direction not in ALLOWED_DIRECTIONS:
            logger.warning("Rejected vote %s: invalid direction %s", txhash, raw_direction)
            return

        # Reject votes for unknown targets (including neutral/clearing votes)
        if not self.db.post_exists(target):
            logger.warning("Rejected vote %s: target not found", txhash)
            return

        if raw_direction == 0:
            # Neutral/clearing vote - zero-out this voter's vote and weight
            # for this target, but keep an audit record.
            # Also reverse topic and author preferences if there was a previous vote.
            previous_vote = self.db.get_vote_by_owner_target(owner, target)
            prev_vote = 0.0
            if previous_vote:
                _, prev_vote, _ = previous_vote
                if prev_vote != 0:
                    reverse_delta = -1.0 if prev_vote > 0 else 1.0

                    # Reverse topic preference - only for root posts, not comments
                    root_topic, root_post_id = self.db.get_root_topic_for_post(target)
                    is_root_post = root_post_id and target == root_post_id
                    if root_topic and owner and is_root_post:
                        try:
                            self.db.update_preference(owner, "topic", root_topic, reverse_delta, ts)
                            logger.debug(
                                "Reversed topic preference for cleared vote: owner=%s topic=%s delta=%s",
                                owner,
                                root_topic,
                                reverse_delta,
                            )
                        except Exception as e:
                            logger.error(
                                "Error reversing topic preference for cleared vote %s: %s", txhash, e, exc_info=True
                            )

                    # Reverse author preference
                    try:
                        post_owner = self.db.get_post_owner(target)
                        if post_owner:
                            target_author = post_owner.strip().lower()
                            if target_author and owner.lower() != target_author:
                                self.db.update_preference(owner, "author", target_author, reverse_delta, ts)
                                logger.debug(
                                    "Reversed author preference for cleared vote: owner=%s author=%s delta=%s",
                                    owner,
                                    target_author,
                                    reverse_delta,
                                )
                    except Exception as e:
                        logger.error(
                            "Error reversing author preference for cleared vote %s: %s", txhash, e, exc_info=True
                        )

            self.db.upsert_vote(txhash, owner, ts, target, 0.0, 0.0, paid)
            self.log_yaml(
                "Stored vote",
                {
                    "height": int(height),
                    "txhash": txhash,
                    "timestamp": int(ts),
                    "time_iso": self.iso_timestamp(ts),
                    "owner": owner,
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

                # Update user topic stats AFTER calculating (so current vote uses pre-vote stats)
                is_new_vote = previous_vote is None
                self.db.update_user_topic_stats(owner, root_topic, raw_direction, root_post_id, is_new_vote)
            except Exception as e:
                logger.error("Error calculating vote weight for %s: %s", txhash, e, exc_info=True)
                # Fallback: upvotes get 1.0, downvotes get baseline (0)
                user_weight = 1.0 if raw_direction > 0 else (COMMUNITY_VOTE_BASELINE * raw_direction)

        # Update per-user topic preference weights for personalization.
        # Only update topic prefs when voting on ROOT posts, not comments.
        # Voting on a comment reflects opinion of the commenter, not the topic.
        is_root_post = root_post_id and target == root_post_id
        if owner and root_topic and is_root_post:
            try:
                new_delta = 1.0 if raw_direction > 0 else -1.0
                # If there was a previous vote and it's different, calculate the net delta
                if prev_vote != 0 and prev_vote != user_vote:
                    # Reverse old vote and apply new: e.g., +1 to -1 = -1 (reverse) + -1 (new) = -2 delta
                    # But with exponential decay, we just apply the difference
                    old_delta = 1.0 if prev_vote > 0 else -1.0
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

        # Persist both the user vote and the weighted contribution.
        self.db.upsert_vote(txhash, owner, ts, target, user_vote, user_weight, paid)

        # Track quest progress for votes
        if owner and raw_direction != 0:
            try:
                # A vote is only a "change" if there was a non-zero previous vote.
                # If user unvoted (set to 0) first, then votes again, that's a NEW vote.
                is_vote_change = previous_vote is not None and prev_vote != 0
                logger.info(
                    "Vote quest tracking: owner=%s target=%s direction=%s previous_vote=%s prev_vote=%s is_vote_change=%s",
                    owner[:12] if owner else None,
                    target[:12] if target else None,
                    raw_direction,
                    previous_vote is not None,
                    prev_vote,
                    is_vote_change,
                )
                self.quest_tracker.update_progress(
                    owner,
                    "vote",
                    ts,
                    target=target,
                    target_owner=target_author,
                    target_topic=root_topic,
                    vote_direction=raw_direction,
                    vote_is_change=is_vote_change,
                )
                # Also track balanced_vote action type
                self.quest_tracker.update_progress(
                    owner,
                    "balanced_vote",
                    ts,
                    target=target,
                    target_owner=target_author,
                    target_topic=root_topic,
                    vote_direction=raw_direction,
                    vote_is_change=is_vote_change,
                )
            except Exception as e:
                logger.warning("Quest progress tracking failed for vote %s: %s", txhash, e)

        # Track quest progress for received upvotes (post/comment authors)
        if target_author and raw_direction > 0:
            try:
                delta_upvotes = 1 if prev_vote <= 0 else 0
                if delta_upvotes > 0:
                    upvotes, downvotes = self.db.get_target_vote_counts(target)
                    post_row = self.db.get_post(target)
                    if not post_row:
                        raise ValueError(f"Vote {txhash} target not found for content length")
                    content_length = len(post_row[2] or "")
                    target_norm = str(target or "").strip().lower()
                    root_norm = str(root_post_id or "").strip().lower()
                    is_root_target = bool(root_norm) and target_norm == root_norm
                    action_type = "upvotes_received" if is_root_target else "comment_upvotes_received"
                    logger.debug(
                        "Received upvote quest check: target=%s author=%s root_post=%s upvotes=%s downvotes=%s action=%s",
                        target_norm[:12] if target_norm else None,
                        target_author[:12] if target_author else None,
                        root_norm[:12] if root_norm else None,
                        upvotes,
                        downvotes,
                        action_type,
                    )
                    self.quest_tracker.update_progress(
                        target_author,
                        action_type,
                        ts,
                        target=target,
                        root_post_id=root_post_id,
                        content_length=content_length,
                        quality=upvotes,
                        target_owner=owner,
                    )
                    if not is_root_target:
                        self.quest_tracker.update_progress(
                            target_author,
                            "quality_comments",
                            ts,
                            target=target,
                            root_post_id=root_post_id,
                            content_length=content_length,
                            quality=upvotes,
                            target_owner=owner,
                        )
            except Exception as e:
                logger.warning("Quest progress tracking failed for received upvote %s: %s", txhash, e)

        # Build detailed vote log
        vote_log = {
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
        override = str(msg_dict.get("override", "") or "").strip().lower()
        target = str(msg_dict.get("target", "") or "").strip().lower()
        topic = str(msg_dict.get("topic", "") or "")
        logger.info("MsgEdit topic=%s", topic)
        title = str(msg_dict.get("title", "") or "")
        content = str(msg_dict.get("content", "") or "")
        tag = str(msg_dict.get("tag", "") or "")

        # Must reference an existing post/comment
        if not override or len(override) != 64:
            logger.warning("Rejected edit %s: invalid override", tx_hash)
            return
        existing = self.db.get_post(override)
        if not existing:
            logger.warning("Rejected edit %s: override not found", tx_hash)
            return

        # Enforce ownership: only the original owner can edit (admins cannot)
        db_owner = self.db.get_post_owner(override)
        if not db_owner or db_owner.lower() != (owner or "").lower():
            logger.warning("Rejected edit %s: owner mismatch", tx_hash)
            return

        # Determine if root (target empty in DB)
        existing_topic, _, _, existing_target, _, _, existing_created_at, _existing_media_raw = existing
        is_root = not bool(existing_target)
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
        try:
            paid_flag = bool(existing[4])
        except Exception:
            paid_flag = True
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

        # Recompute thumbnail on root edits (content change)
        try:
            if is_root:
                thumb = self.discover_post_thumbnail(content)
                self.db.update_post_thumbnail(override, thumb)
        except Exception:
            pass

        # Re-extract @mentions on edit (delete old, insert new)
        if owner and content:
            try:
                self.db.delete_mentions_for_post(override)
                self._extract_and_store_mentions(content, override, owner, ts)
            except Exception:
                logger.exception("Failed to re-extract mentions for edit %s", tx_hash)

        # Log update
        self.log_yaml(
            "Edited post",
            {
                "height": int(height),
                "txhash": (tx_hash or "").lower(),
                "timestamp": int(ts),
                "time_iso": self.iso_timestamp(ts),
                "owner": owner,
                "override": override,
                "is_root": bool(is_root),
            },
        )

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

            min_username = get_min_username_size()
            max_username = get_max_username_size()
            if len(username) < min_username or len(username) > max_username:
                logger.warning(
                    "Rejected set_username: invalid username length %s (min=%s, max=%s)",
                    len(username),
                    min_username,
                    max_username,
                )
                return

            level = 0

            # Query profile core (without lists)
            key_hex = (f"profiles/{addr}").encode().hex()
            resp_data = self.chain.abci_query('"/store/core/key"', f"0x{key_hex}", timeout=HTTP_TIMEOUT_SHORT)
            result = resp_data.get("result")
            if result:
                response = result.get("response")
                if response:
                    val_b64 = response.get("value")
                    if val_b64:
                        js = base64.b64decode(val_b64).decode()
                        prof = json.loads(js)
                        username = str(prof.get("username", username))
                        level = int(prof.get("level", 0))

            # Query followed moderators separately (split storage)
            moderators = []
            mods_key_hex = (f"plist_mods/{addr}").encode().hex()
            mods_resp = self.chain.abci_query('"/store/core/key"', f"0x{mods_key_hex}", timeout=HTTP_TIMEOUT_SHORT)
            mods_result = mods_resp.get("result")
            if mods_result:
                mods_response = mods_result.get("response")
                if mods_response:
                    mods_val_b64 = mods_response.get("value")
                    if mods_val_b64:
                        mods_js = base64.b64decode(mods_val_b64).decode()
                        moderators = json.loads(mods_js) if mods_js else []

            old = self.db.get_profile(addr)
            self.db.upsert_profile(addr, username, level, ts)
            self.db.set_moderators(addr, moderators)

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
                        "moderators": moderators,
                    },
                )
        except Exception as e:
            logger.error("Error handling MsgSetUsername: %s", e, exc_info=True)

    def _refresh_followed_mods(self, addr: str, ts: int):
        moderators: list[str] = []
        # With split storage, followed_moderators are in plist_mods/{addr}
        key_hex = (f"plist_mods/{addr}").encode().hex()
        resp_data = self.chain.abci_query('"/store/core/key"', f"0x{key_hex}", timeout=HTTP_TIMEOUT_SHORT)
        result = resp_data.get("result")
        if result:
            response = result.get("response")
            if response:
                val_b64 = response.get("value")
                if val_b64:
                    js = base64.b64decode(val_b64).decode()
                    moderators = json.loads(js) if js else []
        self.db.set_moderators(addr, moderators)
        self.db.update_profile_timestamp(addr, ts)
        self.log_yaml(
            "Updated followed moderators",
            {
                "address": addr,
                "timestamp": int(ts),
                "time_iso": self.iso_timestamp(ts),
                "moderators": moderators,
            },
        )

    def _handle_follow_moderator(self, type_url: str, value: bytes, ts: int):
        """Handle MsgFollowModerator."""
        try:
            parsed = MsgFollowModerator()
            parsed.ParseFromString(value)
            msg_dict = MessageToDict(parsed, preserving_proto_field_name=True)
            owner = msg_dict.get("target", "") or derive_owner_from_msg(msg_dict)
            if not owner:
                logger.warning("Rejected follow_moderator: missing owner")
                return
            self._refresh_followed_mods(owner, ts)
        except Exception as e:
            logger.error("Error handling MsgFollowModerator: %s", e, exc_info=True)

    def _handle_unfollow_moderator(self, type_url: str, value: bytes, ts: int):
        """Handle MsgUnfollowModerator."""
        try:
            parsed = MsgUnfollowModerator()
            parsed.ParseFromString(value)
            msg_dict = MessageToDict(parsed, preserving_proto_field_name=True)
            owner = msg_dict.get("target", "") or derive_owner_from_msg(msg_dict)
            if not owner:
                logger.warning("Rejected unfollow_moderator: missing owner")
                return
            self._refresh_followed_mods(owner, ts)
        except Exception as e:
            logger.error("Error handling MsgUnfollowModerator: %s", e, exc_info=True)

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

            self.db.follow_user(owner, user)
            self.log_yaml(
                "Follow user",
                {"owner": owner, "user": user, "timestamp": int(ts), "time_iso": self.iso_timestamp(ts)},
            )
        except Exception as e:
            logger.error("Error handling MsgFollowUser: %s", e, exc_info=True)

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

            self.db.unfollow_user(owner, user)
            self.log_yaml(
                "Unfollow user",
                {"owner": owner, "user": user, "timestamp": int(ts), "time_iso": self.iso_timestamp(ts)},
            )
        except Exception as e:
            logger.error("Error handling MsgUnfollowUser: %s", e, exc_info=True)

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

            self.db.follow_topic(owner, topic)
            self.log_yaml(
                "Follow topic",
                {"owner": owner, "topic": topic, "timestamp": int(ts), "time_iso": self.iso_timestamp(ts)},
            )
        except Exception as e:
            logger.error("Error handling MsgFollowTopic: %s", e, exc_info=True)

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

            self.db.unfollow_topic(owner, topic)
            self.log_yaml(
                "Unfollow topic",
                {"owner": owner, "topic": topic, "timestamp": int(ts), "time_iso": self.iso_timestamp(ts)},
            )
        except Exception as e:
            logger.error("Error handling MsgUnfollowTopic: %s", e, exc_info=True)

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

            self.db.block_post(owner, target)
            self.log_yaml(
                "Block post",
                {"owner": owner, "target": target, "timestamp": int(ts), "time_iso": self.iso_timestamp(ts)},
            )
        except Exception as e:
            logger.error("Error handling MsgBlockPost: %s", e, exc_info=True)

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

            self.db.block_user(owner, target)
            self.log_yaml(
                "Block user",
                {"owner": owner, "target": target, "timestamp": int(ts), "time_iso": self.iso_timestamp(ts)},
            )
        except Exception as e:
            logger.error("Error handling MsgBlockUser: %s", e, exc_info=True)

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

    def _handle_upgrade_level(self, type_url: str, value: bytes, ts: int):
        """Handle MsgUpgradeLevel (user-initiated tier upgrade)."""
        try:
            parsed = MsgUpgradeLevel()
            parsed.ParseFromString(value)
            msg_dict = MessageToDict(parsed, preserving_proto_field_name=True)
            # For MsgUpgradeLevel, derive owner from envelope_pubkey
            owner = derive_owner_from_msg(msg_dict)
            requested_level = int(msg_dict.get("level", 0) or 0)

            if not owner:
                logger.warning("Rejected upgrade_level: could not derive owner")
                return

            # Query the chain for the updated profile (includes subscription_expiry, auto_renew)
            profile_data = self._query_chain_profile(owner)
            if profile_data:
                level = int(profile_data.get("level", requested_level))
                subscription_expiry = int(profile_data.get("subscription_expiry", 0) or 0)
                auto_renew = bool(profile_data.get("auto_renew", False))
                username = profile_data.get("username") or None
                created_at = int(profile_data.get("created_at", 0) or 0)
                is_moderator = bool(profile_data.get("is_moderator", False))
                biography = profile_data.get("biography", "") or ""
                avatar = profile_data.get("avatar", "") or ""
                banner = profile_data.get("banner", "") or ""

                self.db.upsert_profile_full(
                    owner,
                    username,
                    level,
                    created_at,
                    subscription_expiry,
                    auto_renew,
                    is_moderator,
                    biography,
                    avatar,
                    banner,
                    ts,
                )
                self.log_yaml(
                    "User upgraded level",
                    {
                        "owner": owner,
                        "level": level,
                        "subscription_expiry": subscription_expiry,
                        "auto_renew": auto_renew,
                        "timestamp": int(ts),
                        "time_iso": self.iso_timestamp(ts),
                    },
                )
            else:
                # Fallback: just update level
                existing = self.db.get_profile(owner)
                if existing:
                    self.db.update_profile_subscription(owner, requested_level, 0, False, ts)
                else:
                    self.db.upsert_profile(owner, None, requested_level, ts)
                self.log_yaml(
                    "User upgraded level (chain query failed)",
                    {
                        "owner": owner,
                        "level": requested_level,
                        "timestamp": int(ts),
                        "time_iso": self.iso_timestamp(ts),
                    },
                )
        except Exception as e:
            logger.error("Error handling upgrade_level: %s", e, exc_info=True)

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
                logger.warning("Rejected set_auto_renewal: could not derive owner")
                return

            # Query the chain for the updated profile (includes subscription_expiry, auto_renew)
            profile_data = self._query_chain_profile(owner)
            if profile_data:
                level = int(profile_data.get("level", 0) or 0)
                subscription_expiry = int(profile_data.get("subscription_expiry", 0) or 0)
                auto_renew = bool(profile_data.get("auto_renew", requested_flag))
                username = profile_data.get("username") or None
                created_at = int(profile_data.get("created_at", 0) or 0)
                is_moderator = bool(profile_data.get("is_moderator", False))
                biography = profile_data.get("biography", "") or ""
                avatar = profile_data.get("avatar", "") or ""
                banner = profile_data.get("banner", "") or ""

                self.db.upsert_profile_full(
                    owner,
                    username,
                    level,
                    created_at,
                    subscription_expiry,
                    auto_renew,
                    is_moderator,
                    biography,
                    avatar,
                    banner,
                    ts,
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
            else:
                existing = self.db.get_profile(owner)
                if existing:
                    # Fallback: only toggle auto_renew flag when chain query fails
                    self.db.update_profile_subscription(
                        owner,
                        existing.level,
                        existing.subscription_expiry,
                        requested_flag,
                        ts,
                    )
                self.log_yaml(
                    "User set auto_renewal (chain query failed)",
                    {
                        "owner": owner,
                        "requested_auto_renew": requested_flag,
                        "timestamp": int(ts),
                        "time_iso": self.iso_timestamp(ts),
                    },
                )
        except Exception as e:
            logger.error("Error handling set_auto_renewal: %s", e, exc_info=True)

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

    def _query_chain_profile(self, addr: str) -> dict | None:
        """Query the chain for a profile's current state."""
        try:
            key_hex = (f"profiles/{addr}").encode().hex()
            resp_data = self.chain.abci_query('"/store/core/key"', f"0x{key_hex}", timeout=HTTP_TIMEOUT_SHORT)
            result = resp_data.get("result")
            if result:
                response = result.get("response")
                if response:
                    val_b64 = response.get("value")
                    if val_b64:
                        return json.loads(base64.b64decode(val_b64).decode())
        except Exception as e:
            logger.warning("Failed to query chain profile for %s: %s", addr, e)
        return None

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
    def _is_public_http_url(raw: str) -> bool:
        try:
            u = urlparse(raw)
            if u.scheme not in ("http", "https"):
                return False
            host = (u.hostname or "").strip()
            if not host:
                return False
            infos = socket.getaddrinfo(host, 80, proto=socket.IPPROTO_TCP)
            if not infos:
                return False
            for info in infos:
                ip_str = info[4][0]
                ip = ipaddress.ip_address(ip_str)
                if (
                    ip.is_private
                    or ip.is_loopback
                    or ip.is_link_local
                    or ip.is_multicast
                    or ip.is_reserved
                    or ip.is_unspecified
                ):
                    return False
            return True
        except Exception:
            return False

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

    @staticmethod
    def _fetch_html(url: str) -> str | None:
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }
            resp = requests.get(url, headers=headers, timeout=5)
            if resp.status_code != 200:
                return None
            ct = resp.headers.get("content-type", "")
            if "text/html" not in ct and "application/xhtml+xml" not in ct:
                return None
            text = resp.text
            return text[:1_500_000]
        except Exception:
            return None

    @staticmethod
    def _probe_dimensions(url: str, max_bytes: int = 2_000_000) -> tuple[int, int] | None:
        try:
            headers = {"User-Agent": "MirageIndexer/1.0", "Accept": "*/*"}
            resp = requests.get(url, headers=headers, timeout=5, stream=True)
            if resp.status_code != 200:
                return None
            total = 0
            buf = BytesIO()
            for chunk in resp.iter_content(chunk_size=65536):
                if not chunk:
                    break
                buf.write(chunk)
                total += len(chunk)
                if total >= max_bytes:
                    break
            buf.seek(0)
            with Image.open(buf) as im:
                return int(im.width), int(im.height)
        except Exception:
            return None

    @staticmethod
    def _normalize(base: str, href: str | None) -> str | None:
        if not href:
            return None
        try:
            out = urljoin(base, href)
            return out
        except Exception:
            return None

    def discover_post_thumbnail(self, content: str) -> str | None:
        """Discover a thumbnail for root post content. Returns absolute image URL or None."""
        first = self._extract_first_url(content or "")
        if not first:
            logger.debug("[thumb] no URL found in content")
            return None
        if not self._is_public_http_url(first):
            logger.debug("[thumb] first URL not public http(s): %s", first)
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
        # YouTube video -> derive thumbnail
        yt_id = self._extract_youtube_video_id(first)
        if yt_id:
            logger.debug("[thumb] derived youtube thumb for video_id=%s", yt_id)
            return f"https://img.youtube.com/vi/{yt_id}/hqdefault.jpg"
        # Fetch and parse HTML
        html = self._fetch_html(first)
        if not html:
            logger.debug("[thumb] fetch_html returned empty for %s", first)
            return None
        try:
            soup = BeautifulSoup(html, "html.parser")
        except Exception:
            logger.debug("[thumb] BeautifulSoup parse failed for %s", first)
            return None

        candidates: list[dict[str, str | None]] = []

        def add(u: str | None, w: str | None = None, h: str | None = None):
            if not u:
                return
            norm = self._normalize(first, u)
            if not norm or not self._is_public_http_url(norm):
                return
            candidates.append({"url": norm, "w": w, "h": h})

        for tag in soup.find_all("meta"):
            prop = (tag.get("property") or tag.get("name") or "").lower()
            if prop in ("og:image", "twitter:image", "og:image:url", "og:image:secure_url"):
                add(tag.get("content"))
        for link in soup.find_all("link"):
            rel = (
                " ".join((link.get("rel") or [])).lower()
                if isinstance(link.get("rel"), list)
                else str(link.get("rel") or "").lower()
            )
            if "image_src" in rel or rel == "image_src" or rel == "image":
                add(link.get("href"))
        for meta in soup.find_all(attrs={"itemprop": "image"}):
            add(meta.get("content") or meta.get("src"))
        for img in soup.find_all("img"):
            add(
                img.get("src") or img.get("data-src"),
                img.get("width") or img.get("data-width"),
                img.get("height") or img.get("data-height"),
            )
        # Fallback: scan raw HTML for direct image URLs (covers cases like Redgifs media.* jpgs)
        try:
            for m in re.findall(r'https?://[^\s"<>\']+\.(?:jpg|jpeg|png|webp)', html, flags=re.IGNORECASE):
                add(m)
        except Exception:
            pass

        # Unique
        seen = set()
        uniq = []
        for c in candidates:
            u = c.get("url")
            if u and u not in seen:
                seen.add(u)
                uniq.append(c)

        logger.debug("[thumb] candidate count=%d first=%s", len(uniq), (uniq[0]["url"] if uniq else ""))

        # Prefer known large images
        for c in uniq:
            try:
                w = int(c.get("w") or "0")
                h = int(c.get("h") or "0")
            except Exception:
                w = h = 0
            if w >= 600 and h >= 400:
                return c["url"]  # type: ignore[index]

        # Probe a few
        for c in uniq[:6]:
            u = c.get("url")
            if not u:
                continue
            dims = self._probe_dimensions(u)
            if dims and dims[0] >= 600 and dims[1] >= 400:
                return u

        return uniq[0].get("url") if uniq else None

    @staticmethod
    def extract_inner_messages(parsed: MsgSubmitProposal) -> list:
        """Extract inner messages from MsgSubmitProposal with fallback for different proto versions."""
        try:
            return parsed.messages
        except AttributeError:
            try:
                return parsed.msgs
            except AttributeError:
                return []

    @staticmethod
    def extract_proposal_id(attrs: dict) -> int | None:
        """Extract proposal_id from event attributes with multiple fallback names."""
        pid = attrs.get("proposal_id") or attrs.get("proposalID") or attrs.get("proposal-id") or attrs.get("proposalId")
        if pid is None:
            return None
        return int(pid)

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
                key_b64 = attr.get("key") if isinstance(attr, dict) else None
                val_b64 = attr.get("value") if isinstance(attr, dict) else None
                if key_b64:
                    try:
                        key = base64.b64decode(key_b64, validate=True).decode("utf-8")
                    except Exception:
                        if isinstance(key_b64, bytes):
                            key = key_b64.decode("utf-8")
                        else:
                            key = str(key_b64)
                    if key:
                        if val_b64:
                            try:
                                val = base64.b64decode(val_b64, validate=True).decode("utf-8")
                            except Exception:
                                if isinstance(val_b64, bytes):
                                    val = val_b64.decode("utf-8")
                                else:
                                    val = str(val_b64)
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

    def process_tx_events(self, events: list, tx_hash: str = "") -> None:
        """Process per-tx events for bridge confirmation updates and power info.

        Args:
            events: List of events from the transaction
            tx_hash: The transaction hash (used to update power on attestation records)
        """
        if not events:
            return
        for ev_type, attrs in self.decode_events(events):
            # Handle inbound bridge mint completion (bridge_mint event)
            # This is emitted when threshold is reached and tokens are minted on Mirage
            if ev_type == "bridge_mint":
                source_chain = str(attrs.get("source_chain", "") or "").strip()
                burn_id = str(attrs.get("burn_id", "") or "").strip()
                recipient = str(attrs.get("recipient", "") or "").strip()
                amount = str(attrs.get("amount", "") or "").strip()
                attested_power = str(attrs.get("attested_power", "") or "").strip()
                required_power = str(attrs.get("required_power", "") or "").strip()
                if not source_chain or not burn_id:
                    logger.warning("bridge_mint event missing identifiers: %s", attrs)
                    continue
                updated = self.db.update_bridge_attestation_minted(source_chain, burn_id, True)
                logger.info(
                    "Bridge mint event (inbound complete): %s:%s -> %s amount=%s power=%s/%s updated=%s",
                    source_chain,
                    burn_id,
                    recipient,
                    amount,
                    attested_power,
                    required_power,
                    updated,
                )

            # Handle inbound bridge attestations (bridge_attest event)
            # This event is emitted for every attestation with power info
            elif ev_type == "bridge_attest":
                source_chain = str(attrs.get("source_chain", "") or "").strip()
                burn_id = str(attrs.get("burn_id", "") or "").strip()
                validator = str(attrs.get("validator", "") or "").strip()
                power = int(attrs.get("power", 0) or 0)
                attested_power = int(attrs.get("attested_power", 0) or 0)
                required_power = int(attrs.get("required_power", 0) or 0)
                minted_raw = str(attrs.get("minted", "") or "").strip().lower()
                minted = minted_raw in ("true", "1", "t", "yes")

                if not source_chain or not burn_id:
                    logger.warning("bridge_attest event missing identifiers: %s", attrs)
                    continue

                # Update power info on the attestation record by tx_hash
                updated = False
                if tx_hash:
                    updated = self.db.update_bridge_attestation_power_by_tx(
                        tx_hash=tx_hash,
                        msg_type="attest_burned",
                        power=power,
                        attested_power=attested_power,
                        required_power=required_power,
                    )
                logger.info(
                    "Bridge attest event (inbound): %s:%s tx=%s validator=%s power=%d attested=%d/%d minted=%s updated=%s",
                    source_chain,
                    burn_id,
                    tx_hash[:16] if tx_hash else "?",
                    validator,
                    power,
                    attested_power,
                    required_power,
                    minted,
                    updated,
                )

                # If threshold reached, also update minted status
                if minted:
                    self.db.update_bridge_attestation_minted(source_chain, burn_id, True)

            # Handle outbound bridge attestations (bridge_attest_minted event)
            elif ev_type == "bridge_attest_minted":
                burn_id = str(attrs.get("burn_id", "") or "").strip()
                mirage_tx_hash = str(attrs.get("mirage_tx_hash", "") or "").strip().lower()
                validator = str(attrs.get("validator", "") or "").strip()
                power = int(attrs.get("power", 0) or 0)
                attested_power = int(attrs.get("attested_power", 0) or 0)
                required_power = int(attrs.get("required_power", 0) or 0)
                minted_raw = str(attrs.get("minted", "") or "").strip().lower()
                minted = minted_raw in ("true", "1", "t", "yes")

                # Use mirage_tx_hash for DB linking (matches burn record's tx_hash)
                effective_burn_id = mirage_tx_hash if mirage_tx_hash else burn_id
                if not effective_burn_id:
                    logger.warning("bridge_attest_minted event missing identifiers: %s", attrs)
                    continue

                # Update power info on the attestation record by tx_hash
                updated = False
                if tx_hash:
                    updated = self.db.update_bridge_attestation_power_by_tx(
                        tx_hash=tx_hash,
                        msg_type="attest_minted",
                        power=power,
                        attested_power=attested_power,
                        required_power=required_power,
                    )
                logger.info(
                    "Bridge attest minted event (outbound): burn_id=%s tx=%s validator=%s power=%d attested=%d/%d minted=%s updated=%s",
                    effective_burn_id,
                    tx_hash[:16] if tx_hash else "?",
                    validator,
                    power,
                    attested_power,
                    required_power,
                    minted,
                    updated,
                )

                # If threshold reached, also update minted status
                if minted:
                    self.db.update_bridge_mint_attestation_confirmed(effective_burn_id, True)

    # ========== Bridge Message Handlers ==========

    def _handle_bridge_burn(self, type_url: str, value: bytes, tx_hash: str, ts: int, height: int):
        """Handle MsgBridgeBurn (outbound bridge: Mirage -> external chain)."""
        try:
            parsed = MsgBridgeBurn()
            parsed.ParseFromString(value)
            msg_dict = MessageToDict(parsed, preserving_proto_field_name=True)

            # For outbound burns, the burn_id is the tx_hash
            destination_chain = str(msg_dict.get("destination_chain", "") or "")
            destination_address = str(msg_dict.get("destination_address", "") or "")
            amount = int(msg_dict.get("amount", 0) or 0)

            # Derive sender from envelope pubkey
            sender = derive_owner_from_msg(msg_dict)

            self.db.insert_bridge_transaction(
                tx_hash=tx_hash,
                direction="out",
                msg_type="burn",
                burn_id=tx_hash,  # For outbound, burn_id = tx_hash
                amount=amount,
                created_at=ts,
                height=height,
                destination_chain=destination_chain,
                recipient=destination_address,
                sender=sender,
            )

            logger.debug(f"Indexed bridge burn: {tx_hash} -> {destination_chain}:{destination_address} amount={amount}")
        except Exception as e:
            logger.error(f"Failed to index bridge burn {tx_hash}: {e}")

    def _handle_bridge_attest_burned(self, type_url: str, value: bytes, tx_hash: str, ts: int, height: int):
        """Handle MsgBridgeAttestBurned (inbound bridge: external chain -> Mirage).

        Mint confirmation must come from chain state/events; we do not infer it here.
        """
        try:
            parsed = MsgBridgeAttestBurned()
            parsed.ParseFromString(value)
            msg_dict = MessageToDict(parsed, preserving_proto_field_name=True)

            validator = str(msg_dict.get("validator", "") or "")
            source_chain = str(msg_dict.get("source_chain", "") or "")
            burn_id = str(msg_dict.get("burn_id", "") or "")
            mirage_recipient = str(msg_dict.get("mirage_recipient", "") or "")
            amount = int(msg_dict.get("amount", 0) or 0)

            self.db.insert_bridge_transaction(
                tx_hash=tx_hash,
                direction="in",
                msg_type="attest_burned",
                burn_id=burn_id,
                amount=amount,
                created_at=ts,
                height=height,
                source_chain=source_chain,
                recipient=mirage_recipient,
                validator=validator,
                minted=False,  # Only set true when chain confirms mint via BridgeConfirmed event
            )

            logger.info(
                f"Indexed bridge attest burned: {source_chain}:{burn_id} validator={validator} -> {mirage_recipient} amount={amount}"
            )
        except Exception as e:
            logger.error(f"Failed to index bridge attest burned {tx_hash}: {e}")

    def _handle_bridge_attest_minted(self, type_url: str, value: bytes, tx_hash: str, ts: int, height: int):
        """Handle MsgBridgeAttestMinted (validator attests mint on external chain for outbound burns).

        The burn_id in the message is the sequence number, but we use mirage_tx_hash
        for linking to the original burn transaction in the indexer database.
        """
        try:
            parsed = MsgBridgeAttestMinted()
            parsed.ParseFromString(value)
            msg_dict = MessageToDict(parsed, preserving_proto_field_name=True)

            validator = str(msg_dict.get("validator", "") or "")
            burn_id_seq = str(msg_dict.get("burn_id", "") or "")  # This is the sequence number
            destination_chain = str(msg_dict.get("destination_chain", "") or "")
            destination_tx = str(msg_dict.get("destination_tx", "") or "")
            # mirage_tx_hash is the original Mirage burn tx hash - use this for DB linking
            mirage_tx_hash = str(msg_dict.get("mirage_tx_hash", "") or "").lower()

            # Use mirage_tx_hash as burn_id for DB linking (matches the burn record's tx_hash)
            # Fall back to burn_id_seq if mirage_tx_hash is empty (shouldn't happen in normal operation)
            effective_burn_id = mirage_tx_hash if mirage_tx_hash else burn_id_seq

            # Record the attestation (confirmation status comes from BridgeConfirmed event)
            self.db.insert_bridge_transaction(
                tx_hash=tx_hash,
                direction="out",
                msg_type="attest_minted",
                burn_id=effective_burn_id,
                amount=0,  # Amount is in the original burn event
                created_at=ts,
                height=height,
                destination_chain=destination_chain,
                destination_tx=destination_tx,
                validator=validator,
                minted=False,  # Only set true via BridgeConfirmed event
            )

            logger.info(
                f"Indexed bridge attest minted: burn_id={effective_burn_id} (seq={burn_id_seq}) validator={validator} -> {destination_chain} tx={destination_tx}"
            )
        except Exception as e:
            logger.error(f"Failed to index bridge attest minted {tx_hash}: {e}")
