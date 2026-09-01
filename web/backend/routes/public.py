from __future__ import annotations

"""Public-facing routes.

Endpoints:
- GET /api/get_parameters: Latest block hash, difficulty, optional balance.
- GET /api/get_chain_config: Chain governance params (tiers, limits, subscription_period).
- GET /api/get_node_config: Per-node static settings (validator info, feature flags).
- GET /api/get_tx_status: Unified tx status with type-specific enrichment.
- GET /api/get_address_from_username: Get address for a username if it exists.
- GET /api/communities: List most active communities, excluding deleted messages.
- GET /api/get_posts: List recent posts with aggregates.
- GET /api/get_user_posts: List recent posts for a specific owner.
- GET /api/get_comments: Root post and nested comments tree.
- GET /api/get_recent_content: Combined chronological stream of recent posts and comments
  (raw, no viewer-specific filtering) for external bot scanning.
"""

import copy
import json
import logging
import os
import re
from db import connect_backend_db, connect_db

logger = logging.getLogger(__name__)

from typing import Any, Dict, List, Optional

import requests
from flask import Blueprint, jsonify, request, has_request_context

from error_utils import safe_error, api_error_code, api_error
from fleet_url import post_json as fleet_post_json, validate_fleet_endpoint
from logging_utils import log_event, next_request_id
from node import require_runtime, derive_address_from_pubkey as _derive_address_from_pubkey
from seen_posts import get_seen_map, ingest_seen_batch, normalize_post_id
from community_glob import MAX_COMMUNITY_WILDCARDS, count_wildcards, community_matches_pattern
from user_last_seen import update_user_last_seen
from params import PARAMS_REFRESH_SECONDS, load_params, expect_params
from curation import (
    filter_posts as _filter_posts_for_lens,
    resolve_effective_tags as _resolve_effective_tags,
    resolve_lens as _resolve_curation_lens,
    thread_locked_for_lens,
)
from settings import (
    IGNORE_DELETIONS,
    REGISTRATION_ENABLED,
    REGISTRATION_INVITE_CODE_REQUIRED,
    OPEN_BROWSING_ENABLED,
    MEDIA_UPLOADS_ENABLED,
    NEW_USER_HIGHLIGHT_DAYS,
    PUSH_NOTIFICATIONS_ENABLED,
    ANDROID_BANNER_ENABLED,
    IOS_BANNER_ENABLED,
)
import threading
import time
import calendar
from datetime import datetime as dt
import math
from urllib.parse import urlencode, urlparse
from chain import (
    classify_reject as _classify_reject,
    get_block_time_seconds as _get_block_time_seconds,
    get_current_pow_difficulty as _get_current_pow_difficulty,
    get_difficulty_info as _get_difficulty_info,
    get_latest_block_hash as _latest_block_hash,
    get_pow_base_bits as _get_pow_base_bits,
    get_pow_factor as _get_pow_factor,
    is_node_catching_up as _is_catching_up,
)
from fleet import active_node_entries
from node_identity import build_local_identity


def _now_epoch() -> int:
    return int(time.time())


# stream_proxy input constraints (L-1). Cloudflare Stream UIDs are lowercase hex;
# the range stays wide so legacy assets keep playing.
_STREAM_UID_RE = re.compile(r"[0-9a-f]{10,100}")
_STREAM_PATH_RE = re.compile(r"[A-Za-z0-9._/-]{1,200}")
# Empirical list: extend it if stream_proxy.param_dropped starts firing. Dropping
# an unknown parameter degrades playback visibly in the log rather than forwarding
# arbitrary client input to the upstream CDN.
_STREAM_PROXY_ALLOWED_PARAMS = frozenset({"token", "exp", "sig", "verify", "clientBandwidthHint", "protocol"})

# `limit` was clamped everywhere and `page` only floored, while several feeds
# compute their SQL row cap as the product of the two. That made `page` the
# unbounded half of a bound: one unauthenticated request with a large page
# removed the LIMIT, and psycopg materializes the whole result at execute().
MAX_FEED_PAGE = 200
# Ceiling for every candidate-pool computation. Some sites wrote max(500, …),
# which reads like a cap and is a floor; the magic home feed already used
# min(…, 500) correctly, so this is that value applied uniformly.
MAX_CANDIDATE_POOL = 500
# The inbox is paged deeper than a feed by real users, so it gets its own larger
# ceiling rather than the pool cap — its query is a ten-level self-join, which is
# exactly why it must not be unbounded.
MAX_INBOX_ROWS = 2000


def _clamp_page(page: int) -> int:
    """Floor and cap a client-supplied page number."""
    return min(max(1, int(page)), MAX_FEED_PAGE)


def _escape_like(value: str) -> str:
    """Escape LIKE metacharacters in a user-supplied search term.

    Backslash goes first: it is PostgreSQL's default LIKE escape character, so
    escaping only % and _ leaves a trailing backslash dangling as an incomplete
    escape sequence and raises, which is an unauthenticated 500 from any search box.
    """
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _lens_request_args(
    community: str | None = None, *, allow_team_without_community: bool = False
) -> tuple[str, int | None, str]:
    scope = (request.args.get("scope") or "current").strip().lower()
    if scope not in ("current", "legacy"):
        raise ValueError("invalid scope")
    default_lens = "raw" if scope == "legacy" else "effective"
    lens = (request.args.get("lens") or default_lens).strip().lower()
    if lens not in ("effective", "default", "team", "raw"):
        raise ValueError("invalid lens")
    raw_team_id = request.args.get("team_id")
    team_id = None
    if raw_team_id is not None:
        try:
            team_id = int(raw_team_id)
        except (TypeError, ValueError) as e:
            raise ValueError("invalid team_id") from e
        if team_id <= 0:
            raise ValueError("invalid team_id")
    if lens == "team" and (
        team_id is None or ((not community or community == "all") and not allow_team_without_community)
    ):
        raise ValueError("team lens requires team_id and community")
    if lens != "team" and team_id is not None:
        raise ValueError("team_id is only valid with team lens")
    if scope == "legacy" and (lens != "raw" or team_id is not None):
        raise ValueError("legacy scope requires raw lens")
    return lens, team_id, scope


def _get_balance(address) -> int:
    """Read balance from indexer DB."""
    if not address:
        return 0
    with connect_db(timeout=3.0, busy_timeout_ms=5000) as conn:
        cur = conn.cursor()
        cur.execute("SELECT balance FROM balances WHERE address = LOWER(%s)", (str(address),))
        row = cur.fetchone()
        return int(row[0]) if row and row[0] is not None else 0


def _get_total_supply() -> int:
    """Read total supply from indexer DB chain_stats."""
    with connect_db(timeout=3.0, busy_timeout_ms=5000) as conn:
        cur = conn.cursor()
        cur.execute("SELECT value FROM chain_stats WHERE key = 'total_supply'")
        row = cur.fetchone()
        if row and row[0] is not None:
            return int(row[0]) if isinstance(row[0], (int, float)) else int(row[0])
        return 0


def _get_balances_batch(addresses) -> list:
    """Read balances for multiple addresses from indexer DB."""
    if not addresses:
        return []
    lower = [a.lower() for a in addresses]
    with connect_db(timeout=3.0, busy_timeout_ms=5000) as conn:
        cur = conn.cursor()
        cur.execute("SELECT address, balance FROM balances WHERE address = ANY(%s)", (lower,))
        found = {r[0]: int(r[1]) for r in cur.fetchall()}
        return [(a, found.get(a.lower(), 0)) for a in addresses]


def _get_staked_balance(address) -> int:
    """Read staked balance for validator operator from indexer DB chain_stats."""
    if not address:
        return 0
    with connect_db(timeout=3.0, busy_timeout_ms=5000) as conn:
        cur = conn.cursor()
        cur.execute("SELECT value FROM chain_stats WHERE key = 'validators'")
        row = cur.fetchone()
        if not row or not isinstance(row[0], list):
            return 0
        validators = row[0]
        # address here is expected to be valoper
        for v in validators:
            if v.get("operator_address") == address:
                return int(v.get("tokens") or 0)
        return 0


def _get_validator(valoper) -> dict:
    """Read validator info from indexer DB chain_stats."""
    if not valoper:
        return {}
    with connect_db(timeout=3.0, busy_timeout_ms=5000) as conn:
        cur = conn.cursor()
        cur.execute("SELECT value FROM chain_stats WHERE key = 'validators'")
        row = cur.fetchone()
        if row and row[0]:
            validators = row[0] if isinstance(row[0], list) else []
            for v in validators:
                if v.get("operator_address") == valoper:
                    return {
                        "moniker": v.get("moniker", ""),
                        "tokens": v.get("tokens", "0"),
                        "status": v.get("status", 0),
                    }
    return {}


import base64


def _inject_balance(resp: dict, addr: str) -> dict:
    """Add balance to response dict if address is provided."""
    if addr and addr.lower() != "guest":
        resp["balance"] = int(_get_balance(addr))
    return resp


def _db_get_profile_scalars(addr: str) -> dict | None:
    """Read profile scalar fields from indexer DB. Returns None if profile not found."""
    with connect_db(timeout=3.0, busy_timeout_ms=5000) as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT owner, username, level, created_at, subscription_expiry,
                      auto_renew, biography, avatar, banner, flair, reserve_funds,
                      effective_paid
               FROM profiles WHERE LOWER(owner) = LOWER(%s) LIMIT 1""",
            (addr,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return {
            "owner": row[0] or addr.lower(),
            "username": row[1] or "",
            "level": int(row[2]) if row[2] is not None else 0,
            "created_at": int(row[3]) if row[3] is not None else 0,
            "subscription_expiry": int(row[4]) if row[4] is not None else 0,
            "auto_renew": bool(row[5]) if row[5] is not None else False,
            "biography": row[6] or "",
            "avatar": row[7] or "",
            "banner": row[8] or "",
            "flair": row[9] or "",
            "reserve_funds": int(row[10]) if row[10] is not None else 0,
            "effective_paid": bool(row[11]) if row[11] is not None else False,
        }


public_bp = Blueprint("public", __name__)


def derive_address_from_pubkey(pub_dec: bytes) -> str:
    addr = _derive_address_from_pubkey(pub_dec)
    if addr:
        source = request.path if has_request_context() else ""
        update_user_last_seen(addr, source=source)
    return addr


def _is_new_user(profile_created_at: int) -> bool:
    """Check if a profile qualifies for the new-user highlight."""
    if NEW_USER_HIGHLIGHT_DAYS <= 0 or not profile_created_at:
        return False
    return (int(time.time()) - int(profile_created_at)) <= NEW_USER_HIGHLIGHT_DAYS * 86400


def _deleted_filter() -> str:
    """Return SQL clause to filter deleted posts, or empty string if IGNORE_DELETIONS is enabled."""
    return "" if IGNORE_DELETIONS else "AND p.deleted = FALSE"


def _deleted_filter_bare() -> str:
    """Return SQL clause to filter deleted posts without table prefix."""
    return "" if IGNORE_DELETIONS else "AND deleted = FALSE"


def _normalize_api_tag(tag: str) -> str:
    """Normalize a single tag value using alias map."""
    t = (tag or "").strip().lower()
    return _TAG_ALIASES.get(t, t)


def _parse_allowed_tags(raw: str) -> set[str]:
    """Parse and normalize the allowed_tags query param."""
    return set(_normalize_api_tag(t) for t in (raw or "").split(",") if t.strip())


def _is_guest(address: str) -> bool:
    """True when the request carries no signed-in viewer."""
    viewer = (address or "").strip().lower()
    return not viewer or viewer == "guest"


def _viewer_allowed_tags(address: str) -> set[str]:
    """Allowed tags for this request, clamped to nothing when signed out.

    A signed-in viewer keeps the 'sensitive' default and whatever they chose in
    settings. A signed-out visitor gets no tagged content at all, regardless of
    what the client asked for: every shipped bundle and both apps send
    allowed_tags=sensitive, and the edge caches assets for 30 days, so trusting
    the parameter would leave tagged posts on the anonymous frontpage long after
    this ships.
    """
    tags = _parse_allowed_tags(request.args.get("allowed_tags", default="sensitive", type=str))
    if _is_guest(address):
        if tags:
            logger.debug("allowed_tags clamped for anonymous viewer requested=%s", sorted(tags))
        return set()
    return tags


def _is_tag_allowed(tag: str, allowed_tags: set[str]) -> bool:
    """Return True if tag is empty (safe) or in allowed_tags."""
    t = _normalize_api_tag(tag)
    return not t or t in allowed_tags


def _filter_posts_by_allowed_tags(
    posts: list[dict],
    allowed_tags: set[str],
    rid: str,
    context: str,
    viewer: str = "",
) -> list[dict]:
    """Filter posts by allowed_tags after agent edits are applied."""
    if not posts:
        return posts
    viewer_lower = (viewer or "").strip().lower()
    now = _now_epoch()
    filtered = []
    own_kept = 0
    for post in posts:
        author_lower = (post.get("author") or post.get("user_id") or "").strip().lower()
        post_ts = int(post.get("timestamp") or 0)
        if viewer_lower and author_lower == viewer_lower and post_ts >= now - 3600:
            own_kept += 1
            filtered.append(post)
            continue
        if _is_tag_allowed(post.get("tag", ""), allowed_tags):
            filtered.append(post)
    removed = len(posts) - len(filtered)
    if removed:
        logger.debug(
            "allowed_tags filtered %d posts after agent edits ctx=%s rid=%s allowed=%s",
            removed,
            context,
            rid,
            sorted(allowed_tags),
        )
    if own_kept:
        logger.debug(
            "allowed_tags viewer bypass kept=%d ctx=%s rid=%s",
            own_kept,
            context,
            rid,
        )
    return filtered


def _filter_user_posts_by_allowed_tags(
    posts: list[dict],
    allowed_tags: set[str],
    root_tag_map: dict[str, str],
    rid: str,
    context: str,
    viewer: str = "",
) -> list[dict]:
    """Filter profile posts by allowed_tags (comments use root post effective tag)."""
    if not posts:
        return posts
    viewer_lower = (viewer or "").strip().lower()
    now = _now_epoch()
    filtered = []
    removed = 0
    own_kept = 0
    for post in posts:
        author_lower = (post.get("user_id") or post.get("author") or "").strip().lower()
        post_ts = int(post.get("timestamp") or 0)
        if viewer_lower and author_lower == viewer_lower and post_ts >= now - 3600:
            own_kept += 1
            filtered.append(post)
            continue
        target = (post.get("target") or "").strip()
        if target:
            root_id = (post.get("_root_post_id") or "").strip().lower()
            if not root_id or root_id not in root_tag_map:
                removed += 1
                continue
            root_tag = root_tag_map.get(root_id, "")
            if not _is_tag_allowed(root_tag, allowed_tags):
                removed += 1
                continue
        else:
            if not _is_tag_allowed(post.get("tag", ""), allowed_tags):
                removed += 1
                continue
        filtered.append(post)
    if removed:
        logger.debug(
            "allowed_tags filtered %d profile posts after agent edits ctx=%s rid=%s allowed=%s",
            removed,
            context,
            rid,
            sorted(allowed_tags),
        )
    if own_kept:
        logger.debug(
            "allowed_tags viewer bypass kept=%d ctx=%s rid=%s",
            own_kept,
            context,
            rid,
        )
    for post in filtered:
        post.pop("_root_post_id", None)
    return filtered


def _sanitize_wh(w, h) -> dict:
    """Return {"w": w, "h": h} if both are valid ints in [1, 10000], else {}."""
    try:
        w, h = int(w), int(h)
    except (TypeError, ValueError):
        return {}
    if 1 <= w <= 10000 and 1 <= h <= 10000:
        return {"w": w, "h": h}
    return {}


# Rumble embed ids, optionally publisher-qualified. This value is interpolated
# into an iframe src by the clients, so it is matched whole rather than escaped.
_EMBED_ID_RE = re.compile(r"^(?:[a-z0-9]+\.)?v[a-z0-9]+$", re.IGNORECASE)


def _sanitize_embed_id(value) -> str | None:
    """Return the embed id if it is one, else None."""
    if not isinstance(value, str) or len(value) > 64:
        return None
    return value if _EMBED_ID_RE.match(value) else None


def _sanitize_media_meta_list(raw_list: list) -> list[dict]:
    """Sanitize a list of media meta dicts, ensuring valid w/h and embed on each."""
    result = []
    for item in raw_list or []:
        entry = {}
        if isinstance(item, dict):
            if item.get("w") and item.get("h"):
                entry = _sanitize_wh(item["w"], item["h"])
            embed = _sanitize_embed_id(item.get("embed"))
            if embed:
                entry["embed"] = embed
        result.append(entry)
    return result


def _extract_media_meta(media_urls: list) -> list[dict]:
    """Extract w/h from media URL query params. Used only for agent-edited media."""
    from urllib.parse import urlparse, parse_qs

    meta = []
    for url in media_urls or []:
        entry = {}
        try:
            parsed = urlparse(str(url))
            qs = parse_qs(parsed.query)
            w = int(qs["w"][0]) if "w" in qs else 0
            h = int(qs["h"][0]) if "h" in qs else 0
            entry = _sanitize_wh(w, h)
        except Exception:
            pass
        meta.append(entry)
    return meta


def _enrich_media_meta(cur, posts: list[dict]) -> None:
    """Batch-read media_meta from DB and set it on each post dict."""
    if not posts:
        return
    post_ids = [p["post_id"] for p in posts if p.get("post_id")]
    if not post_ids:
        return
    ph = ",".join(["%s"] * len(post_ids))
    cur.execute(
        f"SELECT LOWER(txhash), COALESCE(media_meta, '[]') FROM posts WHERE LOWER(txhash) IN ({ph})",
        post_ids,
    )
    meta_map: dict[str, list[dict]] = {}
    for pid, meta_raw in cur.fetchall():
        try:
            parsed = json.loads(meta_raw or "[]")
            if isinstance(parsed, list):
                meta_map[pid] = _sanitize_media_meta_list(parsed)
        except Exception:
            pass
    for post in posts:
        pid = post.get("post_id", "")
        if pid in meta_map:
            post["media_meta"] = meta_map[pid]


def _collect_image_impression_ids(posts: list[dict]) -> set[str]:
    """Return unique image asset ids from post media URLs, across all providers.

    Provider-agnostic: consults the media provider registry so view tracking
    works for local/cloudflare/bunny and any future provider (and dual-read of
    legacy Cloudflare URLs).
    """
    from media import image_asset_id_from_url

    ids: set[str] = set()
    for post in posts or []:
        for raw_url in post.get("media") or []:
            if not raw_url:
                continue
            asset_id = image_asset_id_from_url(str(raw_url))
            if asset_id:
                ids.add(asset_id)
    return ids


def _track_image_impressions(posts: list[dict], rid: int, context: str) -> None:
    """Upsert view counts for images attached to returned posts."""
    image_ids = _collect_image_impression_ids(posts)
    if not image_ids:
        return
    now_ts = int(time.time())
    with connect_backend_db() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO image_views (image_id, view_count, last_viewed_at)
                VALUES (%s, 1, %s)
                ON CONFLICT (image_id) DO UPDATE SET
                    view_count = image_views.view_count + 1,
                    last_viewed_at = EXCLUDED.last_viewed_at
                """,
                [(image_id, now_ts) for image_id in sorted(image_ids)],
            )
    log_event(rid, "image_impressions.ok", count=len(image_ids), context=context)


# Allowed content tags used for community safety classification
_COMMUNITY_TAGS = ("sensitive", "gore", "violence", "death", "adult")

# TODO: remove "porn" alias once all clients send "adult"
_TAG_ALIASES = {"porn": "adult"}


def _compute_dominant_flags(cur, communities_lower: list[str]) -> dict[str, dict]:
    """Return dominant tag info for a list of lowercase communities, computed live from posts."""
    if not communities_lower:
        return {}
    try:
        cur.execute(
            """
            SELECT
                LOWER(TRIM(p.community)) AS community,
                COUNT(1) AS total_posts,
                SUM(CASE WHEN LOWER(COALESCE(p.tag, '')) = 'sensitive' THEN 1 ELSE 0 END) AS sensitive_count,
                SUM(CASE WHEN LOWER(COALESCE(p.tag, '')) = 'gore' THEN 1 ELSE 0 END) AS gore_count,
                SUM(CASE WHEN LOWER(COALESCE(p.tag, '')) = 'violence' THEN 1 ELSE 0 END) AS violence_count,
                SUM(CASE WHEN LOWER(COALESCE(p.tag, '')) = 'death' THEN 1 ELSE 0 END) AS death_count,
                SUM(CASE WHEN LOWER(COALESCE(p.tag, '')) IN ('adult', 'porn') THEN 1 ELSE 0 END) AS adult_count
            FROM posts p
            WHERE COALESCE(p.target, '') = ''
              AND p.community IS NOT NULL
              AND LOWER(TRIM(p.community)) = ANY(%s)
              AND p.deleted = FALSE
            GROUP BY LOWER(TRIM(p.community))
            """,
            (communities_lower,),
        )
        result = {}
        for row in cur.fetchall():
            community = row[0]
            total = float(row[1] or 0)
            counts = {
                "sensitive": float(row[2] or 0),
                "gore": float(row[3] or 0),
                "violence": float(row[4] or 0),
                "death": float(row[5] or 0),
                "adult": float(row[6] or 0),
            }
            dominant_tag = ""
            dominant_ratio = 0.0
            if total > 0:
                for k, v in counts.items():
                    ratio = v / total
                    if ratio >= 0.5 and ratio > dominant_ratio:
                        dominant_tag = k
                        dominant_ratio = ratio
            result[community] = {"dominant_tag": dominant_tag or None, "dominant_ratio": dominant_ratio}
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


def _get_blocked_posts(cur, address: str) -> set[str]:
    """Get all post txhashes blocked by the viewer."""
    if not address:
        return set()

    cur.execute("SELECT target FROM blocked_posts WHERE owner = %s", (address.lower(),))
    return {row[0].lower() for row in cur.fetchall()}


def _get_blocked_users(cur, address: str) -> set[str]:
    """Get all user addresses blocked by the viewer."""
    if not address:
        return set()

    cur.execute("SELECT target FROM blocked_users WHERE owner = %s", (address.lower(),))
    blocked_users = {row[0].lower() for row in cur.fetchall()}
    blocked_users.discard(address.lower())
    return blocked_users


def _get_blocked_communities(cur, address: str) -> set[str]:
    """Get all communities blocked by the viewer and their enabled agents."""
    if not address:
        return set()

    blocked_communities = set()

    # Get viewer's own blocked communities
    cur.execute("SELECT target FROM blocked_communities WHERE owner = %s", (address.lower(),))
    blocked_communities.update(row[0].lower() for row in cur.fetchall())

    return blocked_communities


def _split_blocked_communities(blocked_communities: set[str] | None) -> tuple[set[str], tuple[str, ...]]:
    """Split blocked communities into exact matches and glob patterns (containing *)."""
    if not blocked_communities:
        return set(), tuple()
    exact: set[str] = set()
    patterns: list[str] = []
    for raw in blocked_communities:
        t = str(raw or "").strip().lower()
        if not t:
            raise ValueError("blocked community cannot be empty")
        if "*" in t:
            alpha = t.replace("*", "")
            if not alpha:
                raise ValueError("blocked community pattern must contain letters")
            patterns.append(t)
        else:
            exact.add(t)
    if patterns:
        import logging

        logging.getLogger(__name__).debug("blocked_communities wildcards active: %d", len(patterns))
    return exact, tuple(patterns)


def _community_is_blocked(community: str, blocked_exact: set[str], blocked_patterns: tuple[str, ...]) -> bool:
    if not community:
        return False
    if blocked_exact and community in blocked_exact:
        return True
    for pat in blocked_patterns:
        if community_matches_pattern(community, pat):
            return True
    return False


def _blocked_communities_sql(
    blocked_exact: set[str],
    blocked_patterns: tuple[str, ...],
    community_col: str = "p.community",
    viewer: str = "",
    owner_col: str = "p.owner",
) -> tuple[str, list[str]]:
    """Return (sql_fragment, params) to exclude blocked communities in a WHERE clause.

    Returns an empty string and empty list when there are no blocked communities,
    so callers can unconditionally splice it into queries:

        f"... WHERE ... {bt_clause} ..."
        params + bt_params
    """
    clauses: list[str] = []
    params: list[str] = []
    if blocked_exact:
        bt_list = list(blocked_exact)
        ph = ",".join(["%s"] * len(bt_list))
        clauses.append(f"LOWER(TRIM({community_col})) NOT IN ({ph})")
        params.extend(bt_list)
    if blocked_patterns:
        for pat in blocked_patterns:
            # PostgreSQL's LIKE backtracks the same way the old regex matcher did,
            # so a pattern with many wildcards is as expensive here as it was
            # there. Patterns over the cap are left out of the pre-filter rather
            # than bounded: every caller routes its rows through _row_to_post,
            # whose _community_is_blocked call is linear and authoritative, so the
            # only cost of omitting one is that a few more rows are fetched.
            if count_wildcards(pat) > MAX_COMMUNITY_WILDCARDS:
                logger.debug("blocked_communities_sql skipping over-cap pattern wildcards=%d", count_wildcards(pat))
                continue
            # Escape SQL LIKE metacharacters then convert glob * to %
            like_pat = pat.replace("%", "\\%").replace("_", "\\_").replace("*", "%")
            clauses.append(f"LOWER(TRIM({community_col})) NOT LIKE %s")
            params.append(like_pat)
    if not clauses:
        return "", []

    community_cond = " AND ".join(clauses)
    viewer_lower = (viewer or "").strip().lower()
    if viewer_lower and viewer_lower != "guest":
        logger.debug(
            "blocked_communities_sql viewer bypass viewer=%s exact=%d patterns=%d",
            viewer_lower[:12],
            len(blocked_exact),
            len(blocked_patterns),
        )
        return f"AND (LOWER({owner_col}) = %s OR ({community_cond}))", [viewer_lower] + params
    return f"AND {community_cond}", params


# ---- Inbox count cache (60s TTL per address; stores count + last_viewed_at) ----
_inbox_cache: dict[str, tuple[int, float, int]] = {}
_INBOX_CACHE_TTL = 60.0
_INBOX_CACHE_MAX = 10000


def _get_new_inbox_count(cur, address: str) -> int:
    """Count replies + @mentions + awards to user's posts after last inbox view.
    Results are cached in-memory for 60s per address."""
    if not address or address.lower() == "guest":
        return 0

    viewer = address.lower()
    now = time.time()

    cached = _inbox_cache.get(viewer)
    if cached and cached[1] > now:
        return cached[0]

    try:
        from shared.inbox import compute_unread_count, fetch_inbox_last_viewed_at

        last_seen = fetch_inbox_last_viewed_at(viewer)
        count, last_seen = compute_unread_count(cur, viewer, last_seen)
    except Exception:
        count = 0
        last_seen = 0

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
        return jsonify({"error": "address required"}), 400

    try:
        conn = connect_db(timeout=10.0, busy_timeout_ms=15000)
        cur = conn.cursor()

        # Get only the user's own blocked users (not agents')
        cur.execute("SELECT target FROM blocked_users WHERE owner = %s", (address.lower(),))
        blocked_users = [row[0] for row in cur.fetchall()]

        conn.close()
        return jsonify({"blocked_users": blocked_users})
    except Exception as e:
        return safe_error(e)


def _get_profile_lists_from_indexer(addr: str) -> dict:
    """Fetch a user's own profile lists from the indexer DB (full history, not chain-limited)."""
    addr_lower = addr.lower()
    lists = {
        "followed_users": [],
        "joined_communities": [],
        "blocked_users": [],
        "blocked_posts": [],
        "blocked_communities": [],
        "following_count": 0,
        "follower_count": 0,
    }
    try:
        conn = connect_db(timeout=5.0, busy_timeout_ms=10000)
        cur = conn.cursor()
        cur.execute(
            "SELECT target FROM followed_users WHERE LOWER(owner) = %s ORDER BY position",
            (addr_lower,),
        )
        lists["followed_users"] = [r[0] for r in cur.fetchall()]
        cur.execute(
            "SELECT community FROM community_curation_preferences WHERE LOWER(owner) = %s ORDER BY community",
            (addr_lower,),
        )
        lists["joined_communities"] = [r[0] for r in cur.fetchall()]
        cur.execute(
            "SELECT target FROM blocked_users WHERE LOWER(owner) = %s ORDER BY position",
            (addr_lower,),
        )
        lists["blocked_users"] = [r[0] for r in cur.fetchall()]
        cur.execute(
            "SELECT target FROM blocked_posts WHERE LOWER(owner) = %s ORDER BY position",
            (addr_lower,),
        )
        lists["blocked_posts"] = [r[0] for r in cur.fetchall()]
        cur.execute(
            "SELECT target FROM blocked_communities WHERE LOWER(owner) = %s ORDER BY position",
            (addr_lower,),
        )
        lists["blocked_communities"] = [r[0] for r in cur.fetchall()]
        # Follow graph sizes (indexed on LOWER(owner) / LOWER(target)).
        cur.execute(
            "SELECT COUNT(*) FROM followed_users WHERE LOWER(owner) = %s",
            (addr_lower,),
        )
        lists["following_count"] = int(cur.fetchone()[0] or 0)
        cur.execute(
            "SELECT COUNT(*) FROM followed_users WHERE LOWER(target) = %s",
            (addr_lower,),
        )
        lists["follower_count"] = int(cur.fetchone()[0] or 0)
        conn.close()
        logger.debug(
            "get_profile.follow_counts addr=%s following=%s followers=%s",
            addr_lower[:12],
            lists["following_count"],
            lists["follower_count"],
        )
    except Exception as e:
        logger.warning("Failed to load profile lists from indexer for %s: %s", addr, e)
    return lists


@public_bp.route("/api/get_profile")
def get_profile():
    """Get profile: all fields from indexer DB."""
    address = request.args.get("address", default="", type=str)
    if not address:
        return jsonify({"error": "address required"}), 400

    try:
        if _is_catching_up():
            return api_error_code("node_catching_up", 503)

        profile = _db_get_profile_scalars(address)
        lists = _get_profile_lists_from_indexer(address)

        if not profile:
            resp = {
                "owner": address.lower(),
                "username": "",
                "level": 0,
                **lists,
            }
            return jsonify(_inject_balance(resp, address))

        resp = {
            **profile,
            **lists,
        }
        return jsonify(_inject_balance(resp, address))
    except Exception as e:
        return safe_error(e)


# ============================================================================
# HOME FEED V2: Similarity-based algorithm
# ============================================================================


def _load_user_preferences(cur, viewer: str) -> tuple[dict, dict]:
    """Load community and author preferences for a user."""
    viewer_lower = viewer.strip().lower()
    community_prefs: dict[str, float] = {}
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
        # 'community' is the pref_type value written into rows already on disk; the
        # concept is a community everywhere above the storage layer.
        if pref_type == "community":
            community_prefs[t] = w
        elif pref_type == "author":
            author_prefs[t] = w

    return community_prefs, author_prefs


def _load_candidate_posts(
    cur,
    max_candidates: int,
    blocked_posts: set[str],
    blocked_users: set[str],
    allowed_tags: set[str],
    blocked_communities: set[str] | None = None,
    blocked_community_prefixes: tuple[str, ...] | None = None,
    viewer: str = "",
) -> list[dict]:
    """Load recent candidate posts for home feed."""
    deleted_clause = _deleted_filter()
    bt_clause, bt_params = _blocked_communities_sql(
        blocked_communities or set(), blocked_community_prefixes or tuple(), viewer=viewer
    )

    cur.execute(
        f"""
        SELECT p.txhash, p.owner, p.created_at, p.community, p.title, p.content,
               COALESCE(p.tag, '') AS tag,
               COALESCE(p.root_community, p.community, '') AS root_community,
               COALESCE(p.root_post_id, p.txhash, '') AS root_post_id,
               COALESCE(pr.username, '') AS username,
               COALESCE(p.edited_at, 0) AS edited_at,
               COALESCE(p.thumbnail_url, '') AS thumbnail,
               COALESCE(pr.level, 0) AS author_level,
               COALESCE(p.media, '[]') AS media,
               COALESCE(pr.created_at, 0) AS author_created_at,
               COALESCE(p.relayer, '') AS relayer
        FROM posts p
        LEFT JOIN profiles pr ON pr.owner = p.owner
        WHERE COALESCE(p.target,'') = ''
          AND LENGTH(COALESCE(p.title,'')) > 0
          {bt_clause}
          {deleted_clause}
        ORDER BY p.created_at DESC
        LIMIT %s
        """,
        bt_params + [max_candidates],
    )
    rows = cur.fetchall()

    # Filter blocked posts/users and blocked communities
    viewer_lower = (viewer or "").strip().lower()
    candidates = []
    for row in rows:
        (
            txhash,
            owner,
            ts,
            community,
            title,
            content,
            tag,
            root_community,
            root_post_id,
            username,
            edited_at,
            thumbnail,
            author_level,
            media_raw,
            author_created_at,
            relayer,
        ) = row
        media = json.loads(media_raw)
        if not isinstance(media, list):
            raise ValueError("invalid media payload in posts table")

        pid = (txhash or "").lower()
        author = (owner or "").lower()
        tag = _normalize_api_tag(tag or "")
        relayer_lower = (relayer or "").strip().lower()
        community_raw = (community or "").strip()
        community_lower = community_raw.lower()
        root_community_raw = (root_community or community or "").strip()
        root_community_lower = root_community_raw.lower()

        is_own = viewer_lower and author == viewer_lower
        post_ts = int(ts) if ts else 0
        if is_own and post_ts < _now_epoch() - 3600:
            is_own = False
        if not is_own and (pid in blocked_posts or author in blocked_users):
            continue
        if not is_own and _community_is_blocked(
            community_lower, blocked_communities or set(), blocked_community_prefixes or tuple()
        ):
            continue
        if not community_lower:
            continue

        candidates.append(
            {
                "post_id": pid,
                "author": author,
                "user_id": author,
                "username": username or "",
                "author_level": int(author_level) if author_level else 0,
                "author_is_new": _is_new_user(int(author_created_at or 0)),
                "timestamp": post_ts,
                "community": community_raw,
                "community": community_raw,
                "community_lower": community_lower,
                "root_community": root_community_raw,
                "root_community_lower": root_community_lower,
                "root_post_id": (root_post_id or pid).lower(),
                "title": title or "",
                "content": content or "",
                "tag": tag,
                "relayer": relayer_lower,
                "edited": bool(edited_at),
                "edited_at": int(edited_at or 0),
                "thumbnail": thumbnail or "",
                "media": media,
                "media_meta": [],
            }
        )

    return candidates


def _load_vote_totals_cached(
    cur, post_ids: list[str], backend_cur=None, force_live: set[str] | None = None
) -> dict[str, float]:
    """
    Return {post_id: total_weight} via a 60s backend-DB cache. Only valid when
    the viewer has no blocked users (the totals here are unfiltered). Callers
    with blocked_users must use the live LATERAL query directly.

    force_live names post_ids that must not be served from the cache — in
    practice the ones the requesting viewer has voted on, where a stale total
    would read as their own vote having failed. They take the live-sum path and
    then refresh the cache, so the fresh value also benefits later readers.
    """
    post_ids = list({str(pid).lower() for pid in post_ids if pid})
    if not post_ids:
        return {}

    force_live = {str(pid).lower() for pid in (force_live or set())}
    now_ts = int(time.time())
    result: dict[str, float] = {}

    def _read_and_fill_cache(bcur):
        cacheable = [pid for pid in post_ids if pid not in force_live]
        bcur.execute(
            """
            SELECT post_id, total_weight
            FROM post_vote_totals_cache
            WHERE post_id = ANY(%s) AND expires_at > %s
            """,
            (cacheable, now_ts),
        )
        for pid, total in bcur.fetchall():
            result[pid] = float(total or 0.0)

        missing = [pid for pid in post_ids if pid not in result]
        if missing:
            pid_values = ",".join(["(%s)"] * len(missing))
            cur.execute(
                f"""SELECT t.pid, COALESCE(x.total, 0)
                    FROM (VALUES {pid_values}) AS t(pid)
                    LEFT JOIN LATERAL (
                        SELECT SUM(v.user_weight) AS total
                        FROM votes v
                        WHERE LOWER(v.target) = t.pid
                    ) x ON true""",
                missing,
            )
            fresh: dict[str, float] = {}
            for tgt, total in cur.fetchall():
                if tgt:
                    fresh[tgt] = float(total or 0.0)

            if fresh:
                expires_at = now_ts + _VOTE_TOTALS_CACHE_TTL
                values_sql = ",".join(["(%s, %s, %s, %s)"] * len(fresh))
                params: list = []
                for pid, total in fresh.items():
                    params.extend((pid, total, now_ts, expires_at))
                bcur.execute(
                    f"""
                    INSERT INTO post_vote_totals_cache (post_id, total_weight, computed_at, expires_at)
                    VALUES {values_sql}
                    ON CONFLICT (post_id) DO UPDATE SET
                        total_weight = EXCLUDED.total_weight,
                        computed_at = EXCLUDED.computed_at,
                        expires_at = EXCLUDED.expires_at
                    """,
                    params,
                )
            result.update(fresh)

    if backend_cur is not None:
        _read_and_fill_cache(backend_cur)
    else:
        with connect_backend_db() as bconn:
            with bconn.cursor() as bcur:
                _read_and_fill_cache(bcur)

    return result


def _viewer_downvoted(user_votes: dict[str, int], post_id: str) -> bool:
    """True when the viewer has an active downvote on this post."""
    return int(user_votes.get((post_id or "").lower(), 0) or 0) < 0


def _load_viewer_downvote_ids(cur, viewer: str, post_ids: list[str]) -> dict[str, int]:
    """Return {post_id: user_vote} for the viewer's active downvotes in post_ids."""
    viewer_lower = (viewer or "").strip().lower()
    if not viewer_lower or viewer_lower == "guest" or not post_ids:
        return {}
    id_ph = ",".join(["%s"] * len(post_ids))
    cur.execute(
        f"""SELECT LOWER(target), user_vote FROM votes
            WHERE LOWER(owner) = %s AND LOWER(target) IN ({id_ph})
              AND user_vote < 0""",
        [viewer_lower] + post_ids,
    )
    out: dict[str, int] = {}
    for tgt, vote in cur.fetchall():
        if tgt:
            out[tgt] = int(vote)
    return out


def _drop_viewer_downvotes(
    posts: list[dict],
    user_votes: dict[str, int],
    *,
    context: str = "",
) -> list[dict]:
    """Remove posts the viewer downvoted (newest + magic feed contract)."""
    if not posts or not user_votes:
        return posts
    kept: list[dict] = []
    dropped = 0
    for post in posts:
        pid = post.get("post_id") or ""
        if _viewer_downvoted(user_votes, pid):
            dropped += 1
            continue
        kept.append(post)
    if dropped:
        logger.debug(
            "feed.hide_downvoted context=%s dropped=%d kept=%d",
            context or "?",
            dropped,
            len(kept),
        )
    return kept


def _load_vote_and_comment_stats(
    cur,
    post_ids: list[str],
    blocked_posts: set[str],
    blocked_users: set[str],
    viewer: str = "",
    backend_cur=None,
) -> tuple[dict, dict, dict, dict, dict]:
    """Batch load points, comment counts, viewer's votes, and viewer's user_weight contributions.

    Returns (vote_totals, comment_counts, user_votes, user_weight_map, timings)
    where timings has stats_vt_ms / stats_cc_ms / stats_uv_ms sub-phase numbers.
    """
    import time as _time

    if not post_ids:
        return {}, {}, {}, {}, {"stats_vt_ms": 0.0, "stats_cc_ms": 0.0, "stats_uv_ms": 0.0}

    vote_totals: dict[str, float] = {}
    comment_counts: dict[str, int] = {}
    user_votes: dict[str, int] = {}
    user_weight_map: dict[str, float] = {}
    id_ph = ",".join(["%s"] * len(post_ids))

    def _ms_since(t0: float) -> float:
        return round((_time.monotonic() - t0) * 1000, 2)

    # Viewer's votes (user_vote: 1=up, -1=down, 0=none) and user_weight contribution.
    # Already fast (~2ms) via uniq_votes_owner_target index — kept as its own query.
    # Loaded before the points sum, because which posts the viewer has voted on is
    # what decides which totals are allowed to come from the 60s cache below.
    _t = _time.monotonic()
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
    stats_uv_ms = _ms_since(_t)

    # Points (sum of user_weight, excluding blocked users).
    # Use a LATERAL join driven from the 200-row post_id set: the `IN (...)`
    # form was getting hash-joined with a seq-scan of the full votes table
    # (~135k rows, 250ms). LATERAL forces an index-driven lookup per id via
    # idx_votes_target_lower — measured ~5x faster (250ms -> 50ms) on prod.
    _t = _time.monotonic()
    if blocked_users:
        pid_values = ",".join(["(%s)"] * len(post_ids))
        blocked_ph = ",".join(["%s"] * len(blocked_users))
        cur.execute(
            f"""SELECT t.pid, COALESCE(x.total, 0)
                FROM (VALUES {pid_values}) AS t(pid)
                LEFT JOIN LATERAL (
                    SELECT SUM(v.user_weight) AS total
                    FROM votes v
                    WHERE LOWER(v.target) = t.pid
                      AND LOWER(v.owner) NOT IN ({blocked_ph})
                ) x ON true""",
            post_ids + list(blocked_users),
        )
        for tgt, total in cur.fetchall():
            if tgt:
                vote_totals[tgt] = float(total or 0.0)
    else:
        # Posts this viewer has voted on skip the cache. A cached total can be up
        # to _VOTE_TOTALS_CACHE_TTL out of date, and the viewer's own vote is the
        # only one they can perceive as missing: user_vote is always read live, so
        # a total computed before their vote was indexed renders as a vote that
        # visibly did not count, while the post page — which sums live — shows it.
        # Other users' votes stay cached; nobody can tell those are seconds late.
        vote_totals = _load_vote_totals_cached(cur, post_ids, backend_cur=backend_cur, force_live=set(user_votes))
    stats_vt_ms = _ms_since(_t)

    # Comment counts
    _t = _time.monotonic()
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
    stats_cc_ms = _ms_since(_t)

    return (
        vote_totals,
        comment_counts,
        user_votes,
        user_weight_map,
        {"stats_vt_ms": stats_vt_ms, "stats_cc_ms": stats_cc_ms, "stats_uv_ms": stats_uv_ms},
    )


def _load_following_candidates(
    cur,
    viewer_lower: str,
    blocked_posts: set[str],
    blocked_users: set[str],
    allowed_tags: set[str],
    max_candidates: int,
    blocked_communities: set[str] = None,
    blocked_community_prefixes: tuple[str, ...] | None = None,
) -> tuple[list[dict], set[str], set[str]]:
    """
    Load candidate posts for the following feed.
    Returns (candidates, joined_communities, followed_users).
    """
    cur.execute("SELECT target FROM followed_users WHERE LOWER(owner) = %s", (viewer_lower,))
    followed_users = {(r[0] or "").strip().lower() for r in cur.fetchall() if r and r[0]}

    conditions = []
    params: list = []
    if followed_users:
        ph = ",".join(["%s"] * len(followed_users))
        conditions.append(f"LOWER(p.owner) IN ({ph})")
        params.extend(list(followed_users))

    conditions.append("LOWER(p.owner) = %s")
    params.append(viewer_lower)

    where_clause = " OR ".join(conditions)
    deleted_clause = _deleted_filter()
    bt_clause, bt_params = _blocked_communities_sql(
        blocked_communities or set(), blocked_community_prefixes or tuple(), viewer=viewer_lower
    )

    cur.execute(
        f"""
        SELECT p.txhash, p.owner, p.created_at, p.community, p.title, p.content,
               COALESCE(p.tag, '') AS tag,
               COALESCE(p.root_community, p.community, '') AS root_community,
               COALESCE(p.root_post_id, p.txhash, '') AS root_post_id,
               COALESCE(pr.username, '') AS username,
               COALESCE(p.edited_at, 0) AS edited_at,
               COALESCE(p.thumbnail_url, '') AS thumbnail,
               COALESCE(pr.level, 0) AS author_level,
               COALESCE(p.media, '[]') AS media,
               COALESCE(pr.created_at, 0) AS author_created_at,
               COALESCE(p.relayer, '') AS relayer
        FROM posts p
        LEFT JOIN profiles pr ON pr.owner = p.owner
        WHERE COALESCE(p.target,'') = ''
          AND LENGTH(COALESCE(p.title,'')) > 0
          AND ({where_clause})
          {bt_clause}
          {deleted_clause}
        ORDER BY p.created_at DESC
        LIMIT %s
        """,
        params + bt_params + [max_candidates],
    )

    seen: set[str] = set()
    candidates: list[dict] = []
    for row in cur.fetchall():
        post = _row_to_post(
            row,
            blocked_posts,
            blocked_users,
            seen,
            blocked_communities,
            blocked_community_prefixes,
            viewer=viewer_lower,
        )
        if post:
            post["_source"] = "following"
            candidates.append(post)

    return candidates, set(), followed_users


def _get_following_feed(
    cur,
    viewer: str,
    limit: int,
    page: int,
    blocked_posts: set[str],
    blocked_users: set[str],
    allowed_tags: set[str],
    sort_mode: str = "magic",
    blocked_communities: set[str] = None,
    blocked_community_prefixes: tuple[str, ...] | None = None,
    seen_posts: dict[str, int] | None = None,
) -> dict:
    """
    Following feed:
    - Candidates: root posts from followed users + posts in followed communities + your own posts
    - Sorting:
      - magic: same Magic scorer as home feed (unified), but without prefs (P=0)
      - newest: fast chronological path
    """
    viewer_lower = viewer.strip().lower() if viewer else ""

    if not viewer_lower or viewer_lower == "guest":
        return _get_guest_feed(
            cur,
            limit,
            page,
            blocked_posts,
            blocked_users,
            allowed_tags,
            blocked_communities=blocked_communities,
            blocked_community_prefixes=blocked_community_prefixes,
        )

    sort_mode = (sort_mode or "magic").strip().lower()
    if sort_mode not in ("magic", "newest"):
        raise ValueError(f"unsupported sort mode: {sort_mode}")

    factor = _seen_overfetch_factor(seen_posts, 4)
    max_candidates = min(limit * page * factor, MAX_CANDIDATE_POOL)
    candidates, joined_communities, followed_users = _load_following_candidates(
        cur,
        viewer_lower,
        blocked_posts,
        blocked_users,
        allowed_tags,
        max_candidates,
        blocked_communities=blocked_communities,
        blocked_community_prefixes=blocked_community_prefixes,
    )

    if not candidates:
        return {"posts": [], "total": 0, "page": page, "limit": limit, "has_more": False}

    # ── Newest: pure chronological ──────────
    if sort_mode == "newest":
        for c in candidates:
            c["_N"] = 1.0
            c["_seen_count"] = 0

        cand_ids = [c["post_id"] for c in candidates]
        candidates = _drop_viewer_downvotes(
            candidates,
            _load_viewer_downvote_ids(cur, viewer_lower, cand_ids),
            context="following.newest",
        )

        start = (page - 1) * limit
        end = start + limit
        page_posts = candidates[start:end] if start < len(candidates) else []
        has_more = len(candidates) > end

        page_ids = [p["post_id"] for p in page_posts]
        vote_totals, comment_counts, user_votes, user_weight_map, _ = _load_vote_and_comment_stats(
            cur, page_ids, blocked_posts, blocked_users, viewer_lower
        )
        _, award_details = _load_award_aggregates(cur, page_ids, blocked_users)

        for post in page_posts:
            pid = post["post_id"]
            sc = post.pop("_seen_count", 0)
            n_val = post.pop("_N", 1.0)
            author_lower = (post.get("author") or "").strip().lower()
            is_own = author_lower == viewer_lower
            by_followed_user = author_lower in followed_users if author_lower else False

            if is_own:
                reason = "Your post"
            elif by_followed_user:
                reason = "From a followed user"
            else:
                reason = "From a followed community"
            if sc > 0:
                reason += " · You've seen this before"

            post["points"] = vote_totals.get(pid, 0.0)
            post["comments"] = comment_counts.get(pid, 0)
            post["awards"] = award_details.get(pid, [])
            post["children"] = []
            post["feed_type"] = "following"
            post["feed_bucket"] = "newest"
            post["feed_debug"] = {
                "reason": reason,
                "bucket": "newest",
                "N": round(n_val, 4),
                "seen_count": sc,
            }
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
    vote_totals, comment_counts, user_votes, user_weight_map, _ = _load_vote_and_comment_stats(
        cur, post_ids, blocked_posts, blocked_users, viewer_lower
    )

    from similarity import get_or_compute_similarities

    similar_users = get_or_compute_similarities(cur, viewer_lower)
    sim_lookup = {u[0]: u[1] for u in similar_users}
    similar_addrs = set(sim_lookup.keys())
    similar_upvotes, _ = _load_similar_user_upvotes(cur, post_ids, similar_addrs)
    unique_commenters = _load_unique_commenter_counts(cur, post_ids, blocked_posts, blocked_users)
    unique_awarders, award_details = _load_award_aggregates(cur, post_ids, blocked_users)
    now_ts = int(time.time())
    community_prefs: dict[str, float] = {}
    author_prefs: dict[str, float] = {}

    seen_penalized = 0
    for post in candidates:
        pid = post["post_id"]
        pts = float(vote_totals.get(pid, 0.0) or 0.0)
        comments = int(comment_counts.get(pid, 0) or 0)

        author_lower = (post.get("author") or post.get("user_id") or "").strip().lower()
        post_community = (post.get("community") or "").strip().lower()
        is_own_post = author_lower == viewer_lower
        by_followed_user = author_lower in followed_users if author_lower else False
        in_joined_community = post_community in joined_communities if post_community else False

        if not (is_own_post or by_followed_user or in_joined_community):
            raise RuntimeError(f"following_feed.unexpected_candidate: pid={pid[:12]} author={author_lower[:12]}")

        score, debug, should_hide = _score_magic(
            post,
            sim_lookup,
            similar_upvotes,
            unique_commenters,
            vote_totals,
            community_prefs,
            author_prefs,
            now_ts,
            False,
            unique_awarders,
            viewer=viewer_lower,
            seen_posts=seen_posts,
            user_votes=user_votes,
        )
        if should_hide:
            continue

        if debug.get("seen_count", 0) > 0:
            seen_penalized += 1

        if is_own_post:
            reason = "Your post"
        elif by_followed_user:
            reason = "From a followed user"
        else:
            reason = "From a followed community"

        post["_score"] = score
        post["points"] = pts
        post["comments"] = comments
        post["unique_commenters"] = unique_commenters.get(pid, 0)
        post["awards"] = award_details.get(pid, [])
        post["children"] = []
        post["feed_type"] = "following"
        post["feed_bucket"] = debug.get("bucket", "following")
        post["user_vote"] = user_votes.get(pid, 0)
        post["user_weight"] = user_weight_map.get(pid, 0.0)
        debug["follow_reason"] = reason
        post["feed_debug"] = debug

    if seen_penalized:
        logger.debug(
            "seen_penalty feed=following.magic viewer=%s penalized=%d/%d",
            viewer_lower[:12],
            seen_penalized,
            len(candidates),
        )

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
    sort_mode: str = "magic",
    blocked_communities: set[str] = None,
    blocked_community_prefixes: tuple[str, ...] | None = None,
    seen_posts: dict[str, int] | None = None,
) -> dict:
    """
    Home feed.

    Sort modes:
    - magic: Magic (unified score + reasons + novelty penalty)
    - newest: chronological (no novelty factor)
    """
    viewer_lower = viewer.strip().lower() if viewer else ""
    sort_mode = (sort_mode or "magic").strip().lower()
    if sort_mode not in ("magic", "newest"):
        raise ValueError(f"unsupported sort mode: {sort_mode}")

    # Newest: chronological, no novelty factor
    if sort_mode == "newest":
        return _get_home_feed_newest(
            cur,
            viewer_lower,
            limit,
            page,
            blocked_posts,
            blocked_users,
            allowed_tags,
            blocked_communities=blocked_communities,
            blocked_community_prefixes=blocked_community_prefixes,
            seen_posts=seen_posts,
        )

    # Guest users: magic-style scoring without personalization
    if not viewer_lower or viewer_lower == "guest":
        return _get_guest_feed_magic(
            cur,
            limit,
            page,
            blocked_posts,
            blocked_users,
            allowed_tags,
            blocked_communities=blocked_communities,
            blocked_community_prefixes=blocked_community_prefixes,
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
        blocked_communities=blocked_communities,
        blocked_community_prefixes=blocked_community_prefixes,
        seen_posts=seen_posts,
    )


def _get_home_feed_newest(
    cur,
    viewer: str,
    limit: int,
    page: int,
    blocked_posts: set[str],
    blocked_users: set[str],
    allowed_tags: set[str],
    blocked_communities: set[str] = None,
    blocked_community_prefixes: tuple[str, ...] | None = None,
    seen_posts: dict[str, int] | None = None,
) -> dict:
    """
    Chronological feed with seen-novelty reordering.

    Posts are fetched newest-first, then reordered by timestamp × N so
    previously-seen content drifts down while still appearing.
    """
    _POST_COLS = """p.txhash, p.owner, p.created_at, p.community, p.title, p.content, p.tag,
                   p.root_community, p.root_post_id, pr.username, p.edited_at, p.thumbnail_url,
                   COALESCE(pr.level, 0) AS author_level,
                   COALESCE(p.media, '[]') AS media,
                   COALESCE(pr.created_at, 0) AS author_created_at,
                   COALESCE(p.relayer, '') AS relayer"""
    _ROOT_FILTER = "(p.root_post_id IS NULL OR p.root_post_id = '' OR LOWER(p.root_post_id) = LOWER(p.txhash))"
    _COMMUNITY_FILTER = "p.community IS NOT NULL AND TRIM(p.community) != ''"

    bt_clause, bt_params = _blocked_communities_sql(
        blocked_communities or set(), blocked_community_prefixes or tuple(), viewer=viewer
    )

    # Fetch in batches using cursor-based pagination (created_at < ?).
    # `need` bounds both the loop below and the list it accumulates, so capping
    # batch_size alone would still let a deep page build 20k post dicts in memory.
    need = min(page * limit + 1, MAX_CANDIDATE_POOL)
    factor = _seen_overfetch_factor(seen_posts, 3)
    seen: set[str] = set()
    posts: list[dict] = []
    batch_size = min(max(500, need * factor), MAX_CANDIDATE_POOL)
    last_ts = None
    viewer_lower = (viewer or "").strip().lower()
    downvote_votes: dict[str, int] = {}

    while len(posts) < need:
        ts_clause = "AND p.created_at < %s" if last_ts is not None else ""
        ts_params = [last_ts] if last_ts is not None else []
        cur.execute(
            f"""SELECT {_POST_COLS}
            FROM posts p
            LEFT JOIN profiles pr ON LOWER(pr.owner) = LOWER(p.owner)
            WHERE {_ROOT_FILTER} AND {_COMMUNITY_FILTER} AND p.deleted = false
            {bt_clause} {ts_clause}
            ORDER BY p.created_at DESC
            LIMIT %s""",
            bt_params + ts_params + [batch_size],
        )
        rows = cur.fetchall()
        if not rows:
            break
        batch: list[dict] = []
        for row in rows:
            post = _row_to_post(
                row,
                blocked_posts,
                blocked_users,
                seen,
                blocked_communities,
                blocked_community_prefixes,
                viewer=viewer,
            )
            if post:
                batch.append(post)
        if batch:
            downvote_votes.update(_load_viewer_downvote_ids(cur, viewer_lower, [p["post_id"] for p in batch]))
            posts.extend(_drop_viewer_downvotes(batch, downvote_votes, context="home.newest"))
        last_ts = rows[-1][2]
        if len(rows) < batch_size:
            break

    if not posts:
        return {"posts": [], "total": 0, "page": page, "limit": limit, "has_more": False}

    for p in posts:
        p["_N"] = 1.0
        p["_seen_count"] = 0

    start = (page - 1) * limit
    end = start + limit
    page_posts = posts[start:end] if start < len(posts) else []
    has_more = len(posts) > end

    # Load vote/comment/award stats only for the posts we're returning
    page_ids = [p["post_id"] for p in page_posts]
    vote_totals, comment_counts, user_votes, user_weight_map, _ = _load_vote_and_comment_stats(
        cur, page_ids, blocked_posts, blocked_users, viewer_lower
    )
    _, award_details = _load_award_aggregates(cur, page_ids, blocked_users)

    for post in page_posts:
        pid = post["post_id"]
        sc = post.pop("_seen_count", 0)
        n_val = post.pop("_N", 1.0)
        reason = "Newest"
        if sc > 0:
            reason += " · You've seen this before"
        post["points"] = vote_totals.get(pid, 0.0)
        post["comments"] = comment_counts.get(pid, 0)
        post["awards"] = award_details.get(pid, [])
        post["children"] = []
        post["feed_type"] = "home"
        post["feed_bucket"] = "newest"
        post["feed_debug"] = {
            "reason": reason,
            "bucket": "newest",
            "N": round(n_val, 4),
            "seen_count": sc,
        }
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
    blocked_communities: set[str] = None,
    blocked_community_prefixes: tuple[str, ...] | None = None,
    seen_posts: dict[str, int] | None = None,
) -> dict:
    """
    Magic feed algorithm.

    Single unified score: (S + V + U + P + A) × R × N

    Where:
    - S = similarity boost from similar users who upvoted
    - V = vote score (sqrt scaling)
    - U = unique commenter score (sqrt scaling)
    - P = preference boost from community/author prefs (sqrt scaling)
    - A = award score
    - R = recency decay (exponential)
    - N = novelty factor from seen view_count
    """
    import time
    from similarity import get_or_compute_similarities

    viewer_lower = viewer.strip().lower() if viewer else ""
    now_ts = int(time.time())

    # Phase timings. Logged by the caller (`get_posts` route) to help
    # pinpoint which step of the home-feed pipeline dominates latency.
    timings: dict[str, float] = {}

    def _ms_since(t0: float) -> float:
        return round((time.monotonic() - t0) * 1000, 2)

    # 1. Load user preferences
    _t = time.monotonic()
    community_prefs, author_prefs = _load_user_preferences(cur, viewer_lower)
    timings["prefs_ms"] = _ms_since(_t)

    with connect_backend_db() as backend_conn:
        with backend_conn.cursor() as backend_cur:
            # 2. Get similar users (cached or computed on-demand)
            _t = time.monotonic()
            similar_users = get_or_compute_similarities(cur, viewer_lower, backend_cur=backend_cur)
            timings["sim_ms"] = _ms_since(_t)
            sim_lookup = {u[0]: u[1] for u in similar_users}
            similar_addrs = set(sim_lookup.keys())

            # 3. Load candidate posts.
            # Cap the per-source pool size on all pages so feed latency stays bounded
            # even when seen-post overfetch would otherwise multiply the query cost.
            per_source = min(limit * page * _seen_overfetch_factor(seen_posts, 4), 500)
            _t = time.monotonic()
            candidates, cand_timings = _load_home_candidates(
                cur,
                viewer_lower,
                similar_addrs,
                blocked_posts,
                blocked_users,
                allowed_tags,
                per_source,
                now_ts,
                blocked_communities=blocked_communities,
                blocked_community_prefixes=blocked_community_prefixes,
            )
            timings["cand_ms"] = _ms_since(_t)
            timings["cand_count"] = len(candidates)
            timings.update(cand_timings)

            if not candidates:
                return {
                    "posts": [],
                    "total": 0,
                    "page": page,
                    "limit": limit,
                    "has_more": False,
                    "_timings": timings,
                }

            # 4. Load which posts similar users have upvoted
            post_ids = [c["post_id"] for c in candidates]
            _t = time.monotonic()
            similar_upvotes, sim_up_timings = _load_similar_user_upvotes(
                cur, post_ids, similar_addrs, backend_cur=backend_cur
            )
            timings["sim_up_ms"] = _ms_since(_t)
            timings.update(sim_up_timings)

            # 5. Load stats
            _t = time.monotonic()
            vote_totals, comment_counts, user_votes, user_weight_map, stats_timings = _load_vote_and_comment_stats(
                cur,
                post_ids,
                blocked_posts,
                blocked_users,
                viewer_lower,
                backend_cur=backend_cur,
            )
            timings["stats_ms"] = _ms_since(_t)
            timings.update(stats_timings)

    _t = time.monotonic()
    unique_commenters = _load_unique_commenter_counts(cur, post_ids, blocked_posts, blocked_users)
    timings["uc_ms"] = _ms_since(_t)

    _t = time.monotonic()
    unique_awarders, award_details = _load_award_aggregates(cur, post_ids, blocked_users)
    timings["aw_ms"] = _ms_since(_t)

    # 6. Score each post with Magic algorithm
    _t_score = time.monotonic()
    scored_posts = []

    seen_penalized = 0
    for post in candidates:
        score, debug, should_hide = _score_magic(
            post,
            sim_lookup,
            similar_upvotes,
            unique_commenters,
            vote_totals,
            community_prefs,
            author_prefs,
            now_ts,
            True,
            unique_awarders,
            viewer=viewer_lower,
            seen_posts=seen_posts,
            user_votes=user_votes,
        )

        if should_hide:
            continue

        if debug.get("seen_count", 0) > 0:
            seen_penalized += 1

        pid = post["post_id"]
        post["_score"] = score
        post["feed_debug"] = debug
        post["points"] = vote_totals.get(pid, 0.0)
        post["comments"] = comment_counts.get(pid, 0)
        post["unique_commenters"] = unique_commenters.get(pid, 0)
        post["awards"] = award_details.get(pid, [])
        post["children"] = []
        post["feed_type"] = "home"
        post["feed_bucket"] = debug["bucket"]
        post["user_vote"] = user_votes.get(post["post_id"], 0)
        post["user_weight"] = user_weight_map.get(post["post_id"], 0.0)
        scored_posts.append(post)

    if seen_penalized:
        logger.debug(
            "seen_penalty feed=home.magic viewer=%s penalized=%d/%d",
            viewer_lower[:12],
            seen_penalized,
            len(scored_posts),
        )

    # 7. Sort by score descending
    scored_posts.sort(key=lambda p: -p["_score"])
    timings["score_ms"] = _ms_since(_t_score)
    timings["scored_count"] = len(scored_posts)

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
        "_timings": timings,
    }


_SEEN_K = 0.9


def _novelty_factor(view_count: int) -> float:
    """N = 1 / (1 + K * view_count).  Unseen → 1.0, seen once → 0.526, etc."""
    return 1.0 / (1.0 + _SEEN_K * max(0, view_count))


def _seen_overfetch_factor(
    seen_posts: dict[str, int] | None,
    base_factor: int,
    max_factor: int = 6,
) -> int:
    if not seen_posts:
        return base_factor
    seen_ratio = min(len(seen_posts) / max(1, 1000), 0.8)
    factor = max(base_factor, int(base_factor / (1 - seen_ratio)))
    return min(max_factor, factor)


def _score_magic(
    post: dict,
    sim_lookup: dict[str, float],
    similar_upvotes: dict[str, list[str]],
    unique_commenters: dict[str, int],
    vote_totals: dict[str, float],
    community_prefs: dict[str, float],
    author_prefs: dict[str, float],
    now_ts: int,
    use_prefs: bool = True,
    unique_awarders: dict[str, int] | None = None,
    viewer: str = "",
    seen_posts: dict[str, int] | None = None,
    user_votes: dict[str, int] | None = None,
) -> tuple[float, dict, bool]:
    """
    Magic scoring: (S + V + U + P + A) × R × N

    Components (uniform weighting):
    - S = sqrt(similarity_sum)
    - V = sqrt(net_votes)
    - U = sqrt(unique_commenters)
    - P = sqrt(max(0, community_pref + author_pref))
    - A = sqrt(unique_award_givers)
    - R = 1 / (1 + (age_hours/9)^1.585) — decay: 4.5h=0.75, 9h=0.5, 18h=0.25, 36h=0.11
    - N = 1 / (1 + 3 * view_count) — novelty: unseen=1.0, seen once=0.25

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
    if user_votes and _viewer_downvoted(user_votes, pid):
        logger.debug("feed.hide_downvoted context=magic pid=%s", (pid or "")[:12])
        return 0.0, {}, True
    author = post["author"]
    community_lower = (post.get("community") or "").strip().lower()
    timestamp = post.get("timestamp", 0)

    if use_prefs:
        # Check user preference - hide severely disliked content
        community_pref = _clamp_pref_raw(float(community_prefs.get(community_lower, 0) or 0.0))
        author_pref = _clamp_pref_raw(float(author_prefs.get(author, 0) or 0.0))
        combined_pref = community_pref + author_pref

        if combined_pref <= HIDE_THRESHOLD:
            return 0.0, {}, True
    else:
        # Non-home feeds: preferences are not part of the score (P=0) and we do not hide.
        community_pref = 0.0
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

    # P = Preference boost (signed sqrt: disliked communities/authors hurt the score)
    P = _sqrt_signed(combined_pref)

    # A = Award score (unique awarders, always >= 0)
    award_count = (unique_awarders or {}).get(pid, 0)
    A = math.sqrt(max(0.0, float(award_count)))

    # R = Recency: inverse polynomial decay (gentler than exponential)
    # 4.5h=0.75, 9h=0.50, 18h=0.25, 36h=0.11
    age_hours = max(0, (now_ts - timestamp) / 3600)
    R = 1 / (1 + (age_hours / 9) ** 1.585)

    # N = Novelty factor from seen view_count
    seen_count = (seen_posts or {}).get(pid, 0)
    N = _novelty_factor(seen_count)

    # Final score
    score = (S + V + U + P + A) * R * N

    # Determine primary reason based on dominant component
    components = [("S", S), ("V", V), ("U", U), ("P", P), ("A", A)]
    dominant = max(components, key=lambda x: x[1])

    if dominant[0] == "S" and S > 0.3:
        reason = "Similar users liked this"
        bucket = "similar"
    elif dominant[0] == "P" and P > 0.3:
        if community_pref > author_pref:
            reason = f"You like #{community_lower}" if community_lower else "You like this community"
        elif author_pref > community_pref:
            reason = "You like this author"
        else:
            reason = "You like this community & author"
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

    if seen_count > 0:
        reason += " · You've seen this before"

    debug = {
        "bucket": bucket,
        "reason": reason,
        "score": round(float(score), 4),
        "equation": "(√S + √V + √U + √P + √A) × R × N",
        "S": round(raw_sim, 3),
        "V": round(net_vote, 3),
        "U": unique_count,
        "P": round(combined_pref, 3),
        "A": award_count,
        "R": round(R, 4),
        "N": round(N, 4),
        "seen_count": seen_count,
        "age_hours": round(age_hours, 1),
        "t_pref": round(community_pref, 1),
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


def _load_award_aggregates(
    cur,
    post_ids: list[str],
    blocked_users: set[str] | None = None,
) -> tuple[dict[str, int], dict[str, list[dict]]]:
    """
    Load per-post award data:
    - unique_awarders: {post_id: count_of_distinct_award_givers}
    - award_details: {post_id: [{"type": "quality_post", "count": 3}, ...]}
    """
    if not post_ids:
        return {}, {}

    unique_awarders: dict[str, int] = {}
    award_details: dict[str, list[dict]] = {}
    id_ph = ",".join(["%s"] * len(post_ids))

    blocked_users = blocked_users or set()
    if blocked_users:
        blocked_ph = ",".join(["%s"] * len(blocked_users))
        cur.execute(
            f"""SELECT LOWER(target), COUNT(DISTINCT LOWER(owner)) FROM awards
                WHERE LOWER(target) IN ({id_ph})
                  AND LOWER(owner) NOT IN ({blocked_ph})
                GROUP BY LOWER(target)""",
            post_ids + list(blocked_users),
        )
    else:
        cur.execute(
            f"SELECT LOWER(target), COUNT(DISTINCT LOWER(owner)) FROM awards WHERE LOWER(target) IN ({id_ph}) GROUP BY LOWER(target)",
            post_ids,
        )
    for tgt, cnt in cur.fetchall():
        if tgt:
            unique_awarders[tgt] = int(cnt or 0)

    if blocked_users:
        blocked_ph = ",".join(["%s"] * len(blocked_users))
        cur.execute(
            f"""SELECT LOWER(target), award_type, COUNT(*) AS cnt
                FROM awards WHERE LOWER(target) IN ({id_ph})
                  AND LOWER(owner) NOT IN ({blocked_ph})
                GROUP BY LOWER(target), award_type""",
            post_ids + list(blocked_users),
        )
    else:
        cur.execute(
            f"""SELECT LOWER(target), award_type, COUNT(*) AS cnt
                FROM awards WHERE LOWER(target) IN ({id_ph})
                GROUP BY LOWER(target), award_type""",
            post_ids,
        )
    for tgt, atype, cnt in cur.fetchall():
        if tgt:
            award_details.setdefault(tgt, []).append({"type": atype, "count": int(cnt or 0)})

    return unique_awarders, award_details


def _load_home_candidates(
    cur,
    viewer: str,
    similar_addrs: set[str],
    blocked_posts: set[str],
    blocked_users: set[str],
    allowed_tags: set[str],
    max_posts: int,
    now_ts: int,
    blocked_communities: set[str] = None,
    blocked_community_prefixes: tuple[str, ...] | None = None,
) -> tuple[list[dict], dict]:
    """
    Load candidate posts for home feed from multiple sources:
    0. Own posts (recent)
    1. Posts by similar users (recent)
    2. Posts upvoted by similar users (recent)
    3. Recent posts (discovery)

    Returns (candidates, timings) where timings maps src{0..3}_ms / src{0..3}_n
    for per-source diagnostics.
    """
    import time as _time

    results = []
    seen = set()
    timings: dict[str, float] = {}

    def _ms_since(t0: float) -> float:
        return round((_time.monotonic() - t0) * 1000, 2)

    _POST_COLS = """p.txhash, p.owner, p.created_at, p.community, p.title, p.content, p.tag,
                   p.root_community, p.root_post_id, pr.username, p.edited_at, p.thumbnail_url,
                   COALESCE(pr.level, 0) AS author_level,
                   COALESCE(p.media, '[]') AS media,
                   COALESCE(pr.created_at, 0) AS author_created_at,
                   COALESCE(p.relayer, '') AS relayer"""
    _ROOT_FILTER = "(p.root_post_id IS NULL OR p.root_post_id = '' OR LOWER(p.root_post_id) = LOWER(p.txhash))"
    _COMMUNITY_FILTER = "p.community IS NOT NULL AND TRIM(p.community) != ''"
    bt_clause, bt_params = _blocked_communities_sql(
        blocked_communities or set(), blocked_community_prefixes or tuple(), viewer=viewer
    )

    min_ts = int(now_ts) - 86400

    # Source 0: Own posts (always included so the viewer always sees their content)
    _t = _time.monotonic()
    cur.execute(
        f"""SELECT {_POST_COLS}
        FROM posts p
        LEFT JOIN profiles pr ON LOWER(pr.owner) = LOWER(p.owner)
        WHERE LOWER(p.owner) = %s
          AND {_ROOT_FILTER} AND {_COMMUNITY_FILTER} AND p.deleted = false
          AND p.created_at >= %s
          {bt_clause}
        ORDER BY p.created_at DESC
        LIMIT %s""",
        [viewer, min_ts] + bt_params + [max_posts],
    )
    src0_n = 0
    for row in cur.fetchall():
        post = _row_to_post(
            row,
            blocked_posts,
            blocked_users,
            seen,
            blocked_communities,
            blocked_community_prefixes,
            viewer=viewer,
        )
        if post:
            post["_source"] = "own"
            results.append(post)
            src0_n += 1
    timings["src0_ms"] = _ms_since(_t)
    timings["src0_n"] = src0_n

    # Source 1: Posts BY similar users (root posts only)
    _t = _time.monotonic()
    src1_n = 0
    if similar_addrs:
        similar_list = list(similar_addrs)
        placeholders = ",".join(["%s"] * len(similar_list))
        cur.execute(
            f"""SELECT {_POST_COLS}
            FROM posts p
            LEFT JOIN profiles pr ON LOWER(pr.owner) = LOWER(p.owner)
            WHERE LOWER(p.owner) IN ({placeholders})
              AND {_ROOT_FILTER} AND {_COMMUNITY_FILTER} AND p.deleted = false
              {bt_clause}
            ORDER BY p.created_at DESC
            LIMIT %s""",
            similar_list + bt_params + [max_posts],
        )
        for row in cur.fetchall():
            post = _row_to_post(
                row,
                blocked_posts,
                blocked_users,
                seen,
                blocked_communities,
                blocked_community_prefixes,
                viewer=viewer,
            )
            if post:
                post["_source"] = "similar_author"
                results.append(post)
                src1_n += 1
    timings["src1_ms"] = _ms_since(_t)
    timings["src1_n"] = src1_n

    # Source 2: Posts UPVOTED by similar users.
    # Drive from posts (uses idx_posts_created_at) and use EXISTS against the
    # uniq_votes_owner_target index instead of seq-scanning votes. The old
    # `FROM votes JOIN posts` plan did a full seq scan of ~128k upvote rows.
    _t = _time.monotonic()
    src2_n = 0
    if similar_addrs:
        similar_list = list(similar_addrs)
        placeholders = ",".join(["%s"] * len(similar_list))
        cur.execute(
            f"""SELECT {_POST_COLS}
            FROM posts p
            LEFT JOIN profiles pr ON LOWER(pr.owner) = LOWER(p.owner)
            WHERE EXISTS (
                SELECT 1 FROM votes v
                WHERE LOWER(v.target) = LOWER(p.txhash)
                  AND LOWER(v.owner) IN ({placeholders})
                  AND v.user_vote > 0
              )
              AND {_ROOT_FILTER} AND {_COMMUNITY_FILTER} AND p.deleted = false
              {bt_clause}
            ORDER BY p.created_at DESC
            LIMIT %s""",
            similar_list + bt_params + [max_posts],
        )
        for row in cur.fetchall():
            post = _row_to_post(
                row,
                blocked_posts,
                blocked_users,
                seen,
                blocked_communities,
                blocked_community_prefixes,
                viewer=viewer,
            )
            if post:
                post["_source"] = "similar_upvoted"
                results.append(post)
                src2_n += 1
    timings["src2_ms"] = _ms_since(_t)
    timings["src2_n"] = src2_n

    # Source 3: Recent posts (discovery)
    _t = _time.monotonic()
    cur.execute(
        f"""SELECT {_POST_COLS}
        FROM posts p
        LEFT JOIN profiles pr ON LOWER(pr.owner) = LOWER(p.owner)
        WHERE {_ROOT_FILTER} AND {_COMMUNITY_FILTER} AND p.deleted = false
        {bt_clause}
        ORDER BY p.created_at DESC
        LIMIT %s""",
        bt_params + [max_posts],
    )
    src3_n = 0
    for row in cur.fetchall():
        post = _row_to_post(
            row,
            blocked_posts,
            blocked_users,
            seen,
            blocked_communities,
            blocked_community_prefixes,
            viewer=viewer,
        )
        if post:
            post["_source"] = "recent"
            results.append(post)
            src3_n += 1
    timings["src3_ms"] = _ms_since(_t)
    timings["src3_n"] = src3_n

    return results, timings


def _row_to_post(
    row,
    blocked_posts,
    blocked_users,
    seen,
    blocked_communities: set[str] | None = None,
    blocked_community_prefixes: tuple[str, ...] | None = None,
    viewer: str = "",
) -> dict | None:
    """Convert a DB row to a post dict, or None if should be skipped."""
    import json as _json

    # 16-column rows (with media + author_created_at + relayer)
    if len(row) >= 16:
        (
            txhash,
            owner,
            ts,
            community,
            title,
            content,
            tag,
            root_community,
            root_post_id,
            username,
            edited_at,
            thumbnail,
            author_level,
            media_raw,
            author_created_at,
            relayer,
        ) = row[:16]
    # 15-column rows (with media + relayer)
    elif len(row) >= 15:
        (
            txhash,
            owner,
            ts,
            community,
            title,
            content,
            tag,
            root_community,
            root_post_id,
            username,
            edited_at,
            thumbnail,
            author_level,
            media_raw,
            relayer,
        ) = row[:15]
        author_created_at = 0
    else:
        (
            txhash,
            owner,
            ts,
            community,
            title,
            content,
            tag,
            root_community,
            root_post_id,
            username,
            edited_at,
            thumbnail,
            author_level,
        ) = row
        media_raw = "[]"
        author_created_at = 0
        relayer = ""

    pid = (txhash or "").lower()
    author = (owner or "").lower()
    tag = _normalize_api_tag(tag or "")

    relayer_lower = (relayer or "").strip().lower()
    viewer_lower = (viewer or "").strip().lower()
    post_ts = int(ts) if ts else 0
    is_own = viewer_lower and author == viewer_lower
    if is_own and post_ts < _now_epoch() - 3600:
        is_own = False
    if pid in seen:
        return None
    if not is_own and (pid in blocked_posts or author in blocked_users):
        return None
    community_lower = (community or "").strip().lower()
    if not is_own and _community_is_blocked(
        community_lower, blocked_communities or set(), blocked_community_prefixes or tuple()
    ):
        return None
    # The author's tag is not filtered here: a curator override or the community
    # tag can raise or clear it, and neither is known until the lens is
    # resolved. Callers drop on the effective tag after _resolve_effective_tags.

    # Parse media JSON array
    try:
        media = _json.loads(media_raw or "[]")
        if not isinstance(media, list):
            media = []
    except Exception:
        media = []

    post = {
        "post_id": pid,
        "author": author,
        "user_id": author,
        "username": username or "",
        "author_level": int(author_level) if author_level else 0,
        "author_is_new": _is_new_user(int(author_created_at or 0)),
        "timestamp": int(ts) if ts else 0,
        "community": (community or "").strip(),
        "root_community": (root_community or community or "").strip(),
        "root_post_id": (root_post_id or pid).lower(),
        "title": title or "",
        "content": content or "",
        "tag": tag,
        "edited": bool(edited_at),
        "edited_at": int(edited_at or 0),
        "thumbnail": thumbnail or "",
        "media": media,
        "media_meta": [],
        "relayer": relayer_lower,
    }
    seen.add(pid)
    return post


# ---- Similar-user upvote cache (backend-DB, per-owner) ----
# The scoring path needs "which similar users upvoted each candidate post".
# Postgres' only viable plan for the naive IN/IN query scans every vote row
# belonging to the 30 similar users (tens of thousands of rows for active
# voters) and costs 100-250ms per home feed load even when the final
# intersection is tiny.
#
# We cache each owner's recent upvoted-post set in `user_upvote_cache` on the
# backend DB (same pattern as `user_similarity_cache`). Shared across gunicorn
# workers and container restarts, keyed on owner so there's no duplication
# across viewers (the same active voter appears in many viewers' similarity
# sets and only needs to be cached once).
#
# Payload is bounded by a 30-day window on votes.created_at: candidate posts
# are dominated by posts from the last few days, so older upvotes can't
# contribute to the intersection anyway.
# TTL is 1h: a similar user's upvote history barely shifts within an hour,
# and a short TTL was producing ~30% miss rate per request (130-290ms
# miss-fill) on top of an already-filtered cache read.
_SIM_UPVOTES_CACHE_TTL = 3600
_SIM_UPVOTES_WINDOW_SECS = 30 * 24 * 3600

# Vote totals cache: feed scoring uses SUM(user_weight) over all votes per post,
# which costs 0.3-0.9ms/post via LATERAL JOIN -> 100-260ms per home feed load
# with 130-370 candidates. We cache the unfiltered total per post for 60s on
# the backend DB. Only used when the viewer has no blocked users (the majority)
# — blocked-user totals are viewer-dependent and fall through to the live query.
_VOTE_TOTALS_CACHE_TTL = 60


def _load_similar_user_upvotes(
    cur,
    post_ids: list[str],
    similar_addrs: set[str],
    backend_cur=None,
) -> tuple[dict[str, list[str]], dict[str, float]]:
    """
    Return ({post_id: [voter_addr, ...]}, timings) for similar users that
    upvoted each candidate post. Reads/writes a shared backend-DB cache
    keyed by owner.

    timings sub-phases (used to track down the 160-230ms sim_up_ms tail):
      sim_up_cache_ms     backend-DB SELECT from user_upvote_cache
      sim_up_miss_ms      cold-fill (votes SELECT + UPSERT), 0 if all hit
      sim_up_intersect_ms Python intersection over cached sets
      sim_up_hits         similar users served from cache
      sim_up_misses       similar users cold-filled this call
    """
    import time as _time

    def _ms_since(t0: float) -> float:
        return round((_time.monotonic() - t0) * 1000, 2)

    timings: dict[str, float] = {
        "sim_up_cache_ms": 0.0,
        "sim_up_miss_ms": 0.0,
        "sim_up_intersect_ms": 0.0,
        "sim_up_hits": 0,
        "sim_up_misses": 0,
    }

    if not post_ids or not similar_addrs:
        return {}, timings

    similar_list = list({str(addr).lower() for addr in similar_addrs if addr})
    if not similar_list:
        return {}, timings
    now_ts = int(time.time())

    cached: dict[str, frozenset[str]] = {}
    fetched: dict[str, frozenset[str]] = {}

    post_set = set(post_ids)

    def _read_and_fill_cache(bcur):
        # Filter the cached TEXT[] to the candidate post_ids in Postgres so we
        # don't ship every user's full 90-day upvote history over the wire
        # just to intersect it in Python — that was costing ~60ms per request
        # even with a 100% cache hit (30 users × ~5k TEXT[] entries = multi-MB
        # transfer + psycopg deserialization). Post-filter rows are at most a
        # few dozen strings per user.
        _t = _time.monotonic()
        bcur.execute(
            """
            SELECT owner,
                   ARRAY(
                       SELECT t FROM unnest(upvoted_posts) t
                       WHERE t = ANY(%s)
                   ) AS matches
            FROM user_upvote_cache
            WHERE owner = ANY(%s) AND expires_at > %s
            """,
            (list(post_set), similar_list, now_ts),
        )
        for owner, matches in bcur.fetchall():
            cached[owner] = frozenset(matches or ())
        timings["sim_up_cache_ms"] = _ms_since(_t)
        timings["sim_up_hits"] = len(cached)

        missing = [a for a in similar_list if a not in cached]
        timings["sim_up_misses"] = len(missing)
        if missing:
            _t = _time.monotonic()
            ph = ",".join(["%s"] * len(missing))
            cutoff = now_ts - _SIM_UPVOTES_WINDOW_SECS
            cur.execute(
                f"""
                SELECT LOWER(owner), LOWER(target)
                FROM votes
                WHERE LOWER(owner) IN ({ph})
                  AND user_vote > 0
                  AND created_at > %s
                """,
                missing + [cutoff],
            )
            raw: dict[str, list[str]] = {addr: [] for addr in missing}
            for owner, target in cur.fetchall():
                bucket = raw.get(owner)
                if bucket is not None and target:
                    bucket.append(target)

            # Users with no recent upvotes get an empty array cached as a
            # negative result so we don't re-query them every 10 minutes.
            expires_at = now_ts + _SIM_UPVOTES_CACHE_TTL
            values_sql = ",".join(["(%s, %s, %s, %s)"] * len(raw))
            params: list = []
            for addr, posts in raw.items():
                params.extend((addr, posts, now_ts, expires_at))
            bcur.execute(
                f"""
                INSERT INTO user_upvote_cache (owner, upvoted_posts, computed_at, expires_at)
                VALUES {values_sql}
                ON CONFLICT (owner) DO UPDATE SET
                    upvoted_posts = EXCLUDED.upvoted_posts,
                    computed_at = EXCLUDED.computed_at,
                    expires_at = EXCLUDED.expires_at
                """,
                params,
            )
            for addr, posts in raw.items():
                fetched[addr] = frozenset(posts)
            timings["sim_up_miss_ms"] = _ms_since(_t)

    if backend_cur is not None:
        _read_and_fill_cache(backend_cur)
    else:
        with connect_backend_db() as bconn:
            with bconn.cursor() as bcur:
                _read_and_fill_cache(bcur)

    _t = _time.monotonic()
    result: dict[str, list[str]] = {}
    # `cached` rows are already filtered to post_set in SQL; `fetched` rows
    # still carry the full recent upvote set and need Python intersection.
    for addr, upvoted in cached.items():
        if not upvoted:
            continue
        for pid in upvoted:
            result.setdefault(pid, []).append(addr)
    for addr, upvoted in fetched.items():
        if not upvoted:
            continue
        for pid in upvoted & post_set:
            result.setdefault(pid, []).append(addr)
    timings["sim_up_intersect_ms"] = _ms_since(_t)
    return result, timings


def _get_guest_feed(
    cur,
    limit: int,
    page: int,
    blocked_posts: set[str],
    blocked_users: set[str],
    allowed_tags: set[str],
    blocked_communities: set[str] = None,
    blocked_community_prefixes: tuple[str, ...] | None = None,
) -> dict:
    """Simple chronological feed for guest users."""
    max_candidates = min(limit * page * 2, MAX_CANDIDATE_POOL)
    candidates = _load_candidate_posts(
        cur,
        max_candidates,
        blocked_posts,
        blocked_users,
        allowed_tags,
        blocked_communities=blocked_communities,
        blocked_community_prefixes=blocked_community_prefixes,
    )

    if not candidates:
        return {"posts": [], "total": 0, "page": page, "limit": limit, "has_more": False}

    # Load vote/comment/award stats (no viewer for guest)
    post_ids = [c["post_id"] for c in candidates]
    vote_totals, comment_counts, _, _, _ = _load_vote_and_comment_stats(cur, post_ids, blocked_posts, blocked_users)
    _, award_details = _load_award_aggregates(cur, post_ids, blocked_users)

    for post in candidates:
        pid = post["post_id"]
        post["points"] = vote_totals.get(pid, 0.0)
        post["comments"] = comment_counts.get(pid, 0)
        post["awards"] = award_details.get(pid, [])
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
    blocked_communities: set[str] = None,
    blocked_community_prefixes: tuple[str, ...] | None = None,
) -> dict:
    """
    Guest home feed, Magic-style:
    - No personalization (S=0, P=0)
    - Score uses the same Magic scorer: (S + V + U + P) × R
    """
    import time

    max_candidates = min(limit * page * 4, MAX_CANDIDATE_POOL)
    candidates = _load_candidate_posts(
        cur,
        max_candidates,
        blocked_posts,
        blocked_users,
        allowed_tags,
        blocked_communities=blocked_communities,
        blocked_community_prefixes=blocked_community_prefixes,
    )

    if not candidates:
        return {"posts": [], "total": 0, "page": page, "limit": limit, "has_more": False}

    post_ids = [c["post_id"] for c in candidates]
    vote_totals, comment_counts, _, _, _ = _load_vote_and_comment_stats(cur, post_ids, blocked_posts, blocked_users)
    unique_commenters = _load_unique_commenter_counts(cur, post_ids, blocked_posts, blocked_users)
    unique_awarders, award_details = _load_award_aggregates(cur, post_ids, blocked_users)

    now_ts = int(time.time())
    sim_lookup: dict[str, float] = {}
    similar_upvotes: dict[str, list[str]] = {}
    community_prefs: dict[str, float] = {}
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
            community_prefs,
            author_prefs,
            now_ts,
            False,
            unique_awarders,
        )
        if should_hide:
            continue

        post["_score"] = score
        post["feed_debug"] = debug
        post["points"] = float(vote_totals.get(pid, 0.0) or 0.0)
        post["comments"] = int(comment_counts.get(pid, 0) or 0)
        post["unique_commenters"] = int(unique_commenters.get(pid, 0) or 0)
        post["awards"] = award_details.get(pid, [])
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
    """Indexer-only tx status for all tx types.

    Queries votes/posts for rich details first, then falls back to
    the universal tx_index table for any other tx type (set_username,
    follow, block, etc.). Returns {found:false} only when
    the tx hasn't been indexed yet.
    """
    rid = next_request_id()
    try:
        if _is_catching_up():
            return api_error_code("node_catching_up", 503)

        tx_hash = str(request.args.get("hash", "") or "").strip().lower()
        if not tx_hash or len(tx_hash) != 64:
            return jsonify({"error": "invalid or missing hash"}), 400

        log_event(rid, "get_tx_status.begin", tx_hash=tx_hash)

        tx_type = "unknown"
        details = None
        conn = None

        try:
            conn = connect_db(timeout=5.0, busy_timeout_ms=15000)
            cur = conn.cursor()

            # Check votes table
            cur.execute(
                """
                SELECT v.owner, v.target, v.user_vote, v.user_weight, v.created_at, COALESCE(v.relayer, '')
                FROM votes v WHERE LOWER(v.txhash) = %s
                """,
                (tx_hash,),
            )
            vote_row = cur.fetchone()
            if vote_row:
                tx_type = "vote"
                owner, target, user_vote_val, user_weight_val, created_at, relayer = vote_row
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
                    "relayer": (relayer or "").strip().lower(),
                    "target": target,
                    "user_vote": user_vote_val,
                    "user_weight": round(user_weight_val, 3) if user_weight_val else 0,
                    "target_points": target_points,
                }
            else:
                # Check posts table
                cur.execute(
                    "SELECT txhash, community, title, COALESCE(relayer, '') FROM posts WHERE LOWER(txhash) = %s",
                    (tx_hash,),
                )
                post_row = cur.fetchone()
                if post_row:
                    tx_type = "post"
                    details = {
                        "post_id": post_row[0],
                        "community": post_row[1] or "",
                        "title": post_row[2] or "",
                        "relayer": (post_row[3] or "").strip().lower(),
                    }

            if tx_type == "unknown":
                cur.execute(
                    """
                    SELECT tx_type, code, raw_log, height
                    FROM tx_index WHERE txhash = %s
                    """,
                    (tx_hash,),
                )
                idx_row = cur.fetchone()
                if idx_row:
                    idx_type, idx_code, idx_log, idx_height = idx_row
                    if int(idx_code or 0) != 0:
                        out = {
                            "found": True,
                            "tx_hash": tx_hash,
                            "height": int(idx_height or 0),
                            "code": int(idx_code),
                            "success": False,
                            "indexed": True,
                            "tx_type": str(idx_type or "unknown"),
                            "error_details": _classify_reject(str(idx_log or "")),
                        }
                        log_event(
                            rid, "get_tx_status.failed", tx_hash=tx_hash, tx_type=out["tx_type"], code=out["code"]
                        )
                        return jsonify(out)
                    tx_type = str(idx_type or "unknown")

        except Exception as db_err:
            log_event(rid, "get_tx_status.db_error", tx_hash=tx_hash, error=str(db_err))
            return safe_error(db_err)
        finally:
            try:
                if conn:
                    conn.close()
            except Exception:
                pass

        if tx_type == "unknown":
            log_event(rid, "get_tx_status.not_indexed", tx_hash=tx_hash)
            return jsonify({"found": False})

        out = {
            "found": True,
            "tx_hash": tx_hash,
            "code": 0,
            "success": True,
            "indexed": True,
            "tx_type": tx_type,
        }
        if details:
            out["details"] = details

        log_event(rid, "get_tx_status.ok", tx_hash=tx_hash, tx_type=tx_type)
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
            return api_error_code("node_catching_up", 503)
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

        op_addr = require_runtime().validator_operator_address
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


def _build_user_status(addr: str) -> dict:
    """Pure helper: build the user-status payload for a given address.

    Caller must ensure addr is non-empty and the node is not catching up.
    Used by both /api/get_user_status and the consolidated /api/bootstrap route.
    """
    username = None
    user_level = 0
    profile_registered_at = None
    subscription_expiry = 0
    auto_renew = False
    reserve_funds = 0
    inbox_last_viewed_at = 0
    referral_precheck_enabled = False
    effective_paid = False

    with connect_db(timeout=10.0, busy_timeout_ms=15000) as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT username, level, created_at, subscription_expiry, auto_renew,
                   reserve_funds, COALESCE(effective_paid, FALSE)
            FROM profiles WHERE LOWER(owner)=LOWER(%s) LIMIT 1
            """,
            (addr,),
        )
        row = cur.fetchone()
        if row:
            username = row[0] if row[0] else None
            user_level = int(row[1]) if row[1] is not None else 0
            profile_registered_at = int(row[2]) if row[2] is not None else None
            subscription_expiry = int(row[3]) if row[3] is not None else 0
            auto_renew = bool(row[4]) if row[4] is not None else False
            reserve_funds = int(row[5]) if row[5] is not None else 0
            effective_paid = bool(row[6])
            if effective_paid and user_level < 1:
                user_level = 1

    addr_lower = addr.lower()
    with connect_backend_db() as conn_ib:
        cur_ib = conn_ib.cursor()
        cur_ib.execute(
            "SELECT inbox_last_viewed_at FROM user_inbox_state WHERE LOWER(owner)=LOWER(%s) LIMIT 1",
            (addr_lower,),
        )
        row_ib = cur_ib.fetchone()
        if row_ib and row_ib[0] is not None:
            inbox_last_viewed_at = int(row_ib[0])

    balance = int(_get_balance(addr))

    recent_votes: list = []
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

    return {
        "username": username,
        "balance": balance,
        "user_level": user_level,
        "subscription_expiry": subscription_expiry,
        "auto_renew": auto_renew,
        "reserve_funds": reserve_funds,
        "profile_registered_at": profile_registered_at,
        "recent_votes": recent_votes,
        "inbox_last_viewed_at": inbox_last_viewed_at,
        "referral_precheck_enabled": referral_precheck_enabled,
        "effective_paid": effective_paid,
    }


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
            return api_error_code("node_catching_up", 503)
        resp = _build_user_status(addr)
        log_event(
            rid,
            "get_user_status.ok",
            user_level=resp.get("user_level", 0),
            effective_paid=bool(resp.get("effective_paid", False)),
            subscription_expiry=resp.get("subscription_expiry", 0),
        )
        return jsonify(resp)
    except Exception as e:
        log_event(rid, "get_user_status.err", error=str(e))
        return safe_error(e)


def _build_user_followed(addr: str) -> dict:
    """Pure helper: build the user-followed payload for a given address.

    Caller must ensure addr is non-empty. Does NOT inject balance — that's the
    standalone route's responsibility. Used by /api/get_user_followed and
    /api/bootstrap.
    """
    # No try/except: an indexer failure must not be reported as "you follow
    # nobody and joined nothing". Empty lists would make the client offer to
    # re-join communities the user is already in. Both callers already turn the
    # exception into a hard error (/api/bootstrap → 503 indexer_unavailable,
    # /api/get_user_followed → safe_error).
    conn = connect_db(timeout=10.0, busy_timeout_ms=15000)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT target FROM followed_users WHERE LOWER(owner)=LOWER(%s) ORDER BY position ASC",
            (addr,),
        )
        followed_users = [row[0] for row in cur.fetchall()]
        cur.execute(
            "SELECT community FROM community_curation_preferences WHERE LOWER(owner)=LOWER(%s) ORDER BY community",
            (addr,),
        )
        joined_communities = [row[0] for row in cur.fetchall()]
    finally:
        conn.close()

    return {
        "followed_users": followed_users,
        "joined_communities": joined_communities,
    }


@public_bp.route("/api/get_user_followed")
def get_user_followed():
    """Get user's follow lists (users, joined communities)."""
    rid = next_request_id()
    addr = request.args.get("address", default=None, type=str)
    log_event(rid, "get_user_followed.begin", address=addr)
    try:
        if not addr:
            return jsonify({"error": "address required"}), 400
        resp = _build_user_followed(addr)
        log_event(
            rid,
            "get_user_followed.ok",
            users=len(resp.get("followed_users", [])),
            communities=len(resp.get("joined_communities", [])),
        )
        return jsonify(_inject_balance(resp, addr))
    except Exception as e:
        log_event(rid, "get_user_followed.err", error=str(e))
        return safe_error(e)


def _build_user_blocked(addr: str) -> dict:
    """Pure helper: build the user-blocked payload for a given address.

    Caller must ensure addr is non-empty. Does NOT inject balance.
    Used by /api/get_user_blocked and /api/bootstrap.
    """
    blocked_posts: list = []
    blocked_users: list = []
    blocked_communities: list = []

    try:
        conn = connect_db(timeout=10.0, busy_timeout_ms=15000)
        cur = conn.cursor()
        cur.execute("SELECT target FROM blocked_posts WHERE LOWER(owner)=LOWER(%s)", (addr,))
        blocked_posts = [row[0] for row in cur.fetchall()]
        cur.execute("SELECT target FROM blocked_users WHERE LOWER(owner)=LOWER(%s)", (addr,))
        blocked_users = [row[0] for row in cur.fetchall()]
        cur.execute("SELECT target FROM blocked_communities WHERE LOWER(owner)=LOWER(%s)", (addr,))
        blocked_communities = [row[0] for row in cur.fetchall()]
        conn.close()
    except Exception:
        pass

    return {
        "blocked_posts": blocked_posts,
        "blocked_users": blocked_users,
        "blocked_communities": blocked_communities,
    }


@public_bp.route("/api/get_user_blocked")
def get_user_blocked():
    """Get user's block lists (posts, users, communities)."""
    rid = next_request_id()
    addr = request.args.get("address", default=None, type=str)
    log_event(rid, "get_user_blocked.begin", address=addr)
    try:
        if not addr:
            return jsonify({"error": "address required"}), 400
        resp = _build_user_blocked(addr)
        log_event(
            rid,
            "get_user_blocked.ok",
            posts=len(resp.get("blocked_posts", [])),
            users=len(resp.get("blocked_users", [])),
        )
        return jsonify(_inject_balance(resp, addr))
    except Exception as e:
        log_event(rid, "get_user_blocked.err", error=str(e))
        return safe_error(e)


@public_bp.route("/api/get_preferences")
def get_preferences():
    """Get user's community/user preference weights."""
    rid = next_request_id()
    addr = request.args.get("address", default=None, type=str)
    log_event(rid, "get_preferences.begin", address=addr)
    try:
        if not addr:
            return jsonify({"error": "address required"}), 400

        communities: list[dict] = []
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
                if pref_type == "community":
                    communities.append({"community": t, "weight": w})
                elif pref_type == "author":
                    authors.append({"user": t, "weight": w})
            conn.close()
        except Exception:
            pass

        communities.sort(key=lambda x: x["weight"], reverse=True)
        authors.sort(key=lambda x: x["weight"], reverse=True)

        resp = {"communities": communities, "authors": authors}
        log_event(rid, "get_preferences.ok", communities=len(communities), authors=len(authors))
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
    """Get staked balance for the validator from indexer DB, cached 60s."""
    now = int(time.time())
    if _staked_balance_cache["expires"] > now:
        return _staked_balance_cache["value"]
    total = 0
    try:
        rt = require_runtime()
        if rt.validator_operator_address:
            total = _get_staked_balance(rt.validator_operator_address)
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
            return api_error_code("node_catching_up", 503)

        # Get block time
        try:
            block_time = _get_block_time_seconds()
        except Exception:
            block_time = 0

        # Get difficulty info
        diff_info = _get_difficulty_info()

        # Get server balance
        rt = require_runtime()
        server_balance = int(_get_balance(rt.validator_payer_addr))

        # Get staked balance (cached 60s)
        staked_balance = 0
        try:
            staked_balance = _get_cached_staked_balance()
        except Exception:
            pass

        # Difference the node's cumulative payout and fee counters, which the
        # indexer accumulates from block events. Differencing node_balance
        # instead counted every transfer in as income and every transfer out as
        # a loss, so a freshly funded node reported its entire holding as 24h
        # earnings and reported the stake it had just delegated as burned.
        since_ts = int(time.time()) - 86400
        conn_sh = connect_db(timeout=5.0, busy_timeout_ms=5000)
        try:
            cur_sh = conn_sh.cursor()
            cur_sh.execute(
                """
                SELECT node_minted_total, node_fees_total FROM supply_history
                WHERE created_at >= %s
                  AND node_minted_total IS NOT NULL
                  AND node_fees_total IS NOT NULL
                ORDER BY height ASC
                """,
                (since_ts,),
            )
            rows_sh = cur_sh.fetchall()
        finally:
            conn_sh.close()
        earned_24h = 0
        spent_24h = 0
        if len(rows_sh) >= 2:
            # Both counters only ever grow. A decrease means the history was
            # rebuilt, and reporting negative earnings would be a lie.
            earned_24h = max(0, int(rows_sh[-1][0]) - int(rows_sh[0][0]))
            spent_24h = max(0, int(rows_sh[-1][1]) - int(rows_sh[0][1]))

        resp = {
            "server_balance": server_balance,
            "staked_balance": staked_balance,
            "block_time": block_time,
            "earned_24h": earned_24h,
            "spent_24h": spent_24h,
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
            SELECT height, total_supply, created_at, node_balance,
                   node_minted_total, node_fees_total
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
        {
            "height": r[0],
            "total_supply": r[1],
            "timestamp": r[2],
            "node_balance": r[3],
            "node_minted_total": r[4],
            "node_fees_total": r[5],
        }
        for r in rows
    ]

    _supply_history_cache["data"] = history
    _supply_history_cache["expires"] = now + 30  # 30 second cache
    return history


def _get_last_seen_rollups(now: int) -> dict[str, int]:
    today_start = now - 86400
    yesterday_start = now - (2 * 86400)
    thirty_days_ago = now - (30 * 86400)

    with connect_backend_db() as bconn:
        bcur = bconn.cursor()
        bcur.execute("SELECT COUNT(*) FROM user_last_seen WHERE last_seen_at >= %s", (today_start,))
        dau_today = bcur.fetchone()[0] or 0
        bcur.execute(
            "SELECT COUNT(*) FROM user_last_seen WHERE last_seen_at >= %s AND last_seen_at < %s",
            (yesterday_start, today_start),
        )
        dau_yesterday = bcur.fetchone()[0] or 0
        bcur.execute("SELECT COUNT(*) FROM user_last_seen WHERE last_seen_at >= %s", (thirty_days_ago,))
        maus = bcur.fetchone()[0] or 0

    logger.debug(
        "stats.last_seen dau_today=%d dau_yesterday=%d maus=%d",
        dau_today,
        dau_yesterday,
        maus,
    )
    return {
        "dau_any_today": int(dau_today),
        "dau_today": int(dau_today),
        "dau_registered_today": int(dau_today),
        "dau_yesterday": int(dau_yesterday),
        "maus": int(maus),
    }


@public_bp.route("/api/get_supply_history")
def get_supply_history():
    """Get supply history for burn/mint chart (7 days)."""
    rid = next_request_id()
    log_event(rid, "get_supply_history.begin")
    try:
        if _is_catching_up():
            return api_error_code("node_catching_up", 503)

        history = _get_cached_supply_history()

        resp = {
            "history": history,
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

# Short-lived cache for unauthenticated full-table aggregations. get_welcome_stats
# next door already had one; the community listing did not, so every anonymous request
# ran two GROUP BY aggregations over the whole posts table with a 10s statement
# timeout and no rate limit. 30s matches the sibling and is well inside the window
# where a newly created community still appears promptly.
AGG_CACHE_TTL_SECONDS = 30
_agg_cache: Dict[str, tuple[int, Any]] = {}
_agg_cache_lock = threading.Lock()


def _agg_cache_get(key: str) -> Any:
    with _agg_cache_lock:
        entry = _agg_cache.get(key)
        if entry and entry[0] > int(time.time()):
            return entry[1]
    return None


def _agg_cache_put(key: str, value: Any) -> None:
    now = int(time.time())
    with _agg_cache_lock:
        # Bounded by eviction of expired entries: the key includes client-supplied
        # arguments, so without this the dict is an unbounded attacker-grown map.
        if len(_agg_cache) > 256:
            for k, v in list(_agg_cache.items()):
                if v[0] <= now:
                    del _agg_cache[k]
        _agg_cache[key] = (now + AGG_CACHE_TTL_SECONDS, value)


# ---- Anonymous feed cache ----
# A signed-out visitor has no blocked lists, no seen map, no vote state and a
# fixed agent list, so page N of the guest feed is a single value shared by
# every guest. It was recomputed from scratch on every request on the busiest
# endpoint on the site: the feed query itself, the media enrichment, the agent
# overlay and the tag filter. Compute it once per TTL instead. Signed-in
# requests never read or write this cache — their feed is viewer-specific.
# 30s matches AGG_CACHE_TTL_SECONDS; a new post reaches the anonymous
# frontpage within that window.
GUEST_FEED_CACHE_TTL_SECONDS = 30
_guest_feed_cache: Dict[str, tuple[int, Dict[str, Any]]] = {}
_guest_feed_cache_lock = threading.Lock()


def _guest_feed_cache_key(
    feed: str,
    sort_mode: str,
    page: int,
    limit: int,
    allowed_tags: set[str],
    *,
    viewer: str,
    community: str,
    scope: str,
    lens: str,
    team_id: int | None,
) -> str:
    # allowed_tags is clamped to empty for guests today, but it stays in the key
    # so a future policy change cannot serve one tag policy's posts under another.
    return (
        f"{viewer}|{feed}|{community}|{scope}|{lens}|{team_id or 0}|"
        f"{sort_mode}|{page}|{limit}|{','.join(sorted(allowed_tags))}"
    )


def _guest_feed_cache_get(key: str) -> Optional[Dict[str, Any]]:
    with _guest_feed_cache_lock:
        entry = _guest_feed_cache.get(key)
        if not entry or entry[0] <= int(time.time()):
            return None
        # Deep copy: callers merge and enrich the response they get back, and a
        # shared entry would accumulate those edits across requests.
        return copy.deepcopy(entry[1])


def _guest_feed_cache_put(key: str, value: Dict[str, Any]) -> None:
    now = int(time.time())
    with _guest_feed_cache_lock:
        # Keys are built from clamped, validated arguments (feed name, sort mode,
        # clamped page/limit), so the space is small — evict expired entries only.
        if len(_guest_feed_cache) > 128:
            for k, v in list(_guest_feed_cache.items()):
                if v[0] <= now:
                    del _guest_feed_cache[k]
        _guest_feed_cache[key] = (now + GUEST_FEED_CACHE_TTL_SECONDS, copy.deepcopy(value))


_WELCOME_STATS_CACHE_TTL = 30  # 30 seconds

# Cache for full overview stats (expensive query)
_overview_stats_cache: Dict[str, Any] = {"data": None, "expires": 0}
_OVERVIEW_STATS_CACHE_TTL = 30  # 30 seconds

# Cache for analytics stats (expensive query)
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
            return api_error_code("node_catching_up", 503)

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
_CHAIN_CONFIG_CACHE_TTL: float = PARAMS_REFRESH_SECONDS


def _build_chain_config() -> dict:
    """Pure helper: build chain governance params."""
    global _CHAIN_CONFIG_CACHE, _CHAIN_CONFIG_CACHE_TIME

    now = time.monotonic()
    if _CHAIN_CONFIG_CACHE is not None and (now - _CHAIN_CONFIG_CACHE_TIME) < _CHAIN_CONFIG_CACHE_TTL:
        return dict(_CHAIN_CONFIG_CACHE)

    if _is_catching_up():
        raise RuntimeError("node_catching_up")

    p = expect_params()
    resp: Dict[str, Any] = {
        "max_username_size": p["max_username_size"],
        "min_username_size": p["min_username_size"],
        "max_community_size": p["max_community_size"],
        "min_community_size": p["min_community_size"],
        "subscription_period": p["subscription_period"],
        "subscription_reserve_bps": p["subscription_reserve_bps"],
        "mint_interval": p["mint_interval"],
        "mint_floor_split": p["mint_floor_split"],
        "mint_dynamic_split": p["mint_dynamic_split"],
        "block_time": _get_block_time_seconds(),
        "tiers": p["tiers"],
        "award_configs": p["award_configs"],
    }
    _CHAIN_CONFIG_CACHE = resp
    _CHAIN_CONFIG_CACHE_TIME = now
    return dict(resp)


@public_bp.route("/api/get_chain_config")
def get_chain_config():
    """Chain governance params (tiers, limits, subscription_period, etc.).

    Cached for the same 60-second window as the underlying parameter cache, so
    governance and upgrade-handler changes become visible together.
    No difficulty/height — use get_network_stats or get_parameters for those.
    """
    rid = next_request_id()
    log_event(rid, "get_chain_config.begin")
    try:
        now = time.monotonic()
        if _CHAIN_CONFIG_CACHE is not None and (now - _CHAIN_CONFIG_CACHE_TIME) < _CHAIN_CONFIG_CACHE_TTL:
            log_event(rid, "get_chain_config.cached")
            return jsonify(_CHAIN_CONFIG_CACHE)

        if _is_catching_up():
            return api_error_code("node_catching_up", 503)

        resp = _build_chain_config()
        log_event(rid, "get_chain_config.ok")
        return jsonify(resp)
    except Exception as e:
        if str(e) == "node_catching_up":
            return api_error_code("node_catching_up", 503)
        log_event(rid, "get_chain_config.err", error=str(e))
        return safe_error(e)


# ---- get_node_config: per-node static settings ----
_NODE_CONFIG_CACHE: Optional[Dict[str, Any]] = None
_NODE_CONFIG_CACHE_TIME: float = 0.0
_NODE_CONFIG_CACHE_TTL: float = 86400.0  # 24 hours — these almost never change


def _build_node_config() -> dict:
    """Pure helper: build the node-config payload (with 24h server-side memoization).

    Cache hits are safe while the node is catching up. Cache misses require the
    caller to enforce catch-up semantics before this helper touches runtime data.
    """
    global _NODE_CONFIG_CACHE, _NODE_CONFIG_CACHE_TIME

    now = time.monotonic()
    if _NODE_CONFIG_CACHE is not None and (now - _NODE_CONFIG_CACHE_TIME) < _NODE_CONFIG_CACHE_TTL:
        return dict(_NODE_CONFIG_CACHE)

    rt = require_runtime()

    valoper = rt.validator_operator_address
    valcons = rt.validator_consensus_address
    val_account = rt.validator_payer_addr

    validator_moniker = ""
    if valoper:
        val_info = _get_validator(valoper)
        validator_moniker = val_info.get("moniker", "")

    resp: Dict[str, Any] = {
        "validator_account_address": val_account,
        "validator_operator_address": valoper,
        "validator_consensus_address": valcons,
        "validator_moniker": validator_moniker,
        "giphy_api_key": os.environ.get("REACT_APP_GIPHY_API_KEY", ""),
        "registration_enabled": REGISTRATION_ENABLED,
        "registration_invite_code_required": REGISTRATION_INVITE_CODE_REQUIRED,
        "open_browsing_enabled": OPEN_BROWSING_ENABLED,
        "new_user_highlight_days": NEW_USER_HIGHLIGHT_DAYS,
        "push_notifications_enabled": PUSH_NOTIFICATIONS_ENABLED,
        "android_banner_enabled": ANDROID_BANNER_ENABLED,
        "ios_banner_enabled": IOS_BANNER_ENABLED,
    }

    _NODE_CONFIG_CACHE = dict(resp)
    _NODE_CONFIG_CACHE_TIME = now
    return dict(resp)


@public_bp.route("/api/get_node_config")
def get_node_config():
    """Per-node static settings (validator info, feature flags, API keys).

    These are deployment-specific and don't change at runtime. Cached 24h server-side.
    """
    rid = next_request_id()
    log_event(rid, "get_node_config.begin")
    try:
        if _NODE_CONFIG_CACHE is None and _is_catching_up():
            return api_error_code("node_catching_up", 503)
        resp = _build_node_config()
        log_event(rid, "get_node_config.ok")
        return jsonify(resp)
    except Exception as e:
        log_event(rid, "get_node_config.err", error=str(e))
        return safe_error(e)


def _build_bootstrap_view(
    view_raw: str | None,
    address: str | None,
    sort_mode: str,
    allowed_tags: set,
    limit: int,
    rid: str,
) -> dict | None:
    """Build the optional bootstrap `view` payload. Returns None if absent/unrecognized."""
    if not view_raw:
        return None
    view = (view_raw or "").strip()
    if not view:
        return None

    addr = (address or "").strip()
    sort_mode = sort_mode if sort_mode in ("magic", "newest") else "magic"
    limit = min(max(1, int(limit or 15)), 100)
    community_hint = view[len("community:") :].strip() if view.startswith("community:") else None
    lens, team_id, scope = _lens_request_args(community_hint, allow_team_without_community=view.startswith("thread:"))

    # ── thread:<post_id> ──────────────────────────────────────────────
    if view.startswith("thread:"):
        post_id = view[len("thread:") :].strip().lower()
        if not post_id:
            return None
        conn = connect_db(timeout=10.0, busy_timeout_ms=15000)
        try:
            cur = conn.cursor()
            blocked_posts = _get_blocked_posts(cur, addr)
            blocked_users = _get_blocked_users(cur, addr)
            blocked_communities = _get_blocked_communities(cur, addr)
            blocked_communities_exact, blocked_community_prefixes = _split_blocked_communities(blocked_communities)
            thread = _build_thread(
                cur,
                post_id,
                addr,
                blocked_posts,
                blocked_users,
                blocked_communities_exact,
                blocked_community_prefixes,
                rid,
                lens=lens,
                team_id=team_id,
                scope=scope,
            )
            if not thread:
                return {"kind": "thread", "found": False}
            return {"kind": "thread", "found": True, **thread}
        finally:
            conn.close()

    # ── feed:home / feed:following / community:<name> ─────────────────────
    feed_name = None
    community_name = None
    if view == "feed:home":
        feed_name = "home"
    elif view == "feed:following":
        feed_name = "following"
    elif view.startswith("community:"):
        community_name = view[len("community:") :].strip()
        if not community_name:
            return None
        # Own connection inside get_posts — do not hold an idle conn here.
        from flask import current_app

        with current_app.test_request_context(
            "/api/get_posts",
            query_string={
                "community": community_name,
                "limit": str(limit),
                "page": "1",
                "by": sort_mode,
                "allowed_tags": ",".join(sorted(allowed_tags)),
                "lens": lens,
                "scope": scope,
                **({"team_id": str(team_id)} if team_id is not None else {}),
                **({"address": addr} if addr else {}),
            },
        ):
            posts_resp = get_posts()
            data = posts_resp.get_json(silent=True) if hasattr(posts_resp, "get_json") else None
            if not isinstance(data, dict) or "posts" not in data:
                raise RuntimeError("community_view_failed")
            return {
                "kind": "feed",
                "community": community_name,
                "posts": data.get("posts") or [],
                "total": data.get("total", 0),
                "page": data.get("page", 1),
                "limit": data.get("limit", limit),
                "has_more": bool(data.get("has_more")),
            }
    elif view == "inbox":
        if not addr:
            return None
        # Reuse get_inbox via its own connection by building query args and
        # calling the route under a request context — keeps pagination logic
        # in one place.
        from flask import current_app

        with current_app.test_request_context(
            "/api/get_inbox",
            query_string={"address": addr, "page": "1", "limit": str(min(limit, 25))},
        ):
            inbox_resp = get_inbox()
            if hasattr(inbox_resp, "get_json"):
                data = inbox_resp.get_json(silent=True) or {}
            else:
                data = {}
            if not isinstance(data, dict) or "replies" not in data:
                raise RuntimeError("inbox_view_failed")
            return {
                "kind": "inbox",
                "replies": data.get("replies") or [],
                "total": data.get("total", 0),
                "page": data.get("page", 1),
                "limit": data.get("limit", 25),
                "has_more": bool(data.get("has_more")),
            }
    else:
        return None

    # feed:home / feed:following only from here
    if feed_name not in ("home", "following"):
        return None

    guest_key = (
        _guest_feed_cache_key(
            feed_name,
            sort_mode,
            1,
            limit,
            allowed_tags,
            viewer="guest",
            community="",
            scope=scope,
            lens=lens,
            team_id=team_id,
        )
        if _is_guest(addr) and (scope == "legacy" or lens == "raw")
        else None
    )
    if guest_key is not None:
        cached = _guest_feed_cache_get(guest_key)
        if cached is not None:
            _track_image_impressions(
                cached.get("posts") or [], rid, context=f"bootstrap.view.feed.{feed_name}.guest_cached"
            )
            log_event(rid, "bootstrap.view.guest_cache.hit", key=guest_key)
            return {"kind": "feed", "feed": feed_name, **cached}

    conn = connect_db(timeout=10.0, busy_timeout_ms=15000)
    try:
        cur = conn.cursor()
        blocked_posts = _get_blocked_posts(cur, addr)
        blocked_users = _get_blocked_users(cur, addr)
        blocked_communities = _get_blocked_communities(cur, addr)
        blocked_communities_exact, blocked_community_prefixes = _split_blocked_communities(blocked_communities)
        persisted_seen: dict[str, int] = {}
        if addr and addr.lower() != "guest":
            try:
                persisted_seen = get_seen_map(addr)
            except Exception:
                logger.debug("bootstrap.view.seen_load.err addr=%s", addr[:12])

        if feed_name == "home":
            resp = _get_home_feed(
                cur,
                viewer=addr,
                limit=limit,
                page=1,
                blocked_posts=blocked_posts,
                blocked_users=blocked_users,
                allowed_tags=allowed_tags,
                sort_mode=sort_mode,
                blocked_communities=blocked_communities_exact,
                blocked_community_prefixes=blocked_community_prefixes,
                seen_posts=persisted_seen,
            )
        else:
            resp = _get_following_feed(
                cur,
                viewer=addr,
                limit=limit,
                page=1,
                blocked_posts=blocked_posts,
                blocked_users=blocked_users,
                allowed_tags=allowed_tags,
                sort_mode=sort_mode,
                blocked_communities=blocked_communities_exact,
                blocked_community_prefixes=blocked_community_prefixes,
                seen_posts=persisted_seen,
            )
        if resp.get("posts"):
            _enrich_media_meta(cur, resp["posts"])
            resp["posts"], _ = _filter_posts_for_lens(
                cur,
                resp["posts"],
                viewer=addr,
                requested_lens=lens,
                requested_team_id=team_id,
                scope=scope,
            )
            _resolve_effective_tags(cur, resp["posts"])
            resp["posts"] = _filter_posts_by_allowed_tags(
                resp["posts"],
                allowed_tags,
                rid=rid,
                context=f"bootstrap.view.feed.{feed_name}",
                viewer=addr,
            )
            _track_image_impressions(resp["posts"], rid, context=f"bootstrap.view.feed.{feed_name}")
        resp.pop("_timings", None)
        if guest_key is not None:
            _guest_feed_cache_put(guest_key, resp)
        return {"kind": "feed", "feed": feed_name, **resp}
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _build_community_bootstrap(address: str) -> dict:
    """Build required lens, quota, and renewal contracts from indexer state."""
    params = expect_params()
    with connect_db(timeout=10.0, busy_timeout_ms=15000) as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT community, mode, pinned_team_id
            FROM community_curation_preferences
            WHERE LOWER(owner)=LOWER(%s)
            ORDER BY community
            """,
            (address,),
        )
        preferences: dict[str, dict] = {}
        for community, mode, pinned_team_id in cur.fetchall():
            resolved = _resolve_curation_lens(cur, viewer=address, community=community)
            preferences[community] = {
                "stored_mode": int(mode),
                "stored_team_id": str(pinned_team_id) if pinned_team_id is not None else None,
                "effective_mode": int(resolved["effective_mode"]),
                "effective_team_id": (
                    str(resolved["effective_team_id"]) if resolved["effective_team_id"] is not None else None
                ),
            }
        cur.execute(
            """
            SELECT effective_paid, subscriber_quota_epoch, subscriber_quota_used,
                   renewal_next_attempt, renewal_last_attempt_epoch,
                   renewal_warning_expiry, renewal_warning_sent,
                   COALESCE(level, 0)
            FROM profiles
            WHERE LOWER(owner)=LOWER(%s)
            """,
            (address,),
        )
        row = cur.fetchone()
    if not row:
        return {
            "community_preferences": preferences,
            "daily_quota": None,
            "renewal_warning": None,
        }
    effective_paid = bool(row[0])
    quota_epoch = row[1]
    quota_used = row[2]
    user_level = int(row[7] or 0)
    tiers = params.get("tiers") or []
    if user_level == 0:
        tier_idx = 0
    elif user_level == 1:
        tier_idx = 1
    elif user_level >= 100:
        tier_idx = 2
    else:
        raise RuntimeError(f"unknown profile level for daily relay quota: {user_level}")
    if tier_idx >= len(tiers) or tiers[tier_idx] is None:
        raise RuntimeError(f"chain params missing tier {tier_idx} for daily relay limit")
    if "max_daily_relays" not in tiers[tier_idx]:
        raise RuntimeError(f"tier {tier_idx} missing max_daily_relays")
    limit = int(tiers[tier_idx]["max_daily_relays"])
    uses_relay = limit > 0
    if uses_relay and (quota_epoch is None or quota_used is None):
        raise RuntimeError("relay-quota profile is missing subscriber quota projection")
    daily_quota = None
    if uses_relay:
        if limit < 1:
            raise RuntimeError("relay-quota tier has max_daily_relays < 1")
        used = int(quota_used)
        if used > limit:
            raise RuntimeError("subscriber quota projection exceeds chain limit")
        daily_quota = {
            "epoch": int(quota_epoch),
            "used": used,
            "limit": limit,
            "remaining": limit - used,
            "reset_at": (int(quota_epoch) + 1) * 86400,
        }
    renewal_values = row[3:7]
    renewal_warning = None
    # Appointed admins (and free users) have no paid subscription. Their renewal
    # columns may still be projected as zeros after a quota backfill — never
    # surface that as a "subscription expires" warning (epoch → 12/31/1969).
    if effective_paid:
        if any(value is None for value in renewal_values):
            raise RuntimeError("paid profile is missing renewal projection")
        expiry = int(row[5])
        if expiry <= 0:
            raise RuntimeError(f"paid profile has non-positive renewal expiry: {expiry}")
        renewal_warning = {
            "expiry": expiry,
            "next_attempt": int(row[3]),
            "last_attempt_epoch": int(row[4]),
            "warning_sent": bool(row[6]),
        }
    logger.debug(
        "[renewal] bootstrap address=%s paid=%s level=%s warning=%s",
        address[:12],
        effective_paid,
        user_level,
        renewal_warning["expiry"] if renewal_warning is not None else None,
    )
    return {
        "community_preferences": preferences,
        "daily_quota": daily_quota,
        "renewal_warning": renewal_warning,
    }


@public_bp.route("/api/bootstrap")
def bootstrap():
    """Combined first-paint endpoint.

    Returns node_config + chain_config (always) plus, when ?address=<addr> is
    provided, user_status, user_followed, user_blocked, and rewards_summary.
    Optional `view=` embeds the initial screen payload
    (feed / thread / inbox) so cold start is a single round trip.
    """
    rid = next_request_id()
    address = (request.args.get("address") or "").strip() or None
    view_raw = request.args.get("view", default=None, type=str)
    by_raw = (request.args.get("by", default="", type=str) or "").strip().lower()
    limit = request.args.get("limit", 15, type=int)
    log_event(rid, "bootstrap.begin", address=address, view=view_raw)

    # 503 while catching up unless both node_config and chain_config are cached
    # (anonymous warm-cache path must not return chain_config:null).
    if _is_catching_up() and (address or _NODE_CONFIG_CACHE is None or _CHAIN_CONFIG_CACHE is None):
        return api_error_code("node_catching_up", 503)

    # Static sections must survive user-section faults. Login clears nothing useful
    # when node_config is present; a missing relay-quota projection used to 503
    # the whole payload and leave the SPA on an endless skeleton + crash.
    try:
        allowed_tags = _viewer_allowed_tags(address)
        resp: Dict[str, Any] = {
            "node_config": _build_node_config(),
            "chain_config": _build_chain_config(),
            "user_status": None,
            "user_followed": None,
            "user_blocked": None,
            "rewards_summary": None,
            "community_preferences": {},
            "daily_quota": None,
            "renewal_warning": None,
            "view": None,
        }
    except Exception as e:
        log_event(rid, "bootstrap.required.err", error=str(e))
        return api_error_code("indexer_unavailable", 503)

    try:
        resp["view"] = _build_bootstrap_view(view_raw, address, by_raw, allowed_tags, limit, rid)
        if address:
            resp["user_status"] = _build_user_status(address)
            resp["user_followed"] = _build_user_followed(address)
            resp["user_blocked"] = _build_user_blocked(address)
            community_bootstrap = _build_community_bootstrap(address)
            resp.update(community_bootstrap)
    except Exception as e:
        # Keep node_config/chain_config. Wipe any partial user fields so the
        # client never caches user_status without daily_quota/renewal_warning.
        log_event(rid, "bootstrap.user.err", error=str(e), address=address)
        resp["user_status"] = None
        resp["user_followed"] = None
        resp["user_blocked"] = None
        resp["rewards_summary"] = None
        resp["community_preferences"] = {}
        resp["daily_quota"] = None
        resp["renewal_warning"] = None
        resp["view"] = None

    log_event(
        rid,
        "bootstrap.ok",
        sections=[k for k, v in resp.items() if v is not None],
        view_kind=(resp["view"] or {}).get("kind") if isinstance(resp.get("view"), dict) else None,
        user_sections_ok=bool(address is None or resp.get("user_status") is not None),
    )
    return jsonify(resp)


@public_bp.route("/api/get_peers")
def get_peers():
    """Every active node's site, for the Sites list on /network.

    The active set from the chain, not this node's P2P connections. Both were
    called "peers", but only one of them answers the question the page is
    actually asking: a node you can open in a browser. A P2P connection may be a
    validator with no web presence, and the same fleet member could appear twice
    under two addresses, while a node that is genuinely part of the network but
    not currently gossiping with this one never appeared at all.

    Every reachable node, http included. Requiring https here conflated being
    listed with being trusted to receive a credential: a node reached by IP can
    hold no certificate, so it served plain http and was hidden, and this page
    reported two servers while four were running. The stats fan-out still
    forwards the admin proof only to destinations it can authenticate — see
    `fleet.authenticated_node_sites`.

    A node whose operator published no address at all is found from this node's
    own P2P connections and listed once it proves itself, so choosing a nickname
    no longer makes a running node invisible.

    `verified` says the address answered a signed challenge as the validator it
    is listed under. An unverified entry is a claim the chain carries but the
    address has not backed, and the page says so rather than presenting the two
    as equivalent.
    """
    try:
        return jsonify(
            {
                "peers": [
                    {
                        "ip": "",
                        "moniker": site.url,
                        "site": site.url,
                        "operator_address": site.operator_address,
                        "verified": site.verified,
                    }
                    for site in active_node_entries()
                ]
            }
        )
    except Exception as e:
        return safe_error(e)


@public_bp.route("/api/node_identity")
def node_identity():
    """Prove this node is the validator it claims, at the address the caller dialed.

    Public and unauthenticated on purpose: it is how any node, or anyone at all,
    checks that a site on /network belongs to the validator named beside it. The
    response commits to a caller-chosen nonce and origin, so it is worthless
    replayed at another address or at another time.

    See `node_identity` for why signing a caller-supplied origin is safe: both
    inputs are validated against narrow grammars first, and the framed payload
    cannot be read as a transaction.
    """
    rid = next_request_id()
    try:
        doc = build_local_identity(
            request.args.get("origin", default="", type=str),
            request.args.get("nonce", default="", type=str),
        )
    except ValueError as e:
        log_event(rid, "node_identity.bad_challenge", error=str(e))
        return api_error_code("invalid_identity_challenge", 400)
    except Exception as e:
        log_event(rid, "node_identity.err", error=str(e))
        return safe_error(e)
    log_event(rid, "node_identity.ok", origin=doc["origin"])
    return jsonify(doc)


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
                f"SELECT LOWER(username), owner FROM profiles WHERE LOWER(username) IN ({ph}) AND deleted_at IS NULL",
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
            return jsonify({"error": "username required"}), 400
        username = single.strip()
        cur.execute(
            "SELECT owner FROM profiles WHERE LOWER(username)=LOWER(%s) AND deleted_at IS NULL LIMIT 1", (username,)
        )
        row = cur.fetchone()
        conn.close()
        if row and row[0]:
            return jsonify({"exists": True, "address": row[0], "username": username})
        return jsonify({"exists": False, "address": None, "username": username})
    except Exception as e:
        return safe_error(e)


@public_bp.route("/api/search_username")
def username_search():
    """Lightweight username search for @mention autocomplete.

    GET: ?q=<query>&limit=8
    Returns: { results: [{username, address}, ...] }
    """
    q = (request.args.get("q") or "").strip().lower()
    limit = min(max(1, request.args.get("limit", 8, type=int)), 20)
    search_q = q[5:] if q.startswith("anon-") else q
    if not search_q:
        search_q = q

    if not q:
        return jsonify({"results": []})

    # This was the one search path that interpolated the query raw into its LIKE
    # patterns, while every sibling escaped first. Not injection — psycopg
    # parameterizes correctly — but wildcard injection: `%` matched every profile
    # and forced the CTE to evaluate LOWER() and a conditional SUBSTRING over the
    # whole table, `_` enabled enumeration by structure, and a trailing backslash
    # produced an unauthenticated 500.
    q_like = _escape_like(q)
    search_q_like = _escape_like(search_q)

    try:
        conn = connect_db(timeout=5.0, busy_timeout_ms=5000)
        cur = conn.cursor()
        cur.execute(
            """
            WITH searchable_profiles AS (
                SELECT
                    username,
                    owner,
                    LOWER(username) AS username_lc,
                    CASE
                        WHEN LOWER(username) LIKE 'anon-%%' THEN SUBSTRING(LOWER(username) FROM 6)
                        ELSE LOWER(username)
                    END AS search_username
                FROM profiles
                WHERE username != '' AND deleted_at IS NULL
            )
            SELECT username, owner
            FROM searchable_profiles
            WHERE username_lc LIKE %s OR search_username LIKE %s
            ORDER BY
                CASE
                    WHEN search_username LIKE %s THEN 0
                    WHEN username_lc LIKE %s THEN 0
                    ELSE 1
                END,
                username_lc
            LIMIT %s
            """,
            (
                f"%{q_like}%",
                f"%{search_q_like}%",
                f"{search_q_like}%",
                f"{q_like}%",
                limit,
            ),
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
            return jsonify({"error": "address required"}), 400
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
    page = _clamp_page(page)
    offset = (page - 1) * limit

    try:
        conn = connect_db(timeout=10.0, busy_timeout_ms=15000)
        cur = conn.cursor()

        username_filter = "WHERE deleted_at IS NULL"
        if has_username:
            username_filter = "WHERE username IS NOT NULL AND username != '' AND deleted_at IS NULL"

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


@public_bp.route("/api/search")
def search():
    """
    Unified search endpoint.
    - @username: Search users by username, return user + their posts
    - #community: Search communities by prefix
    - Otherwise: Search communities, users, and posts with substring matching

    Query Parameters:
      - q (required): Search query
      - type: Filter to 'communities', 'users', or 'posts' (for Load More)
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
    try:
        lens, team_id, scope = _lens_request_args()
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    allowed_tags = _viewer_allowed_tags(viewer)

    # Detect search type from prefix
    if q_raw.startswith("@"):
        search_type = "user"
        query = q_raw[1:].strip()
    elif q_raw.startswith("#"):
        search_type = "community"
        query = q_raw[1:].strip()
    else:
        search_type = "general"
        query = q_raw

    if not query:
        return jsonify(
            {
                "query": q_raw,
                "search_type": search_type,
                "communities": [],
                "users": [],
                "posts": [],
                "has_more_communities": False,
                "has_more_users": False,
                "has_more_posts": False,
            }
        )

    try:
        conn = connect_db(timeout=10.0, busy_timeout_ms=15000)
        cur = conn.cursor()
        blocked_posts = _get_blocked_posts(cur, viewer) if viewer else set()
        blocked_users = _get_blocked_users(cur, viewer) if viewer else set()
        blocked_communities = _get_blocked_communities(cur, viewer) if viewer else set()
        blocked_communities_exact, blocked_community_prefixes = _split_blocked_communities(blocked_communities)
        deleted_clause = _deleted_filter()
        deleted_bare = _deleted_filter_bare()

        result = {
            "query": q_raw,
            "search_type": search_type,
            "communities": [],
            "users": [],
            "posts": [],
            "has_more_communities": False,
            "has_more_users": False,
            "has_more_posts": False,
        }

        # Sanitize query for LIKE matching (escape special chars)
        query_lower = query.lower()
        like_query = _escape_like(query_lower)

        # ========== USER SEARCH (@username) ==========
        if search_type == "user":
            # Find user by username (exact or prefix match) with post count
            cur.execute(
                f"""
                SELECT pr.owner, COALESCE(pr.username, ''), pr.level, pr.created_at,
                       (SELECT COUNT(1) FROM posts p WHERE LOWER(p.owner) = LOWER(pr.owner) 
                        AND COALESCE(p.target, '') = '' {deleted_clause}) as post_count
                FROM profiles pr
                WHERE LOWER(pr.username) LIKE %s AND pr.deleted_at IS NULL
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
                        "user_is_new": _is_new_user(int(created_at or 0)),
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
                    SELECT p.txhash, p.owner, p.created_at, p.community, p.title, p.content,
                           COALESCE(pr.username, '') as username,
                           COALESCE(p.target, '') as target,
                           COALESCE(p.tag, '') as tag,
                           COALESCE(p.thumbnail_url, '') as thumbnail,
                           COALESCE(pr.level, 0) as author_level,
                           COALESCE(p.media, '[]') as media,
                      COALESCE(pr.created_at, 0) as author_created_at,
                      COALESCE(p.relayer, '') as relayer
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
                    cur,
                    post_rows,
                    blocked_posts,
                    blocked_users,
                    viewer,
                    deleted_bare,
                    blocked_communities_exact,
                    blocked_community_prefixes,
                    allowed_tags=allowed_tags,
                )
                result["posts"] = posts

        # ========== COMMUNITY SEARCH (#community) ==========
        elif search_type == "community":
            p = expect_params()
            min_community = int(p["min_community_size"])
            max_community = int(p["max_community_size"])

            cur.execute(
                f"""
                WITH community_base AS (
                    SELECT LOWER(TRIM(p.community)) AS community,
                           COUNT(1) AS post_count
                    FROM posts p
                    WHERE COALESCE(p.target, '') = ''
                      AND p.community IS NOT NULL
                      AND LENGTH(TRIM(p.community)) >= %s
                      AND LENGTH(TRIM(p.community)) <= %s
                      AND LOWER(p.community) LIKE %s
                      {deleted_clause}
                    GROUP BY LOWER(TRIM(p.community))
                    ORDER BY post_count DESC, community ASC
                    LIMIT %s
                    OFFSET %s
                )
                SELECT
                    tb.community,
                    tb.post_count,
                    COALESCE(tcs.dominant_tag, '') AS dominant_tag,
                    COALESCE(tcs.dominant_ratio, 0) AS dominant_ratio
                FROM community_base tb
                LEFT JOIN community_content_stats tcs ON LOWER(tcs.community) = tb.community
                """,
                (min_community, max_community, f"{like_query}%", limit + 1, offset),
            )
            community_rows = cur.fetchall()
            has_more_communities = len(community_rows) > limit
            community_rows = community_rows[:limit]

            communities = []
            community_rows = [
                row
                for row in community_rows
                if not _community_is_blocked(
                    (row[0] or "").lower(), blocked_communities_exact, blocked_community_prefixes
                )
            ]
            community_list = [row[0] for row in community_rows]
            stats = _compute_dominant_flags(cur, community_list) if community_list else {}

            for row in community_rows:
                community, post_count, dominant_tag, dominant_ratio = row
                stat = stats.get(community, {}) if stats else {}
                dom_tag = _normalize_api_tag(stat.get("dominant_tag") or "")
                dom_ratio = float(stat.get("dominant_ratio") or 0)
                if dom_tag and dom_tag not in allowed_tags:
                    continue
                communities.append(
                    {
                        "community": community,
                        "post_count": int(post_count or 0),
                        "dominant_tag": dom_tag or None,
                        "dominant_ratio": dom_ratio,
                    }
                )

            result["communities"] = communities
            result["has_more_communities"] = has_more_communities

        # ========== GENERAL SEARCH ==========
        else:
            # Search communities (if not filtering or filtering to communities)
            if not search_type_filter or search_type_filter == "communities":
                p = expect_params()
                min_community = int(p["min_community_size"])
                max_community = int(p["max_community_size"])

                cur.execute(
                    f"""
                    WITH community_base AS (
                        SELECT LOWER(TRIM(p.community)) AS community,
                               COUNT(1) AS post_count
                        FROM posts p
                        WHERE COALESCE(p.target, '') = ''
                          AND p.community IS NOT NULL
                          AND LENGTH(TRIM(p.community)) >= %s
                          AND LENGTH(TRIM(p.community)) <= %s
                          AND LOWER(p.community) LIKE %s
                          {deleted_clause}
                        GROUP BY LOWER(TRIM(p.community))
                        ORDER BY post_count DESC, community ASC
                        LIMIT %s
                        OFFSET %s
                    )
                    SELECT
                        tb.community,
                        tb.post_count,
                        COALESCE(tcs.dominant_tag, '') AS dominant_tag,
                        COALESCE(tcs.dominant_ratio, 0) AS dominant_ratio
                    FROM community_base tb
                    LEFT JOIN community_content_stats tcs ON LOWER(tcs.community) = tb.community
                    """,
                    (min_community, max_community, f"%{like_query}%", limit + 1, offset),
                )
                community_rows = cur.fetchall()
                has_more_communities = len(community_rows) > limit
                community_rows = community_rows[:limit]

                communities = []
                community_rows = [
                    row
                    for row in community_rows
                    if not _community_is_blocked(
                        (row[0] or "").lower(), blocked_communities_exact, blocked_community_prefixes
                    )
                ]
                community_list = [row[0] for row in community_rows]
                stats = _compute_dominant_flags(cur, community_list) if community_list else {}

                for row in community_rows:
                    community, post_count, dominant_tag, dominant_ratio = row
                    stat = stats.get(community, {}) if stats else {}
                    dom_tag = _normalize_api_tag(stat.get("dominant_tag") or "")
                    dom_ratio = float(stat.get("dominant_ratio") or 0)
                    if dom_tag and dom_tag not in allowed_tags:
                        continue
                    communities.append(
                        {
                            "community": community,
                            "post_count": int(post_count or 0),
                            "dominant_tag": dom_tag or None,
                            "dominant_ratio": dom_ratio,
                        }
                    )

                result["communities"] = communities
                result["has_more_communities"] = has_more_communities

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
                      AND pr.deleted_at IS NULL
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
                            "user_is_new": _is_new_user(int(created_at or 0)),
                            "post_count": int(post_count or 0),
                        }
                    )

                result["users"] = users
                result["has_more_users"] = has_more_users

            # Search posts (if not filtering or filtering to posts)
            if not search_type_filter or search_type_filter == "posts":
                cur.execute(
                    f"""
                    SELECT p.txhash, p.owner, p.created_at, p.community, p.title, p.content,
                           COALESCE(pr.username, '') as username,
                           COALESCE(p.target, '') as target,
                           COALESCE(p.tag, '') as tag,
                           COALESCE(p.thumbnail_url, '') as thumbnail,
                           COALESCE(pr.level, 0) as author_level,
                           COALESCE(p.media, '[]') as media,
                           COALESCE(pr.created_at, 0) as author_created_at,
                           COALESCE(p.relayer, '') as relayer
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
                    cur,
                    post_rows,
                    blocked_posts,
                    blocked_users,
                    viewer,
                    deleted_bare,
                    blocked_communities_exact,
                    blocked_community_prefixes,
                    allowed_tags=allowed_tags,
                )
                result["posts"] = posts
                result["has_more_posts"] = has_more_posts

        if result["posts"]:
            result["posts"], _ = _filter_posts_for_lens(
                cur,
                result["posts"],
                viewer=viewer,
                requested_lens=lens,
                requested_team_id=team_id,
                scope=scope,
            )
            _resolve_effective_tags(cur, result["posts"])
            result["posts"] = _filter_posts_by_allowed_tags(
                result["posts"],
                allowed_tags,
                rid=next_request_id(),
                context="search.posts",
                viewer=viewer,
            )
        conn.close()
        return jsonify(result)
    except Exception as e:
        return safe_error(e)


def _format_search_posts(
    cur,
    rows,
    blocked_posts,
    blocked_users,
    viewer,
    deleted_bare,
    blocked_communities=None,
    blocked_community_prefixes=None,
    allowed_tags=None,
):
    """Format post rows for search results with vote counts."""
    if allowed_tags is None:
        allowed_tags = {"sensitive"}
    viewer_lower = (viewer or "").strip().lower()
    # Filter blocked posts, users, communities, and disallowed tags
    filtered = []
    for r in rows:
        txhash = (r[0] or "").lower()
        owner = (r[1] or "").lower()
        community = (r[3] or "").strip().lower() if len(r) > 3 else ""
        is_own = viewer_lower and owner == viewer_lower
        if not is_own and (txhash in blocked_posts or owner in blocked_users):
            continue
        if not is_own and _community_is_blocked(
            community, blocked_communities or set(), blocked_community_prefixes or tuple()
        ):
            continue
        # Tags are filtered by the caller once the lens has resolved the
        # effective tag; the author's own tag is not the final answer.
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

    # Load awards for all posts
    _, award_details = _load_award_aggregates(cur, post_ids, blocked_users) if post_ids else ({}, {})

    posts = []
    for row in filtered:
        import json as _json

        author_created_at = 0
        if len(row) >= 14:
            (
                txhash,
                owner,
                ts,
                community,
                title,
                content,
                username,
                target,
                tag,
                thumbnail,
                author_level,
                media_raw,
                author_created_at,
                relayer,
            ) = row[:14]
        elif len(row) >= 13:
            (
                txhash,
                owner,
                ts,
                community,
                title,
                content,
                username,
                target,
                tag,
                thumbnail,
                author_level,
                media_raw,
                author_created_at,
            ) = row[:13]
            relayer = ""
        elif len(row) >= 12:
            txhash, owner, ts, community, title, content, username, target, tag, thumbnail, author_level, media_raw = (
                row[:12]
            )
            relayer = ""
        else:
            txhash, owner, ts, community, title, content, username, target, tag, thumbnail, author_level = row
            media_raw = "[]"
            relayer = ""
        try:
            media_val = _json.loads(media_raw or "[]")
            if not isinstance(media_val, list):
                media_val = []
        except Exception:
            media_val = []
        pid = (txhash or "").lower()
        relayer_lower = (relayer or "").strip().lower()
        posts.append(
            {
                "post_id": pid,
                "user_id": owner,
                "username": username or None,
                "author_level": int(author_level) if author_level else 0,
                "author_is_new": _is_new_user(int(author_created_at or 0)),
                "timestamp": int(ts) if ts else None,
                "community": community,
                "title": title,
                "content": content,
                "tag": _normalize_api_tag(tag or ""),
                "thumbnail": thumbnail or "",
                "media": media_val,
                "media_meta": [],
                "relayer": relayer_lower,
                "points": vote_totals.get(pid, 0),
                "comments": comment_counts.get(pid, 0),
                "user_vote": user_votes.get(pid, 0),
                "user_weight": user_weight_map.get(pid, 0.0),
                "awards": award_details.get(pid, []),
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
    page = _clamp_page(page)
    offset = (page - 1) * limit
    community = request.args.get("community", default=None, type=str)
    # An outdated client sends `topic=`, so that is the param this rejects. It is
    # deliberately not `community=`, which is the live one every caller uses.
    if request.args.get("topic") is not None:
        log_event(rid, "get_posts.topic_retired", topic=request.args.get("topic"), page=page)
        return api_error_code("topic_retired")
    address = request.args.get("address", default="", type=str)
    try:
        lens, team_id, scope = _lens_request_args(community)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    # Parse allowed_tags: comma-separated list of tags the user wants to see.
    # Signed in, only 'sensitive' is allowed by default (adult, violence, gore,
    # death are hidden); signed out, nothing tagged is allowed at all.
    allowed_tags = _viewer_allowed_tags(address)

    # Feed mode and sort are pure request parsing, and a signed-out feed request
    # is answered from the shared guest cache before any database work:
    # connect_db is an unpooled connect, so opening it first would charge every
    # cache hit a full Postgres handshake.
    feed = (request.args.get("feed", default=None, type=str) or "").strip().lower()
    sort_mode = (request.args.get("by", default="", type=str) or "").strip().lower()
    if sort_mode and sort_mode not in ("magic", "newest"):
        return jsonify({"error": "unsupported sort mode", "sort_mode": sort_mode}), 400
    sort_mode = sort_mode or "magic"

    guest_key = (
        _guest_feed_cache_key(
            feed,
            sort_mode,
            page,
            limit,
            allowed_tags,
            viewer="guest",
            community=(community or "").strip().lower(),
            scope=scope,
            lens=lens,
            team_id=team_id,
        )
        if feed in ("home", "following") and _is_guest(address) and (scope == "legacy" or lens == "raw")
        else None
    )
    if guest_key is not None:
        cached = _guest_feed_cache_get(guest_key)
        if cached is not None:
            # Impressions are still counted per request; only the feed is shared.
            _track_image_impressions(cached.get("posts") or [], rid, context=f"get_posts.feed.{feed}.guest_cached")
            log_event(rid, "get_posts.guest_cache.hit", key=guest_key)
            return jsonify(cached)

    try:
        conn = connect_db(timeout=10.0, busy_timeout_ms=15000)
        cur = conn.cursor()

        _t_blocked = time.monotonic()
        blocked_posts = _get_blocked_posts(cur, address)
        blocked_users = _get_blocked_users(cur, address)
        blocked_communities = _get_blocked_communities(cur, address)
        blocked_communities_exact, blocked_community_prefixes = _split_blocked_communities(blocked_communities)
        blocked_ms = round((time.monotonic() - _t_blocked) * 1000, 2)

        deleted_clause = _deleted_filter()

        # ── Seen-posts: load persisted map for novelty scoring ────
        persisted_seen: dict[str, int] = {}
        _t_seen = time.monotonic()
        if address and address.lower() != "guest":
            try:
                persisted_seen = get_seen_map(address)
            except Exception:
                logger.debug("get_posts.seen_load.err addr=%s", address[:12])
        seen_ms = round((time.monotonic() - _t_seen) * 1000, 2)

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

            _t_feed = time.monotonic()
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
                    sort_mode=sort_mode,
                    blocked_communities=blocked_communities_exact,
                    blocked_community_prefixes=blocked_community_prefixes,
                    seen_posts=persisted_seen,
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
                    blocked_communities=blocked_communities_exact,
                    blocked_community_prefixes=blocked_community_prefixes,
                    seen_posts=persisted_seen,
                )
            feed_ms = round((time.monotonic() - _t_feed) * 1000, 2)

            enrich_ms = 0.0
            filter_ms = 0.0
            if resp.get("posts"):
                _t = time.monotonic()
                _enrich_media_meta(cur, resp["posts"])
                enrich_ms = round((time.monotonic() - _t) * 1000, 2)

                _t = time.monotonic()
                resp["posts"], _ = _filter_posts_for_lens(
                    cur,
                    resp["posts"],
                    viewer=address,
                    requested_lens=lens,
                    requested_team_id=team_id,
                    scope=scope,
                )
                _resolve_effective_tags(cur, resp["posts"])
                resp["posts"] = _filter_posts_by_allowed_tags(
                    resp["posts"],
                    allowed_tags,
                    rid=rid,
                    context=f"get_posts.feed.{feed or 'unknown'}",
                    viewer=address,
                )
                filter_ms = round((time.monotonic() - _t) * 1000, 2)
                _track_image_impressions(resp["posts"], rid, context=f"get_posts.feed.{feed or 'unknown'}")

            # Emit one structured line for slow feed requests so we can see
            # which step of the home-feed pipeline is dominating latency.
            inner = resp.pop("_timings", {}) or {}
            total_ms = round((time.monotonic() - t_start) * 1000, 2)
            if total_ms > 500:
                log_event(
                    rid,
                    "get_posts.timing",
                    feed=feed,
                    sort=sort_mode,
                    page=page,
                    limit=limit,
                    viewer=(address[:12] + "...") if address else "",
                    blocked_ms=blocked_ms,
                    seen_ms=seen_ms,
                    feed_ms=feed_ms,
                    enrich_ms=enrich_ms,
                    filter_ms=filter_ms,
                    total_ms=total_ms,
                    returned=len(resp.get("posts") or []),
                    **inner,
                )

            if guest_key is not None:
                _guest_feed_cache_put(guest_key, resp)

            conn.close()
            return jsonify(resp)

        # Blocked-community SQL clause (only applied for "all" / no community; explicit community visits are not filtered)
        bt_clause, bt_params = (
            ("", [])
            if (community and community != "all")
            else _blocked_communities_sql(blocked_communities_exact, blocked_community_prefixes, viewer=address)
        )

        # First, get total count for pagination
        t_count = time.monotonic()
        if community and community != "all":
            cur.execute(
                f"""
                SELECT COUNT(1)
                FROM posts p
                WHERE COALESCE(p.target, '') = '' AND LOWER(p.community) = LOWER(%s) AND LENGTH(COALESCE(p.title,'')) > 0 {deleted_clause}
                """,
                (community,),
            )
        else:
            cur.execute(
                f"""
                SELECT COUNT(1)
                FROM posts p
                WHERE COALESCE(p.target, '') = '' AND LENGTH(COALESCE(p.title,'')) > 0 {bt_clause} {deleted_clause}
                """,
                bt_params,
            )
        total = cur.fetchone()[0] or 0
        count_ms = (time.monotonic() - t_count) * 1000

        # Fetch candidate posts. For magic mode we must rank in Python using the same Magic scorer.
        # (Eligibility comes from the community filter; ranking is always via `_score_magic`.)
        max_candidates = min(max(500, limit * page * _seen_overfetch_factor(persisted_seen, 3)), MAX_CANDIDATE_POOL)
        order_clause = "ORDER BY p.created_at DESC"

        t_select = time.monotonic()
        if community and community != "all":
            cur.execute(
                f"""
                SELECT p.txhash,
                       p.owner,
                       p.created_at,
                       p.community,
                       p.title,
                       p.content,
                       COALESCE(p.tag, '') AS tag,
                       COALESCE(p.root_community, p.community, '') AS root_community,
                       COALESCE(p.root_post_id, p.txhash, '') AS root_post_id,
                       COALESCE(pr.username, '') as username,
                       COALESCE(p.edited_at, 0) as edited_at,
                      COALESCE(p.thumbnail_url, '') as thumbnail,
                      COALESCE(pr.level, 0) as author_level,
                      COALESCE(p.media, '[]') as media,
                      COALESCE(pr.created_at, 0) as author_created_at,
                      COALESCE(p.relayer, '') as relayer
                FROM posts p
                LEFT JOIN profiles pr ON pr.owner = p.owner
                WHERE COALESCE(p.target, '') = '' AND LOWER(p.community) = LOWER(%s) AND LENGTH(COALESCE(p.title,'')) > 0 {deleted_clause}
                {order_clause}
                LIMIT %s
                """,
                (community, max_candidates),
            )
        else:
            cur.execute(
                f"""
                SELECT p.txhash,
                       p.owner,
                       p.created_at,
                       p.community,
                       p.title,
                       p.content,
                       COALESCE(p.tag, '') AS tag,
                       COALESCE(p.root_community, p.community, '') AS root_community,
                       COALESCE(p.root_post_id, p.txhash, '') AS root_post_id,
                       COALESCE(pr.username, '') as username,
                       COALESCE(p.edited_at, 0) as edited_at,
                       COALESCE(p.thumbnail_url, '') as thumbnail,
                       COALESCE(pr.level, 0) as author_level,
                       COALESCE(p.media, '[]') as media,
                       COALESCE(pr.created_at, 0) as author_created_at,
                       COALESCE(p.relayer, '') as relayer
                FROM posts p
                LEFT JOIN profiles pr ON pr.owner = p.owner
                WHERE COALESCE(p.target, '') = '' AND LENGTH(COALESCE(p.title,'')) > 0 {bt_clause} {deleted_clause}
                {order_clause}
                LIMIT %s
                """,
                bt_params + [max_candidates],
            )
        rows = cur.fetchall()
        select_ms = (time.monotonic() - t_select) * 1000

        # Filter blocked posts, posts from blocked users, and blocked communities
        # Own posts always pass through (never hidden by agent blocks)
        address_lower = (address or "").strip().lower()
        rows = [
            r
            for r in rows
            if (address_lower and (r[1] or "").lower() == address_lower)
            or (
                (r[0] or "").lower() not in blocked_posts
                and (r[1] or "").lower() not in blocked_users
                and not _community_is_blocked(
                    (r[3] or "").strip().lower(), blocked_communities_exact, blocked_community_prefixes
                )
            )
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
            post = _row_to_post(
                row,
                blocked_posts,
                blocked_users,
                seen,
                blocked_communities_exact,
                blocked_community_prefixes,
                viewer=address,
            )
            if not post:
                continue
            post["_source"] = "community" if (community and community != "all") else "all"
            candidates.append(post)

        # Attach feed metadata for community/global feeds.
        community_lower = (community or "").strip().lower()
        is_global_community_feed = (not community_lower) or (community_lower == "all")
        community_feed_type = "all" if is_global_community_feed else "community"

        if sort_mode == "magic":
            # Rank via the same Magic scorer (no prefs in community feeds, P=0).
            from similarity import get_or_compute_similarities

            address_lower = (address or "").strip().lower()
            if address_lower and address_lower != "guest":
                similar_users = get_or_compute_similarities(cur, address_lower)
                sim_lookup = {u[0]: u[1] for u in similar_users}
            else:
                sim_lookup = {}
            similar_addrs = set(sim_lookup.keys())

            post_ids = [p["post_id"] for p in candidates]
            similar_upvotes, _ = _load_similar_user_upvotes(cur, post_ids, similar_addrs)
            unique_commenters = _load_unique_commenter_counts(cur, post_ids, blocked_posts, blocked_users)
            unique_awarders, award_details = _load_award_aggregates(cur, post_ids, blocked_users)
            community_prefs: dict[str, float] = {}
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
                    community_prefs,
                    author_prefs,
                    now_ts,
                    False,
                    unique_awarders,
                    viewer=address_lower,
                    seen_posts=persisted_seen,
                    user_votes=user_votes,
                )
                if should_hide:
                    continue
                pid = post["post_id"]
                post["_score"] = score
                post["feed_debug"] = debug
                post["points"] = float(vote_totals.get(pid, 0.0) or 0.0)
                post["comments"] = int(comment_counts.get(pid, 0) or 0)
                post["unique_commenters"] = int(unique_commenters.get(pid, 0) or 0)
                post["awards"] = award_details.get(pid, [])
                post["children"] = []
                post["feed_type"] = community_feed_type
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
            # newest: pure chronological
            candidates = _drop_viewer_downvotes(
                candidates, user_votes, context=f"community.newest.{community_feed_type}"
            )
            for c in candidates:
                c["_N"] = 1.0
                c["_seen_count"] = 0

            start = (page - 1) * limit
            end = start + limit
            page_posts = candidates[start:end] if start < len(candidates) else []
            page_pids = [p["post_id"] for p in page_posts]
            _, award_details = _load_award_aggregates(cur, page_pids, blocked_users)
            result = []
            for post in page_posts:
                pid = post["post_id"]
                sc = post.pop("_seen_count", 0)
                n_val = post.pop("_N", 1.0)
                reason = "Newest"
                if sc > 0:
                    reason += " · You've seen this before"
                post["points"] = float(vote_totals.get(pid, 0.0) or 0.0)
                post["comments"] = int(comment_counts.get(pid, 0) or 0)
                post["awards"] = award_details.get(pid, [])
                post["children"] = []
                post["feed_type"] = community_feed_type
                post["feed_bucket"] = "newest"
                post["user_vote"] = user_votes.get(pid, 0)
                post["user_weight"] = user_weight_map.get(pid, 0.0)
                post["feed_debug"] = {
                    "bucket": "newest",
                    "reason": reason,
                    "N": round(n_val, 4),
                    "seen_count": sc,
                }
                result.append(post)

        if result:
            _enrich_media_meta(cur, result)
            result, _ = _filter_posts_for_lens(
                cur,
                result,
                viewer=address,
                requested_lens=lens,
                requested_team_id=team_id,
                scope=scope,
            )
            _resolve_effective_tags(cur, result)
            result = _filter_posts_by_allowed_tags(
                result,
                allowed_tags,
                rid=rid,
                context=f"get_posts.community.{community or 'all'}",
                viewer=address,
            )
            _track_image_impressions(result, rid, context=f"get_posts.community.{community or 'all'}")

        has_more = len(result) >= limit and (page * limit) < total
        resp = {"posts": result, "total": total, "page": page, "limit": limit, "has_more": has_more}
        total_ms = (time.monotonic() - t_start) * 1000
        if max(total_ms, count_ms, select_ms) > 2000:
            log_event(
                rid,
                "get_posts.slow",
                community=community or "all",
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
    rid = next_request_id()
    owner = request.args.get("owner", type=str)
    viewer = request.args.get("address", default="", type=str)
    try:
        lens, team_id, scope = _lens_request_args()
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    limit = request.args.get("limit", 10, type=int)
    page = request.args.get("page", 1, type=int)
    post_type = request.args.get("type", default="", type=str)
    limit = min(max(1, limit), 50)
    page = _clamp_page(page)
    offset = (page - 1) * limit

    allowed_tags = _viewer_allowed_tags(viewer)
    if not allowed_tags:
        log_event(rid, "get_user_posts.allowed_tags.empty", owner=owner[:12] if owner else None)
    if post_type == "comments":
        try:
            logging.getLogger(__name__).debug(
                "get_user_posts comment tag filter active rid=%s allowed_tags=%s",
                rid,
                sorted(allowed_tags),
            )
        except Exception:
            pass

    if not owner:
        return jsonify({"error": "owner required"}), 400

    try:
        conn = connect_db(timeout=10.0, busy_timeout_ms=15000)
        cur = conn.cursor()
        blocked_posts = _get_blocked_posts(cur, viewer)
        blocked_users = _get_blocked_users(cur, viewer)
        blocked_communities = _get_blocked_communities(cur, viewer)
        blocked_communities_exact, blocked_community_prefixes = _split_blocked_communities(blocked_communities)

        deleted_clause = _deleted_filter()

        type_filter = ""
        if post_type == "submissions":
            type_filter = "AND COALESCE(p.target, '') = ''"
        elif post_type == "comments":
            type_filter = "AND COALESCE(p.target, '') != ''"

        cur.execute(
            f"""
            SELECT p.txhash, p.owner, p.created_at, p.community, p.title, p.content,
                   COALESCE(pr.username, '') as username,
                   COALESCE(p.target, '') as target,
                   (p.edited_at IS NOT NULL) as edited,
                   COALESCE(p.edited_at, 0) as edited_at,
                   COALESCE(p.thumbnail_url, '') as thumbnail,
                   COALESCE(pr.level, 0) as author_level,
                   COALESCE(p.media, '[]') as media,
                   COALESCE(pr.created_at, 0) as author_created_at,
                   COALESCE(p.relayer, '') as relayer,
                   COALESCE(p.tag, '') as tag,
                   COALESCE(p.root_post_id, '') as root_post_id
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
        viewer_lower = (viewer or "").strip().lower()
        rows = [
            r
            for r in rows
            if (viewer_lower and (r[1] or "").lower() == viewer_lower)
            or (
                (r[0] or "").lower() not in blocked_posts
                and (r[1] or "").lower() not in blocked_users
                and not _community_is_blocked(
                    (r[3] or "").strip().lower(), blocked_communities_exact, blocked_community_prefixes
                )
            )
        ]
        root_tag_map: dict[str, str] = {}
        comment_root_ids = {
            (r[16] or "").strip().lower()
            for r in rows
            if len(r) > 16 and (r[7] or "").strip() and (r[16] or "").strip()
        }
        if comment_root_ids:
            ph = ",".join(["%s"] * len(comment_root_ids))
            cur.execute(
                f"SELECT LOWER(txhash), COALESCE(tag, ''), LOWER(COALESCE(community, '')) "
                f"FROM posts WHERE LOWER(txhash) IN ({ph})",
                list(comment_root_ids),
            )
            root_posts = [
                {"post_id": pid, "tag": _normalize_api_tag(tag or ""), "community": community}
                for pid, tag, community in cur.fetchall()
            ]
            if root_posts:
                # A comment inherits its root's tag, so the root has to be
                # resolved through the lens too or an override on the root would
                # not reach its replies.
                _resolve_effective_tags(
                    cur,
                    root_posts,
                    viewer=viewer,
                    requested_lens=lens,
                    requested_team_id=team_id,
                )
                root_tag_map = {p["post_id"]: p.get("tag", "") or "" for p in root_posts}
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
            author_created_at = 0
            tag = ""
            root_post_id = ""
            if len(row) >= 17:
                (
                    txhash,
                    owner_addr,
                    ts,
                    community,
                    title,
                    content,
                    uname,
                    target,
                    edited,
                    edited_at,
                    thumbnail,
                    author_level,
                    media_raw,
                    author_created_at,
                    relayer,
                    tag,
                    root_post_id,
                ) = row[:17]
            elif len(row) >= 16:
                (
                    txhash,
                    owner_addr,
                    ts,
                    community,
                    title,
                    content,
                    uname,
                    target,
                    edited,
                    edited_at,
                    thumbnail,
                    author_level,
                    media_raw,
                    author_created_at,
                    relayer,
                    tag,
                ) = row[:16]
            elif len(row) >= 15:
                (
                    txhash,
                    owner_addr,
                    ts,
                    community,
                    title,
                    content,
                    uname,
                    target,
                    edited,
                    edited_at,
                    thumbnail,
                    author_level,
                    media_raw,
                    author_created_at,
                    relayer,
                ) = row[:15]
            elif len(row) >= 14:
                (
                    txhash,
                    owner_addr,
                    ts,
                    community,
                    title,
                    content,
                    uname,
                    target,
                    edited,
                    edited_at,
                    thumbnail,
                    author_level,
                    media_raw,
                    author_created_at,
                ) = row[:14]
                relayer = ""
            elif len(row) >= 13:
                (
                    txhash,
                    owner_addr,
                    ts,
                    community,
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
                relayer = ""
            elif len(row) >= 12:
                (
                    txhash,
                    owner_addr,
                    ts,
                    community,
                    title,
                    content,
                    uname,
                    target,
                    edited,
                    edited_at,
                    thumbnail,
                    author_level,
                ) = row[:12]
                relayer = ""
            else:
                txhash, owner_addr, ts, community, title, content, uname, target = row[:8]
                edited, edited_at = 0, 0
                thumbnail = ""
                author_level = 0
                relayer = ""
            try:
                media_val = _json.loads(media_raw or "[]")
                if not isinstance(media_val, list):
                    media_val = []
            except Exception:
                media_val = []
            pid = (txhash or "").lower()
            relayer_lower = (relayer or "").strip().lower()
            root_post_id_lower = (root_post_id or "").strip().lower()
            result.append(
                {
                    "post_id": pid,
                    "_root_post_id": root_post_id_lower,
                    "user_id": owner_addr,
                    "username": uname,
                    "author_level": int(author_level) if author_level else 0,
                    "author_is_new": _is_new_user(int(author_created_at or 0)),
                    "timestamp": int(ts) if ts is not None else None,
                    "community": community,
                    "title": title,
                    "content": content,
                    "tag": _normalize_api_tag(tag or ""),
                    "target": target,
                    "edited": bool(edited_at),
                    "edited_at": int(edited_at or 0),
                    "thumbnail": thumbnail,
                    "media": media_val,
                    "media_meta": [],
                    "relayer": relayer_lower,
                    "points": vote_totals.get(pid, 0),
                    "comments": comment_counts.get(pid, 0),
                    "user_vote": user_votes.get(pid, 0),
                    "user_weight": user_weight_map.get(pid, 0.0),
                }
            )
        if result:
            _enrich_media_meta(cur, result)
            result, _ = _filter_posts_for_lens(
                cur,
                result,
                viewer=viewer,
                requested_lens=lens,
                requested_team_id=team_id,
                scope=scope,
            )
            _resolve_effective_tags(cur, result)
            result = _filter_user_posts_by_allowed_tags(
                result,
                allowed_tags,
                root_tag_map,
                rid=rid,
                context=f"get_user_posts.{post_type or 'all'}",
                viewer=viewer,
            )
            _track_image_impressions(result, rid, context=f"get_user_posts.{post_type or 'all'}")
        conn.close()
        has_more = len(result) >= limit and (page * limit) < total
        resp = {"posts": result, "page": page, "limit": limit, "has_more": has_more, "total": total}
        return jsonify(_inject_balance(resp, viewer))
    except Exception as e:
        return safe_error(e)


@public_bp.route("/api/get_recent_content")
def get_recent_content():
    """Return recent non-deleted posts and comments in one chronological stream.

    Designed for external Mirage bots that need to scan recent public content
    without walking get_posts plus get_comments trees. Raw output: no viewer
    filtering, agent overlays, ranking, vote/comment aggregation, or media
    enrichment.
    """
    rid = next_request_id()
    try:
        limit = request.args.get("limit", default=100, type=int)
        if limit is None:
            limit = 100
        limit = min(max(1, limit), 500)

        before = request.args.get("before", default=None, type=int)
        before_id = (request.args.get("before_id", default="", type=str) or "").strip().lower()

        deleted_clause = _deleted_filter()
        before_clause = ""
        params: list = []
        if before is not None and before_id:
            before_clause = "AND (p.created_at < %s OR (p.created_at = %s AND LOWER(p.txhash) < %s))"
            params.extend([int(before), int(before), before_id])
        elif before is not None:
            before_clause = "AND p.created_at < %s"
            params.append(int(before))
        params.append(limit + 1)

        log_event(
            rid,
            "get_recent_content.query",
            limit=limit,
            before=before,
            before_id=before_id,
        )

        with connect_db(timeout=10.0, busy_timeout_ms=15000) as conn:
            cur = conn.cursor()
            cur.execute(
                f"""
                SELECT p.txhash,
                       p.owner,
                       COALESCE(pr.username, '') AS username,
                       p.created_at,
                       COALESCE(p.community, '') AS community,
                       COALESCE(p.root_community, p.community, '') AS root_community,
                       COALESCE(p.root_post_id, p.txhash, '') AS root_post_id,
                       COALESCE(p.target, '') AS target,
                       COALESCE(p.title, '') AS title,
                       COALESCE(p.content, '') AS content,
                       COALESCE(p.tag, '') AS tag,
                       COALESCE(p.edited_at, 0) AS edited_at
                FROM posts p
                LEFT JOIN profiles pr ON pr.owner = p.owner
                WHERE TRUE
                  {before_clause}
                  {deleted_clause}
                ORDER BY p.created_at DESC, LOWER(p.txhash) DESC
                LIMIT %s
                """,
                params,
            )
            rows = cur.fetchall()

        has_more = len(rows) > limit
        rows = rows[:limit]

        items: list[dict] = []
        for r in rows:
            target = r[7] or ""
            items.append(
                {
                    "post_id": r[0],
                    "author": r[1],
                    "username": r[2] or "",
                    "timestamp": int(r[3]) if r[3] is not None else 0,
                    "community": r[4] or "",
                    "root_community": r[5] or "",
                    "root_post_id": r[6] or "",
                    "target": target,
                    "title": r[8] or "",
                    "content": r[9] or "",
                    "tag": r[10] or "",
                    "edited_at": int(r[11]) if r[11] is not None else 0,
                    "is_comment": bool(target),
                }
            )

        next_before = items[-1]["timestamp"] if (has_more and items) else None
        next_before_id = items[-1]["post_id"] if (has_more and items) else None

        return jsonify(
            {
                "items": items,
                "limit": limit,
                "next_before": next_before,
                "next_before_id": next_before_id,
                "has_more": has_more,
            }
        )
    except Exception as e:
        return safe_error(e)


@public_bp.route("/api/get_reports")
def get_reports():
    try:
        # Query params carry the signed identity for GET.
        data = {
            "address": request.args.get("address", default="", type=str),
            "pubkey": request.args.get("pubkey", default="", type=str),
            "signature": request.args.get("signature", default="", type=str),
            "timestamp": request.args.get("timestamp"),
            "envelope_nonce": request.args.get("envelope_nonce"),
        }
        addr = (data.get("address") or "").strip()
        limit = request.args.get("limit", default=100, type=int)
        limit = max(1, min(limit, 500))
        if not addr:
            return jsonify({"error": "address required"}), 400

        from routes.core import _require_signed_read, get_user_level

        admin_addr, aerr = _require_signed_read(data, "get_reports", addr)
        if aerr is not None:
            return aerr

        level = get_user_level(admin_addr)
        if level < 100:
            return api_error_code("forbidden", 403)

        with connect_backend_db() as bconn:
            bcur = bconn.cursor()
            bcur.execute(
                """
                SELECT id, owner, target, reason, created_at
                FROM reports
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            report_rows = bcur.fetchall()

        if not report_rows:
            return jsonify({"reports": []})

        reporter_addrs = list({(r[1] or "").lower() for r in report_rows if r[1]})
        target_hashes = list({(r[2] or "").lower() for r in report_rows if r[2]})

        username_map: dict[str, str] = {}
        post_map: dict[str, dict] = {}

        with connect_db(timeout=10.0, busy_timeout_ms=15000) as conn:
            cur = conn.cursor()
            if reporter_addrs:
                ph = ",".join(["%s"] * len(reporter_addrs))
                cur.execute(
                    f"SELECT LOWER(owner), COALESCE(username, '') FROM profiles WHERE LOWER(owner) IN ({ph})",
                    reporter_addrs,
                )
                for owner_lc, uname in cur.fetchall():
                    username_map[owner_lc] = uname

            if target_hashes:
                ph = ",".join(["%s"] * len(target_hashes))
                cur.execute(
                    f"""SELECT LOWER(txhash), owner, COALESCE(title, ''), COALESCE(content, '')
                        FROM posts WHERE LOWER(txhash) IN ({ph})""",
                    target_hashes,
                )
                for txh, p_owner, title, content in cur.fetchall():
                    post_map[txh] = {"owner": (p_owner or "").lower(), "title": title, "content": content}
                post_owner_addrs = list({v["owner"] for v in post_map.values() if v["owner"]})
                if post_owner_addrs:
                    ph2 = ",".join(["%s"] * len(post_owner_addrs))
                    cur.execute(
                        f"SELECT LOWER(owner), COALESCE(username, '') FROM profiles WHERE LOWER(owner) IN ({ph2})",
                        post_owner_addrs,
                    )
                    for owner_lc, uname in cur.fetchall():
                        username_map[owner_lc] = uname

        out = []
        for r in report_rows:
            reporter_lc = (r[1] or "").lower()
            target_lc = (r[2] or "").lower()
            post = post_map.get(target_lc, {})
            post_owner = post.get("owner", "")
            out.append(
                {
                    "id": int(r[0]),
                    "reporter_owner": reporter_lc,
                    "reporter_username": username_map.get(reporter_lc, ""),
                    "target": target_lc,
                    "reason": r[3] or "",
                    "timestamp": int(r[4] or 0),
                    "post_owner": post_owner,
                    "post_username": username_map.get(post_owner, ""),
                    "title": post.get("title", ""),
                    "content": post.get("content", ""),
                }
            )
        return jsonify({"reports": out})
    except Exception as e:
        return safe_error(e)


def _fetch_post(
    cur,
    txhash: str,
    blocked_posts: set[str] = None,
    blocked_users: set[str] = None,
    use_stored_counts: bool = False,
    blocked_communities: set[str] = None,
    blocked_community_prefixes: tuple[str, ...] | None = None,
    viewer: str = "",
):
    """Fetch a single post with aggregates.

    Args:
        cur: Database cursor
        txhash: Post ID
        blocked_posts: Set of blocked post IDs to filter
        blocked_users: Set of blocked user addresses to filter
        use_stored_counts: If True, use stored comment_count instead of computing
                          via recursive CTE. Faster but doesn't exclude blocked content.
        viewer: Viewer address — own posts always bypass block filters.
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
               p.community,
               p.title,
               p.content,
               COALESCE(p.tag, '') as tag,
               COALESCE(p.root_community, p.community, '') as root_community,
               COALESCE(p.root_post_id, p.txhash, '') as root_post_id,
               COALESCE(p.target, '') as target,
               COALESCE(pr.username, '') AS username,
               CASE WHEN p.edited_at IS NULL THEN 0 ELSE 1 END as edited,
               COALESCE(p.edited_at, 0) as edited_at,
               COALESCE(p.thumbnail_url, '') as thumbnail,
               COALESCE(pr.level, 0) as author_level,
               COALESCE(p.comment_count, 0) as comment_count,
               COALESCE(p.media, '[]') as media,
               COALESCE(pr.created_at, 0) as author_created_at,
               COALESCE(p.relayer, '') as relayer
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
    community_val = row[3]
    title_val = row[4]
    content_val = row[5]
    tag_val = _normalize_api_tag((row[6] or "").strip())
    root_community_val = (row[7] or "").strip()
    root_post_id_val = (row[8] or "").strip().lower()
    target_val = (row[9] or "").strip().lower()
    username_val = row[10] or ""
    edited_flag = bool(row[11] if len(row) > 11 else 0)
    edited_at_val = int(row[12] or 0) if len(row) > 12 else 0
    thumbnail_val = (row[13] or "") if len(row) > 13 else ""
    author_level_val = int(row[14]) if len(row) > 14 and row[14] else 0
    stored_comment_count = int(row[15]) if len(row) > 15 and row[15] else 0
    media_raw_val = row[16] if len(row) > 16 else "[]"
    author_created_at_val = int(row[17]) if len(row) > 17 and row[17] else 0
    relayer_val = (row[18] or "").strip().lower() if len(row) > 18 else ""

    # Parse media JSON array
    try:
        import json as _json

        media_val = _json.loads(media_raw_val or "[]")
        if not isinstance(media_val, list):
            media_val = []
    except Exception:
        media_val = []

    viewer_lower = (viewer or "").strip().lower()
    is_own = viewer_lower and owner == viewer_lower
    if not is_own:
        if pid in blocked_posts:
            return None
        if owner in blocked_users:
            return None
        if _community_is_blocked(
            (community_val or "").strip().lower(), blocked_communities or set(), blocked_community_prefixes or tuple()
        ):
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
        "author_is_new": _is_new_user(author_created_at_val),
        "timestamp": int(created_at) if created_at is not None else None,
        "community": community_val,
        "root_community": root_community_val,
        "root_post_id": root_post_id_val,
        "title": title_val,
        "content": content_val,
        "tag": tag_val,
        "edited": edited_flag,
        "edited_at": edited_at_val,
        "thumbnail": thumbnail_val,
        "media": media_val,
        "media_meta": [],
        "relayer": relayer_val,
        "points": points,
        "comments": comments,
        "children": [],
    }


# Column order expected by _post_row_to_dict. Both the subtree CTE outer SELECT
# and the ancestor CTE must produce rows in exactly this order (depth, when
# present, is appended as index 19 and is NOT part of this constant).
_POST_ROW_COLUMNS = """
    st.txhash, st.owner, st.created_at, st.community, st.title, st.content,
    st.tag, st.root_community, st.root_post_id, st.target, st.thumbnail_url,
    (COALESCE(st.edited_at, 0) > 0) AS edited, st.edited_at,
    COALESCE(pr.username, '') as username,
    COALESCE(pr.level, 0) as author_level,
    st.media,
    COALESCE(pr.created_at, 0) as author_created_at,
    st.relayer,
    st.comment_count
"""


def _post_row_to_dict(row) -> dict:
    """Map a _POST_ROW_COLUMNS row to the API post shape.

    Callers set points / user_vote / user_weight / awards afterwards.
    Tree builder overwrites comments with the visible descendant count.
    """
    import json as _json

    try:
        media_val = _json.loads(row[15] or "[]")
        if not isinstance(media_val, list):
            media_val = []
    except Exception:
        media_val = []

    created_at = row[2]
    return {
        "post_id": (row[0] or "").lower(),
        "target": (row[9] or "").strip().lower(),
        "user_id": (row[1] or "").lower(),
        "username": row[13] or "",
        "author_level": int(row[14]) if row[14] else 0,
        "author_is_new": _is_new_user(int(row[16]) if row[16] else 0),
        "timestamp": int(created_at) if created_at is not None else None,
        "community": row[3],
        "root_community": (row[7] or "").strip(),
        "root_post_id": (row[8] or "").strip().lower(),
        "title": row[4],
        "content": row[5],
        "tag": _normalize_api_tag((row[6] or "").strip()),
        "edited": bool(row[11]),
        "edited_at": int(row[12] or 0),
        "thumbnail": row[10] or "",
        "media": media_val,
        "media_meta": [],
        "relayer": (row[17] or "").strip().lower(),
        "points": 0,
        "comments": int(row[18]) if row[18] else 0,
        "children": [],
        "user_vote": 0,
        "user_weight": 0.0,
    }


def _fetch_comment_tree_batch(
    cur,
    root_id: str,
    blocked_posts: set[str],
    blocked_users: set[str],
    max_depth: int = 6,
    blocked_communities: set[str] = None,
    blocked_community_prefixes: tuple[str, ...] | None = None,
    viewer: str = "",
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
            SELECT p.txhash, p.owner, p.created_at, p.community, p.title, p.content,
                   COALESCE(p.tag, '') as tag,
                   COALESCE(p.root_community, p.community, '') as root_community,
                   COALESCE(p.root_post_id, p.txhash, '') as root_post_id,
                   COALESCE(p.target, '') as target,
                   COALESCE(p.thumbnail_url, '') as thumbnail_url,
                   COALESCE(p.edited_at, 0) as edited_at,
                   0 as depth,
                   COALESCE(p.media, '[]') as media,
                   COALESCE(p.relayer, '') as relayer,
                   COALESCE(p.comment_count, 0) as comment_count
            FROM posts p
            WHERE LOWER(p.txhash) = %s {deleted_clause}
            UNION ALL
            SELECT p.txhash, p.owner, p.created_at, p.community, p.title, p.content,
                   COALESCE(p.tag, '') as tag,
                   COALESCE(p.root_community, p.community, '') as root_community,
                   COALESCE(p.root_post_id, p.txhash, '') as root_post_id,
                   COALESCE(p.target, '') as target,
                   COALESCE(p.thumbnail_url, '') as thumbnail_url,
                   COALESCE(p.edited_at, 0) as edited_at,
                   s.depth + 1 as depth,
                   COALESCE(p.media, '[]') as media,
                   COALESCE(p.relayer, '') as relayer,
                   COALESCE(p.comment_count, 0) as comment_count
            FROM posts p
            JOIN subtree s ON LOWER(p.target) = LOWER(s.txhash)
            WHERE s.depth < %s {deleted_clause}
        )
        SELECT {_POST_ROW_COLUMNS}, st.depth
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
    viewer_lower = (viewer or "").strip().lower()

    for row in rows:
        post = _post_row_to_dict(row)
        pid = post["post_id"]
        owner = post["user_id"]
        target_val = post["target"]
        depth = int(row[19])
        post["_depth"] = depth
        # Visible descendant count is computed later via count_descendants.
        post["comments"] = 0

        # Skip if this post or its owner is blocked, or community is blocked
        # Own posts always bypass block filters
        is_own = viewer_lower and owner == viewer_lower
        community_lower = (post["community"] or "").strip().lower()
        if not is_own and (
            pid in blocked_posts
            or owner in blocked_users
            or _community_is_blocked(
                community_lower, blocked_communities or set(), blocked_community_prefixes or tuple()
            )
        ):
            blocked_ids.add(pid)
            continue

        # Skip if parent is blocked (prune subtree)
        if target_val and target_val in blocked_ids:
            blocked_ids.add(pid)
            continue

        all_posts[pid] = post

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


def _fetch_ancestor_chain(
    cur,
    comment_id: str,
    blocked_posts: set[str],
    blocked_users: set[str],
    blocked_communities: set[str] | None = None,
    blocked_community_prefixes: tuple[str, ...] | None = None,
    viewer: str = "",
    near_limit: int = 5,
    hard_cap: int = 100,
) -> tuple[list[dict], int]:
    """Walk up the target chain from `comment_id` to the root post.

    Returns (ancestors, omitted) where `ancestors` is ordered ROOT FIRST and
    ends at the immediate parent, and `omitted` counts visible ancestors
    dropped between the root and the nearest `near_limit`.

    Returns ([], 0) for a root post (no target).
    """
    deleted_clause = _deleted_filter()
    cur.execute(
        f"""
        WITH RECURSIVE chain AS (
            SELECT p.txhash, COALESCE(p.target, '') AS target, 0 AS up,
                   ARRAY[LOWER(p.txhash)] AS path
            FROM posts p
            WHERE LOWER(p.txhash) = %s {deleted_clause}
            UNION ALL
            SELECT p.txhash, COALESCE(p.target, '') AS target, c.up + 1,
                   c.path || LOWER(p.txhash)
            FROM posts p
            JOIN chain c ON LOWER(p.txhash) = LOWER(c.target)
            WHERE c.up < %s
              AND COALESCE(c.target, '') <> ''
              AND NOT (LOWER(p.txhash) = ANY (c.path))
              {deleted_clause}
        )
        SELECT p.txhash, p.owner, p.created_at, p.community, p.title, p.content,
               COALESCE(p.tag, '') as tag,
               COALESCE(p.root_community, p.community, '') as root_community,
               COALESCE(p.root_post_id, p.txhash, '') as root_post_id,
               COALESCE(p.target, '') as target,
               COALESCE(p.thumbnail_url, '') as thumbnail,
               CASE WHEN p.edited_at IS NULL THEN 0 ELSE 1 END as edited,
               COALESCE(p.edited_at, 0) as edited_at,
               COALESCE(pr.username, '') as username,
               COALESCE(pr.level, 0) as author_level,
               COALESCE(p.media, '[]') as media,
               COALESCE(pr.created_at, 0) as author_created_at,
               COALESCE(p.relayer, '') as relayer,
               COALESCE(p.comment_count, 0) as comment_count,
               c.up
        FROM chain c
        JOIN posts p ON LOWER(p.txhash) = LOWER(c.txhash)
        LEFT JOIN profiles pr ON LOWER(pr.owner) = LOWER(p.owner)
        WHERE c.up > 0
        ORDER BY c.up ASC
        """,
        (comment_id.lower(), hard_cap),
    )

    viewer_lower = (viewer or "").strip().lower()
    # Track the furthest CTE row (by `up`) independent of block filtering so we
    # can detect hard_cap truncation without mistaking a blocked/skipped root.
    furthest_up = -1
    furthest_is_root = False
    chain: list[dict] = []
    for row in cur.fetchall():
        post = _post_row_to_dict(row)
        up = int(row[19]) if len(row) > 19 and row[19] is not None else 0
        if up >= furthest_up:
            furthest_up = up
            furthest_is_root = not bool((post.get("target") or "").strip())
        is_own = viewer_lower and post["user_id"] == viewer_lower
        if not is_own and (
            post["post_id"] in blocked_posts
            or post["user_id"] in blocked_users
            or _community_is_blocked(
                (post["community"] or "").strip().lower(),
                blocked_communities or set(),
                blocked_community_prefixes or tuple(),
            )
        ):
            continue
        chain.append(post)

    if not chain:
        return [], 0

    # Batch vote totals (same enrichment the tree path does for descendants).
    anc_ids = [a["post_id"] for a in chain]
    if blocked_users:
        blocked_ph = ",".join(["%s"] * len(blocked_users))
        ph = ",".join(["%s"] * len(anc_ids))
        cur.execute(
            f"""
            SELECT LOWER(target), COALESCE(SUM(user_weight), 0)
            FROM votes
            WHERE LOWER(target) IN ({ph})
              AND LOWER(owner) NOT IN ({blocked_ph})
            GROUP BY LOWER(target)
            """,
            anc_ids + list(blocked_users),
        )
    else:
        ph = ",".join(["%s"] * len(anc_ids))
        cur.execute(
            f"""
            SELECT LOWER(target), COALESCE(SUM(user_weight), 0)
            FROM votes
            WHERE LOWER(target) IN ({ph})
            GROUP BY LOWER(target)
            """,
            anc_ids,
        )
    pts_map = {tgt: float(pts or 0) for tgt, pts in cur.fetchall() if tgt}
    for a in chain:
        a["points"] = pts_map.get(a["post_id"], 0)

    # chain is parent-first: [parent, grandparent, ..., furthest]
    # Hit hard_cap mid-chain: furthest is NOT the OP — do not invent a root.
    truncated = furthest_up >= hard_cap and not furthest_is_root
    if truncated:
        near = chain[:near_limit]
        walked_beyond = max(0, len(chain) - near_limit)
        # +1 for unknown ancestors past the cap (UI: "N older replies above")
        omitted = walked_beyond + 1
        logger.debug(
            "ancestor_chain.truncated hard_cap=%s furthest_up=%s returned=%s omitted=%s",
            hard_cap,
            furthest_up,
            len(near),
            omitted,
        )
        return list(reversed(near)), omitted

    if len(chain) <= near_limit + 1:
        return list(reversed(chain)), 0
    root_node = chain[-1]
    near = chain[:near_limit]
    return [root_node] + list(reversed(near)), len(chain) - near_limit - 1


def _build_thread(
    cur,
    post_id: str,
    address: str,
    blocked_posts: set[str],
    blocked_users: set[str],
    blocked_communities_exact: set[str],
    blocked_community_prefixes: tuple[str, ...],
    rid: str,
    lens: str = "effective",
    team_id: int | None = None,
    scope: str = "current",
) -> dict | None:
    """Build the get_comments payload for `post_id`. Returns None if not found/blocked."""
    root, children = _fetch_comment_tree_batch(
        cur,
        post_id,
        blocked_posts,
        blocked_users,
        max_depth=6,
        blocked_communities=blocked_communities_exact,
        blocked_community_prefixes=blocked_community_prefixes,
        viewer=address,
    )
    if not root:
        return None

    if (root.get("target") or "").strip():
        ancestors, ancestors_omitted = _fetch_ancestor_chain(
            cur,
            root["post_id"],
            blocked_posts,
            blocked_users,
            blocked_communities=blocked_communities_exact,
            blocked_community_prefixes=blocked_community_prefixes,
            viewer=address,
        )
    else:
        ancestors, ancestors_omitted = [], 0

    viewer_lower = (address or "").strip().lower()
    if viewer_lower and viewer_lower != "guest":
        all_post_ids = [root["post_id"]] + [a["post_id"] for a in ancestors]

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
            apply_votes(ancestors)

    all_ids_for_awards = [root["post_id"]] + [a["post_id"] for a in ancestors]

    def collect_ids_for_awards(nodes):
        for n in nodes:
            all_ids_for_awards.append(n["post_id"])
            if n.get("children"):
                collect_ids_for_awards(n["children"])

    collect_ids_for_awards(children)
    _, award_details = _load_award_aggregates(cur, all_ids_for_awards, blocked_users)
    root["awards"] = award_details.get(root["post_id"], [])

    def apply_awards(nodes):
        for n in nodes:
            n["awards"] = award_details.get(n["post_id"], [])
            if n.get("children"):
                apply_awards(n["children"])

    apply_awards(children)
    apply_awards(ancestors)

    def _collect_posts(nodes, out):
        for n in nodes:
            out.append(n)
            if n.get("children"):
                _collect_posts(n["children"], out)

    thread_posts = [root]
    _collect_posts(children, thread_posts)
    overlay_posts = thread_posts + ancestors
    _enrich_media_meta(cur, overlay_posts)
    visible_posts, tombstones = _filter_posts_for_lens(
        cur,
        overlay_posts,
        viewer=address,
        requested_lens=lens,
        requested_team_id=team_id,
        scope=scope,
        direct=True,
    )
    # Direct thread views stay unfiltered by allowed_tags, but the tag they
    # report still has to be the effective one so the client blurs correctly.
    _resolve_effective_tags(cur, visible_posts)
    visible_ids = {post["post_id"] for post in visible_posts}
    if root["post_id"] not in visible_ids:
        tombstone = next((item for item in tombstones if item["post_id"] == root["post_id"]), None)
        if tombstone is None:
            return None
        return {"root": tombstone, "children": [], "ancestors": [], "ancestors_omitted": 0}

    def retain_visible(nodes):
        kept = []
        for node in nodes:
            if node["post_id"] not in visible_ids:
                continue
            if node.get("children"):
                node["children"] = retain_visible(node["children"])
            kept.append(node)
        return kept

    children = retain_visible(children)
    ancestors = [ancestor for ancestor in ancestors if ancestor["post_id"] in visible_ids]
    _track_image_impressions(thread_posts, rid, context="get_comments")

    # count_descendants ran on the raw tree, before the lens dropped anything, so
    # the header would advertise comments this response refuses to return. That
    # is how a locked thread showed "Comments (2)" above an empty tree. Truncated
    # leaves keep their stored count: those replies were never loaded, so there is
    # nothing to filter them against and guessing would be worse than the skew.
    def recount_visible(nodes) -> int:
        """Return visible loaded descendants, mirroring count_descendants."""
        total = 0
        for node in nodes:
            kids = node.get("children") or []
            below = recount_visible(kids)
            # A node with no loaded children may still be a truncated leaf whose
            # count came from a reply query rather than the tree; leave it alone.
            if kids:
                node["comments"] = below
            total += 1 + below
        return total

    root["comments"] = recount_visible(children)

    lens_team_id = (root.get("lens") or {}).get("effective_team_id")
    root["thread_locked"] = thread_locked_for_lens(cur, root.get("community") or "", root["post_id"], lens_team_id)
    if root["thread_locked"]:
        logger.debug(
            "[lock] thread locked for lens root=%s community=%s team=%s",
            str(root["post_id"])[:12],
            root.get("community"),
            lens_team_id,
        )

    return {
        "root": root,
        "children": children,
        "ancestors": ancestors,
        "ancestors_omitted": ancestors_omitted,
    }


@public_bp.route("/api/get_comments")
def get_comments():
    rid = next_request_id()
    t_start = time.time()

    post_id = request.args.get("post_id", type=str)
    address = request.args.get("address", default="", type=str)
    try:
        lens, team_id, scope = _lens_request_args(allow_team_without_community=True)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    if not post_id:
        return jsonify({"error": "post_id is required"}), 400
    try:
        conn = connect_db(timeout=10.0, busy_timeout_ms=15000)
        cur = conn.cursor()

        t_blocked = time.time()
        blocked_posts = _get_blocked_posts(cur, address)
        blocked_users = _get_blocked_users(cur, address)
        blocked_communities = _get_blocked_communities(cur, address)
        blocked_communities_exact, blocked_community_prefixes = _split_blocked_communities(blocked_communities)
        t_blocked_ms = (time.time() - t_blocked) * 1000

        t_tree = time.time()
        resp = _build_thread(
            cur,
            post_id,
            address,
            blocked_posts,
            blocked_users,
            blocked_communities_exact,
            blocked_community_prefixes,
            rid,
            lens=lens,
            team_id=team_id,
            scope=scope,
        )
        t_tree_ms = (time.time() - t_tree) * 1000

        if not resp:
            conn.close()
            log_event(rid, "get_comments.not_found", post_id=post_id[:16])
            return jsonify({"error": "post not found"}), 404

        conn.close()

        def count_nodes(nodes):
            total = 0
            for n in nodes:
                total += 1
                if n.get("children"):
                    total += count_nodes(n["children"])
            return total

        node_count = 1 + count_nodes(resp["children"])
        total_ms = (time.time() - t_start) * 1000
        log_event(
            rid,
            "get_comments.ok",
            post_id=post_id[:16],
            nodes=node_count,
            ancestors=len(resp["ancestors"]),
            ancestors_omitted=resp["ancestors_omitted"],
            blocked_posts=len(blocked_posts),
            blocked_users=len(blocked_users),
            blocked_ms=round(t_blocked_ms, 1),
            tree_ms=round(t_tree_ms, 1),
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
            return jsonify({"error": "comment not found or invalid"}), 404
        return jsonify({"root_post_id": root_id, "comment_id": comment_id})
    except Exception as e:
        return safe_error(e)


@public_bp.route("/api/get_comment_context")
def get_comment_context():
    rid = next_request_id()
    comment_id = request.args.get("comment_id", type=str)
    address = request.args.get("address", default="", type=str)
    try:
        lens, team_id, scope = _lens_request_args(allow_team_without_community=True)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    max_depth_raw = request.args.get("max_depth", default=None, type=str)

    # Parse and validate max_depth strictly (1-5, hard error on invalid)
    if max_depth_raw is None:
        max_depth = 5  # Default to max
    else:
        try:
            max_depth = int(max_depth_raw)
        except (ValueError, TypeError):
            log_event(rid, "get_comment_context.invalid_depth", raw=max_depth_raw)
            return jsonify({"error": "invalid max_depth", "max_depth": max_depth_raw}), 400
        if max_depth < 1 or max_depth > 5:
            log_event(rid, "get_comment_context.invalid_depth", value=max_depth)
            return jsonify({"error": "invalid max_depth", "max_depth": max_depth}), 400

    if not comment_id:
        return jsonify({"error": "comment_id is required"}), 400
    try:
        conn = connect_db(timeout=10.0, busy_timeout_ms=15000)
        cur = conn.cursor()
        blocked_posts = _get_blocked_posts(cur, address)
        blocked_users = _get_blocked_users(cur, address)
        blocked_communities = _get_blocked_communities(cur, address)
        blocked_communities_exact, blocked_community_prefixes = _split_blocked_communities(blocked_communities)
        # Parent-first order for legacy callers (they reverse on the client).
        # hard_cap=max_depth matches old _fetch_parent_chain: at most N parents,
        # no forced root inclusion.
        ancestors, _omitted = _fetch_ancestor_chain(
            cur,
            comment_id,
            blocked_posts,
            blocked_users,
            blocked_communities=blocked_communities_exact,
            blocked_community_prefixes=blocked_community_prefixes,
            viewer=address,
            near_limit=max_depth,
            hard_cap=max_depth,
        )
        chain = list(reversed(ancestors))
        chain, _ = _filter_posts_for_lens(
            cur,
            chain,
            viewer=address,
            requested_lens=lens,
            requested_team_id=team_id,
            scope=scope,
        )
        _resolve_effective_tags(cur, chain)
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
        return jsonify({"error": "address required"}), 400

    limit = min(max(1, limit), 100)
    page = _clamp_page(page)
    offset = (page - 1) * limit
    viewer_lower = address.lower()
    need = min(offset + limit, MAX_INBOX_ROWS)

    try:
        t_db_open = time.time()
        conn = connect_db(timeout=30.0, busy_timeout_ms=15000)
        cur = conn.cursor()
        logger.info(f"[get_inbox] DB open: {(time.time() - t_db_open)*1000:.1f}ms")

        t_blocked = time.time()
        blocked_posts = _get_blocked_posts(cur, address)
        blocked_users = _get_blocked_users(cur, address)
        blocked_communities = _get_blocked_communities(cur, address)
        blocked_communities_exact, blocked_community_prefixes = _split_blocked_communities(blocked_communities)
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
                    '' as item_award_type,
                    'reply' as item_type,
                    COALESCE(r.root_community, r.community, '') as item_community,
                    COALESCE(pr.created_at, 0) as actor_created_at
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
                    '' as item_award_type,
                    'mention' as item_type,
                    COALESCE(mp.root_community, mp.community, '') as item_community,
                    COALESCE(mpr.created_at, 0) as actor_created_at
                FROM mentions m
                INNER JOIN posts mp ON mp.txhash = m.post_txhash AND mp.deleted = FALSE
                LEFT JOIN profiles mpr ON mpr.owner = m.mentioner_address
                WHERE LOWER(m.mentioned_address) = %s
                  AND LOWER(m.mentioner_address) != %s
                  AND NOT EXISTS (
                      SELECT 1 FROM posts tp
                      WHERE tp.txhash = mp.target
                        AND LOWER(tp.owner) = %s
                  )

                UNION ALL

                SELECT
                    p.txhash as item_id,
                    a.owner as actor_owner,
                    a.created_at as item_timestamp,
                    COALESCE(p.content, '') as item_content,
                    p.txhash as context_id,
                    p.content as context_content,
                    p.title as context_title,
                    COALESCE(p.target, '') as context_target,
                    p.owner as context_owner,
                    COALESCE(apr.username, '') as actor_username,
                    COALESCE(p.root_post_id, p.txhash) as root_post_id,
                    COALESCE(apr.level, 0) as actor_level,
                    a.award_type as item_award_type,
                    'award' as item_type,
                    COALESCE(p.root_community, p.community, '') as item_community,
                    COALESCE(apr.created_at, 0) as actor_created_at
                FROM awards a
                INNER JOIN posts p ON p.txhash = a.target AND p.deleted = FALSE
                LEFT JOIN profiles apr ON apr.owner = a.owner
                WHERE LOWER(p.owner) = %s
                  AND LOWER(a.owner) != %s
            ) inbox
            ORDER BY inbox.item_timestamp DESC
            LIMIT %s OFFSET %s
        """

        params = [
            viewer_lower,
            viewer_lower,
            viewer_lower,
            viewer_lower,
            viewer_lower,
            viewer_lower,
            viewer_lower,
            need,
            0,
        ]

        t_query = time.time()
        cur.execute(query, params)
        rows = cur.fetchall()
        query_ms = (time.time() - t_query) * 1000
        logger.info(f"[get_inbox] Main query: {query_ms:.1f}ms, rows={len(rows)}")

        t_backend = time.time()
        backend_rows = []
        bconn = connect_backend_db()
        bcur = bconn.cursor()
        bcur.execute(
            """
            SELECT event_key, actor, event_type, created_at, amount, tx_hash
            FROM inbox_events
            WHERE LOWER(recipient) = %s
              AND LOWER(actor) != %s
              AND event_type IN ('follow', 'donation', 'subscription_gift', 'trending')
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (viewer_lower, viewer_lower, need),
        )
        backend_rows = bcur.fetchall()
        logger.info(
            f"[get_inbox] Backend events query: {(time.time() - t_backend)*1000:.1f}ms, rows={len(backend_rows)}"
        )

        trending_posts: dict[str, dict] = {}
        missing_event_keys: list[str] = []
        if backend_rows:
            trending_tx_hashes = sorted(
                {str(row[5] or "").strip().lower() for row in backend_rows if (row[2] or "") == "trending" and row[5]}
            )
            if trending_tx_hashes:
                placeholders = ",".join(["%s"] * len(trending_tx_hashes))
                cur.execute(
                    f"""
                    SELECT LOWER(txhash), COALESCE(title, ''), COALESCE(content, ''), LOWER(owner),
                           COALESCE(community, '')
                    FROM posts WHERE LOWER(txhash) IN ({placeholders}) AND deleted = FALSE
                    """,
                    trending_tx_hashes,
                )
                for prow in cur.fetchall():
                    trending_posts[prow[0]] = {
                        "title": prow[1] or "",
                        "content": prow[2] or "",
                        "owner": prow[3] or "",
                        "community": prow[4] or "",
                    }
                for row in backend_rows:
                    if (row[2] or "") != "trending":
                        continue
                    tx_hash_lc = str(row[5] or "").strip().lower()
                    if tx_hash_lc not in trending_posts:
                        missing_event_keys.append(str(row[0] or "").lower())
            if missing_event_keys:
                placeholders = ",".join(["%s"] * len(missing_event_keys))
                bcur.execute(
                    f"DELETE FROM inbox_events WHERE event_key IN ({placeholders})",
                    missing_event_keys,
                )
                missing_set = set(missing_event_keys)
                backend_rows = [row for row in backend_rows if (row[0] or "").lower() not in missing_set]
                logger.debug(
                    "[get_inbox] Dropped stale trending events count=%d",
                    len(missing_event_keys),
                )

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
                  AND NOT EXISTS (
                      SELECT 1 FROM posts tp
                      WHERE tp.txhash = mp.target
                        AND LOWER(tp.owner) = %s
                  )
            ) + (
                SELECT COUNT(*) FROM awards a
                INNER JOIN posts p ON p.txhash = a.target AND p.deleted = FALSE
                WHERE LOWER(p.owner) = %s AND LOWER(a.owner) != %s
            )
        """
        cur.execute(
            count_query,
            [viewer_lower, viewer_lower, viewer_lower, viewer_lower, viewer_lower, viewer_lower, viewer_lower],
        )
        total_row = cur.fetchone()
        total_indexer = int(total_row[0]) if total_row and total_row[0] else 0

        bcur.execute(
            """
            SELECT COUNT(*) FROM inbox_events
            WHERE LOWER(recipient) = %s
              AND LOWER(actor) != %s
              AND event_type IN ('follow', 'donation', 'subscription_gift', 'trending')
            """,
            (viewer_lower, viewer_lower),
        )
        backend_total_row = bcur.fetchone()
        total_backend = int(backend_total_row[0]) if backend_total_row and backend_total_row[0] else 0

        total = total_indexer + total_backend

        items = []
        for row in rows:
            items.append(
                {
                    "item_id": (row[0] or "").lower(),
                    "actor_owner": (row[1] or "").lower(),
                    "item_timestamp": int(row[2]) if row[2] is not None else 0,
                    "item_content": row[3] or "",
                    "context_id": (row[4] or "").lower(),
                    "context_content": row[5] or "",
                    "context_title": row[6] or "",
                    "context_target": (row[7] or "").strip().lower(),
                    "context_owner": (row[8] or "").lower(),
                    "actor_username": row[9] or "",
                    "root_post_id": (row[10] or "").lower(),
                    "actor_level": int(row[11]) if row[11] else 0,
                    "item_award_type": row[12] or "",
                    "item_type": row[13] or "reply",
                    "item_community": (row[14] or "").strip().lower() if len(row) > 14 else "",
                    "actor_created_at": int(row[15]) if len(row) > 15 and row[15] else 0,
                    "amount": None,
                }
            )

        backend_profiles = {}
        if backend_rows:
            backend_actors = sorted({str(row[1] or "").strip().lower() for row in backend_rows if row[1]})
            if backend_actors:
                placeholders = ",".join(["%s"] * len(backend_actors))
                cur.execute(
                    f"""
                    SELECT LOWER(owner), COALESCE(username, ''), COALESCE(level, 0), COALESCE(created_at, 0)
                    FROM profiles WHERE LOWER(owner) IN ({placeholders})
                    """,
                    backend_actors,
                )
                for prow in cur.fetchall():
                    backend_profiles[prow[0]] = {
                        "username": prow[1] or "",
                        "level": int(prow[2]) if prow[2] is not None else 0,
                        "created_at": int(prow[3]) if prow[3] is not None else 0,
                    }

        for row in backend_rows:
            event_key = (row[0] or "").lower()
            actor_owner = (row[1] or "").lower()
            event_type = row[2] or ""
            item_timestamp = int(row[3]) if row[3] is not None else 0
            amount = int(row[4]) if row[4] is not None else None
            tx_hash_lc = (row[5] or "").lower()
            profile = backend_profiles.get(actor_owner, {})

            context_id = ""
            context_content = ""
            context_title = ""
            context_owner = viewer_lower
            root_post_id = ""
            item_community = ""
            if event_type == "trending":
                post = trending_posts.get(tx_hash_lc)
                if not post:
                    continue
                context_id = tx_hash_lc
                context_title = post["title"]
                context_content = post["content"]
                context_owner = post["owner"]
                root_post_id = tx_hash_lc
                item_community = post["community"]

            items.append(
                {
                    "item_id": event_key,
                    "actor_owner": actor_owner,
                    "item_timestamp": item_timestamp,
                    "item_content": "",
                    "context_id": context_id,
                    "context_content": context_content,
                    "context_title": context_title,
                    "context_target": "",
                    "context_owner": context_owner,
                    "actor_username": profile.get("username", ""),
                    "root_post_id": root_post_id,
                    "actor_level": profile.get("level", 0),
                    "item_award_type": "",
                    "item_type": event_type,
                    "item_community": item_community,
                    "actor_created_at": profile.get("created_at", 0),
                    "amount": amount,
                }
            )

        items.sort(key=lambda item: (item.get("item_timestamp", 0), item.get("item_id", "")), reverse=True)
        page_items = items[offset : offset + limit]

        replies = []
        for item in page_items:
            item_id = item["item_id"]
            actor_owner = item["actor_owner"]
            item_timestamp = item["item_timestamp"]
            item_content = item["item_content"]
            context_id = item["context_id"]
            context_content = item["context_content"]
            context_title = item["context_title"]
            context_target = item["context_target"]
            context_owner = item["context_owner"]
            actor_username = item["actor_username"]
            root_post_id = item["root_post_id"]
            actor_level = item["actor_level"]
            item_award_type = item["item_award_type"]
            item_type = item["item_type"] or "reply"
            item_community = item["item_community"]
            actor_created_at = item["actor_created_at"]
            amount = item["amount"]

            is_profile_notice = item_type in ("follow", "donation", "subscription_gift")
            if actor_owner in blocked_users:
                continue

            if not is_profile_notice:
                is_own_context = context_owner == viewer_lower
                if item_id in blocked_posts:
                    continue
                if not is_own_context and (context_id in blocked_posts or context_owner in blocked_users):
                    continue
                if not is_own_context and _community_is_blocked(
                    item_community, blocked_communities_exact, blocked_community_prefixes
                ):
                    continue
                if not root_post_id:
                    continue

            if is_profile_notice:
                parent_display_text = ""
            elif item_type == "reply":
                if not context_target:
                    parent_display_text = context_title or ""
                else:
                    parent_display_text = context_content or ""
            elif item_type == "award":
                parent_display_text = context_title or ""
            else:
                parent_display_text = context_title or context_content or ""

            if len(parent_display_text) > 200:
                parent_display_text = parent_display_text[:197] + "..."

            replies.append(
                {
                    "reply_id": item_id,
                    "reply_owner": actor_owner,
                    "reply_username": actor_username,
                    "reply_author_level": actor_level,
                    "reply_author_is_new": _is_new_user(actor_created_at),
                    "reply_content": item_content,
                    "reply_timestamp": item_timestamp,
                    "parent_id": context_id,
                    "parent_content": parent_display_text,
                    "parent_owner": context_owner,
                    "root_post_id": root_post_id,
                    "award_type": item_award_type,
                    "type": item_type,
                    "amount": amount,
                }
            )

        bconn.close()
        conn.close()

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


def _verify_seen_signature(
    address: str,
    pub_b64: str,
    sig_b64: str,
    timestamp_raw: str | int | None,
    nonce_raw: str | int | None,
):
    from routes.core import _parse_envelope_nonce, _verify_signature, _guard_push_request

    if not (pub_b64 and sig_b64):
        return None, "missing required fields"
    try:
        timestamp = int(timestamp_raw)
    except (TypeError, ValueError):
        return None, "invalid timestamp"
    nonce, err = _parse_envelope_nonce({"envelope_nonce": nonce_raw})
    if err is not None:
        return None, "invalid envelope_nonce"

    try:
        pub_dec = base64.b64decode(pub_b64)
        sig_dec = base64.b64decode(sig_b64)
    except Exception:
        return None, "invalid relay fields"
    if len(sig_dec) == 65:
        sig_dec = sig_dec[:64]
    if len(pub_dec) != 33 or len(sig_dec) != 64:
        return None, "invalid relay fields"

    user_addr = _derive_address_from_pubkey(pub_dec)
    if not user_addr:
        return None, "invalid pubkey"
    if address and address.lower() != user_addr.lower():
        return None, "address does not match pubkey"

    signed_payload = f"seen_posts:{user_addr.lower()}:{timestamp}:{nonce}"
    if not _verify_signature(pub_dec, sig_dec, signed_payload.encode("utf-8")):
        return None, "invalid signature"

    ok, guard_err = _guard_push_request(user_addr, "seen_posts", timestamp, nonce)
    if not ok:
        # _guard_push_request hands back a (response, status) pair, but this
        # function's contract is a message string — returning the pair made the
        # caller jsonify a Response object and 500.
        body, _code = guard_err
        return None, (body.get_json(silent=True) or {}).get("error") or "invalid signature"
    return user_addr.lower(), None


@public_bp.route("/api/seen_posts", methods=["POST"])
def seen_posts_beacon():
    """Fallback endpoint for sendBeacon flush of seen post IDs on tab close."""
    data = request.get_json(silent=True) or {}
    address = (data.get("address") or "").strip().lower()
    pub_b64 = str(data.get("pubkey", "")).strip()
    sig_b64 = str(data.get("signature", "")).strip()
    timestamp_raw = data.get("timestamp")
    nonce_raw = data.get("envelope_nonce")
    if not address:
        return jsonify({"error": "address required"}), 400
    if address == "guest":
        return jsonify({"ok": True, "ingested": 0})
    user_addr, err = _verify_seen_signature(address, pub_b64, sig_b64, timestamp_raw, nonce_raw)
    if not user_addr:
        return jsonify({"error": err or "invalid signature"}), 400

    posts_raw = data.get("posts") or []
    if not isinstance(posts_raw, list):
        return api_error_code("posts_not_list", 400)
    entries = []
    fallback_reason = str(data.get("reason", "view")).strip().lower()
    for entry in posts_raw[:100]:
        if isinstance(entry, str):
            pid = normalize_post_id(entry)
            reason = fallback_reason
        elif isinstance(entry, dict) and entry.get("id"):
            pid = normalize_post_id(entry.get("id"))
            reason = str(entry.get("reason") or fallback_reason).strip().lower()
        else:
            continue
        if pid:
            entries.append((pid, reason))

    try:
        count = ingest_seen_batch(user_addr, entries, fallback_reason)
    except Exception:
        logger.debug("seen_posts_beacon.err addr=%s", address[:12])
        count = 0
    return jsonify({"ok": True, "ingested": count})


@public_bp.route("/api/mark_inbox_viewed", methods=["POST"])
def mark_inbox_viewed():
    """Set the user's inbox_last_viewed_at to now, clearing their unread count."""
    rid = next_request_id()
    data = request.get_json(silent=True) or {}
    pub_b64 = str(data.get("pubkey", "")).strip()
    sig_b64 = str(data.get("signature", "")).strip()
    address = (data.get("address") or "").strip()
    if "timestamp" not in data:
        return jsonify({"error": "timestamp required"}), 400
    try:
        timestamp = int(data.get("timestamp"))
    except (TypeError, ValueError):
        return jsonify({"error": "invalid timestamp"}), 400
    from routes.core import _parse_envelope_nonce, _verify_signature, _guard_push_request

    nonce, err = _parse_envelope_nonce(data)
    if err is not None:
        return err[0], err[1]

    if not (pub_b64 and sig_b64):
        return jsonify({"error": "missing required fields"}), 400

    try:
        pub_dec = base64.b64decode(pub_b64)
        sig_dec = base64.b64decode(sig_b64)
    except Exception:
        return jsonify({"error": "invalid relay fields"}), 400
    if len(sig_dec) == 65:
        sig_dec = sig_dec[:64]
    if len(pub_dec) != 33 or len(sig_dec) != 64:
        return jsonify({"error": "invalid relay fields"}), 400

    user_addr = derive_address_from_pubkey(pub_dec)
    if not user_addr:
        return jsonify({"error": "invalid pubkey"}), 400

    if address and address.lower() != user_addr.lower():
        return jsonify({"error": "address does not match pubkey"}), 400

    signed_payload = f"mark_inbox_viewed:{user_addr.lower()}:{timestamp}:{nonce}"
    if not _verify_signature(pub_dec, sig_dec, signed_payload.encode("utf-8")):
        return jsonify({"error": "invalid signature"}), 400
    ok, err = _guard_push_request(user_addr, "mark_inbox_viewed", timestamp, nonce)
    if not ok:
        return err[0], err[1]

    addr_lower = user_addr.lower()
    now_ts = int(time.time())

    try:
        conn = connect_backend_db()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO user_inbox_state (owner, inbox_last_viewed_at)
            VALUES (%s, %s)
            ON CONFLICT (owner) DO UPDATE SET inbox_last_viewed_at = EXCLUDED.inbox_last_viewed_at
            """,
            (addr_lower, now_ts),
        )
        conn.close()
        _invalidate_inbox_cache(addr_lower)

        try:
            from shared.push import clear_push_throttle

            clear_push_throttle(addr_lower)
        except Exception as push_err:
            log_event(rid, "mark_inbox_viewed.push_throttle_err", error=str(push_err))

        log_event(rid, "mark_inbox_viewed.ok", address=addr_lower)
        return jsonify({"ok": True, "inbox_last_viewed_at": now_ts})
    except Exception as e:
        log_event(rid, "mark_inbox_viewed.err", error=str(e))
        return safe_error(e)


# ── Admin stats (signed, admin-only, fleet-aggregated) ───────────────────────

# One signed payload type for every stats surface: `stats:{addr}:{ts}:{nonce}`.
# The aggregate endpoint forwards the admin's identical proof to peer export
# endpoints, so a single signature authorizes the whole fan-out.
STATS_ADMIN_ACTION = "stats"
STATS_ADMIN_MIN_LEVEL = 100


def _verify_admin_stats_request(data: dict):
    """Verify a signed admin stats request. Returns (address, None) or
    (None, (response, code)). Mirrors the inbox signing pattern and additionally
    requires the caller to be an admin (profiles.level >= 100)."""
    from routes.core import _parse_envelope_nonce, _verify_signature, _guard_push_request, get_user_level

    pub_b64 = str(data.get("pubkey", "")).strip()
    sig_b64 = str(data.get("signature", "")).strip()
    address = (data.get("address") or "").strip()
    if "timestamp" not in data:
        return None, (jsonify({"error": "timestamp required"}), 400)
    try:
        timestamp = int(data.get("timestamp"))
    except (TypeError, ValueError):
        return None, (jsonify({"error": "invalid timestamp"}), 400)

    nonce, err = _parse_envelope_nonce(data)
    if err is not None:
        return None, (err[0], err[1])
    if not (pub_b64 and sig_b64):
        return None, (jsonify({"error": "missing required fields"}), 400)

    try:
        pub_dec = base64.b64decode(pub_b64)
        sig_dec = base64.b64decode(sig_b64)
    except Exception:
        return None, (jsonify({"error": "invalid relay fields"}), 400)
    if len(sig_dec) == 65:
        sig_dec = sig_dec[:64]
    if len(pub_dec) != 33 or len(sig_dec) != 64:
        return None, (jsonify({"error": "invalid relay fields"}), 400)

    user_addr = _derive_address_from_pubkey(pub_dec)
    if not user_addr:
        return None, (jsonify({"error": "invalid pubkey"}), 400)
    if address and address.lower() != user_addr.lower():
        return None, (jsonify({"error": "address does not match pubkey"}), 400)

    signed_payload = f"{STATS_ADMIN_ACTION}:{user_addr.lower()}:{timestamp}:{nonce}"
    if not _verify_signature(pub_dec, sig_dec, signed_payload.encode("utf-8")):
        return None, (jsonify({"error": "invalid signature"}), 400)

    ok, gerr = _guard_push_request(user_addr, STATS_ADMIN_ACTION, timestamp, nonce)
    if not ok:
        return None, (gerr[0], gerr[1])

    if get_user_level(user_addr) < STATS_ADMIN_MIN_LEVEL:
        return None, api_error_code("forbidden", 403)

    return user_addr.lower(), None


def _parse_stats_window(data: dict):
    """Parse [start, end] unix-second window. Defaults to the last 30 days."""
    now_ts = int(time.time())
    try:
        end = int(data.get("end")) if data.get("end") not in (None, "") else now_ts
    except (TypeError, ValueError):
        end = now_ts
    try:
        start = int(data.get("start")) if data.get("start") not in (None, "") else (end - 30 * 86400)
    except (TypeError, ValueError):
        start = end - 30 * 86400
    if start > end:
        start, end = end, start
    return start, end


@public_bp.route("/api/admin/stats/export", methods=["POST"])
def admin_stats_export():
    """Return this server's local stats for the signed window. Admin-only."""
    rid = next_request_id()
    data = request.get_json(silent=True) or {}
    addr, err = _verify_admin_stats_request(data)
    if err is not None:
        return err[0], err[1]
    start, end = _parse_stats_window(data)
    try:
        import stats as _stats

        payload = _stats.compute_local_stats(start, end)
        log_event(rid, "admin_stats_export.ok", address=addr, start=start, end=end)
        return jsonify(payload)
    except Exception as e:
        log_event(rid, "admin_stats_export.err", error=str(e))
        return safe_error(e)


@public_bp.route("/api/admin/stats/aggregate", methods=["POST"])
def admin_stats_aggregate():
    """Verify the admin signature, compute local stats, fan out the identical
    signed proof to peer export endpoints, and return {aggregate, servers}.
    Failed peers are reported explicitly; never zero-filled."""
    rid = next_request_id()
    data = request.get_json(silent=True) or {}
    addr, err = _verify_admin_stats_request(data)
    if err is not None:
        return err[0], err[1]
    start, end = _parse_stats_window(data)

    import stats as _stats

    servers: List[Dict[str, Any]] = []

    # Local server, computed in-process (never HTTP self-call).
    local_label = _stats.local_server_label()
    try:
        local_stats = _stats.compute_local_stats(start, end)
        servers.append({"server": local_label, "status": "ok", "stats": local_stats})
    except Exception as e:
        log_event(rid, "admin_stats_aggregate.local_err", error=str(e))
        servers.append({"server": local_label, "status": "bad_response", "error": str(e)})

    # Forward the admin's identical proof to remote peers.
    proof = {
        "pubkey": data.get("pubkey"),
        "signature": data.get("signature"),
        "address": data.get("address"),
        "timestamp": data.get("timestamp"),
        "envelope_nonce": data.get("envelope_nonce"),
        "start": start,
        "end": end,
    }
    # Match how the fleet list spells this node before excluding it, rather than
    # comparing raw labels: discovery yields a validated lowercase https URL,
    # while the local label is DOMAIN or a bare moniker. Any spelling difference
    # would make the node HTTP self-call and count its own visitors twice.
    local_endpoint = validate_fleet_endpoint(local_label)
    local_norm = (local_endpoint.url if local_endpoint else local_label.rstrip("/")).lower()
    for base_url in _stats.fleet_fanout_targets():
        if base_url.rstrip("/").lower() == local_norm:
            continue
        entry: Dict[str, Any] = {"server": base_url}
        # Revalidate at send time: discovery is cached for a minute and this
        # request carries the admin's signed proof, so the address it actually
        # goes to is resolved here. IP literals are not accepted — a credential
        # destination has to be a named https host so the certificate can be
        # checked against something.
        endpoint = validate_fleet_endpoint(base_url)
        if endpoint is None or endpoint.url.split(":", 1)[0] != "https":
            entry["status"] = "rejected"
            log_event(rid, "admin_stats_aggregate.rejected_destination", server=base_url)
            servers.append(entry)
            continue
        try:
            resp = fleet_post_json(endpoint, "api/admin/stats/export", proof, timeout=6)
            if resp.status_code == 200:
                entry["status"] = "ok"
                # Validate before merging: the peer decides these numbers, and the
                # aggregation used bare int() on them outside any try/except.
                try:
                    entry["stats"] = _stats.validate_peer_stats(resp.json())
                except ValueError as ve:
                    entry["status"] = "bad_response"
                    entry["error"] = str(ve)
                    log_event(rid, "admin_stats_aggregate.bad_peer_stats", server=base_url, error=str(ve))
            elif resp.status_code in (401, 403):
                entry["status"] = "unauthorized"
            else:
                entry["status"] = "bad_response"
                entry["http_status"] = resp.status_code
        except requests.RequestException:
            entry["status"] = "unreachable"
        except Exception as e:  # noqa: BLE001
            entry["status"] = "bad_response"
            entry["error"] = str(e)
        servers.append(entry)

    aggregate = _stats.aggregate_server_stats([s for s in servers if s.get("status") == "ok"], start, end)
    log_event(rid, "admin_stats_aggregate.ok", address=addr, servers=len(servers))
    return jsonify({"aggregate": aggregate, "servers": servers, "window": {"start": start, "end": end}})


@public_bp.route("/api/stats/visitor_attribution", methods=["POST"])
def stats_visitor_attribution():
    """Public analytics ingest: record first-touch UTM for a visitor id.
    Idempotent; first-touch is never overwritten. No signature required (it is
    anonymous analytics), but it writes only attribution, never reads."""
    data = request.get_json(silent=True) or {}
    visitor_id = str(data.get("visitor_id", "")).strip()
    if not visitor_id:
        return api_error_code("visitor_id_required", 400)
    platform = str(data.get("platform", "")).strip().lower() or None
    utm = {
        k: str(data.get(k, "")).strip() for k in ("utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term")
    }
    ref = str(data.get("ref", "")).strip()
    import stats as _stats

    _stats.record_attribution(visitor_id, platform, utm, ref)
    return jsonify({"ok": True})


def _parse_int_field(raw) -> Optional[int]:
    """Parse a non-negative int from a form field; None if missing/invalid."""
    if raw is None:
        return None
    try:
        return int(float(str(raw).strip()))
    except (TypeError, ValueError):
        return None


@public_bp.route("/api/upload_media", methods=["POST"])
def upload_media():
    """Uniform, provider-agnostic media upload endpoint.

    query string:
      - kind: "image" | "video" — read here so the per-kind size cap can be
        applied before the body is transferred. Clients released before this
        moved out of the form body may still send it as a form field.

    multipart form:
      - file: the bytes
      - duration, height: required for video (probed client-side)

    Returns {url, asset_id, kind}. All provider specifics (local disk / Cloudflare
    / Bunny) are hidden behind this single endpoint, so every client uploads the
    same way regardless of what storage the node runs.
    """
    rid = next_request_id()
    log_event(rid, "upload_media.begin")
    # Uploads are only accepted where a scanning edge (Bunny Shield) fronts them.
    # A node not behind such an edge sets MEDIA_UPLOADS_ENABLED=false (migration).
    if not MEDIA_UPLOADS_ENABLED:
        log_event(rid, "upload_media.disabled")
        return api_error_code("uploads_disabled", 403)
    try:
        from media import (
            MediaError,
            enforce_video_policy,
            get_media_provider,
            validate_upload,
        )
        from media.base import max_image_bytes, max_video_bytes

        # Prefer the query string. Reading `kind` from request.form invokes
        # Werkzeug's multipart parser, which consumes the whole stream and spools
        # the file part to disk — so a form-only `kind` cannot bound the transfer
        # it is meant to bound. Clients released before that change send `kind` as
        # a form field only; those requests are bounded by the video cap, the
        # largest body this endpoint accepts from anyone, and the exact per-kind
        # cap is applied below once the kind is known.
        kind = (request.args.get("kind") or "").strip().lower()
        kind_from_query = kind in ("image", "video")
        if kind and not kind_from_query:
            log_event(rid, "upload_media.rejected", code="media_invalid_kind", kind=kind)
            return api_error_code("media_invalid_kind", 400)

        # Bound before request.files materializes the body into memory/disk.
        # Multipart framing adds a small overhead above the raw file size, so
        # allow 1 MiB of slack on the Content-Length probe; the post-read check
        # still enforces the exact per-kind cap.
        max_bytes = max_image_bytes() if kind == "image" else max_video_bytes()
        slack_bytes = max_bytes + (1024 * 1024)
        content_length = request.content_length
        if content_length is not None and content_length > slack_bytes:
            log_event(rid, "upload_media.too_large", kind=kind, content_length=content_length, max=max_bytes)
            return api_error_code("media_too_large", 413)
        # Belt and braces for a chunked upload that declares no Content-Length:
        # Werkzeug enforces this during the parse itself, so the stream is cut off
        # at the per-kind limit rather than at the video-sized global one.
        request.max_content_length = slack_bytes

        f = request.files.get("file")
        if f is None:
            log_event(rid, "upload_media.rejected", code="media_file_required", kind=kind)
            return api_error_code("media_file_required", 400)

        if not kind_from_query:
            kind = (request.form.get("kind") or "").strip().lower()
            if kind not in ("image", "video"):
                log_event(rid, "upload_media.rejected", code="media_invalid_kind", kind=kind)
                return api_error_code("media_invalid_kind", 400)
            max_bytes = max_image_bytes() if kind == "image" else max_video_bytes()
            log_event(rid, "upload_media.legacy_form_kind", kind=kind)

        data = f.read()
        if len(data) > max_bytes:
            log_event(rid, "upload_media.too_large", kind=kind, size=len(data), max=max_bytes)
            return api_error_code("media_too_large", 413)

        try:
            provider = get_media_provider()
            ext = validate_upload(kind, data, f.mimetype)
            duration = height = None
            if kind == "video":
                duration = _parse_int_field(request.form.get("duration"))
                height = _parse_int_field(request.form.get("height"))
                enforce_video_policy(provider.transcodes, duration, height)
            result = provider.store(kind, data, f.mimetype, ext=ext, duration=duration, height=height)
        except MediaError as me:
            log_event(rid, "upload_media.rejected", code=me.code, kind=kind)
            return api_error(me.code, me.message, me.status)

        # Register images in the catalog for GC tracking (videos are not GC'd).
        if kind == "image":
            asset_id = str(result.get("asset_id", "")).strip()
            if asset_id:
                with connect_backend_db() as bconn:
                    with bconn.cursor() as bcur:
                        bcur.execute(
                            "INSERT INTO image_catalog (image_id, created_at, provider) "
                            "VALUES (%s, %s, %s) ON CONFLICT (image_id) DO NOTHING",
                            (asset_id, int(time.time()), provider.id),
                        )
                log_event(rid, "image_catalog.registered", image_id=asset_id, provider=provider.id)

        log_event(rid, "upload_media.ok", kind=kind, provider=provider.id)
        return jsonify(result)
    except Exception as e:
        log_event(rid, "upload_media.err", error=str(e))
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
        # Validate video UID format. The length-only check this replaced let any
        # charset through, so the UID reached both the upstream URL and the
        # manifest-rewrite regexes unconstrained (L-1).
        if not _STREAM_UID_RE.fullmatch(video_uid or ""):
            log_event(rid, "stream_proxy.invalid_uid", video_uid=str(video_uid)[:32])
            return api_error_code("invalid_video_uid", 400)

        # <path:path> matches slashes, so a traversal segment would otherwise
        # repoint the upstream path away from this UID.
        if path and (not _STREAM_PATH_RE.fullmatch(path) or ".." in path):
            log_event(rid, "stream_proxy.invalid_path", path=str(path)[:64])
            return api_error_code("invalid_video_uid", 400)

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

        # Forward only known upstream parameters (L-1). Anything else is dropped
        # and logged rather than passed through blind.
        dropped = [k for k in request.args.keys() if k not in _STREAM_PROXY_ALLOWED_PARAMS]
        if dropped:
            log_event(rid, "stream_proxy.param_dropped", params=",".join(sorted(dropped))[:120])
        forwarded = [
            (k, v) for k in request.args.keys() if k in _STREAM_PROXY_ALLOWED_PARAMS for v in request.args.getlist(k)
        ]
        if forwarded:
            qs = urlencode(forwarded)
            target_url = f"{target_url}{'&' if '?' in target_url else '?'}{qs}"

        # Forward request without Origin header
        headers = {"User-Agent": request.headers.get("User-Agent", "Mirage/1.0"), "Accept": "*/*"}

        # Handle Range requests for video segments
        if request.headers.get("Range"):
            headers["Range"] = request.headers.get("Range")

        # allow_redirects=False: the response body is reflected to the caller with
        # Access-Control-Allow-Origin *, so following an upstream redirect would
        # let videodelivery.net point this proxy at any host (L-1).
        response = requests.get(target_url, headers=headers, timeout=30, stream=True, allow_redirects=False)

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


def _get_stats_analytics(rid: int):
    """Return analytics stats from user_last_seen (DAU/MAU only)."""
    now = int(time.time())

    # Check cache first
    if _analytics_stats_cache["data"] is not None and _analytics_stats_cache["expires"] > now:
        log_event(rid, "get_stats.analytics.cached")
        return jsonify(_analytics_stats_cache["data"])

    try:
        stats = _get_last_seen_rollups(now)

        # Cache the result
        _analytics_stats_cache["data"] = stats
        _analytics_stats_cache["expires"] = now + _ANALYTICS_STATS_CACHE_TTL

        log_event(rid, "get_stats.analytics.ok", dau=stats.get("dau_today", 0), mau=stats.get("maus", 0))
        return jsonify(stats)
    except Exception as e:
        log_event(rid, "get_stats.analytics.err", error=str(e))
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
                    (SELECT COUNT(*) FROM posts WHERE LOWER(owner) = LOWER(p.owner) AND COALESCE(target,'') = '' AND deleted = FALSE) as post_count,
                    (SELECT COUNT(*) FROM posts WHERE LOWER(owner) = LOWER(p.owner) AND LENGTH(COALESCE(target,'')) > 0 AND deleted = FALSE) as comment_count,
                    (SELECT COUNT(*) FROM votes WHERE LOWER(owner) = LOWER(p.owner)) as vote_count,
                    (SELECT COUNT(*) FROM followed_users WHERE LOWER(target) = LOWER(p.owner)) as follower_count
                FROM profiles p
                WHERE p.subscription_expiry > %s AND p.level > 0 AND p.level < 100 AND p.deleted_at IS NULL
                ORDER BY p.level DESC, p.created_at DESC
                """,
                (now,),
            )
            rows = cur.fetchall()

            # Group by tier
            by_tier: dict[int, list] = {1: [], 10: []}
            for row in rows:
                (
                    owner,
                    username,
                    avatar,
                    level,
                    sub_expiry,
                    created_at,
                    post_count,
                    comment_count,
                    vote_count,
                    follower_count,
                ) = row
                tier = level if level in (1, 10) else 1
                by_tier[tier].append(
                    {
                        "address": owner,
                        "username": username or None,
                        "avatar": avatar or None,
                        "level": level or 0,
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
                "tier_10": by_tier[10],
                "total_subscribers": total_subscribers,
                "count_tier_1": len(by_tier[1]),
                "count_tier_10": len(by_tier[10]),
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
        day_start = now - 86400
        week_start = now - (7 * 86400)

        with connect_db(timeout=3.0, busy_timeout_ms=5000) as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM profiles")
            registered_users = cur.fetchone()[0] or 0

            cur.execute(
                """
                SELECT COUNT(*) FROM posts
                WHERE deleted = FALSE
                  AND created_at >= %s
                """,
                (day_start,),
            )
            posts_24h = cur.fetchone()[0] or 0

            # Network-wide chain-active addresses in the last 7 days.
            # Posts (root + comments) and votes are chain data, identical
            # on every node, so this catches users who participate via ANY
            # node. Pure lurkers on other nodes remain invisible — a known
            # limitation, since no chain action records their presence.
            cur.execute(
                """
                SELECT LOWER(owner) FROM posts
                WHERE created_at >= %s AND deleted = FALSE
                UNION
                SELECT LOWER(owner) FROM votes
                WHERE created_at >= %s
                """,
                (week_start, week_start),
            )
            chain_active = {row[0] for row in cur.fetchall()}

        # This-node logged-in users (incl. lurkers) in the last 7 days.
        # Combined with chain_active via set union, addresses that show up
        # in both are counted once.
        with connect_backend_db() as bconn:
            bcur = bconn.cursor()
            bcur.execute(
                "SELECT LOWER(owner) FROM user_last_seen WHERE last_seen_at >= %s",
                (week_start,),
            )
            local_active = {row[0] for row in bcur.fetchall()}

        active_7d = len(chain_active | local_active)

        result = {
            "registered_users": registered_users,
            "posts_24h": posts_24h,
            "active_7d": active_7d,
        }

        # Cache the result
        _welcome_stats_cache["data"] = result
        _welcome_stats_cache["expires"] = now + _WELCOME_STATS_CACHE_TTL

        log_event(rid, "get_welcome_stats.ok", **result)
        return jsonify(result)
    except Exception as e:
        log_event(rid, "get_welcome_stats.err", error=str(e))
        return safe_error(e)


@public_bp.route("/api/get_stats")
def get_stats():
    """Return stats for the stats page. Supports tabs: overview (default), subscribers, accounts, analytics."""
    rid = next_request_id()
    tab = request.args.get("tab", "overview").lower()
    log_event(rid, "get_stats.begin", tab=tab)

    # Admin-only: this endpoint exposes sensitive financial/subscriber data and is
    # superseded by the signed /api/admin/stats/* fleet API. Require the same signed
    # admin proof. Signing fields may arrive via query string (GET) or JSON body.
    auth_data = {**request.args.to_dict(), **(request.get_json(silent=True) or {})}
    _addr, _err = _verify_admin_stats_request(auth_data)
    if _err is not None:
        return _err[0], _err[1]

    # Route to tab-specific handlers. The signup and reward tabs read the invite,
    # referral and quest tables v1.39.0 dropped; they answer 410 like the rest of
    # that surface rather than serving zeros a reader would take for real data.
    if tab in ("signups", "rewards", "rewards_history"):
        log_event(rid, "get_stats.tab_retired", tab=tab)
        return api_error_code("gone", 410)
    if tab == "subscribers":
        return _get_stats_subscribers(rid)
    elif tab == "accounts":
        return get_stats_accounts(rid)
    elif tab == "analytics":
        return _get_stats_analytics(rid)

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
            stats["subscribers_tier_10"] = subscribers_by_tier.get(10, 0)

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

            # Most active communities (top 5)
            cur.execute(
                """
                SELECT community, COUNT(*) as count
                FROM posts
                WHERE community IS NOT NULL
                  AND LENGTH(community) > 0
                  AND COALESCE(target,'') = ''
                  AND deleted = FALSE
                GROUP BY community
                ORDER BY count DESC
                LIMIT 5
                """
            )
            stats["most_active_communities"] = [{"community": row[0], "count": row[1]} for row in cur.fetchall()]

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
                "adult": tag_counts.get("adult", 0) + tag_counts.get("porn", 0),
            }

            stats["chain_active_24h"] = stats.get("chain_active_24h", 0)
            stats["total_users"] = stats.get("registered_users", 0)

        finally:
            conn.close()

        last_seen = _get_last_seen_rollups(now)
        stats.update(last_seen)
        logger.debug(
            "get_stats.overview.last_seen dau=%d maus=%d",
            last_seen.get("dau_today", 0),
            last_seen.get("maus", 0),
        )

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


# ── Referral link endpoints ──────────────────────────────────────────────────
__all__ = ["public_bp"]
