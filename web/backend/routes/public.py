from __future__ import annotations

"""Public-facing routes.

Endpoints:
- GET /api/get_parameters: Latest block hash, difficulty, optional balance.
- GET /api/get_chain_config: Chain governance params (tiers, limits, subscription_period).
- GET /api/get_node_config: Per-node static settings (validator info, feature flags).
- GET /api/get_tx_status: Unified tx status with type-specific enrichment.
- GET /api/get_address_from_username: Get address for a username if it exists.
- GET /api/get_topics: List most active topics, excluding deleted messages.
- GET /api/get_posts: List recent posts with aggregates.
- GET /api/get_user_posts: List recent posts for a specific owner.
- GET /api/get_comments: Root post and nested comments tree.
"""

import json
import os
import re
from db import connect_db

from typing import Any, Dict, List, Optional

import requests
from flask import Blueprint, jsonify, request

from error_utils import safe_error
from logging_utils import log_event, next_request_id
from node import require_runtime, find_local_operator_address, find_local_consensus_address
from params import load_params, expect_params
from settings import (
    IGNORE_DELETIONS,
    IGNORE_MOD_BLOCKED_POSTS,
    IGNORE_MOD_BLOCKED_USERS,
    REGISTRATION_ENABLED,
    REGISTRATION_INVITE_CODE_REQUIRED,
    QUESTS_ENABLED,
    QUESTS_PAYOUTS_ENABLED,
)
import time
import hashlib
import math
from urllib.parse import urljoin, urlparse
from chain import (
    classify_reject as _classify_reject,
    get_block_time_seconds as _get_block_time_seconds,
    get_current_pow_difficulty as _get_current_pow_difficulty,
    get_difficulty_info as _get_difficulty_info,
    get_latest_block_hash as _latest_block_hash,
    get_pow_base_bits as _get_pow_base_bits,
    get_pow_factor as _get_pow_factor,
    is_node_catching_up as _is_catching_up,
    get_connected_peers as _get_connected_peers,
)
from bank import (
    get_balance as _get_balance,
    get_total_supply as _get_total_supply,
    get_balances_batch as _get_balances_batch,
    get_staked_balance as _get_staked_balance,
    get_validator as _get_validator,
)
import base64
import urllib.request as _ur
import urllib.parse as _up
from user_agents import parse as parse_user_agent


def _inject_balance(resp: dict, addr: str) -> dict:
    """Add balance to response dict if address is provided."""
    if addr and addr.lower() != "guest":
        try:
            resp["balance"] = int(_get_balance(addr))
        except Exception:
            pass
    return resp


def _query_chain_profile(addr: str) -> dict | None:
    """Query the chain directly for a profile's current state (including real-time subscription_expiry)."""
    try:
        rpc = require_runtime().rpc_url
        key_hex = f"profiles/{addr}".encode().hex()
        # Tendermint ABCI expects the path quoted as a JSON string in the URL
        path = _up.quote('"/store/core/key"')
        url = f"{rpc}/abci_query?path={path}&data=0x{key_hex}"
        with _ur.urlopen(url, timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        value_b64 = (((data or {}).get("result") or {}).get("response") or {}).get("value")
        if value_b64:
            return json.loads(base64.b64decode(value_b64).decode())
    except Exception:
        pass
    return None


def _query_chain_profile_full(addr: str) -> dict | None:
    """Query the chain gRPC-gateway for full profile including all lists."""
    try:
        rt = require_runtime()
        api_url = rt.api_url.rstrip("/")
        url = f"{api_url}/mirage/core/v1/profile/{addr.lower()}"
        with _ur.urlopen(url, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data
    except Exception:
        pass
    return None


public_bp = Blueprint("public", __name__)


def _deleted_filter() -> str:
    """Return SQL clause to filter deleted posts, or empty string if IGNORE_DELETIONS is enabled."""
    return "" if IGNORE_DELETIONS else "AND p.deleted = FALSE"


def _deleted_filter_bare() -> str:
    """Return SQL clause to filter deleted posts without table prefix."""
    return "" if IGNORE_DELETIONS else "AND deleted = FALSE"


# Allowed content tags used for topic safety classification
_TOPIC_TAGS = ("sensitive", "gore", "violence", "death", "porn")


def _compute_dominant_flags(cur, topics_lower: list[str]) -> dict[str, dict]:
    """Return dominant tag info for a list of lowercase topics, computed live from posts."""
    if not topics_lower:
        return {}
    try:
        cur.execute(
            """
            SELECT
                LOWER(TRIM(p.topic)) AS topic,
                COUNT(1) AS total_posts,
                SUM(CASE WHEN LOWER(COALESCE(p.tag, '')) = 'sensitive' THEN 1 ELSE 0 END) AS sensitive_count,
                SUM(CASE WHEN LOWER(COALESCE(p.tag, '')) = 'gore' THEN 1 ELSE 0 END) AS gore_count,
                SUM(CASE WHEN LOWER(COALESCE(p.tag, '')) = 'violence' THEN 1 ELSE 0 END) AS violence_count,
                SUM(CASE WHEN LOWER(COALESCE(p.tag, '')) = 'death' THEN 1 ELSE 0 END) AS death_count,
                SUM(CASE WHEN LOWER(COALESCE(p.tag, '')) = 'porn' THEN 1 ELSE 0 END) AS porn_count
            FROM posts p
            WHERE COALESCE(p.target, '') = ''
              AND p.topic IS NOT NULL
              AND LOWER(TRIM(p.topic)) = ANY(%s)
              AND p.deleted = FALSE
            GROUP BY LOWER(TRIM(p.topic))
            """,
            (topics_lower,),
        )
        result = {}
        for row in cur.fetchall():
            topic = row[0]
            total = float(row[1] or 0)
            counts = {
                "sensitive": float(row[2] or 0),
                "gore": float(row[3] or 0),
                "violence": float(row[4] or 0),
                "death": float(row[5] or 0),
                "porn": float(row[6] or 0),
            }
            dominant_tag = ""
            dominant_ratio = 0.0
            if total > 0:
                for k, v in counts.items():
                    ratio = v / total
                    if ratio >= 0.5 and ratio > dominant_ratio:
                        dominant_tag = k
                        dominant_ratio = ratio
            result[topic] = {"dominant_tag": dominant_tag or None, "dominant_ratio": dominant_ratio}
        return result
    except Exception:
        return {}


# Removed runtime schema migrations (no backfills, hard-fail policy)


# Basic direct-image detection and backfill (no remote HTML parsing here)
_IMG_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".avif")


# LEGACY (v1.11): First-line media URL extraction for posts created before v1.12.0.
# Remove after March 2026 when all old posts have been migrated or expired.
def _extract_first_url(text: str) -> str:
    try:
        if not text or not isinstance(text, str):
            return ""
        m = re.search(r"https?://[^\s<>'\"]+", text)
        return m.group(0) if m else ""
    except Exception:
        return ""


def _is_direct_image_url(url: str) -> bool:
    try:
        if not url:
            return False
        u = urlparse(url)
        host = (u.hostname or "").lower()
        path = (u.path or "").lower()
        if host.endswith("imagedelivery.net"):
            return True
        return any(path.endswith(ext) for ext in _IMG_EXTS)
    except Exception:
        return False


def _stream_uid_from_url(url: str) -> str | None:
    try:
        if not url:
            return None
        u = urlparse(url)
        host = (u.hostname or "").lower()
        path = (u.path or "").strip("/")
        if host.endswith("videodelivery.net"):
            parts = path.split("/")
            if parts and re.fullmatch(r"[a-z0-9]+", parts[0]):
                return parts[0]
        if host.endswith("cloudflarestream.com"):
            parts = path.split("/")
            if parts and re.fullmatch(r"[a-z0-9]+", parts[0]):
                return parts[0]
    except Exception:
        return None
    return None


def _youtube_video_id_from_url(url: str) -> str | None:
    try:
        if not url:
            return None
        u = urlparse(url)
        host = (u.hostname or "").lower()
        if host in ("www.youtube.com", "youtube.com", "m.youtube.com"):
            if u.path == "/watch":
                from urllib.parse import parse_qs

                qs = parse_qs(u.query)
                v = qs.get("v")
                if v and v[0]:
                    return v[0]
            if u.path.startswith("/embed/") or u.path.startswith("/v/"):
                parts = u.path.split("/")
                if len(parts) >= 3 and parts[2]:
                    return parts[2].split("?")[0]
            if u.path.startswith("/shorts/"):
                parts = u.path.split("/")
                if len(parts) >= 3 and parts[2]:
                    return parts[2].split("?")[0]
        if host in ("youtu.be", "www.youtu.be"):
            path = (u.path or "").strip("/")
            if path:
                return path.split("/")[0].split("?")[0]
    except Exception:
        return None
    return None


# Note: thumbnail discovery moved to the indexer. No public endpoint is exposed.


@public_bp.route("/api/reload_params", methods=["POST"])
def reload_params():
    """Force reload chain parameters from live chain state."""
    rid = next_request_id()
    try:
        rt = require_runtime()
        load_params(force=True)
        params = expect_params()
        log_event(rid, "reload_params.success", params_keys=list(params.keys()))
        return jsonify({"status": "ok", "params": params})
    except Exception as e:
        log_event(rid, "reload_params.error", error=str(e))
        return safe_error(e)


def _get_followed_moderators(cur, address: str) -> list[str]:
    """Get list of moderator addresses followed by the viewer."""
    if not address:
        return []
    cur.execute("SELECT moderator FROM followed_mods WHERE owner = %s", (address.lower(),))
    return [row[0].lower() for row in cur.fetchall()]


def _get_blocked_posts(cur, address: str) -> set[str]:
    """Get all post txhashes blocked by the viewer and their followed moderators."""
    if not address:
        return set()

    blocked_posts = set()

    # Get viewer's own blocked posts
    cur.execute("SELECT target FROM blocked_posts WHERE owner = %s", (address.lower(),))
    blocked_posts.update(row[0].lower() for row in cur.fetchall())

    # Get blocked posts from followed moderators (unless IGNORE_MOD_BLOCKED_POSTS is enabled)
    if not IGNORE_MOD_BLOCKED_POSTS:
        moderators = _get_followed_moderators(cur, address)
        for mod_address in moderators:
            cur.execute("SELECT target FROM blocked_posts WHERE owner = %s", (mod_address.lower(),))
            blocked_posts.update(row[0].lower() for row in cur.fetchall())

    return blocked_posts


def _get_blocked_users(cur, address: str) -> set[str]:
    """Get all user addresses blocked by the viewer and their followed moderators."""
    if not address:
        return set()

    blocked_users = set()

    # Get viewer's own blocked users
    cur.execute("SELECT target FROM blocked_users WHERE owner = %s", (address.lower(),))
    blocked_users.update(row[0].lower() for row in cur.fetchall())

    # Get blocked users from followed moderators (unless IGNORE_MOD_BLOCKED_USERS is enabled)
    if not IGNORE_MOD_BLOCKED_USERS:
        moderators = _get_followed_moderators(cur, address)
        for mod_address in moderators:
            cur.execute("SELECT target FROM blocked_users WHERE owner = %s", (mod_address.lower(),))
            blocked_users.update(row[0].lower() for row in cur.fetchall())

    return blocked_users


def _get_blocked_topics(cur, address: str) -> set[str]:
    """Get all topics blocked by the viewer and their followed moderators."""
    if not address:
        return set()

    blocked_topics = set()

    # Get viewer's own blocked topics
    cur.execute("SELECT target FROM blocked_topics WHERE owner = %s", (address.lower(),))
    blocked_topics.update(row[0].lower() for row in cur.fetchall())

    # Get blocked topics from followed moderators
    moderators = _get_followed_moderators(cur, address)
    for mod_address in moderators:
        cur.execute("SELECT target FROM blocked_topics WHERE owner = %s", (mod_address.lower(),))
        blocked_topics.update(row[0].lower() for row in cur.fetchall())

    return blocked_topics


# ---- Inbox count cache (60s TTL per address; stores count + last_viewed_at) ----
_inbox_cache: dict[str, tuple[int, float, int]] = {}
_INBOX_CACHE_TTL = 60.0
_INBOX_CACHE_MAX = 10000


def _get_new_inbox_count(cur, address: str) -> int:
    """Count replies + @mentions to user's posts that arrived after their last inbox view.
    Results are cached in-memory for 60s per address."""
    if not address or address.lower() == "guest":
        return 0

    viewer = address.lower()
    now = time.time()

    cached = _inbox_cache.get(viewer)
    if cached and cached[1] > now:
        return cached[0]

    last_seen = 0
    reply_count = 0
    mention_count = 0
    try:
        # Count new replies
        cur.execute(
            """
            SELECT pr.inbox_last_viewed_at,
                   COUNT(r.txhash)
            FROM profiles pr
            LEFT JOIN posts p ON LOWER(p.owner) = LOWER(pr.owner)
            LEFT JOIN posts r
              ON r.target = p.txhash
             AND LOWER(r.owner) != LOWER(pr.owner)
             AND r.deleted = FALSE
             AND r.created_at > pr.inbox_last_viewed_at
            WHERE LOWER(pr.owner) = %s
            GROUP BY pr.inbox_last_viewed_at
            """,
            (viewer,),
        )
        row = cur.fetchone()
        last_seen = int(row[0]) if row and row[0] else 0
        reply_count = int(row[1]) if row and row[1] else 0
    except Exception:
        last_seen = 0
        reply_count = 0

    try:
        # Count new @mentions
        cur.execute(
            """
            SELECT COUNT(*) FROM mentions m
            JOIN posts p ON p.txhash = m.post_txhash AND p.deleted = FALSE
            WHERE LOWER(m.mentioned_address) = %s
              AND LOWER(m.mentioner_address) != %s
              AND m.created_at > %s
            """,
            (viewer, viewer, last_seen),
        )
        mrow = cur.fetchone()
        mention_count = int(mrow[0]) if mrow and mrow[0] else 0
    except Exception:
        mention_count = 0

    count = reply_count + mention_count

    # Evict expired entries if cache is too large
    if len(_inbox_cache) >= _INBOX_CACHE_MAX:
        expired = [k for k, v in _inbox_cache.items() if v[1] <= now]
        for k in expired:
            del _inbox_cache[k]
        # If still too large after eviction, clear entirely
        if len(_inbox_cache) >= _INBOX_CACHE_MAX:
            _inbox_cache.clear()

    _inbox_cache[viewer] = (count, now + _INBOX_CACHE_TTL, last_seen)
    return count


def _invalidate_inbox_cache(address: str) -> None:
    """Remove a user's inbox count from cache so it refreshes immediately."""
    _inbox_cache.pop(address.lower(), None)


@public_bp.route("/api/get_blocked_users")
def get_blocked_users():
    address = request.args.get("address", default="", type=str)
    if not address:
        return jsonify({"error": "address is required"}), 400

    try:
        conn = connect_db(timeout=10.0, busy_timeout_ms=15000)
        cur = conn.cursor()

        # Get only the user's own blocked users (not moderators')
        cur.execute("SELECT target FROM blocked_users WHERE owner = %s", (address.lower(),))
        blocked_users = [row[0] for row in cur.fetchall()]

        conn.close()
        return jsonify({"blocked_users": blocked_users})
    except Exception as e:
        return safe_error(e)


@public_bp.route("/api/get_profile")
def get_profile():
    """Get full profile from blockchain including all lists (followed_users, followed_topics, etc.)."""
    address = request.args.get("address", default="", type=str)
    if not address:
        return jsonify({"error": "address is required"}), 400

    try:
        if _is_catching_up():
            return jsonify({"error": "node_catching_up"}), 503

        profile = _query_chain_profile_full(address.lower())
        if not profile:
            resp = {
                "owner": address.lower(),
                "username": "",
                "level": 0,
                "followed_users": [],
                "followed_topics": [],
                "followed_moderators": [],
                "blocked_users": [],
                "blocked_posts": [],
                "blocked_topics": [],
            }
            return jsonify(_inject_balance(resp, address))

        resp = {
            "owner": profile.get("owner", address.lower()),
            "username": profile.get("username", ""),
            "level": int(profile.get("level", 0)),
            "created_at": int(profile.get("created_at", 0) or profile.get("createdAt", 0)),
            "subscription_expiry": int(profile.get("subscription_expiry", 0) or profile.get("subscriptionExpiry", 0)),
            "auto_renew": bool(profile.get("auto_renew", False) or profile.get("autoRenew", False)),
            "reserve_funds": int(profile.get("reserve_funds", 0) or profile.get("reserveFunds", 0)),
            "is_moderator": bool(profile.get("is_moderator", False) or profile.get("isModerator", False)),
            "biography": profile.get("biography", ""),
            "avatar": profile.get("avatar", ""),
            "banner": profile.get("banner", ""),
            "followed_users": profile.get("followed_users", []) or profile.get("followedUsers", []) or [],
            "followed_topics": profile.get("followed_topics", []) or profile.get("followedTopics", []) or [],
            "followed_moderators": profile.get("followed_moderators", [])
            or profile.get("followedModerators", [])
            or [],
            "blocked_users": profile.get("blocked_users", []) or profile.get("blockedUsers", []) or [],
            "blocked_posts": profile.get("blocked_posts", []) or profile.get("blockedPosts", []) or [],
            "blocked_topics": profile.get("blocked_topics", []) or profile.get("blockedTopics", []) or [],
        }
        return jsonify(_inject_balance(resp, address))
    except Exception as e:
        return safe_error(e)


# ============================================================================
# HOME FEED V2: Similarity-based algorithm
# ============================================================================


def _load_user_preferences(cur, viewer: str) -> tuple[dict, dict]:
    """Load topic and author preferences for a user."""
    viewer_lower = viewer.strip().lower()
    topic_prefs: dict[str, float] = {}
    author_prefs: dict[str, float] = {}

    cur.execute(
        "SELECT pref_type, target, weight FROM preferences WHERE LOWER(owner) = %s",
        (viewer_lower,),
    )
    for pref_type, target, weight in cur.fetchall():
        t = (target or "").strip().lower()
        if not t:
            continue
        try:
            w = float(weight or 0.0)
        except Exception:
            continue
        if pref_type == "topic":
            topic_prefs[t] = w
        elif pref_type == "author":
            author_prefs[t] = w

    return topic_prefs, author_prefs


def _load_candidate_posts(
    cur,
    max_candidates: int,
    blocked_posts: set[str],
    blocked_users: set[str],
    allowed_tags: set[str],
    blocked_topics: set[str] | None = None,
) -> list[dict]:
    """Load recent candidate posts for home feed."""
    deleted_clause = _deleted_filter()

    cur.execute(
        f"""
        SELECT p.txhash, p.owner, p.created_at, p.topic, p.title, p.content,
               COALESCE(p.tag, '') AS tag,
               COALESCE(p.root_topic, p.topic, '') AS root_topic,
               COALESCE(p.root_post_id, p.txhash, '') AS root_post_id,
               COALESCE(pr.username, '') AS username,
               COALESCE(p.edited_at, 0) AS edited_at,
               COALESCE(p.thumbnail_url, '') AS thumbnail,
               COALESCE(pr.level, 0) AS author_level,
               COALESCE(p.media, '[]') AS media
        FROM posts p
        LEFT JOIN profiles pr ON pr.owner = p.owner
        WHERE COALESCE(p.target,'') = ''
          AND LENGTH(COALESCE(p.title,'')) > 0
          {deleted_clause}
        ORDER BY p.created_at DESC
        LIMIT %s
        """,
        (max_candidates,),
    )
    rows = cur.fetchall()

    # Filter blocked posts/users and disallowed tags
    candidates = []
    for row in rows:
        (
            txhash,
            owner,
            ts,
            topic,
            title,
            content,
            tag,
            root_topic,
            root_post_id,
            username,
            edited_at,
            thumbnail,
            author_level,
            media_raw,
        ) = row
        media = json.loads(media_raw)
        if not isinstance(media, list):
            raise ValueError("invalid media payload in posts table")

        pid = (txhash or "").lower()
        author = (owner or "").lower()
        tag_lower = (tag or "").strip().lower()
        topic_raw = (topic or "").strip()
        topic_lower = topic_raw.lower()
        root_topic_raw = (root_topic or topic or "").strip()
        root_topic_lower = root_topic_raw.lower()

        if pid in blocked_posts or author in blocked_users:
            continue
        if blocked_topics and topic_lower in blocked_topics:
            continue
        if tag_lower and tag_lower not in allowed_tags:
            continue
        if not topic_lower:
            continue

        candidates.append(
            {
                "post_id": pid,
                "author": author,
                "user_id": author,
                "username": username or "",
                "author_level": int(author_level) if author_level else 0,
                "timestamp": int(ts) if ts else 0,
                "topic": topic_raw,
                "topic_lower": topic_lower,
                "root_topic": root_topic_raw,
                "root_topic_lower": root_topic_lower,
                "root_post_id": (root_post_id or pid).lower(),
                "title": title or "",
                "content": content or "",
                "tag": tag or "",
                "edited": bool(edited_at),
                "edited_at": int(edited_at or 0),
                "thumbnail": thumbnail or "",
                "media": media,
            }
        )

    return candidates


def _load_vote_and_comment_stats(
    cur,
    post_ids: list[str],
    blocked_posts: set[str],
    blocked_users: set[str],
    viewer: str = "",
) -> tuple[dict, dict, dict, dict]:
    """Batch load points, comment counts, viewer's votes, and viewer's user_weight contributions."""
    if not post_ids:
        return {}, {}, {}, {}

    vote_totals: dict[str, float] = {}
    comment_counts: dict[str, int] = {}
    user_votes: dict[str, int] = {}
    user_weight_map: dict[str, float] = {}
    id_ph = ",".join(["%s"] * len(post_ids))

    # Points (sum of user_weight, excluding blocked users)
    if blocked_users:
        blocked_ph = ",".join(["%s"] * len(blocked_users))
        cur.execute(
            f"""SELECT LOWER(target), COALESCE(SUM(user_weight), 0)
                FROM votes WHERE LOWER(target) IN ({id_ph}) AND LOWER(owner) NOT IN ({blocked_ph})
                GROUP BY LOWER(target)""",
            post_ids + list(blocked_users),
        )
    else:
        cur.execute(
            f"SELECT LOWER(target), COALESCE(SUM(user_weight), 0) FROM votes WHERE LOWER(target) IN ({id_ph}) GROUP BY LOWER(target)",
            post_ids,
        )
    for tgt, total in cur.fetchall():
        if tgt:
            vote_totals[tgt] = float(total or 0.0)

    # Comment counts
    deleted_bare = _deleted_filter_bare()
    all_blocked = (blocked_posts or set()) | (blocked_users or set())
    if all_blocked:
        ab_ph = ",".join(["%s"] * len(all_blocked))
        cur.execute(
            f"""SELECT LOWER(root_post_id), COUNT(1) FROM posts
                WHERE LOWER(root_post_id) IN ({id_ph})
                  AND COALESCE(target, '') != ''
                  AND LOWER(txhash) NOT IN ({ab_ph})
                  AND LOWER(owner) NOT IN ({ab_ph})
                  {deleted_bare}
                GROUP BY LOWER(root_post_id)""",
            post_ids + list(all_blocked) + list(all_blocked),
        )
    else:
        cur.execute(
            f"""SELECT LOWER(root_post_id), COUNT(1) FROM posts
                WHERE LOWER(root_post_id) IN ({id_ph})
                  AND COALESCE(target, '') != ''
                  {deleted_bare}
                GROUP BY LOWER(root_post_id)""",
            post_ids,
        )
    for root_id, cnt in cur.fetchall():
        if root_id:
            comment_counts[root_id] = int(cnt or 0)

    # Viewer's votes (user_vote: 1=up, -1=down, 0=none) and user_weight contribution
    viewer_lower = (viewer or "").strip().lower()
    if viewer_lower and viewer_lower != "guest":
        cur.execute(
            f"""SELECT LOWER(target), user_vote, user_weight FROM votes
                WHERE LOWER(owner) = %s AND LOWER(target) IN ({id_ph})""",
            [viewer_lower] + post_ids,
        )
        for tgt, vote, weight in cur.fetchall():
            if tgt:
                user_votes[tgt] = int(vote) if vote else 0
                user_weight_map[tgt] = float(weight) if weight else 0.0

    return vote_totals, comment_counts, user_votes, user_weight_map


def _load_following_candidates(
    cur,
    viewer_lower: str,
    blocked_posts: set[str],
    blocked_users: set[str],
    allowed_tags: set[str],
    max_candidates: int,
    blocked_topics: set[str] = None,
) -> tuple[list[dict], set[str], set[str]]:
    """
    Load candidate posts for the following feed.
    Returns (candidates, followed_topics, followed_users).
    """
    cur.execute("SELECT topic FROM followed_topics WHERE LOWER(owner) = %s", (viewer_lower,))
    followed_topics = {(r[0] or "").strip().lower() for r in cur.fetchall() if r and r[0]}

    cur.execute("SELECT target FROM followed_users WHERE LOWER(owner) = %s", (viewer_lower,))
    followed_users = {(r[0] or "").strip().lower() for r in cur.fetchall() if r and r[0]}

    conditions = []
    params: list = []
    if followed_topics:
        ph = ",".join(["%s"] * len(followed_topics))
        conditions.append(f"LOWER(p.topic) IN ({ph})")
        params.extend(list(followed_topics))
    if followed_users:
        ph = ",".join(["%s"] * len(followed_users))
        conditions.append(f"LOWER(p.owner) IN ({ph})")
        params.extend(list(followed_users))

    conditions.append("LOWER(p.owner) = %s")
    params.append(viewer_lower)

    where_clause = " OR ".join(conditions)
    deleted_clause = _deleted_filter()

    cur.execute(
        f"""
        SELECT p.txhash, p.owner, p.created_at, p.topic, p.title, p.content,
               COALESCE(p.tag, '') AS tag,
               COALESCE(p.root_topic, p.topic, '') AS root_topic,
               COALESCE(p.root_post_id, p.txhash, '') AS root_post_id,
               COALESCE(pr.username, '') AS username,
               COALESCE(p.edited_at, 0) AS edited_at,
               COALESCE(p.thumbnail_url, '') AS thumbnail,
               COALESCE(pr.level, 0) AS author_level,
               COALESCE(p.media, '[]') AS media
        FROM posts p
        LEFT JOIN profiles pr ON pr.owner = p.owner
        WHERE COALESCE(p.target,'') = ''
          AND LENGTH(COALESCE(p.title,'')) > 0
          AND ({where_clause})
          {deleted_clause}
        ORDER BY p.created_at DESC
        LIMIT %s
        """,
        params + [max_candidates],
    )

    seen: set[str] = set()
    candidates: list[dict] = []
    for row in cur.fetchall():
        post = _row_to_post(row, blocked_posts, blocked_users, allowed_tags, seen, blocked_topics)
        if post:
            post["_source"] = "following"
            candidates.append(post)

    return candidates, followed_topics, followed_users


def _get_following_feed(
    cur,
    viewer: str,
    limit: int,
    page: int,
    blocked_posts: set[str],
    blocked_users: set[str],
    allowed_tags: set[str],
    sort_mode: str = "magic",
    blocked_topics: set[str] = None,
) -> dict:
    """
    Following feed:
    - Candidates: root posts from followed topics/users + your own posts
    - Sorting:
      - magic: same Magic scorer as home feed (unified), but without prefs (P=0)
      - newest: fast chronological path
    """
    viewer_lower = viewer.strip().lower() if viewer else ""

    if not viewer_lower or viewer_lower == "guest":
        return _get_guest_feed(
            cur, limit, page, blocked_posts, blocked_users, allowed_tags, blocked_topics=blocked_topics
        )

    sort_mode = (sort_mode or "magic").strip().lower()
    if sort_mode not in ("magic", "newest"):
        raise ValueError(f"unsupported sort mode: {sort_mode}")

    max_candidates = limit * page * 4
    candidates, followed_topics, followed_users = _load_following_candidates(
        cur, viewer_lower, blocked_posts, blocked_users, allowed_tags, max_candidates, blocked_topics=blocked_topics
    )

    if not candidates:
        return {"posts": [], "total": 0, "page": page, "limit": limit, "has_more": False}

    # ── Newest: fast path (no scoring) ──────────────────────────────
    if sort_mode == "newest":
        # Already chronological from DB query
        start = (page - 1) * limit
        end = start + limit
        page_posts = candidates[start:end] if start < len(candidates) else []
        has_more = len(candidates) > end

        # Only load stats for the page slice
        page_ids = [p["post_id"] for p in page_posts]
        vote_totals, comment_counts, user_votes, user_weight_map = _load_vote_and_comment_stats(
            cur, page_ids, blocked_posts, blocked_users, viewer_lower
        )

        for post in page_posts:
            pid = post["post_id"]
            author_lower = (post.get("author") or "").strip().lower()
            topic_lower = (post.get("topic") or "").strip().lower()
            is_own = author_lower == viewer_lower
            in_topic = topic_lower in followed_topics
            by_user = author_lower in followed_users

            if is_own:
                reason = "Your post"
            elif in_topic and by_user:
                reason = "From a followed topic and user"
            elif in_topic:
                reason = "From a followed topic"
            else:
                reason = "From a followed user"

            post["points"] = vote_totals.get(pid, 0.0)
            post["comments"] = comment_counts.get(pid, 0)
            post["children"] = []
            post["feed_type"] = "following"
            post["feed_bucket"] = "newest"
            post["feed_debug"] = {"reason": reason, "bucket": "newest"}
            post["user_vote"] = user_votes.get(pid, 0)
            post["user_weight"] = user_weight_map.get(pid, 0.0)

        return {
            "posts": page_posts,
            "total": len(candidates),
            "page": page,
            "limit": limit,
            "has_more": has_more,
        }

    # ── Magic: full scoring path ────────────────────────────────────
    post_ids = [c["post_id"] for c in candidates]
    vote_totals, comment_counts, user_votes, user_weight_map = _load_vote_and_comment_stats(
        cur, post_ids, blocked_posts, blocked_users, viewer_lower
    )

    from similarity import get_or_compute_similarities

    similar_users = get_or_compute_similarities(cur, viewer_lower)
    sim_lookup = {u[0]: u[1] for u in similar_users}
    similar_addrs = set(sim_lookup.keys())
    similar_upvotes = _load_similar_user_upvotes(cur, post_ids, similar_addrs)
    unique_commenters = _load_unique_commenter_counts(cur, post_ids, blocked_posts, blocked_users)
    now_ts = int(time.time())
    topic_prefs: dict[str, float] = {}
    author_prefs: dict[str, float] = {}

    for post in candidates:
        pid = post["post_id"]
        pts = float(vote_totals.get(pid, 0.0) or 0.0)
        comments = int(comment_counts.get(pid, 0) or 0)

        author_lower = (post.get("author") or post.get("user_id") or "").strip().lower()
        topic_lower = (post.get("topic") or "").strip().lower()
        is_own_post = author_lower == viewer_lower
        in_followed_topic = topic_lower in followed_topics if topic_lower else False
        by_followed_user = author_lower in followed_users if author_lower else False

        if not (is_own_post or in_followed_topic or by_followed_user):
            raise RuntimeError(
                f"following_feed.unexpected_candidate: pid={pid[:12]} author={author_lower[:12]} topic={topic_lower}"
            )

        score, debug, should_hide = _score_magic(
            post,
            sim_lookup,
            similar_upvotes,
            unique_commenters,
            vote_totals,
            topic_prefs,
            author_prefs,
            now_ts,
            False,
        )
        if should_hide:
            continue

        if is_own_post:
            reason = "Your post"
        elif in_followed_topic and by_followed_user:
            reason = "From a followed topic and user"
        elif in_followed_topic:
            reason = "From a followed topic"
        else:
            reason = "From a followed user"

        post["_score"] = score
        post["points"] = pts
        post["comments"] = comments
        post["unique_commenters"] = unique_commenters.get(pid, 0)
        post["children"] = []
        post["feed_type"] = "following"
        post["feed_bucket"] = debug.get("bucket", "following")
        post["user_vote"] = user_votes.get(pid, 0)
        post["user_weight"] = user_weight_map.get(pid, 0.0)
        debug["follow_reason"] = reason
        post["feed_debug"] = debug

    candidates.sort(key=lambda p: -float(p.get("_score", 0.0)))

    start = (page - 1) * limit
    end = start + limit
    page_posts = candidates[start:end] if start < len(candidates) else []
    has_more = len(candidates) > end

    for p in page_posts:
        p.pop("_score", None)

    return {
        "posts": page_posts,
        "total": len(candidates),
        "page": page,
        "limit": limit,
        "has_more": has_more,
    }


def _get_home_feed(
    cur,
    viewer: str,
    limit: int,
    page: int,
    blocked_posts: set[str],
    blocked_users: set[str],
    allowed_tags: set[str],
    seed: int = 0,
    sort_mode: str = "magic",
    blocked_topics: set[str] = None,
) -> dict:
    """
    Home feed.

    Sort modes:
    - magic: Magic (unified score + reasons)
    - newest: chronological ordering with the same debug breakdown
    """
    viewer_lower = viewer.strip().lower() if viewer else ""
    sort_mode = (sort_mode or "magic").strip().lower()
    if sort_mode not in ("magic", "newest"):
        raise ValueError(f"unsupported sort mode: {sort_mode}")

    # Newest: fast chronological path (no scoring overhead)
    if sort_mode == "newest":
        return _get_home_feed_newest(
            cur, viewer_lower, limit, page, blocked_posts, blocked_users, allowed_tags, blocked_topics=blocked_topics
        )

    # Guest users: magic-style scoring without personalization
    if not viewer_lower or viewer_lower == "guest":
        return _get_guest_feed_magic(
            cur, limit, page, blocked_posts, blocked_users, allowed_tags, blocked_topics=blocked_topics
        )

    # Logged-in users: Magic (unified score).
    return _get_home_feed_magic(
        cur,
        viewer_lower,
        limit,
        page,
        blocked_posts,
        blocked_users,
        allowed_tags,
        blocked_topics=blocked_topics,
    )


def _get_home_feed_newest(
    cur,
    viewer: str,
    limit: int,
    page: int,
    blocked_posts: set[str],
    blocked_users: set[str],
    allowed_tags: set[str],
    blocked_topics: set[str] = None,
) -> dict:
    """
    Fast chronological feed — no scoring, no similarity, no preferences.

    Just fetches the newest root posts, filters blocked/tags, attaches
    vote/comment stats, and paginates.
    """
    _POST_COLS = """p.txhash, p.owner, p.created_at, p.topic, p.title, p.content, p.tag,
                   p.root_topic, p.root_post_id, pr.username, p.edited_at, p.thumbnail_url,
                   COALESCE(pr.level, 0) AS author_level,
                   COALESCE(p.media, '[]') AS media"""
    _ROOT_FILTER = "(p.root_post_id IS NULL OR p.root_post_id = '' OR LOWER(p.root_post_id) = LOWER(p.txhash))"
    _TOPIC_FILTER = "p.topic IS NOT NULL AND TRIM(p.topic) != ''"

    # Over-fetch to account for blocked/tag filtering, then take the page slice
    fetch_limit = limit * page * 2
    cur.execute(
        f"""SELECT {_POST_COLS}
        FROM posts p
        LEFT JOIN profiles pr ON LOWER(pr.owner) = LOWER(p.owner)
        WHERE {_ROOT_FILTER} AND {_TOPIC_FILTER} AND p.deleted = false
        ORDER BY p.created_at DESC
        LIMIT %s""",
        [fetch_limit],
    )

    seen: set[str] = set()
    posts = []
    for row in cur.fetchall():
        post = _row_to_post(row, blocked_posts, blocked_users, allowed_tags, seen, blocked_topics)
        if post:
            posts.append(post)

    if not posts:
        return {"posts": [], "total": 0, "page": page, "limit": limit, "has_more": False}

    # Paginate first, then only load stats for the page slice
    start = (page - 1) * limit
    end = start + limit
    page_posts = posts[start:end] if start < len(posts) else []
    has_more = len(posts) > end

    # Load vote/comment stats only for the posts we're returning
    page_ids = [p["post_id"] for p in page_posts]
    viewer_lower = (viewer or "").strip().lower()
    vote_totals, comment_counts, user_votes, user_weight_map = _load_vote_and_comment_stats(
        cur, page_ids, blocked_posts, blocked_users, viewer_lower
    )

    for post in page_posts:
        pid = post["post_id"]
        post["points"] = vote_totals.get(pid, 0.0)
        post["comments"] = comment_counts.get(pid, 0)
        post["children"] = []
        post["feed_type"] = "home"
        post["feed_bucket"] = "newest"
        post["feed_debug"] = {"reason": "Newest", "bucket": "newest"}
        post["user_vote"] = user_votes.get(pid, 0)
        post["user_weight"] = user_weight_map.get(pid, 0.0)

    return {
        "posts": page_posts,
        "total": len(posts),
        "page": page,
        "limit": limit,
        "has_more": has_more,
    }


def _get_home_feed_magic(
    cur,
    viewer: str,
    limit: int,
    page: int,
    blocked_posts: set[str],
    blocked_users: set[str],
    allowed_tags: set[str],
    blocked_topics: set[str] = None,
) -> dict:
    """
    Magic feed algorithm.

    Single unified score: (S + V + U + P) × R

    Where:
    - S = similarity boost from similar users who upvoted
    - V = vote score (sqrt scaling)
    - U = unique commenter score (sqrt scaling)
    - P = preference boost from topic/author prefs (sqrt scaling)
    - R = recency decay (exponential)
    """
    import time
    from similarity import get_or_compute_similarities

    viewer_lower = viewer.strip().lower() if viewer else ""

    # 1. Load user preferences
    topic_prefs, author_prefs = _load_user_preferences(cur, viewer_lower)

    # 2. Get similar users (cached or computed on-demand)
    similar_users = get_or_compute_similarities(cur, viewer_lower)
    sim_lookup = {u[0]: u[1] for u in similar_users}
    similar_addrs = set(sim_lookup.keys())

    # 3. Load candidate posts (small targeted pool + random exploration)
    per_source = limit * page * 4  # ~60 per source for page 1
    candidates = _load_home_candidates(
        cur,
        viewer_lower,
        similar_addrs,
        blocked_posts,
        blocked_users,
        allowed_tags,
        per_source,
        blocked_topics=blocked_topics,
    )

    if not candidates:
        return {"posts": [], "total": 0, "page": page, "limit": limit, "has_more": False}

    # 4. Load which posts similar users have upvoted
    post_ids = [c["post_id"] for c in candidates]
    similar_upvotes = _load_similar_user_upvotes(cur, post_ids, similar_addrs)

    # 5. Load stats
    vote_totals, comment_counts, user_votes, user_weight_map = _load_vote_and_comment_stats(
        cur, post_ids, blocked_posts, blocked_users, viewer_lower
    )
    unique_commenters = _load_unique_commenter_counts(cur, post_ids, blocked_posts, blocked_users)

    # 6. Score each post with Magic algorithm
    now_ts = int(time.time())
    scored_posts = []

    for post in candidates:
        score, debug, should_hide = _score_magic(
            post,
            sim_lookup,
            similar_upvotes,
            unique_commenters,
            vote_totals,
            topic_prefs,
            author_prefs,
            now_ts,
            True,
        )

        if should_hide:
            continue

        post["_score"] = score
        post["feed_debug"] = debug
        post["points"] = vote_totals.get(post["post_id"], 0.0)
        post["comments"] = comment_counts.get(post["post_id"], 0)
        post["unique_commenters"] = unique_commenters.get(post["post_id"], 0)
        post["children"] = []
        post["feed_type"] = "home"
        post["feed_bucket"] = debug["bucket"]
        post["user_vote"] = user_votes.get(post["post_id"], 0)
        post["user_weight"] = user_weight_map.get(post["post_id"], 0.0)
        scored_posts.append(post)

    # 7. Sort by score descending
    scored_posts.sort(key=lambda p: -p["_score"])

    # 8. Paginate
    start = (page - 1) * limit
    end = start + limit
    page_posts = scored_posts[start:end] if start < len(scored_posts) else []
    has_more = len(scored_posts) > end

    # Clean up internal fields
    for post in page_posts:
        post.pop("_score", None)

    return {
        "posts": page_posts,
        "total": len(scored_posts),
        "page": page,
        "limit": limit,
        "has_more": has_more,
    }


def _score_magic(
    post: dict,
    sim_lookup: dict[str, float],
    similar_upvotes: dict[str, list[str]],
    unique_commenters: dict[str, int],
    vote_totals: dict[str, float],
    topic_prefs: dict[str, float],
    author_prefs: dict[str, float],
    now_ts: int,
    use_prefs: bool = True,
) -> tuple[float, dict, bool]:
    """
    Magic scoring: (S + V + U + P) × R

    Components (uniform weighting):
    - S = sqrt(similarity_sum)
    - V = sqrt(net_votes)
    - U = sqrt(unique_commenters)
    - P = sqrt(max(0, topic_pref + author_pref))
    - R = 1 / (1 + (age_hours/9)^1.585) — decay: 4.5h=0.75, 9h=0.5, 18h=0.25, 36h=0.11

    Returns (score, debug_info, should_hide).
    """
    import math

    HIDE_THRESHOLD = -5.0
    PREF_RAW_CAP = 5.0

    def _clamp_pref_raw(x: float) -> float:
        if x > PREF_RAW_CAP:
            return PREF_RAW_CAP
        if x < -PREF_RAW_CAP:
            return -PREF_RAW_CAP
        return x

    pid = post["post_id"]
    author = post["author"]
    topic_lower = (post.get("topic") or "").strip().lower()
    timestamp = post.get("timestamp", 0)

    if use_prefs:
        # Check user preference - hide severely disliked content
        topic_pref = _clamp_pref_raw(float(topic_prefs.get(topic_lower, 0) or 0.0))
        author_pref = _clamp_pref_raw(float(author_prefs.get(author, 0) or 0.0))
        combined_pref = topic_pref + author_pref

        if combined_pref <= HIDE_THRESHOLD:
            return 0.0, {}, True
    else:
        # Non-home feeds: preferences are not part of the score (P=0) and we do not hide.
        topic_pref = 0.0
        author_pref = 0.0
        combined_pref = 0.0

    # Signed sqrt: sqrt(abs(x)) * sign(x) — preserves sign, compresses magnitude
    def _sqrt_signed(x: float) -> float:
        if x >= 0:
            return math.sqrt(x)
        return -math.sqrt(abs(x))

    # S = Similarity boost (always >= 0)
    upvoters = similar_upvotes.get(pid, [])
    raw_sim = sum(float(sim_lookup.get(v, 0.0) or 0.0) for v in upvoters)
    S = math.sqrt(max(0.0, raw_sim))

    # V = Vote score (signed sqrt: negative votes hurt the score)
    net_vote = float(vote_totals.get(pid, 0.0) or 0.0)
    V = _sqrt_signed(net_vote)

    # U = Unique commenter score (always >= 0)
    unique_count = unique_commenters.get(pid, 0)
    U = math.sqrt(max(0.0, float(unique_count)))

    # P = Preference boost (signed sqrt: disliked topics/authors hurt the score)
    P = _sqrt_signed(combined_pref)

    # R = Recency: inverse polynomial decay (gentler than exponential)
    # 4.5h=0.75, 9h=0.50, 18h=0.25, 36h=0.11
    age_hours = max(0, (now_ts - timestamp) / 3600)
    R = 1 / (1 + (age_hours / 9) ** 1.585)

    # Final score
    score = (S + V + U + P) * R

    # Determine primary reason based on dominant component
    components = [("S", S), ("V", V), ("U", U), ("P", P)]
    dominant = max(components, key=lambda x: x[1])

    if dominant[0] == "S" and S > 0.3:
        reason = "Similar users liked this"
        bucket = "similar"
    elif dominant[0] == "P" and P > 0.3:
        if topic_pref > author_pref:
            reason = f"You like #{topic_lower}" if topic_lower else "You like this topic"
        elif author_pref > topic_pref:
            reason = "You like this author"
        else:
            reason = "You like this topic & author"
        bucket = "liked"
    elif dominant[0] == "V" and net_vote >= 3:
        reason = "Popular post"
        bucket = "popular"
    elif dominant[0] == "U" and unique_count >= 2:
        reason = "Active discussion"
        bucket = "discussion"
    else:
        reason = "Fresh content"
        bucket = "discovery"

    debug = {
        "bucket": bucket,
        "reason": reason,
        "score": round(float(score), 4),
        "equation": "(√S + √V + √U + √P) × R",
        # Raw input values (before sqrt) so the formula makes sense
        "S": round(raw_sim, 3),
        "V": round(net_vote, 3),
        "U": unique_count,
        "P": round(combined_pref, 3),
        "R": round(R, 4),
        "age_hours": round(age_hours, 1),
        "t_pref": round(topic_pref, 1),
        "a_pref": round(author_pref, 1),
        "source": post.get("_source", "unknown"),
    }

    return score, debug, False


def _load_unique_commenter_counts(
    cur,
    post_ids: list[str],
    blocked_posts: set[str],
    blocked_users: set[str],
) -> dict[str, int]:
    """
    Load count of unique commenters per post.

    Unlike regular comment_counts which just counts all comments,
    this counts DISTINCT owners to avoid inflating scores when
    one user spams multiple comments.

    IMPORTANT: The root post author is excluded from the count.
    Otherwise anyone could boost their own post by adding a comment.
    """
    if not post_ids:
        return {}

    result: dict[str, int] = {}
    id_ph = ",".join(["%s"] * len(post_ids))
    all_blocked = blocked_posts | blocked_users

    # Join with root posts to get the author, then exclude them from unique commenter count
    if all_blocked:
        ab_ph = ",".join(["%s"] * len(all_blocked))
        cur.execute(
            f"""
            SELECT LOWER(c.root_post_id), COUNT(DISTINCT LOWER(c.owner)) AS unique_commenters
            FROM posts c
            JOIN posts root ON LOWER(root.txhash) = LOWER(c.root_post_id)
            WHERE LOWER(c.root_post_id) IN ({id_ph})
              AND COALESCE(c.target, '') != ''
              AND LOWER(c.owner) != LOWER(root.owner)
              AND LOWER(c.txhash) NOT IN ({ab_ph})
              AND LOWER(c.owner) NOT IN ({ab_ph})
              AND c.deleted = false
            GROUP BY LOWER(c.root_post_id)
            """,
            post_ids + list(all_blocked) + list(all_blocked),
        )
    else:
        cur.execute(
            f"""
            SELECT LOWER(c.root_post_id), COUNT(DISTINCT LOWER(c.owner)) AS unique_commenters
            FROM posts c
            JOIN posts root ON LOWER(root.txhash) = LOWER(c.root_post_id)
            WHERE LOWER(c.root_post_id) IN ({id_ph})
              AND COALESCE(c.target, '') != ''
              AND LOWER(c.owner) != LOWER(root.owner)
              AND c.deleted = false
            GROUP BY LOWER(c.root_post_id)
            """,
            post_ids,
        )

    for root_id, cnt in cur.fetchall():
        if root_id:
            result[root_id] = int(cnt or 0)

    return result


def _load_home_candidates(
    cur,
    viewer: str,
    similar_addrs: set[str],
    blocked_posts: set[str],
    blocked_users: set[str],
    allowed_tags: set[str],
    max_posts: int,
    blocked_topics: set[str] = None,
) -> list[dict]:
    """
    Load candidate posts for home feed from multiple sources:
    1. Posts by similar users (recent)
    2. Posts upvoted by similar users (recent)
    3. Recent posts (discovery)
    4. Random exploration (upvoted posts from wider time window)
    """
    results = []
    seen = set()

    _POST_COLS = """p.txhash, p.owner, p.created_at, p.topic, p.title, p.content, p.tag,
                   p.root_topic, p.root_post_id, pr.username, p.edited_at, p.thumbnail_url,
                   COALESCE(pr.level, 0) AS author_level,
                   COALESCE(p.media, '[]') AS media"""
    _ROOT_FILTER = "(p.root_post_id IS NULL OR p.root_post_id = '' OR LOWER(p.root_post_id) = LOWER(p.txhash))"
    _TOPIC_FILTER = "p.topic IS NOT NULL AND TRIM(p.topic) != ''"

    # Source 1: Posts BY similar users (root posts only)
    if similar_addrs:
        similar_list = list(similar_addrs)
        placeholders = ",".join(["%s"] * len(similar_list))
        cur.execute(
            f"""SELECT {_POST_COLS}
            FROM posts p
            LEFT JOIN profiles pr ON LOWER(pr.owner) = LOWER(p.owner)
            WHERE LOWER(p.owner) IN ({placeholders})
              AND {_ROOT_FILTER} AND {_TOPIC_FILTER} AND p.deleted = false
            ORDER BY p.created_at DESC
            LIMIT %s""",
            similar_list + [max_posts],
        )
        for row in cur.fetchall():
            post = _row_to_post(row, blocked_posts, blocked_users, allowed_tags, seen, blocked_topics)
            if post:
                post["_source"] = "similar_author"
                results.append(post)

    # Source 2: Posts UPVOTED by similar users
    if similar_addrs:
        similar_list = list(similar_addrs)
        placeholders = ",".join(["%s"] * len(similar_list))
        cur.execute(
            f"""SELECT DISTINCT ON (p.txhash)
                   {_POST_COLS}
            FROM votes v
            JOIN posts p ON LOWER(v.target) = LOWER(p.txhash)
            LEFT JOIN profiles pr ON LOWER(pr.owner) = LOWER(p.owner)
            WHERE LOWER(v.owner) IN ({placeholders})
              AND v.user_vote > 0
              AND {_ROOT_FILTER} AND {_TOPIC_FILTER} AND p.deleted = false
            ORDER BY p.txhash, p.created_at DESC
            LIMIT %s""",
            similar_list + [max_posts],
        )
        for row in cur.fetchall():
            post = _row_to_post(row, blocked_posts, blocked_users, allowed_tags, seen, blocked_topics)
            if post:
                post["_source"] = "similar_upvoted"
                results.append(post)

    # Source 3: Recent posts (discovery)
    cur.execute(
        f"""SELECT {_POST_COLS}
        FROM posts p
        LEFT JOIN profiles pr ON LOWER(pr.owner) = LOWER(p.owner)
        WHERE {_ROOT_FILTER} AND {_TOPIC_FILTER} AND p.deleted = false
        ORDER BY p.created_at DESC
        LIMIT %s""",
        [max_posts],
    )
    for row in cur.fetchall():
        post = _row_to_post(row, blocked_posts, blocked_users, allowed_tags, seen, blocked_topics)
        if post:
            post["_source"] = "recent"
            results.append(post)

    # Source 4: Random exploration (upvoted posts from last 60 days)
    # Pulls random posts that have at least one upvote, giving older quality
    # content a chance to surface. Different results each request.
    explore_limit = max(20, max_posts // 3)
    cur.execute(
        f"""SELECT {_POST_COLS}
        FROM posts p
        LEFT JOIN profiles pr ON LOWER(pr.owner) = LOWER(p.owner)
        WHERE {_ROOT_FILTER} AND {_TOPIC_FILTER} AND p.deleted = false
          AND p.created_at > EXTRACT(EPOCH FROM NOW()) - 60 * 86400
          AND EXISTS (
              SELECT 1 FROM votes v
              WHERE LOWER(v.target) = LOWER(p.txhash) AND v.user_vote > 0
          )
        ORDER BY RANDOM()
        LIMIT %s""",
        [explore_limit],
    )
    for row in cur.fetchall():
        post = _row_to_post(row, blocked_posts, blocked_users, allowed_tags, seen, blocked_topics)
        if post:
            post["_source"] = "explore"
            results.append(post)

    return results


def _row_to_post(row, blocked_posts, blocked_users, allowed_tags, seen, blocked_topics=None) -> dict | None:
    """Convert a DB row to a post dict, or None if should be skipped."""
    import json as _json

    # Support both 13-column (legacy) and 14-column (v1.12.0 with media) rows
    if len(row) >= 14:
        (
            txhash,
            owner,
            ts,
            topic,
            title,
            content,
            tag,
            root_topic,
            root_post_id,
            username,
            edited_at,
            thumbnail,
            author_level,
            media_raw,
        ) = row[:14]
    else:
        (
            txhash,
            owner,
            ts,
            topic,
            title,
            content,
            tag,
            root_topic,
            root_post_id,
            username,
            edited_at,
            thumbnail,
            author_level,
        ) = row
        media_raw = "[]"

    pid = (txhash or "").lower()
    author = (owner or "").lower()

    if pid in seen or pid in blocked_posts or author in blocked_users:
        return None
    topic_lower = (topic or "").strip().lower()
    if blocked_topics and topic_lower in blocked_topics:
        return None
    if (tag or "").strip() and (tag or "").lower() not in allowed_tags:
        return None

    # Parse media JSON array
    try:
        media = _json.loads(media_raw or "[]")
        if not isinstance(media, list):
            media = []
    except Exception:
        media = []

    seen.add(pid)
    return {
        "post_id": pid,
        "author": author,
        "user_id": author,
        "username": username or "",
        "author_level": int(author_level) if author_level else 0,
        "timestamp": int(ts) if ts else 0,
        "topic": (topic or "").strip(),
        "root_topic": (root_topic or topic or "").strip(),
        "root_post_id": (root_post_id or pid).lower(),
        "title": title or "",
        "content": content or "",
        "tag": tag or "",
        "edited": bool(edited_at),
        "edited_at": int(edited_at or 0),
        "thumbnail": thumbnail or "",
        "media": media,
    }


def _load_similar_user_upvotes(cur, post_ids: list[str], similar_addrs: set[str]) -> dict[str, list[str]]:
    """
    Load which similar users upvoted which posts.
    Returns: {post_id: [voter_addr, ...]}
    """
    if not post_ids or not similar_addrs:
        return {}

    similar_list = list(similar_addrs)
    post_placeholders = ",".join(["%s"] * len(post_ids))
    user_placeholders = ",".join(["%s"] * len(similar_list))

    query = f"""
        SELECT LOWER(target), LOWER(owner)
        FROM votes
        WHERE LOWER(target) IN ({post_placeholders})
          AND LOWER(owner) IN ({user_placeholders})
          AND user_vote > 0
    """
    cur.execute(query, post_ids + similar_list)

    result = {}
    for target, voter in cur.fetchall():
        if target not in result:
            result[target] = []
        result[target].append(voter)
    return result


def _get_guest_feed(
    cur,
    limit: int,
    page: int,
    blocked_posts: set[str],
    blocked_users: set[str],
    allowed_tags: set[str],
    blocked_topics: set[str] = None,
) -> dict:
    """Simple chronological feed for guest users."""
    max_candidates = limit * page * 2
    candidates = _load_candidate_posts(
        cur, max_candidates, blocked_posts, blocked_users, allowed_tags, blocked_topics=blocked_topics
    )

    if not candidates:
        return {"posts": [], "total": 0, "page": page, "limit": limit, "has_more": False}

    # Load vote/comment stats (no viewer for guest)
    post_ids = [c["post_id"] for c in candidates]
    vote_totals, comment_counts, _, _ = _load_vote_and_comment_stats(cur, post_ids, blocked_posts, blocked_users)

    for post in candidates:
        pid = post["post_id"]
        post["points"] = vote_totals.get(pid, 0.0)
        post["comments"] = comment_counts.get(pid, 0)
        post["children"] = []
        post["feed_type"] = "home"
        post["feed_bucket"] = "guest"
        post["user_vote"] = 0
        post["user_weight"] = 0.0
        post["feed_debug"] = {"reason": "Guest feed (chronological)", "bucket": "guest"}

    # Filter out posts with <= 0 points for guests (show only positive content)
    candidates = [p for p in candidates if p["points"] > 0]

    # Already sorted by timestamp from query
    offset = (page - 1) * limit
    feed = candidates[offset : offset + limit]
    has_more = (offset + limit) < len(candidates)

    return {
        "posts": feed,
        "total": len(candidates),
        "page": page,
        "limit": limit,
        "has_more": has_more,
    }


def _get_guest_feed_magic(
    cur,
    limit: int,
    page: int,
    blocked_posts: set[str],
    blocked_users: set[str],
    allowed_tags: set[str],
    blocked_topics: set[str] = None,
) -> dict:
    """
    Guest home feed, Magic-style:
    - No personalization (S=0, P=0)
    - Score uses the same Magic scorer: (S + V + U + P) × R
    """
    import time

    max_candidates = limit * page * 4
    candidates = _load_candidate_posts(
        cur, max_candidates, blocked_posts, blocked_users, allowed_tags, blocked_topics=blocked_topics
    )

    if not candidates:
        return {"posts": [], "total": 0, "page": page, "limit": limit, "has_more": False}

    post_ids = [c["post_id"] for c in candidates]
    vote_totals, comment_counts, _, _ = _load_vote_and_comment_stats(cur, post_ids, blocked_posts, blocked_users)
    unique_commenters = _load_unique_commenter_counts(cur, post_ids, blocked_posts, blocked_users)

    now_ts = int(time.time())
    sim_lookup: dict[str, float] = {}
    similar_upvotes: dict[str, list[str]] = {}
    topic_prefs: dict[str, float] = {}
    author_prefs: dict[str, float] = {}

    scored_posts = []
    for post in candidates:
        pid = post["post_id"]
        post["_source"] = "guest"
        score, debug, should_hide = _score_magic(
            post,
            sim_lookup,
            similar_upvotes,
            unique_commenters,
            vote_totals,
            topic_prefs,
            author_prefs,
            now_ts,
            False,
        )
        if should_hide:
            continue

        post["_score"] = score
        post["feed_debug"] = debug
        post["points"] = float(vote_totals.get(pid, 0.0) or 0.0)
        post["comments"] = int(comment_counts.get(pid, 0) or 0)
        post["unique_commenters"] = int(unique_commenters.get(pid, 0) or 0)
        post["children"] = []
        post["feed_type"] = "home"
        post["feed_bucket"] = debug["bucket"]
        post["user_vote"] = 0
        post["user_weight"] = 0.0
        scored_posts.append(post)

    scored_posts.sort(key=lambda p: -float(p.get("_score", 0.0)))

    start = (page - 1) * limit
    end = start + limit
    page_posts = scored_posts[start:end] if start < len(scored_posts) else []
    has_more = len(scored_posts) > end

    for p in page_posts:
        p.pop("_score", None)

    return {
        "posts": page_posts,
        "total": len(scored_posts),
        "page": page,
        "limit": limit,
        "has_more": has_more,
    }


# ============================================================================
# END HOME FEED V2
# ============================================================================


@public_bp.route("/api/get_tx_status")
def get_tx_status():
    """Unified transaction status endpoint with type-specific enrichment."""
    rid = next_request_id()
    try:
        if _is_catching_up():
            return jsonify({"error": "node_catching_up"}), 503

        tx_hash = str(request.args.get("hash", "") or "").strip().lower()
        address = str(request.args.get("address", "") or "").strip().lower()
        if not tx_hash or len(tx_hash) != 64:
            return jsonify({"error": "invalid or missing hash"}), 400

        log_event(rid, "get_tx_status.begin", tx_hash=tx_hash)

        # Check RPC for tx confirmation
        import urllib.request as _url

        rpc = require_runtime().rpc_url
        url = f"{rpc}/tx?hash=0x{tx_hash.upper()}&prove=false"
        try:
            with _url.urlopen(url, timeout=2) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as fetch_err:
            log_event(rid, "get_tx_status.rpc_error", tx_hash=tx_hash, error=str(fetch_err))
            return jsonify({"found": False})

        txr = (data or {}).get("result", {})
        height = int(txr.get("height", 0) or 0)
        if height <= 0:
            log_event(rid, "get_tx_status.not_found", tx_hash=tx_hash)
            return jsonify({"found": False})

        code = int(txr.get("tx_result", {}).get("code", 0) or 0)
        raw_log = str(txr.get("tx_result", {}).get("log", ""))
        success = code == 0

        # Check if indexed and detect tx type
        indexed = False
        tx_type = "unknown"
        details = None
        conn = None

        try:
            conn = connect_db(timeout=5.0, busy_timeout_ms=15000)
            cur = conn.cursor()

            # Check indexer height
            cur.execute("SELECT value FROM meta WHERE key='last_height'")
            row = cur.fetchone()
            last_indexed_height = int(row[0]) if row and row[0] is not None else 0
            indexed = last_indexed_height >= height

            if indexed and success:
                # Detect tx type and get details

                # Check votes table
                cur.execute(
                    """
                    SELECT v.owner, v.target, v.user_vote, v.user_weight, v.created_at
                    FROM votes v WHERE LOWER(v.txhash) = %s
                    """,
                    (tx_hash,),
                )
                vote_row = cur.fetchone()
                if vote_row:
                    tx_type = "vote"
                    owner, target, user_vote_val, user_weight_val, created_at = vote_row
                    # Get target post's current points
                    target_points = None
                    if target:
                        cur.execute(
                            "SELECT COALESCE(SUM(user_weight), 0) FROM votes WHERE LOWER(target) = %s",
                            (target.lower(),),
                        )
                        pts_row = cur.fetchone()
                        if pts_row:
                            target_points = float(pts_row[0])
                    details = {
                        "owner": owner,
                        "target": target,
                        "user_vote": user_vote_val,
                        "user_weight": round(user_weight_val, 3) if user_weight_val else 0,
                        "target_points": target_points,
                    }
                else:
                    # Check posts table
                    cur.execute(
                        "SELECT txhash, topic, title FROM posts WHERE LOWER(txhash) = %s",
                        (tx_hash,),
                    )
                    post_row = cur.fetchone()
                    if post_row:
                        tx_type = "post"
                        details = {
                            "post_id": post_row[0],
                            "topic": post_row[1] or "",
                            "title": post_row[2] or "",
                        }
                    else:
                        # Check profiles for account/username changes
                        cur.execute(
                            "SELECT owner, username FROM profiles WHERE LOWER(txhash) = %s",
                            (tx_hash,),
                        )
                        profile_row = cur.fetchone()
                        if profile_row:
                            tx_type = "profile"
                            details = {
                                "owner": profile_row[0],
                                "username": profile_row[1] or "",
                            }
                        else:
                            # Check followed_users
                            cur.execute(
                                "SELECT owner, target FROM followed_users WHERE LOWER(txhash) = %s",
                                (tx_hash,),
                            )
                            follow_user_row = cur.fetchone()
                            if follow_user_row:
                                tx_type = "follow_user"
                                details = {
                                    "owner": follow_user_row[0],
                                    "target": follow_user_row[1],
                                }
                            else:
                                # Check preferences for topic follows
                                cur.execute(
                                    "SELECT owner, pref_value FROM preferences WHERE LOWER(txhash) = %s AND pref_type = 'topic'",
                                    (tx_hash,),
                                )
                                pref_row = cur.fetchone()
                                if pref_row:
                                    tx_type = "follow_topic"
                                    details = {
                                        "owner": pref_row[0],
                                        "topic": pref_row[1],
                                    }

        except Exception as db_err:
            log_event(rid, "get_tx_status.db_error", tx_hash=tx_hash, error=str(db_err))
        finally:
            try:
                if conn:
                    conn.close()
            except Exception:
                pass

        out = {
            "found": True,
            "tx_hash": tx_hash,
            "height": height,
            "code": code,
            "success": success,
            "indexed": indexed,
            "tx_type": tx_type,
        }
        if details:
            out["details"] = details
        if code != 0:
            out["error_details"] = _classify_reject(raw_log)

        log_event(rid, "get_tx_status.ok", tx_hash=tx_hash, tx_type=tx_type, indexed=indexed)
        return jsonify(out)

    except Exception as e:
        log_event(rid, "get_tx_status.err", error=str(e))
        return safe_error(e)


# ---- get_parameters: short cache for pow params ----
_PARAMS_CACHE: Dict[str, Any] = {"data": None, "expires": 0.0}
_PARAMS_CACHE_TTL: float = 3.0  # seconds


@public_bp.route("/api/get_parameters")
def get_parameters():
    rid = next_request_id()
    log_event(rid, "get_parameters.begin", address=request.args.get("address"))
    try:
        if _is_catching_up():
            return jsonify({"error": "node_catching_up"}), 503
        addr = request.args.get("address", default=None, type=str)
        now = time.monotonic()
        cached = _PARAMS_CACHE["data"]
        if cached is not None and _PARAMS_CACHE["expires"] > now:
            base = cached
            cache_hit = True
        else:
            last = _latest_block_hash()
            diff = _get_current_pow_difficulty()
            base_bits = _get_pow_base_bits()
            pow_factor = _get_pow_factor()
            base = {
                "last_block_hash": last,
                "pow_difficulty": diff,
                "pow_base_bits": base_bits,
                "pow_factor": pow_factor,
            }
            _PARAMS_CACHE["data"] = base
            _PARAMS_CACHE["expires"] = now + _PARAMS_CACHE_TTL
            cache_hit = False

        op_addr = find_local_operator_address()
        bal = _get_balance(addr) if addr else None
        log_event(
            rid,
            "get_parameters.cached" if cache_hit else "get_parameters.ok",
            last=base["last_block_hash"][:8],
            diff=base["pow_difficulty"],
            pow_factor=base.get("pow_factor"),
            operator=op_addr,
            addr=addr,
            bal=bal,
        )
        payload: Dict[str, Any] = dict(base)
        if bal is not None:
            try:
                payload["balance"] = int(bal)
            except Exception:
                payload["balance"] = 0
        return jsonify(payload)
    except Exception as e:
        log_event(rid, "get_parameters.err", error=str(e))
        return safe_error(e)


@public_bp.route("/api/get_user_status")
def get_user_status():
    """Get user-specific dynamic data (balance, level, subscription info)."""
    rid = next_request_id()
    addr = request.args.get("address", default=None, type=str)
    log_event(rid, "get_user_status.begin", address=addr)
    try:
        if not addr:
            return jsonify({"error": "address required"}), 400
        if _is_catching_up():
            return jsonify({"error": "node_catching_up"}), 503

        username = None
        user_level = 0
        profile_registered_at = None
        subscription_expiry = 0
        auto_renew = False
        reserve_funds = 0

        # Query DB for profile
        try:
            conn = connect_db(timeout=10.0, busy_timeout_ms=15000)
            cur = conn.cursor()
            cur.execute(
                "SELECT username, level, created_at, subscription_expiry FROM profiles WHERE LOWER(owner)=LOWER(%s) LIMIT 1",
                (addr,),
            )
            row = cur.fetchone()
            if row:
                username = row[0] if row[0] else None
                user_level = int(row[1]) if row[1] is not None else 0
                profile_registered_at = int(row[2]) if row[2] is not None else None
                subscription_expiry = int(row[3]) if row[3] is not None else 0
            conn.close()
        except Exception:
            pass

        # Query chain for real-time subscription data (use full gRPC query to get level)
        chain_profile = _query_chain_profile_full(addr)
        if chain_profile:
            if chain_profile.get("level") is not None:
                user_level = int(chain_profile["level"])
            if chain_profile.get("subscription_expiry") is not None:
                subscription_expiry = int(chain_profile["subscription_expiry"])
            if chain_profile.get("auto_renew") is not None:
                auto_renew = bool(chain_profile["auto_renew"])
            if chain_profile.get("reserve_funds") is not None:
                reserve_funds = int(chain_profile["reserve_funds"])

        # Get balance
        balance = 0
        try:
            balance = int(_get_balance(addr))
        except Exception:
            pass

        # Get recent votes (limit 100 for login sync) and inbox timestamp
        recent_votes = []
        inbox_ts = None
        try:
            conn = connect_db(timeout=10.0, busy_timeout_ms=15000)
            cur = conn.cursor()
            cur.execute(
                """
                SELECT target, user_vote, created_at
                FROM votes
                WHERE LOWER(owner) = LOWER(%s)
                ORDER BY created_at DESC
                LIMIT 100
                """,
                (addr,),
            )
            for tgt, user_vote, ts in cur.fetchall():
                if tgt is not None:
                    recent_votes.append(
                        {
                            "target": str(tgt).lower(),
                            "direction": int(user_vote or 0),
                            "timestamp": int(ts or 0),
                        }
                    )
            conn.close()
        except Exception:
            pass

        resp = {
            "username": username,
            "balance": balance,
            "user_level": user_level,
            "subscription_expiry": subscription_expiry,
            "auto_renew": auto_renew,
            "reserve_funds": reserve_funds,
            "profile_registered_at": profile_registered_at,
            "recent_votes": recent_votes,
        }
        log_event(rid, "get_user_status.ok", user_level=user_level)
        return jsonify(resp)
    except Exception as e:
        log_event(rid, "get_user_status.err", error=str(e))
        return safe_error(e)


@public_bp.route("/api/get_user_followed")
def get_user_followed():
    """Get user's follow lists (moderators, topics, users)."""
    rid = next_request_id()
    addr = request.args.get("address", default=None, type=str)
    log_event(rid, "get_user_followed.begin", address=addr)
    try:
        if not addr:
            return jsonify({"error": "address required"}), 400

        followed_moderators = []
        followed_topics = []
        followed_users = []

        try:
            conn = connect_db(timeout=10.0, busy_timeout_ms=15000)
            cur = conn.cursor()
            # Followed moderators
            cur.execute("SELECT moderator FROM followed_mods WHERE LOWER(owner)=LOWER(%s)", (addr,))
            followed_moderators = [row[0] for row in cur.fetchall()]
            # Followed topics
            cur.execute("SELECT topic FROM followed_topics WHERE LOWER(owner)=LOWER(%s)", (addr,))
            followed_topics = [row[0] for row in cur.fetchall()]
            # Followed users
            cur.execute(
                "SELECT target FROM followed_users WHERE LOWER(owner)=LOWER(%s) ORDER BY position ASC",
                (addr,),
            )
            followed_users = [row[0] for row in cur.fetchall()]
            conn.close()
        except Exception:
            pass

        resp = {
            "followed_moderators": followed_moderators,
            "followed_topics": followed_topics,
            "followed_users": followed_users,
        }
        log_event(
            rid,
            "get_user_followed.ok",
            mods=len(followed_moderators),
            topics=len(followed_topics),
            users=len(followed_users),
        )
        return jsonify(_inject_balance(resp, addr))
    except Exception as e:
        log_event(rid, "get_user_followed.err", error=str(e))
        return safe_error(e)


@public_bp.route("/api/get_user_blocked")
def get_user_blocked():
    """Get user's block lists (posts, users, topics)."""
    rid = next_request_id()
    addr = request.args.get("address", default=None, type=str)
    log_event(rid, "get_user_blocked.begin", address=addr)
    try:
        if not addr:
            return jsonify({"error": "address required"}), 400

        blocked_posts = []
        blocked_users = []
        blocked_topics = []

        try:
            conn = connect_db(timeout=10.0, busy_timeout_ms=15000)
            cur = conn.cursor()
            # Blocked posts
            cur.execute("SELECT target FROM blocked_posts WHERE LOWER(owner)=LOWER(%s)", (addr,))
            blocked_posts = [row[0] for row in cur.fetchall()]
            # Blocked users
            cur.execute("SELECT target FROM blocked_users WHERE LOWER(owner)=LOWER(%s)", (addr,))
            blocked_users = [row[0] for row in cur.fetchall()]
            # Blocked topics
            cur.execute("SELECT target FROM blocked_topics WHERE LOWER(owner)=LOWER(%s)", (addr,))
            blocked_topics = [row[0] for row in cur.fetchall()]
            conn.close()
        except Exception:
            pass

        resp = {
            "blocked_posts": blocked_posts,
            "blocked_users": blocked_users,
            "blocked_topics": blocked_topics,
        }
        log_event(rid, "get_user_blocked.ok", posts=len(blocked_posts), users=len(blocked_users))
        return jsonify(_inject_balance(resp, addr))
    except Exception as e:
        log_event(rid, "get_user_blocked.err", error=str(e))
        return safe_error(e)


@public_bp.route("/api/get_preferences")
def get_preferences():
    """Get user's topic/user preference weights."""
    rid = next_request_id()
    addr = request.args.get("address", default=None, type=str)
    log_event(rid, "get_preferences.begin", address=addr)
    try:
        if not addr:
            return jsonify({"error": "address required"}), 400

        topics: list[dict] = []
        authors: list[dict] = []

        try:
            conn = connect_db(timeout=10.0, busy_timeout_ms=15000)
            cur = conn.cursor()
            cur.execute(
                "SELECT pref_type, target, weight FROM preferences WHERE LOWER(owner) = LOWER(%s)",
                (addr,),
            )
            for pref_type, target, weight in cur.fetchall():
                t = (target or "").strip().lower()
                if not t:
                    continue
                try:
                    w = float(weight or 0.0)
                except Exception:
                    continue
                if w == 0:
                    continue
                if pref_type == "topic":
                    topics.append({"topic": t, "weight": w})
                elif pref_type == "author":
                    authors.append({"user": t, "weight": w})
            conn.close()
        except Exception:
            pass

        topics.sort(key=lambda x: x["weight"], reverse=True)
        authors.sort(key=lambda x: x["weight"], reverse=True)

        resp = {"topics": topics, "authors": authors}
        log_event(rid, "get_preferences.ok", topics=len(topics), authors=len(authors))
        return jsonify(_inject_balance(resp, addr))
    except Exception as e:
        log_event(rid, "get_preferences.err", error=str(e))
        return safe_error(e)


@public_bp.route("/api/get_similar_users")
def get_similar_users():
    """Get users with similar taste profiles based on preference vectors."""
    rid = next_request_id()
    addr = request.args.get("address", default=None, type=str)
    log_event(rid, "get_similar_users.begin", address=addr[:12] if addr else None)

    if not addr:
        return jsonify({"error": "address required"}), 400

    try:
        from similarity import get_or_compute_similarities

        conn = connect_db(timeout=15.0, busy_timeout_ms=20000)
        cur = conn.cursor()

        # Get similar users (cached or computed)
        similar_users = get_or_compute_similarities(cur, addr)

        # Fetch usernames for similar users
        usernames: dict[str, str] = {}
        if similar_users:
            user_addrs = [u[0] for u in similar_users]
            ph = ",".join(["%s"] * len(user_addrs))
            cur.execute(
                f"SELECT LOWER(owner), username FROM profiles WHERE LOWER(owner) IN ({ph})",
                user_addrs,
            )
            for owner, uname in cur.fetchall():
                if owner and uname:
                    usernames[owner] = uname

        # Build response with similarity details
        result = []
        for user_addr, similarity, shared_dims in similar_users:
            result.append(
                {
                    "address": user_addr,
                    "username": usernames.get(user_addr, ""),
                    "similarity": round(similarity, 3),
                    "shared_dimensions": shared_dims,
                }
            )

        conn.close()

        log_event(rid, "get_similar_users.ok", count=len(result))
        return jsonify({"similar_users": result})

    except Exception as e:
        log_event(rid, "get_similar_users.err", error=str(e))
        return safe_error(e)


# Cache for staked balance (60 second TTL)
_staked_balance_cache: Dict[str, Any] = {"value": 0, "expires": 0}


def _get_cached_staked_balance() -> int:
    """Get total staked (delegated) balance for the validator via gRPC, cached 60s."""
    now = int(time.time())
    if _staked_balance_cache["expires"] > now:
        return _staked_balance_cache["value"]
    total = 0
    try:
        rt = require_runtime()
        if rt.validator_payer_addr:
            total = _get_staked_balance(rt.validator_payer_addr)
    except Exception:
        pass
    _staked_balance_cache["value"] = total
    _staked_balance_cache["expires"] = now + 60
    return total


@public_bp.route("/api/get_network_stats")
def get_network_stats():
    """Get network/node stats for NetworkView."""
    rid = next_request_id()
    log_event(rid, "get_network_stats.begin")
    try:
        if _is_catching_up():
            return jsonify({"error": "node_catching_up"}), 503

        # Get block time
        try:
            block_time = _get_block_time_seconds()
        except Exception:
            block_time = 0

        # Get difficulty info
        diff_info = _get_difficulty_info()

        # Get server balance
        server_balance = 0
        try:
            rt = require_runtime()
            server_balance = int(_get_balance(rt.validator_payer_addr))
        except Exception:
            pass

        # Get staked balance (cached 60s)
        staked_balance = 0
        try:
            staked_balance = _get_cached_staked_balance()
        except Exception:
            pass

        # Get mint params for 24h earnings
        mint_quantity = 0
        mint_interval = 0
        try:
            p = load_params(force=False)
            mint_quantity = int(p["mint_quantity"])
            mint_interval = int(p["mint_interval"])
        except Exception:
            pass

        resp = {
            "server_balance": server_balance,
            "staked_balance": staked_balance,
            "block_time": block_time,
            "mint_quantity": mint_quantity,
            "mint_interval": mint_interval,
            "pow_difficulty": int(diff_info["current_difficulty"]),
            "pow_factor": float(_get_pow_factor()),
            "pow_message_count": int(diff_info.get("pow_message_count", 0)),
            "pow_calm_sequence": int(diff_info.get("consecutive_low_usage", 0)),
            "pow_last_change_height": int(diff_info.get("last_change_height", 0)),
            "current_height": int(diff_info.get("current_height", 0)),
            "difficulty_history": _get_cached_difficulty_history(),
        }
        log_event(rid, "get_network_stats.ok", pow_diff=resp["pow_difficulty"])
        return jsonify(resp)
    except Exception as e:
        log_event(rid, "get_network_stats.err", error=str(e))
        return safe_error(e)


# Cache for supply history (30 second TTL)
_supply_history_cache: Dict[str, Any] = {"data": None, "expires": 0}


def _get_cached_supply_history() -> list:
    """Get supply history for last 7 days with 30 second cache."""
    now = int(time.time())
    if _supply_history_cache["data"] is not None and _supply_history_cache["expires"] > now:
        return _supply_history_cache["data"]

    # Query last 7 days
    since_ts = now - (7 * 24 * 3600)
    conn = connect_db(timeout=10.0, busy_timeout_ms=15000)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT height, total_supply, created_at, node_balance
            FROM supply_history
            WHERE created_at >= %s
            ORDER BY height ASC
            """,
            (since_ts,),
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    history = [
        {"height": r[0], "total_supply": r[1], "timestamp": r[2], "node_balance": r[3] if len(r) > 3 else None}
        for r in rows
    ]

    _supply_history_cache["data"] = history
    _supply_history_cache["expires"] = now + 30  # 30 second cache
    return history


@public_bp.route("/api/get_supply_history")
def get_supply_history():
    """Get supply history for burn/mint chart (7 days)."""
    rid = next_request_id()
    log_event(rid, "get_supply_history.begin")
    try:
        if _is_catching_up():
            return jsonify({"error": "node_catching_up"}), 503

        history = _get_cached_supply_history()

        # Get mint params for calculations
        p = load_params(force=False)
        mint_interval = int(p["mint_interval"])
        mint_quantity = int(p["mint_quantity"])

        resp = {
            "history": history,
            "mint_interval": mint_interval,
            "mint_quantity": mint_quantity,
        }
        log_event(rid, "get_supply_history.ok", count=len(history))
        return jsonify(resp)
    except Exception as e:
        log_event(rid, "get_supply_history.err", error=str(e))
        return safe_error(e)


# Cache for circulation stats (expensive query)
_circulation_cache: Dict[str, Any] = {"data": None, "expires": 0}
_CIRCULATION_CACHE_TTL = 60  # 60 seconds

# Cache for welcome stats (lightweight stats for landing page)
_welcome_stats_cache: Dict[str, Any] = {"data": None, "expires": 0}
_WELCOME_STATS_CACHE_TTL = 30  # 30 seconds

# Cache for full overview stats (expensive query)
_overview_stats_cache: Dict[str, Any] = {"data": None, "expires": 0}
_OVERVIEW_STATS_CACHE_TTL = 30  # 30 seconds

# Cache for analytics stats (very expensive - stats_events processing)
_analytics_stats_cache: Dict[str, Any] = {"data": None, "expires": 0}
_ANALYTICS_STATS_CACHE_TTL = 60  # 60 seconds (longer TTL for expensive query)

# Wallets excluded from circulating supply (team/founder controlled)
_EXCLUDED_FROM_CIRCULATING = [
    "mirage1x2epe8m0x3jkfxm4x4fpns4anv8u78ywm77ygg",  # Founders Fund
    "mirage1zjs7qn3chramktnu96wft4cs6ry2srddv27dmr",  # Marketing Fund
    "mirage13e3rxansuzneayrf9nwrxdpp38sphshz7ly8xd",  # Development Fund
]


@public_bp.route("/api/get_total_supply")
def get_total_supply():
    """CoinGecko-compliant total supply endpoint.

    Returns total supply as plain text with 6 decimals.
    Example response: 1234567.890000
    """
    rid = next_request_id()
    log_event(rid, "get_total_supply.begin")
    try:
        if _is_catching_up():
            return "0", 503, {"Content-Type": "text/plain"}

        total_supply_umirage = _get_total_supply()
        supply_mirage = total_supply_umirage / 1_000_000
        result = f"{supply_mirage:.6f}"
        log_event(rid, "get_total_supply.ok", supply=result)
        return result, 200, {"Content-Type": "text/plain"}
    except Exception as e:
        log_event(rid, "get_total_supply.err", error=str(e))
        return "0", 500, {"Content-Type": "text/plain"}


@public_bp.route("/api/get_circulating_supply")
def get_circulating_supply():
    """CoinGecko-compliant circulating supply endpoint.

    Returns circulating supply as plain text with 6 decimals.
    Circulating = Total - Excluded wallets (Founders, Marketing, Development funds).
    Example response: 1234567.890000
    """
    rid = next_request_id()
    log_event(rid, "get_circulating_supply.begin")
    try:
        if _is_catching_up():
            return "0", 503, {"Content-Type": "text/plain"}

        total_supply_umirage = _get_total_supply()
        excluded_balances = _get_balances_batch(_EXCLUDED_FROM_CIRCULATING)
        excluded_total = sum(bal for _, bal in excluded_balances)
        circulating_umirage = total_supply_umirage - excluded_total
        circulating_mirage = circulating_umirage / 1_000_000
        result = f"{circulating_mirage:.6f}"
        log_event(
            rid,
            "get_circulating_supply.ok",
            total=total_supply_umirage,
            excluded=excluded_total,
            circulating=result,
        )
        return result, 200, {"Content-Type": "text/plain"}
    except Exception as e:
        log_event(rid, "get_circulating_supply.err", error=str(e))
        return "0", 500, {"Content-Type": "text/plain"}


@public_bp.route("/api/get_circulation_stats")
def get_circulation_stats():
    """Get total supply and top 10 accounts by balance."""
    rid = next_request_id()
    log_event(rid, "get_circulation_stats.begin")
    try:
        if _is_catching_up():
            return jsonify({"error": "node_catching_up"}), 503

        now = time.time()
        if _circulation_cache["data"] and _circulation_cache["expires"] > now:
            log_event(rid, "get_circulation_stats.cached")
            return jsonify(_circulation_cache["data"])

        total_supply = _get_total_supply()

        conn = connect_db(timeout=10.0, busy_timeout_ms=15000)
        try:
            cur = conn.cursor()
            cur.execute("SELECT DISTINCT owner FROM profiles")
            rows = cur.fetchall()
            addresses = [r[0] for r in rows if r[0]]

            cur.execute(
                """
                SELECT LOWER(owner), username FROM profiles
                WHERE username IS NOT NULL AND LENGTH(username) > 0
                """
            )
            username_map = {r[0]: r[1] for r in cur.fetchall()}
        finally:
            conn.close()

        balances = _get_balances_batch(addresses)
        sorted_balances = sorted(balances, key=lambda x: x[1], reverse=True)
        top_10 = sorted_balances[:10]

        top_accounts = []
        for addr, bal in top_10:
            username = username_map.get(addr.lower(), "")
            top_accounts.append(
                {
                    "address": addr,
                    "username": username,
                    "balance": bal,
                }
            )

        resp = {
            "total_supply": total_supply,
            "top_accounts": top_accounts,
        }

        _circulation_cache["data"] = resp
        _circulation_cache["expires"] = now + _CIRCULATION_CACHE_TTL

        log_event(rid, "get_circulation_stats.ok", total_supply=total_supply, top_count=len(top_accounts))
        return jsonify(resp)
    except Exception as e:
        log_event(rid, "get_circulation_stats.err", error=str(e))
        return safe_error(e)


# ---- get_chain_config: chain governance params only ----
_CHAIN_CONFIG_CACHE: Optional[Dict[str, Any]] = None
_CHAIN_CONFIG_CACHE_TIME: float = 0.0
_CHAIN_CONFIG_CACHE_TTL: float = 86400.0  # 24 hours — governance changes are rare


@public_bp.route("/api/get_chain_config")
def get_chain_config():
    """Chain governance params (tiers, limits, subscription_period, etc.).

    These change only via governance proposals. Cached 24h server-side.
    No difficulty/height — use get_network_stats or get_parameters for those.
    """
    global _CHAIN_CONFIG_CACHE, _CHAIN_CONFIG_CACHE_TIME

    rid = next_request_id()
    log_event(rid, "get_chain_config.begin")
    try:
        now = time.monotonic()
        if _CHAIN_CONFIG_CACHE is not None and (now - _CHAIN_CONFIG_CACHE_TIME) < _CHAIN_CONFIG_CACHE_TTL:
            log_event(rid, "get_chain_config.cached")
            return jsonify(_CHAIN_CONFIG_CACHE)

        if _is_catching_up():
            return jsonify({"error": "node_catching_up"}), 503

        try:
            p = load_params(force=False)
        except Exception as e:
            log_event(rid, "get_chain_config.params_err", error=str(e))
            return safe_error(e, context="get_chain_config.params")

        resp: Dict[str, Any] = {
            "max_username_size": p["max_username_size"],
            "min_username_size": p["min_username_size"],
            "max_topic_size": p["max_topic_size"],
            "min_topic_size": p["min_topic_size"],
            "subscription_period": p["subscription_period"],
            "mint_interval": p["mint_interval"],
            "block_time": _get_block_time_seconds(),
            "tiers": p["tiers"],
        }

        _CHAIN_CONFIG_CACHE = resp
        _CHAIN_CONFIG_CACHE_TIME = now

        log_event(rid, "get_chain_config.ok")
        return jsonify(resp)
    except Exception as e:
        log_event(rid, "get_chain_config.err", error=str(e))
        return safe_error(e)


# ---- get_node_config: per-node static settings ----
_NODE_CONFIG_CACHE: Optional[Dict[str, Any]] = None
_NODE_CONFIG_CACHE_TIME: float = 0.0
_NODE_CONFIG_CACHE_TTL: float = 86400.0  # 24 hours — these almost never change


@public_bp.route("/api/get_node_config")
def get_node_config():
    """Per-node static settings (validator info, feature flags, API keys).

    These are deployment-specific and don't change at runtime. Cached 24h server-side.
    """
    global _NODE_CONFIG_CACHE, _NODE_CONFIG_CACHE_TIME

    rid = next_request_id()
    log_event(rid, "get_node_config.begin")
    try:
        now = time.monotonic()
        if _NODE_CONFIG_CACHE is not None and (now - _NODE_CONFIG_CACHE_TIME) < _NODE_CONFIG_CACHE_TTL:
            log_event(rid, "get_node_config.cached")
            return jsonify(_NODE_CONFIG_CACHE)

        if _is_catching_up():
            return jsonify({"error": "node_catching_up"}), 503

        rt = require_runtime()
        valoper = find_local_operator_address()
        valcons = find_local_consensus_address()

        validator_moniker = ""
        try:
            if valoper:
                val_info = _get_validator(valoper)
                validator_moniker = val_info.get("moniker", "")
        except Exception:
            pass

        resp: Dict[str, Any] = {
            "validator_account_address": rt.validator_payer_addr,
            "validator_operator_address": valoper,
            "validator_consensus_address": valcons,
            "validator_moniker": validator_moniker,
            "giphy_api_key": os.environ.get("REACT_APP_GIPHY_API_KEY", ""),
            "registration_enabled": REGISTRATION_ENABLED,
            "registration_invite_code_required": REGISTRATION_INVITE_CODE_REQUIRED,
            "quests_enabled": QUESTS_ENABLED,
            "quest_payouts_enabled": QUESTS_PAYOUTS_ENABLED,
        }

        _NODE_CONFIG_CACHE = resp
        _NODE_CONFIG_CACHE_TIME = now

        log_event(rid, "get_node_config.ok")
        return jsonify(resp)
    except Exception as e:
        log_event(rid, "get_node_config.err", error=str(e))
        return safe_error(e)


def _get_peer_info(peer: Dict[str, str]) -> Dict[str, str]:
    """Get peer information including IP and on-chain validator moniker."""

    def _normalize_moniker(moniker: str) -> str:
        m = (moniker or "").strip()
        if not m:
            return ""

        if m.startswith("http://") or m.startswith("https://"):
            return m

        if any(ch.isspace() for ch in m) or "/" in m:
            return m

        host = m
        if ":" in host:
            maybe_host, maybe_port = host.rsplit(":", 1)
            if maybe_host and maybe_port.isdigit():
                host = maybe_host

        host = host.strip(".")
        if host.count(".") < 1:
            return m

        labels = host.split(".")
        for label in labels:
            if not label or len(label) > 63:
                return m
            if label[0] == "-" or label[-1] == "-":
                return m
            if not re.fullmatch(r"[A-Za-z0-9-]+", label):
                return m

        return f"https://{m}"

    return {
        "ip": peer["ip"],
        "moniker": _normalize_moniker(peer.get("moniker", "")),
    }


@public_bp.route("/api/get_peers")
def get_peers():
    """Return a list of currently connected peers with domain resolution."""
    try:
        peers_data = _get_connected_peers()
        peers = [_get_peer_info(p) for p in peers_data]
        return jsonify({"peers": peers})
    except Exception as e:
        return safe_error(e)


# Cache for difficulty history (1 minute TTL)
_difficulty_history_cache: Dict[str, Any] = {"data": None, "expires": 0}


def _get_cached_difficulty_history() -> list:
    """Get difficulty history with 60 second cache."""
    now = int(time.time())
    if _difficulty_history_cache["data"] is not None and _difficulty_history_cache["expires"] > now:
        return _difficulty_history_cache["data"]

    # Query last 24 hours
    since_ts = now - (24 * 3600)
    try:
        conn = connect_db(timeout=10.0, busy_timeout_ms=15000)
        cur = conn.cursor()
        cur.execute(
            """
            SELECT height, difficulty, COALESCE(msg_count, 0), created_at
            FROM difficulty_history
            WHERE created_at >= %s
            ORDER BY height ASC
            """,
            (since_ts,),
        )
        rows = cur.fetchall()
        conn.close()
        history = [{"height": r[0], "difficulty": r[1], "msg_count": r[2], "timestamp": r[3]} for r in rows]
    except Exception:
        history = []

    _difficulty_history_cache["data"] = history
    _difficulty_history_cache["expires"] = now + 10  # 10 second cache
    return history


@public_bp.route("/api/get_address_from_username", methods=["GET", "POST"])
def get_address_from_username():
    """Get address(es) for username(s).

    GET: ?username=foo (single)
    POST: { username: str } or { usernames: [str] }

    Returns:
      - Single: { exists: bool, address: str|null, username: str }
      - Bulk: { map: { "username": "address", ... } }
    """
    try:
        conn = connect_db(timeout=10.0, busy_timeout_ms=15000)
        cur = conn.cursor()

        # Parse input
        if request.method == "POST":
            data = request.get_json(silent=True) or {}
            single = data.get("username")
            many = data.get("usernames")
        else:
            single = request.args.get("username", type=str)
            many = None

        # Bulk mode
        if isinstance(many, list) and len(many) > 0:
            cleaned = []
            seen = set()
            for u in many[:200]:  # Cap at 200
                if isinstance(u, str) and u.strip():
                    lower = u.strip().lower()
                    if lower not in seen:
                        seen.add(lower)
                        cleaned.append(lower)
            if not cleaned:
                conn.close()
                return jsonify({"map": {}})
            ph = ",".join(["%s"] * len(cleaned))
            cur.execute(
                f"SELECT LOWER(username), owner FROM profiles WHERE LOWER(username) IN ({ph})",
                cleaned,
            )
            result = {}
            for uname, owner in cur.fetchall():
                if uname and owner:
                    result[uname] = owner
            conn.close()
            return jsonify({"map": result})

        # Single mode
        if not single:
            conn.close()
            return jsonify({"error": "username is required"}), 400
        username = single.strip()
        cur.execute("SELECT owner FROM profiles WHERE LOWER(username)=LOWER(%s) LIMIT 1", (username,))
        row = cur.fetchone()
        conn.close()
        if row and row[0]:
            return jsonify({"exists": True, "address": row[0], "username": username})
        return jsonify({"exists": False, "address": None, "username": username})
    except Exception as e:
        return safe_error(e)


@public_bp.route("/api/search_username")
def username_search():
    """Lightweight username prefix search for @mention autocomplete.

    GET: ?q=<prefix>&limit=8
    Returns: { results: [{username, address}, ...] }
    """
    q = (request.args.get("q") or "").strip().lower()
    limit = min(max(1, request.args.get("limit", 8, type=int)), 20)

    if not q:
        return jsonify({"results": []})

    try:
        conn = connect_db(timeout=5.0, busy_timeout_ms=5000)
        cur = conn.cursor()
        # Prefix match on username, exclude empty usernames
        cur.execute(
            "SELECT username, owner FROM profiles WHERE LOWER(username) LIKE %s AND username != '' ORDER BY username LIMIT %s",
            (q + "%", limit),
        )
        results = [{"username": row[0], "address": row[1]} for row in cur.fetchall() if row[0] and row[1]]
        conn.close()
        return jsonify({"results": results})
    except Exception as e:
        return safe_error(e, context="search_username")


@public_bp.route("/api/get_username_from_address", methods=["GET", "POST"])
def get_username_from_address():
    """Get username(s) for address(es).

    GET: ?address=mirage1... (single)
    POST: { address: str } or { addresses: [str] }

    Returns:
      - Single: { username: str|null, address: str }
      - Bulk: { map: { "address": "username", ... } }
    """
    try:
        conn = connect_db(timeout=10.0, busy_timeout_ms=15000)
        cur = conn.cursor()

        # Parse input
        if request.method == "POST":
            data = request.get_json(silent=True) or {}
            single = data.get("address")
            many = data.get("addresses")
        else:
            single = request.args.get("address", type=str)
            many = None

        # Bulk mode
        if isinstance(many, list) and len(many) > 0:
            cleaned = []
            seen = set()
            for a in many[:200]:  # Cap at 200
                if isinstance(a, str) and a.strip():
                    lower = a.strip().lower()
                    if lower not in seen:
                        seen.add(lower)
                        cleaned.append(lower)
            if not cleaned:
                conn.close()
                return jsonify({"map": {}})
            ph = ",".join(["%s"] * len(cleaned))
            cur.execute(
                f"SELECT LOWER(owner), COALESCE(username, '') FROM profiles WHERE LOWER(owner) IN ({ph})",
                cleaned,
            )
            result = {}
            for owner, uname in cur.fetchall():
                if owner and uname:
                    result[owner] = uname
            conn.close()
            return jsonify({"map": result})

        # Single mode
        if not single:
            conn.close()
            return jsonify({"error": "address is required"}), 400
        address = single.strip()
        cur.execute("SELECT username FROM profiles WHERE LOWER(owner)=LOWER(%s) LIMIT 1", (address,))
        row = cur.fetchone()
        conn.close()
        if row and row[0]:
            return jsonify({"username": row[0], "address": address})
        return jsonify({"username": None, "address": address})
    except Exception as e:
        return safe_error(e)


# Removed compatibility alias endpoints for username resolution (no fallbacks)


@public_bp.route("/api/get_users")
def get_users():
    """Get all registered users with username and address.

    Query Parameters:
      - limit (default: 100, max: 500): Number of users per page
      - page (default: 1): Page number
      - has_username (default: false): If true, only return users with a username set

    Returns:
      { users: [{ address, username }], page, limit, has_more, total }
    """
    limit = request.args.get("limit", 100, type=int)
    page = request.args.get("page", 1, type=int)
    has_username = request.args.get("has_username", "false", type=str).lower() in ("true", "1", "yes")

    limit = min(max(1, limit), 500)
    page = max(1, page)
    offset = (page - 1) * limit

    try:
        conn = connect_db(timeout=10.0, busy_timeout_ms=15000)
        cur = conn.cursor()

        username_filter = ""
        if has_username:
            username_filter = "WHERE username IS NOT NULL AND username != ''"

        cur.execute(
            f"""
            SELECT owner, COALESCE(username, '') as username
            FROM profiles
            {username_filter}
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
            """,
            (limit, offset),
        )
        rows = cur.fetchall()

        cur.execute(
            f"""
            SELECT COUNT(*) FROM profiles
            {username_filter}
            """
        )
        total_row = cur.fetchone()
        total = int(total_row[0] or 0) if total_row else 0

        conn.close()

        users = [{"address": row[0], "username": row[1]} for row in rows]
        has_more = (page * limit) < total

        return jsonify({"users": users, "page": page, "limit": limit, "has_more": has_more, "total": total})
    except Exception as e:
        return safe_error(e)


@public_bp.route("/api/get_topics")
def get_topics():
    """Get list of most active topics, excluding deleted messages."""
    limit = request.args.get("limit", 50, type=int)
    limit = min(max(1, limit), 200)
    min_posts = request.args.get("min_posts", 10, type=int)  # Filter topics with < N posts
    try:
        # Get min/max topic size from chain params
        p = expect_params()
        min_topic = p.get("min_topic_size", 3)
        max_topic = p.get("max_topic_size", 50)

        conn = connect_db(timeout=10.0, busy_timeout_ms=15000)
        cur = conn.cursor()

        deleted_clause = _deleted_filter()

        # Get topics with at least min_posts
        cur.execute(
            f"""
            SELECT p.topic, COUNT(1) as post_count
            FROM posts p
            WHERE COALESCE(p.target, '') = ''
              AND LENGTH(COALESCE(p.title, '')) > 0
              AND p.topic IS NOT NULL
              AND LENGTH(TRIM(p.topic)) >= %s
              AND LENGTH(TRIM(p.topic)) <= %s
              {deleted_clause}
            GROUP BY p.topic
            HAVING COUNT(1) >= %s
            ORDER BY post_count DESC, p.topic ASC
            LIMIT %s
            """,
            (min_topic, max_topic, min_posts, limit),
        )
        rows = cur.fetchall()

        # Count topics with fewer posts (for "and X more" display)
        small_topics_count = 0
        if min_posts > 1:
            cur.execute(
                f"""
                SELECT COUNT(*) FROM (
                    SELECT p.topic
                    FROM posts p
                    WHERE COALESCE(p.target, '') = ''
                      AND LENGTH(COALESCE(p.title, '')) > 0
                      AND p.topic IS NOT NULL
                      AND LENGTH(TRIM(p.topic)) >= %s
                      AND LENGTH(TRIM(p.topic)) <= %s
                      {deleted_clause}
                    GROUP BY p.topic
                    HAVING COUNT(1) > 0 AND COUNT(1) < %s
                ) small_topics
                """,
                (min_topic, max_topic, min_posts),
            )
            small_topics_count = cur.fetchone()[0] or 0

        # Filter out blocked topics for the viewer
        viewer_addr = request.args.get("address", default="", type=str)
        viewer_blocked_topics = _get_blocked_topics(cur, viewer_addr) if viewer_addr else set()

        topics_dict = {}
        for row in rows:
            if row[0] and row[1] and row[1] > 0:
                if viewer_blocked_topics and (row[0] or "").strip().lower() in viewer_blocked_topics:
                    continue
                topics_dict[row[0]] = {"topic": row[0], "post_count": row[1], "count": row[1], "comment_count": 0}

        if topics_dict:
            cur.execute(
                f"""
                SELECT p.root_topic, COUNT(1) as comment_count
                FROM posts p
                WHERE COALESCE(p.target, '') != ''
                  AND p.root_topic IS NOT NULL
                  AND LENGTH(TRIM(p.root_topic)) > 0
                  {deleted_clause}
                GROUP BY p.root_topic
                """
            )
            # root_topic is stored lowercase; build a lookup from the original-case topic keys
            lower_to_topic = {k.lower(): k for k in topics_dict}
            for row in cur.fetchall():
                root_topic, count = row[0], row[1]
                key = lower_to_topic.get((root_topic or "").lower())
                if key:
                    topics_dict[key]["comment_count"] = count or 0

        if topics_dict:
            lower_to_key = {k.lower(): k for k in topics_dict.keys()}
            stats = _compute_dominant_flags(cur, list(lower_to_key.keys()))
            for t_lower, info in stats.items():
                key = lower_to_key.get(t_lower)
                if not key or key not in topics_dict:
                    continue
                dominant_tag = (info.get("dominant_tag") or "") if info else ""
                dominant_ratio = float(info.get("dominant_ratio") or 0)
                flags = {tag: dominant_tag == tag for tag in _TOPIC_TAGS}
                topics_dict[key]["flags"] = flags
                topics_dict[key]["dominant_tag"] = dominant_tag or None
                topics_dict[key]["dominant_ratio"] = dominant_ratio

        topics = list(topics_dict.values())
        conn.close()

        return jsonify({"topics": topics, "small_topics_count": small_topics_count, "min_posts": min_posts})
    except Exception as e:
        return safe_error(e)


@public_bp.route("/api/search_topics")
def search_topics():
    """Search topics by substring with relevance sorting.

    Sorts results by: exact match > prefix match > contains match, then by post count.
    """
    limit = request.args.get("limit", 20, type=int)
    offset = request.args.get("offset", 0, type=int)
    limit = min(max(1, limit), 50)
    offset = max(0, offset)

    q_raw = request.args.get("q", default="", type=str)
    q = re.sub(r"[^a-zA-Z0-9]", "", str(q_raw or "")).lower()
    if len(q) < 2:
        return jsonify({"topics": []})

    try:
        p = expect_params()
        min_topic = p.get("min_topic_size", 3)
        max_topic = p.get("max_topic_size", 50)

        conn = connect_db(timeout=10.0, busy_timeout_ms=15000)
        cur = conn.cursor()
        deleted_clause = _deleted_filter()

        # Search with substring match, sorted by relevance:
        # 0 = exact match, 1 = prefix match, 2 = contains match
        cur.execute(
            f"""
            WITH topic_base AS (
                SELECT LOWER(TRIM(p.topic)) AS topic,
                       COUNT(1) AS post_count
                FROM posts p
                WHERE COALESCE(p.target, '') = ''
                  AND p.topic IS NOT NULL
                  AND LENGTH(TRIM(p.topic)) >= %s
                  AND LENGTH(TRIM(p.topic)) <= %s
                  AND LOWER(p.topic) LIKE %s
                  {deleted_clause}
                GROUP BY LOWER(TRIM(p.topic))
            )
            SELECT
                tb.topic,
                tb.post_count,
                COALESCE(tcs.dominant_tag, '') AS dominant_tag,
                COALESCE(tcs.dominant_ratio, 0) AS dominant_ratio,
                CASE
                    WHEN tb.topic = %s THEN 0
                    WHEN tb.topic LIKE %s THEN 1
                    ELSE 2
                END AS relevance
            FROM topic_base tb
            LEFT JOIN topic_content_stats tcs ON LOWER(tcs.topic) = tb.topic
            ORDER BY relevance ASC, post_count DESC, topic ASC
            LIMIT %s
            OFFSET %s
            """,
            (min_topic, max_topic, f"%{q}%", q, f"{q}%", limit, offset),
        )

        rows = cur.fetchall()

        # Filter out blocked topics for the viewer
        viewer_addr = request.args.get("address", default="", type=str)
        viewer_blocked_topics = _get_blocked_topics(cur, viewer_addr) if viewer_addr else set()

        topics = []
        topic_list = [
            row[0] for row in rows if not (viewer_blocked_topics and (row[0] or "").lower() in viewer_blocked_topics)
        ]

        # Compute live dominant flags from posts to avoid stale stats
        stats = _compute_dominant_flags(cur, topic_list)

        for row in rows:
            topic = row[0]
            if viewer_blocked_topics and (topic or "").lower() in viewer_blocked_topics:
                continue
            post_count = int(row[1] or 0)
            stat = stats.get(topic, {}) if stats else {}
            dominant_tag = str(stat.get("dominant_tag") or "").lower()
            dominant_ratio = float(stat.get("dominant_ratio") or 0)
            flags = {tag: dominant_tag == tag for tag in _TOPIC_TAGS}
            topics.append(
                {
                    "topic": topic,
                    "post_count": post_count,
                    "count": post_count,
                    "flags": flags,
                    "dominant_tag": dominant_tag or None,
                    "dominant_ratio": dominant_ratio,
                }
            )
        conn.close()
        return jsonify({"topics": topics})
    except Exception as e:
        return safe_error(e)


@public_bp.route("/api/search")
def search():
    """
    Unified search endpoint.
    - @username: Search users by username, return user + their posts
    - #topic: Search topics by prefix
    - Otherwise: Search topics, users, and posts with substring matching

    Query Parameters:
      - q (required): Search query
      - type: Filter to 'topics', 'users', or 'posts' (for Load More)
      - limit (default: 10, max: 50): Results per type
      - offset (default: 0): For pagination
      - address: Viewer address for filtering blocked content
    """
    q_raw = request.args.get("q", default="", type=str).strip()
    if not q_raw:
        return jsonify({"error": "q parameter is required"}), 400

    search_type_filter = request.args.get("type", default="", type=str).strip().lower()
    limit = request.args.get("limit", 10, type=int)
    limit = min(max(1, limit), 50)
    offset = request.args.get("offset", 0, type=int)
    offset = max(0, offset)
    viewer = request.args.get("address", default="", type=str).strip()

    # Detect search type from prefix
    if q_raw.startswith("@"):
        search_type = "user"
        query = q_raw[1:].strip()
    elif q_raw.startswith("#"):
        search_type = "topic"
        query = q_raw[1:].strip()
    else:
        search_type = "general"
        query = q_raw

    if not query:
        return jsonify(
            {
                "query": q_raw,
                "search_type": search_type,
                "topics": [],
                "users": [],
                "posts": [],
                "has_more_topics": False,
                "has_more_users": False,
                "has_more_posts": False,
            }
        )

    try:
        conn = connect_db(timeout=10.0, busy_timeout_ms=15000)
        cur = conn.cursor()
        blocked_posts = _get_blocked_posts(cur, viewer) if viewer else set()
        blocked_users = _get_blocked_users(cur, viewer) if viewer else set()
        blocked_topics = _get_blocked_topics(cur, viewer) if viewer else set()
        deleted_clause = _deleted_filter()
        deleted_bare = _deleted_filter_bare()

        result = {
            "query": q_raw,
            "search_type": search_type,
            "topics": [],
            "users": [],
            "posts": [],
            "has_more_topics": False,
            "has_more_users": False,
            "has_more_posts": False,
        }

        # Sanitize query for LIKE matching (escape special chars)
        query_lower = query.lower()
        like_query = query_lower.replace("%", "\\%").replace("_", "\\_")

        # ========== USER SEARCH (@username) ==========
        if search_type == "user":
            # Find user by username (exact or prefix match) with post count
            cur.execute(
                f"""
                SELECT pr.owner, COALESCE(pr.username, ''), pr.level, pr.created_at,
                       (SELECT COUNT(1) FROM posts p WHERE LOWER(p.owner) = LOWER(pr.owner) 
                        AND COALESCE(p.target, '') = '' {deleted_clause}) as post_count
                FROM profiles pr
                WHERE LOWER(pr.username) LIKE %s
                ORDER BY 
                    CASE WHEN LOWER(pr.username) = %s THEN 0 ELSE 1 END,
                    pr.created_at DESC
                LIMIT %s OFFSET %s
                """,
                (f"{like_query}%", query_lower, limit + 1, offset),
            )
            user_rows = cur.fetchall()
            has_more_users = len(user_rows) > limit
            user_rows = user_rows[:limit]

            users = []
            for row in user_rows:
                addr, uname, level, created_at, post_count = row
                if addr.lower() in blocked_users:
                    continue
                users.append(
                    {
                        "address": addr,
                        "username": uname or None,
                        "level": level or 0,
                        "created_at": int(created_at) if created_at else None,
                        "post_count": int(post_count or 0),
                    }
                )

            result["users"] = users
            result["has_more_users"] = has_more_users

            # Also fetch posts from the first matched user if any
            if users and not search_type_filter:
                first_user_addr = users[0]["address"]
                cur.execute(
                    f"""
                    SELECT p.txhash, p.owner, p.created_at, p.topic, p.title, p.content,
                           COALESCE(pr.username, '') as username,
                           COALESCE(p.target, '') as target,
                           COALESCE(p.tag, '') as tag,
                           COALESCE(p.thumbnail_url, '') as thumbnail,
                           COALESCE(pr.level, 0) as author_level,
                           COALESCE(p.media, '[]') as media
                    FROM posts p
                    LEFT JOIN profiles pr ON pr.owner = p.owner
                    WHERE LOWER(p.owner) = LOWER(%s)
                      AND COALESCE(p.target, '') = ''
                      {deleted_clause}
                    ORDER BY p.created_at DESC
                    LIMIT 10
                    """,
                    (first_user_addr,),
                )
                post_rows = cur.fetchall()
                posts = _format_search_posts(
                    cur, post_rows, blocked_posts, blocked_users, viewer, deleted_bare, blocked_topics
                )
                result["posts"] = posts

        # ========== TOPIC SEARCH (#topic) ==========
        elif search_type == "topic":
            p = expect_params()
            min_topic = p.get("min_topic_size", 3)
            max_topic = p.get("max_topic_size", 50)

            cur.execute(
                f"""
                WITH topic_base AS (
                    SELECT LOWER(TRIM(p.topic)) AS topic,
                           COUNT(1) AS post_count
                    FROM posts p
                    WHERE COALESCE(p.target, '') = ''
                      AND p.topic IS NOT NULL
                      AND LENGTH(TRIM(p.topic)) >= %s
                      AND LENGTH(TRIM(p.topic)) <= %s
                      AND LOWER(p.topic) LIKE %s
                      {deleted_clause}
                    GROUP BY LOWER(TRIM(p.topic))
                    ORDER BY post_count DESC, topic ASC
                    LIMIT %s
                    OFFSET %s
                )
                SELECT
                    tb.topic,
                    tb.post_count,
                    COALESCE(tcs.dominant_tag, '') AS dominant_tag,
                    COALESCE(tcs.dominant_ratio, 0) AS dominant_ratio
                FROM topic_base tb
                LEFT JOIN topic_content_stats tcs ON LOWER(tcs.topic) = tb.topic
                """,
                (min_topic, max_topic, f"{like_query}%", limit + 1, offset),
            )
            topic_rows = cur.fetchall()
            has_more_topics = len(topic_rows) > limit
            topic_rows = topic_rows[:limit]

            topics = []
            topic_list = [row[0] for row in topic_rows]
            stats = _compute_dominant_flags(cur, topic_list) if topic_list else {}

            for row in topic_rows:
                topic, post_count, dominant_tag, dominant_ratio = row
                stat = stats.get(topic, {}) if stats else {}
                dom_tag = str(stat.get("dominant_tag") or "").lower()
                dom_ratio = float(stat.get("dominant_ratio") or 0)
                topics.append(
                    {
                        "topic": topic,
                        "post_count": int(post_count or 0),
                        "dominant_tag": dom_tag or None,
                        "dominant_ratio": dom_ratio,
                    }
                )

            result["topics"] = topics
            result["has_more_topics"] = has_more_topics

        # ========== GENERAL SEARCH ==========
        else:
            # Search topics (if not filtering or filtering to topics)
            if not search_type_filter or search_type_filter == "topics":
                p = expect_params()
                min_topic = p.get("min_topic_size", 3)
                max_topic = p.get("max_topic_size", 50)

                cur.execute(
                    f"""
                    WITH topic_base AS (
                        SELECT LOWER(TRIM(p.topic)) AS topic,
                               COUNT(1) AS post_count
                        FROM posts p
                        WHERE COALESCE(p.target, '') = ''
                          AND p.topic IS NOT NULL
                          AND LENGTH(TRIM(p.topic)) >= %s
                          AND LENGTH(TRIM(p.topic)) <= %s
                          AND LOWER(p.topic) LIKE %s
                          {deleted_clause}
                        GROUP BY LOWER(TRIM(p.topic))
                        ORDER BY post_count DESC, topic ASC
                        LIMIT %s
                        OFFSET %s
                    )
                    SELECT
                        tb.topic,
                        tb.post_count,
                        COALESCE(tcs.dominant_tag, '') AS dominant_tag,
                        COALESCE(tcs.dominant_ratio, 0) AS dominant_ratio
                    FROM topic_base tb
                    LEFT JOIN topic_content_stats tcs ON LOWER(tcs.topic) = tb.topic
                    """,
                    (min_topic, max_topic, f"%{like_query}%", limit + 1, offset),
                )
                topic_rows = cur.fetchall()
                has_more_topics = len(topic_rows) > limit
                topic_rows = topic_rows[:limit]

                topics = []
                topic_list = [row[0] for row in topic_rows]
                stats = _compute_dominant_flags(cur, topic_list) if topic_list else {}

                for row in topic_rows:
                    topic, post_count, dominant_tag, dominant_ratio = row
                    stat = stats.get(topic, {}) if stats else {}
                    dom_tag = str(stat.get("dominant_tag") or "").lower()
                    dom_ratio = float(stat.get("dominant_ratio") or 0)
                    topics.append(
                        {
                            "topic": topic,
                            "post_count": int(post_count or 0),
                            "dominant_tag": dom_tag or None,
                            "dominant_ratio": dom_ratio,
                        }
                    )

                result["topics"] = topics
                result["has_more_topics"] = has_more_topics

            # Search users (if not filtering or filtering to users)
            if not search_type_filter or search_type_filter == "users":
                cur.execute(
                    f"""
                    SELECT pr.owner, COALESCE(pr.username, ''), pr.level, pr.created_at,
                           (SELECT COUNT(1) FROM posts p WHERE LOWER(p.owner) = LOWER(pr.owner) 
                            AND COALESCE(p.target, '') = '' {deleted_clause}) as post_count
                    FROM profiles pr
                    WHERE pr.username IS NOT NULL 
                      AND pr.username != ''
                      AND LOWER(pr.username) LIKE %s
                    ORDER BY pr.created_at DESC
                    LIMIT %s OFFSET %s
                    """,
                    (f"%{like_query}%", limit + 1, offset),
                )
                user_rows = cur.fetchall()
                has_more_users = len(user_rows) > limit
                user_rows = user_rows[:limit]

                users = []
                for row in user_rows:
                    addr, uname, level, created_at, post_count = row
                    if addr.lower() in blocked_users:
                        continue
                    users.append(
                        {
                            "address": addr,
                            "username": uname or None,
                            "level": level or 0,
                            "created_at": int(created_at) if created_at else None,
                            "post_count": int(post_count or 0),
                        }
                    )

                result["users"] = users
                result["has_more_users"] = has_more_users

            # Search posts (if not filtering or filtering to posts)
            if not search_type_filter or search_type_filter == "posts":
                cur.execute(
                    f"""
                    SELECT p.txhash, p.owner, p.created_at, p.topic, p.title, p.content,
                           COALESCE(pr.username, '') as username,
                           COALESCE(p.target, '') as target,
                           COALESCE(p.tag, '') as tag,
                           COALESCE(p.thumbnail_url, '') as thumbnail,
                           COALESCE(pr.level, 0) as author_level,
                           COALESCE(p.media, '[]') as media
                    FROM posts p
                    LEFT JOIN profiles pr ON pr.owner = p.owner
                    WHERE COALESCE(p.target, '') = ''
                      AND (LOWER(p.title) LIKE %s OR LOWER(p.content) LIKE %s)
                      {deleted_clause}
                    ORDER BY p.created_at DESC
                    LIMIT %s OFFSET %s
                    """,
                    (f"%{like_query}%", f"%{like_query}%", limit + 1, offset),
                )
                post_rows = cur.fetchall()
                has_more_posts = len(post_rows) > limit
                post_rows = post_rows[:limit]

                posts = _format_search_posts(
                    cur, post_rows, blocked_posts, blocked_users, viewer, deleted_bare, blocked_topics
                )
                result["posts"] = posts
                result["has_more_posts"] = has_more_posts

        conn.close()
        return jsonify(result)
    except Exception as e:
        return safe_error(e)


def _format_search_posts(cur, rows, blocked_posts, blocked_users, viewer, deleted_bare, blocked_topics=None):
    """Format post rows for search results with vote counts."""
    # Filter blocked posts, users, and topics
    filtered = []
    for r in rows:
        txhash = (r[0] or "").lower()
        owner = (r[1] or "").lower()
        topic = (r[3] or "").strip().lower() if len(r) > 3 else ""
        if txhash in blocked_posts or owner in blocked_users:
            continue
        if blocked_topics and topic in blocked_topics:
            continue
        filtered.append(r)

    if not filtered:
        return []

    post_ids = [(r[0] or "").lower() for r in filtered]

    # Get points (sum of user_weight)
    vote_totals = {}
    if post_ids:
        placeholders = ",".join(["%s"] * len(post_ids))
        if blocked_users:
            blocked_placeholders = ",".join(["%s"] * len(blocked_users))
            cur.execute(
                f"""SELECT LOWER(target), COALESCE(SUM(user_weight), 0) FROM votes 
                WHERE LOWER(target) IN ({placeholders})
                  AND LOWER(owner) NOT IN ({blocked_placeholders})
                GROUP BY LOWER(target)""",
                post_ids + list(blocked_users),
            )
        else:
            cur.execute(
                f"""SELECT LOWER(target), COALESCE(SUM(user_weight), 0) FROM votes 
                WHERE LOWER(target) IN ({placeholders}) GROUP BY LOWER(target)""",
                post_ids,
            )
        for tgt, vote_sum in cur.fetchall():
            if tgt:
                vote_totals[tgt] = round(vote_sum or 0)

    # Get comment counts
    comment_counts = {}
    if post_ids:
        placeholders = ",".join(["%s"] * len(post_ids))
        all_blocked = blocked_posts | blocked_users
        if all_blocked:
            blocked_placeholders = ",".join(["%s"] * len(all_blocked))
            cur.execute(
                f"""
                SELECT LOWER(root_post_id), COUNT(1)
                FROM posts
                WHERE LOWER(root_post_id) IN ({placeholders})
                  AND COALESCE(target, '') != ''
                  AND LOWER(txhash) NOT IN ({blocked_placeholders})
                  AND LOWER(owner) NOT IN ({blocked_placeholders})
                  {deleted_bare}
                GROUP BY LOWER(root_post_id)
                """,
                post_ids + list(all_blocked) + list(all_blocked),
            )
        else:
            cur.execute(
                f"""
                SELECT LOWER(root_post_id), COUNT(1)
                FROM posts
                WHERE LOWER(root_post_id) IN ({placeholders})
                  AND COALESCE(target, '') != ''
                  {deleted_bare}
                GROUP BY LOWER(root_post_id)
                """,
                post_ids,
            )
        for root_id, cnt in cur.fetchall():
            if root_id:
                comment_counts[root_id] = int(cnt or 0)

    # Get viewer's votes and user_weight contributions
    user_votes = {}
    user_weight_map = {}
    viewer_lower = (viewer or "").strip().lower()
    if viewer_lower and viewer_lower != "guest" and post_ids:
        placeholders = ",".join(["%s"] * len(post_ids))
        cur.execute(
            f"""SELECT LOWER(target), user_vote, user_weight FROM votes
                WHERE LOWER(owner) = %s AND LOWER(target) IN ({placeholders})""",
            [viewer_lower] + post_ids,
        )
        for tgt, vote, weight in cur.fetchall():
            if tgt:
                user_votes[tgt] = int(vote) if vote else 0
                user_weight_map[tgt] = float(weight) if weight else 0.0

    posts = []
    for row in filtered:
        import json as _json

        if len(row) >= 12:
            txhash, owner, ts, topic, title, content, username, target, tag, thumbnail, author_level, media_raw = row[
                :12
            ]
        else:
            txhash, owner, ts, topic, title, content, username, target, tag, thumbnail, author_level = row
            media_raw = "[]"
        try:
            media_val = _json.loads(media_raw or "[]")
            if not isinstance(media_val, list):
                media_val = []
        except Exception:
            media_val = []
        pid = (txhash or "").lower()
        posts.append(
            {
                "post_id": pid,
                "user_id": owner,
                "username": username or None,
                "author_level": int(author_level) if author_level else 0,
                "timestamp": int(ts) if ts else None,
                "topic": topic,
                "title": title,
                "content": content,
                "tag": tag or "",
                "thumbnail": thumbnail or "",
                "media": media_val,
                "points": vote_totals.get(pid, 0),
                "comments": comment_counts.get(pid, 0),
                "user_vote": user_votes.get(pid, 0),
                "user_weight": user_weight_map.get(pid, 0.0),
            }
        )

    return posts


@public_bp.route("/api/get_posts")
def get_posts():
    rid = next_request_id()
    t_start = time.monotonic()
    limit = request.args.get("limit", 25, type=int)
    limit = min(max(1, limit), 100)
    page = request.args.get("page", 1, type=int)
    page = max(1, page)
    offset = (page - 1) * limit
    topic = request.args.get("topic", default=None, type=str)
    address = request.args.get("address", default="", type=str)

    # Parse allowed_tags: comma-separated list of tags the user wants to see
    # Default: only 'sensitive' is allowed; others (porn, violence, gore, death) are hidden
    allowed_tags_raw = request.args.get("allowed_tags", default="sensitive", type=str)
    allowed_tags = set(t.strip().lower() for t in (allowed_tags_raw or "").split(",") if t.strip())

    try:
        conn = connect_db(timeout=10.0, busy_timeout_ms=15000)
        cur = conn.cursor()
        blocked_posts = _get_blocked_posts(cur, address)
        blocked_users = _get_blocked_users(cur, address)
        blocked_topics = _get_blocked_topics(cur, address)

        deleted_clause = _deleted_filter()

        # New feed modes: Home / Following
        feed = request.args.get("feed", default=None, type=str)
        feed = (feed or "").strip().lower()
        sort_mode = (request.args.get("by", default="", type=str) or "").strip().lower()

        # Only supported sort modes.
        if sort_mode and sort_mode not in ("magic", "newest"):
            return jsonify({"error": f"unsupported sort mode: {sort_mode}"}), 400

        sort_mode = sort_mode or "magic"
        if feed in ("home", "following"):
            try:
                log_event(
                    next_request_id(),
                    "get_posts.feed",
                    feed=feed,
                    address=(address[:12] + "...") if address else "",
                    page=page,
                    limit=limit,
                    by=sort_mode,
                )
            except Exception:
                pass

            # Home feed uses new similarity-based algorithm
            if feed == "home":
                resp = _get_home_feed(
                    cur,
                    viewer=address,
                    limit=limit,
                    page=page,
                    blocked_posts=blocked_posts,
                    blocked_users=blocked_users,
                    allowed_tags=allowed_tags,
                    seed=int(time.time() // 60),
                    sort_mode=sort_mode,
                    blocked_topics=blocked_topics,
                )
            else:
                resp = _get_following_feed(
                    cur,
                    viewer=address,
                    limit=limit,
                    page=page,
                    blocked_posts=blocked_posts,
                    blocked_users=blocked_users,
                    allowed_tags=allowed_tags,
                    sort_mode=sort_mode,
                    blocked_topics=blocked_topics,
                )

            conn.close()
            return jsonify(resp)

        # First, get total count for pagination
        t_count = time.monotonic()
        if topic and topic != "all":
            cur.execute(
                f"""
                SELECT COUNT(1)
                FROM posts p
                WHERE COALESCE(p.target, '') = '' AND LOWER(p.topic) = LOWER(%s) AND LENGTH(COALESCE(p.title,'')) > 0 {deleted_clause}
                """,
                (topic,),
            )
        else:
            cur.execute(
                f"""
                SELECT COUNT(1)
                FROM posts p
                WHERE COALESCE(p.target, '') = '' AND LENGTH(COALESCE(p.title,'')) > 0 {deleted_clause}
                """,
            )
        total = cur.fetchone()[0] or 0
        count_ms = (time.monotonic() - t_count) * 1000

        # Fetch candidate posts. For magic mode we must rank in Python using the same Magic scorer.
        # (Eligibility comes from the topic filter; ranking is always via `_score_magic`.)
        max_candidates = max(500, limit * page * 3)
        order_clause = "ORDER BY p.created_at DESC"

        t_select = time.monotonic()
        if topic and topic != "all":
            cur.execute(
                f"""
                SELECT p.txhash,
                       p.owner,
                       p.created_at,
                       p.topic,
                       p.title,
                       p.content,
                       COALESCE(p.tag, '') AS tag,
                       COALESCE(p.root_topic, p.topic, '') AS root_topic,
                       COALESCE(p.root_post_id, p.txhash, '') AS root_post_id,
                       COALESCE(pr.username, '') as username,
                       COALESCE(p.edited_at, 0) as edited_at,
                      COALESCE(p.thumbnail_url, '') as thumbnail,
                      COALESCE(pr.level, 0) as author_level,
                      COALESCE(p.media, '[]') as media
                FROM posts p
                LEFT JOIN profiles pr ON pr.owner = p.owner
                WHERE COALESCE(p.target, '') = '' AND LOWER(p.topic) = LOWER(%s) AND LENGTH(COALESCE(p.title,'')) > 0 {deleted_clause}
                {order_clause}
                LIMIT %s
                """,
                (topic, max_candidates),
            )
        else:
            cur.execute(
                f"""
                SELECT p.txhash,
                       p.owner,
                       p.created_at,
                       p.topic,
                       p.title,
                       p.content,
                       COALESCE(p.tag, '') AS tag,
                       COALESCE(p.root_topic, p.topic, '') AS root_topic,
                       COALESCE(p.root_post_id, p.txhash, '') AS root_post_id,
                       COALESCE(pr.username, '') as username,
                       COALESCE(p.edited_at, 0) as edited_at,
                       COALESCE(p.thumbnail_url, '') as thumbnail,
                       COALESCE(pr.level, 0) as author_level
                FROM posts p
                LEFT JOIN profiles pr ON pr.owner = p.owner
                WHERE COALESCE(p.target, '') = '' AND LENGTH(COALESCE(p.title,'')) > 0 {deleted_clause}
                {order_clause}
                LIMIT %s
                """,
                (max_candidates,),
            )
        rows = cur.fetchall()
        select_ms = (time.monotonic() - t_select) * 1000

        # Filter blocked posts, posts from blocked users, and posts with disallowed tags
        def _tag_allowed(row_tag):
            t = (row_tag or "").strip().lower()
            return not t or t in allowed_tags  # Empty tag (safe) is always allowed

        rows = [
            r
            for r in rows
            if (r[0] or "").lower() not in blocked_posts
            and (r[1] or "").lower() not in blocked_users
            and (r[3] or "").strip().lower() not in blocked_topics
            and _tag_allowed(r[6] if len(r) > 6 else "")
        ]
        post_ids = [r[0].lower() for r in rows]
        vote_totals: Dict[str, int] = {}
        comment_counts: Dict[str, int] = {}
        if post_ids:
            placeholders = ",".join(["%s"] * len(post_ids))
            # Filter votes from blocked users
            if blocked_users:
                blocked_placeholders = ",".join(["%s"] * len(blocked_users))
                cur.execute(
                    f"""SELECT LOWER(target), COALESCE(SUM(user_weight), 0) FROM votes 
                    WHERE LOWER(target) IN ({placeholders})
                      AND LOWER(owner) NOT IN ({blocked_placeholders})
                    GROUP BY LOWER(target)""",
                    post_ids + list(blocked_users),
                )
            else:
                cur.execute(
                    f"""SELECT LOWER(target), COALESCE(SUM(user_weight), 0) FROM votes 
                    WHERE LOWER(target) IN ({placeholders}) GROUP BY LOWER(target)""",
                    post_ids,
                )
            for tgt, vote_sum in cur.fetchall():
                if tgt is not None:
                    vote_totals[tgt] = vote_sum

            # Count comments via root_post_id (batched query)
            deleted_bare = _deleted_filter_bare()
            all_blocked = blocked_posts | blocked_users
            if all_blocked:
                blocked_placeholders = ",".join(["%s"] * len(all_blocked))
                cur.execute(
                    f"""
                    SELECT LOWER(root_post_id), COUNT(1)
                    FROM posts
                    WHERE LOWER(root_post_id) IN ({placeholders})
                      AND COALESCE(target, '') != ''
                      AND LOWER(txhash) NOT IN ({blocked_placeholders})
                      AND LOWER(owner) NOT IN ({blocked_placeholders})
                      {deleted_bare}
                    GROUP BY LOWER(root_post_id)
                    """,
                    post_ids + list(all_blocked) + list(all_blocked),
                )
            else:
                cur.execute(
                    f"""
                    SELECT LOWER(root_post_id), COUNT(1)
                    FROM posts
                    WHERE LOWER(root_post_id) IN ({placeholders})
                      AND COALESCE(target, '') != ''
                      {deleted_bare}
                    GROUP BY LOWER(root_post_id)
                    """,
                    post_ids,
                )
            for root_id, cnt in cur.fetchall():
                if root_id:
                    comment_counts[root_id] = int(cnt or 0)

            # Viewer's votes and user_weight contributions
            user_votes: Dict[str, int] = {}
            user_weight_map: Dict[str, float] = {}
            address_lower = (address or "").strip().lower()
            if address_lower and address_lower != "guest":
                cur.execute(
                    f"""SELECT LOWER(target), user_vote, user_weight FROM votes
                        WHERE LOWER(owner) = %s AND LOWER(target) IN ({placeholders})""",
                    [address_lower] + post_ids,
                )
                for tgt, vote, weight in cur.fetchall():
                    if tgt:
                        user_votes[tgt] = int(vote) if vote else 0
                        user_weight_map[tgt] = float(weight) if weight else 0.0
        else:
            user_votes = {}
            user_weight_map = {}

        # Convert rows to post dicts (and de-dupe / tag-filter consistently)
        seen: set[str] = set()
        candidates: list[dict] = []
        for row in rows:
            post = _row_to_post(row, blocked_posts, blocked_users, allowed_tags, seen, blocked_topics)
            if not post:
                continue
            post["_source"] = "topic" if (topic and topic != "all") else "all"
            candidates.append(post)

        # Attach feed metadata for topic/global feeds.
        topic_lower = (topic or "").strip().lower()
        is_global_topic_feed = (not topic_lower) or (topic_lower == "all")
        topic_feed_type = "all" if is_global_topic_feed else "topic"

        if sort_mode == "magic":
            # Rank via the same Magic scorer (no prefs in topic feeds, P=0).
            from similarity import get_or_compute_similarities

            address_lower = (address or "").strip().lower()
            if address_lower and address_lower != "guest":
                similar_users = get_or_compute_similarities(cur, address_lower)
                sim_lookup = {u[0]: u[1] for u in similar_users}
            else:
                sim_lookup = {}
            similar_addrs = set(sim_lookup.keys())

            post_ids = [p["post_id"] for p in candidates]
            similar_upvotes = _load_similar_user_upvotes(cur, post_ids, similar_addrs)
            unique_commenters = _load_unique_commenter_counts(cur, post_ids, blocked_posts, blocked_users)
            topic_prefs: dict[str, float] = {}
            author_prefs: dict[str, float] = {}
            now_ts = int(time.time())

            scored = []
            for post in candidates:
                score, debug, should_hide = _score_magic(
                    post,
                    sim_lookup,
                    similar_upvotes,
                    unique_commenters,
                    vote_totals,
                    topic_prefs,
                    author_prefs,
                    now_ts,
                    False,
                )
                if should_hide:
                    continue
                pid = post["post_id"]
                post["_score"] = score
                post["feed_debug"] = debug
                post["points"] = float(vote_totals.get(pid, 0.0) or 0.0)
                post["comments"] = int(comment_counts.get(pid, 0) or 0)
                post["unique_commenters"] = int(unique_commenters.get(pid, 0) or 0)
                post["children"] = []
                post["feed_type"] = topic_feed_type
                post["feed_bucket"] = debug.get("bucket", "discovery")
                post["user_vote"] = user_votes.get(pid, 0)
                post["user_weight"] = user_weight_map.get(pid, 0.0)
                scored.append(post)

            scored.sort(key=lambda p: -float(p.get("_score", 0.0)))
            start = (page - 1) * limit
            end = start + limit
            result = scored[start:end] if start < len(scored) else []
            for p in result:
                p.pop("_score", None)
        else:
            # newest: just return the newest candidates (already by created_at desc)
            start = (page - 1) * limit
            end = start + limit
            page_posts = candidates[start:end] if start < len(candidates) else []
            result = []
            for post in page_posts:
                pid = post["post_id"]
                post["points"] = float(vote_totals.get(pid, 0.0) or 0.0)
                post["comments"] = int(comment_counts.get(pid, 0) or 0)
                post["children"] = []
                post["feed_type"] = topic_feed_type
                post["feed_bucket"] = "newest"
                post["user_vote"] = user_votes.get(pid, 0)
                post["user_weight"] = user_weight_map.get(pid, 0.0)
                post["feed_debug"] = {
                    "bucket": "newest",
                    "reason": "Newest",
                    "score": float(post.get("timestamp", 0) or 0),
                    "equation": "timestamp",
                    "formula": f"ts = {int(post.get('timestamp', 0) or 0)}",
                }
                result.append(post)

        has_more = (page * limit) < total

        resp = {"posts": result, "total": total, "page": page, "limit": limit, "has_more": has_more}
        total_ms = (time.monotonic() - t_start) * 1000
        if max(total_ms, count_ms, select_ms) > 2000:
            log_event(
                rid,
                "get_posts.slow",
                topic=topic or "all",
                page=page,
                limit=limit,
                count_ms=round(count_ms, 1),
                select_ms=round(select_ms, 1),
                total_ms=round(total_ms, 1),
                candidates=len(rows),
                sort=sort_mode,
            )

        conn.close()
        return jsonify(_inject_balance(resp, address))
    except Exception as e:
        log_event(rid, "get_posts.err", error=str(e))
        return safe_error(e)


@public_bp.route("/api/get_user_posts")
def get_user_posts():
    owner = request.args.get("owner", type=str)
    viewer = request.args.get("address", default="", type=str)
    limit = request.args.get("limit", 10, type=int)
    page = request.args.get("page", 1, type=int)
    post_type = request.args.get("type", default="", type=str)
    limit = min(max(1, limit), 50)
    page = max(1, page)
    offset = (page - 1) * limit

    if not owner:
        return jsonify({"error": "owner is required"}), 400

    try:
        conn = connect_db(timeout=10.0, busy_timeout_ms=15000)
        cur = conn.cursor()
        blocked_posts = _get_blocked_posts(cur, viewer)
        blocked_users = _get_blocked_users(cur, viewer)
        blocked_topics = _get_blocked_topics(cur, viewer)

        deleted_clause = _deleted_filter()

        type_filter = ""
        if post_type == "submissions":
            type_filter = "AND COALESCE(p.target, '') = ''"
        elif post_type == "comments":
            type_filter = "AND COALESCE(p.target, '') != ''"

        cur.execute(
            f"""
            SELECT p.txhash, p.owner, p.created_at, p.topic, p.title, p.content,
                   COALESCE(pr.username, '') as username,
                   COALESCE(p.target, '') as target,
                   (p.edited_at IS NOT NULL) as edited,
                   COALESCE(p.edited_at, 0) as edited_at,
                   COALESCE(p.thumbnail_url, '') as thumbnail,
                   COALESCE(pr.level, 0) as author_level,
                   COALESCE(p.media, '[]') as media
            FROM posts p
            LEFT JOIN profiles pr ON pr.owner = p.owner
            WHERE LOWER(p.owner) = LOWER(%s)
              {deleted_clause}
              {type_filter}
            ORDER BY p.created_at DESC
            LIMIT %s OFFSET %s
            """,
            (owner, limit, offset),
        )
        rows = cur.fetchall()
        rows = [
            r
            for r in rows
            if (r[0] or "").lower() not in blocked_posts
            and (r[1] or "").lower() not in blocked_users
            and (r[3] or "").strip().lower() not in blocked_topics
        ]
        post_ids = [r[0].lower() for r in rows]
        vote_totals: Dict[str, int] = {}
        comment_counts: Dict[str, int] = {}
        if post_ids:
            placeholders = ",".join(["%s"] * len(post_ids))
            if blocked_users:
                blocked_placeholders = ",".join(["%s"] * len(blocked_users))
                cur.execute(
                    f"""SELECT LOWER(target), COALESCE(SUM(user_weight), 0) FROM votes 
                    WHERE LOWER(target) IN ({placeholders})
                      AND LOWER(owner) NOT IN ({blocked_placeholders})
                    GROUP BY LOWER(target)""",
                    post_ids + list(blocked_users),
                )
            else:
                cur.execute(
                    f"""SELECT LOWER(target), COALESCE(SUM(user_weight), 0) FROM votes 
                    WHERE LOWER(target) IN ({placeholders}) GROUP BY LOWER(target)""",
                    post_ids,
                )
            for tgt, vote_sum in cur.fetchall():
                if tgt is not None:
                    vote_totals[tgt] = vote_sum

            # Count comments via root_post_id (batched query)
            deleted_bare = _deleted_filter_bare()
            all_blocked = blocked_posts | blocked_users
            if all_blocked:
                blocked_placeholders = ",".join(["%s"] * len(all_blocked))
                cur.execute(
                    f"""
                    SELECT LOWER(root_post_id), COUNT(1)
                    FROM posts
                    WHERE LOWER(root_post_id) IN ({placeholders})
                      AND COALESCE(target, '') != ''
                      AND LOWER(txhash) NOT IN ({blocked_placeholders})
                      AND LOWER(owner) NOT IN ({blocked_placeholders})
                      {deleted_bare}
                    GROUP BY LOWER(root_post_id)
                    """,
                    post_ids + list(all_blocked) + list(all_blocked),
                )
            else:
                cur.execute(
                    f"""
                    SELECT LOWER(root_post_id), COUNT(1)
                    FROM posts
                    WHERE LOWER(root_post_id) IN ({placeholders})
                      AND COALESCE(target, '') != ''
                      {deleted_bare}
                    GROUP BY LOWER(root_post_id)
                    """,
                    post_ids,
                )
            for root_id, cnt in cur.fetchall():
                if root_id:
                    comment_counts[root_id] = int(cnt or 0)

            # Viewer's votes and user_weight contributions
            user_votes: Dict[str, int] = {}
            user_weight_map: Dict[str, float] = {}
            viewer_lower = (viewer or "").strip().lower()
            if viewer_lower and viewer_lower != "guest":
                cur.execute(
                    f"""SELECT LOWER(target), user_vote, user_weight FROM votes
                        WHERE LOWER(owner) = %s AND LOWER(target) IN ({placeholders})""",
                    [viewer_lower] + post_ids,
                )
                for tgt, vote, weight in cur.fetchall():
                    if tgt:
                        user_votes[tgt] = int(vote) if vote else 0
                        user_weight_map[tgt] = float(weight) if weight else 0.0
        else:
            user_votes = {}
            user_weight_map = {}

        total = 0
        try:
            cur.execute(
                f"""
                SELECT COUNT(1)
                FROM posts p
                WHERE LOWER(p.owner) = LOWER(%s)
                  {deleted_clause}
                  {type_filter}
                """,
                (owner,),
            )
            total_row = cur.fetchone()
            total = int(total_row[0] or 0) if total_row else 0
        except Exception:
            total = len(rows)

        result = []
        for row in rows:
            import json as _json

            media_raw = "[]"
            if len(row) >= 13:
                (
                    txhash,
                    owner_addr,
                    ts,
                    topic,
                    title,
                    content,
                    uname,
                    target,
                    edited,
                    edited_at,
                    thumbnail,
                    author_level,
                    media_raw,
                ) = row[:13]
            elif len(row) >= 12:
                (
                    txhash,
                    owner_addr,
                    ts,
                    topic,
                    title,
                    content,
                    uname,
                    target,
                    edited,
                    edited_at,
                    thumbnail,
                    author_level,
                ) = row
            elif len(row) >= 11:
                txhash, owner_addr, ts, topic, title, content, uname, target, edited, edited_at, thumbnail = row
                author_level = 0
            elif len(row) == 10:
                txhash, owner_addr, ts, topic, title, content, uname, target, edited, edited_at = row
                thumbnail = ""
                author_level = 0
            else:
                txhash, owner_addr, ts, topic, title, content, uname, target = row
                edited, edited_at = 0, 0
                thumbnail = ""
                author_level = 0
            try:
                media_val = _json.loads(media_raw or "[]")
                if not isinstance(media_val, list):
                    media_val = []
            except Exception:
                media_val = []
            pid = (txhash or "").lower()
            result.append(
                {
                    "post_id": pid,
                    "user_id": owner_addr,
                    "username": uname,
                    "author_level": int(author_level) if author_level else 0,
                    "timestamp": int(ts) if ts is not None else None,
                    "topic": topic,
                    "title": title,
                    "content": content,
                    "target": target,
                    "edited": bool(edited_at),
                    "edited_at": int(edited_at or 0),
                    "thumbnail": thumbnail,
                    "media": media_val,
                    "points": vote_totals.get(pid, 0),
                    "comments": comment_counts.get(pid, 0),
                    "user_vote": user_votes.get(pid, 0),
                    "user_weight": user_weight_map.get(pid, 0.0),
                }
            )
        conn.close()
        has_more = (page * limit) < total
        resp = {"posts": result, "page": page, "limit": limit, "has_more": has_more, "total": total}
        return jsonify(_inject_balance(resp, viewer))
    except Exception as e:
        return safe_error(e)


@public_bp.route("/api/get_reports")
def get_reports():
    try:
        addr = request.args.get("address", default=None, type=str)
        limit = request.args.get("limit", default=100, type=int)
        limit = max(1, min(limit, 500))
        if not addr:
            return jsonify({"error": "missing address"}), 400

        conn = connect_db(timeout=10.0, busy_timeout_ms=15000)
        try:
            cur = conn.cursor()
            cur.execute("SELECT level FROM profiles WHERE LOWER(owner)=LOWER(%s) LIMIT 1", (addr,))
            row = cur.fetchone()
            level = int(row[0]) if row and row[0] is not None else 0
            if level < 100:
                return jsonify({"error": "forbidden"}), 403

            cur.execute(
                """
                SELECT r.id,
                       r.owner,
                       COALESCE(ru.username, ''),
                       r.target,
                       r.reason,
                       r.created_at,
                       COALESCE(p.owner, ''),
                       COALESCE(pr.username, ''),
                       COALESCE(p.title, ''),
                       COALESCE(p.content, '')
                FROM reports r
                LEFT JOIN profiles ru ON LOWER(ru.owner) = LOWER(r.owner)
                LEFT JOIN posts p ON LOWER(p.txhash) = LOWER(r.target)
                LEFT JOIN profiles pr ON pr.owner = p.owner
                ORDER BY r.created_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            rows = cur.fetchall()
            out = []
            for r in rows:
                out.append(
                    {
                        "id": int(r[0]),
                        "reporter_owner": (r[1] or "").lower(),
                        "reporter_username": r[2] or "",
                        "target": (r[3] or "").lower(),
                        "reason": r[4] or "",
                        "timestamp": int(r[5] or 0),
                        "post_owner": (r[6] or "").lower(),
                        "post_username": r[7] or "",
                        "title": r[8] or "",
                        "content": r[9] or "",
                    }
                )
            return jsonify({"reports": out})
        finally:
            try:
                conn.close()
            except Exception:
                pass
    except Exception as e:
        return safe_error(e)


def _fetch_post(
    cur,
    txhash: str,
    blocked_posts: set[str] = None,
    blocked_users: set[str] = None,
    use_stored_counts: bool = False,
    blocked_topics: set[str] = None,
):
    """Fetch a single post with aggregates.

    Args:
        cur: Database cursor
        txhash: Post ID
        blocked_posts: Set of blocked post IDs to filter
        blocked_users: Set of blocked user addresses to filter
        use_stored_counts: If True, use stored comment_count instead of computing
                          via recursive CTE. Faster but doesn't exclude blocked content.
    """
    if blocked_posts is None:
        blocked_posts = set()
    if blocked_users is None:
        blocked_users = set()

    deleted_clause = _deleted_filter()
    cur.execute(
        f"""
        SELECT p.txhash,
               p.owner,
               p.created_at,
               p.topic,
               p.title,
               p.content,
               COALESCE(p.tag, '') as tag,
               COALESCE(p.root_topic, p.topic, '') as root_topic,
               COALESCE(p.root_post_id, p.txhash, '') as root_post_id,
               COALESCE(p.target, '') as target,
               COALESCE(pr.username, '') AS username,
               CASE WHEN p.edited_at IS NULL THEN 0 ELSE 1 END as edited,
               COALESCE(p.edited_at, 0) as edited_at,
               COALESCE(p.thumbnail_url, '') as thumbnail,
               COALESCE(pr.level, 0) as author_level,
               COALESCE(p.comment_count, 0) as comment_count
        FROM posts p
        LEFT JOIN profiles pr ON pr.owner = p.owner
        WHERE LOWER(p.txhash) = LOWER(%s) {deleted_clause} LIMIT 1
        """,
        (txhash,),
    )
    row = cur.fetchone()
    if not row:
        return None
    pid = (row[0] or "").lower()
    owner = (row[1] or "").lower()
    created_at = row[2]
    topic_val = row[3]
    title_val = row[4]
    content_val = row[5]
    tag_val = (row[6] or "").strip()
    root_topic_val = (row[7] or "").strip()
    root_post_id_val = (row[8] or "").strip().lower()
    target_val = (row[9] or "").strip().lower()
    username_val = row[10] or ""
    edited_flag = bool(row[11] if len(row) > 11 else 0)
    edited_at_val = int(row[12] or 0) if len(row) > 12 else 0
    thumbnail_val = (row[13] or "") if len(row) > 13 else ""
    author_level_val = int(row[14]) if len(row) > 14 and row[14] else 0
    stored_comment_count = int(row[15]) if len(row) > 15 and row[15] else 0

    # Filter if post ID is blocked
    if pid in blocked_posts:
        return None

    # Filter if post owner is blocked
    if owner in blocked_users:
        return None

    # Filter if post topic is blocked
    if blocked_topics and (topic_val or "").strip().lower() in blocked_topics:
        return None

    # Filter votes from blocked users; use user_weight for points
    if blocked_users:
        blocked_placeholders = ",".join(["%s"] * len(blocked_users))
        cur.execute(
            f"""SELECT COALESCE(SUM(user_weight), 0) FROM votes 
            WHERE LOWER(target) = %s
              AND LOWER(owner) NOT IN ({blocked_placeholders})""",
            [pid] + list(blocked_users),
        )
    else:
        cur.execute(
            """SELECT COALESCE(SUM(user_weight), 0) FROM votes WHERE LOWER(target) = %s""",
            (pid,),
        )
    points = cur.fetchone()[0] or 0

    # Count comments: use stored count or compute dynamically
    all_blocked = blocked_posts | blocked_users
    if use_stored_counts or not all_blocked:
        # Use stored count when requested or when no blocking filters apply
        comments = stored_comment_count
    else:
        # Compute visible-only count excluding blocked posts/users
        blocked_placeholders = ",".join(["%s"] * len(all_blocked))
        cur.execute(
            f"""
            WITH RECURSIVE subtree(tx, owner) AS (
                SELECT p.txhash, p.owner FROM posts p WHERE COALESCE(p.target,'') = %s {deleted_clause}
                UNION ALL
                SELECT p.txhash, p.owner FROM posts p JOIN subtree s ON p.target = s.tx {deleted_clause}
            )
            SELECT COUNT(1) FROM subtree 
            WHERE LOWER(tx) NOT IN ({blocked_placeholders})
              AND LOWER(owner) NOT IN ({blocked_placeholders})
            """,
            [pid] + list(all_blocked) + list(all_blocked),
        )
        comments = int(cur.fetchone()[0] or 0)
    return {
        "post_id": pid,
        "target": target_val,
        "user_id": owner,
        "username": username_val,
        "author_level": author_level_val,
        "timestamp": int(created_at) if created_at is not None else None,
        "topic": topic_val,
        "root_topic": root_topic_val,
        "root_post_id": root_post_id_val,
        "title": title_val,
        "content": content_val,
        "tag": tag_val,
        "edited": edited_flag,
        "edited_at": edited_at_val,
        "thumbnail": thumbnail_val,
        "points": points,
        "comments": comments,
        "children": [],
    }


def _fetch_comment_tree_batch(
    cur,
    root_id: str,
    blocked_posts: set[str],
    blocked_users: set[str],
    max_depth: int = 6,
    blocked_topics: set[str] = None,
) -> tuple[dict | None, list[dict]]:
    """
    Fetch root post and entire comment subtree in batch queries.
    Returns (root_dict, children_list) where children_list is the top-level children
    with nested 'children' arrays. Returns (None, []) if root not found or blocked.
    """
    deleted_clause = _deleted_filter()
    root_id_lower = root_id.lower()

    # Step 1: Fetch the entire subtree (root + all descendants up to max_depth) in one recursive CTE
    # We include depth to enforce max_depth, and filter deleted posts in the CTE.
    # Blocked posts/users are filtered in Python to allow proper subtree pruning.
    cur.execute(
        f"""
        WITH RECURSIVE subtree AS (
            SELECT p.txhash, p.owner, p.created_at, p.topic, p.title, p.content,
                   COALESCE(p.tag, '') as tag,
                   COALESCE(p.root_topic, p.topic, '') as root_topic,
                   COALESCE(p.root_post_id, p.txhash, '') as root_post_id,
                   COALESCE(p.target, '') as target,
                   COALESCE(p.thumbnail_url, '') as thumbnail,
                   CASE WHEN p.edited_at IS NULL THEN 0 ELSE 1 END as edited,
                   COALESCE(p.edited_at, 0) as edited_at,
                   0 as depth,
                   COALESCE(p.media, '[]') as media
            FROM posts p
            WHERE LOWER(p.txhash) = %s {deleted_clause}
            UNION ALL
            SELECT p.txhash, p.owner, p.created_at, p.topic, p.title, p.content,
                   COALESCE(p.tag, '') as tag,
                   COALESCE(p.root_topic, p.topic, '') as root_topic,
                   COALESCE(p.root_post_id, p.txhash, '') as root_post_id,
                   COALESCE(p.target, '') as target,
                   COALESCE(p.thumbnail_url, '') as thumbnail,
                   CASE WHEN p.edited_at IS NULL THEN 0 ELSE 1 END as edited,
                   COALESCE(p.edited_at, 0) as edited_at,
                   s.depth + 1 as depth,
                   COALESCE(p.media, '[]') as media
            FROM posts p
            JOIN subtree s ON LOWER(p.target) = LOWER(s.txhash)
            WHERE s.depth < %s {deleted_clause}
        )
        SELECT st.txhash, st.owner, st.created_at, st.topic, st.title, st.content,
               st.tag, st.root_topic, st.root_post_id, st.target, st.thumbnail,
               st.edited, st.edited_at, st.depth,
               COALESCE(pr.username, '') as username,
               COALESCE(pr.level, 0) as author_level,
               st.media
        FROM subtree st
        LEFT JOIN profiles pr ON LOWER(pr.owner) = LOWER(st.owner)
        ORDER BY st.depth ASC, st.created_at ASC
        """,
        (root_id_lower, max_depth),
    )
    rows = cur.fetchall()

    if not rows:
        return None, []

    # Build a dict of all posts keyed by post_id, filtering blocked posts/users
    all_posts: dict[str, dict] = {}
    blocked_ids: set[str] = set()  # Track which IDs are blocked (so we prune their subtrees)

    for row in rows:
        pid = (row[0] or "").lower()
        owner = (row[1] or "").lower()
        created_at = row[2]
        topic_val = row[3]
        title_val = row[4]
        content_val = row[5]
        tag_val = (row[6] or "").strip()
        root_topic_val = (row[7] or "").strip()
        root_post_id_val = (row[8] or "").strip().lower()
        target_val = (row[9] or "").strip().lower()
        thumbnail_val = row[10] or ""
        edited_flag = bool(row[11])
        edited_at_val = int(row[12] or 0)
        depth = int(row[13])
        username_val = row[14] or ""
        author_level_val = int(row[15]) if row[15] else 0
        media_raw_val = row[16] if len(row) > 16 else "[]"

        # Parse media JSON array
        try:
            import json as _json

            media_val = _json.loads(media_raw_val or "[]")
            if not isinstance(media_val, list):
                media_val = []
        except Exception:
            media_val = []

        # Skip if this post or its owner is blocked, or topic is blocked
        topic_lower = (row[3] or "").strip().lower()
        if pid in blocked_posts or owner in blocked_users or (blocked_topics and topic_lower in blocked_topics):
            blocked_ids.add(pid)
            continue

        # Skip if parent is blocked (prune subtree)
        if target_val and target_val in blocked_ids:
            blocked_ids.add(pid)
            continue

        all_posts[pid] = {
            "post_id": pid,
            "target": target_val,
            "user_id": owner,
            "username": username_val,
            "author_level": author_level_val,
            "timestamp": int(created_at) if created_at is not None else None,
            "topic": topic_val,
            "root_topic": root_topic_val,
            "root_post_id": root_post_id_val,
            "title": title_val,
            "content": content_val,
            "tag": tag_val,
            "edited": edited_flag,
            "edited_at": edited_at_val,
            "thumbnail": thumbnail_val,
            "media": media_val,
            "points": 0,  # Will be populated later
            "comments": 0,  # Will be computed from tree
            "children": [],
            "user_vote": 0,
            "user_weight": 0.0,
            "_depth": depth,  # Internal, removed before return
        }

    # Check if root exists after filtering
    if root_id_lower not in all_posts:
        return None, []

    # Step 2: Batch fetch vote totals for all posts
    post_ids = list(all_posts.keys())
    if post_ids:
        if blocked_users:
            # Exclude votes from blocked users
            blocked_ph = ",".join(["%s"] * len(blocked_users))
            ph = ",".join(["%s"] * len(post_ids))
            cur.execute(
                f"""
                SELECT LOWER(target), COALESCE(SUM(user_weight), 0)
                FROM votes
                WHERE LOWER(target) IN ({ph})
                  AND LOWER(owner) NOT IN ({blocked_ph})
                GROUP BY LOWER(target)
                """,
                post_ids + list(blocked_users),
            )
        else:
            ph = ",".join(["%s"] * len(post_ids))
            cur.execute(
                f"""
                SELECT LOWER(target), COALESCE(SUM(user_weight), 0)
                FROM votes
                WHERE LOWER(target) IN ({ph})
                GROUP BY LOWER(target)
                """,
                post_ids,
            )
        for tgt, pts in cur.fetchall():
            if tgt and tgt in all_posts:
                all_posts[tgt]["points"] = float(pts) if pts else 0

    # Step 3: Build the tree structure in memory
    # Group children by their target (parent)
    children_by_parent: dict[str, list[dict]] = {}
    for pid, post in all_posts.items():
        target = post["target"]
        if target and target in all_posts:
            if target not in children_by_parent:
                children_by_parent[target] = []
            children_by_parent[target].append(post)

    # Attach children to parents (already sorted by created_at from query)
    for parent_id, kids in children_by_parent.items():
        if parent_id in all_posts:
            all_posts[parent_id]["children"] = kids

    # Step 3b: For posts at max_depth with no loaded children, query actual reply counts
    # This ensures "Continue this thread" links appear when there are deeper replies
    deleted_bare = _deleted_filter_bare()
    leaf_ids = [pid for pid, post in all_posts.items() if post.get("_depth") == max_depth and not post.get("children")]
    leaf_reply_counts: dict[str, int] = {}
    if leaf_ids:
        # Exclude blocked posts/users from the count
        if blocked_posts or blocked_users:
            all_blocked = list((blocked_posts or set()) | (blocked_users or set()))
            blocked_ph = ",".join(["%s"] * len(all_blocked))
            leaf_ph = ",".join(["%s"] * len(leaf_ids))
            cur.execute(
                f"""
                SELECT LOWER(target), COUNT(1)
                FROM posts
                WHERE LOWER(target) IN ({leaf_ph})
                  AND LOWER(txhash) NOT IN ({blocked_ph})
                  AND LOWER(owner) NOT IN ({blocked_ph})
                  {deleted_bare}
                GROUP BY LOWER(target)
                """,
                leaf_ids + all_blocked + all_blocked,
            )
        else:
            leaf_ph = ",".join(["%s"] * len(leaf_ids))
            cur.execute(
                f"""
                SELECT LOWER(target), COUNT(1)
                FROM posts
                WHERE LOWER(target) IN ({leaf_ph})
                  {deleted_bare}
                GROUP BY LOWER(target)
                """,
                leaf_ids,
            )
        for tgt, cnt in cur.fetchall():
            if tgt:
                leaf_reply_counts[tgt] = int(cnt or 0)

    # Step 4: Compute visible-only comment counts via post-order traversal
    def count_descendants(node: dict) -> int:
        """Count all descendants (recursive). Updates node['comments'] and returns total."""
        total = 0
        for child in node.get("children", []):
            total += 1 + count_descendants(child)
        # For leaf nodes at max_depth, use the queried reply count instead
        pid = node.get("post_id", "")
        if pid in leaf_reply_counts:
            node["comments"] = leaf_reply_counts[pid]
        else:
            node["comments"] = total
        return total

    root = all_posts[root_id_lower]
    count_descendants(root)

    # Step 5: Clean up internal fields
    for post in all_posts.values():
        post.pop("_depth", None)

    # Extract top-level children (direct replies to root)
    top_children = root.pop("children", [])
    root["children"] = []  # Root returns with empty children array (frontend expects this)

    return root, top_children


@public_bp.route("/api/get_comments")
def get_comments():
    rid = next_request_id()
    t_start = time.time()

    post_id = request.args.get("post_id", type=str)
    address = request.args.get("address", default="", type=str)
    if not post_id:
        return jsonify({"error": "post_id is required"}), 400
    try:
        conn = connect_db(timeout=10.0, busy_timeout_ms=15000)
        cur = conn.cursor()

        t_blocked = time.time()
        blocked_posts = _get_blocked_posts(cur, address)
        blocked_users = _get_blocked_users(cur, address)
        blocked_topics = _get_blocked_topics(cur, address)
        t_blocked_ms = (time.time() - t_blocked) * 1000

        t_tree = time.time()
        root, children = _fetch_comment_tree_batch(
            cur, post_id, blocked_posts, blocked_users, max_depth=6, blocked_topics=blocked_topics
        )
        t_tree_ms = (time.time() - t_tree) * 1000

        if not root:
            conn.close()
            log_event(rid, "get_comments.not_found", post_id=post_id[:16])
            return jsonify({"error": "Post not found"}), 404

        # Count total nodes for logging
        def count_nodes(nodes):
            total = 0
            for n in nodes:
                total += 1
                if n.get("children"):
                    total += count_nodes(n["children"])
            return total

        node_count = 1 + count_nodes(children)  # root + all children

        # Load viewer's votes and user_weight contributions for root and all children
        viewer_lower = (address or "").strip().lower()
        t_votes = time.time()
        if viewer_lower and viewer_lower != "guest":
            all_post_ids = [root["post_id"]]

            def collect_ids(nodes):
                for n in nodes:
                    all_post_ids.append(n["post_id"])
                    if n.get("children"):
                        collect_ids(n["children"])

            collect_ids(children)
            if all_post_ids:
                ph = ",".join(["%s"] * len(all_post_ids))
                cur.execute(
                    f"SELECT LOWER(target), user_vote, user_weight FROM votes WHERE LOWER(owner) = %s AND LOWER(target) IN ({ph})",
                    [viewer_lower] + all_post_ids,
                )
                user_votes = {}
                user_weight_map = {}
                for tgt, vote, weight in cur.fetchall():
                    if tgt:
                        user_votes[tgt] = int(vote) if vote else 0
                        user_weight_map[tgt] = float(weight) if weight else 0.0
                root["user_vote"] = user_votes.get(root["post_id"], 0)
                root["user_weight"] = user_weight_map.get(root["post_id"], 0.0)

                def apply_votes(nodes):
                    for n in nodes:
                        n["user_vote"] = user_votes.get(n["post_id"], 0)
                        n["user_weight"] = user_weight_map.get(n["post_id"], 0.0)
                        if n.get("children"):
                            apply_votes(n["children"])

                apply_votes(children)
        t_votes_ms = (time.time() - t_votes) * 1000

        resp = {"root": root, "children": children}

        conn.close()

        total_ms = (time.time() - t_start) * 1000
        log_event(
            rid,
            "get_comments.ok",
            post_id=post_id[:16],
            nodes=node_count,
            blocked_posts=len(blocked_posts),
            blocked_users=len(blocked_users),
            blocked_ms=round(t_blocked_ms, 1),
            tree_ms=round(t_tree_ms, 1),
            votes_ms=round(t_votes_ms, 1),
            total_ms=round(total_ms, 1),
        )
        return jsonify(_inject_balance(resp, address))
    except Exception as e:
        log_event(rid, "get_comments.err", error=str(e))
        return safe_error(e)


def _find_root_post_id(cur, comment_id: str):
    """Find the root post ID for a given comment by traversing up the tree."""
    deleted_clause = _deleted_filter_bare()
    current_id = comment_id.lower()
    visited = set()
    max_depth = 100

    for _ in range(max_depth):
        if current_id in visited:
            break
        visited.add(current_id)

        cur.execute(
            f"SELECT COALESCE(target, '') FROM posts WHERE LOWER(txhash) = LOWER(%s) {deleted_clause} LIMIT 1",
            (current_id,),
        )
        row = cur.fetchone()
        if not row:
            break
        target = (row[0] or "").strip().lower()
        if not target:
            return current_id
        current_id = target

    return None


def _fetch_parent_chain(
    cur, comment_id: str, max_depth: int = 3, blocked_posts: set[str] = None, blocked_users: set[str] = None
):
    """Fetch up to max_depth parent comments in the chain."""
    if blocked_posts is None:
        blocked_posts = set()
    if blocked_users is None:
        blocked_users = set()
    deleted_clause = _deleted_filter_bare()
    chain = []
    current_id = comment_id.lower()
    visited = set()

    for _ in range(max_depth):
        if current_id in visited:
            break
        visited.add(current_id)

        cur.execute(
            f"SELECT COALESCE(target, '') FROM posts WHERE LOWER(txhash) = LOWER(%s) {deleted_clause} LIMIT 1",
            (current_id,),
        )
        row = cur.fetchone()
        if not row:
            break
        target = (row[0] or "").strip().lower()
        if not target:
            break

        parent_post = _fetch_post(cur, target, blocked_posts, blocked_users)
        if parent_post:
            chain.append(parent_post)
        current_id = target

    return chain


@public_bp.route("/api/get_root_post_id")
def get_root_post_id():
    comment_id = request.args.get("comment_id", type=str)
    if not comment_id:
        return jsonify({"error": "comment_id is required"}), 400
    try:
        conn = connect_db(timeout=10.0, busy_timeout_ms=15000)
        cur = conn.cursor()
        root_id = _find_root_post_id(cur, comment_id)
        conn.close()
        if not root_id:
            return jsonify({"error": "Comment not found or invalid"}), 404
        return jsonify({"root_post_id": root_id, "comment_id": comment_id})
    except Exception as e:
        return safe_error(e)


@public_bp.route("/api/get_comment_context")
def get_comment_context():
    rid = next_request_id()
    comment_id = request.args.get("comment_id", type=str)
    address = request.args.get("address", default="", type=str)
    max_depth_raw = request.args.get("max_depth", default=None, type=str)

    # Parse and validate max_depth strictly (1-5, hard error on invalid)
    if max_depth_raw is None:
        max_depth = 5  # Default to max
    else:
        try:
            max_depth = int(max_depth_raw)
        except (ValueError, TypeError):
            log_event(rid, "get_comment_context.invalid_depth", raw=max_depth_raw)
            return jsonify({"error": f"Invalid max_depth '{max_depth_raw}'. Must be integer 1-5."}), 400
        if max_depth < 1 or max_depth > 5:
            log_event(rid, "get_comment_context.invalid_depth", value=max_depth)
            return jsonify({"error": f"max_depth must be 1-5, got {max_depth}"}), 400

    if not comment_id:
        return jsonify({"error": "comment_id is required"}), 400
    try:
        conn = connect_db(timeout=10.0, busy_timeout_ms=15000)
        cur = conn.cursor()
        blocked_posts = _get_blocked_posts(cur, address)
        blocked_users = _get_blocked_users(cur, address)
        blocked_topics_set = _get_blocked_topics(cur, address)
        chain = _fetch_parent_chain(cur, comment_id, max_depth, blocked_posts, blocked_users)
        conn.close()
        resp = {"context": chain, "comment_id": comment_id}
        return jsonify(_inject_balance(resp, address))
    except Exception as e:
        return safe_error(e)


@public_bp.route("/api/get_inbox")
def get_inbox():
    import logging

    logger = logging.getLogger(__name__)
    t_start = time.time()

    address = request.args.get("address", default="", type=str)
    page = request.args.get("page", 1, type=int)
    limit = request.args.get("limit", 25, type=int)

    if not address:
        return jsonify({"error": "address is required"}), 400

    limit = min(max(1, limit), 100)
    page = max(1, page)
    offset = (page - 1) * limit
    viewer_lower = address.lower()

    try:
        t_db_open = time.time()
        conn = connect_db(timeout=30.0, busy_timeout_ms=15000)
        cur = conn.cursor()
        logger.info(f"[get_inbox] DB open: {(time.time() - t_db_open)*1000:.1f}ms")

        t_blocked = time.time()
        blocked_posts = _get_blocked_posts(cur, address)
        blocked_users = _get_blocked_users(cur, address)
        blocked_topics = _get_blocked_topics(cur, address)
        logger.info(
            f"[get_inbox] Blocked query: {(time.time() - t_blocked)*1000:.1f}ms, posts={len(blocked_posts)}, users={len(blocked_users)}"
        )

        deleted_filter = "" if IGNORE_DELETIONS else "AND p.deleted = FALSE"

        # Unified inbox: UNION of replies and @mentions, sorted by timestamp
        # Replies use a fixed-depth join to find root posts (up to 10 levels)
        # Mentions join the mentions table with the post containing the mention
        query = f"""
            SELECT * FROM (
                SELECT
                    r.txhash as item_id,
                    r.owner as actor_owner,
                    r.created_at as item_timestamp,
                    r.content as item_content,
                    p.txhash as context_id,
                    p.content as context_content,
                    p.title as context_title,
                    COALESCE(p.target, '') as context_target,
                    p.owner as context_owner,
                    COALESCE(pr.username, '') as actor_username,
                    COALESCE(
                        CASE WHEN COALESCE(p.target, '') = '' THEN p.txhash ELSE NULL END,
                        CASE WHEN COALESCE(p2.target, '') = '' THEN p2.txhash ELSE NULL END,
                        CASE WHEN COALESCE(p3.target, '') = '' THEN p3.txhash ELSE NULL END,
                        CASE WHEN COALESCE(p4.target, '') = '' THEN p4.txhash ELSE NULL END,
                        CASE WHEN COALESCE(p5.target, '') = '' THEN p5.txhash ELSE NULL END,
                        CASE WHEN COALESCE(p6.target, '') = '' THEN p6.txhash ELSE NULL END,
                        CASE WHEN COALESCE(p7.target, '') = '' THEN p7.txhash ELSE NULL END,
                        CASE WHEN COALESCE(p8.target, '') = '' THEN p8.txhash ELSE NULL END,
                        CASE WHEN COALESCE(p9.target, '') = '' THEN p9.txhash ELSE NULL END,
                        CASE WHEN COALESCE(p10.target, '') = '' THEN p10.txhash ELSE NULL END
                    ) as root_post_id,
                    COALESCE(pr.level, 0) as actor_level,
                    'reply' as item_type,
                    COALESCE(r.root_topic, r.topic, '') as item_topic
                FROM posts r
                INNER JOIN posts p ON p.txhash = r.target
                LEFT JOIN profiles pr ON pr.owner = r.owner
                LEFT JOIN posts p2 ON p2.txhash = p.target AND p.target != ''
                LEFT JOIN posts p3 ON p3.txhash = p2.target AND p2.target != ''
                LEFT JOIN posts p4 ON p4.txhash = p3.target AND p3.target != ''
                LEFT JOIN posts p5 ON p5.txhash = p4.target AND p4.target != ''
                LEFT JOIN posts p6 ON p6.txhash = p5.target AND p5.target != ''
                LEFT JOIN posts p7 ON p7.txhash = p6.target AND p6.target != ''
                LEFT JOIN posts p8 ON p8.txhash = p7.target AND p7.target != ''
                LEFT JOIN posts p9 ON p9.txhash = p8.target AND p8.target != ''
                LEFT JOIN posts p10 ON p10.txhash = p9.target AND p9.target != ''
                WHERE LOWER(p.owner) = %s
                  AND LOWER(r.owner) != %s
                  AND r.deleted = FALSE
                  {deleted_filter}

                UNION ALL

                SELECT
                    mp.txhash as item_id,
                    m.mentioner_address as actor_owner,
                    m.created_at as item_timestamp,
                    mp.content as item_content,
                    mp.txhash as context_id,
                    mp.content as context_content,
                    mp.title as context_title,
                    COALESCE(mp.target, '') as context_target,
                    mp.owner as context_owner,
                    COALESCE(mpr.username, '') as actor_username,
                    COALESCE(mp.root_post_id, mp.txhash) as root_post_id,
                    COALESCE(mpr.level, 0) as actor_level,
                    'mention' as item_type,
                    COALESCE(mp.root_topic, mp.topic, '') as item_topic
                FROM mentions m
                INNER JOIN posts mp ON mp.txhash = m.post_txhash AND mp.deleted = FALSE
                LEFT JOIN profiles mpr ON mpr.owner = m.mentioner_address
                WHERE LOWER(m.mentioned_address) = %s
                  AND LOWER(m.mentioner_address) != %s
            ) inbox
            ORDER BY inbox.item_timestamp DESC
            LIMIT %s OFFSET %s
        """

        params = [viewer_lower, viewer_lower, viewer_lower, viewer_lower, limit, offset]

        t_query = time.time()
        cur.execute(query, params)
        rows = cur.fetchall()
        query_ms = (time.time() - t_query) * 1000
        logger.info(f"[get_inbox] Main query: {query_ms:.1f}ms, rows={len(rows)}")

        # Get total count via a separate lightweight query
        count_query = f"""
            SELECT (
                SELECT COUNT(*) FROM posts r
                INNER JOIN posts p ON p.txhash = r.target
                WHERE LOWER(p.owner) = %s AND LOWER(r.owner) != %s
                  AND r.deleted = FALSE {deleted_filter}
            ) + (
                SELECT COUNT(*) FROM mentions m
                INNER JOIN posts mp ON mp.txhash = m.post_txhash AND mp.deleted = FALSE
                WHERE LOWER(m.mentioned_address) = %s AND LOWER(m.mentioner_address) != %s
            )
        """
        cur.execute(count_query, [viewer_lower, viewer_lower, viewer_lower, viewer_lower])
        total_row = cur.fetchone()
        total = int(total_row[0]) if total_row and total_row[0] else 0

        conn.close()

        replies = []
        for row in rows:
            item_id = (row[0] or "").lower()
            actor_owner = (row[1] or "").lower()
            item_timestamp = int(row[2]) if row[2] is not None else None
            item_content = row[3] or ""
            context_id = (row[4] or "").lower()
            context_content = row[5] or ""
            context_title = row[6] or ""
            context_target = (row[7] or "").strip().lower()
            context_owner = (row[8] or "").lower()
            actor_username = row[9] or ""
            root_post_id = (row[10] or "").lower()
            actor_level = int(row[11]) if row[11] else 0
            item_type = row[12] or "reply"
            item_topic = (row[13] or "").strip().lower() if len(row) > 13 else ""

            if item_id in blocked_posts or actor_owner in blocked_users:
                continue
            if context_id in blocked_posts or context_owner in blocked_users:
                continue
            if blocked_topics and item_topic in blocked_topics:
                continue
            if not root_post_id:
                continue

            if item_type == "reply":
                if not context_target:
                    parent_display_text = context_title or ""
                else:
                    parent_display_text = context_content or ""
            else:
                # For mentions, show a snippet of the post content
                parent_display_text = context_title or context_content or ""

            if len(parent_display_text) > 200:
                parent_display_text = parent_display_text[:197] + "..."

            replies.append(
                {
                    "reply_id": item_id,
                    "reply_owner": actor_owner,
                    "reply_username": actor_username,
                    "reply_author_level": actor_level,
                    "reply_content": item_content,
                    "reply_timestamp": item_timestamp,
                    "parent_id": context_id,
                    "parent_content": parent_display_text,
                    "parent_owner": context_owner,
                    "root_post_id": root_post_id,
                    "type": item_type,
                }
            )

        has_more = (page * limit) < total

        total_ms = (time.time() - t_start) * 1000
        logger.info(f"[get_inbox] Total: {total_ms:.1f}ms, replies={len(replies)}, total_count={total}")

        resp = {
            "replies": replies,
            "total": total,
            "page": page,
            "limit": limit,
            "has_more": has_more,
            "_perf_ms": round(total_ms, 1),
            "_query_ms": round(query_ms, 1),
        }
        return jsonify(_inject_balance(resp, address))
    except Exception as e:
        return safe_error(e, context="get_inbox")


@public_bp.route("/api/mark_inbox_viewed", methods=["POST"])
def mark_inbox_viewed():
    """Set the user's inbox_last_viewed_at to now, clearing their unread count."""
    rid = next_request_id()
    data = request.get_json(silent=True) or {}
    address = (data.get("address") or "").strip()
    if not address:
        return jsonify({"error": "address is required"}), 400

    addr_lower = address.lower()
    now_ts = int(time.time())

    try:
        conn = connect_db(timeout=5.0, busy_timeout_ms=10000)
        cur = conn.cursor()
        cur.execute(
            "UPDATE profiles SET inbox_last_viewed_at = %s WHERE LOWER(owner) = %s",
            (now_ts, addr_lower),
        )
        conn.commit()
        conn.close()
        _invalidate_inbox_cache(addr_lower)
        log_event(rid, "mark_inbox_viewed.ok", address=addr_lower)
        return jsonify({"ok": True, "inbox_last_viewed_at": now_ts})
    except Exception as e:
        log_event(rid, "mark_inbox_viewed.err", error=str(e))
        return safe_error(e)


@public_bp.route("/api/get_upload_url", methods=["POST"])
def get_upload_url():
    """Get a direct upload URL for client-side uploads.

    - type=image -> Cloudflare Images direct upload
    - type=video -> Cloudflare Stream direct upload
    """
    rid = next_request_id()
    log_event(rid, "get_upload_url.begin")
    try:
        data = request.get_json(force=True) or {}
        upload_type = str(data.get("type", "image")).strip().lower()

        # accept both image and video
        if False:
            return jsonify({"error": "only 'image' type is supported"}), 400

        account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "").strip()
        api_token = os.environ.get("CLOUDFLARE_API_TOKEN", "").strip()

        if upload_type == "video":
            # Cloudflare Stream direct upload
            stream_customer = os.environ.get("CLOUDFLARE_STREAM_CUSTOMER_CODE", "").strip()
            if not account_id or not api_token:
                log_event(rid, "get_upload_url.err", error="missing_stream_credentials")
                return jsonify({"error": "Cloudflare Stream credentials not configured"}), 500

            url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/stream/direct_upload"
            headers = {"Authorization": f"Bearer {api_token}", "Content-Type": "application/json"}
            payload = {"maxDurationSeconds": 60}
            # IMPORTANT: allowedOrigins required for iframe player on customer domains
            payload["allowedOrigins"] = ["*"]
            response = requests.post(url, headers=headers, json=payload, timeout=10)

            if response.status_code != 200:
                log_event(rid, "get_upload_url.err", error=f"cloudflare_stream_api_error_{response.status_code}")
                return jsonify({"error": "Upload service error"}), 500

            result = response.json()
            # Stream responses typically contain result.uploadURL and sometimes result.uid
            upload_data = result.get("result", {}) if isinstance(result, dict) else {}
            upload_url = upload_data.get("uploadURL", "")
            direct_uid = upload_data.get("uid") or upload_data.get("id") or ""

            if not upload_url:
                log_event(rid, "get_upload_url.err", error="missing_stream_upload_url")
                return jsonify({"error": "No Stream upload URL received from Cloudflare"}), 500

            log_event(rid, "get_upload_url.ok", upload_id=direct_uid)
            # Return uid so client can embed immediately after upload
            return jsonify(
                {"uploadURL": upload_url, "provider": "stream", "streamCustomer": stream_customer, "uid": direct_uid}
            )

        # Default: image (Cloudflare Images)
        account_hash = os.environ.get("CLOUDFLARE_ACCOUNT_HASH", "").strip()
        if not account_id or not api_token or not account_hash:
            log_event(rid, "get_upload_url.err", error="missing_credentials")
            return jsonify({"error": "Cloudflare credentials not configured"}), 500

        url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/images/v2/direct_upload"
        headers = {"Authorization": f"Bearer {api_token}", "Content-Type": "application/json"}
        response = requests.post(url, headers=headers, timeout=10)

        if response.status_code != 200:
            log_event(rid, "get_upload_url.err", error=f"cloudflare_api_error_{response.status_code}")
            return jsonify({"error": "Upload service error"}), 500

        result = response.json()
        if not result.get("success"):
            errors = result.get("errors", [])
            error_msg = errors[0].get("message", "Unknown error") if errors else "Unknown error"
            log_event(rid, "get_upload_url.err", error=f"cloudflare_error_{error_msg}")
            return jsonify({"error": "Upload service error"}), 500

        upload_data = result.get("result", {})
        upload_url = upload_data.get("uploadURL", "")
        upload_id = upload_data.get("id", "")

        if not upload_url:
            log_event(rid, "get_upload_url.err", error="missing_upload_url")
            return jsonify({"error": "No upload URL received from Cloudflare"}), 500

        log_event(rid, "get_upload_url.ok", upload_id=upload_id)
        return jsonify({"uploadURL": upload_url, "id": upload_id, "accountHash": account_hash})
    except Exception as e:
        log_event(rid, "get_upload_url.err", error=str(e))
        return safe_error(e)


@public_bp.route("/api/stream_proxy/<video_uid>", defaults={"path": ""})
@public_bp.route("/api/stream_proxy/<video_uid>/<path:path>")
def stream_proxy(video_uid, path):
    """Proxy HLS manifest and segment requests to avoid CORS issues with Cloudflare Stream.

    Cloudflare Stream returns 500 when browser sends Origin header.
    This proxy forwards the request without Origin header.

    Routes:
    - /api/stream_proxy/{uid} -> manifest
    - /api/stream_proxy/{uid}/{segment_path} -> video segments
    """
    rid = next_request_id()
    try:
        # Validate video UID format (hex string, reasonable length)
        if not video_uid or len(video_uid) < 10 or len(video_uid) > 100:
            return jsonify({"error": "Invalid video UID"}), 400

        # Construct the URL
        if path:
            # Segment, nested manifest, or video segment
            # Nested manifests (.m3u8) need /manifest/ prefix
            if path.endswith(".m3u8") and not path.startswith("manifest/"):
                target_url = f"https://videodelivery.net/{video_uid}/manifest/{path}"
            else:
                # Video segments (.ts) or other files
                target_url = f"https://videodelivery.net/{video_uid}/{path}"
        else:
            # Main manifest
            target_url = f"https://videodelivery.net/{video_uid}/manifest/video.m3u8"

        # Append original query string (e.g., signed token parameters) to target URL
        try:
            if request.query_string:
                qs = request.query_string.decode("utf-8", errors="ignore")
                if qs:
                    target_url = f"{target_url}{'&' if '?' in target_url else '?'}{qs}"
        except Exception:
            pass

        # Forward request without Origin header
        headers = {"User-Agent": request.headers.get("User-Agent", "Mirage/1.0"), "Accept": "*/*"}

        # Handle Range requests for video segments
        if request.headers.get("Range"):
            headers["Range"] = request.headers.get("Range")

        response = requests.get(target_url, headers=headers, timeout=30, stream=True)

        # If Cloudflare returns an error, forward it
        if response.status_code != 200:
            log_event(
                rid,
                "stream_proxy.cloudflare_error",
                status=response.status_code,
                video_uid=video_uid[:20],
                path=path[:50] if path else "",
            )
            from flask import Response

            return Response(
                response.text if hasattr(response, "text") else response.content,
                status=response.status_code,
                headers={
                    "Content-Type": response.headers.get("Content-Type", "text/plain"),
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "GET, OPTIONS",
                    "Access-Control-Allow-Headers": "Range, Content-Type",
                },
            )

        # Determine content type
        content_type = response.headers.get("Content-Type", "application/vnd.apple.mpegurl")
        if path.endswith(".m3u8") or (not path and target_url.endswith(".m3u8")):
            content_type = "application/vnd.apple.mpegurl"
        elif path.endswith(".ts"):
            content_type = "video/mp2t"

        # For manifest files, rewrite URLs to use our proxy
        if content_type == "application/vnd.apple.mpegurl":
            content = response.text
            # Rewrite videodelivery.net URLs to use our proxy
            import re

            # Replace absolute URLs
            content = re.sub(
                r"https://videodelivery\.net/" + re.escape(video_uid) + r"/([^\s]+)",
                lambda m: f"/api/stream_proxy/{video_uid}/{m.group(1)}",
                content,
            )
            # Always rewrite relative nested manifests (.m3u8) to go through our proxy with the UID prefix
            content = re.sub(
                r"^(?!#)(?!(?:/|https?://))([^#\n]+\.m3u8)",
                lambda m: f"/api/stream_proxy/{video_uid}/{m.group(1)}",
                content,
                flags=re.MULTILINE,
            )
            # Rewrite absolute-path nested manifests that start with a slash, e.g., /stream_xxx.m3u8
            content = re.sub(
                r"^/([^#\n]+\.m3u8)",
                lambda m: f"/api/stream_proxy/{video_uid}/{m.group(1)}",
                content,
                flags=re.MULTILINE,
            )
            # Also rewrite URI="...m3u8" attributes in EXT-X-MEDIA lines (audio tracks) to include our proxy and UID
            content = re.sub(
                r'URI="(?!https?://)(?:/)?([^"]+\.m3u8)"',
                lambda m: f'URI="/api/stream_proxy/{video_uid}/{m.group(1)}"',
                content,
            )

            # Handle relative paths like ../../{uid}/video/... or ../../{uid}/audio/... for segments
            # This usually appears in audio track manifests
            # E.g. "../../f365.../audio/132/seg_1.ts" -> "/api/stream_proxy/f365.../audio/132/seg_1.ts"
            content = re.sub(
                r"(\.\./\.\./)(" + re.escape(video_uid) + r")/([^\s]+)",
                lambda m: f"/api/stream_proxy/{m.group(2)}/{m.group(3)}",
                content,
            )

            from flask import Response

            return Response(
                content,
                status=response.status_code,
                headers={
                    "Content-Type": content_type,
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "GET, OPTIONS",
                    "Access-Control-Allow-Headers": "Range, Content-Type",
                    "Cache-Control": response.headers.get("Cache-Control", "public, max-age=600"),
                },
            )

        # For video segments, stream directly
        from flask import Response

        resp_headers = {
            "Content-Type": content_type,
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, OPTIONS",
            "Access-Control-Allow-Headers": "Range, Content-Type",
            "Cache-Control": response.headers.get("Cache-Control", "public, max-age=600"),
        }

        # Forward Range response headers
        if response.headers.get("Content-Range"):
            resp_headers["Content-Range"] = response.headers.get("Content-Range")
        if response.headers.get("Accept-Ranges"):
            resp_headers["Accept-Ranges"] = response.headers.get("Accept-Ranges")

        return Response(response.iter_content(chunk_size=8192), status=response.status_code, headers=resp_headers)
    except Exception as e:
        log_event(rid, "stream_proxy.err", error=str(e), video_uid=video_uid[:20], path=path[:50] if path else "")
        return safe_error(e)


_STATS_BOT_NAMES = {
    "googlebot",
    "applebot",
    "bingbot",
    "yandexbot",
    "baiduspider",
    "duckduckbot",
    "slurp",
    "facebook",
    "facebookexternalhit",
    "facebot",
    "twitterbot",
    "twitter",
    "linkedinbot",
    "pinterest",
    "semrushbot",
    "ahrefsbot",
    "mj12bot",
    "dotbot",
    "petalbot",
    "bytespider",
}


@public_bp.route("/api/stats/event", methods=["POST"])
def stats_event():
    """Record analytics events (visits, sessions, page views). Bot requests are silently discarded.

    The raw User-Agent is never stored. Only coarse categories are persisted
    (e.g. "Chrome", "Windows", "desktop") which are shared by millions of users.
    """
    rid = next_request_id()
    try:
        # Server-side: parse User-Agent for bot detection + coarse category extraction
        ua_string = request.headers.get("User-Agent", "")
        browser_family = None
        os_family = None
        device_type = None
        if ua_string:
            try:
                ua = parse_user_agent(ua_string)
                if ua.is_bot or (ua.browser.family or "").lower() in _STATS_BOT_NAMES:
                    return jsonify({"success": True})
                # Extract coarse categories only (never store the raw UA string)
                browser_family = ua.browser.family or None
                os_family = ua.os.family or None
                if ua.is_mobile:
                    device_type = "mobile"
                elif ua.is_tablet:
                    device_type = "tablet"
                elif ua.is_pc:
                    device_type = "desktop"
                else:
                    device_type = "other"
            except Exception:
                pass

        data = request.get_json(force=True) or {}
        event_type = str(data.get("event_type", "")).strip()
        session_id = str(data.get("session_id", "")).strip()
        user_address = data.get("user_address")
        user_address = str(user_address).strip().lower() if user_address else None
        page_path = data.get("page_path")
        page_path = str(page_path).strip() if page_path else None

        if not event_type or not session_id:
            return jsonify({"error": "missing required fields"}), 400

        if event_type not in ("visit", "session_start", "session_end", "page_view"):
            return jsonify({"error": "invalid event_type"}), 400

        timestamp = int(time.time())

        conn = connect_db(timeout=10.0, busy_timeout_ms=15000)
        try:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO stats_events(event_type, user_address, session_id, created_at, page_path, browser_family, os_family, device_type)
                VALUES(%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (event_type, user_address, session_id, timestamp, page_path, browser_family, os_family, device_type),
            )
            conn.commit()
        finally:
            conn.close()

        return jsonify({"success": True})
    except Exception as e:
        log_event(rid, "stats_event.err", error=str(e))
        return safe_error(e)


def _get_stats_analytics(rid: int):
    """Return analytics stats from stats_events (DAU/MAU, browser/OS/device breakdown).

    Bots are filtered at ingest time so all stored events are from real users.
    Only coarse categories are stored (e.g. "Chrome", "Windows", "desktop").
    """
    now = int(time.time())

    # Check cache first
    if _analytics_stats_cache["data"] is not None and _analytics_stats_cache["expires"] > now:
        log_event(rid, "get_stats.analytics.cached")
        return jsonify(_analytics_stats_cache["data"])

    try:
        conn = connect_db(timeout=15.0, busy_timeout_ms=20000)
        try:
            cur = conn.cursor()
            today_start = now - 86400
            yesterday_start = now - (2 * 86400)
            thirty_days_ago = now - (30 * 86400)

            stats: dict[str, Any] = {}

            # Fetch events from last 30 days (bots already filtered at ingest)
            cur.execute(
                """
                SELECT session_id, user_address, created_at, event_type, browser_family, os_family, device_type
                FROM stats_events
                WHERE created_at >= %s
                """,
                (thirty_days_ago,),
            )
            all_events = cur.fetchall()

            if all_events:
                # Calculate DAU/MAU
                dau_today_set: set[str] = set()
                dau_yesterday_set: set[str] = set()
                mau_set: set[str] = set()
                dau_reg_set: set[str] = set()
                unreg_sessions: set[str] = set()

                # Track coarse categories per session (deduplicated)
                session_browser: dict[str, str] = {}
                session_os: dict[str, str] = {}
                session_device: dict[str, str] = {}

                for sess_id, user_addr, created_at, event_type, browser, os_fam, dev_type in all_events:
                    if event_type not in ("visit", "session_start", "page_view"):
                        continue
                    user_key = user_addr.lower() if user_addr and user_addr.strip() else sess_id

                    mau_set.add(user_key)

                    if created_at >= today_start:
                        dau_today_set.add(user_key)
                        if user_addr and user_addr.strip():
                            dau_reg_set.add(user_addr.lower())

                    if yesterday_start <= created_at < today_start:
                        dau_yesterday_set.add(user_key)

                    if not user_addr or not user_addr.strip():
                        unreg_sessions.add(sess_id)

                    # Store first seen category per session
                    if browser and sess_id not in session_browser:
                        session_browser[sess_id] = browser
                    if os_fam and sess_id not in session_os:
                        session_os[sess_id] = os_fam
                    if dev_type and sess_id not in session_device:
                        session_device[sess_id] = dev_type

                stats["dau_today"] = len(dau_today_set)
                stats["dau_any_today"] = len(dau_today_set)
                stats["dau_yesterday"] = len(dau_yesterday_set)
                stats["maus"] = len(mau_set)
                stats["dau_registered_today"] = len(dau_reg_set)
                stats["unregistered_users"] = len(unreg_sessions)

                # Browser breakdown
                browser_counts: dict[str, int] = {}
                for b in session_browser.values():
                    browser_counts[b] = browser_counts.get(b, 0) + 1
                total_sessions = len(session_browser) or 1
                browser_pcts = [(k, round(v / total_sessions * 100, 1)) for k, v in browser_counts.items()]
                browser_pcts.sort(key=lambda x: x[1], reverse=True)
                top_browsers = [{"name": k, "pct": f"{p}%"} for k, p in browser_pcts[:4]]
                if len(browser_pcts) > 4:
                    other_pct = round(sum(p for _, p in browser_pcts[4:]), 1)
                    if other_pct > 0:
                        top_browsers.append({"name": "Other", "pct": f"{other_pct}%"})
                stats["browser_breakdown"] = top_browsers

                # OS breakdown
                os_counts: dict[str, int] = {}
                for o in session_os.values():
                    os_counts[o] = os_counts.get(o, 0) + 1
                total_os = len(session_os) or 1
                os_pcts = [(k, round(v / total_os * 100, 1)) for k, v in os_counts.items()]
                os_pcts.sort(key=lambda x: x[1], reverse=True)
                top_os = [{"name": k, "pct": f"{p}%"} for k, p in os_pcts[:4]]
                if len(os_pcts) > 4:
                    other_pct = round(sum(p for _, p in os_pcts[4:]), 1)
                    if other_pct > 0:
                        top_os.append({"name": "Other", "pct": f"{other_pct}%"})
                stats["os_breakdown"] = top_os

                # Device type breakdown
                device_counts: dict[str, int] = {"desktop": 0, "mobile": 0, "tablet": 0, "other": 0}
                for d in session_device.values():
                    if d in device_counts:
                        device_counts[d] += 1
                    else:
                        device_counts["other"] += 1
                device_total = sum(device_counts.values()) or 1
                stats["device_breakdown"] = {
                    k: f"{round(v / device_total * 100, 1)}%" for k, v in device_counts.items()
                }
            else:
                stats["dau_today"] = 0
                stats["dau_any_today"] = 0
                stats["dau_yesterday"] = 0
                stats["maus"] = 0
                stats["dau_registered_today"] = 0
                stats["unregistered_users"] = 0
                stats["browser_breakdown"] = []
                stats["os_breakdown"] = []
                stats["device_breakdown"] = {"desktop": "0%", "mobile": "0%", "tablet": "0%", "other": "0%"}

        finally:
            conn.close()

        # Cache the result
        _analytics_stats_cache["data"] = stats
        _analytics_stats_cache["expires"] = now + _ANALYTICS_STATS_CACHE_TTL

        log_event(rid, "get_stats.analytics.ok", dau=stats.get("dau_today", 0), mau=stats.get("maus", 0))
        return jsonify(stats)

    except Exception as e:
        log_event(rid, "get_stats.analytics.err", error=str(e))
        return safe_error(e)


def _get_stats_rewards(rid: int):
    """Return comprehensive reward statistics."""
    from routes.quests import get_distributor

    try:
        ts = int(time.time())

        # Get pool balance
        distributor = get_distributor()
        pool_balance = distributor.get_pool_balance() if distributor.is_configured() else 0

        conn = connect_db(timeout=10.0, busy_timeout_ms=15000)
        try:
            cur = conn.cursor()

            # Get overall stats
            cur.execute(
                """
                SELECT 
                    COUNT(*) as total_rewards,
                    COUNT(CASE WHEN claimed_at IS NOT NULL THEN 1 END) as claimed_count,
                    COUNT(CASE WHEN claimed_at IS NULL THEN 1 END) as pending_count,
                    COALESCE(SUM(CASE WHEN reward_type = 'mirage' THEN 
                        COALESCE(payout_amount, (reward_data->>'amount')::bigint)
                    ELSE 0 END), 0) as total_amount,
                    COALESCE(SUM(CASE WHEN reward_type = 'mirage' AND claimed_at IS NOT NULL THEN 
                        COALESCE(payout_amount, (reward_data->>'amount')::bigint)
                    ELSE 0 END), 0) as claimed_amount,
                    COALESCE(SUM(CASE WHEN reward_type = 'mirage' AND claimed_at IS NULL THEN (reward_data->>'amount')::bigint ELSE 0 END), 0) as pending_amount,
                    MIN(created_at) as first_reward_at,
                    MAX(created_at) as last_reward_at
                FROM pending_rewards
            """
            )
            summary_row = cur.fetchone()

            summary = {
                "total_rewards": summary_row[0] or 0,
                "claimed_count": summary_row[1] or 0,
                "pending_count": summary_row[2] or 0,
                "total_amount": summary_row[3] or 0,
                "claimed_amount": summary_row[4] or 0,
                "pending_amount": summary_row[5] or 0,
                "first_reward_at": summary_row[6],
                "last_reward_at": summary_row[7],
                "pool_balance": pool_balance,
                "quest_payouts_enabled": distributor.is_configured(),
            }

            # Calculate daily rate (last 7 days)
            week_ago = ts - (7 * 86400)
            cur.execute(
                """
                SELECT COALESCE(SUM(CASE WHEN reward_type = 'mirage' THEN 
                    COALESCE(payout_amount, (reward_data->>'amount')::bigint)
                ELSE 0 END), 0)
                FROM pending_rewards
                WHERE created_at >= %s
            """,
                (week_ago,),
            )
            week_total = cur.fetchone()[0] or 0
            summary["daily_rate"] = week_total // 7

            # Get per-user stats
            cur.execute(
                """
                SELECT 
                    pr.owner,
                    p.username,
                    COUNT(*) as reward_count,
                    COUNT(CASE WHEN pr.claimed_at IS NOT NULL THEN 1 END) as claimed_count,
                    COUNT(CASE WHEN pr.claimed_at IS NULL THEN 1 END) as pending_count,
                    COALESCE(SUM(CASE WHEN pr.reward_type = 'mirage' THEN 
                        COALESCE(pr.payout_amount, (pr.reward_data->>'amount')::bigint)
                    ELSE 0 END), 0) as total_earned,
                    COALESCE(SUM(CASE WHEN pr.reward_type = 'mirage' AND pr.claimed_at IS NOT NULL THEN 
                        COALESCE(pr.payout_amount, (pr.reward_data->>'amount')::bigint)
                    ELSE 0 END), 0) as claimed_amount,
                    COALESCE(SUM(CASE WHEN pr.reward_type = 'mirage' AND pr.claimed_at IS NULL THEN (pr.reward_data->>'amount')::bigint ELSE 0 END), 0) as pending_amount,
                    MIN(pr.created_at) as first_reward_at,
                    MAX(pr.created_at) as last_reward_at,
                    p.created_at as account_created_at
                FROM pending_rewards pr
                LEFT JOIN profiles p ON LOWER(pr.owner) = LOWER(p.owner)
                GROUP BY pr.owner, p.username, p.created_at
                ORDER BY total_earned DESC
            """
            )
            user_rows = cur.fetchall()

            users = []
            for row in user_rows:
                owner = row[0]
                first_reward_at = row[8]
                last_reward_at = row[9]
                total_earned = row[5] or 0

                # Calculate earnings per day
                if first_reward_at and last_reward_at and first_reward_at != last_reward_at:
                    days_active = max(1, (last_reward_at - first_reward_at) // 86400)
                    earnings_per_day = total_earned // days_active
                else:
                    earnings_per_day = total_earned

                users.append(
                    {
                        "address": owner,
                        "username": row[1],
                        "reward_count": row[2] or 0,
                        "claimed_count": row[3] or 0,
                        "pending_count": row[4] or 0,
                        "total_earned": total_earned,
                        "claimed_amount": row[6] or 0,
                        "pending_amount": row[7] or 0,
                        "first_reward_at": first_reward_at,
                        "last_reward_at": last_reward_at,
                        "account_created_at": row[10],
                        "earnings_per_day": earnings_per_day,
                    }
                )

        finally:
            conn.close()

        log_event(rid, "get_stats.rewards.ok", user_count=len(users))
        return jsonify({"summary": summary, "users": users})

    except Exception as e:
        log_event(rid, "get_stats.rewards.err", error=str(e))
        return safe_error(e)


def _get_stats_rewards_history(rid: int):
    """Return paginated reward history."""
    try:
        offset = int(request.args.get("offset", 0))
        limit = min(int(request.args.get("limit", 50)), 100)

        conn = connect_db(timeout=10.0, busy_timeout_ms=15000)
        try:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT 
                    pr.owner,
                    p.username,
                    pr.reward_type,
                    pr.reward_data,
                    pr.reason,
                    pr.created_at,
                    pr.claimed_at,
                    pr.payout_amount
                FROM pending_rewards pr
                LEFT JOIN profiles p ON LOWER(pr.owner) = LOWER(p.owner)
                ORDER BY pr.created_at DESC
                LIMIT %s OFFSET %s
            """,
                (limit + 1, offset),
            )
            reward_rows = cur.fetchall()

            has_more = len(reward_rows) > limit
            if has_more:
                reward_rows = reward_rows[:limit]

            rewards = []
            for row in reward_rows:
                reward_data = row[3] if isinstance(row[3], dict) else {}
                base_amount = reward_data.get("amount", 0)
                payout_amount = row[7]
                display_amount = payout_amount if payout_amount is not None else base_amount
                rewards.append(
                    {
                        "address": row[0],
                        "username": row[1],
                        "type": row[2],
                        "amount": display_amount,
                        "reason": row[4],
                        "created_at": row[5],
                        "claimed_at": row[6],
                        "claimed": row[6] is not None,
                    }
                )

        finally:
            conn.close()

        log_event(rid, "get_stats.rewards_history.ok", count=len(rewards), offset=offset)
        return jsonify({"rewards": rewards, "has_more": has_more})

    except Exception as e:
        log_event(rid, "get_stats.rewards_history.err", error=str(e))
        return safe_error(e)


def _get_stats_signups(rid: int):
    """Return recent signups via invite codes with referrer info."""
    try:
        conn = connect_db(timeout=10.0, busy_timeout_ms=15000)
        try:
            cur = conn.cursor()
            # Get recent signups (used_by is not null means invite was used)
            # Join with profiles to get username/moniker for both signup and referrer
            cur.execute(
                """
                SELECT 
                    ic.code,
                    ic.used_by,
                    ic.owner as invited_by,
                    ic.used_at,
                    ic.created_at as code_created_at,
                    p_signup.username as signup_username,
                    p_signup.avatar as signup_avatar,
                    p_signup.level as signup_level,
                    p_signup.subscription_expiry as signup_sub_expiry,
                    p_signup.created_at as signup_created_at,
                    p_ref.username as referrer_username,
                    p_ref.avatar as referrer_avatar,
                    p_ref.level as referrer_level
                FROM invite_codes ic
                LEFT JOIN profiles p_signup ON LOWER(p_signup.owner) = LOWER(ic.used_by)
                LEFT JOIN profiles p_ref ON LOWER(p_ref.owner) = LOWER(ic.owner)
                WHERE ic.used_by IS NOT NULL
                ORDER BY ic.used_at DESC NULLS LAST
                LIMIT 100
                """
            )
            rows = cur.fetchall()
            now = int(time.time())
            signups = []
            for row in rows:
                (
                    code,
                    used_by,
                    invited_by,
                    used_at,
                    code_created_at,
                    signup_username,
                    signup_avatar,
                    signup_level,
                    signup_sub_expiry,
                    signup_created_at,
                    referrer_username,
                    referrer_avatar,
                    referrer_level,
                ) = row
                signups.append(
                    {
                        "code": code,
                        "signup": {
                            "address": used_by,
                            "username": signup_username or None,
                            "avatar": signup_avatar or None,
                            "level": signup_level or 0,
                            "is_subscriber": (signup_sub_expiry or 0) > now,
                            "created_at": signup_created_at or used_at,
                        },
                        "referrer": {
                            "address": invited_by,
                            "username": referrer_username or None,
                            "avatar": referrer_avatar or None,
                            "level": referrer_level or 0,
                        },
                        "used_at": used_at,
                    }
                )

            # Get summary stats
            cur.execute("SELECT COUNT(*) FROM invite_codes WHERE used_by IS NOT NULL")
            total_used = cur.fetchone()[0] or 0
            cur.execute("SELECT COUNT(*) FROM invite_codes WHERE used_by IS NULL")
            total_available = cur.fetchone()[0] or 0
            cur.execute("SELECT COUNT(DISTINCT owner) FROM invite_codes WHERE used_by IS NOT NULL")
            unique_referrers = cur.fetchone()[0] or 0

            # Get top referrers
            cur.execute(
                """
                SELECT 
                    ic.owner,
                    COUNT(*) as invite_count,
                    p.username,
                    p.avatar
                FROM invite_codes ic
                LEFT JOIN profiles p ON LOWER(p.owner) = LOWER(ic.owner)
                WHERE ic.used_by IS NOT NULL
                GROUP BY ic.owner, p.username, p.avatar
                ORDER BY invite_count DESC
                LIMIT 10
                """
            )
            top_referrers = [
                {
                    "address": r[0],
                    "invite_count": r[1],
                    "username": r[2] or None,
                    "avatar": r[3] or None,
                }
                for r in cur.fetchall()
            ]

        finally:
            conn.close()

        log_event(rid, "get_stats.signups.ok", total_signups=len(signups))
        return jsonify(
            {
                "signups": signups,
                "total_used": total_used,
                "total_available": total_available,
                "unique_referrers": unique_referrers,
                "top_referrers": top_referrers,
            }
        )
    except Exception as e:
        log_event(rid, "get_stats.signups.err", error=str(e))
        return safe_error(e)


def _get_stats_subscribers(rid: int):
    """Return subscribers grouped by tier with activity stats."""
    try:
        conn = connect_db(timeout=10.0, busy_timeout_ms=15000)
        try:
            cur = conn.cursor()
            now = int(time.time())

            # Get all active subscribers with activity stats, grouped by tier
            cur.execute(
                """
                SELECT 
                    p.owner,
                    p.username,
                    p.avatar,
                    p.level,
                    p.subscription_expiry,
                    p.created_at,
                    p.is_moderator,
                    (SELECT COUNT(*) FROM posts WHERE LOWER(owner) = LOWER(p.owner) AND COALESCE(target,'') = '' AND deleted = FALSE) as post_count,
                    (SELECT COUNT(*) FROM posts WHERE LOWER(owner) = LOWER(p.owner) AND LENGTH(COALESCE(target,'')) > 0 AND deleted = FALSE) as comment_count,
                    (SELECT COUNT(*) FROM votes WHERE LOWER(owner) = LOWER(p.owner)) as vote_count,
                    (SELECT COUNT(*) FROM followed_users WHERE LOWER(target) = LOWER(p.owner)) as follower_count
                FROM profiles p
                WHERE p.subscription_expiry > %s AND p.level > 0 AND p.level < 100
                ORDER BY p.level DESC, p.created_at DESC
                """,
                (now,),
            )
            rows = cur.fetchall()

            # Group by tier
            by_tier: dict[int, list] = {1: [], 2: [], 3: []}
            for row in rows:
                (
                    owner,
                    username,
                    avatar,
                    level,
                    sub_expiry,
                    created_at,
                    is_moderator,
                    post_count,
                    comment_count,
                    vote_count,
                    follower_count,
                ) = row
                tier = level if level in (1, 2, 3) else 1
                by_tier[tier].append(
                    {
                        "address": owner,
                        "username": username or None,
                        "avatar": avatar or None,
                        "level": level or 0,
                        "is_moderator": is_moderator or False,
                        "created_at": created_at or 0,
                        "post_count": post_count or 0,
                        "comment_count": comment_count or 0,
                        "vote_count": vote_count or 0,
                        "follower_count": follower_count or 0,
                    }
                )

            # Get summary counts
            total_subscribers = len(rows)

        finally:
            conn.close()

        log_event(rid, "get_stats.subscribers.ok", total_subscribers=total_subscribers)
        return jsonify(
            {
                "tier_1": by_tier[1],
                "tier_2": by_tier[2],
                "tier_3": by_tier[3],
                "total_subscribers": total_subscribers,
                "count_tier_1": len(by_tier[1]),
                "count_tier_2": len(by_tier[2]),
                "count_tier_3": len(by_tier[3]),
            }
        )
    except Exception as e:
        log_event(rid, "get_stats.subscribers.err", error=str(e))
        return safe_error(e)


def get_stats_accounts(rid: int):
    """Return top 100 accounts by wallet balance."""
    try:
        conn = connect_db(timeout=10.0, busy_timeout_ms=15000)
        try:
            cur = conn.cursor()

            # Get all accounts with usernames
            cur.execute(
                """
                SELECT p.owner, p.username
                FROM profiles p
                """
            )
            all_profiles = cur.fetchall()

            # Get summary
            cur.execute("SELECT COUNT(*) FROM profiles")
            total_accounts = cur.fetchone()[0] or 0

        finally:
            conn.close()

        # Fetch balances for all profiles in batch
        addresses = [row[0] for row in all_profiles]
        username_map = {row[0].lower(): row[1] for row in all_profiles}

        if addresses:
            balances = _get_balances_batch(addresses)
            # Sort by balance descending, take top 100
            balances.sort(key=lambda x: x[1], reverse=True)
            top_100 = balances[:100]

            accounts = [
                {
                    "address": addr,
                    "username": username_map.get(addr.lower()) or None,
                    "balance": bal,
                }
                for addr, bal in top_100
            ]
        else:
            accounts = []

        log_event(rid, "get_stats.accounts.ok", total_accounts=len(accounts))
        return jsonify(
            {
                "accounts": accounts,
                "total_accounts": total_accounts,
            }
        )
    except Exception as e:
        log_event(rid, "get_stats.accounts.err", error=str(e))
        return safe_error(e)


@public_bp.route("/api/get_welcome_stats")
def get_welcome_stats():
    """Lightweight stats for welcome/landing page. Returns only essential counts.

    This is much faster than get_stats?tab=overview as it only runs 3 queries.
    Cached for 30 seconds.
    """
    rid = next_request_id()
    log_event(rid, "get_welcome_stats.begin")

    now = int(time.time())

    # Check cache first
    if _welcome_stats_cache["data"] is not None and _welcome_stats_cache["expires"] > now:
        log_event(rid, "get_welcome_stats.cached")
        return jsonify(_welcome_stats_cache["data"])

    try:
        conn = connect_db(timeout=3.0, busy_timeout_ms=5000)
        try:
            cur = conn.cursor()
            today_start = now - 86400  # last 24h window

            # Query 1: registered users count
            cur.execute("SELECT COUNT(*) FROM profiles")
            registered_users = cur.fetchone()[0] or 0

            # Query 2: posts + comments in last 24h
            cur.execute(
                """
                SELECT COUNT(*) FROM posts
                WHERE deleted = FALSE
                  AND created_at >= %s
                """,
                (today_start,),
            )
            posts_24h = cur.fetchone()[0] or 0

            # Query 3: DAU from stats_events (actual page visits, same as /stats page)
            # Count unique visitors: registered users by address, guests by session_id
            cur.execute(
                """
                SELECT COUNT(DISTINCT 
                    CASE 
                        WHEN user_address IS NOT NULL AND user_address != '' THEN LOWER(user_address)
                        ELSE session_id
                    END
                )
                FROM stats_events
                WHERE created_at >= %s
                  AND event_type IN ('visit', 'session_start', 'page_view')
                """,
                (today_start,),
            )
            active_24h = cur.fetchone()[0] or 0

            result = {
                "registered_users": registered_users,
                "posts_24h": posts_24h,
                "active_24h": active_24h,
            }

            # Cache the result
            _welcome_stats_cache["data"] = result
            _welcome_stats_cache["expires"] = now + _WELCOME_STATS_CACHE_TTL

            log_event(rid, "get_welcome_stats.ok", **result)
            return jsonify(result)
        finally:
            conn.close()
    except Exception as e:
        log_event(rid, "get_welcome_stats.err", error=str(e))
        return safe_error(e)


@public_bp.route("/api/get_stats")
def get_stats():
    """Return stats for the stats page. Supports tabs: overview (default), signups, accounts, analytics, rewards."""
    rid = next_request_id()
    tab = request.args.get("tab", "overview").lower()
    log_event(rid, "get_stats.begin", tab=tab)

    # Route to tab-specific handlers
    if tab == "signups":
        return _get_stats_signups(rid)
    elif tab == "subscribers":
        return _get_stats_subscribers(rid)
    elif tab == "accounts":
        return get_stats_accounts(rid)
    elif tab == "analytics":
        return _get_stats_analytics(rid)
    elif tab == "rewards":
        return _get_stats_rewards(rid)
    elif tab == "rewards_history":
        return _get_stats_rewards_history(rid)

    # Check cache for overview stats
    now = int(time.time())
    if _overview_stats_cache["data"] is not None and _overview_stats_cache["expires"] > now:
        log_event(rid, "get_stats.overview.cached")
        return jsonify(_overview_stats_cache["data"])

    # Default: overview stats
    try:
        conn = connect_db(timeout=10.0, busy_timeout_ms=15000)
        try:
            cur = conn.cursor()
            now = int(time.time())
            # Sliding windows instead of UTC day boundaries to avoid zeros around day rollover
            today_start = now - 86400  # last 24h window
            yesterday_start = now - (2 * 86400)
            thirty_days_ago = now - (30 * 86400)
            deleted_clause_bare = _deleted_filter_bare()

            stats: dict[str, Any] = {}

            # Core blockchain-wide counts
            cur.execute("SELECT COUNT(*) FROM profiles")
            stats["registered_users"] = cur.fetchone()[0] or 0

            cur.execute(
                """
                SELECT COUNT(*) FROM posts
                WHERE COALESCE(target,'') = ''
                  AND deleted = FALSE
                """
            )
            stats["total_posts"] = cur.fetchone()[0] or 0

            cur.execute(f"SELECT COUNT(*) FROM posts WHERE LENGTH(COALESCE(target,'')) > 0 {deleted_clause_bare}")
            stats["total_comments"] = cur.fetchone()[0] or 0

            cur.execute("SELECT COUNT(*) FROM votes")
            stats["total_votes"] = cur.fetchone()[0] or 0

            # Posts and comments in last 24h (for welcome screen stats)
            cur.execute(
                """
                SELECT COUNT(*) FROM posts
                WHERE COALESCE(target,'') = ''
                  AND deleted = FALSE
                  AND created_at >= %s
                """,
                (today_start,),
            )
            stats["posts_24h"] = cur.fetchone()[0] or 0

            cur.execute(
                """
                SELECT COUNT(*) FROM posts
                WHERE LENGTH(COALESCE(target,'')) > 0
                  AND deleted = FALSE
                  AND created_at >= %s
                """,
                (today_start,),
            )
            stats["comments_24h"] = cur.fetchone()[0] or 0

            # Unique users active on-chain in last 24h (posted, commented, or voted)
            cur.execute(
                """
                SELECT COUNT(DISTINCT owner) FROM (
                    SELECT LOWER(owner) as owner FROM posts WHERE created_at >= %s AND deleted = FALSE
                    UNION
                    SELECT LOWER(owner) as owner FROM votes WHERE created_at >= %s
                ) active_users
                """,
                (today_start, today_start),
            )
            stats["chain_active_24h"] = cur.fetchone()[0] or 0

            # Registered-only engagement tallies
            cur.execute(
                """
                SELECT COUNT(*) FROM posts p
                WHERE COALESCE(p.target,'') = ''
                  AND p.deleted = FALSE
                  AND EXISTS (
                    SELECT 1 FROM profiles pr WHERE LOWER(pr.owner) = LOWER(p.owner)
                  )
                """
            )
            registered_posts = cur.fetchone()[0] or 0

            cur.execute(
                f"""
                SELECT COUNT(*) FROM posts p
                WHERE LENGTH(COALESCE(p.target,'')) > 0 {deleted_clause_bare}
                  AND EXISTS (
                    SELECT 1 FROM profiles pr WHERE LOWER(pr.owner) = LOWER(p.owner)
                  )
                """
            )
            registered_comments = cur.fetchone()[0] or 0

            cur.execute(
                """
                SELECT COUNT(*) FROM votes v
                WHERE EXISTS (
                    SELECT 1 FROM profiles pr WHERE LOWER(pr.owner) = LOWER(v.owner)
                )
                """
            )
            registered_votes = cur.fetchone()[0] or 0

            # Funding and engagement ratios (paid via active subscribers only)
            cur.execute(
                """
                SELECT COUNT(*) FROM posts p
                JOIN profiles pr ON LOWER(p.owner) = LOWER(pr.owner)
                WHERE p.paid
                  AND p.deleted = FALSE
                  AND pr.subscription_expiry > %s
                """,
                (now,),
            )
            paid_messages = cur.fetchone()[0] or 0
            cur.execute(
                """
                SELECT COUNT(*) FROM posts
                WHERE deleted = FALSE
                """
            )
            total_messages = cur.fetchone()[0] or 0
            stats["mirage_funded_ratio"] = paid_messages / max(total_messages, 1)

            cur.execute(
                """
                SELECT COUNT(*) FROM posts p
                JOIN profiles pr ON LOWER(p.owner) = LOWER(pr.owner)
                WHERE COALESCE(p.target,'') = ''
                  AND p.paid
                  AND p.deleted = FALSE
                  AND pr.subscription_expiry > %s
                """,
                (now,),
            )
            paid_posts = cur.fetchone()[0] or 0
            stats["paid_posts"] = int(paid_posts)
            stats["free_posts"] = max(int(stats["total_posts"]) - int(paid_posts), 0)

            # Vote counts (by direction)
            cur.execute("SELECT COUNT(*) FROM votes WHERE user_vote > 0")
            upvotes = cur.fetchone()[0] or 0
            cur.execute("SELECT COUNT(*) FROM votes WHERE user_vote < 0")
            downvotes = cur.fetchone()[0] or 0
            stats["upvotes"] = upvotes
            stats["downvotes"] = downvotes

            # Edit % and Delete % based on all posts (root + comments)
            cur.execute(
                """
                SELECT COUNT(*) FROM posts
                WHERE edited_at IS NOT NULL
                  AND deleted = FALSE
                """
            )
            edited_all = cur.fetchone()[0] or 0
            cur.execute("SELECT COUNT(*) FROM posts WHERE deleted = FALSE")
            all_non_deleted = cur.fetchone()[0] or 0
            stats["edit_frequency"] = edited_all / max(all_non_deleted, 1)

            cur.execute("SELECT COUNT(*) FROM posts WHERE deleted = TRUE")
            deleted_all = cur.fetchone()[0] or 0
            total_all = all_non_deleted + deleted_all
            stats["delete_rate"] = deleted_all / max(total_all, 1)

            # User cohorts - subscribers by tier
            cur.execute(
                """
                SELECT level, COUNT(*) FROM profiles
                WHERE subscription_expiry > %s AND level > 0 AND level < 100
                GROUP BY level
                ORDER BY level
                """,
                (now,),
            )
            subscribers_by_tier = {row[0]: row[1] for row in cur.fetchall()}
            stats["subscribers"] = sum(subscribers_by_tier.values())
            stats["subscribers_tier_1"] = subscribers_by_tier.get(1, 0)
            stats["subscribers_tier_2"] = subscribers_by_tier.get(2, 0)
            stats["subscribers_tier_3"] = subscribers_by_tier.get(3, 0)

            seven_days_ago = now - (7 * 86400)
            cur.execute(
                """
                SELECT COUNT(*) FROM profiles
                WHERE created_at >= %s
                """,
                (seven_days_ago,),
            )
            stats["new_registrations_7d"] = cur.fetchone()[0] or 0

            if stats["registered_users"] > 0:
                stats["average_posts_per_user"] = registered_posts / stats["registered_users"]
                stats["average_votes_per_user"] = registered_votes / stats["registered_users"]
            else:
                stats["average_posts_per_user"] = 0.0
                stats["average_votes_per_user"] = 0.0

            if registered_posts > 0:
                stats["average_comments_per_post"] = registered_comments / registered_posts
            else:
                stats["average_comments_per_post"] = 0.0

            # Most active topics (top 5)
            cur.execute(
                """
                SELECT topic, COUNT(*) as count
                FROM posts
                WHERE topic IS NOT NULL
                  AND LENGTH(topic) > 0
                  AND COALESCE(target,'') = ''
                  AND deleted = FALSE
                GROUP BY topic
                ORDER BY count DESC
                LIMIT 5
                """
            )
            stats["most_active_topics"] = [{"topic": row[0], "count": row[1]} for row in cur.fetchall()]

            # Content tags breakdown
            cur.execute(
                """
                SELECT LOWER(COALESCE(tag, '')) AS tag, COUNT(*) as count
                FROM posts
                WHERE deleted = FALSE
                GROUP BY LOWER(COALESCE(tag, ''))
                """
            )
            tag_counts = {row[0]: row[1] for row in cur.fetchall()}
            stats["tag_counts"] = {
                "safe": tag_counts.get("", 0),
                "sensitive": tag_counts.get("sensitive", 0),
                "gore": tag_counts.get("gore", 0),
                "violence": tag_counts.get("violence", 0),
                "death": tag_counts.get("death", 0),
                "porn": tag_counts.get("porn", 0),
            }

            # Analytics stats (DAU/MAU, device breakdown) are loaded separately via tab=analytics
            # Use on-chain active users as a fast proxy for DAU
            stats["chain_active_24h"] = stats.get("chain_active_24h", 0)
            stats["dau_any_today"] = stats["chain_active_24h"]  # Fast approximation
            stats["dau_today"] = stats["chain_active_24h"]
            stats["total_users"] = stats.get("registered_users", 0)

        finally:
            conn.close()

        # Cache the result
        _overview_stats_cache["data"] = stats
        _overview_stats_cache["expires"] = int(time.time()) + _OVERVIEW_STATS_CACHE_TTL

        log_event(
            rid,
            "get_stats.ok",
            total_users=stats.get("total_users", 0),
            total_posts=stats.get("total_posts", 0),
            dau=stats.get("dau_today", 0),
            subscribers=stats.get("subscribers", 0),
        )
        return jsonify(stats)
    except Exception as e:
        log_event(rid, "get_stats.err", error=str(e))
        return safe_error(e)


# =============================================================================
# REFERRAL ADMIN ENDPOINTS
# =============================================================================


def _is_admin(address: str) -> bool:
    """Check if address is an admin (level >= 100 on chain)."""
    if not address:
        return False
    try:
        profile = _query_chain_profile_full(address)
        if profile:
            level = int(profile.get("level", 0) or 0)
            return level >= 100
    except Exception:
        pass
    return False


def _require_admin():
    """Get admin address from request or return None if not admin."""
    address = request.args.get("admin_address", "").strip().lower()
    if not address:
        address = (request.get_json(force=True, silent=True) or {}).get("admin_address", "").strip().lower()
    if not address or not _is_admin(address):
        return None
    return address


@public_bp.route("/api/referral/stats", methods=["GET"])
def get_referral_stats():
    """Get referral stats for a user (their pending/paid rewards and referral tree)."""
    rid = next_request_id()
    address = request.args.get("address", "").strip().lower()
    if not address:
        return jsonify({"error": "address required"}), 400

    log_event(rid, "referral.stats.begin", address=address)
    try:
        with connect_db() as conn:
            with conn.cursor() as cur:
                # Get pending and paid reward totals
                cur.execute(
                    """
                    SELECT 
                        COALESCE(SUM(CASE WHEN status = 'pending' THEN total_pending ELSE 0 END), 0) as pending_total,
                        COALESCE(SUM(CASE WHEN status IN ('approved', 'paid') THEN total_pending ELSE 0 END), 0) as paid_total
                    FROM referral_pending_rewards
                    WHERE user_address = %s
                """,
                    (address,),
                )
                row = cur.fetchone()
                pending_total = float(row[0]) if row else 0.0
                paid_total = float(row[1]) if row else 0.0

                # Get who referred this user
                cur.execute(
                    """
                    SELECT 
                        rl.referrer_address,
                        COALESCE(p.username, '') as username
                    FROM referral_links rl
                    LEFT JOIN profiles p ON LOWER(p.owner) = rl.referrer_address
                    WHERE rl.user_address = %s
                    """,
                    (address,),
                )
                referrer_row = cur.fetchone()
                referred_by = None
                if referrer_row:
                    referred_by = {
                        "address": referrer_row[0],
                        "username": referrer_row[1] or None,
                    }

                # Load all referral links for tree building
                cur.execute("SELECT user_address, referrer_address FROM referral_links")
                all_links = {r[0]: r[1] for r in cur.fetchall()}

                # Load all usernames
                cur.execute("SELECT LOWER(owner), username FROM profiles WHERE username IS NOT NULL AND username != ''")
                usernames = {r[0]: r[1] for r in cur.fetchall()}

                # Load actual accruals for this user (from referral_user_accruals table)
                cur.execute(
                    """
                    SELECT referee_address, level, pending, paid, COALESCE(denied, 0)
                    FROM referral_user_accruals
                    WHERE beneficiary_address = %s
                """,
                    (address,),
                )
                accruals = {
                    r[0]: {"level": r[1], "pending": float(r[2]), "paid": float(r[3]), "denied": float(r[4])}
                    for r in cur.fetchall()
                }

                # Reward rates by level (same as referral_accrue.py)
                REWARD_RATES = [0.0, 1.0, 0.5, 0.25, 0.125, 0.0625]

                def build_tree(parent_addr: str, level: int, max_depth: int = 5):
                    """Build referral tree recursively with actual accrued earnings."""
                    if level > max_depth:
                        return []

                    # Find direct referees of this parent
                    direct_referees = [addr for addr, ref in all_links.items() if ref == parent_addr]

                    tree = []
                    for ref_addr in direct_referees:
                        rate = REWARD_RATES[level] if level < len(REWARD_RATES) else 0.0

                        # Get actual accrued amounts from database
                        accrual = accruals.get(ref_addr, {"pending": 0.0, "paid": 0.0, "denied": 0.0})

                        # Get children recursively
                        children = build_tree(ref_addr, level + 1, max_depth)

                        def count_descendants(nodes):
                            total = len(nodes)
                            for n in nodes:
                                total += count_descendants(n.get("children", []))
                            return total

                        tree.append(
                            {
                                "address": ref_addr,
                                "username": usernames.get(ref_addr),
                                "level": level,
                                "rate": rate,
                                "pending": accrual["pending"],
                                "paid": accrual["paid"],
                                "denied": accrual["denied"],
                                "children": children,
                                "descendant_count": count_descendants(children),
                            }
                        )

                    return tree

                # Build the referral tree starting from the user
                referral_tree = build_tree(address, 1, 5)

                # Count total referrals and sum pending/paid from tree
                def count_all(nodes):
                    total = len(nodes)
                    for n in nodes:
                        total += count_all(n.get("children", []))
                    return total

                def sum_tree_amounts(nodes):
                    pending = 0.0
                    paid = 0.0
                    for n in nodes:
                        pending += n.get("pending", 0.0)
                        paid += n.get("paid", 0.0)
                        child_pending, child_paid = sum_tree_amounts(n.get("children", []))
                        pending += child_pending
                        paid += child_paid
                    return pending, paid

                total_referrals = count_all(referral_tree)
                tree_pending, tree_paid = sum_tree_amounts(referral_tree)

                # Get next update time from referral daemon state
                cur.execute("SELECT value FROM referral_state WHERE key = %s", ("referral_accrue_last_run",))
                state_row = cur.fetchone()
                last_run_ts = int(state_row[0]) if state_row else None
                # Read period from database (stored by accrue script), fallback to 24h
                cur.execute("SELECT value FROM referral_state WHERE key = %s", ("referral_accrue_period",))
                period_row = cur.fetchone()
                period_seconds = int(period_row[0]) if period_row else 86400
                next_update_ts = (last_run_ts + period_seconds) if last_run_ts else None

        result = {
            "pending_total": tree_pending,
            "paid_total": tree_paid,
            "total_referrals": total_referrals,
            "referral_tree": referral_tree,
            "referred_by": referred_by,
            "last_update_ts": last_run_ts,
            "next_update_ts": next_update_ts,
        }
        log_event(rid, "referral.stats.ok", total_referrals=total_referrals)
        return jsonify(result)
    except Exception as e:
        log_event(rid, "referral.stats.err", error=str(e))
        return safe_error(e)


# =============================================================================
# Invite Code System (mirage.talk / localhost only)
# =============================================================================


def _is_main_site() -> bool:
    """Check if request is from mirage.talk or localhost (where invite codes work)."""
    host = request.host.split(":")[0].lower()
    return host in ("mirage.talk", "localhost", "127.0.0.1")


@public_bp.route("/api/get_invite_codes")
def get_invite_codes():
    """Get all invite codes owned by the given address."""
    rid = next_request_id()
    address = request.args.get("address", "", type=str).strip()
    if not address:
        return jsonify({"error": "address required"}), 400

    try:
        conn = connect_db(timeout=5.0)
        cur = conn.cursor()

        cur.execute(
            """
            SELECT code, used_by, created_at, used_at
            FROM invite_codes
            WHERE LOWER(owner) = LOWER(%s)
            ORDER BY created_at ASC
            """,
            (address,),
        )
        rows = cur.fetchall()
        conn.close()

        codes = []
        for row in rows:
            codes.append(
                {
                    "code": row[0],
                    "used_by": row[1],
                    "created_at": row[2],
                    "used_at": row[3],
                    "is_used": row[1] is not None,
                }
            )

        available_count = sum(1 for c in codes if not c["is_used"])
        log_event(rid, "invite.get_codes.ok", address=address[:12], total=len(codes), available=available_count)
        resp = {"codes": codes, "total": len(codes), "available": available_count}
        return jsonify(_inject_balance(resp, address))
    except Exception as e:
        log_event(rid, "invite.get_codes.err", error=str(e))
        return safe_error(e)


@public_bp.route("/api/validate_invite_code", methods=["POST"])
def validate_invite_code():
    """Validate that an invite code exists and is unused. Only works on mirage.talk/localhost."""
    rid = next_request_id()

    if not _is_main_site():
        log_event(rid, "invite.validate.blocked", host=request.host)
        return jsonify({"error": "Invite codes only work on mirage.talk"}), 403

    data = request.get_json(silent=True) or {}
    code = (data.get("code") or "").strip().upper()

    if not code or len(code) != 9 or code[4] != "-":
        return jsonify({"valid": False, "error": "Invalid code format"}), 400

    try:
        conn = connect_db(timeout=5.0)
        cur = conn.cursor()

        cur.execute(
            "SELECT owner, used_by FROM invite_codes WHERE UPPER(code) = %s",
            (code,),
        )
        row = cur.fetchone()
        conn.close()

        if not row:
            log_event(rid, "invite.validate.notfound", code=code)
            return jsonify({"valid": False, "error": "Invalid invite code"})

        owner, used_by = row
        if used_by:
            log_event(rid, "invite.validate.used", code=code)
            return jsonify({"valid": False, "error": "This invite code has already been used"})

        log_event(rid, "invite.validate.ok", code=code)
        return jsonify({"valid": True, "owner": owner})
    except Exception as e:
        log_event(rid, "invite.validate.err", error=str(e))
        return safe_error(e, context="validate_invite_code")


__all__ = ["public_bp"]
