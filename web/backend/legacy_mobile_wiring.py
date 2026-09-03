from __future__ import annotations

"""Temporary HTTP compatibility for the published pre-v1.39 mobile app."""

import json
import re
from collections import Counter
from urllib.parse import parse_qsl, urlencode

from bech32 import bech32_decode, convertbits
from flask import Flask, current_app, g, jsonify, request

from error_utils import api_error_code
from logging_utils import logger, next_request_id
from shared.datatypes import MsgBlockTopic, MsgFollowTopic, MsgUnblockTopic, MsgUnfollowTopic


RESTORED_PATHS = frozenset(
    {
        "/api/get_topics",
        "/api/search_topics",
        "/api/get_agents",
        "/api/get_invite_codes",
        "/api/rewards/summary",
        "/api/rewards/achievements",
        "/api/referrals/precheck",
        "/api/referrals/summary",
        "/api/referral/stats",
        "/api/core/follow_topic",
        "/api/core/unfollow_topic",
        "/api/core/block_topic",
        "/api/core/unblock_topic",
    }
)

TYPED_DISABLED_READ_PATHS = frozenset(
    {
        "/api/get_agents",
        "/api/get_invite_codes",
        "/api/rewards/summary",
        "/api/rewards/achievements",
        "/api/referrals/precheck",
        "/api/referrals/summary",
        "/api/referral/stats",
    }
)

# Renamed codes the bridge can actually emit. `community_required` is raised by
# the restored topic writes below; every other v1.39 community code is either
# unreachable from a legacy path or already worded the way the app expects.
LEGACY_ERROR_CODES = {"community_required": "topic_required"}

LEGACY_ERROR_MESSAGES = {"topic_required": "topic required"}

RESPONSE_KEY_ALIASES = {
    "community": "topic",
    "root_community": "root_topic",
    "joined_communities": "followed_topics",
    "blocked_communities": "blocked_topics",
}

_CONTENT_READ_ACTIONS = frozenset({"get_posts", "get_comments"})

# The published app sends `address` unsigned on exactly these reads, so the
# bridge is bounded to them by path rather than by action name: several routes
# share the `get_posts` action and must not inherit unsigned personalization.
_UNSIGNED_READ_PATHS = frozenset(
    {
        "/api/get_posts",
        "/api/get_comments",
        "/api/get_user_posts",
        "/api/search",
        "/api/bootstrap",
    }
)
_COUNTERS: Counter[str] = Counter()

_DISABLED_REWARDS = {
    "disabled": True,
    "suspended": False,
    "daily_quests": [],
    "flash_quest": None,
    "pending_rewards": [],
    "seconds_until_reset": 0,
    "reward_multiplier": 1,
    "total_mirage": 0,
    "total_mirage_after_multiplier": 0,
    "pending_invite_codes": 0,
    "claiming_available": False,
    "debug": False,
}
_EMPTY_INVITES = {"codes": [], "total": 0, "available": 0}


def _record(event: str, *, debug: bool = False, **fields) -> None:
    _COUNTERS[event] += 1
    rid = getattr(g, "request_id", None) or next_request_id()
    parts = [f"event={event}", f"rid={rid}", *(f"{key}={fields[key]}" for key in sorted(fields)), f"total={_COUNTERS[event]}"]
    message = " ".join(parts)
    if debug:
        logger().debug(message)
    else:
        logger().info(message)


def _legacy_error(code: str, status: int = 400):
    return api_error_code(code, status)


def _same_body_value(left, right) -> bool:
    return str(left if left is not None else "").strip() == str(right if right is not None else "").strip()


def prepare_post_request(raw: dict) -> tuple[dict, int, bool, tuple | None]:
    if not isinstance(raw, dict):
        return {}, 0, False, _legacy_error("invalid_input")
    data = dict(raw)
    has_topic = "topic" in data
    has_community = "community" in data
    if has_topic and has_community:
        if not _same_body_value(data["topic"], data["community"]):
            return data, 0, False, _legacy_error("invalid_input")
        data.pop("topic")
        has_topic = False
    legacy = has_topic and not has_community and "protocol_version" not in data
    if has_topic:
        data["community"] = data.pop("topic")
    if legacy:
        g.legacy_mobile_request = True
        _record("legacy_mobile.post_v0", path=request.path)
        return data, 0, True, None
    try:
        protocol_version = int(data.get("protocol_version", 0))
    except (TypeError, ValueError):
        return data, 0, False, _legacy_error("upgrade_required", 426)
    return data, protocol_version, False, None


def prepare_edit_request(raw: dict) -> tuple[dict, bool, tuple | None]:
    if not isinstance(raw, dict):
        return {}, False, _legacy_error("invalid_input")
    data = dict(raw)
    has_topic = "topic" in data
    has_community = "community" in data
    if has_topic and has_community:
        if not _same_body_value(data["topic"], data["community"]):
            return data, False, _legacy_error("invalid_input")
        data.pop("topic")
        has_topic = False
    legacy = has_topic and not has_community
    if has_topic:
        data["community"] = data.pop("topic")
    if legacy:
        g.legacy_mobile_request = True
        _record("legacy_mobile.edit_topic", path=request.path)
    return data, legacy, None


def prepare_subscribe_request(raw: dict) -> tuple[dict, tuple | None]:
    if not isinstance(raw, dict):
        return {}, _legacy_error("invalid_input")
    try:
        wire_level = int(raw.get("level", 0))
    except (TypeError, ValueError):
        return {}, _legacy_error("invalid_input_type")
    legacy = "period_count" not in raw
    if legacy:
        wire_period_count = 0
        effective_level = 1 if wire_level in (1, 10) else wire_level
        effective_period_count = 1
        g.legacy_mobile_request = True
        _record("legacy_mobile.subscribe_period0", path=request.path, wire_level=wire_level)
        if wire_level == 10:
            _record("legacy_mobile.subscribe_level10", path=request.path)
    else:
        try:
            wire_period_count = int(raw.get("period_count"))
        except (TypeError, ValueError):
            return {}, _legacy_error("invalid_input_type")
        effective_level = wire_level
        effective_period_count = wire_period_count
    return {
        "legacy": legacy,
        "wire_level": wire_level,
        "wire_period_count": wire_period_count,
        "effective_level": effective_level,
        "effective_period_count": effective_period_count,
    }, None


def _valid_mirage_address(value: str) -> bool:
    address = (value or "").strip()
    if address != address.lower():
        return False
    hrp, data = bech32_decode(address)
    if hrp != "mirage" or not data:
        return False
    decoded = convertbits(data, 5, 8, False)
    return decoded is not None and len(decoded) == 20


def legacy_unsigned_content_viewer(claimed_address: str, action: str) -> str | None:
    claimed = (claimed_address or "").strip()
    if (
        request.headers.get("X-Mirage-Visitor") is not None
        or action not in _CONTENT_READ_ACTIONS
        or (request.path.rstrip("/") or "/") not in _UNSIGNED_READ_PATHS
        or not _valid_mirage_address(claimed)
    ):
        return None
    address = claimed.lower()
    g.legacy_mobile_request = True
    _record("legacy_mobile.unsigned_read", action=action, address_prefix=address[:12])
    return address


def legacy_bootstrap_signed_viewer(claimed_address: str) -> str | None:
    proof_fields = ("pubkey", "signature", "timestamp", "envelope_nonce")
    if (
        request.path.rstrip("/") != "/api/bootstrap"
        or request.headers.get("X-Mirage-Visitor") is not None
        or not all(request.args.get(field) not in (None, "") for field in proof_fields)
    ):
        return None
    from routes.core import _require_signed_read

    viewer, auth_error = _require_signed_read(request.args, "get_invite_codes", claimed_address)
    if auth_error is not None:
        return None
    g.legacy_mobile_request = True
    _record("legacy_mobile.bootstrap_signed_read", address_prefix=viewer[:12])
    return viewer


def _query_rewrite():
    path = request.path.rstrip("/") or "/"
    pairs = parse_qsl(request.environ.get("QUERY_STRING", ""), keep_blank_values=True)
    changed = False

    if path == "/api/get_posts":
        topics = [value for key, value in pairs if key == "topic"]
        communities = [value for key, value in pairs if key == "community"]
        if topics:
            if communities and any(topic != community for topic in topics for community in communities):
                return _legacy_error("invalid_input")
            pairs = [(key, value) for key, value in pairs if key != "topic"]
            if not communities:
                pairs.append(("community", topics[-1]))
            g.legacy_mobile_request = True
            changed = True
    elif path == "/api/bootstrap":
        rewritten = []
        for key, value in pairs:
            if key == "view" and value.startswith("topic:"):
                value = "community:" + value[len("topic:") :]
                g.legacy_mobile_request = True
                changed = True
            rewritten.append((key, value))
        pairs = rewritten
    elif path == "/api/search":
        rewritten = []
        for key, value in pairs:
            if key == "type" and value.strip().lower() == "topics":
                value = "communities"
                g.legacy_mobile_request = True
                g.legacy_mobile_search_topics = True
                changed = True
            rewritten.append((key, value))
        pairs = rewritten

    if path in {"/api/get_chain_config", "/api/get_node_config", "/api/bootstrap"} and request.headers.get(
        "X-Mirage-Visitor"
    ) is None:
        g.legacy_mobile_request = True
    if path in RESTORED_PATHS:
        g.legacy_mobile_request = True

    if changed:
        rewritten_query = urlencode(pairs)
        request.environ["QUERY_STRING"] = rewritten_query
        request.query_string = rewritten_query.encode("ascii")
        _record("legacy_mobile.query_rewrite", path=path)
    return None


def _make_response(result):
    return current_app.make_response(result)


def _disabled_read(path: str):
    g.legacy_mobile_typed_disabled = True
    if path == "/api/get_agents":
        payload = {"agents": []}
    elif path == "/api/get_invite_codes":
        payload = dict(_EMPTY_INVITES)
    elif path == "/api/rewards/summary":
        payload = dict(_DISABLED_REWARDS)
    elif path == "/api/rewards/achievements":
        payload = {"achievements": []}
    elif path == "/api/referrals/precheck":
        payload = {
            "valid": False,
            "available": 0,
            "error": "referrals_retired",
            "error_code": "referrals_retired",
        }
    elif path == "/api/referrals/summary":
        try:
            limit = int(request.args.get("limit", 50))
            offset = int(request.args.get("offset", 0))
        except (TypeError, ValueError):
            return _legacy_error("invalid_input_type")
        if limit < 1 or limit > 50:
            return _legacy_error("invalid_limit")
        if offset < 0:
            return _legacy_error("invalid_offset")
        payload = {
            "referrals": [],
            "total": 0,
            "period_start": 0,
            "period_end": 0,
            "limit": limit,
            "offset": offset,
            "has_more": False,
        }
    elif path == "/api/referral/stats":
        payload = {
            "pending_total": 0,
            "paid_total": 0,
            "total_referrals": 0,
            "referral_tree": {"address": "", "children": []},
            "last_update_ts": 0,
            "next_update_ts": 0,
        }
    else:
        raise RuntimeError(f"unhandled disabled legacy path: {path}")
    _record("legacy_mobile.disabled_read", path=path)
    return jsonify(payload)


def _legacy_allowed_tags() -> set:
    """Historical `allowed_tags` handling for restored topic search."""
    from routes import public as public_routes

    return public_routes._parse_allowed_tags(
        request.args.get("allowed_tags", default="sensitive", type=str)
    )


def _legacy_viewer_address() -> str:
    """Claimed viewer for a restored legacy-only read.

    These paths exist solely for the published app, so the unsigned `address`
    is honored here the way v1.38 honored it everywhere: for blocked-list and
    tag filtering only. It never establishes identity.
    """
    claimed = (request.args.get("address") or "").strip()
    if not _valid_mirage_address(claimed):
        return ""
    address = claimed.lower()
    g.legacy_mobile_request = True
    _record("legacy_mobile.unsigned_read", action=request.path, address_prefix=address[:12])
    return address


def _legacy_topics():
    """`GET /api/get_topics` as the published app knows it.

    Mirrors the pre-v1.39 aggregate exactly: titled root posts grouped by
    community, `min_posts` applied in SQL, comment counts from `root_community`,
    live dominant-tag flags, viewer blocked-community filtering, and the
    `small_topics_count` / `min_posts` envelope.
    """
    limit = min(max(1, request.args.get("limit", default=50, type=int)), 200)
    min_posts = request.args.get("min_posts", default=10, type=int)
    viewer = _legacy_viewer_address()

    from db import connect_db
    from params import expect_params
    from routes import public as public_routes

    allowed = public_routes._viewer_allowed_tags(viewer)
    params = expect_params()
    min_size = int(params["min_community_size"])
    max_size = int(params["max_community_size"])
    deleted = public_routes._deleted_filter()

    try:
        with connect_db(timeout=10.0, busy_timeout_ms=15000) as conn:
            cur = conn.cursor()
            cur.execute(
                f"""
                SELECT LOWER(TRIM(p.community)) AS community, COUNT(1) AS post_count
                FROM posts p
                WHERE COALESCE(p.target, '') = ''
                  AND LENGTH(COALESCE(p.title, '')) > 0
                  AND p.community IS NOT NULL
                  AND LENGTH(TRIM(p.community)) >= %s
                  AND LENGTH(TRIM(p.community)) <= %s
                  {deleted}
                GROUP BY LOWER(TRIM(p.community))
                HAVING COUNT(1) >= %s
                ORDER BY post_count DESC, community ASC
                LIMIT %s
                """,
                (min_size, max_size, min_posts, limit),
            )
            ranked = [
                (str(row[0]), int(row[1] or 0))
                for row in cur.fetchall()
                if row[0] and int(row[1] or 0) > 0
            ]

            small_topics_count = 0
            if min_posts > 1:
                cur.execute(
                    f"""
                    SELECT COUNT(*) FROM (
                        SELECT LOWER(TRIM(p.community))
                        FROM posts p
                        WHERE COALESCE(p.target, '') = ''
                          AND LENGTH(COALESCE(p.title, '')) > 0
                          AND p.community IS NOT NULL
                          AND LENGTH(TRIM(p.community)) >= %s
                          AND LENGTH(TRIM(p.community)) <= %s
                          {deleted}
                        GROUP BY LOWER(TRIM(p.community))
                        HAVING COUNT(1) > 0 AND COUNT(1) < %s
                    ) small_communities
                    """,
                    (min_size, max_size, min_posts),
                )
                small_topics_count = int(cur.fetchone()[0] or 0)

            blocked_exact, blocked_patterns = public_routes._split_blocked_communities(
                public_routes._get_blocked_communities(cur, viewer)
            )
            visible = [
                (slug, post_count)
                for slug, post_count in ranked
                if not public_routes._community_is_blocked(slug, blocked_exact, blocked_patterns)
            ]
            slugs = [slug for slug, _ in visible]

            comment_counts: dict[str, int] = {}
            if slugs:
                cur.execute(
                    f"""
                    SELECT LOWER(TRIM(p.root_community)) AS community, COUNT(1) AS comment_count
                    FROM posts p
                    WHERE COALESCE(p.target, '') <> ''
                      AND p.root_community IS NOT NULL
                      AND LENGTH(TRIM(p.root_community)) > 0
                      AND LOWER(TRIM(p.root_community)) = ANY(%s)
                      {deleted}
                    GROUP BY LOWER(TRIM(p.root_community))
                    """,
                    (slugs,),
                )
                comment_counts = {str(row[0]): int(row[1] or 0) for row in cur.fetchall()}
            stats = public_routes._compute_dominant_flags(cur, slugs) if slugs else {}
    except Exception as exc:
        _record("legacy_mobile.topic_list_error", path=request.path, error=type(exc).__name__)
        return api_error_code("indexer_unavailable", 503)

    # Never hint at hidden communities while a content filter is active.
    if not set(public_routes._COMMUNITY_TAGS).issubset(allowed):
        small_topics_count = 0

    topics = []
    for slug, post_count in visible:
        item, dropped = _legacy_topic_item(public_routes, slug, post_count, stats, allowed)
        if dropped:
            continue
        item["comment_count"] = comment_counts.get(slug, 0)
        topics.append(item)
    return jsonify({"topics": topics, "small_topics_count": small_topics_count, "min_posts": min_posts})


def _legacy_topic_item(public_routes, slug: str, post_count: int, stats: dict, allowed: set) -> tuple[dict, bool]:
    stat = stats.get(slug) or {}
    dominant_tag = public_routes._normalize_api_tag(stat.get("dominant_tag") or "")
    if dominant_tag and dominant_tag not in allowed:
        return {}, True
    return (
        {
            "topic": slug,
            "post_count": post_count,
            "count": post_count,
            "flags": {tag: dominant_tag == tag for tag in public_routes._COMMUNITY_TAGS},
            "dominant_tag": dominant_tag or None,
            "dominant_ratio": float(stat.get("dominant_ratio") or 0.0),
        },
        False,
    )


def _legacy_search_topics():
    """`GET /api/search_topics` as the published app knows it.

    Substring match on the sanitized query with the historical relevance order
    (exact, then prefix, then contains; ties by post count then name), the
    historical default limit of 20, an empty result for queries shorter than
    two alphanumeric characters, and the historical item shape.
    """
    limit = min(max(1, request.args.get("limit", default=20, type=int)), 50)
    offset = max(0, request.args.get("offset", default=0, type=int))
    allowed = _legacy_allowed_tags()
    query = re.sub(r"[^a-zA-Z0-9]", "", str(request.args.get("q") or "")).lower()
    if len(query) < 2:
        return jsonify({"topics": []})
    viewer = _legacy_viewer_address()

    from db import connect_db
    from params import expect_params
    from routes import public as public_routes

    params = expect_params()
    min_size = int(params["min_community_size"])
    max_size = int(params["max_community_size"])
    deleted = public_routes._deleted_filter()

    try:
        with connect_db(timeout=10.0, busy_timeout_ms=15000) as conn:
            cur = conn.cursor()
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
                      {deleted}
                    GROUP BY LOWER(TRIM(p.community))
                )
                SELECT cb.community,
                       cb.post_count,
                       CASE
                           WHEN cb.community = %s THEN 0
                           WHEN cb.community LIKE %s THEN 1
                           ELSE 2
                       END AS relevance
                FROM community_base cb
                ORDER BY relevance ASC, post_count DESC, community ASC
                LIMIT %s
                OFFSET %s
                """,
                (min_size, max_size, f"%{query}%", query, f"{query}%", limit, offset),
            )
            ranked = [(str(row[0]), int(row[1] or 0)) for row in cur.fetchall() if row[0]]
            blocked_exact, blocked_patterns = public_routes._split_blocked_communities(
                public_routes._get_blocked_communities(cur, viewer)
            )
            visible = [
                (slug, post_count)
                for slug, post_count in ranked
                if not public_routes._community_is_blocked(slug, blocked_exact, blocked_patterns)
            ]
            stats = public_routes._compute_dominant_flags(cur, [slug for slug, _ in visible]) if visible else {}
    except Exception as exc:
        _record("legacy_mobile.topic_search_error", path=request.path, error=type(exc).__name__)
        return api_error_code("indexer_unavailable", 503)

    topics = []
    for slug, post_count in visible:
        item, dropped = _legacy_topic_item(public_routes, slug, post_count, stats, allowed)
        if dropped:
            continue
        topics.append(item)
    return jsonify({"topics": topics})


_TOPIC_ACTIONS = {
    "/api/core/follow_topic": (
        "follow_topic",
        MsgFollowTopic,
        "canon_base_follow_topic",
        "/mirage.core.v1.MsgFollowTopic",
        False,
    ),
    "/api/core/unfollow_topic": (
        "unfollow_topic",
        MsgUnfollowTopic,
        "canon_base_unfollow_topic",
        "/mirage.core.v1.MsgUnfollowTopic",
        False,
    ),
    "/api/core/block_topic": (
        "block_topic",
        MsgBlockTopic,
        "canon_base_block_topic",
        "/mirage.core.v1.MsgBlockTopic",
        True,
    ),
    "/api/core/unblock_topic": (
        "unblock_topic",
        MsgUnblockTopic,
        "canon_base_unblock_topic",
        "/mirage.core.v1.MsgUnblockTopic",
        True,
    ),
}


def _legacy_topic_action(path: str):
    from routes import core as core_routes
    import pow as pow_helpers

    rid = next_request_id()
    action, message_type, canon_name, type_url, empty_target = _TOPIC_ACTIONS[path]
    try:
        if core_routes.is_node_catching_up():
            return api_error_code("node_catching_up", 503)
        data = request.get_json(force=True) or {}
        if not isinstance(data, dict):
            return _legacy_error("invalid_input")
        env, error, status = core_routes._parse_relay_envelope(data)
        if env is None:
            return error, status
        topic = str(data.get("topic", "")).strip().lower()
        if not topic:
            return _legacy_error("community_required")
        target = str(data.get("target", ""))
        if empty_target:
            if target != "":
                return _legacy_error("invalid_target")
        else:
            target = target.strip()
            if not target or target.lower() != env["user_addr"].lower():
                return _legacy_error("address_mismatch")
        pow_error = core_routes._maybe_pow_precheck(
            rid, action, env, getattr(pow_helpers, canon_name), target, topic
        )
        if pow_error is not None:
            return pow_error
        message = message_type()
        core_routes._fill_envelope(message, env, core_routes.require_runtime().validator_payer_addr)
        message.target = target
        message.topic = topic
        _record("legacy_mobile.topic_action", action=action, topic=topic)
        return core_routes._broadcast_core_msg(
            rid, action, type_url, message, len(target) + len(topic), env["user_addr"]
        )
    except Exception as exc:
        core_routes.log_event(rid, f"{action}.err", error=str(exc))
        message, status = core_routes._classify_exception(str(exc))
        return jsonify({"error": message}), status


def _dispatch_restored(path: str):
    if path in TYPED_DISABLED_READ_PATHS:
        return _disabled_read(path)
    if path == "/api/get_topics":
        return _legacy_topics()
    if path == "/api/search_topics":
        return _legacy_search_topics()
    if path in _TOPIC_ACTIONS:
        return _legacy_topic_action(path)
    raise RuntimeError(f"unhandled restored legacy path: {path}")


def _before_request():
    rewrite_error = _query_rewrite()
    if rewrite_error is not None:
        return rewrite_error
    path = request.path.rstrip("/") or "/"
    expected_method = "POST" if path in _TOPIC_ACTIONS else "GET"
    if path not in RESTORED_PATHS or request.method != expected_method:
        return None
    _record("legacy_mobile.route", path=path, method=request.method)
    return _dispatch_restored(path)


def _add_recursive_aliases(value) -> tuple[object, int]:
    changed = 0
    if isinstance(value, list):
        for index, item in enumerate(value):
            value[index], item_changed = _add_recursive_aliases(item)
            changed += item_changed
        return value, changed
    if not isinstance(value, dict):
        return value, 0
    for child_key, child in list(value.items()):
        value[child_key], item_changed = _add_recursive_aliases(child)
        changed += item_changed
    for modern, legacy in RESPONSE_KEY_ALIASES.items():
        if modern not in value or legacy in value:
            continue
        if modern in ("joined_communities", "blocked_communities") and not isinstance(value[modern], list):
            continue
        value[legacy] = value[modern]
        changed += 1
    if "followed_users" in value:
        if "enabled_agents" not in value:
            value["enabled_agents"] = []
            changed += 1
        if "auto_enabled_agents" not in value:
            value["auto_enabled_agents"] = []
            changed += 1
    return value, changed


def _transform_chain_config(config: dict) -> int:
    changed = 0
    for modern, legacy in (("max_community_size", "max_topic_size"), ("min_community_size", "min_topic_size")):
        if modern in config and legacy not in config:
            config[legacy] = config[modern]
            changed += 1
    tiers = config.get("tiers")
    if isinstance(tiers, list):
        if len(tiers) > 2:
            config["tiers"] = tiers[:2]
            tiers = config["tiers"]
            changed += 1
        for tier in tiers:
            if not isinstance(tier, dict):
                continue
            for modern, legacy in (
                ("max_joined_communities", "max_followed_topics"),
                ("max_blocked_communities", "max_blocked_topics"),
            ):
                if modern in tier and legacy not in tier:
                    tier[legacy] = str(tier[modern])
                    changed += 1
            if "max_enabled_agents" not in tier:
                tier["max_enabled_agents"] = "0"
                changed += 1
            if "can_be_agent" not in tier:
                tier["can_be_agent"] = False
                changed += 1
    return changed


def _transform_node_config(config: dict) -> int:
    additions = {
        "auto_enabled_agents": [],
        "quests_enabled": False,
        "quest_payouts_enabled": False,
        "registration_invite_code_required": False,
    }
    changed = 0
    for key, value in additions.items():
        if config.get(key) != value:
            config[key] = value
            changed += 1
    return changed


def _after_request(response):
    if "application/json" not in (response.content_type or ""):
        return response
    data = response.get_json(silent=True)
    if not isinstance(data, (dict, list)):
        return response

    data, changed = _add_recursive_aliases(data)
    path = request.path.rstrip("/") or "/"
    if isinstance(data, dict):
        if getattr(g, "legacy_mobile_typed_disabled", False):
            for injected_key in ("error_code", "new_inbox_items"):
                if injected_key in data:
                    data.pop(injected_key)
                    changed += 1
        if path == "/api/get_preferences" and isinstance(data.get("communities"), list) and "topics" not in data:
            data["topics"] = data["communities"]
            changed += 1
        if path == "/api/search":
            if isinstance(data.get("communities"), list) and "topics" not in data:
                data["topics"] = data["communities"]
                changed += 1
            if "has_more_communities" in data and "has_more_topics" not in data:
                data["has_more_topics"] = data["has_more_communities"]
                changed += 1
            if getattr(g, "legacy_mobile_search_topics", False) and data.get("search_type") != "topic":
                data["search_type"] = "topic"
                changed += 1
        if "most_active_communities" in data and "most_active_topics" not in data:
            communities = data["most_active_communities"]
            if isinstance(communities, list):
                data["most_active_topics"] = [
                    item.get("community", "") for item in communities if isinstance(item, dict)
                ]
                changed += 1
        if getattr(g, "legacy_mobile_request", False):
            if path == "/api/get_chain_config":
                changed += _transform_chain_config(data)
            elif path == "/api/get_node_config":
                changed += _transform_node_config(data)
            elif path == "/api/bootstrap":
                if isinstance(data.get("chain_config"), dict):
                    changed += _transform_chain_config(data["chain_config"])
                if isinstance(data.get("node_config"), dict):
                    changed += _transform_node_config(data["node_config"])
                if isinstance(data.get("user_status"), dict):
                    if data.get("rewards_summary") != _DISABLED_REWARDS:
                        data["rewards_summary"] = dict(_DISABLED_REWARDS)
                        changed += 1
                    if data.get("invite_codes") != _EMPTY_INVITES:
                        data["invite_codes"] = dict(_EMPTY_INVITES)
                        changed += 1
            error_code = data.get("error_code")
            mapped = LEGACY_ERROR_CODES.get(str(error_code or ""))
            if mapped:
                data["error_code"] = mapped
                data["error"] = LEGACY_ERROR_MESSAGES[mapped]
                changed += 1
        if response.status_code < 400 and path == "/api/get_parameters" and request.args.get("address"):
            from routes.core import get_user_level

            try:
                level = get_user_level(request.args["address"])
            except Exception as exc:
                _record("legacy_mobile.parameters_error", path=path, error=type(exc).__name__)
                return _make_response(api_error_code("indexer_unavailable", 503))
            if data.get("user_level") != level:
                data["user_level"] = level
                changed += 1

    if changed:
        response.set_data(json.dumps(data, separators=(",", ":")))
        _record("legacy_mobile.response_aliases", debug=True, path=path, aliases=changed)
    return response


def install_legacy_mobile_wiring(app: Flask) -> None:
    marker = "legacy_mobile_wiring"
    if marker in app.extensions:
        raise RuntimeError("legacy mobile wiring installed twice")
    app.extensions[marker] = {"counters": _COUNTERS}
    app.before_request(_before_request)
    app.after_request(_after_request)
    with app.app_context():
        _record("legacy_mobile.install", path="app")


__all__ = [
    "install_legacy_mobile_wiring",
    "prepare_post_request",
    "prepare_edit_request",
    "prepare_subscribe_request",
    "legacy_unsigned_content_viewer",
    "legacy_bootstrap_signed_viewer",
]
