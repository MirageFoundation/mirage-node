from __future__ import annotations

"""Temporary HTTP compatibility for the published pre-v1.39 mobile app."""

import json
from collections import Counter
from urllib.parse import parse_qsl, urlencode

from bech32 import bech32_decode, convertbits
from flask import Flask, current_app, g, has_request_context, jsonify, request

from error_utils import api_error_code, get_message
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

LEGACY_ERROR_CODES = {
    "community_required": "topic_required",
    "community_too_short": "topic_too_short",
    "community_too_long": "topic_too_long",
    "community_invalid_format": "topic_invalid_format",
    "community_too_many_wildcards": "topic_too_many_wildcards",
    "post_community_required": "topic_required",
    "comment_must_not_include_community": "comment_must_not_include_topic",
    "community_already_blocked": "topic_already_blocked",
    "community_already_joined": "topic_already_followed",
}

LEGACY_ERROR_MESSAGES = {
    "topic_too_short": "topic too short",
    "topic_too_long": "topic too long",
    "topic_invalid_format": "invalid topic format",
    "topic_too_many_wildcards": "too many wildcards in topic pattern",
    "topic_required": "topic required",
    "comment_must_not_include_topic": "comments must not include topic",
    "topic_already_blocked": "topic is already blocked",
    "topic_already_followed": "topic is already followed",
}

RESPONSE_KEY_ALIASES = {
    "community": "topic",
    "root_community": "root_topic",
    "joined_communities": "followed_topics",
    "blocked_communities": "blocked_topics",
}

_CONTENT_READ_ACTIONS = frozenset({"get_posts", "get_comments"})
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


def classify_legacy_exception(message: str) -> tuple[str, int] | None:
    low = (message or "").lower()
    if "legacy_thread_read_only" not in low and "parent post metadata not found" not in low:
        return None
    if has_request_context():
        _record("legacy_mobile.thread_read_only", path=request.path)
    return get_message("legacy_thread_read_only"), 400


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


def _legacy_topics():
    try:
        requested = int(request.args.get("limit", 50))
    except (TypeError, ValueError):
        return _legacy_error("invalid_input_type")
    limit = min(max(1, requested), 200)
    address = (request.args.get("address") or "").strip()
    allowed_tags = request.args.get("allowed_tags")
    items: list[dict] = []
    cursor = ""
    seen_cursors: set[str] = set()

    from routes import communities as communities_routes

    while len(items) < limit:
        query = [("limit", str(min(100, limit - len(items))))]
        if cursor:
            query.append(("cursor", cursor))
        with current_app.test_request_context("/api/communities", query_string=query):
            page_response = _make_response(communities_routes.list_communities())
            page_data = page_response.get_json(silent=True)
        if page_response.status_code != 200:
            return page_response
        if not isinstance(page_data, dict) or not isinstance(page_data.get("items"), list):
            raise RuntimeError("legacy topic list received malformed community response")
        page_items = page_data["items"]
        items.extend(page_items)
        next_cursor = str(page_data.get("next_cursor") or "")
        if not page_data.get("has_more") or not page_items:
            break
        if not next_cursor or next_cursor in seen_cursors:
            raise RuntimeError("legacy topic list cursor repeated")
        seen_cursors.add(next_cursor)
        cursor = next_cursor

    slugs = [str(item.get("community") or "").strip().lower() for item in items[:limit]]
    if not slugs:
        return jsonify({"topics": []})
    from db import connect_db
    from routes import public as public_routes

    try:
        with connect_db(timeout=10.0, busy_timeout_ms=15000) as conn:
            cur = conn.cursor()
            cur.execute(
                """
                WITH requested AS (
                    SELECT UNNEST(%s::text[]) AS community
                ),
                comments AS (
                    SELECT LOWER(TRIM(COALESCE(NULLIF(root_community, ''), community))) AS community,
                           COUNT(*) AS comment_count
                    FROM posts
                    WHERE COALESCE(target, '') <> ''
                      AND deleted = FALSE
                      AND LOWER(TRIM(COALESCE(NULLIF(root_community, ''), community))) = ANY(%s)
                    GROUP BY LOWER(TRIM(COALESCE(NULLIF(root_community, ''), community)))
                ),
                tags AS (
                    SELECT LOWER(TRIM(community)) AS community,
                           COUNT(*) AS total_posts,
                           COUNT(*) FILTER (WHERE LOWER(COALESCE(tag, '')) = 'sensitive') AS sensitive_count,
                           COUNT(*) FILTER (WHERE LOWER(COALESCE(tag, '')) IN ('adult', 'porn')) AS adult_count,
                           COUNT(*) FILTER (WHERE LOWER(COALESCE(tag, '')) = 'gore') AS gore_count,
                           COUNT(*) FILTER (WHERE LOWER(COALESCE(tag, '')) = 'violence') AS violence_count,
                           COUNT(*) FILTER (WHERE LOWER(COALESCE(tag, '')) = 'death') AS death_count
                    FROM posts
                    WHERE COALESCE(target, '') = ''
                      AND deleted = FALSE
                      AND LOWER(TRIM(community)) = ANY(%s)
                    GROUP BY LOWER(TRIM(community))
                )
                SELECT r.community,
                       COALESCE(c.comment_count, 0),
                       COALESCE(t.total_posts, 0),
                       COALESCE(t.sensitive_count, 0),
                       COALESCE(t.adult_count, 0),
                       COALESCE(t.gore_count, 0),
                       COALESCE(t.violence_count, 0),
                       COALESCE(t.death_count, 0)
                FROM requested r
                LEFT JOIN comments c USING (community)
                LEFT JOIN tags t USING (community)
                """,
                (slugs, slugs, slugs),
            )
            topic_stats = {}
            for row in cur.fetchall():
                total = int(row[2] or 0)
                counts = {
                    "sensitive": int(row[3] or 0),
                    "adult": int(row[4] or 0),
                    "gore": int(row[5] or 0),
                    "violence": int(row[6] or 0),
                    "death": int(row[7] or 0),
                }
                dominant_tag = ""
                dominant_ratio = 0.0
                if total:
                    for tag, count in counts.items():
                        ratio = count / total
                        if ratio >= 0.5 and ratio > dominant_ratio:
                            dominant_tag = tag
                            dominant_ratio = ratio
                topic_stats[str(row[0])] = {
                    "comment_count": int(row[1] or 0),
                    "dominant_tag": dominant_tag,
                    "dominant_ratio": dominant_ratio,
                }
    except Exception as exc:
        _record("legacy_mobile.topic_list_error", path=request.path, error=type(exc).__name__)
        return api_error_code("indexer_unavailable", 503)

    visitor_header = request.headers.get("X-Mirage-Visitor")
    with current_app.test_request_context(
        "/api/get_topics",
        query_string={
            **({"address": address} if address else {}),
            **({"allowed_tags": allowed_tags} if allowed_tags is not None else {}),
        },
        headers={"X-Mirage-Visitor": visitor_header} if visitor_header is not None else None,
    ):
        viewer = legacy_unsigned_content_viewer(address, "get_posts") or ""
        allowed = public_routes._viewer_allowed_tags(viewer)

    topics = []
    for item in items[:limit]:
        slug = str(item.get("community") or "").strip().lower()
        stat = topic_stats[slug]
        dominant_tag = public_routes._normalize_api_tag(stat.get("dominant_tag") or "")
        if dominant_tag and dominant_tag not in allowed:
            continue
        ratio = float(stat.get("dominant_ratio") or 0.0)
        flags = {tag: dominant_tag == tag for tag in ("sensitive", "adult", "gore", "violence", "death")}
        comment_count = int(stat["comment_count"])
        topics.append(
            {
                "topic": slug,
                "post_count": int(item.get("post_count") or 0),
                "count": comment_count,
                "comment_count": comment_count,
                "flags": flags,
                "dominant_tag": dominant_tag,
                "dominant_ratio": ratio,
            }
        )
    return jsonify({"topics": topics})


def _legacy_search_topics():
    query = (request.args.get("q") or "").strip()
    if not query:
        return api_error_code("query_required", 400)
    if query.startswith("#"):
        query = query[1:]
    query = query.strip()
    if len(query) < 2:
        return api_error_code("invalid_input", 400)
    try:
        limit = min(max(1, int(request.args.get("limit", 10))), 50)
        offset = max(0, int(request.args.get("offset", 0)))
    except (TypeError, ValueError):
        return _legacy_error("invalid_input_type")
    nested = {
        "q": f"#{query}",
        "type": "communities",
        "limit": str(limit),
        "offset": str(offset),
    }
    for key in ("address", "allowed_tags"):
        value = request.args.get(key)
        if value is not None:
            nested[key] = value

    from routes import public as public_routes

    visitor_header = request.headers.get("X-Mirage-Visitor")
    with current_app.test_request_context(
        "/api/search",
        query_string=nested,
        headers={"X-Mirage-Visitor": visitor_header} if visitor_header is not None else None,
    ):
        result = _make_response(public_routes.search())
        data = result.get_json(silent=True)
    if result.status_code != 200:
        return result
    if not isinstance(data, dict) or not isinstance(data.get("communities"), list):
        raise RuntimeError("legacy topic search received malformed search response")
    topics = []
    for item in data["communities"]:
        mapped = dict(item)
        mapped.setdefault("topic", mapped.get("community", ""))
        topics.append(mapped)
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
    "classify_legacy_exception",
]
