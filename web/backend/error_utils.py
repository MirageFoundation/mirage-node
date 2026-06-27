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


# ── Canonical error registry: code → message ─────────────────────────
# This is the single source of truth. The reverse map is auto-derived below.
# All messages MUST be lowercase. No duplicates allowed.
ERRORS = {
    # Registration / signup
    "registration_disabled": "registration is disabled on this node",
    "invite_code_required": "invite code required for new account registration",
    "invite_code_invalid": "invalid invite code",
    "invite_code_used": "this invite code has already been used",
    "invite_code_check_failed": "failed to validate invite code",
    "invite_code_invalid_format": "invalid code format",
    "invite_codes_not_required": "invite codes not required on this node",
    "invite_codes_main_site_only": "invite codes only work on mirage.talk",
    # Username
    "username_required": "username required",
    "username_too_short": "username too short",
    "username_too_long": "username too long",
    "username_invalid_format": "invalid username format",
    # Referrals
    "referral_requires_invite_codes": "referral links require invite codes",
    "referrer_not_found": "referrer not found",
    "referrer_not_opted_in": "referrer has not enabled referral links",
    "referrer_no_codes": "referrer has no available codes",
    "referrer_already_used": "already used this referrer",
    "referrer_username_too_long": "referrer username too long",
    "referrer_username_invalid_format": "invalid referrer username format",
    "referrer_check_failed": "failed to validate referrer",
    "self_referral": "self-referral is not allowed",
    # Auth / envelope
    "missing_fields": "missing required fields",
    "invalid_pubkey": "invalid pubkey",
    "invalid_signature": "invalid signature",
    "invalid_timestamp": "invalid timestamp",
    "timestamp_required": "timestamp required",
    "timestamp_must_be_millis": "timestamp must be milliseconds",
    "timestamp_outside_window": "timestamp outside allowed window",
    "invalid_nonce": "invalid envelope_nonce",
    "nonce_required": "envelope_nonce is required (v1.20.0)",
    "nonce_must_be_positive": "envelope_nonce must be > 0",
    "nonce_out_of_range": "envelope_nonce exceeds uint64 range",
    "nonce_replayed": "replayed envelope_nonce",
    "invalid_relay_fields": "invalid relay fields",
    "invalid_owner": "invalid owner",
    "address_mismatch": "address does not match pubkey",
    "address_required": "address required",
    "control_characters": "fields contain invalid control characters",
    "forbidden": "action forbidden",
    "unauthorized": "unauthorized access",
    "enabled_must_be_boolean": "enabled must be boolean",
    "owner_required": "owner required",
    # Server state
    "node_catching_up": "node is catching up",
    "backend_not_initialized": "backend not initialized",
    "indexer_unavailable": "indexer DB unavailable",
    "internal_error": "internal server error",
    "debug_localhost_only": "debug endpoints only available on localhost",
    # PoW
    "insufficient_pow_precheck": "insufficient pow (precheck)",
    "pow_not_allowed_agents": "pow not allowed for agents",
    "pow_not_allowed_for_award": "pow not allowed for award",
    "pow_not_allowed_for_set_auto_renewal": "pow not allowed for set_auto_renewal",
    "pow_required": "proof of work required",
    "invalid_pow_fields": "invalid pow fields",
    "invalid_last_block_hash": "invalid last_block_hash",
    # Content / posts
    "title_too_long": "title exceeds limit",
    "content_too_long": "content exceeds limit",
    "topic_too_short": "topic too short",
    "topic_too_long": "topic too long",
    "topic_invalid_format": "invalid topic format",
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
    "agents_must_be_array": "agents must be an array",
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
    "invalid_level": "invalid level (must be 1 or 10; use set_auto_renewal to change auto-renewal)",
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
    "push_token_other_account": "push token already registered to another account",
    # Reports / moderation
    "reason_too_long": "reason too long (max 200 chars)",
    "admin_required": "admin required",
    "admin_and_target_required": "admin and target required",
    "admin_target_duration_reason_required": "admin, target, duration_days, and reason required",
    "suspended": "account suspended",
    # Search / query
    "query_required": "q parameter is required",
    "count_must_be_non_negative": "count must be >= 0",
    "invalid_amount": "invalid amount",
    "amount_must_be_positive": "amount must be positive",
    "invalid_duration_days": "invalid duration_days",
    "invalid_month_format": "invalid month format, use YYYY-MM",
    "invalid_max_depth": "invalid max_depth",
    "unsupported_sort_mode": "unsupported sort mode",
    # Quests
    "quest_id_required": "quest_id required",
    "unknown_quest_id": "unknown quest_id",
    "quest_not_assigned": "quest not assigned",
    "quest_already_completed": "quest already completed",
    "no_rewards": "no rewards available",
    "pool_not_configured": "reward pool not configured",
    "payout_failed": "payout failed",
    "stats_event_disabled": "stats events disabled",
    "retry": "please retry",
    "not_configured": "service not configured",
    # Bridge / upload
    "destination_chain_required": "destination_chain required",
    "destination_address_required": "destination_address required",
    "destination_chain_not_enabled": "destination_chain not enabled",
    "destination_chain_too_long": "destination_chain too long",
    "destination_address_too_long": "destination_address too long",
    "invalid_solana_address": "invalid solana address",
    "invalid_solana_address_length": "invalid solana address length",
    "burn_sequence_required": "burn_sequence required",
    "burn_tx_hash_required": "burn_tx_hash required",
    "burn_sequence_not_allowed_outbound": "burn_sequence not allowed for outbound queries",
    "burn_tx_hash_not_allowed_inbound": "burn_tx_hash not allowed for inbound queries",
    "invalid_burn_tx_hash": "invalid burn_tx_hash (expected tx hash)",
    "upload_service_error": "upload service error",
    "cloudflare_not_configured": "cloudflare credentials not configured",
    "cloudflare_stream_not_configured": "cloudflare stream credentials not configured",
    "cloudflare_no_url": "no upload URL received from cloudflare",
    "cloudflare_stream_no_url": "no stream upload URL received from cloudflare",
    "image_type_only": "only 'image' type is supported",
    "invalid_video_uid": "invalid video uid",
    # Pluggable media providers (POST /api/upload_media)
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
    "legacy_upload_unsupported": "this node no longer supports the legacy upload endpoint; use /api/upload_media",
    "media_edge_unauthorized": "edge registration signature invalid",
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
    logger().error(f"{prefix}request_id={request_id} {type(e).__name__}: {e}\n{traceback.format_exc()}")
    return jsonify({"error": "internal server error", "error_code": "internal_error", "request_id": request_id}), 500
