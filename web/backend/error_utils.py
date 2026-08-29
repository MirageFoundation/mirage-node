from __future__ import annotations

"""Centralized error response helpers.

Never return raw exception text to API clients. Use safe_error() in catch blocks
to log the full exception server-side and return a generic message to the caller.

All error responses MUST include error_code. Do not return error-only payloads.
"""

import traceback
import uuid

from flask import jsonify
from logging_utils import logger


class IndexerUnavailable(RuntimeError):
    """The indexer DB could not answer a query the backend needs.

    Raised instead of returning a plausible-looking default, so an outage cannot
    be mistaken for real chain state (M-6). safe_error() maps this to a 503 with
    the indexer_unavailable code, which is what makes it distinguishable from
    node_catching_up at every route that already catches Exception.
    """


# ── Canonical error registry: code → message ─────────────────────────
# This is the single source of truth. The reverse map is auto-derived below.
# All messages MUST be lowercase. No duplicates allowed.
ERRORS = {
    # Registration / signup
    "registration_disabled": "registration is disabled on this node",
    # Username
    "username_required": "username required",
    "username_too_short": "username too short",
    "username_too_long": "username too long",
    "username_invalid_format": "invalid username format",
    # Auth / envelope
    "missing_fields": "missing required fields",
    "invalid_pubkey": "invalid pubkey",
    "invalid_signature": "invalid signature",
    "invalid_timestamp": "invalid timestamp",
    "timestamp_required": "timestamp required",
    "timestamp_must_be_millis": "timestamp must be milliseconds",
    "timestamp_outside_window": "timestamp outside allowed window",
    "envelope_expired": "request expired, please retry",
    "invalid_nonce": "invalid envelope_nonce",
    "nonce_required": "envelope_nonce is required (v1.20.0)",
    "nonce_must_be_positive": "envelope_nonce must be > 0",
    "nonce_out_of_range": "envelope_nonce exceeds uint64 range",
    "nonce_replayed": "replayed envelope_nonce",
    "invalid_relay_fields": "invalid relay fields",
    "invalid_owner": "invalid owner",
    "address_mismatch": "address does not match pubkey",
    "address_required": "address required",
    "visitor_id_required": "visitor_id required",
    "control_characters": "fields contain invalid control characters",
    "forbidden": "action forbidden",
    "unauthorized": "unauthorized access",
    "signature_required": "signature required",
    "not_found": "not found",
    "enabled_must_be_boolean": "enabled must be boolean",
    "owner_required": "owner required",
    # Server state
    "node_catching_up": "node is catching up",
    "backend_not_initialized": "backend not initialized",
    "upgrade_required": "client upgrade required",
    "gone": "this API has been removed",
    "community_invalid": "invalid community slug",
    "invalid_curated": "curated must be true or false",
    "curation_team_not_found": "curator team not found",
    "missing_viewer": "viewer is required",
    "missing_post_id": "post_id is required",
    "missing_author": "author is required",
    "invalid_offset": "offset must be a non-negative integer",
    "invalid_limit": "limit must be an integer from 1 to 50",
    "internal_error": "internal server error",
    "indexer_unavailable": "indexer DB unavailable",
    "debug_localhost_only": "debug endpoints only available on localhost",
    # PoW
    "insufficient_pow_precheck": "insufficient pow (precheck)",
    "pow_not_allowed_agents": "pow not allowed for agents",
    "pow_not_allowed_for_award": "pow not allowed for award",
    "pow_not_allowed_for_set_auto_renewal": "pow not allowed for set_auto_renewal",
    "pow_required": "proof of work required",
    "invalid_pow_fields": "invalid pow fields",
    "invalid_last_block_hash": "invalid last_block_hash",
    # Request shape
    "invalid_input": "invalid input",
    "invalid_input_type": "invalid input type",
    "invalid_base64": "invalid base64 encoding",
    # Content / posts
    "title_too_long": "title exceeds limit",
    "content_too_long": "content exceeds limit",
    "topic_too_short": "topic too short",
    "topic_too_long": "topic too long",
    "topic_invalid_format": "invalid topic format",
    "topic_too_many_wildcards": "too many wildcards in topic pattern",
    "topic_required": "topic required for root posts",
    "comment_content_required": "comment content required",
    "comment_not_found": "comment not found or invalid",
    "comment_must_not_include_topic": "comments must not include topic",
    "post_not_found": "post not found",
    "invalid_target": "invalid target",
    "invalid_target_format": "invalid target format",
    "target_not_found": "target not found",
    "target_mismatch": "target mismatch: cannot change post parent",
    "target_must_be_mirage1": "target must be a valid mirage1 address",
    "tag_too_long": "tag too long",
    "invalid_tag": "invalid tag",
    "invalid_override": "invalid override",
    "post_id_required": "post_id is required",
    "comment_id_required": "comment_id is required",
    "invalid_hash": "invalid or missing hash",
    # Media
    "media_not_list": "media must be a list",
    "posts_not_list": "posts must be a list",
    "media_limit_exceeded": "media exceeds limit",
    "media_item_too_long": "media item exceeds length limit",
    "media_must_use_https": "media must use https",
    "media_control_characters": "media contains invalid control characters",
    # Biography
    "biography_too_long": "biography too long",
    # Blocks / follows
    "cannot_block_self": "cannot block yourself",
    "cannot_follow_self": "cannot follow yourself",
    "post_already_blocked": "post is already blocked",
    "user_already_blocked": "user is already blocked",
    "topic_already_blocked": "topic is already blocked",
    "user_already_followed": "user is already followed",
    "topic_already_followed": "topic is already followed",
    "user_must_be_mirage1": "user must be a valid mirage1 address",
    # Agents
    "invalid_agent_address": "invalid agent address",
    "duplicate_agent": "duplicate agent",
    "agent_already_enabled": "agent is already enabled",
    "cannot_enable_self_as_agent": "cannot enable yourself as an agent",
    "cannot_set_self_as_agent": "cannot set yourself as an agent",
    "too_many_agents": "too many agents",
    "agent_tier_required": "agent tier required",
    "missing_tier_config": "missing tier config",
    "missing_profile_level": "missing profile level",
    "missing_max_agents": "missing max_enabled_agents",
    "invalid_user_level": "invalid user level",
    # Subscription
    "not_subscriber": "active subscription required",
    "already_curator": "already a curator in this community",
    "leave_blocked_by_curation": "cannot leave a community while curating a team in it",
    "not_joined": "not a member of this community",
    "invalid_level": "invalid level (must be 1; use set_auto_renewal to change auto-renewal)",
    "invalid_period_count": "period_count must be in [1,12]",
    "insufficient_balance": "insufficient balance",
    "admin_insufficient_balance": "admin insufficient balance",
    "insufficient_funds": "insufficient funds",
    "auto_renew_required": "auto_renew required",
    "gift_rejected_higher_tier": "gift rejected: recipient has a higher tier than requested",
    "gift_invalid_target": "target must be a valid mirage1 address",
    # Awards
    "cannot_award_own_post": "cannot award your own post",
    "already_awarded": "already awarded this post",
    "award_eligibility_failed": "unable to verify award eligibility",
    "unknown_award_type": "unknown award type",
    # Push notifications
    "push_disabled": "push notifications not enabled on this node",
    "push_invalid_token": "invalid expo push token format",
    "push_token_length": "invalid expo push token length",
    "push_invalid_platform": "platform must be ios or android",
    # Reports / moderation
    "reason_too_long": "reason too long (max 200 chars)",
    "admin_required": "admin required",
    # Search / query
    "query_required": "q parameter is required",
    "count_must_be_non_negative": "count must be >= 0",
    "invalid_amount": "invalid amount",
    "amount_must_be_positive": "amount must be positive",
    "invalid_month_format": "invalid month format, use YYYY-MM",
    "invalid_max_depth": "invalid max_depth",
    "unsupported_sort_mode": "unsupported sort mode",
    # Misc service state
    "stats_event_disabled": "stats events disabled",
    "retry": "please retry",
    "not_configured": "service not configured",
    # Upload
    "upload_service_error": "upload service error",
    "cloudflare_not_configured": "cloudflare credentials not configured",
    "cloudflare_stream_not_configured": "cloudflare stream credentials not configured",
    "cloudflare_no_url": "no upload URL received from cloudflare",
    "cloudflare_stream_no_url": "no stream upload URL received from cloudflare",
    "image_type_only": "only 'image' type is supported",
    "invalid_video_uid": "invalid video uid",
    # Pluggable media providers (POST /api/upload_media)
    "uploads_disabled": "media uploads are disabled on this node",
    "media_invalid_kind": "kind must be 'image' or 'video'",
    "media_file_required": "no file uploaded",
    "media_too_large": "uploaded file is too large",
    "media_invalid_type": "unsupported or unrecognized file type",
    "media_metadata_required": "video duration and height are required",
    "video_too_long": "video is too long",
    "video_resolution_too_high": "video resolution too high for its duration on this node",
    "media_provider_not_configured": "media provider not configured",
    "media_store_failed": "media upload service error",
    "media_unknown_provider": "unknown media provider configured",
    "media_edge_unauthorized": "edge registration signature invalid",
    # Communities / curation
    "community_required": "community required",
    "target_and_community_required": "target and community required",
    "community_and_name_required": "community and name required",
    "invalid_curation_mode": "invalid mode",
    "invalid_pinned_team_id": "invalid pinned_team_id",
    "epoch_ids_required": "epoch_ids required",
    "too_many_epoch_ids": "at most 30 epoch_ids",
    "epoch_ids_not_increasing": "epoch_ids must be strictly increasing",
    "topic_retired": "topic is retired; use community",
    "invalid_pow_difficulty": "invalid pow_difficulty",
    "invalid_pow": "invalid pow",
    # Chain rejects (from classify_reject)
    "transaction_rejected": "transaction rejected",
    "out_of_gas": "out of gas",
    "fee_payer_insufficient_funds": "fee payer insufficient funds",
    "empty_error_log": "chain returned empty error log for this transaction",
}

# ── Derived reverse map: message → code ───────────────────────────────
_MSG_TO_CODE = {msg: code for code, msg in ERRORS.items()}


def get_message(code: str) -> str:
    """Look up the canonical message for an error code. Fails hard if unknown."""
    msg = ERRORS.get(code)
    if msg is None:
        raise KeyError(f"unknown error code: {code}")
    return msg


def get_error_code(message: str) -> str:
    """Look up the error code for a message string. Used by the middleware.
    Fails hard if the message is not in the registry."""
    msg = str(message or "").strip()
    if not msg:
        raise ValueError("error message missing")
    code = _MSG_TO_CODE.get(msg)
    if not code:
        raise KeyError(f"unmapped error message: {msg}")
    return code


def api_error(code: str, message: str, status: int = 400, **extra) -> tuple:
    """Return a structured JSON error with both error_code and error string.

    Low-level helper — prefer api_error_code() which derives the message from the code.
    """
    body = {"error": message, "error_code": code}
    body.update(extra)
    try:
        logger().debug(f"api_error code={code} status={status} message={message}")
    except Exception:
        pass
    return jsonify(body), status


def api_error_code(code: str, status: int = 400, **extra) -> tuple:
    """Return a structured JSON error by code. Message is auto-derived."""
    message = get_message(code)
    return api_error(code, message, status, **extra)


def safe_error(e: Exception, context: str = "") -> tuple:
    """Log exception server-side and return a generic JSON error to the client."""
    request_id = uuid.uuid4().hex[:8]
    prefix = f"[{context}] " if context else ""
    if isinstance(e, IndexerUnavailable):
        logger().error(f"{prefix}request_id={request_id} indexer_unavailable: {e}")
        return api_error_code("indexer_unavailable", 503, request_id=request_id)
    logger().error(f"{prefix}request_id={request_id} {type(e).__name__}: {e}\n{traceback.format_exc()}")
    return jsonify({"error": "internal server error", "error_code": "internal_error", "request_id": request_id}), 500
