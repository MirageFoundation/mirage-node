from __future__ import annotations

"""Core message relay endpoints.

TRUST MODEL — read docs/architecture/backend-trust-model.md before adding a check
here. The chain's ante handlers are the only enforcement boundary. `/chain/rest/*`
and `/chain/rpc/*` are publicly proxied, so any client can broadcast a relay
transaction without touching this module. Every validation below is advisory: it
buys an honest client a fast, cheap rejection, and nothing more. Do not rely on it
to keep anything out of the chain, and do not read a check on one endpoint as a
guarantee on another — 13 endpoints verify the envelope signature here and 16 do
not, by accepted decision.

Endpoints:
- POST /api/core/set_username: Relay meta-signed username message.
- POST /api/core/block_post: Relay meta-signed block post message.
- POST /api/core/block_user: Relay meta-signed block user message.
- POST /api/core/post: Relay meta-signed post/comment message.
- POST /api/core/vote: Relay meta-signed vote message.
"""

import base64
import hashlib
import ipaddress
import logging
import os
import random
import re
import sys
import time
import threading
from typing import Any, Dict

from flask import Blueprint, g, jsonify, request, has_request_context
from client_ip import get_trusted_client_ip as _get_trusted_client_ip, hash_client_ip as _hash_client_ip
from settings import (
    ACHIEVEMENTS_ENABLED,
    QUESTS_ENABLED,
    REGISTRATION_ENABLED,
    REGISTRATION_INVITE_CODE_REQUIRED,
    PUSH_NOTIFICATIONS_ENABLED,
)
from google.protobuf.any_pb2 import Any as AnyPB
from cosmpy.protos.cosmos.tx.v1beta1.tx_pb2 import TxBody, AuthInfo, Fee, TxRaw, SignerInfo, ModeInfo
from cosmpy.protos.cosmos.tx.signing.v1beta1.signing_pb2 import SignMode
from cosmpy.protos.cosmos.base.v1beta1.coin_pb2 import Coin
from cosmpy.protos.cosmos.bank.v1beta1.tx_pb2 import MsgSend

from shared.datatypes import (
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
    MsgSendTokens,
    MsgPost,
    MsgVote,
    MsgEdit,
    MsgAnnotate,
    MsgSubscribe,
    MsgSetAutoRenewal,
    MsgAward,
    MsgCreateCommunity,
    MsgSetCommunityMetadata,
    MsgTransferCommunity,
    MsgJoinCommunity,
    MsgLeaveCommunity,
    MsgBlockCommunity,
    MsgUnblockCommunity,
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
    MsgClaimCreatorRewards,
)

from logging_utils import log_event, next_request_id, logger
from error_utils import IndexerUnavailable, api_error_code, get_message
from node import derive_address_from_pubkey as _derive_address_from_pubkey, min_gas_price_umirage, require_runtime
from params import expect_params
from quest_assignment import _locked_transaction
from topic_glob import MAX_TOPIC_WILDCARDS, count_wildcards
from db import connect_db, connect_backend_db
from user_last_seen import update_user_last_seen

from shared.inbox import record_inbox_event, follow_event_key, donation_event_key, subscription_gift_event_key
from pow import (
    argon2_digest,
    canon_attribution,
    canon_base_post,
    canon_base_edit,
    canon_base_annotate,
    canon_base_vote,
    canon_base_set_username,
    canon_base_set_biography,
    canon_base_enable_agent,
    canon_base_disable_agent,
    canon_base_set_agents,
    canon_base_follow_user,
    canon_base_unfollow_user,
    canon_base_follow_topic,
    canon_base_unfollow_topic,
    canon_base_block_post,
    canon_base_unblock_post,
    canon_base_block_user,
    canon_base_unblock_user,
    canon_base_block_topic,
    canon_base_unblock_topic,
    canon_base_report,
    canon_base_delete,
    canon_base_delete_user,
    canon_base_send_tokens,
    canon_base_subscribe,
    canon_base_set_auto_renewal,
    canon_base_award,
    check_pow_target,
    decode_b64,
)
from shared.canon import (
    canon_signed_with_pow,
    canon_base_join_community,
    canon_base_leave_community,
    canon_base_block_community,
    canon_base_unblock_community,
    canon_base_create_community,
    canon_base_set_community_metadata,
    canon_base_transfer_community,
    canon_base_create_curation_team,
    canon_base_set_curation_preference,
    canon_base_claim_creator_rewards,
)
from tx import estimate_total_gas_limit, build_tx_bytes, build_and_broadcast_tx, simulate_gas
from chain import (
    classify_reject,
    get_difficulty_info,
    get_pow_base_bits,
    is_node_catching_up,
    is_valid_recent_block_hash,
    max_envelope_future_skew_seconds,
)


def get_balance(address) -> int:
    """Read balance from indexer DB."""
    if not address:
        return 0
    with connect_db(timeout=3.0, busy_timeout_ms=5000) as conn:
        cur = conn.cursor()
        cur.execute("SELECT balance FROM balances WHERE address = LOWER(%s)", (str(address),))
        row = cur.fetchone()
        return int(row[0]) if row and row[0] is not None else 0


import hashlib
import json
import socket

from psycopg.types.json import Jsonb


core_bp = Blueprint("core", __name__)


def derive_address_from_pubkey(pub_dec: bytes) -> str:
    """Derive a bech32 address and mark it as a candidate for the last-seen write.

    The name implied a verified identity and this function verified nothing: the
    underlying derivation checks only that it received 33 bytes, never that they
    are a valid curve point, so any 33-byte string yielded a distinct valid-looking
    address — and the row was committed before the request failed downstream. That
    made `active_7d` on the unauthenticated welcome screen, and the whole admin
    DAU/MAU basis, inflatable without bound by an unauthenticated caller.

    Recording the candidate and letting flush_user_last_seen write it only on a
    successful response keeps the 16 relay routes counted (they are authenticated
    by the chain ante rather than by the backend, and a rejected transaction comes
    back as a 400) while a forged pubkey now writes nothing.
    """
    addr = _derive_address_from_pubkey(pub_dec)
    if addr and has_request_context():
        g.last_seen_candidate = addr
    return addr


# Gas estimation buffer (multiplier). Simulation can underestimate due to
# state changes between simulation and execution, and storage write costs
# (WriteFlat) that vary based on key/value sizes.
GAS_BUFFER_MULTIPLIER = 1.25  # C-1: simulate skips some sig-verify cost vs DeliverTx

# Devices kept per account. Comfortably above a real user's phone/tablet/reinstall
# history, and far below Expo's 100-message limit for a single unchunked send.
MAX_PUSH_TOKENS_PER_OWNER = 20
PUSH_TIMESTAMP_SKEW_MS = 5 * 60 * 1000
PUSH_NONCE_TTL_SECONDS = 60 * 60


# ── Quest tracker (lazy singleton, backend-owned DB) ────────────────────────
_quest_tracker_instance = None
_quest_tracker_lock = threading.Lock()


def _get_quest_tracker():
    """Lazy-init the backend quest tracker (uses connect_backend_db)."""
    global _quest_tracker_instance
    if _quest_tracker_instance is None:
        with _quest_tracker_lock:
            if _quest_tracker_instance is None:
                from quest_tracker import QuestTracker

                _quest_tracker_instance = QuestTracker(connect_backend_db)
                logger().debug("Quest tracker initialized")
    return _quest_tracker_instance


def _track_quest_progress(user_addr: str, action_type: str, ts: int, **kwargs) -> None:
    """Fire-and-forget quest progress update after a successful tx."""
    if not QUESTS_ENABLED and not ACHIEVEMENTS_ENABLED:
        logger().debug("quest.tracker.skipped action=%s (quests and achievements disabled)", action_type)
        return
    try:
        qt = _get_quest_tracker()
        qt.update_progress(user_addr, action_type, ts, **kwargs)
    except Exception as e:
        logger().warning("Quest progress tracking failed for %s/%s: %s", user_addr[:12], action_type, e)


def _db_get_profile_level(addr: str) -> int | None:
    """Read profile level from indexer DB. Returns None if profile not found."""
    with connect_db(timeout=3.0, busy_timeout_ms=5000) as conn:
        cur = conn.cursor()
        cur.execute("SELECT level FROM profiles WHERE LOWER(owner) = LOWER(%s) LIMIT 1", (addr,))
        row = cur.fetchone()
        return int(row[0]) if row and row[0] is not None else None


def _db_list_contains(table: str, owner: str, target_col: str, target_val: str) -> bool:
    """Check if a value exists in a profile list table (enabled_agents, followed_users, etc.)."""
    with connect_db(timeout=3.0, busy_timeout_ms=5000) as conn:
        cur = conn.cursor()
        cur.execute(
            f"SELECT 1 FROM {table} WHERE LOWER(owner) = LOWER(%s) AND LOWER({target_col}) = LOWER(%s) LIMIT 1",
            (owner, target_val),
        )
        return cur.fetchone() is not None


def _get_utc_julian_day(ts: int) -> int:
    """Convert Unix timestamp to UTC Julian day number."""
    return 2440588 + (ts // 86400)


def _get_username_for_owner(owner: str) -> str:
    addr = str(owner or "").strip()
    if not addr:
        return ""
    with connect_db(timeout=3.0, busy_timeout_ms=5000) as conn:
        cur = conn.cursor()
        cur.execute("SELECT username FROM profiles WHERE LOWER(owner)=LOWER(%s) LIMIT 1", (addr,))
        row = cur.fetchone()
    if not row or not row[0]:
        return ""
    return str(row[0]).strip()


def _log_user_action(username: str, client_ip: str, action: str, target: str, tx_hash: str) -> None:
    logger().info(
        "user_action username=%s ip=%s action=%s target=%s tx_hash=%s",
        username,
        client_ip,
        action,
        target,
        tx_hash,
    )


def _process_invite_quest_completion(rid: str, new_user_addr: str) -> None:
    """
    Process invite quest completion when a new user sets their username.

    Checks if:
    1. New user used an invite code
    2. Referrer has invite_recruit quest assigned for today and not completed

    If both conditions are met:
    - Marks referrer's invite_recruit quest as completed
    - Creates pending reward for referrer (10k MIRAGE, no multiplier)
    - Creates invite_referred quest for new user (completed) with pending reward
    """
    now_ts = int(time.time())
    day_utc = _get_utc_julian_day(now_ts)

    # Step 1 is keyed on the new user, so it is not contended and needs no lock.
    with connect_backend_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT owner, code FROM invite_codes
                WHERE LOWER(used_by) = LOWER(%s)
                ORDER BY used_at DESC
                LIMIT 1
                """,
                (new_user_addr,),
            )
            invite_row = cur.fetchone()

    if not invite_row:
        log_event(rid, "invite_quest.no_invite_code", new_user=new_user_addr)
        return

    referrer_addr, invite_code = invite_row
    referrer_addr = referrer_addr.lower()
    log_event(rid, "invite_quest.found_referrer", new_user=new_user_addr, referrer=referrer_addr, code=invite_code)

    # Steps 2-6 are a read-decide-write on the referrer's quest row, and the
    # contention is between two *different* new users redeeming codes from the same
    # referrer: both used to read the quest as incomplete and both paid out. The
    # lock is keyed on the referrer for that reason, and shares quest_assignment's
    # key so it also serializes against assignment and completion of the same row.
    with _locked_transaction(f"quest_assignment:{referrer_addr}") as cur:
        # Step 2: Check if referrer has invite_recruit quest for today, not completed
        cur.execute(
            """
            SELECT quest_id, completed_at FROM user_daily_quests
            WHERE LOWER(owner) = LOWER(%s) AND day_utc = %s AND quest_id = 'invite_recruit'
            """,
            (referrer_addr, day_utc),
        )
        quest_row = cur.fetchone()

        if not quest_row:
            log_event(rid, "invite_quest.referrer_no_quest", referrer=referrer_addr, day_utc=day_utc)
            return

        _, completed_at = quest_row
        if completed_at is not None:
            log_event(rid, "invite_quest.referrer_quest_already_completed", referrer=referrer_addr)
            return

        log_event(rid, "invite_quest.completing", referrer=referrer_addr, new_user=new_user_addr)

        # Step 3: Mark referrer's invite_recruit quest as completed
        cur.execute(
            """
            UPDATE user_daily_quests
            SET progress = 1, completed_at = %s
            WHERE LOWER(owner) = LOWER(%s) AND day_utc = %s AND quest_id = 'invite_recruit'
            """,
            (now_ts, referrer_addr, day_utc),
        )

        # Step 4: Insert pending reward for referrer (10k MIRAGE = 10,000,000,000 umirage)
        # Referrer reward DOES get multiplier (apply_multiplier: True)
        reward_amount_umirage = 10000 * 1_000_000  # 10k MIRAGE
        # ON CONFLICT for the same reason as every other pending_rewards insert:
        # without it a collision inside the same second raised mid-sequence, after
        # step 3 had already marked the quest complete, so the referee's reward at
        # step 6 was never written and step 2 short-circuits every retry.
        cur.execute(
            """
            INSERT INTO pending_rewards (owner, reward_type, reward_data, reason, created_at)
            VALUES (%s, 'mirage', %s, 'quest:invite_recruit', %s)
            ON CONFLICT (owner, reward_type, reason, created_at) DO NOTHING
            """,
            (referrer_addr, json.dumps({"amount": reward_amount_umirage, "apply_multiplier": True}), now_ts),
        )
        log_event(rid, "invite_quest.referrer_reward_created", referrer=referrer_addr, amount=reward_amount_umirage)

        # Step 5: Insert invite_referred quest for new user (already completed)
        cur.execute(
            """
            INSERT INTO user_daily_quests (owner, day_utc, quest_id, progress, progress_meta, completed_at)
            VALUES (%s, %s, 'invite_referred', 1, '{}', %s)
            ON CONFLICT (owner, day_utc, quest_id) DO NOTHING
            """,
            (new_user_addr, day_utc, now_ts),
        )

        # Step 6: Insert pending reward for new user (10k MIRAGE)
        # New user reward does NOT get multiplier (they're new, multiplier would be 1x anyway)
        cur.execute(
            """
            INSERT INTO pending_rewards (owner, reward_type, reward_data, reason, created_at)
            VALUES (%s, 'mirage', %s, 'quest:invite_referred', %s)
            ON CONFLICT (owner, reward_type, reason, created_at) DO NOTHING
            """,
            (new_user_addr, json.dumps({"amount": reward_amount_umirage, "apply_multiplier": False}), now_ts),
        )
        log_event(rid, "invite_quest.referee_reward_created", new_user=new_user_addr, amount=reward_amount_umirage)

        log_event(rid, "invite_quest.completed", referrer=referrer_addr, new_user=new_user_addr)


def _parse_envelope_nonce(data: dict):
    """Parse envelope_nonce from request. Returns (nonce, None) or (0, error_response).

    Nonce generation (for clients):
        nonce = (Date.now() * 1_000_000) ^ (rand32)
        Must be >0; for JS keep <=2^53-1. Include in signature.

    v1.20.0: envelope_nonce is mandatory. Requests without it are rejected.
    """
    if "envelope_nonce" not in data:
        return 0, (jsonify({"error": "envelope_nonce is required (v1.20.0)"}), 400)
    raw = data.get("envelope_nonce")
    if not isinstance(raw, (str, int, float)):
        return 0, (jsonify({"error": "invalid envelope_nonce"}), 400)
    try:
        nonce = int(raw)
        if nonce <= 0:
            return 0, (jsonify({"error": "envelope_nonce must be > 0"}), 400)
        if nonce > 0xFFFFFFFFFFFFFFFF:
            return 0, (jsonify({"error": "envelope_nonce exceeds uint64 range"}), 400)
        return nonce, None
    except (TypeError, ValueError):
        return 0, (jsonify({"error": "invalid envelope_nonce"}), 400)


def _guard_push_request(owner: str, action: str, timestamp_ms: int, nonce: int):
    """Reject replayed or stale push-related requests."""
    if timestamp_ms < 10_000_000_000:
        return False, (jsonify({"error": "timestamp must be milliseconds"}), 400)
    now_ms = int(time.time() * 1000)
    if abs(now_ms - timestamp_ms) > PUSH_TIMESTAMP_SKEW_MS:
        return False, (jsonify({"error": "timestamp outside allowed window"}), 400)

    owner_lc = (owner or "").strip().lower()
    if not owner_lc:
        return False, (jsonify({"error": "invalid owner"}), 400)

    try:
        cutoff = int(time.time()) - PUSH_NONCE_TTL_SECONDS
        with connect_backend_db() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM push_nonces WHERE created_at < %s", (cutoff,))
                cur.execute(
                    """
                    INSERT INTO push_nonces (owner, action, nonce, created_at)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                    RETURNING nonce
                    """,
                    (owner_lc, action, nonce, int(time.time())),
                )
                row = cur.fetchone()
                if not row:
                    return False, (jsonify({"error": "replayed envelope_nonce"}), 400)
        return True, None
    except Exception:
        return False, (jsonify({"error": "indexer DB unavailable"}), 503)


def _validate_envelope_timestamp(timestamp_ms: int):
    """Reject envelope timestamps the ante handler is certain to refuse.

    The chain allows max_envelope_age of age and half that (capped at 30s) of
    future skew, measured against block time. Block time is never ahead of now,
    so anything outside this window here is outside it there too — a wider relay
    window only spends a simulate round trip to earn a rejection.
    """
    if timestamp_ms < 10_000_000_000:
        return False, api_error_code("timestamp_must_be_millis")
    max_age_ms = int(expect_params()["max_envelope_age"]) * 1000
    now_ms = int(time.time() * 1000)
    if timestamp_ms - now_ms > max_envelope_future_skew_seconds() * 1000:
        return False, api_error_code("timestamp_outside_window")
    if now_ms - timestamp_ms > max_age_ms:
        return False, api_error_code("timestamp_outside_window")
    return True, None


def _hex_to_bytes(s: str) -> bytes:
    """Convert hex string to bytes for envelope_block_hash."""
    try:
        return bytes.fromhex(s.strip()) if s else b""
    except Exception:
        return b""


def _min_required_difficulty() -> int:
    """Return the minimum required difficulty steps, honouring the chain's
    PowDifficultyGracePeriod window.

    During the grace period after a difficulty change the chain accepts the
    *previous* (possibly lower) difficulty.  The backend precheck must
    mirror this so we don't reject transactions that the chain itself would
    accept.
    """
    info = get_difficulty_info()
    current = int(info["current_difficulty"])
    prev = int(info.get("previous_difficulty", current))
    last_change = int(info.get("last_change_height", 0))
    height = int(info.get("current_height", 0))

    p = expect_params()
    grace_period = int(p.get("pow_difficulty_grace_period", 0))

    min_required = current
    if grace_period > 0 and last_change > 0 and height - last_change <= int(grace_period):
        if prev < min_required:
            min_required = prev
    return min_required


def _effective_difficulty(declared: int) -> int:
    """Mirror chain's PoW threshold logic for difficulty steps."""
    min_required = _min_required_difficulty()
    eff = int(declared)
    if eff < min_required:
        eff = min_required
    return eff


def _log_subscriber_pow_ignored(
    rid: str,
    action: str,
    difficulty: int,
    proof: int,
    has_difficulty: bool | None = None,
    has_pow: bool | None = None,
) -> None:
    if int(difficulty) <= 0 and int(proof) <= 0 and not (has_difficulty or has_pow):
        return
    payload = {"difficulty": int(difficulty), "proof": int(proof)}
    if has_difficulty is not None:
        payload["has_difficulty"] = bool(has_difficulty)
    if has_pow is not None:
        payload["has_pow"] = bool(has_pow)
    log_event(rid, f"{action}.pow_ignored", **payload)


def _pow_factor() -> float:
    p = expect_params()
    return float(p["pow_factor"])


def _client_timestamp(rid: str, action: str, data: Dict[str, Any]) -> int:
    """Return the envelope timestamp exactly as the client sent it.

    follow_topic and unfollow_topic used to substitute `now` when the field was
    absent, which forwards to the chain an envelope_timestamp the user never
    signed. The ante covers the timestamp (canon field 6), so the chain rejected
    it as `invalid relay signature` and the real cause — the missing field — was
    hidden (H-3). Absence is passed through as 0 and logged instead, which the
    chain reports as `envelope_timestamp is required`.
    """
    timestamp = int(data.get("timestamp", 0) or 0)
    if not timestamp:
        log_event(rid, "envelope.timestamp_absent", action=action)
    return timestamp


def _log_pow_precheck_error(rid: str, action: str, exc: Exception) -> None:
    """Record a PoW precheck that could not be evaluated.

    The precheck is advisory — the chain's PowDecorator is authoritative, so a
    precheck that throws must not reject the request (see
    docs/architecture/backend-trust-model.md). It must not vanish either: this
    used to be `except Exception: pass` at 21 sites, which meant a malformed
    field or an Argon2 error silently disabled the check with no way to observe
    the rate. Alert on pow.precheck_error — a sustained rate means the precheck
    is broken and every proof is reaching the chain unscreened.
    """
    logger().warning("[pow.precheck_error] action=%s %s: %s", action, type(exc).__name__, exc)
    log_event(rid, "pow.precheck_error", action=action, error_type=type(exc).__name__, error=str(exc))


def _tx_error(
    rid: str,
    endpoint: str,
    msg_type: str,
    code: int,
    tx_hash: str,
    raw_log: str,
    extra: Dict[str, Any] | None = None,
):
    """
    Standardized error payload for failed chain broadcasts.

    - Normalizes empty raw_log into a generic "rejected" message.
    - Attaches useful context (endpoint, msg_type, code, tx_hash, extra fields).
    - Logs the failure via log_event so we can inspect backend logs.
    """
    info = classify_reject(raw_log)
    if extra:
        try:
            info.update(extra)
        except Exception:
            # Best-effort only; never let logging helpers break the response.
            pass
    info.setdefault("code", code)
    info.setdefault("tx_type", msg_type)
    info.setdefault("endpoint", endpoint)
    info.setdefault("tx_hash", tx_hash)

    # If chain returned an empty or whitespace-only message, normalize it.
    message = (info.get("message") or "").strip() or "rejected"

    # Record a structured log entry for backend debugging.
    try:
        log_event(
            rid,
            f"{endpoint}.reject",
            code=code,
            tx_hash=tx_hash,
            height=extra.get("height") if isinstance(extra, dict) else None,
            raw_log=raw_log,
            details=info,
        )
    except Exception:
        # Never fail the request just because logging failed.
        pass

    return jsonify({"error": message, "details": info, "tx_hash": tx_hash}), 400


def _classify_exception(err_str: str):
    """Return (message, http_status) for common chain exceptions.

    Checks for known error patterns and returns user-safe messages.
    Unknown exceptions get a generic message (details are in server logs).
    """
    # Read the live exception rather than sniffing err_str: every caller is inside
    # an except block, and an indexer outage must be reported as 503
    # indexer_unavailable, not folded into the generic 500 (M-6). Outside an
    # except block sys.exc_info() is empty and this is a no-op.
    if isinstance(sys.exc_info()[1], IndexerUnavailable):
        return get_message("indexer_unavailable"), 503

    low = err_str.lower()
    if "admin insufficient balance" in low:
        return "admin insufficient balance", 400
    if "gift rejected" in low and "level" in low:
        return get_message("gift_rejected_higher_tier"), 400
    if "insufficient balance" in low or "insufficient funds" in low:
        return "insufficient balance", 400
    # Input parsing errors (int(), base64, type coercion)
    if "invalid literal for int()" in low:
        return "invalid input type", 400
    if "int() argument must be" in low:
        return "invalid input type", 400
    if "base64" in low or "incorrect padding" in low:
        return "invalid base64 encoding", 400
    # Ante rejections arrive as HTTP 500 from the tx-service REST, so the 4xx
    # branches below never see them and every one of them used to be reported as
    # an internal error. _validate_envelope_timestamp already bounded the
    # timestamp against our clock, so "in future" means our own block time is
    # stale (the node trails the network) and the client should retry; "too old"
    # means the envelope aged out in flight and must be re-signed.
    if "envelope_timestamp in future" in low:
        return get_message("node_catching_up"), 503
    if "envelope_timestamp too old" in low:
        return get_message("envelope_expired"), 400
    # Chain simulation / broadcast rejections (HTTP 400 from chain = client error)
    if "simulate_gas http 400" in low:
        return "transaction rejected", 400
    if "simulate_gas http 4" in low:
        return "transaction rejected", 400
    return "internal server error", 500


def get_nonce_for_subscriber(last_block_hash: str) -> str:
    """For subscribers without PoW, use timestamp as nonce to ensure tx uniqueness."""
    if last_block_hash:
        return last_block_hash
    import time

    return str(int(time.time()))


def is_subscriber(addr: str) -> bool:
    """Check if user is a paid subscriber via the indexer database (level-based).
    Note: We intentionally do not apply runtime expiry logic here; the chain/indexer
    state must be the source of truth for level transitions.
    """
    # Small in-process TTL cache to avoid hitting the database on every call
    if not hasattr(is_subscriber, "_cache"):
        setattr(is_subscriber, "_cache", {})  # type: ignore[attr-defined]
        setattr(is_subscriber, "_ttl", 10.0)  # seconds  # type: ignore[attr-defined]
    cache: dict[str, tuple[float, bool]] = getattr(is_subscriber, "_cache")  # type: ignore[attr-defined]
    ttl: float = getattr(is_subscriber, "_ttl")  # type: ignore[attr-defined]
    addr_lc = (addr or "").strip().lower()
    if not addr_lc:
        return False
    now = time.time()
    ent = cache.get(addr_lc)
    if ent and (now - ent[0]) < ttl:
        return bool(ent[1])
    try:
        with connect_db(timeout=10.0, busy_timeout_ms=15000) as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT COALESCE(effective_paid, FALSE) FROM profiles WHERE LOWER(owner) = LOWER(%s) LIMIT 1",
                (addr_lc,),
            )
            row = cur.fetchone()
            is_sub = bool(row[0]) if row and row[0] is not None else False
            cache[addr_lc] = (now, is_sub)
            # Bound cache size
            if len(cache) > 4096:
                oldest = min(cache.items(), key=lambda kv: kv[1][0])[0]
                cache.pop(oldest, None)
            return is_sub
    except Exception:
        return False


def _get_post_owner(txhash: str) -> str | None:
    """Return the lowercase owner address for a post txhash, or None if not found or on error."""
    try:
        with connect_db(timeout=10.0, busy_timeout_ms=15000) as conn:
            cur = conn.cursor()
            cur.execute("SELECT owner FROM posts WHERE LOWER(txhash)=LOWER(%s) LIMIT 1", (txhash,))
            row = cur.fetchone()
            return (row[0] or "").strip().lower() if row and row[0] else None
    except Exception:
        return None


def _get_post_quest_info(txhash: str) -> dict | None:
    """Return quest-relevant info (owner, topic, root_post_id) for a post, or None on error."""
    try:
        with connect_db(timeout=3.0, busy_timeout_ms=5000) as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT owner, COALESCE(root_community, community, ''), COALESCE(root_post_id, txhash) "
                "FROM posts WHERE LOWER(txhash)=LOWER(%s) LIMIT 1",
                (txhash,),
            )
            row = cur.fetchone()
            if not row:
                return None
            return {
                "owner": (row[0] or "").strip().lower(),
                "topic": (row[1] or "").strip().lower(),
                "root_post_id": (row[2] or "").strip().lower(),
            }
    except Exception:
        return None


def _is_hex64(s: str) -> bool:
    import re as _re

    return bool(s) and bool(_re.fullmatch(r"(?i)[0-9a-f]{64}", s.strip()))


def _is_valid_mirage_addr(s: str) -> bool:
    import re as _re

    return bool(_re.fullmatch(r"mirage1[0-9a-z]{38}", (s or "").strip()))


def _verify_signature(pub_dec: bytes, sig_dec: bytes, signed_bytes: bytes) -> bool:
    """Verify compact 64-byte (r||s) signature over SHA-256(signed_bytes)."""
    try:
        import hashlib as _hl
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import utils as _utils

        digest = _hl.sha256(signed_bytes).digest()
        r = int.from_bytes(sig_dec[:32], "big")
        s = int.from_bytes(sig_dec[32:], "big")

        def _i2osp(x: int) -> bytes:
            b = x.to_bytes((x.bit_length() + 7) // 8 or 1, "big")
            if b[0] & 0x80:
                b = b"\x00" + b
            return b

        r_b = _i2osp(r)
        s_b = _i2osp(s)
        der = bytes([0x30, 2 + len(r_b) + 2 + len(s_b), 0x02, len(r_b)]) + r_b + bytes([0x02, len(s_b)]) + s_b
        pub = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256K1(), pub_dec)
        pub.verify(der, digest, ec.ECDSA(_utils.Prehashed(hashes.SHA256())))
        if has_request_context():
            g.verified_request_address = _derive_address_from_pubkey(pub_dec)
        return True
    except Exception:
        return False


def flush_user_last_seen(status_code: int) -> None:
    """Write the request's last-seen row, but only if the request succeeded.

    Registered as an after_request hook. A signature-verified address is preferred
    over the merely-derived candidate, since the former is proof of key ownership
    and the latter is only proof that 33 bytes were supplied.
    """
    if not has_request_context() or status_code >= 400:
        return
    addr = getattr(g, "verified_request_address", "") or getattr(g, "last_seen_candidate", "")
    if addr:
        update_user_last_seen(addr, source=request.path)


def _auth_error(message: str, status: int = 401):
    """Authentication failure. 401 (not 403): no proof of identity yet.

    Returns a Flask (response, status) pair ready to return from a route or
    to stash as the error half of (address, err).
    """
    return jsonify({"error": message}), status


def _parse_signed_fields(data: dict):
    """Extract pubkey/signature/timestamp/nonce from a request dict.

    Returns (pub_dec, sig_dec, timestamp, nonce, None) or (None, None, 0, 0, (response, code)).
    """
    pub_b64 = str(data.get("pubkey", "") or "").strip()
    sig_b64 = str(data.get("signature", "") or "").strip()
    if not (pub_b64 and sig_b64):
        return None, None, 0, 0, _auth_error("missing required fields")
    if "timestamp" not in data:
        return None, None, 0, 0, _auth_error("timestamp required")
    try:
        timestamp = int(data.get("timestamp"))
    except (TypeError, ValueError):
        return None, None, 0, 0, _auth_error("invalid timestamp")
    nonce, err = _parse_envelope_nonce(data)
    if err is not None:
        # Re-wrap as 401 so unsigned/malformed proofs are never confused with 403.
        body, _code = err
        try:
            payload = body.get_json(silent=True) if hasattr(body, "get_json") else None
            msg = (payload or {}).get("error") or "invalid envelope_nonce"
        except Exception:
            msg = "invalid envelope_nonce"
        return None, None, 0, 0, _auth_error(msg)
    try:
        pub_dec = base64.b64decode(pub_b64)
        sig_dec = base64.b64decode(sig_b64)
    except Exception:
        return None, None, 0, 0, _auth_error("invalid relay fields")
    if len(sig_dec) == 65:
        sig_dec = sig_dec[:64]
    if len(pub_dec) != 33 or len(sig_dec) != 64:
        return None, None, 0, 0, _auth_error("invalid relay fields")
    return pub_dec, sig_dec, timestamp, nonce, None


def _require_signed_read(data: dict, action: str, expected_address: str):
    """Verify signature + timestamp skew for a read. No push_nonces row.

    Returns (address, None) on success or (None, (response, code)) on failure.
    """
    expected = (expected_address or "").strip().lower()
    if not expected:
        return None, _auth_error("address required")

    pub_dec, sig_dec, timestamp, nonce, err = _parse_signed_fields(data)
    if err is not None:
        return None, err

    if timestamp < 10_000_000_000:
        return None, _auth_error("timestamp must be milliseconds")
    now_ms = int(time.time() * 1000)
    if abs(now_ms - timestamp) > PUSH_TIMESTAMP_SKEW_MS:
        return None, _auth_error("timestamp outside allowed window")

    user_addr = _derive_address_from_pubkey(pub_dec)
    if not user_addr:
        return None, _auth_error("invalid pubkey")
    if user_addr.lower() != expected:
        return None, _auth_error("address does not match pubkey")

    signed_payload = f"{action}:{user_addr.lower()}:{timestamp}:{nonce}"
    if not _verify_signature(pub_dec, sig_dec, signed_payload.encode("utf-8")):
        return None, _auth_error("invalid signature")

    return user_addr.lower(), None


def _require_signed_request(data: dict, action: str, expected_address: str):
    """Verify signature + push-nonce replay guard for a write.

    Returns (address, None) on success or (None, (response, code)) on failure.
    """
    expected = (expected_address or "").strip().lower()
    if not expected:
        return None, _auth_error("address required")

    pub_dec, sig_dec, timestamp, nonce, err = _parse_signed_fields(data)
    if err is not None:
        return None, err

    user_addr = _derive_address_from_pubkey(pub_dec)
    if not user_addr:
        return None, _auth_error("invalid pubkey")
    if user_addr.lower() != expected:
        return None, _auth_error("address does not match pubkey")

    signed_payload = f"{action}:{user_addr.lower()}:{timestamp}:{nonce}"
    if not _verify_signature(pub_dec, sig_dec, signed_payload.encode("utf-8")):
        return None, _auth_error("invalid signature")

    ok, gerr = _guard_push_request(user_addr, action, timestamp, nonce)
    if not ok:
        # Preserve the guard's status (400 replay / 503 DB) but surface as auth
        # failure when the guard returned a 400-class proof problem.
        body, code = gerr
        if code == 400:
            try:
                payload = body.get_json(silent=True) if hasattr(body, "get_json") else None
                msg = (payload or {}).get("error") or "invalid signature"
            except Exception:
                msg = "invalid signature"
            return None, _auth_error(msg)
        return None, gerr

    return user_addr.lower(), None


def get_user_level(addr: str) -> int:
    """Return subscription level for user from indexer DB."""
    try:
        a = (addr or "").strip().lower()
        if not a:
            return 0
        with connect_db(timeout=10.0, busy_timeout_ms=15000) as conn:
            cur = conn.cursor()
            cur.execute("SELECT level FROM profiles WHERE LOWER(owner) = LOWER(%s) LIMIT 1", (a,))
            row = cur.fetchone()
            return int(row[0]) if row and row[0] is not None else 0
    except Exception:
        return 0


@core_bp.route("/api/core/set_username", methods=["POST"])
def core_set_username():
    rid = next_request_id()
    log_event(rid, "set_username.begin")
    try:
        if is_node_catching_up():
            return api_error_code("node_catching_up", 503)
        data = request.get_json(force=True) or {}
        log_event(rid, "set_username.data", data=data)
        pub_b64 = str(data.get("pubkey", "").strip())
        sig_b64 = str(data.get("signature", "").strip())
        username = str(data.get("username", "").strip())
        last_block_hash = str(data.get("last_block_hash", "").strip())
        difficulty = int(data.get("pow_difficulty", 0))
        proof = int(data.get("pow", 0))
        has_difficulty = "pow_difficulty" in data
        has_pow = "pow" in data
        if "timestamp" not in data:
            return jsonify({"error": "timestamp required"}), 400
        try:
            timestamp = int(data.get("timestamp"))
        except (TypeError, ValueError):
            return jsonify({"error": "invalid timestamp"}), 400
        ts_ok, ts_err = _validate_envelope_timestamp(timestamp)
        if not ts_ok:
            log_event(rid, "post.timestamp_invalid", timestamp=timestamp, now_ms=int(time.time() * 1000))
            return ts_err[0], ts_err[1]
        ts_ok, ts_err = _validate_envelope_timestamp(timestamp)
        if not ts_ok:
            log_event(rid, "post.timestamp_invalid", timestamp=timestamp, now_ms=int(time.time() * 1000))
            return ts_err[0], ts_err[1]
        nonce, err = _parse_envelope_nonce(data)
        if err is not None:
            return err[0], err[1]

        # Log what we got
        log_event(
            rid,
            "set_username.parsed",
            pubkey_len=len(pub_b64),
            sig_len=len(sig_b64),
            username=username,
            last_block_hash=last_block_hash[:16] if last_block_hash else "",
            difficulty=difficulty,
            proof=proof,
        )

        if _has_unsafe_chars(username):
            return jsonify({"error": "fields contain invalid control characters"}), 400

        # Minimal required fields; last_block_hash is optional for subscribers
        if not (pub_b64 and sig_b64 and username):
            log_event(
                rid,
                "set_username.missing_fields",
                has_pubkey=bool(pub_b64),
                has_sig=bool(sig_b64),
                has_username=bool(username),
                has_last_block_hash=bool(last_block_hash),
            )
            return jsonify({"error": "missing required fields"}), 400

        pub_dec = base64.b64decode(pub_b64)
        sig_dec = base64.b64decode(sig_b64)
        if len(sig_dec) == 65:
            sig_dec = sig_dec[:64]
        if len(pub_dec) != 33 or len(sig_dec) != 64:
            return jsonify({"error": "invalid relay fields", "pub_len": len(pub_dec), "sig_len": len(sig_dec)}), 400

        user_addr = derive_address_from_pubkey(pub_dec)
        if not user_addr:
            return jsonify({"error": "invalid pubkey"}), 400

        target = str(data.get("target", "")).strip().lower()
        if target and target != user_addr.lower():
            return api_error_code("unauthorized", 403)

        validator_addr = require_runtime().validator_payer_addr

        # Username validation handled below; no title/content checks here

        # Username format and length validation at backend (first line of defense)
        try:
            p = expect_params()
            min_u = int(p.get("min_username_size"))
            max_u = int(p.get("max_username_size"))
        except Exception:
            # Fail hard if params unavailable
            return jsonify({"error": "backend not initialized"}), 503
        if len(username) < min_u:
            return api_error_code("username_too_short")
        if len(username) > max_u:
            return api_error_code("username_too_long")
        if not re.fullmatch(r"[A-Za-z0-9-]+", username):
            return api_error_code("username_invalid_format")

        invite_code = str(data.get("invite_code", "")).strip().upper()
        has_direct_code = bool(invite_code and len(invite_code) == 9 and invite_code[4] == "-")
        # Keep the value as received: the attribution signature covers what the client
        # sent, not what this handler later decides to ignore.
        received_referrer = str(data.get("referrer_username", "")).strip()
        raw_referrer = "" if has_direct_code else received_referrer
        referrer_is_address = raw_referrer.lower().startswith("mirage1")
        referrer_max_length = 64 if referrer_is_address else max_u
        if raw_referrer and len(raw_referrer) > referrer_max_length:
            if REGISTRATION_INVITE_CODE_REQUIRED:
                return api_error_code("referrer_username_too_long")
            log_event(
                rid,
                "set_username.profile_referral_skipped",
                reason="referrer_username_too_long",
                referrer=raw_referrer,
                user=user_addr,
            )
            raw_referrer = ""
        if raw_referrer and not re.fullmatch(r"[A-Za-z0-9-]+", raw_referrer):
            if REGISTRATION_INVITE_CODE_REQUIRED:
                return api_error_code("referrer_username_invalid_format")
            log_event(
                rid,
                "set_username.profile_referral_skipped",
                reason="referrer_username_invalid_format",
                referrer=raw_referrer,
                user=user_addr,
            )
            raw_referrer = ""

        # Free users require PoW; subscribers skip PoW (chain uses reserve)
        if not is_subscriber(user_addr):
            if not (last_block_hash and has_difficulty and has_pow):
                return jsonify({"error": "missing required fields"}), 400
            try:
                base = canon_base_set_username(
                    pub_dec,
                    last_block_hash,
                    int(difficulty),
                    timestamp,
                    user_addr,
                    username,
                    nonce=nonce,
                )
                digest = argon2_digest(base, last_block_hash, proof)
                if digest is not None:
                    effective_required = _effective_difficulty(int(difficulty))
                    if not check_pow_target(digest, effective_required, get_pow_base_bits(), _pow_factor()):
                        return jsonify({"error": "insufficient pow (precheck)"}), 400
            except Exception as _pow_exc:
                _log_pow_precheck_error(rid, "set_username", _pow_exc)
        else:
            _log_subscriber_pow_ignored(rid, "set_username", difficulty, proof, has_difficulty, has_pow)
        # Verify signature over canonical signed bytes
        try:
            base = canon_base_set_username(
                pub_dec,
                last_block_hash,
                int(difficulty),
                timestamp,
                user_addr,
                username,
                nonce=nonce,
            )
            signed = canon_signed_with_pow(base, int(proof))
            if not _verify_signature(pub_dec, sig_dec, signed):
                return jsonify({"error": "invalid signature"}), 400
        except Exception:
            return jsonify({"error": "invalid signature"}), 400

        # invite_code and referrer_username drive the referral reward path but cannot
        # go into the chain envelope, whose shape the ante fixes. They carry their own
        # signature so the signed payload is as wide as the body acted on.
        if invite_code or received_referrer:
            attribution_sig = str(data.get("attribution_signature", "")).strip()
            if not attribution_sig:
                log_event(rid, "set_username.attribution_signature_missing", user=user_addr)
                return api_error_code("attribution_signature_invalid")
            try:
                attr_sig_dec = base64.b64decode(attribution_sig)
            except Exception:
                return api_error_code("attribution_signature_invalid")
            attr_signed = canon_attribution(
                "set_username",
                user_addr,
                invite_code,
                received_referrer,
                nonce,
            )
            if not _verify_signature(pub_dec, attr_sig_dec, attr_signed):
                log_event(rid, "set_username.attribution_signature_invalid", user=user_addr)
                return api_error_code("attribution_signature_invalid")

        referrer_username = raw_referrer
        referrer_address = ""
        referrer_skip_reason = ""

        # Check if this is a new user (no existing profile/username)
        is_new_user = False
        try:
            with connect_db(timeout=10.0, busy_timeout_ms=15000) as conn:
                cur = conn.cursor()
                cur.execute(
                    "SELECT username FROM profiles WHERE LOWER(owner) = LOWER(%s) LIMIT 1",
                    (user_addr,),
                )
                row = cur.fetchone()
                is_new_user = not row or not row[0] or row[0].strip() == ""
        except Exception as db_err:
            log_event(rid, "set_username.profile_check_error", error=str(db_err))
            return jsonify({"error": "indexer DB unavailable"}), 503

        if not REGISTRATION_ENABLED and is_new_user:
            log_event(rid, "set_username.registration_disabled", user=user_addr, username=username)
            return api_error_code("registration_disabled", 403)

        # An explicit invite code owns attribution. Otherwise resolve the profile
        # share referrer independently of invite and reward configuration.
        if is_new_user and referrer_username and not has_direct_code:
            try:
                with connect_db(timeout=10.0, busy_timeout_ms=15000) as conn:
                    cur = conn.cursor()
                    if referrer_is_address:
                        cur.execute(
                            "SELECT owner FROM profiles WHERE LOWER(owner) = LOWER(%s) LIMIT 1",
                            (referrer_username,),
                        )
                    else:
                        cur.execute(
                            "SELECT owner FROM profiles WHERE LOWER(username) = LOWER(%s) LIMIT 1",
                            (referrer_username,),
                        )
                    row = cur.fetchone()
                    if not row:
                        log_event(rid, "set_username.referrer_not_found", referrer=referrer_username, user=user_addr)
                        if REGISTRATION_INVITE_CODE_REQUIRED:
                            return api_error_code("referrer_not_found")
                        referrer_skip_reason = "referrer_not_found"
                    else:
                        referrer_address = row[0].lower()
                        if referrer_address == user_addr.lower():
                            if REGISTRATION_INVITE_CODE_REQUIRED:
                                return api_error_code("self_referral")
                            referrer_skip_reason = "self_referral"
                            referrer_address = ""
                        else:
                            log_event(
                                rid,
                                "set_username.referrer_resolved",
                                referrer=referrer_username,
                                address=referrer_address,
                                user=user_addr,
                            )
                if referrer_skip_reason:
                    log_event(
                        rid,
                        "set_username.profile_referral_skipped",
                        reason=referrer_skip_reason,
                        referrer=referrer_username,
                        user=user_addr,
                    )
                client_hash = _hash_client_ip(_get_trusted_client_ip())
                if referrer_address and client_hash:
                    with connect_backend_db() as bconn:
                        with bconn.cursor() as bcur:
                            bcur.execute(
                                "SELECT 1 FROM referral_links WHERE client_hash = %s AND referrer_address = %s",
                                (client_hash, referrer_address),
                            )
                            if bcur.fetchone():
                                log_event(
                                    rid,
                                    "set_username.referral_client_gate",
                                    referrer=referrer_address,
                                    user=user_addr,
                                )
                                if REGISTRATION_INVITE_CODE_REQUIRED:
                                    return api_error_code("referrer_already_used")
                                log_event(
                                    rid,
                                    "set_username.profile_referral_skipped",
                                    reason="client_gate",
                                    referrer=referrer_address,
                                    user=user_addr,
                                )
                                referrer_address = ""
            except Exception as ref_err:
                log_event(rid, "set_username.referrer_resolve_error", error=str(ref_err))
                return api_error_code("referrer_check_failed", 500)

        if REGISTRATION_INVITE_CODE_REQUIRED and is_new_user:
            if has_direct_code:
                try:
                    with connect_backend_db() as conn:
                        cur = conn.cursor()
                        cur.execute(
                            "SELECT owner, used_by FROM invite_codes WHERE UPPER(code) = %s",
                            (invite_code,),
                        )
                        row = cur.fetchone()
                        if not row:
                            log_event(rid, "set_username.invite_code_invalid", code=invite_code, user=user_addr)
                            return api_error_code("invite_code_invalid")
                        owner, used_by = row
                        if used_by:
                            log_event(
                                rid,
                                "set_username.invite_code_already_used",
                                code=invite_code,
                                user=user_addr,
                                used_by=used_by,
                            )
                            return api_error_code("invite_code_used")
                        log_event(rid, "set_username.invite_code_validated", code=invite_code, user=user_addr)
                except Exception as invite_check_err:
                    log_event(rid, "set_username.invite_code_check_error", error=str(invite_check_err))
                    return api_error_code("invite_code_check_failed", 500)
            elif referrer_address:
                try:
                    with connect_backend_db() as conn:
                        with conn.cursor() as cur:
                            cur.execute(
                                "SELECT precheck_enabled FROM referral_user_settings WHERE owner = %s",
                                (referrer_address,),
                            )
                            settings_row = cur.fetchone()
                            cur.execute(
                                "SELECT 1 FROM invite_codes WHERE LOWER(owner) = %s AND used_by IS NULL LIMIT 1",
                                (referrer_address,),
                            )
                            available_code = cur.fetchone()
                    if not settings_row or settings_row[0] is not True or not available_code:
                        log_event(
                            rid,
                            "set_username.referrer_cannot_invite",
                            referrer=referrer_address,
                            user=user_addr,
                        )
                        return api_error_code("invite_code_required")
                except Exception as ref_invite_err:
                    log_event(rid, "set_username.referrer_invite_check_error", error=str(ref_invite_err))
                    return api_error_code("invite_code_check_failed", 500)
            else:
                log_event(rid, "set_username.invite_code_required", user=user_addr, username=username)
                return api_error_code("invite_code_required")

        msg = MsgSetUsername()
        # authority is the validator/node address relaying this transaction, NOT the user's address
        msg.authority = validator_addr
        msg.envelope_pubkey = pub_dec
        msg.envelope_block_hash = _hex_to_bytes(last_block_hash)
        msg.envelope_difficulty = int(difficulty)
        msg.envelope_pow = int(proof)
        msg.envelope_timestamp = timestamp
        msg.envelope_nonce = nonce
        msg.envelope_signature = sig_dec
        msg.target = user_addr
        msg.username = username

        any_msg = AnyPB()
        any_msg.type_url = "/mirage.core.v1.MsgSetUsername"
        any_msg.value = msg.SerializeToString()
        body = TxBody(messages=[any_msg], memo="")
        body_bytes = body.SerializeToString()
        content_len = len(msg.username)
        gas_est = int(estimate_total_gas_limit(body_bytes, content_len))
        tx_bytes_est = build_tx_bytes(body_bytes, gas_est, zero_fee=is_subscriber(user_addr))
        gas_used = int(simulate_gas(tx_bytes_est))
        gas_limit = max(gas_est, int(gas_used * GAS_BUFFER_MULTIPLIER))
        tx_hash, code, height, raw_log = build_and_broadcast_tx(
            body_bytes, gas_limit, zero_fee=is_subscriber(user_addr)
        )
        if code != 0:
            extra = {
                "height": height,
                "username": username,
                "user_addr": user_addr,
                "last_block_hash": last_block_hash,
                "difficulty": int(difficulty),
                "proof": int(proof),
            }
            return _tx_error(rid, "core/set_username", "MsgSetUsername", code, tx_hash, raw_log, extra)

        # ── Post-tx: profile-share referral attribution ──
        if referrer_address and is_new_user and code == 0:
            try:
                now_ts = int(time.time())
                conn = connect_backend_db()
                conn.autocommit = False
                try:
                    with conn.cursor() as cur:
                        if REGISTRATION_INVITE_CODE_REQUIRED:
                            cur.execute(
                                """
                                UPDATE invite_codes SET used_by = %s, used_at = %s
                                WHERE code = (
                                    SELECT code FROM invite_codes
                                    WHERE LOWER(owner) = %s AND used_by IS NULL
                                    LIMIT 1
                                )
                                RETURNING code
                                """,
                                (user_addr.lower(), now_ts, referrer_address),
                            )
                            row = cur.fetchone()
                            if not row:
                                raise RuntimeError("validated referral invite code is no longer available")
                            log_event(
                                rid,
                                "set_username.referral_code_applied",
                                code=row[0],
                                referrer=referrer_address,
                                user=user_addr,
                            )
                        client_hash = _hash_client_ip(_get_trusted_client_ip())
                        cur.execute(
                            """
                            INSERT INTO referral_links (user_address, referrer_address, referred_at, client_hash)
                            VALUES (%s, %s, %s, %s)
                            ON CONFLICT (user_address) DO NOTHING
                            """,
                            (user_addr.lower(), referrer_address, now_ts, client_hash),
                        )
                    conn.commit()
                    log_event(
                        rid,
                        "set_username.profile_referral_recorded",
                        referrer=referrer_address,
                        user=user_addr,
                    )
                except Exception:
                    conn.rollback()
                    raise
                finally:
                    conn.close()
            except Exception as ref_err:
                log_event(rid, "set_username.profile_referral_error", error=str(ref_err))

        # ── Post-tx: record referral from direct address (legacy path) ──
        elif is_new_user and not referrer_address:
            referrer = str(data.get("referrer", "")).strip().lower()
            if referrer and referrer.startswith("mirage1") and len(referrer) >= 39:
                if referrer != user_addr.lower():
                    try:
                        now_ts = int(time.time())
                        with connect_backend_db() as conn:
                            with conn.cursor() as cur:
                                cur.execute(
                                    """
                                    INSERT INTO referral_links (user_address, referrer_address, referred_at)
                                    VALUES (%s, %s, %s)
                                    ON CONFLICT (user_address) DO NOTHING
                                    """,
                                    (user_addr.lower(), referrer, now_ts),
                                )
                        log_event(rid, "set_username.referral_recorded", user=user_addr, referrer=referrer)
                    except Exception as ref_err:
                        log_event(rid, "set_username.referral_error", error=str(ref_err))

        # Mark direct invite code as used (must happen BEFORE quest completion check)
        if is_new_user and has_direct_code and code == 0 and not referrer_address:
            try:
                now_ts = int(time.time())
                with connect_backend_db() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            UPDATE invite_codes 
                            SET used_by = %s, used_at = %s 
                            WHERE UPPER(code) = %s AND used_by IS NULL
                            RETURNING owner
                            """,
                            (user_addr.lower(), now_ts, invite_code),
                        )
                        row = cur.fetchone()
                        if row:
                            owner = row[0]
                            log_event(rid, "set_username.invite_code_used", code=invite_code, user=user_addr)
                            # Bridge invite-code redemption → referral_links so the
                            # /api/referrals/summary endpoint (which only reads
                            # referral_links) reflects direct-code redemptions,
                            # not just username-based referrals. Historically
                            # path-3 only updated invite_codes and this bridge
                            # was missing, so direct-code referrers appeared as
                            # zero-referral accounts.
                            client_hash = _hash_client_ip(_get_trusted_client_ip())
                            cur.execute(
                                """
                                INSERT INTO referral_links (user_address, referrer_address, referred_at, client_hash)
                                VALUES (%s, %s, %s, %s)
                                ON CONFLICT (user_address) DO NOTHING
                                """,
                                (user_addr.lower(), owner, now_ts, client_hash),
                            )
                        else:
                            log_event(rid, "set_username.invite_code_already_used_or_invalid", code=invite_code)
            except Exception as ic_err:
                log_event(rid, "set_username.invite_code_error", error=str(ic_err))

        # Ensure referral settings row exists for this user (default: disabled)
        try:
            now_ts = int(time.time())
            with connect_backend_db() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO referral_user_settings (owner, precheck_enabled, updated_at)
                        VALUES (%s, FALSE, %s)
                        ON CONFLICT (owner) DO NOTHING
                        """,
                        (user_addr.lower(), now_ts),
                    )
        except Exception as settings_err:
            log_event(rid, "set_username.referral_settings_init_error", error=str(settings_err))

        # Check for invite quest completion (referrer has invite_recruit, new user used their code)
        # Registration only. The invite_codes redemption row is permanent, so running
        # this for an already-registered user re-pays both sides 10k MIRAGE every time
        # the referrer is re-assigned the quest — a username change is enough to trigger it.
        if is_new_user and code == 0:
            try:
                _process_invite_quest_completion(rid, user_addr.lower())
            except Exception as invite_err:
                log_event(rid, "set_username.invite_quest_error", error=str(invite_err))

        return jsonify({"tx_hash": tx_hash, "code": code, "height": height, "raw_log": raw_log})
    except Exception as e:
        err_str = str(e)
        log_event(rid, "set_username.err", error=err_str)
        msg, status = _classify_exception(err_str)
        return jsonify({"error": msg}), status


@core_bp.route("/api/core/set_biography", methods=["POST"])
def core_set_biography():
    rid = next_request_id()
    log_event(rid, "set_biography.begin")
    try:
        if is_node_catching_up():
            return api_error_code("node_catching_up", 503)
        data = request.get_json(force=True) or {}
        log_event(rid, "set_biography.data", data=data)
        pub_b64 = str(data.get("pubkey", "").strip())
        sig_b64 = str(data.get("signature", "").strip())
        biography = str(data.get("biography", ""))
        last_block_hash = str(data.get("last_block_hash", "").strip())
        difficulty = int(data.get("pow_difficulty", 0))
        proof = int(data.get("pow", 0))
        has_difficulty = "pow_difficulty" in data
        has_pow = "pow" in data
        if "timestamp" not in data:
            return jsonify({"error": "timestamp required"}), 400
        try:
            timestamp = int(data.get("timestamp"))
        except (TypeError, ValueError):
            return jsonify({"error": "invalid timestamp"}), 400
        nonce, err = _parse_envelope_nonce(data)
        if err is not None:
            return err[0], err[1]

        log_event(
            rid,
            "set_biography.parsed",
            pubkey_len=len(pub_b64),
            sig_len=len(sig_b64),
            biography_len=len(biography),
            last_block_hash=last_block_hash[:16] if last_block_hash else "",
            difficulty=difficulty,
            proof=proof,
        )

        if _has_unsafe_chars(biography):
            return jsonify({"error": "fields contain invalid control characters"}), 400

        if not (pub_b64 and sig_b64):
            return jsonify({"error": "missing required fields"}), 400

        if len(biography) > 512:
            return api_error_code("biography_too_long")

        pub_dec = base64.b64decode(pub_b64)
        sig_dec = base64.b64decode(sig_b64)
        if len(sig_dec) == 65:
            sig_dec = sig_dec[:64]
        if len(pub_dec) != 33 or len(sig_dec) != 64:
            return jsonify({"error": "invalid relay fields", "pub_len": len(pub_dec), "sig_len": len(sig_dec)}), 400

        user_addr = derive_address_from_pubkey(pub_dec)
        if not user_addr:
            return jsonify({"error": "invalid pubkey"}), 400

        validator_addr = require_runtime().validator_payer_addr

        # Free users require PoW; subscribers skip PoW (chain uses reserve)
        if not is_subscriber(user_addr):
            if not (last_block_hash and has_difficulty and has_pow):
                return jsonify({"error": "missing required fields"}), 400
            try:
                base = canon_base_set_biography(
                    pub_dec,
                    last_block_hash,
                    int(difficulty),
                    timestamp,
                    user_addr,
                    biography,
                    nonce=nonce,
                )
                digest = argon2_digest(base, last_block_hash, proof)
                if digest is not None:
                    effective_required = _effective_difficulty(int(difficulty))
                    if not check_pow_target(digest, effective_required, get_pow_base_bits(), _pow_factor()):
                        return jsonify({"error": "insufficient pow (precheck)"}), 400
            except Exception as _pow_exc:
                _log_pow_precheck_error(rid, "set_biography", _pow_exc)
        else:
            _log_subscriber_pow_ignored(rid, "set_biography", difficulty, proof, has_difficulty, has_pow)

        # Verify signature over canonical signed bytes
        try:
            base = canon_base_set_biography(
                pub_dec,
                last_block_hash,
                int(difficulty),
                timestamp,
                user_addr,
                biography,
                nonce=nonce,
            )
            signed = canon_signed_with_pow(base, int(proof))
            if not _verify_signature(pub_dec, sig_dec, signed):
                return jsonify({"error": "invalid signature"}), 400
        except Exception:
            return jsonify({"error": "invalid signature"}), 400

        msg = MsgSetBiography()
        msg.authority = validator_addr
        msg.envelope_pubkey = pub_dec
        msg.envelope_block_hash = _hex_to_bytes(last_block_hash)
        msg.envelope_difficulty = int(difficulty)
        msg.envelope_pow = int(proof)
        msg.envelope_timestamp = timestamp
        msg.envelope_nonce = nonce
        msg.envelope_signature = sig_dec
        msg.target = user_addr
        msg.biography = biography

        any_msg = AnyPB()
        any_msg.type_url = "/mirage.core.v1.MsgSetBiography"
        any_msg.value = msg.SerializeToString()
        body = TxBody(messages=[any_msg], memo="")
        body_bytes = body.SerializeToString()
        content_len = len(msg.biography)
        gas_est = int(estimate_total_gas_limit(body_bytes, content_len))
        tx_bytes_est = build_tx_bytes(body_bytes, gas_est, zero_fee=is_subscriber(user_addr))
        gas_used = int(simulate_gas(tx_bytes_est))
        gas_limit = max(gas_est, int(gas_used * GAS_BUFFER_MULTIPLIER))
        tx_hash, code, height, raw_log = build_and_broadcast_tx(
            body_bytes, gas_limit, zero_fee=is_subscriber(user_addr)
        )
        if code != 0:
            extra = {
                "height": height,
                "user_addr": user_addr,
                "biography_len": len(biography),
                "last_block_hash": last_block_hash,
                "difficulty": int(difficulty),
                "proof": int(proof),
            }
            return _tx_error(rid, "core/set_biography", "MsgSetBiography", code, tx_hash, raw_log, extra)

        log_event(rid, "set_biography.ok", tx_hash=tx_hash, user=user_addr, biography_len=len(biography))
        return jsonify({"tx_hash": tx_hash, "code": code, "height": height, "raw_log": raw_log})
    except Exception as e:
        err_str = str(e)
        log_event(rid, "set_biography.err", error=err_str)
        msg, status = _classify_exception(err_str)
        return jsonify({"error": msg}), status


@core_bp.route("/api/core/enable_agent", methods=["POST"])
def core_enable_agent():
    rid = next_request_id()
    log_event(rid, "enable_agent.begin")
    try:
        if is_node_catching_up():
            return api_error_code("node_catching_up", 503)
        data = request.get_json(force=True) or {}
        log_event(rid, "enable_agent.data", data=data)
        pub_b64 = str(data.get("pubkey", "").strip())
        sig_b64 = str(data.get("signature", "").strip())
        agent = str(data.get("agent", "").strip())
        last_block_hash = str(data.get("last_block_hash", "").strip())
        difficulty = int(data.get("pow_difficulty", 0))
        proof = int(data.get("pow", 0))
        has_difficulty = "pow_difficulty" in data
        has_pow = "pow" in data
        if "timestamp" not in data:
            return jsonify({"error": "timestamp required"}), 400
        try:
            timestamp = int(data.get("timestamp"))
        except (TypeError, ValueError):
            return jsonify({"error": "invalid timestamp"}), 400
        nonce, err = _parse_envelope_nonce(data)
        if err is not None:
            return err[0], err[1]

        if not (pub_b64 and sig_b64 and agent):
            return jsonify({"error": "missing required fields"}), 400
        if not _is_valid_mirage_addr(agent):
            return api_error_code("invalid_agent_address")

        pub_dec = base64.b64decode(pub_b64)
        sig_dec = base64.b64decode(sig_b64)
        if len(sig_dec) == 65:
            sig_dec = sig_dec[:64]
        if len(pub_dec) != 33 or len(sig_dec) != 64:
            return jsonify({"error": "invalid relay fields"}), 400

        user_addr = derive_address_from_pubkey(pub_dec)
        if not user_addr:
            return jsonify({"error": "invalid pubkey"}), 400
        if user_addr.lower() == agent.lower():
            log_event(rid, "enable_agent.self_not_allowed", agent=agent, user_addr=user_addr)
            return api_error_code("cannot_enable_self_as_agent")

        # Check if agent is already enabled (indexer DB)
        try:
            if _db_list_contains("enabled_agents", user_addr, "agent", agent):
                log_event(rid, "enable_agent.already_enabled", agent=agent, user_addr=user_addr)
                return api_error_code("agent_already_enabled")
        except Exception as db_err:
            log_event(rid, "enable_agent.db_error", error=str(db_err))
            return jsonify({"error": "indexer DB unavailable"}), 503

        validator_addr = require_runtime().validator_payer_addr

        if not is_subscriber(user_addr):
            required = _min_required_difficulty()
            if int(difficulty) < int(required):
                return jsonify({"error": "insufficient pow (precheck)"}), 400
            if not _is_hex64(last_block_hash):
                return jsonify({"error": "invalid last_block_hash"}), 400
            if not is_valid_recent_block_hash(last_block_hash):
                return jsonify({"error": "invalid last_block_hash"}), 400
            try:
                base = canon_base_enable_agent(
                    pub_dec, last_block_hash, int(difficulty), timestamp, user_addr, agent, nonce=nonce
                )
                digest = argon2_digest(base, last_block_hash, proof)
                if digest is not None and not check_pow_target(
                    digest, _effective_difficulty(int(difficulty)), get_pow_base_bits(), _pow_factor()
                ):
                    return jsonify({"error": "insufficient pow (precheck)"}), 400
            except Exception as _pow_exc:
                _log_pow_precheck_error(rid, "enable_agent", _pow_exc)
        else:
            _log_subscriber_pow_ignored(rid, "enable_agent", difficulty, proof, has_difficulty, has_pow)

        msg = MsgEnableAgent()
        msg.authority = validator_addr
        msg.envelope_pubkey = pub_dec
        msg.envelope_block_hash = _hex_to_bytes(last_block_hash)
        msg.envelope_difficulty = int(difficulty)
        msg.envelope_pow = int(proof)
        msg.envelope_timestamp = timestamp
        msg.envelope_nonce = nonce
        msg.envelope_signature = sig_dec
        msg.target = user_addr
        msg.agent = agent

        any_msg = AnyPB()
        any_msg.type_url = "/mirage.core.v1.MsgEnableAgent"
        any_msg.value = msg.SerializeToString()
        body = TxBody(messages=[any_msg], memo="")
        body_bytes = body.SerializeToString()
        gas_est = int(estimate_total_gas_limit(body_bytes, len(agent)))
        tx_bytes_est = build_tx_bytes(body_bytes, gas_est, zero_fee=is_subscriber(user_addr))
        gas_used = int(simulate_gas(tx_bytes_est))
        gas_limit = max(gas_est, int(gas_used * GAS_BUFFER_MULTIPLIER))
        tx_hash, code, height, raw_log = build_and_broadcast_tx(
            body_bytes, gas_limit, zero_fee=is_subscriber(user_addr)
        )
        if code != 0:
            extra = {
                "height": height,
                "user_addr": user_addr,
                "agent": agent,
                "last_block_hash": last_block_hash,
                "difficulty": int(difficulty),
                "proof": int(proof),
            }
            return _tx_error(rid, "core/enable_agent", "MsgEnableAgent", code, tx_hash, raw_log, extra)
        return jsonify({"tx_hash": tx_hash, "code": code, "height": height, "raw_log": raw_log})
    except Exception as e:
        log_event(rid, "enable_agent.err", error=str(e))
        msg, status = _classify_exception(str(e))
        return jsonify({"error": msg}), status


@core_bp.route("/api/core/disable_agent", methods=["POST"])
def core_disable_agent():
    rid = next_request_id()
    log_event(rid, "disable_agent.begin")
    try:
        if is_node_catching_up():
            return api_error_code("node_catching_up", 503)
        data = request.get_json(force=True) or {}
        pub_b64 = str(data.get("pubkey", "").strip())
        sig_b64 = str(data.get("signature", "").strip())
        agent = str(data.get("agent", "").strip())
        last_block_hash = str(data.get("last_block_hash", "").strip())
        difficulty = int(data.get("pow_difficulty", 0))
        proof = int(data.get("pow", 0))
        if "timestamp" not in data:
            return jsonify({"error": "timestamp required"}), 400
        try:
            timestamp = int(data.get("timestamp"))
        except (TypeError, ValueError):
            return jsonify({"error": "invalid timestamp"}), 400
        nonce, err = _parse_envelope_nonce(data)
        if err is not None:
            return err[0], err[1]

        if not (pub_b64 and sig_b64 and agent):
            return jsonify({"error": "missing required fields"}), 400

        pub_dec = base64.b64decode(pub_b64)
        sig_dec = base64.b64decode(sig_b64)
        if len(sig_dec) == 65:
            sig_dec = sig_dec[:64]
        if len(pub_dec) != 33 or len(sig_dec) != 64:
            return jsonify({"error": "invalid relay fields"}), 400

        user_addr = derive_address_from_pubkey(pub_dec)
        if not user_addr:
            return jsonify({"error": "invalid pubkey"}), 400

        validator_addr = require_runtime().validator_payer_addr

        if not is_subscriber(user_addr):
            required = _min_required_difficulty()
            if int(difficulty) < int(required):
                return jsonify({"error": "insufficient pow (precheck)"}), 400
            if not _is_hex64(last_block_hash):
                return jsonify({"error": "invalid last_block_hash"}), 400
            if not is_valid_recent_block_hash(last_block_hash):
                return jsonify({"error": "invalid last_block_hash"}), 400
            try:
                base = canon_base_disable_agent(
                    pub_dec, last_block_hash, int(difficulty), timestamp, user_addr, agent, nonce=nonce
                )
                digest = argon2_digest(base, last_block_hash, proof)
                if digest is not None and not check_pow_target(
                    digest, _effective_difficulty(int(difficulty)), get_pow_base_bits(), _pow_factor()
                ):
                    return jsonify({"error": "insufficient pow (precheck)"}), 400
            except Exception as _pow_exc:
                _log_pow_precheck_error(rid, "disable_agent", _pow_exc)
        else:
            _log_subscriber_pow_ignored(rid, "disable_agent", difficulty, proof)

        msg = MsgDisableAgent()
        msg.authority = validator_addr
        msg.envelope_pubkey = pub_dec
        msg.envelope_block_hash = _hex_to_bytes(last_block_hash)
        msg.envelope_difficulty = int(difficulty)
        msg.envelope_pow = int(proof)
        msg.envelope_timestamp = timestamp
        msg.envelope_nonce = nonce
        msg.envelope_signature = sig_dec
        msg.target = user_addr
        msg.agent = agent

        any_msg = AnyPB()
        any_msg.type_url = "/mirage.core.v1.MsgDisableAgent"
        any_msg.value = msg.SerializeToString()
        body = TxBody(messages=[any_msg], memo="")
        body_bytes = body.SerializeToString()
        gas_est = int(estimate_total_gas_limit(body_bytes, len(agent)))
        tx_bytes_est = build_tx_bytes(body_bytes, gas_est, zero_fee=is_subscriber(user_addr))
        gas_used = int(simulate_gas(tx_bytes_est))
        gas_limit = max(gas_est, int(gas_used * GAS_BUFFER_MULTIPLIER))
        tx_hash, code, height, raw_log = build_and_broadcast_tx(
            body_bytes, gas_limit, zero_fee=is_subscriber(user_addr)
        )
        if code != 0:
            extra = {
                "height": height,
                "user_addr": user_addr,
                "agent": agent,
                "last_block_hash": last_block_hash,
                "difficulty": int(difficulty),
                "proof": int(proof),
            }
            return _tx_error(rid, "core/disable_agent", "MsgDisableAgent", code, tx_hash, raw_log, extra)
        return jsonify({"tx_hash": tx_hash, "code": code, "height": height, "raw_log": raw_log})
    except Exception as e:
        log_event(rid, "disable_agent.err", error=str(e))
        msg, status = _classify_exception(str(e))
        return jsonify({"error": msg}), status


@core_bp.route("/api/core/set_agents", methods=["POST"])
def core_set_agents():
    rid = next_request_id()
    log_event(rid, "set_agents.begin")
    try:
        if is_node_catching_up():
            return api_error_code("node_catching_up", 503)
        data = request.get_json(force=True) or {}
        log_event(rid, "set_agents.data", data=data)
        pub_b64 = str(data.get("pubkey", "").strip())
        sig_b64 = str(data.get("signature", "").strip())
        agents_raw = data.get("agents")
        if not isinstance(agents_raw, list):
            return api_error_code("agents_must_be_array")
        agents = [str(a).strip().lower() for a in agents_raw]
        last_block_hash = str(data.get("last_block_hash", "").strip())
        difficulty = int(data.get("pow_difficulty", 0))
        proof = int(data.get("pow", 0))
        if "timestamp" not in data:
            return jsonify({"error": "timestamp required"}), 400
        try:
            timestamp = int(data.get("timestamp"))
        except (TypeError, ValueError):
            return jsonify({"error": "invalid timestamp"}), 400
        nonce, err = _parse_envelope_nonce(data)
        if err is not None:
            return err[0], err[1]

        if not (pub_b64 and sig_b64):
            return jsonify({"error": "missing required fields"}), 400

        for a in agents:
            if not _is_valid_mirage_addr(a):
                return jsonify({"error": "invalid agent address", "agent": a}), 400

        seen = set()
        for a in agents:
            if a in seen:
                return jsonify({"error": "duplicate agent", "agent": a}), 400
            seen.add(a)

        pub_dec = base64.b64decode(pub_b64)
        sig_dec = base64.b64decode(sig_b64)
        if len(sig_dec) == 65:
            sig_dec = sig_dec[:64]
        if len(pub_dec) != 33 or len(sig_dec) != 64:
            return jsonify({"error": "invalid relay fields"}), 400

        user_addr = derive_address_from_pubkey(pub_dec)
        if not user_addr:
            return jsonify({"error": "invalid pubkey"}), 400

        if user_addr.lower() in agents:
            return api_error_code("cannot_set_self_as_agent")

        # Enforce max_enabled_agents from chain params (fail hard if missing)
        params = expect_params()
        tiers = params.get("tiers")
        if not isinstance(tiers, list) or not tiers:
            return api_error_code("missing_tier_config", 500)

        try:
            user_level = _db_get_profile_level(user_addr)
        except Exception as db_err:
            log_event(rid, "set_agents.db_error", error=str(db_err))
            return jsonify({"error": "indexer DB unavailable"}), 503
        if user_level is None:
            return api_error_code("missing_profile_level", 500)

        idx = {0: 0, 1: 1, 10: 2}.get(user_level, 2 if user_level >= 100 else -1)
        if idx < 0 or idx >= len(tiers):
            return jsonify({"error": "invalid user level", "user_level": user_level}), 500
        tier_cfg = tiers[idx] or {}
        if "max_enabled_agents" not in tier_cfg:
            return api_error_code("missing_max_agents", 500)
        max_agents = int(tier_cfg.get("max_enabled_agents"))
        if len(agents) > max_agents:
            log_event(rid, "set_agents.limit_exceeded", count=len(agents), max=max_agents)
            return jsonify({"error": "too many agents", "count": len(agents), "max": max_agents}), 400

        validator_addr = require_runtime().validator_payer_addr

        if not is_subscriber(user_addr):
            required = _min_required_difficulty()
            if int(difficulty) < int(required):
                return jsonify({"error": "insufficient pow (precheck)"}), 400
            if not _is_hex64(last_block_hash):
                return jsonify({"error": "invalid last_block_hash"}), 400
            if not is_valid_recent_block_hash(last_block_hash):
                return jsonify({"error": "invalid last_block_hash"}), 400
            try:
                base = canon_base_set_agents(
                    pub_dec, last_block_hash, int(difficulty), timestamp, user_addr, agents, nonce=nonce
                )
                digest = argon2_digest(base, last_block_hash, proof)
                if digest is not None and not check_pow_target(
                    digest, _effective_difficulty(int(difficulty)), get_pow_base_bits(), _pow_factor()
                ):
                    return jsonify({"error": "insufficient pow (precheck)"}), 400
            except Exception as _pow_exc:
                _log_pow_precheck_error(rid, "set_agents", _pow_exc)
        else:
            _log_subscriber_pow_ignored(rid, "set_agents", difficulty, proof)

        msg = MsgSetAgents()
        msg.authority = validator_addr
        msg.envelope_pubkey = pub_dec
        msg.envelope_block_hash = _hex_to_bytes(last_block_hash)
        msg.envelope_difficulty = int(difficulty)
        msg.envelope_pow = int(proof)
        msg.envelope_timestamp = timestamp
        msg.envelope_nonce = nonce
        msg.envelope_signature = sig_dec
        msg.target = user_addr
        for a in agents:
            msg.agents.append(a)

        any_msg = AnyPB()
        any_msg.type_url = "/mirage.core.v1.MsgSetAgents"
        any_msg.value = msg.SerializeToString()
        body = TxBody(messages=[any_msg], memo="")
        body_bytes = body.SerializeToString()
        payload_size = sum(len(a) for a in agents)
        gas_est = int(estimate_total_gas_limit(body_bytes, payload_size))
        tx_bytes_est = build_tx_bytes(body_bytes, gas_est, zero_fee=is_subscriber(user_addr))
        gas_used = int(simulate_gas(tx_bytes_est))
        gas_limit = max(gas_est, int(gas_used * GAS_BUFFER_MULTIPLIER))
        tx_hash, code, height, raw_log = build_and_broadcast_tx(
            body_bytes, gas_limit, zero_fee=is_subscriber(user_addr)
        )
        if code != 0:
            extra = {
                "height": height,
                "user_addr": user_addr,
                "agents": agents,
                "last_block_hash": last_block_hash,
                "difficulty": int(difficulty),
                "proof": int(proof),
            }
            return _tx_error(rid, "core/set_agents", "MsgSetAgents", code, tx_hash, raw_log, extra)
        log_event(rid, "set_agents.ok", tx_hash=tx_hash, count=len(agents))
        return jsonify({"tx_hash": tx_hash, "code": code, "height": height, "raw_log": raw_log})
    except Exception as e:
        log_event(rid, "set_agents.err", error=str(e))
        msg_str, status = _classify_exception(str(e))
        return jsonify({"error": msg_str}), status


@core_bp.route("/api/core/block_post", methods=["POST"])
def core_block_post():
    rid = next_request_id()
    log_event(rid, "block_post.begin")
    try:
        if is_node_catching_up():
            return api_error_code("node_catching_up", 503)
        data = request.get_json(force=True) or {}
        log_event(rid, "block_post.data", data=data)
        pub_b64 = str(data.get("pubkey", "").strip())
        sig_b64 = str(data.get("signature", "").strip())
        target = str(data.get("target", "").strip()).lower()

        last_block_hash = str(data.get("last_block_hash", "").strip())
        difficulty = int(data.get("pow_difficulty", 0))
        proof = int(data.get("pow", 0))
        if "timestamp" not in data:
            return jsonify({"error": "timestamp required"}), 400
        try:
            timestamp = int(data.get("timestamp"))
        except (TypeError, ValueError):
            return jsonify({"error": "invalid timestamp"}), 400
        nonce, err = _parse_envelope_nonce(data)
        if err is not None:
            return err[0], err[1]

        log_event(
            rid,
            "block_post.parsed",
            pubkey_len=len(pub_b64),
            sig_len=len(sig_b64),
            target=target[:16] if target else "",
            last_block_hash=last_block_hash[:16] if last_block_hash else "",
            difficulty=difficulty,
            proof=proof,
        )

        if not (pub_b64 and sig_b64 and target):
            log_event(
                rid,
                "block_post.missing_fields",
                has_pubkey=bool(pub_b64),
                has_sig=bool(sig_b64),
                has_last_block_hash=bool(last_block_hash),
                has_target=bool(target),
            )
            return jsonify({"error": "missing required fields"}), 400

        pub_dec = base64.b64decode(pub_b64)
        sig_dec = base64.b64decode(sig_b64)
        if len(sig_dec) == 65:
            sig_dec = sig_dec[:64]
        if len(pub_dec) != 33 or len(sig_dec) != 64:
            return jsonify({"error": "invalid relay fields", "pub_len": len(pub_dec), "sig_len": len(sig_dec)}), 400

        user_addr = derive_address_from_pubkey(pub_dec)
        if not user_addr:
            return jsonify({"error": "invalid pubkey"}), 400

        # Check if post is already blocked (indexer DB)
        try:
            if _db_list_contains("blocked_posts", user_addr, "target", target):
                log_event(rid, "block_post.already_blocked", target=target, user_addr=user_addr)
                return jsonify({"error": "post is already blocked"}), 400
        except Exception as db_err:
            log_event(rid, "block_post.db_error", error=str(db_err))
            return jsonify({"error": "indexer DB unavailable"}), 503

        validator_addr = require_runtime().validator_payer_addr

        if not is_subscriber(user_addr):
            try:
                base = canon_base_block_post(pub_dec, last_block_hash, int(difficulty), timestamp, target, nonce=nonce)
                digest = argon2_digest(base, last_block_hash, proof)
                if digest is not None:
                    effective_required = _effective_difficulty(int(difficulty))
                    if not check_pow_target(digest, effective_required, get_pow_base_bits(), _pow_factor()):
                        return jsonify({"error": "insufficient pow (precheck)"}), 400
            except Exception as _pow_exc:
                _log_pow_precheck_error(rid, "block_post", _pow_exc)
        else:
            _log_subscriber_pow_ignored(rid, "block_post", difficulty, proof)

        msg = MsgBlockPost()
        msg.authority = validator_addr
        msg.envelope_pubkey = pub_dec
        msg.envelope_block_hash = _hex_to_bytes(last_block_hash)
        msg.envelope_difficulty = int(difficulty)
        msg.envelope_pow = int(proof)
        msg.envelope_timestamp = int(timestamp)
        msg.envelope_nonce = nonce
        msg.envelope_signature = sig_dec
        msg.target = target

        any_msg = AnyPB()
        any_msg.type_url = "/mirage.core.v1.MsgBlockPost"
        any_msg.value = msg.SerializeToString()
        body = TxBody(messages=[any_msg], memo="")
        body_bytes = body.SerializeToString()
        gas_est = int(estimate_total_gas_limit(body_bytes, len(target)))
        tx_bytes_est = build_tx_bytes(body_bytes, gas_est, zero_fee=is_subscriber(user_addr))
        gas_used = int(simulate_gas(tx_bytes_est))
        gas_limit = max(gas_est, int(gas_used * GAS_BUFFER_MULTIPLIER))
        tx_hash, code, height, raw_log = build_and_broadcast_tx(
            body_bytes, gas_limit, zero_fee=is_subscriber(user_addr)
        )
        if code != 0:
            extra = {
                "height": height,
                "target": target,
                "last_block_hash": last_block_hash,
                "difficulty": int(difficulty),
                "proof": int(proof),
            }
            return _tx_error(rid, "core/block_post", "MsgBlockPost", code, tx_hash, raw_log, extra)
        return jsonify({"tx_hash": tx_hash, "code": code, "height": height, "raw_log": raw_log})
    except Exception as e:
        log_event(rid, "block_post.err", error=str(e))
        msg, status = _classify_exception(str(e))
        return jsonify({"error": msg}), status


@core_bp.route("/api/core/block_user", methods=["POST"])
def core_block_user():
    rid = next_request_id()
    log_event(rid, "block_user.begin")
    try:
        if is_node_catching_up():
            return api_error_code("node_catching_up", 503)
        data = request.get_json(force=True) or {}
        log_event(rid, "block_user.data", data=data)
        pub_b64 = str(data.get("pubkey", "").strip())
        sig_b64 = str(data.get("signature", "").strip())
        target = str(data.get("target", "").strip()).lower()

        last_block_hash = str(data.get("last_block_hash", "").strip())
        difficulty = int(data.get("pow_difficulty", 0))
        proof = int(data.get("pow", 0))
        if "timestamp" not in data:
            return jsonify({"error": "timestamp required"}), 400
        try:
            timestamp = int(data.get("timestamp"))
        except (TypeError, ValueError):
            return jsonify({"error": "invalid timestamp"}), 400
        nonce, err = _parse_envelope_nonce(data)
        if err is not None:
            return err[0], err[1]

        log_event(
            rid,
            "block_user.parsed",
            pubkey_len=len(pub_b64),
            sig_len=len(sig_b64),
            target=target,
            last_block_hash=last_block_hash[:16] if last_block_hash else "",
            difficulty=difficulty,
            proof=proof,
        )

        if not (pub_b64 and sig_b64 and target):
            log_event(
                rid,
                "block_user.missing_fields",
                has_pubkey=bool(pub_b64),
                has_sig=bool(sig_b64),
                has_last_block_hash=bool(last_block_hash),
                has_target=bool(target),
            )
            return jsonify({"error": "missing required fields"}), 400

        pub_dec = base64.b64decode(pub_b64)
        sig_dec = base64.b64decode(sig_b64)
        if len(sig_dec) == 65:
            sig_dec = sig_dec[:64]
        if len(pub_dec) != 33 or len(sig_dec) != 64:
            return jsonify({"error": "invalid relay fields", "pub_len": len(pub_dec), "sig_len": len(sig_dec)}), 400

        user_addr = derive_address_from_pubkey(pub_dec)
        if not user_addr:
            return jsonify({"error": "invalid pubkey"}), 400

        if user_addr.lower() == target.lower():
            log_event(rid, "block_user.self_block", user_addr=user_addr)
            return api_error_code("cannot_block_self")

        # Check if user is already blocked (indexer DB)
        try:
            if _db_list_contains("blocked_users", user_addr, "target", target):
                log_event(rid, "block_user.already_blocked", target=target, user_addr=user_addr)
                return jsonify({"error": "user is already blocked"}), 400
        except Exception as db_err:
            log_event(rid, "block_user.db_error", error=str(db_err))
            return jsonify({"error": "indexer DB unavailable"}), 503

        validator_addr = require_runtime().validator_payer_addr

        if not is_subscriber(user_addr):
            try:
                base = canon_base_block_user(pub_dec, last_block_hash, int(difficulty), timestamp, target, nonce=nonce)
                digest = argon2_digest(base, last_block_hash, proof)
                if digest is not None:
                    effective_required = _effective_difficulty(int(difficulty))
                    if not check_pow_target(digest, effective_required, get_pow_base_bits(), _pow_factor()):
                        return jsonify({"error": "insufficient pow (precheck)"}), 400
            except Exception as _pow_exc:
                _log_pow_precheck_error(rid, "block_user", _pow_exc)
        else:
            _log_subscriber_pow_ignored(rid, "block_user", difficulty, proof)

        msg = MsgBlockUser()
        msg.authority = validator_addr
        msg.envelope_pubkey = pub_dec
        msg.envelope_block_hash = _hex_to_bytes(last_block_hash)
        msg.envelope_difficulty = int(difficulty)
        msg.envelope_pow = int(proof)
        msg.envelope_timestamp = int(timestamp)
        msg.envelope_nonce = nonce
        msg.envelope_signature = sig_dec
        msg.target = target

        any_msg = AnyPB()
        any_msg.type_url = "/mirage.core.v1.MsgBlockUser"
        any_msg.value = msg.SerializeToString()
        body = TxBody(messages=[any_msg], memo="")
        body_bytes = body.SerializeToString()
        gas_est = int(estimate_total_gas_limit(body_bytes, len(target)))
        tx_bytes_est = build_tx_bytes(body_bytes, gas_est, zero_fee=is_subscriber(user_addr))
        gas_used = int(simulate_gas(tx_bytes_est))
        gas_limit = max(gas_est, int(gas_used * GAS_BUFFER_MULTIPLIER))
        tx_hash, code, height, raw_log = build_and_broadcast_tx(
            body_bytes, gas_limit, zero_fee=is_subscriber(user_addr)
        )
        if code != 0:
            extra = {
                "height": height,
                "target": target,
                "last_block_hash": last_block_hash,
                "difficulty": int(difficulty),
                "proof": int(proof),
            }
            return _tx_error(rid, "core/block_user", "MsgBlockUser", code, tx_hash, raw_log, extra)
        return jsonify({"tx_hash": tx_hash, "code": code, "height": height, "raw_log": raw_log})
    except Exception as e:
        log_event(rid, "block_user.err", error=str(e))
        msg, status = _classify_exception(str(e))
        return jsonify({"error": msg}), status


@core_bp.route("/api/core/unblock_post", methods=["POST"])
def core_unblock_post():
    rid = next_request_id()
    log_event(rid, "unblock_post.begin")
    try:
        if is_node_catching_up():
            return api_error_code("node_catching_up", 503)
        data = request.get_json(force=True) or {}
        pub_b64 = str(data.get("pubkey", "").strip())
        sig_b64 = str(data.get("signature", "").strip())
        target = str(data.get("target", "").strip()).lower()
        last_block_hash = str(data.get("last_block_hash", "").strip())
        difficulty = int(data.get("pow_difficulty", 0))
        proof = int(data.get("pow", 0))
        if "timestamp" not in data:
            return jsonify({"error": "timestamp required"}), 400
        try:
            timestamp = int(data.get("timestamp"))
        except (TypeError, ValueError):
            return jsonify({"error": "invalid timestamp"}), 400
        nonce, err = _parse_envelope_nonce(data)
        if err is not None:
            return err[0], err[1]

        if not (pub_b64 and sig_b64 and target):
            return jsonify({"error": "missing required fields"}), 400

        pub_dec = base64.b64decode(pub_b64)
        sig_dec = base64.b64decode(sig_b64)
        if len(sig_dec) == 65:
            sig_dec = sig_dec[:64]
        if len(pub_dec) != 33 or len(sig_dec) != 64:
            return jsonify({"error": "invalid relay fields"}), 400

        user_addr = derive_address_from_pubkey(pub_dec)
        if not user_addr:
            return jsonify({"error": "invalid pubkey"}), 400

        validator_addr = require_runtime().validator_payer_addr

        if not is_subscriber(user_addr):
            try:
                base = canon_base_unblock_post(
                    pub_dec, last_block_hash, int(difficulty), timestamp, target, nonce=nonce
                )
                digest = argon2_digest(base, last_block_hash, proof)
                if digest is not None:
                    effective_required = _effective_difficulty(int(difficulty))
                    if not check_pow_target(digest, effective_required, get_pow_base_bits(), _pow_factor()):
                        return jsonify({"error": "insufficient pow (precheck)"}), 400
            except Exception as _pow_exc:
                _log_pow_precheck_error(rid, "unblock_post", _pow_exc)
        else:
            _log_subscriber_pow_ignored(rid, "unblock_post", difficulty, proof)

        msg = MsgUnblockPost()
        msg.authority = validator_addr
        msg.envelope_pubkey = pub_dec
        msg.envelope_block_hash = _hex_to_bytes(last_block_hash)
        msg.envelope_difficulty = int(difficulty)
        msg.envelope_pow = int(proof)
        msg.envelope_timestamp = int(timestamp)
        msg.envelope_nonce = nonce
        msg.envelope_signature = sig_dec
        msg.target = target

        any_msg = AnyPB()
        any_msg.type_url = "/mirage.core.v1.MsgUnblockPost"
        any_msg.value = msg.SerializeToString()
        body = TxBody(messages=[any_msg], memo="")
        body_bytes = body.SerializeToString()
        gas_est = int(estimate_total_gas_limit(body_bytes, len(target)))
        tx_bytes_est = build_tx_bytes(body_bytes, gas_est, zero_fee=is_subscriber(user_addr))
        gas_used = int(simulate_gas(tx_bytes_est))
        gas_limit = max(gas_est, int(gas_used * GAS_BUFFER_MULTIPLIER))
        tx_hash, code, height, raw_log = build_and_broadcast_tx(
            body_bytes, gas_limit, zero_fee=is_subscriber(user_addr)
        )
        if code != 0:
            extra = {
                "height": height,
                "target": target,
                "last_block_hash": last_block_hash,
                "difficulty": int(difficulty),
                "proof": int(proof),
            }
            return _tx_error(rid, "core/unblock_post", "MsgUnblockPost", code, tx_hash, raw_log, extra)
        return jsonify({"tx_hash": tx_hash, "code": code, "height": height, "raw_log": raw_log})
    except Exception as e:
        log_event(rid, "unblock_post.err", error=str(e))
        msg, status = _classify_exception(str(e))
        return jsonify({"error": msg}), status


@core_bp.route("/api/core/unblock_user", methods=["POST"])
def core_unblock_user():
    rid = next_request_id()
    log_event(rid, "unblock_user.begin")
    try:
        if is_node_catching_up():
            return api_error_code("node_catching_up", 503)
        data = request.get_json(force=True) or {}
        pub_b64 = str(data.get("pubkey", "").strip())
        sig_b64 = str(data.get("signature", "").strip())
        target = str(data.get("target", "").strip()).lower()
        last_block_hash = str(data.get("last_block_hash", "").strip())
        difficulty = int(data.get("pow_difficulty", 0))
        proof = int(data.get("pow", 0))
        if "timestamp" not in data:
            return jsonify({"error": "timestamp required"}), 400
        try:
            timestamp = int(data.get("timestamp"))
        except (TypeError, ValueError):
            return jsonify({"error": "invalid timestamp"}), 400
        nonce, err = _parse_envelope_nonce(data)
        if err is not None:
            return err[0], err[1]

        if not (pub_b64 and sig_b64 and target):
            return jsonify({"error": "missing required fields"}), 400

        pub_dec = base64.b64decode(pub_b64)
        sig_dec = base64.b64decode(sig_b64)
        if len(sig_dec) == 65:
            sig_dec = sig_dec[:64]
        if len(pub_dec) != 33 or len(sig_dec) != 64:
            return jsonify({"error": "invalid relay fields"}), 400

        user_addr = derive_address_from_pubkey(pub_dec)
        if not user_addr:
            return jsonify({"error": "invalid pubkey"}), 400

        validator_addr = require_runtime().validator_payer_addr

        if not is_subscriber(user_addr):
            try:
                base = canon_base_unblock_user(
                    pub_dec, last_block_hash, int(difficulty), timestamp, target, nonce=nonce
                )
                digest = argon2_digest(base, last_block_hash, proof)
                if digest is not None:
                    effective_required = _effective_difficulty(int(difficulty))
                    if not check_pow_target(digest, effective_required, get_pow_base_bits(), _pow_factor()):
                        return jsonify({"error": "insufficient pow (precheck)"}), 400
            except Exception as _pow_exc:
                _log_pow_precheck_error(rid, "unblock_user", _pow_exc)
        else:
            _log_subscriber_pow_ignored(rid, "unblock_user", difficulty, proof)

        msg = MsgUnblockUser()
        msg.authority = validator_addr
        msg.envelope_pubkey = pub_dec
        msg.envelope_block_hash = _hex_to_bytes(last_block_hash)
        msg.envelope_difficulty = int(difficulty)
        msg.envelope_pow = int(proof)
        msg.envelope_timestamp = int(timestamp)
        msg.envelope_nonce = nonce
        msg.envelope_signature = sig_dec
        msg.target = target

        any_msg = AnyPB()
        any_msg.type_url = "/mirage.core.v1.MsgUnblockUser"
        any_msg.value = msg.SerializeToString()
        body = TxBody(messages=[any_msg], memo="")
        body_bytes = body.SerializeToString()
        gas_est = int(estimate_total_gas_limit(body_bytes, len(target)))
        tx_bytes_est = build_tx_bytes(body_bytes, gas_est, zero_fee=is_subscriber(user_addr))
        gas_used = int(simulate_gas(tx_bytes_est))
        gas_limit = max(gas_est, int(gas_used * GAS_BUFFER_MULTIPLIER))
        tx_hash, code, height, raw_log = build_and_broadcast_tx(
            body_bytes, gas_limit, zero_fee=is_subscriber(user_addr)
        )
        if code != 0:
            extra = {
                "height": height,
                "target": target,
                "last_block_hash": last_block_hash,
                "difficulty": int(difficulty),
                "proof": int(proof),
            }
            return _tx_error(rid, "core/unblock_user", "MsgUnblockUser", code, tx_hash, raw_log, extra)
        return jsonify({"tx_hash": tx_hash, "code": code, "height": height, "raw_log": raw_log})
    except Exception as e:
        log_event(rid, "unblock_user.err", error=str(e))
        msg, status = _classify_exception(str(e))
        return jsonify({"error": msg}), status


@core_bp.route("/api/core/block_topic", methods=["POST"])
def core_block_topic():
    rid = next_request_id()
    log_event(rid, "block_topic.begin")
    try:
        if is_node_catching_up():
            return api_error_code("node_catching_up", 503)
        data = request.get_json(force=True) or {}
        log_event(rid, "block_topic.data", data=data)
        pub_b64 = str(data.get("pubkey", "").strip())
        sig_b64 = str(data.get("signature", "").strip())
        topic = str(data.get("topic", "").strip()).lower()

        last_block_hash = str(data.get("last_block_hash", "").strip())
        difficulty = int(data.get("pow_difficulty", 0))
        proof = int(data.get("pow", 0))
        if "timestamp" not in data:
            return jsonify({"error": "timestamp required"}), 400
        try:
            timestamp = int(data.get("timestamp"))
        except (TypeError, ValueError):
            return jsonify({"error": "invalid timestamp"}), 400
        nonce, err = _parse_envelope_nonce(data)
        if err is not None:
            return err[0], err[1]

        import re

        if not topic:
            return jsonify({"error": "invalid topic format"}), 400
        # Allow * as glob wildcard anywhere in blocked topic patterns
        _topic_alpha = topic.replace("*", "")
        if not _topic_alpha or not re.fullmatch(r"[a-z0-9]+", _topic_alpha):
            return jsonify({"error": "invalid topic format"}), 400
        if "**" in topic:
            return jsonify({"error": "invalid topic format"}), 400
        # The chain bounds the alphanumerics but leaves the wildcards free, so a
        # 35-character topic limit still admits 34 of them. That was the input to
        # the backend's backtracking matcher; the matcher is linear now, but the
        # SQL pre-filter's LIKE is not, so the count stays bounded at the door.
        if count_wildcards(topic) > MAX_TOPIC_WILDCARDS:
            log_event(rid, "block_topic.too_many_wildcards", wildcards=count_wildcards(topic))
            return api_error_code("topic_too_many_wildcards")

        p = expect_params()
        min_topic = int(p.get("min_topic_size", 2))
        max_topic = int(p.get("max_topic_size", 35))
        if len(_topic_alpha) < min_topic:
            return jsonify({"error": "topic too short"}), 400
        if len(_topic_alpha) > max_topic:
            return jsonify({"error": "topic too long"}), 400

        if not (pub_b64 and sig_b64):
            log_event(rid, "block_topic.missing_fields", has_pubkey=bool(pub_b64), has_sig=bool(sig_b64))
            return jsonify({"error": "missing required fields"}), 400

        pub_dec = base64.b64decode(pub_b64)
        sig_dec = base64.b64decode(sig_b64)
        if len(sig_dec) == 65:
            sig_dec = sig_dec[:64]
        if len(pub_dec) != 33 or len(sig_dec) != 64:
            return jsonify({"error": "invalid relay fields", "pub_len": len(pub_dec), "sig_len": len(sig_dec)}), 400

        user_addr = derive_address_from_pubkey(pub_dec)
        if not user_addr:
            return jsonify({"error": "invalid pubkey"}), 400

        # Check if topic is already blocked (indexer DB)
        try:
            if _db_list_contains("blocked_topics", user_addr, "target", topic):
                log_event(rid, "block_topic.already_blocked", topic=topic, user_addr=user_addr)
                return jsonify({"error": "topic is already blocked"}), 400
        except Exception as db_err:
            log_event(rid, "block_topic.db_error", error=str(db_err))
            return jsonify({"error": "indexer DB unavailable"}), 503

        validator_addr = require_runtime().validator_payer_addr

        if not is_subscriber(user_addr):
            try:
                base = canon_base_block_topic(
                    pub_dec, last_block_hash, int(difficulty), timestamp, "", topic, nonce=nonce
                )
                digest = argon2_digest(base, last_block_hash, proof)
                if digest is not None:
                    effective_required = _effective_difficulty(int(difficulty))
                    if not check_pow_target(digest, effective_required, get_pow_base_bits(), _pow_factor()):
                        return jsonify({"error": "insufficient pow (precheck)"}), 400
            except Exception as _pow_exc:
                _log_pow_precheck_error(rid, "block_topic", _pow_exc)
        else:
            _log_subscriber_pow_ignored(rid, "block_topic", difficulty, proof)

        msg = MsgBlockTopic()
        msg.authority = validator_addr
        msg.envelope_pubkey = pub_dec
        msg.envelope_block_hash = _hex_to_bytes(last_block_hash)
        msg.envelope_difficulty = int(difficulty)
        msg.envelope_pow = int(proof)
        msg.envelope_timestamp = int(timestamp)
        msg.envelope_nonce = nonce
        msg.envelope_signature = sig_dec
        msg.target = ""
        msg.topic = topic

        any_msg = AnyPB()
        any_msg.type_url = "/mirage.core.v1.MsgBlockTopic"
        any_msg.value = msg.SerializeToString()
        body = TxBody(messages=[any_msg], memo="")
        body_bytes = body.SerializeToString()
        gas_est = int(estimate_total_gas_limit(body_bytes, len(topic)))
        tx_bytes_est = build_tx_bytes(body_bytes, gas_est, zero_fee=is_subscriber(user_addr))
        gas_used = int(simulate_gas(tx_bytes_est))
        gas_limit = max(gas_est, int(gas_used * GAS_BUFFER_MULTIPLIER))
        tx_hash, code, height, raw_log = build_and_broadcast_tx(
            body_bytes, gas_limit, zero_fee=is_subscriber(user_addr)
        )
        if code != 0:
            extra = {
                "height": height,
                "topic": topic,
                "last_block_hash": last_block_hash,
                "difficulty": int(difficulty),
                "proof": int(proof),
            }
            return _tx_error(rid, "core/block_topic", "MsgBlockTopic", code, tx_hash, raw_log, extra)
        return jsonify({"tx_hash": tx_hash, "code": code, "height": height, "raw_log": raw_log})
    except Exception as e:
        log_event(rid, "block_topic.err", error=str(e))
        msg, status = _classify_exception(str(e))
        return jsonify({"error": msg}), status


@core_bp.route("/api/core/unblock_topic", methods=["POST"])
def core_unblock_topic():
    rid = next_request_id()
    log_event(rid, "unblock_topic.begin")
    try:
        if is_node_catching_up():
            return api_error_code("node_catching_up", 503)
        data = request.get_json(force=True) or {}
        pub_b64 = str(data.get("pubkey", "").strip())
        sig_b64 = str(data.get("signature", "").strip())
        topic = str(data.get("topic", "").strip()).lower()
        last_block_hash = str(data.get("last_block_hash", "").strip())
        difficulty = int(data.get("pow_difficulty", 0))
        proof = int(data.get("pow", 0))
        if "timestamp" not in data:
            return jsonify({"error": "timestamp required"}), 400
        try:
            timestamp = int(data.get("timestamp"))
        except (TypeError, ValueError):
            return jsonify({"error": "invalid timestamp"}), 400
        nonce, err = _parse_envelope_nonce(data)
        if err is not None:
            return err[0], err[1]

        if not (pub_b64 and sig_b64 and topic):
            return jsonify({"error": "missing required fields"}), 400

        pub_dec = base64.b64decode(pub_b64)
        sig_dec = base64.b64decode(sig_b64)
        if len(sig_dec) == 65:
            sig_dec = sig_dec[:64]
        if len(pub_dec) != 33 or len(sig_dec) != 64:
            return jsonify({"error": "invalid relay fields"}), 400

        user_addr = derive_address_from_pubkey(pub_dec)
        if not user_addr:
            return jsonify({"error": "invalid pubkey"}), 400

        validator_addr = require_runtime().validator_payer_addr

        if not is_subscriber(user_addr):
            try:
                base = canon_base_unblock_topic(
                    pub_dec, last_block_hash, int(difficulty), timestamp, "", topic, nonce=nonce
                )
                digest = argon2_digest(base, last_block_hash, proof)
                if digest is not None:
                    effective_required = _effective_difficulty(int(difficulty))
                    if not check_pow_target(digest, effective_required, get_pow_base_bits(), _pow_factor()):
                        return jsonify({"error": "insufficient pow (precheck)"}), 400
            except Exception as _pow_exc:
                _log_pow_precheck_error(rid, "unblock_topic", _pow_exc)
        else:
            _log_subscriber_pow_ignored(rid, "unblock_topic", difficulty, proof)

        msg = MsgUnblockTopic()
        msg.authority = validator_addr
        msg.envelope_pubkey = pub_dec
        msg.envelope_block_hash = _hex_to_bytes(last_block_hash)
        msg.envelope_difficulty = int(difficulty)
        msg.envelope_pow = int(proof)
        msg.envelope_timestamp = int(timestamp)
        msg.envelope_nonce = nonce
        msg.envelope_signature = sig_dec
        msg.target = ""
        msg.topic = topic

        any_msg = AnyPB()
        any_msg.type_url = "/mirage.core.v1.MsgUnblockTopic"
        any_msg.value = msg.SerializeToString()
        body = TxBody(messages=[any_msg], memo="")
        body_bytes = body.SerializeToString()
        gas_est = int(estimate_total_gas_limit(body_bytes, len(topic)))
        tx_bytes_est = build_tx_bytes(body_bytes, gas_est, zero_fee=is_subscriber(user_addr))
        gas_used = int(simulate_gas(tx_bytes_est))
        gas_limit = max(gas_est, int(gas_used * GAS_BUFFER_MULTIPLIER))
        tx_hash, code, height, raw_log = build_and_broadcast_tx(
            body_bytes, gas_limit, zero_fee=is_subscriber(user_addr)
        )
        if code != 0:
            extra = {
                "height": height,
                "topic": topic,
                "last_block_hash": last_block_hash,
                "difficulty": int(difficulty),
                "proof": int(proof),
            }
            return _tx_error(rid, "core/unblock_topic", "MsgUnblockTopic", code, tx_hash, raw_log, extra)
        return jsonify({"tx_hash": tx_hash, "code": code, "height": height, "raw_log": raw_log})
    except Exception as e:
        log_event(rid, "unblock_topic.err", error=str(e))
        msg, status = _classify_exception(str(e))
        return jsonify({"error": msg}), status


@core_bp.route("/api/core/follow_user", methods=["POST"])
def core_follow_user():
    rid = next_request_id()
    log_event(rid, "follow_user.begin")
    try:
        if is_node_catching_up():
            return api_error_code("node_catching_up", 503)
        data = request.get_json(force=True) or {}
        pub_b64 = str(data.get("pubkey", "").strip())
        sig_b64 = str(data.get("signature", "").strip())
        target = str(data.get("target", "").strip()).lower()
        user = str(data.get("user", "").strip()).lower()
        last_block_hash = str(data.get("last_block_hash", "").strip())
        difficulty = int(data.get("pow_difficulty", 0))
        proof = int(data.get("pow", 0))
        if "timestamp" not in data:
            return jsonify({"error": "timestamp required"}), 400
        try:
            timestamp = int(data.get("timestamp"))
        except (TypeError, ValueError):
            return jsonify({"error": "invalid timestamp"}), 400
        nonce, err = _parse_envelope_nonce(data)
        if err is not None:
            return err[0], err[1]

        if not (pub_b64 and sig_b64 and target and user):
            return jsonify({"error": "missing required fields"}), 400

        pub_dec = base64.b64decode(pub_b64)
        sig_dec = base64.b64decode(sig_b64)
        if len(sig_dec) == 65:
            sig_dec = sig_dec[:64]
        if len(pub_dec) != 33 or len(sig_dec) != 64:
            return jsonify({"error": "invalid relay fields"}), 400

        user_addr = derive_address_from_pubkey(pub_dec)
        if not user_addr:
            return jsonify({"error": "invalid pubkey"}), 400

        if not _is_valid_mirage_addr(target):
            return api_error_code("target_must_be_mirage1")
        if not _is_valid_mirage_addr(user):
            return api_error_code("user_must_be_mirage1")

        if user_addr.lower() == user.lower():
            log_event(rid, "follow_user.self_follow", user_addr=user_addr)
            return api_error_code("cannot_follow_self")

        # Check if user is already followed (indexer DB)
        try:
            if _db_list_contains("followed_users", user_addr, "target", user):
                log_event(rid, "follow_user.already_followed", user=user, user_addr=user_addr)
                return jsonify({"error": "user is already followed"}), 400
        except Exception as db_err:
            log_event(rid, "follow_user.db_error", error=str(db_err))
            return jsonify({"error": "indexer DB unavailable"}), 503

        validator_addr = require_runtime().validator_payer_addr

        if not is_subscriber(user_addr):
            try:
                base = canon_base_follow_user(
                    pub_dec, last_block_hash, int(difficulty), timestamp, target, user, nonce=nonce
                )
                digest = argon2_digest(base, last_block_hash, proof)
                if digest is not None:
                    effective_required = _effective_difficulty(int(difficulty))
                    if not check_pow_target(digest, effective_required, get_pow_base_bits(), _pow_factor()):
                        return jsonify({"error": "insufficient pow (precheck)"}), 400
            except Exception as _pow_exc:
                _log_pow_precheck_error(rid, "follow_user", _pow_exc)

        msg = MsgFollowUser()
        msg.authority = validator_addr
        msg.envelope_pubkey = pub_dec
        msg.envelope_block_hash = _hex_to_bytes(last_block_hash)
        msg.envelope_difficulty = int(difficulty)
        msg.envelope_pow = int(proof)
        msg.envelope_timestamp = timestamp
        msg.envelope_nonce = nonce
        msg.envelope_signature = sig_dec
        msg.target = target
        msg.user = user

        any_msg = AnyPB()
        any_msg.type_url = "/mirage.core.v1.MsgFollowUser"
        any_msg.value = msg.SerializeToString()
        body = TxBody(messages=[any_msg], memo="")
        body_bytes = body.SerializeToString()
        gas_est = int(estimate_total_gas_limit(body_bytes, len(target) + len(user)))
        tx_bytes_est = build_tx_bytes(body_bytes, gas_est, zero_fee=is_subscriber(user_addr))
        gas_used = int(simulate_gas(tx_bytes_est))
        gas_limit = max(gas_est, int(gas_used * GAS_BUFFER_MULTIPLIER))
        tx_hash, code, height, raw_log = build_and_broadcast_tx(
            body_bytes, gas_limit, zero_fee=is_subscriber(user_addr)
        )
        if code != 0:
            extra = {
                "height": height,
                "user_addr": user_addr,
                "last_block_hash": last_block_hash,
                "difficulty": int(difficulty),
                "proof": int(proof),
            }
            return _tx_error(rid, "core/follow_user", "MsgFollowUser", code, tx_hash, raw_log, extra)
        log_event(rid, "follow_user.success", tx_hash=tx_hash, target=user)
        if user_addr.lower() != user.lower():
            event_key = follow_event_key(user_addr, user, tx_hash)
            inserted = record_inbox_event(
                event_key=event_key,
                recipient=user,
                actor=user_addr,
                event_type="follow",
                created_at=int(time.time()),
                tx_hash=tx_hash,
            )
            log_event(
                rid,
                "follow_user.notify",
                recipient=user,
                actor=user_addr,
                tx_hash=tx_hash,
                inserted=inserted,
            )
            from routes.public import _invalidate_inbox_cache

            _invalidate_inbox_cache(user)
        return jsonify({"tx_hash": tx_hash, "code": code, "height": height, "raw_log": raw_log})
    except Exception as e:
        log_event(rid, "follow_user.err", error=str(e))
        msg, status = _classify_exception(str(e))
        return jsonify({"error": msg}), status


@core_bp.route("/api/core/unfollow_user", methods=["POST"])
def core_unfollow_user():
    rid = next_request_id()
    log_event(rid, "unfollow_user.begin")
    try:
        if is_node_catching_up():
            return api_error_code("node_catching_up", 503)
        data = request.get_json(force=True) or {}
        pub_b64 = str(data.get("pubkey", "").strip())
        sig_b64 = str(data.get("signature", "").strip())
        target = str(data.get("target", "").strip()).lower()
        user = str(data.get("user", "").strip()).lower()
        last_block_hash = str(data.get("last_block_hash", "").strip())
        difficulty = int(data.get("pow_difficulty", 0))
        proof = int(data.get("pow", 0))
        if "timestamp" not in data:
            return jsonify({"error": "timestamp required"}), 400
        try:
            timestamp = int(data.get("timestamp"))
        except (TypeError, ValueError):
            return jsonify({"error": "invalid timestamp"}), 400
        nonce, err = _parse_envelope_nonce(data)
        if err is not None:
            return err[0], err[1]

        if not (pub_b64 and sig_b64 and target and user):
            return jsonify({"error": "missing required fields"}), 400

        pub_dec = base64.b64decode(pub_b64)
        sig_dec = base64.b64decode(sig_b64)
        if len(sig_dec) == 65:
            sig_dec = sig_dec[:64]
        if len(pub_dec) != 33 or len(sig_dec) != 64:
            return jsonify({"error": "invalid relay fields"}), 400

        user_addr = derive_address_from_pubkey(pub_dec)
        if not user_addr:
            return jsonify({"error": "invalid pubkey"}), 400

        validator_addr = require_runtime().validator_payer_addr

        if not is_subscriber(user_addr):
            try:
                base = canon_base_unfollow_user(
                    pub_dec, last_block_hash, int(difficulty), timestamp, target, user, nonce=nonce
                )
                digest = argon2_digest(base, last_block_hash, proof)
                if digest is not None:
                    effective_required = _effective_difficulty(int(difficulty))
                    if not check_pow_target(digest, effective_required, get_pow_base_bits(), _pow_factor()):
                        return jsonify({"error": "insufficient pow (precheck)"}), 400
            except Exception as _pow_exc:
                _log_pow_precheck_error(rid, "unfollow_user", _pow_exc)

        msg = MsgUnfollowUser()
        msg.authority = validator_addr
        msg.envelope_pubkey = pub_dec
        msg.envelope_block_hash = _hex_to_bytes(last_block_hash)
        msg.envelope_difficulty = int(difficulty)
        msg.envelope_pow = int(proof)
        msg.envelope_timestamp = timestamp
        msg.envelope_nonce = nonce
        msg.envelope_signature = sig_dec
        msg.target = target
        msg.user = user

        any_msg = AnyPB()
        any_msg.type_url = "/mirage.core.v1.MsgUnfollowUser"
        any_msg.value = msg.SerializeToString()
        body = TxBody(messages=[any_msg], memo="")
        body_bytes = body.SerializeToString()
        gas_est = int(estimate_total_gas_limit(body_bytes, len(target) + len(user)))
        tx_bytes_est = build_tx_bytes(body_bytes, gas_est, zero_fee=is_subscriber(user_addr))
        gas_used = int(simulate_gas(tx_bytes_est))
        gas_limit = max(gas_est, int(gas_used * GAS_BUFFER_MULTIPLIER))
        tx_hash, code, height, raw_log = build_and_broadcast_tx(
            body_bytes, gas_limit, zero_fee=is_subscriber(user_addr)
        )
        if code != 0:
            extra = {
                "height": height,
                "user_addr": user_addr,
                "last_block_hash": last_block_hash,
                "difficulty": int(difficulty),
                "proof": int(proof),
            }
            return _tx_error(rid, "core/unfollow_user", "MsgUnfollowUser", code, tx_hash, raw_log, extra)
        return jsonify({"tx_hash": tx_hash, "code": code, "height": height, "raw_log": raw_log})
    except Exception as e:
        log_event(rid, "unfollow_user.err", error=str(e))
        msg, status = _classify_exception(str(e))
        return jsonify({"error": msg}), status


@core_bp.route("/api/core/follow_topic", methods=["POST"])
def core_follow_topic():
    rid = next_request_id()
    log_event(rid, "follow_topic.begin")
    try:
        if is_node_catching_up():
            return api_error_code("node_catching_up", 503)
        data = request.get_json(force=True) or {}
        pub_b64 = str(data.get("pubkey", "").strip())
        sig_b64 = str(data.get("signature", "").strip())
        target = str(data.get("target", "").strip()).lower()
        topic = str(data.get("topic", "").strip()).lower()
        last_block_hash = str(data.get("last_block_hash", "").strip())
        difficulty = int(data.get("pow_difficulty", 0))
        proof = int(data.get("pow", 0))
        timestamp = _client_timestamp(rid, "follow_topic", data)
        nonce, err = _parse_envelope_nonce(data)
        if err is not None:
            return err[0], err[1]

        if not (pub_b64 and sig_b64 and target and topic):
            return jsonify({"error": "missing required fields"}), 400

        pub_dec = base64.b64decode(pub_b64)
        sig_dec = base64.b64decode(sig_b64)
        if len(sig_dec) == 65:
            sig_dec = sig_dec[:64]
        if len(pub_dec) != 33 or len(sig_dec) != 64:
            return jsonify({"error": "invalid relay fields"}), 400

        user_addr = derive_address_from_pubkey(pub_dec)
        if not user_addr:
            return jsonify({"error": "invalid pubkey"}), 400

        # Check if topic is already followed (indexer DB)
        try:
            if _db_list_contains("followed_topics", user_addr, "topic", topic):
                log_event(rid, "follow_topic.already_followed", topic=topic, user_addr=user_addr)
                return jsonify({"error": "topic is already followed"}), 400
        except Exception as db_err:
            log_event(rid, "follow_topic.db_error", error=str(db_err))
            return jsonify({"error": "indexer DB unavailable"}), 503

        validator_addr = require_runtime().validator_payer_addr

        if not is_subscriber(user_addr):
            try:
                base = canon_base_follow_topic(
                    pub_dec, last_block_hash, int(difficulty), timestamp, target, topic, nonce=nonce
                )
                digest = argon2_digest(base, last_block_hash, proof)
                if digest is not None:
                    effective_required = _effective_difficulty(int(difficulty))
                    if not check_pow_target(digest, effective_required, get_pow_base_bits(), _pow_factor()):
                        return jsonify({"error": "insufficient pow (precheck)"}), 400
            except Exception as _pow_exc:
                _log_pow_precheck_error(rid, "follow_topic", _pow_exc)

        msg = MsgFollowTopic()
        msg.authority = validator_addr
        msg.envelope_pubkey = pub_dec
        msg.envelope_block_hash = _hex_to_bytes(last_block_hash)
        msg.envelope_difficulty = int(difficulty)
        msg.envelope_pow = int(proof)
        msg.envelope_timestamp = timestamp
        msg.envelope_nonce = nonce
        msg.envelope_signature = sig_dec
        msg.target = target
        msg.topic = topic

        any_msg = AnyPB()
        any_msg.type_url = "/mirage.core.v1.MsgFollowTopic"
        any_msg.value = msg.SerializeToString()
        body = TxBody(messages=[any_msg], memo="")
        body_bytes = body.SerializeToString()
        gas_est = int(estimate_total_gas_limit(body_bytes, len(target) + len(topic)))
        tx_bytes_est = build_tx_bytes(body_bytes, gas_est, zero_fee=is_subscriber(user_addr))
        gas_used = int(simulate_gas(tx_bytes_est))
        gas_limit = max(gas_est, int(gas_used * GAS_BUFFER_MULTIPLIER))
        tx_hash, code, height, raw_log = build_and_broadcast_tx(
            body_bytes, gas_limit, zero_fee=is_subscriber(user_addr)
        )
        if code != 0:
            extra = {
                "height": height,
                "user_addr": user_addr,
                "target": target,
                "topic": topic,
                "last_block_hash": last_block_hash,
                "difficulty": int(difficulty),
                "proof": int(proof),
            }
            return _tx_error(rid, "core/follow_topic", "MsgFollowTopic", code, tx_hash, raw_log, extra)
        return jsonify({"tx_hash": tx_hash, "code": code, "height": height, "raw_log": raw_log})
    except Exception as e:
        log_event(rid, "follow_topic.err", error=str(e))
        msg, status = _classify_exception(str(e))
        return jsonify({"error": msg}), status


@core_bp.route("/api/core/unfollow_topic", methods=["POST"])
def core_unfollow_topic():
    rid = next_request_id()
    log_event(rid, "unfollow_topic.begin")
    try:
        if is_node_catching_up():
            return api_error_code("node_catching_up", 503)
        data = request.get_json(force=True) or {}
        pub_b64 = str(data.get("pubkey", "").strip())
        sig_b64 = str(data.get("signature", "").strip())
        target = str(data.get("target", "").strip()).lower()
        topic = str(data.get("topic", "").strip()).lower()
        last_block_hash = str(data.get("last_block_hash", "").strip())
        difficulty = int(data.get("pow_difficulty", 0))
        proof = int(data.get("pow", 0))
        timestamp = _client_timestamp(rid, "unfollow_topic", data)
        nonce, err = _parse_envelope_nonce(data)
        if err is not None:
            return err[0], err[1]

        if not (pub_b64 and sig_b64 and target and topic):
            return jsonify({"error": "missing required fields"}), 400

        pub_dec = base64.b64decode(pub_b64)
        sig_dec = base64.b64decode(sig_b64)
        if len(sig_dec) == 65:
            sig_dec = sig_dec[:64]
        if len(pub_dec) != 33 or len(sig_dec) != 64:
            return jsonify({"error": "invalid relay fields"}), 400

        user_addr = derive_address_from_pubkey(pub_dec)
        if not user_addr:
            return jsonify({"error": "invalid pubkey"}), 400

        validator_addr = require_runtime().validator_payer_addr

        if not is_subscriber(user_addr):
            try:
                base = canon_base_unfollow_topic(
                    pub_dec, last_block_hash, int(difficulty), timestamp, target, topic, nonce=nonce
                )
                digest = argon2_digest(base, last_block_hash, proof)
                if digest is not None:
                    effective_required = _effective_difficulty(int(difficulty))
                    if not check_pow_target(digest, effective_required, get_pow_base_bits(), _pow_factor()):
                        return jsonify({"error": "insufficient pow (precheck)"}), 400
            except Exception as _pow_exc:
                _log_pow_precheck_error(rid, "unfollow_topic", _pow_exc)

        msg = MsgUnfollowTopic()
        msg.authority = validator_addr
        msg.envelope_pubkey = pub_dec
        msg.envelope_block_hash = _hex_to_bytes(last_block_hash)
        msg.envelope_difficulty = int(difficulty)
        msg.envelope_pow = int(proof)
        msg.envelope_timestamp = timestamp
        msg.envelope_nonce = nonce
        msg.envelope_signature = sig_dec
        msg.target = target
        msg.topic = topic

        any_msg = AnyPB()
        any_msg.type_url = "/mirage.core.v1.MsgUnfollowTopic"
        any_msg.value = msg.SerializeToString()
        body = TxBody(messages=[any_msg], memo="")
        body_bytes = body.SerializeToString()
        gas_est = int(estimate_total_gas_limit(body_bytes, len(target) + len(topic)))
        tx_bytes_est = build_tx_bytes(body_bytes, gas_est, zero_fee=is_subscriber(user_addr))
        gas_used = int(simulate_gas(tx_bytes_est))
        gas_limit = max(gas_est, int(gas_used * GAS_BUFFER_MULTIPLIER))
        tx_hash, code, height, raw_log = build_and_broadcast_tx(
            body_bytes, gas_limit, zero_fee=is_subscriber(user_addr)
        )
        if code != 0:
            extra = {
                "height": height,
                "user_addr": user_addr,
                "target": target,
                "topic": topic,
                "last_block_hash": last_block_hash,
                "difficulty": int(difficulty),
                "proof": int(proof),
            }
            return _tx_error(rid, "core/unfollow_topic", "MsgUnfollowTopic", code, tx_hash, raw_log, extra)
        return jsonify({"tx_hash": tx_hash, "code": code, "height": height, "raw_log": raw_log})
    except Exception as e:
        log_event(rid, "unfollow_topic.err", error=str(e))
        msg, status = _classify_exception(str(e))
        return jsonify({"error": msg}), status


@core_bp.route("/api/core/delete_post", methods=["POST"])
def core_delete_post():
    rid = next_request_id()
    log_event(rid, "delete_post.begin")
    try:
        if is_node_catching_up():
            return api_error_code("node_catching_up", 503)
        data = request.get_json(force=True) or {}
        pub_b64 = str(data.get("pubkey", "")).strip()
        sig_b64 = str(data.get("signature", "")).strip()
        last_block_hash = str(data.get("last_block_hash", "")).strip()
        difficulty = int(data.get("pow_difficulty", 0))
        proof = int(data.get("pow", 0))
        if "timestamp" not in data:
            return jsonify({"error": "timestamp required"}), 400
        try:
            timestamp = int(data.get("timestamp"))
        except (TypeError, ValueError):
            return jsonify({"error": "invalid timestamp"}), 400
        nonce, err = _parse_envelope_nonce(data)
        if err is not None:
            return err[0], err[1]
        target = str(data.get("target", "")).strip()
        # no client-provided fees

        log_event(
            rid,
            "delete_post.params",
            pubkey_len=len(pub_b64),
            sig_len=len(sig_b64),
            target=target[:16] if target else "",
            last_block_hash=last_block_hash[:16] if last_block_hash else "",
            difficulty=difficulty,
            proof=proof,
        )

        if not (pub_b64 and sig_b64 and target):
            log_event(
                rid,
                "delete_post.missing_fields",
                has_pubkey=bool(pub_b64),
                has_sig=bool(sig_b64),
                has_last_block_hash=bool(last_block_hash),
                has_target=bool(target),
            )
            return jsonify({"error": "missing required fields"}), 400

        pub_dec = base64.b64decode(pub_b64)
        sig_dec = base64.b64decode(sig_b64)
        if len(sig_dec) == 65:
            sig_dec = sig_dec[:64]
        if len(pub_dec) != 33 or len(sig_dec) != 64:
            return jsonify({"error": "invalid relay fields", "pub_len": len(pub_dec), "sig_len": len(sig_dec)}), 400

        user_addr = derive_address_from_pubkey(pub_dec)
        if not user_addr:
            return jsonify({"error": "invalid pubkey"}), 400

        validator_addr = require_runtime().validator_payer_addr

        if not is_subscriber(user_addr):
            required = _min_required_difficulty()
            if int(difficulty) < int(required):
                return jsonify({"error": "insufficient pow (precheck)"}), 400
            if not _is_hex64(last_block_hash):
                return jsonify({"error": "invalid last_block_hash"}), 400
            if not is_valid_recent_block_hash(last_block_hash):
                return jsonify({"error": "invalid last_block_hash"}), 400
            try:
                base = canon_base_delete(pub_dec, last_block_hash, int(difficulty), timestamp, target, nonce=nonce)
                digest = argon2_digest(base, last_block_hash, proof)
                if digest is not None and not check_pow_target(
                    digest, _effective_difficulty(int(difficulty)), get_pow_base_bits(), _pow_factor()
                ):
                    return jsonify({"error": "insufficient pow (precheck)"}), 400
            except Exception as _pow_exc:
                _log_pow_precheck_error(rid, "delete_post", _pow_exc)

        # Ownership/admin precheck:
        # - Owner can always delete their own post
        # - Admins (level >= 100) may delete any post
        owner = _get_post_owner(target)
        if owner is None:
            return jsonify({"error": "target not found"}), 404
        user_level = get_user_level(user_addr)
        if owner != user_addr.strip().lower() and user_level < 100:
            return api_error_code("forbidden", 403)

        # No fee precheck

        msg = MsgDelete()
        # AUTHORITY IS ALWAYS THE VALIDATOR NODE (or gov), NEVER the user
        msg.authority = validator_addr
        msg.envelope_pubkey = pub_dec
        msg.envelope_block_hash = _hex_to_bytes(last_block_hash)
        msg.envelope_difficulty = int(difficulty)
        msg.envelope_pow = int(proof)
        msg.envelope_timestamp = int(timestamp)
        msg.envelope_nonce = nonce
        msg.envelope_signature = sig_dec
        msg.target = target

        any_msg = AnyPB()
        any_msg.type_url = "/mirage.core.v1.MsgDelete"
        any_msg.value = msg.SerializeToString()
        body = TxBody(messages=[any_msg], memo="")
        body_bytes = body.SerializeToString()
        gas_est = int(estimate_total_gas_limit(body_bytes, len(target)))
        tx_bytes_est = build_tx_bytes(body_bytes, gas_est, zero_fee=is_subscriber(user_addr))
        gas_used = int(simulate_gas(tx_bytes_est))
        gas_limit = max(gas_est, int(gas_used * GAS_BUFFER_MULTIPLIER))
        tx_hash, code, height, raw_log = build_and_broadcast_tx(
            body_bytes, gas_limit, zero_fee=is_subscriber(user_addr)
        )
        if code != 0:
            extra = {
                "height": height,
                "target": target,
                "last_block_hash": last_block_hash,
                "difficulty": int(difficulty),
                "proof": int(proof),
            }
            return _tx_error(rid, "core/delete_post", "MsgDelete", code, tx_hash, raw_log, extra)

        try:
            with connect_backend_db() as conn:
                cur = conn.cursor()
                cur.execute("DELETE FROM reports WHERE LOWER(target) = LOWER(%s)", (target,))
                deleted_count = cur.rowcount
                log_event(rid, "delete_post.reports_removed", target=target[:16], count=deleted_count)
        except Exception as e:
            log_event(rid, "delete_post.reports_cleanup_failed", error=str(e))

        return jsonify({"tx_hash": tx_hash, "code": code, "height": height, "raw_log": raw_log})
    except Exception as e:
        log_event(rid, "delete_post.err", error=str(e))
        msg, status = _classify_exception(str(e))
        return jsonify({"error": msg}), status


@core_bp.route("/api/core/delete_user", methods=["POST"])
def core_delete_user():
    rid = next_request_id()
    log_event(rid, "delete_user.begin")
    try:
        if is_node_catching_up():
            return api_error_code("node_catching_up", 503)
        data = request.get_json(force=True) or {}
        pub_b64 = str(data.get("pubkey", "")).strip()
        sig_b64 = str(data.get("signature", "")).strip()
        last_block_hash = str(data.get("last_block_hash", "")).strip()
        difficulty = int(data.get("pow_difficulty", 0))
        proof = int(data.get("pow", 0))
        if "timestamp" not in data:
            return jsonify({"error": "timestamp required"}), 400
        try:
            timestamp = int(data.get("timestamp"))
        except (TypeError, ValueError):
            return jsonify({"error": "invalid timestamp"}), 400
        nonce, err = _parse_envelope_nonce(data)
        if err is not None:
            return err[0], err[1]
        target = str(data.get("target", "")).strip().lower()

        log_event(
            rid,
            "delete_user.params",
            pubkey_len=len(pub_b64),
            sig_len=len(sig_b64),
            target=target[:16] if target else "",
            last_block_hash=last_block_hash[:16] if last_block_hash else "",
            difficulty=difficulty,
            proof=proof,
        )

        if not (pub_b64 and sig_b64 and target):
            log_event(
                rid,
                "delete_user.missing_fields",
                has_pubkey=bool(pub_b64),
                has_sig=bool(sig_b64),
                has_last_block_hash=bool(last_block_hash),
                has_target=bool(target),
            )
            return jsonify({"error": "missing required fields"}), 400

        if not _is_valid_mirage_addr(target):
            return jsonify({"error": "target must be a valid mirage1 address"}), 400

        pub_dec = base64.b64decode(pub_b64)
        sig_dec = base64.b64decode(sig_b64)
        if len(sig_dec) == 65:
            sig_dec = sig_dec[:64]
        if len(pub_dec) != 33 or len(sig_dec) != 64:
            return jsonify({"error": "invalid relay fields", "pub_len": len(pub_dec), "sig_len": len(sig_dec)}), 400

        user_addr = derive_address_from_pubkey(pub_dec)
        if not user_addr:
            return jsonify({"error": "invalid pubkey"}), 400
        user_addr = user_addr.strip().lower()
        if user_addr != target:
            return api_error_code("unauthorized", 403)

        validator_addr = require_runtime().validator_payer_addr

        if not is_subscriber(user_addr):
            required = _min_required_difficulty()
            if int(difficulty) < int(required):
                return jsonify({"error": "insufficient pow (precheck)"}), 400
            if not _is_hex64(last_block_hash):
                return jsonify({"error": "invalid last_block_hash"}), 400
            if not is_valid_recent_block_hash(last_block_hash):
                return jsonify({"error": "invalid last_block_hash"}), 400
            try:
                base = canon_base_delete_user(pub_dec, last_block_hash, int(difficulty), timestamp, target, nonce=nonce)
                digest = argon2_digest(base, last_block_hash, proof)
                if digest is not None and not check_pow_target(
                    digest, _effective_difficulty(int(difficulty)), get_pow_base_bits(), _pow_factor()
                ):
                    return jsonify({"error": "insufficient pow (precheck)"}), 400
            except Exception as _pow_exc:
                _log_pow_precheck_error(rid, "delete_user", _pow_exc)

        msg = MsgDeleteUser()
        # AUTHORITY IS ALWAYS THE VALIDATOR NODE (or gov), NEVER the user
        msg.authority = validator_addr
        msg.envelope_pubkey = pub_dec
        msg.envelope_block_hash = _hex_to_bytes(last_block_hash)
        msg.envelope_difficulty = int(difficulty)
        msg.envelope_pow = int(proof)
        msg.envelope_timestamp = int(timestamp)
        msg.envelope_nonce = nonce
        msg.envelope_signature = sig_dec
        msg.target = target

        any_msg = AnyPB()
        any_msg.type_url = "/mirage.core.v1.MsgDeleteUser"
        any_msg.value = msg.SerializeToString()
        body = TxBody(messages=[any_msg], memo="")
        body_bytes = body.SerializeToString()
        gas_est = int(estimate_total_gas_limit(body_bytes, len(target)))
        tx_bytes_est = build_tx_bytes(body_bytes, gas_est, zero_fee=is_subscriber(user_addr))
        gas_used = int(simulate_gas(tx_bytes_est))
        gas_limit = max(gas_est, int(gas_used * GAS_BUFFER_MULTIPLIER))
        tx_hash, code, height, raw_log = build_and_broadcast_tx(
            body_bytes, gas_limit, zero_fee=is_subscriber(user_addr)
        )
        if code != 0:
            extra = {
                "height": height,
                "target": target,
                "last_block_hash": last_block_hash,
                "difficulty": int(difficulty),
                "proof": int(proof),
            }
            return _tx_error(rid, "core/delete_user", "MsgDeleteUser", code, tx_hash, raw_log, extra)

        return jsonify({"tx_hash": tx_hash, "code": code, "height": height, "raw_log": raw_log})
    except Exception as e:
        log_event(rid, "delete_user.err", error=str(e))
        msg, status = _classify_exception(str(e))
        return jsonify({"error": msg}), status


@core_bp.route("/api/core/report", methods=["POST"])
def core_report():
    rid = next_request_id()
    log_event(rid, "report.begin")
    try:
        if is_node_catching_up():
            return api_error_code("node_catching_up", 503)
        import time

        data = request.get_json(force=True) or {}
        log_event(rid, "report.data", data=data)
        pub_b64 = str(data.get("pubkey", "").strip())
        sig_b64 = str(data.get("signature", "").strip())
        last_block_hash = str(data.get("last_block_hash", "").strip())
        difficulty = int(data.get("pow_difficulty", 0))
        proof = int(data.get("pow", 0))
        has_difficulty = "pow_difficulty" in data
        has_pow = "pow" in data
        target = str(data.get("target", "").strip()).lower()
        reason_raw = str(data.get("reason", "").strip())

        if "timestamp" not in data:
            return jsonify({"error": "timestamp required"}), 400
        try:
            timestamp = int(data.get("timestamp"))
        except (TypeError, ValueError):
            return jsonify({"error": "invalid timestamp"}), 400
        nonce, err = _parse_envelope_nonce(data)
        if err is not None:
            return err[0], err[1]

        reason = "".join(c for c in reason_raw if ord(c) >= 32 and ord(c) < 127 or ord(c) >= 160)
        reason = reason.strip()

        if not (pub_b64 and sig_b64 and last_block_hash and has_difficulty and has_pow and target and reason):
            log_event(rid, "report.missing_fields", has_reason=bool(reason), reason_len=len(reason))
            return jsonify({"error": "missing required fields"}), 400

        if len(reason) > 200:
            return jsonify({"error": "reason too long (max 200 chars)"}), 400

        if not target or len(target) != 64:
            return jsonify({"error": "invalid target format"}), 400

        if not _is_hex64(last_block_hash):
            return jsonify({"error": "invalid last_block_hash"}), 400
        if not is_valid_recent_block_hash(last_block_hash):
            return jsonify({"error": "invalid last_block_hash"}), 400

        try:
            pub_dec = decode_b64(pub_b64)
            base = canon_base_report(pub_dec, last_block_hash, int(difficulty), timestamp, target, reason, nonce=nonce)
            digest = argon2_digest(base, last_block_hash, proof)
            if digest is not None:
                effective_required = _effective_difficulty(int(difficulty))
                if not check_pow_target(digest, effective_required, get_pow_base_bits(), _pow_factor()):
                    return jsonify({"error": "insufficient pow (precheck)"}), 400
        except Exception as _pow_exc:
            _log_pow_precheck_error(rid, "report", _pow_exc)

        pub_dec = base64.b64decode(pub_b64)
        sig_dec = base64.b64decode(sig_b64)
        if len(sig_dec) == 65:
            sig_dec = sig_dec[:64]
        if len(pub_dec) != 33 or len(sig_dec) != 64:
            return jsonify({"error": "invalid relay fields", "pub_len": len(pub_dec), "sig_len": len(sig_dec)}), 400

        owner_addr = derive_address_from_pubkey(pub_dec)
        if not owner_addr:
            return jsonify({"error": "invalid pubkey"}), 400

        # Verify signature over canon(base + pow) (STRICT, no fallbacks)
        try:
            import hashlib as _hl
            from cryptography.hazmat.primitives.asymmetric import ec
            from cryptography.hazmat.primitives import hashes
            from cryptography.hazmat.primitives.asymmetric import utils as _utils

            base = canon_base_report(pub_dec, last_block_hash, int(difficulty), timestamp, target, reason, nonce=nonce)
            signed = canon_signed_with_pow(base, int(proof))
            digest = _hl.sha256(signed).digest()

            # Convert compact r||s to DER
            r = int.from_bytes(sig_dec[:32], "big")
            s = int.from_bytes(sig_dec[32:], "big")

            def _i2osp(x: int) -> bytes:
                b = x.to_bytes((x.bit_length() + 7) // 8 or 1, "big")
                if b[0] & 0x80:
                    b = b"\x00" + b
                return b

            r_b = _i2osp(r)
            s_b = _i2osp(s)
            der = bytes([0x30, 2 + len(r_b) + 2 + len(s_b), 0x02, len(r_b)]) + r_b + bytes([0x02, len(s_b)]) + s_b

            pub = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256K1(), pub_dec)
            pub.verify(der, digest, ec.ECDSA(_utils.Prehashed(hashes.SHA256())))
        except Exception as ve:
            return jsonify({"error": "invalid signature", "detail": str(ve)[:120]}), 400

        with connect_backend_db() as conn:
            cur = conn.cursor()
            ts = int(time.time())
            cur.execute(
                "INSERT INTO reports(owner, target, reason, created_at) VALUES(%s, %s, %s, %s) RETURNING id",
                (owner_addr.lower(), target, reason, ts),
            )
            row = cur.fetchone()
            report_id = row[0] if row else 0

        return jsonify({"success": True, "id": int(report_id)})
    except Exception as e:
        log_event(rid, "report.err", error=str(e))
        msg, status = _classify_exception(str(e))
        return jsonify({"error": msg}), status


@core_bp.route("/api/core/resolve_report", methods=["POST"])
def core_resolve_report():
    rid = next_request_id()
    log_event(rid, "resolve_report.begin")
    try:
        data = request.get_json(force=True) or {}
        address = str(data.get("address", "").strip()).lower()
        report_id = int(data.get("id", 0))
        if not address or report_id <= 0:
            return jsonify({"error": "missing required fields"}), 400

        admin_addr, aerr = _require_signed_request(data, "resolve_report", address)
        if aerr is not None:
            return aerr

        if get_user_level(admin_addr) < 100:
            return api_error_code("forbidden", 403)
        with connect_backend_db() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM reports WHERE id = %s", (int(report_id),))
        return jsonify({"success": True})
    except Exception as e:
        log_event(rid, "resolve_report.err", error=str(e))
        msg, status = _classify_exception(str(e))
        return jsonify({"error": msg}), status


@core_bp.route("/api/core/edit", methods=["POST"])
def core_edit():
    rid = next_request_id()
    log_event(rid, "edit.begin")
    try:
        if is_node_catching_up():
            return api_error_code("node_catching_up", 503)
        data = request.get_json(force=True) or {}
        pub_b64 = str(data.get("pubkey", "")).strip()
        sig_b64 = str(data.get("signature", "")).strip()
        last_block_hash = str(data.get("last_block_hash", "")).strip()
        difficulty = int(data.get("pow_difficulty", 0))
        proof = int(data.get("pow", 0))
        has_difficulty = "pow_difficulty" in data
        has_pow = "pow" in data
        if "timestamp" not in data:
            return jsonify({"error": "timestamp required"}), 400
        try:
            timestamp = int(data.get("timestamp"))
        except (TypeError, ValueError):
            return jsonify({"error": "invalid timestamp"}), 400
        nonce, err = _parse_envelope_nonce(data)
        if err is not None:
            return err[0], err[1]
        target = str(data.get("target", "")).strip()
        topic = str(data.get("topic", "")).strip()
        title = str(data.get("title", "")).strip()
        content = str(data.get("content", "")).strip()
        override = str(data.get("override", "")).strip().lower()
        tag = _normalize_tag(data.get("tag", ""))

        if _has_unsafe_chars(topic, title, content, target, tag):
            return jsonify({"error": "fields contain invalid control characters"}), 400

        if tag not in ALLOWED_TAGS:
            return jsonify({"error": "invalid tag", "tag": tag}), 400
        if len(tag) > 50:
            return jsonify({"error": "tag too long"}), 400

        # Validate media field (v1.12.0+ edit support)
        media_raw = data.get("media", [])
        if not isinstance(media_raw, list):
            return jsonify({"error": "media must be a list"}), 400
        media = [str(m) for m in media_raw]
        if len(media) > 10:
            return jsonify({"error": "media exceeds limit", "count": len(media), "max": 10}), 400
        for i, media_item in enumerate(media):
            if len(media_item) > 2048:
                return (
                    jsonify(
                        {"error": "media item exceeds length limit", "index": i, "length": len(media_item), "max": 2048}
                    ),
                    400,
                )
            if not media_item.startswith("https://"):
                return jsonify({"error": "media must use https", "index": i}), 400
            if _has_unsafe_chars(media_item):
                return jsonify({"error": "media contains invalid control characters", "index": i}), 400

        # Require basics: editing requires an override hash and auth fields
        if not (pub_b64 and sig_b64 and override):
            return jsonify({"error": "missing required fields"}), 400
        if not override or len(override) != 64 or not all(c in "0123456789abcdef" for c in override.lower()):
            return jsonify({"error": "invalid override"}), 400
        # Topic/target invariants must be respected on edit as well
        is_comment = bool(target)
        if is_comment:
            if not _is_hex64(target):
                return jsonify({"error": "invalid target"}), 400
            if topic:
                return jsonify({"error": "comments must not include topic"}), 400
        else:
            if not topic:
                return jsonify({"error": "topic required for root posts"}), 400
            try:
                max_topic = int(expect_params()["max_topic_size"])
            except Exception:
                return jsonify({"error": "backend not initialized"}), 503
            if len(topic) > max_topic:
                return jsonify({"error": "topic too long"}), 400
            if not re.fullmatch(r"[a-z0-9]+", topic):
                return jsonify({"error": "invalid topic format"}), 400

        pub_dec = base64.b64decode(pub_b64)
        sig_dec = base64.b64decode(sig_b64)
        if len(sig_dec) == 65:
            sig_dec = sig_dec[:64]
        if len(pub_dec) != 33 or len(sig_dec) != 64:
            return jsonify({"error": "invalid relay fields", "pub_len": len(pub_dec), "sig_len": len(sig_dec)}), 400

        user_addr = derive_address_from_pubkey(pub_dec)
        if not user_addr:
            return jsonify({"error": "invalid pubkey"}), 400

        # Ownership fast-fail (non-governance); ensure the override is owned by signer
        # and that target cannot be changed (immutable parent reference)
        try:
            conn = connect_db(timeout=10.0, busy_timeout_ms=15000)
            cur = conn.cursor()
            cur.execute(
                "SELECT owner, COALESCE(target, '') FROM posts WHERE LOWER(txhash)=LOWER(%s) LIMIT 1", (override,)
            )
            row = cur.fetchone()
            conn.close()
            if not row or not row[0]:
                # Indexer may lag briefly behind the chain; don't hard-block relay
                # on local precheck misses. Chain/indexer validation will enforce
                # real existence/ownership rules.
                log_event(rid, "edit.override_precheck_miss", override=override, user_addr=user_addr)
            else:
                owner_of_override = (row[0] or "").lower()
                if owner_of_override != user_addr.lower():
                    return api_error_code("forbidden", 403)
                stored_target = (row[1] or "").lower()
                if target.lower() != stored_target:
                    log_event(rid, "edit.target_mismatch", supplied=target, stored=stored_target, override=override)
                    return jsonify({"error": "target mismatch: cannot change post parent"}), 400
        except Exception:
            # If DB check fails, let chain proceed; indexer will enforce
            pass

        validator_addr = require_runtime().validator_payer_addr

        # Free users require PoW; subscribers skip PoW (chain uses reserve)
        if not is_subscriber(user_addr):
            if not (last_block_hash and has_difficulty and has_pow):
                return jsonify({"error": "missing required fields"}), 400
            topic_for_canon = topic if (topic and not is_comment) else ""
            try:
                base = canon_base_edit(
                    pub_dec,
                    last_block_hash,
                    int(difficulty),
                    timestamp,
                    target,
                    topic_for_canon,
                    title,
                    content,
                    tag,
                    override,
                    media=media,
                    nonce=nonce,
                )
                digest = argon2_digest(base, last_block_hash, proof)
                if digest is not None:
                    effective_required = _effective_difficulty(int(difficulty))
                    if not check_pow_target(digest, effective_required, get_pow_base_bits(), _pow_factor()):
                        return jsonify({"error": "insufficient pow (precheck)"}), 400
            except Exception as _pow_exc:
                _log_pow_precheck_error(rid, "edit", _pow_exc)
        else:
            _log_subscriber_pow_ignored(rid, "edit", difficulty, proof, has_difficulty, has_pow)
        # Verify signature over canonical signed bytes
        topic_for_canon = topic if (topic and not is_comment) else ""
        try:
            base = canon_base_edit(
                pub_dec,
                last_block_hash,
                int(difficulty),
                timestamp,
                target,
                topic_for_canon,
                title,
                content,
                tag,
                override,
                media=media,
                nonce=nonce,
            )
            signed = canon_signed_with_pow(base, int(proof))
            if not _verify_signature(pub_dec, sig_dec, signed):
                return jsonify({"error": "invalid signature"}), 400
        except Exception:
            return jsonify({"error": "invalid signature"}), 400

        msg = MsgEdit()
        # Authority is the validator/node address relaying this transaction
        msg.authority = validator_addr
        msg.envelope_pubkey = pub_dec
        msg.envelope_block_hash = _hex_to_bytes(last_block_hash)
        msg.envelope_difficulty = int(difficulty)
        msg.envelope_pow = int(proof)
        msg.envelope_timestamp = timestamp
        msg.envelope_nonce = nonce
        msg.envelope_signature = sig_dec
        msg.target = target
        log_event(rid, "edit.debug", is_comment=is_comment, topic=topic, target=target, media_count=len(media))
        msg.community = topic_for_canon
        msg.title = title
        msg.content = content
        msg.tag = tag
        msg.override = override
        for m in media:
            msg.media.append(m)

        any_msg = AnyPB()
        any_msg.type_url = "/mirage.core.v1.MsgEdit"
        any_msg.value = msg.SerializeToString()
        body = TxBody(messages=[any_msg], memo="")
        body_bytes = body.SerializeToString()
        media_len = sum(len(m) for m in media)
        content_len = len(target) + len(topic) + len(title) + len(content) + len(tag) + media_len
        gas_est = int(estimate_total_gas_limit(body_bytes, content_len))
        tx_bytes_est = build_tx_bytes(body_bytes, gas_est, zero_fee=is_subscriber(user_addr))
        gas_used = int(simulate_gas(tx_bytes_est))
        gas_limit = max(gas_est, int(gas_used * GAS_BUFFER_MULTIPLIER))
        tx_hash, code, height, raw_log = build_and_broadcast_tx(
            body_bytes, gas_limit, zero_fee=is_subscriber(user_addr)
        )
        if code != 0:
            extra = {
                "height": height,
                "user_addr": user_addr,
                "target": target,
                "topic": topic,
                "title": title,
                "content": content,
                "tag": tag,
                "override": override,
                "media_count": len(media),
                "last_block_hash": last_block_hash,
                "difficulty": int(difficulty),
                "proof": int(proof),
            }
            return _tx_error(rid, "core/edit", "MsgEdit", code, tx_hash, raw_log, extra)
        return jsonify({"tx_hash": tx_hash, "code": code, "height": height, "raw_log": raw_log})
    except Exception as e:
        log_event(rid, "edit.err", error=str(e))
        msg, status = _classify_exception(str(e))
        return jsonify({"error": msg}), status


def _is_agent(addr: str) -> bool:
    """Check if user is agent tier (level >= 10) via the indexer database."""
    addr_lc = (addr or "").strip().lower()
    if not addr_lc:
        return False
    with connect_db(timeout=10.0, busy_timeout_ms=15000) as conn:
        cur = conn.cursor()
        cur.execute("SELECT level FROM profiles WHERE LOWER(owner) = LOWER(%s) LIMIT 1", (addr_lc,))
        row = cur.fetchone()
        level = int(row[0]) if row and row[0] is not None else 0
        return level >= 10


ANNOTATE_SENTINEL = "."


@core_bp.route("/api/core/annotate", methods=["POST"])
def core_annotate():
    """Agent-only endpoint to create an overlay edit on an existing post."""
    rid = next_request_id()
    log_event(rid, "annotate.begin")
    try:
        if is_node_catching_up():
            return api_error_code("node_catching_up", 503)
        data = request.get_json(force=True) or {}
        pub_b64 = str(data.get("pubkey", "")).strip()
        sig_b64 = str(data.get("signature", "")).strip()
        last_block_hash = str(data.get("last_block_hash", "")).strip()
        difficulty = int(data.get("pow_difficulty", 0))
        proof = int(data.get("pow", 0))
        if "timestamp" not in data:
            return jsonify({"error": "timestamp required"}), 400
        try:
            timestamp = int(data.get("timestamp"))
        except (TypeError, ValueError):
            return jsonify({"error": "invalid timestamp"}), 400
        nonce, err = _parse_envelope_nonce(data)
        if err is not None:
            return err[0], err[1]
        topic = str(data.get("topic", "")).strip()
        title = str(data.get("title", "")).strip()
        content = str(data.get("content", "")).strip()
        override = str(data.get("override", "")).strip().lower()
        raw_tag = str(data.get("tag", "")).strip()
        tag = _normalize_tag(raw_tag) if raw_tag != ANNOTATE_SENTINEL else raw_tag
        appendix = str(data.get("appendix", "")).strip()

        # Media: list of strings or omitted
        media_raw = data.get("media", [])
        if not isinstance(media_raw, list):
            return jsonify({"error": "media must be a list"}), 400
        media = [str(m) for m in media_raw]

        # Validate non-sentinel fields for unsafe chars
        non_sentinel_vals = [v for v in [topic, title, content, tag, appendix] if v != ANNOTATE_SENTINEL]
        if _has_unsafe_chars(*non_sentinel_vals):
            return jsonify({"error": "fields contain invalid control characters"}), 400

        # Validate tag if not sentinel
        if tag != ANNOTATE_SENTINEL and tag not in ALLOWED_TAGS:
            return jsonify({"error": "invalid tag", "tag": tag}), 400

        # Validate media if not sentinel ["."]
        is_sentinel_media = len(media) == 1 and media[0] == ANNOTATE_SENTINEL
        if not is_sentinel_media:
            if len(media) > 10:
                return jsonify({"error": "media exceeds limit", "count": len(media), "max": 10}), 400
            for i, media_item in enumerate(media):
                if len(media_item) > 2048:
                    return (
                        jsonify(
                            {
                                "error": "media item exceeds length limit",
                                "index": i,
                                "length": len(media_item),
                                "max": 2048,
                            }
                        ),
                        400,
                    )
                if media_item and not media_item.startswith("https://"):
                    return jsonify({"error": "media must use https", "index": i}), 400
                if _has_unsafe_chars(media_item):
                    return jsonify({"error": "media contains invalid control characters", "index": i}), 400

        if not (pub_b64 and sig_b64 and override):
            return jsonify({"error": "missing required fields"}), 400
        if not override or len(override) != 64 or not all(c in "0123456789abcdef" for c in override.lower()):
            return jsonify({"error": "invalid override"}), 400

        pub_dec = base64.b64decode(pub_b64)
        sig_dec = base64.b64decode(sig_b64)
        if len(sig_dec) == 65:
            sig_dec = sig_dec[:64]
        if len(pub_dec) != 33 or len(sig_dec) != 64:
            return jsonify({"error": "invalid relay fields", "pub_len": len(pub_dec), "sig_len": len(sig_dec)}), 400

        user_addr = derive_address_from_pubkey(pub_dec)
        if not user_addr:
            return jsonify({"error": "invalid pubkey"}), 400

        # Enforce agent tier
        if not _is_agent(user_addr):
            return jsonify({"error": "agent tier required"}), 403

        # Verify the override post exists
        with connect_db(timeout=10.0, busy_timeout_ms=15000) as conn:
            cur = conn.cursor()
            cur.execute("SELECT owner FROM posts WHERE LOWER(txhash)=LOWER(%s) LIMIT 1", (override,))
            row = cur.fetchone()
            if not row or not row[0]:
                # Same as edit route: avoid false negatives during indexer lag.
                log_event(rid, "annotate.override_precheck_miss", override=override, user_addr=user_addr)

        validator_addr = require_runtime().validator_payer_addr

        # Agents are subscribers — no PoW
        if int(difficulty) > 0 or int(proof) > 0:
            log_event(rid, "annotate.pow_rejected", difficulty=int(difficulty), pow=int(proof))
            return jsonify({"error": "pow not allowed for agents"}), 400

        # Verify signature over canonical signed bytes
        try:
            base = canon_base_annotate(
                pub_dec,
                last_block_hash,
                int(difficulty),
                timestamp,
                topic,
                title,
                content,
                tag,
                override,
                media=media,
                appendix=appendix,
                nonce=nonce,
            )
            signed = canon_signed_with_pow(base, int(proof))
            if not _verify_signature(pub_dec, sig_dec, signed):
                return jsonify({"error": "invalid signature"}), 400
        except Exception:
            return jsonify({"error": "invalid signature"}), 400

        log_event(
            rid,
            "annotate.debug",
            override=override,
            topic=topic,
            tag=tag,
            appendix_len=len(appendix),
            media_count=len(media),
        )

        msg = MsgAnnotate()
        msg.authority = validator_addr
        msg.envelope_pubkey = pub_dec
        msg.envelope_block_hash = _hex_to_bytes(last_block_hash)
        msg.envelope_difficulty = int(difficulty)
        msg.envelope_pow = int(proof)
        msg.envelope_timestamp = timestamp
        msg.envelope_nonce = nonce
        msg.envelope_signature = sig_dec
        msg.topic = topic
        msg.title = title
        msg.content = content
        msg.tag = tag
        msg.override = override
        for m in media:
            msg.media.append(m)
        msg.appendix = appendix

        any_msg = AnyPB()
        any_msg.type_url = "/mirage.core.v1.MsgAnnotate"
        any_msg.value = msg.SerializeToString()
        body = TxBody(messages=[any_msg], memo="")
        body_bytes = body.SerializeToString()
        media_len = sum(len(m) for m in media)
        content_len = len(topic) + len(title) + len(content) + len(tag) + len(appendix) + media_len
        gas_est = int(estimate_total_gas_limit(body_bytes, content_len))
        tx_bytes_est = build_tx_bytes(body_bytes, gas_est, zero_fee=is_subscriber(user_addr))
        gas_used = int(simulate_gas(tx_bytes_est))
        gas_limit = max(gas_est, int(gas_used * GAS_BUFFER_MULTIPLIER))
        tx_hash, code, height, raw_log = build_and_broadcast_tx(
            body_bytes, gas_limit, zero_fee=is_subscriber(user_addr)
        )
        if code != 0:
            extra = {
                "height": height,
                "user_addr": user_addr,
                "topic": topic,
                "title": title,
                "content": content,
                "tag": tag,
                "override": override,
                "appendix_len": len(appendix),
                "media_count": len(media),
            }
            return _tx_error(rid, "core/annotate", "MsgAnnotate", code, tx_hash, raw_log, extra)
        return jsonify({"tx_hash": tx_hash, "code": code, "height": height, "raw_log": raw_log})
    except Exception as e:
        log_event(rid, "annotate.err", error=str(e))
        msg, status = _classify_exception(str(e))
        return jsonify({"error": msg}), status


ALLOWED_TAGS = {"", "sensitive", "adult", "gore", "violence", "death"}

# TODO: remove "porn" alias once all clients send "adult"
_TAG_ALIASES = {"porn": "adult"}


def _normalize_tag(tag: str) -> str:
    """Return canonical tag name, applying aliases.

    Matches Go's `normalizeTag` in `blockchain/x/core/module/module.go`:
    only trim + alias, no case folding. Non-canonical casing must be
    rejected as "invalid tag" rather than silently coerced — otherwise
    the user's signature (computed over the original casing) won't match
    the canonical bytes the backend reconstructs.
    """
    t = (tag or "").strip()
    return _TAG_ALIASES.get(t, t)


def _has_unsafe_chars(*values: str) -> bool:
    """Return True if any value contains NUL, control chars (except tab/newline/CR), or DEL."""
    for v in values:
        for ch in v:
            cp = ord(ch)
            if cp <= 0x1F and cp not in (0x09, 0x0A, 0x0D):
                return True
            if cp == 0x7F:
                return True
    return False


@core_bp.route("/api/core/post", methods=["POST"])
def core_post():
    rid = next_request_id()
    log_event(rid, "post.begin")
    try:
        if is_node_catching_up():
            return api_error_code("node_catching_up", 503)
        data = request.get_json(force=True) or {}
        pub_b64 = str(data.get("pubkey", "")).strip()
        sig_b64 = str(data.get("signature", "")).strip()
        last_block_hash = str(data.get("last_block_hash", "")).strip()
        has_difficulty = "pow_difficulty" in data
        has_pow = "pow" in data
        try:
            difficulty = int(data.get("pow_difficulty", 0))
        except (TypeError, ValueError):
            return jsonify({"error": "invalid pow_difficulty", "error_code": "invalid_input"}), 400
        try:
            proof = int(data.get("pow", 0))
        except (TypeError, ValueError):
            return jsonify({"error": "invalid pow", "error_code": "invalid_input"}), 400
        if "timestamp" not in data:
            return jsonify({"error": "timestamp required"}), 400
        try:
            timestamp = int(data.get("timestamp"))
        except (TypeError, ValueError):
            return jsonify({"error": "invalid timestamp"}), 400
        ts_ok, ts_err = _validate_envelope_timestamp(timestamp)
        if not ts_ok:
            log_event(rid, "post.timestamp_invalid", timestamp=timestamp, now_ms=int(time.time() * 1000))
            return ts_err[0], ts_err[1]
        nonce, err = _parse_envelope_nonce(data)
        if err is not None:
            log_event(rid, "post.invalid_nonce", envelope_nonce=data.get("envelope_nonce"))
            return err[0], err[1]
        target = str(data.get("target", ""))
        topic = str(data.get("community") or data.get("topic") or "").strip()
        title = str(data.get("title", ""))
        content = str(data.get("content", ""))
        tag = _normalize_tag(data.get("tag", ""))
        try:
            protocol_version = int(data.get("protocol_version", 0))
        except (TypeError, ValueError):
            protocol_version = 0
        if protocol_version != 1:
            return api_error_code("upgrade_required", 426)

        if _has_unsafe_chars(topic, title, content, target, tag):
            return jsonify({"error": "fields contain invalid control characters"}), 400

        # Validate tag
        if tag not in ALLOWED_TAGS:
            return jsonify({"error": "invalid tag", "tag": tag}), 400
        if len(tag) > 50:
            return jsonify({"error": "tag too long"}), 400

        # Validate media field (v1.12.0)
        media_raw = data.get("media", [])
        if not isinstance(media_raw, list):
            return jsonify({"error": "media must be a list"}), 400
        media = [str(m) for m in media_raw]
        if len(media) > 10:
            return jsonify({"error": "media exceeds limit", "count": len(media), "max": 10}), 400
        for i, media_item in enumerate(media):
            if len(media_item) > 2048:
                return (
                    jsonify(
                        {"error": "media item exceeds length limit", "index": i, "length": len(media_item), "max": 2048}
                    ),
                    400,
                )
            if not media_item.startswith("https://"):
                return jsonify({"error": "media must use https", "index": i}), 400
            if _has_unsafe_chars(media_item):
                return jsonify({"error": "media contains invalid control characters", "index": i}), 400

        # Basic fields must be present; last_block_hash is optional for subscribers
        if not (pub_b64 and sig_b64):
            return jsonify({"error": "missing required fields"}), 400
        # Topic/target invariants
        is_comment = bool(target.strip())
        if is_comment:
            if not _is_hex64(target.strip()):
                return jsonify({"error": "invalid target"}), 400
            if topic:
                return jsonify({"error": "comments must not include topic"}), 400
            if not content.strip():
                return jsonify({"error": "comment content required"}), 400
        else:
            if not topic:
                return jsonify({"error": "topic required for root posts"}), 400
            try:
                p = expect_params()
                max_topic = int(p["max_topic_size"])
                min_topic = int(p["min_topic_size"])
            except Exception:
                # Both keys are in _REQUIRED_INT_PARAMS, so the previous fallback
                # was unreachable by construction — and wrong anyway: it used 50
                # where the chain default is 35, so had it ever fired it would have
                # accepted topics the chain rejects. Fail to 503 like the username
                # bounds immediately above.
                return jsonify({"error": "backend not initialized"}), 503
            if len(topic) < min_topic:
                return jsonify({"error": "topic too short"}), 400
            if len(topic) > max_topic:
                return jsonify({"error": "topic too long"}), 400
            if not re.fullmatch(r"[a-z0-9]+", topic):
                return jsonify({"error": "invalid topic format"}), 400

        try:
            pub_dec = base64.b64decode(pub_b64)
        except Exception:
            return jsonify({"error": "invalid pubkey encoding", "error_code": "invalid_input"}), 400
        try:
            sig_dec = base64.b64decode(sig_b64)
        except Exception:
            return jsonify({"error": "invalid signature encoding", "error_code": "invalid_input"}), 400
        if len(sig_dec) == 65:
            sig_dec = sig_dec[:64]
        if len(pub_dec) != 33 or len(sig_dec) != 64:
            return jsonify({"error": "invalid relay fields", "pub_len": len(pub_dec), "sig_len": len(sig_dec)}), 400

        user_addr = derive_address_from_pubkey(pub_dec)
        if not user_addr:
            return jsonify({"error": "invalid pubkey"}), 400

        validator_addr = require_runtime().validator_payer_addr

        # Enforce tier limits (title/content) based on user's subscription level
        try:
            p = expect_params()
            tiers = p.get("tiers") or []
            level = get_user_level(user_addr)
            # Map user level to tier array index: 0->0, 1->1, 10->2, 100+->2
            idx = {0: 0, 1: 1, 10: 2}.get(level, 2 if level >= 100 else -1)
            if idx < 0 or idx >= len(tiers):
                return api_error_code("invalid_user_level")
            tier_cfg = tiers[idx] or {}
            max_title = int(tier_cfg.get("max_title_length", 0))
            max_content = int(tier_cfg.get("max_content_length", 0))
        except Exception:
            return jsonify({"error": "backend not initialized"}), 503

        # Comments: only content limit applies; Root posts: both title and content
        if is_comment:
            if len(content) > max_content:
                return (
                    jsonify(
                        {
                            "error": "content exceeds limit",
                            "length": len(content),
                            "max": max_content,
                            "tier_level": level,
                        }
                    ),
                    400,
                )
        else:
            if len(title) > max_title:
                return (
                    jsonify(
                        {"error": "title exceeds limit", "length": len(title), "max": max_title, "tier_level": level}
                    ),
                    400,
                )
            if len(content) > max_content:
                return (
                    jsonify(
                        {
                            "error": "content exceeds limit",
                            "length": len(content),
                            "max": max_content,
                            "tier_level": level,
                        }
                    ),
                    400,
                )

        # Free users require PoW; subscribers skip PoW (chain uses reserve)
        if not is_subscriber(user_addr):
            if not (has_difficulty and has_pow):
                return jsonify({"error": "missing required fields"}), 400
            required = _min_required_difficulty()
            if int(difficulty) < int(required):
                return jsonify({"error": "insufficient pow (precheck)"}), 400
            if not _is_hex64(last_block_hash):
                return jsonify({"error": "invalid last_block_hash"}), 400
            if not is_valid_recent_block_hash(last_block_hash):
                return jsonify({"error": "invalid last_block_hash"}), 400
            try:
                base = canon_base_post(
                    pub_dec,
                    last_block_hash,
                    int(difficulty),
                    timestamp,
                    target,
                    topic,
                    title,
                    content,
                    tag,
                    media=media,
                    nonce=nonce,
                )
                digest = argon2_digest(base, last_block_hash, proof)
                if digest is not None:
                    if not check_pow_target(
                        digest, _effective_difficulty(int(difficulty)), get_pow_base_bits(), _pow_factor()
                    ):
                        return jsonify({"error": "insufficient pow (precheck)"}), 400
            except Exception as _pow_exc:
                _log_pow_precheck_error(rid, "post", _pow_exc)
        else:
            _log_subscriber_pow_ignored(rid, "post", difficulty, proof, has_difficulty, has_pow)

        # Verify signature over canonical signed bytes
        try:
            base = canon_base_post(
                pub_dec,
                last_block_hash,
                int(difficulty),
                timestamp,
                target,
                topic,
                title,
                content,
                tag,
                media=media,
                nonce=nonce,
            )
            signed = canon_signed_with_pow(base, int(proof))
            if not _verify_signature(pub_dec, sig_dec, signed):
                return jsonify({"error": "invalid signature"}), 400
        except Exception:
            return jsonify({"error": "invalid signature"}), 400

        msg = MsgPost()
        # authority is the validator/node address relaying this transaction, NOT the user's address
        msg.authority = validator_addr
        msg.envelope_pubkey = pub_dec
        msg.envelope_block_hash = _hex_to_bytes(last_block_hash)
        msg.envelope_difficulty = int(difficulty)
        msg.envelope_pow = int(proof)
        msg.envelope_timestamp = timestamp
        msg.envelope_nonce = nonce
        msg.envelope_signature = sig_dec
        msg.target = target
        msg.community = topic
        msg.title = title
        msg.content = content
        msg.tag = tag
        msg.protocol_version = 1
        for m in media:
            msg.media.append(m)

        any_msg = AnyPB()
        any_msg.type_url = "/mirage.core.v1.MsgPost"
        any_msg.value = msg.SerializeToString()
        body = TxBody(messages=[any_msg], memo="")
        body_bytes = body.SerializeToString()
        media_len = sum(len(m) for m in media)
        content_len = len(target) + len(topic) + len(title) + len(content) + media_len
        gas_est = int(estimate_total_gas_limit(body_bytes, content_len))
        tx_bytes_est = build_tx_bytes(body_bytes, gas_est, zero_fee=is_subscriber(user_addr))
        gas_used = int(simulate_gas(tx_bytes_est))
        gas_limit = max(gas_est, int(gas_used * GAS_BUFFER_MULTIPLIER))
        tx_hash, code, height, raw_log = build_and_broadcast_tx(
            body_bytes, gas_limit, zero_fee=is_subscriber(user_addr)
        )
        if code != 0:
            extra = {
                "height": height,
                "user_addr": user_addr,
                "target": target,
                "topic": topic,
                "title": title,
                "content": content,
                "tag": tag,
                "last_block_hash": last_block_hash,
                "difficulty": int(difficulty),
                "proof": int(proof),
            }
            return _tx_error(rid, "core/post", "MsgPost", code, tx_hash, raw_log, extra)
        poster_username = ""
        try:
            client_ip = _get_trusted_client_ip()
            if client_ip:
                target_log = str(target or "").strip().lower()
                action = "create_comment" if target_log else "create_post"
                poster_username = _get_username_for_owner(user_addr)
                _log_user_action(poster_username, client_ip, action, target_log, str(tx_hash or "").lower())
        except Exception:
            pass

        now_ts = int(time.time())
        quest_action = "comment" if target else "post"
        comment_quest_kwargs = {
            "content_length": len(content),
        }
        if target:
            parent_info = _get_post_quest_info(target)
            if not parent_info:
                log_event(rid, "quest.comment.parent_missing", owner=user_addr, target=target)
            else:
                parent_topic = (parent_info.get("topic") or "").strip().lower()
                comment_quest_kwargs["root_post_id"] = parent_info["root_post_id"]
                comment_quest_kwargs["target_owner"] = parent_info["owner"]
                if parent_topic:
                    comment_quest_kwargs["topic"] = parent_topic
                    comment_quest_kwargs["target_topic"] = parent_topic
                else:
                    log_event(rid, "quest.comment.parent_topic_missing", owner=user_addr, target=target)
                if topic and topic != parent_topic:
                    log_event(
                        rid,
                        "quest.comment.topic_override",
                        owner=user_addr,
                        target=target,
                        request_topic=topic,
                        parent_topic=parent_topic,
                    )
        else:
            comment_quest_kwargs["topic"] = topic
            comment_quest_kwargs["target_topic"] = topic
        _track_quest_progress(user_addr, quest_action, now_ts, **comment_quest_kwargs)
        if not target and topic:
            _track_quest_progress(
                user_addr,
                "unique_topic_post",
                now_ts,
                topic=topic,
                content_length=len(content),
            )

        return jsonify({"tx_hash": tx_hash, "code": code, "height": height, "raw_log": raw_log})
    except Exception as e:
        log_event(rid, "post.err", error=str(e))
        msg, status = _classify_exception(str(e))
        return jsonify({"error": msg}), status


@core_bp.route("/api/core/vote", methods=["POST"])
def core_vote():
    rid = next_request_id()
    log_event(rid, "vote.begin")
    try:
        if is_node_catching_up():
            return api_error_code("node_catching_up", 503)
        data = request.get_json(force=True) or {}
        pub_b64 = str(data.get("pubkey", "")).strip()
        sig_b64 = str(data.get("signature", "")).strip()
        last_block_hash = str(data.get("last_block_hash", "")).strip()
        has_difficulty = "pow_difficulty" in data
        has_pow = "pow" in data
        try:
            difficulty = int(data.get("pow_difficulty", 0))
        except (TypeError, ValueError):
            return jsonify({"error": "invalid pow_difficulty", "error_code": "invalid_input"}), 400
        try:
            proof = int(data.get("pow", 0))
        except (TypeError, ValueError):
            return jsonify({"error": "invalid pow", "error_code": "invalid_input"}), 400
        target = str(data.get("target", ""))
        try:
            direction = int(data.get("direction", 0))
        except (TypeError, ValueError):
            return jsonify({"error": "invalid direction", "error_code": "invalid_input"}), 400
        if "timestamp" not in data:
            return jsonify({"error": "timestamp required"}), 400
        try:
            timestamp = int(data.get("timestamp"))
        except (TypeError, ValueError):
            return jsonify({"error": "invalid timestamp"}), 400
        nonce, err = _parse_envelope_nonce(data)
        if err is not None:
            return err[0], err[1]
        # no client-provided fees
        # Minimal fields; last_block_hash/difficulty/proof only needed for PoW path
        if not (pub_b64 and sig_b64 and target):
            log_event(
                rid,
                "vote.missing_fields",
                has_pubkey=bool(pub_b64),
                has_signature=bool(sig_b64),
                has_target=bool(target),
            )
            return (
                jsonify(
                    {
                        "error": "missing required fields",
                        "details": f"pubkey={bool(pub_b64)}, signature={bool(sig_b64)}, target={bool(target)}",
                    }
                ),
                400,
            )
        if not _is_hex64(target.strip()):
            return jsonify({"error": "invalid target"}), 400

        try:
            pub_dec = base64.b64decode(pub_b64)
        except Exception:
            return jsonify({"error": "invalid pubkey encoding", "error_code": "invalid_input"}), 400
        try:
            sig_dec = base64.b64decode(sig_b64)
        except Exception:
            return jsonify({"error": "invalid signature encoding", "error_code": "invalid_input"}), 400
        if len(sig_dec) == 65:
            sig_dec = sig_dec[:64]
        if len(pub_dec) != 33 or len(sig_dec) != 64:
            return jsonify({"error": "invalid relay fields", "pub_len": len(pub_dec), "sig_len": len(sig_dec)}), 400

        user_addr = derive_address_from_pubkey(pub_dec)
        if not user_addr:
            return jsonify({"error": "invalid pubkey"}), 400

        validator_addr = require_runtime().validator_payer_addr

        # Free users require PoW; subscribers skip PoW (chain uses reserve)
        user_is_sub = is_subscriber(user_addr)
        log_event(
            rid, "vote.subscriber_check", user_addr=user_addr, is_subscriber=user_is_sub, pow_difficulty=difficulty
        )
        if not user_is_sub:
            if not (has_difficulty and has_pow):
                log_event(rid, "vote.pow_required", user_addr=user_addr, difficulty=difficulty, proof=proof)
                return api_error_code(
                    "pow_required",
                    400,
                    details="Non-subscriber must provide valid PoW. Your subscription may have expired.",
                )
            required = _min_required_difficulty()
            if int(difficulty) < int(required):
                return jsonify({"error": "insufficient pow (precheck)"}), 400
            if not _is_hex64(last_block_hash):
                return jsonify({"error": "invalid last_block_hash"}), 400
            if not is_valid_recent_block_hash(last_block_hash):
                return jsonify({"error": "invalid last_block_hash"}), 400
                # PoW precheck: mirror chain's validatePoWBytesArgon2 threshold
            try:
                base = canon_base_vote(
                    pub_dec, last_block_hash, int(difficulty), timestamp, target, int(direction), nonce=nonce
                )
                digest = argon2_digest(base, last_block_hash, proof)
                if digest is not None:
                    effective_required = _effective_difficulty(int(difficulty))
                    if not check_pow_target(digest, effective_required, get_pow_base_bits(), _pow_factor()):
                        return jsonify({"error": "insufficient pow (precheck)"}), 400
            except Exception as _pow_exc:
                _log_pow_precheck_error(rid, "vote", _pow_exc)

            # Verify signature for PoW users (chain also verifies via ante handler)
            try:
                base = canon_base_vote(
                    pub_dec,
                    last_block_hash,
                    int(difficulty),
                    timestamp,
                    target,
                    int(direction),
                    nonce=nonce,
                )
                signed = canon_signed_with_pow(base, int(proof))
                if not _verify_signature(pub_dec, sig_dec, signed):
                    # Detailed failure logging to help debug canonical or signature mismatches
                    log_event(
                        rid,
                        "vote.sig_fail",
                        canonical_hex=signed.hex(),
                        last_block_hash=last_block_hash,
                        difficulty=int(difficulty),
                        timestamp=timestamp,
                        target=target,
                        direction=int(direction),
                        proof=int(proof),
                        pubkey_b64=pub_b64,
                        signature_b64=sig_b64,
                    )
                    return jsonify({"error": "invalid signature"}), 400

                # Also log successful verification so we can compare frontend/backend canonicals
                log_event(
                    rid,
                    "vote.sig_ok",
                    canonical_hex=signed.hex(),
                    last_block_hash=last_block_hash,
                    difficulty=int(difficulty),
                    timestamp=timestamp,
                    target=target,
                    direction=int(direction),
                    proof=int(proof),
                    pubkey_b64=pub_b64,
                    signature_b64=sig_b64,
                )
            except Exception as sig_err:
                log_event(rid, "vote.sig_exception", error=str(sig_err))
                return jsonify({"error": "invalid signature"}), 400
        else:
            _log_subscriber_pow_ignored(rid, "vote", difficulty, proof, has_difficulty, has_pow)
            # Subscribers: skip backend signature verification - chain verifies via ante handler
        msg = MsgVote()
        # authority is the validator/node address relaying this transaction, NOT the user's address
        msg.authority = validator_addr
        msg.envelope_pubkey = pub_dec
        msg.envelope_block_hash = _hex_to_bytes(last_block_hash)
        msg.envelope_difficulty = int(difficulty)
        msg.envelope_pow = int(proof)
        msg.envelope_timestamp = timestamp
        msg.envelope_nonce = nonce
        msg.envelope_signature = sig_dec
        msg.target = target
        msg.direction = int(direction)

        any_msg = AnyPB()
        any_msg.type_url = "/mirage.core.v1.MsgVote"
        any_msg.value = msg.SerializeToString()
        body = TxBody(messages=[any_msg], memo="")
        body_bytes = body.SerializeToString()
        content_len = len(target)
        gas_est = int(estimate_total_gas_limit(body_bytes, content_len))
        tx_bytes_est = build_tx_bytes(body_bytes, gas_est, zero_fee=is_subscriber(user_addr))
        gas_used = int(simulate_gas(tx_bytes_est))
        gas_limit = max(gas_est, int(gas_used * GAS_BUFFER_MULTIPLIER))
        tx_hash, code, height, raw_log = build_and_broadcast_tx(
            body_bytes, gas_limit, zero_fee=is_subscriber(user_addr)
        )
        if code != 0:
            extra = {
                "height": height,
                "user_addr": user_addr,
                "target": target,
                "direction": int(direction),
                "last_block_hash": last_block_hash,
                "difficulty": int(difficulty),
                "proof": int(proof),
            }
            return _tx_error(rid, "core/vote", "MsgVote", code, tx_hash, raw_log, extra)
        try:
            client_ip = _get_trusted_client_ip()
            if client_ip:
                target_log = str(target or "").strip().lower()
                username = _get_username_for_owner(user_addr)
                _log_user_action(username, client_ip, "vote", target_log, str(tx_hash or "").lower())
        except Exception:
            pass

        now_ts = int(time.time())
        post_info = _get_post_quest_info(target)
        vote_quest_kwargs = dict(
            target=target,
            vote_direction=int(direction),
            vote_is_change=False,
        )
        if post_info:
            vote_quest_kwargs["target_topic"] = post_info["topic"]
            vote_quest_kwargs["target_owner"] = post_info["owner"]
        _track_quest_progress(user_addr, "vote", now_ts, **vote_quest_kwargs)
        _track_quest_progress(user_addr, "balanced_vote", now_ts, **vote_quest_kwargs)

        return jsonify({"tx_hash": tx_hash, "code": code, "height": height, "raw_log": raw_log})
    except Exception as e:
        log_event(rid, "vote.err", error=str(e))
        msg, status = _classify_exception(str(e))
        return jsonify({"error": msg}), status


@core_bp.route("/api/core/send_tokens", methods=["POST"])
def core_send_tokens():
    rid = next_request_id()
    log_event(rid, "send_tokens.begin")
    try:
        if is_node_catching_up():
            return api_error_code("node_catching_up", 503)
        data = request.get_json(force=True) or {}
        log_event(rid, "send_tokens.data", data=data)

        pub_b64 = str(data.get("pubkey", "")).strip()
        sig_b64 = str(data.get("signature", "")).strip()
        last_block_hash = str(data.get("last_block_hash", "")).strip()
        has_difficulty = "pow_difficulty" in data
        has_pow = "pow" in data
        try:
            difficulty = int(data.get("pow_difficulty", 0))
        except (TypeError, ValueError):
            return jsonify({"error": "invalid pow_difficulty", "error_code": "invalid_input"}), 400
        try:
            proof = int(data.get("pow", 0))
        except (TypeError, ValueError):
            return jsonify({"error": "invalid pow", "error_code": "invalid_input"}), 400
        target = str(data.get("target", "")).strip().lower()
        try:
            amount = int(data.get("amount", 0))
        except (TypeError, ValueError):
            return jsonify({"error": "invalid amount", "error_code": "invalid_input"}), 400
        if "timestamp" not in data:
            return jsonify({"error": "timestamp required"}), 400
        try:
            timestamp = int(data.get("timestamp"))
        except (TypeError, ValueError):
            return jsonify({"error": "invalid timestamp"}), 400
        nonce, err = _parse_envelope_nonce(data)
        if err is not None:
            return err[0], err[1]
        # no client-provided fees

        log_event(rid, "send_tokens.parsed", target=target, amount=amount)

        if not (pub_b64 and sig_b64 and target and amount > 0):
            log_event(rid, "send_tokens.missing_fields")
            return jsonify({"error": "missing required fields"}), 400

        # Validate target is a mirage1 address
        if not target.startswith("mirage1"):
            return jsonify({"error": "target must be a valid mirage1 address"}), 400

        try:
            pub_dec = base64.b64decode(pub_b64)
        except Exception:
            return jsonify({"error": "invalid pubkey encoding", "error_code": "invalid_input"}), 400
        try:
            sig_dec = base64.b64decode(sig_b64)
        except Exception:
            return jsonify({"error": "invalid signature encoding", "error_code": "invalid_input"}), 400
        if len(sig_dec) == 65:
            sig_dec = sig_dec[:64]
        if len(pub_dec) != 33 or len(sig_dec) != 64:
            return jsonify({"error": "invalid relay fields"}), 400

        user_addr = derive_address_from_pubkey(pub_dec)
        if not user_addr:
            return jsonify({"error": "invalid pubkey"}), 400
        # Ensure lowercase for consistency with frontend signerAddress
        user_addr = user_addr.lower()

        validator_addr = require_runtime().validator_payer_addr

        # Insufficient balance precheck (reject before broadcast)
        try:
            have = int(get_balance(user_addr) or 0)
        except Exception as db_err:
            log_event(rid, "send_tokens.db_error", error=str(db_err))
            return jsonify({"error": "indexer DB unavailable"}), 503
        if int(amount) > have:
            return jsonify({"error": "insufficient balance", "balance": have, "needed": int(amount)}), 400

        # Free users require PoW; subscribers skip PoW (chain uses reserve)
        if not is_subscriber(user_addr):
            if not (last_block_hash and has_difficulty and has_pow):
                return jsonify({"error": "missing required fields"}), 400
            try:
                base = canon_base_send_tokens(
                    pub_dec,
                    last_block_hash,
                    int(difficulty),
                    timestamp,
                    user_addr,
                    target,
                    int(amount),
                    nonce=nonce,
                )
                digest = argon2_digest(base, last_block_hash, proof)
                if digest is not None:
                    effective_required = _effective_difficulty(int(difficulty))
                    if not check_pow_target(digest, effective_required, get_pow_base_bits(), _pow_factor()):
                        return jsonify({"error": "insufficient pow (precheck)"}), 400
            except Exception as _pow_exc:
                _log_pow_precheck_error(rid, "send_tokens", _pow_exc)
        else:
            _log_subscriber_pow_ignored(rid, "send_tokens", difficulty, proof, has_difficulty, has_pow)

        # Backend signature verification (first line of defense)
        try:
            base = canon_base_send_tokens(
                pub_dec,
                last_block_hash,
                int(difficulty),
                timestamp,
                user_addr,
                target,
                int(amount),
                nonce=nonce,
            )
            signed = canon_signed_with_pow(base, int(proof))
            if not _verify_signature(pub_dec, sig_dec, signed):
                return jsonify({"error": "invalid signature"}), 400
        except Exception:
            return jsonify({"error": "invalid signature"}), 400

        msg = MsgSendTokens()
        # authority is the validator/node address relaying this transaction, NOT the user's address
        msg.authority = validator_addr
        msg.envelope_pubkey = pub_dec
        msg.envelope_block_hash = _hex_to_bytes(last_block_hash)
        msg.envelope_difficulty = int(difficulty)
        msg.envelope_pow = int(proof)
        msg.envelope_timestamp = int(timestamp)
        msg.envelope_nonce = nonce
        msg.envelope_signature = sig_dec
        msg.sender = user_addr
        msg.target = target
        msg.amount = int(amount)

        any_msg = AnyPB()
        any_msg.type_url = "/mirage.core.v1.MsgSendTokens"
        any_msg.value = msg.SerializeToString()
        body = TxBody(messages=[any_msg], memo="")
        body_bytes = body.SerializeToString()
        content_len = len(target)
        gas_est = int(estimate_total_gas_limit(body_bytes, content_len))
        tx_bytes_est = build_tx_bytes(body_bytes, gas_est, zero_fee=is_subscriber(user_addr))
        gas_used = int(simulate_gas(tx_bytes_est))
        gas_limit = max(gas_est, int(gas_used * GAS_BUFFER_MULTIPLIER))
        tx_hash, code, height, raw_log = build_and_broadcast_tx(
            body_bytes, gas_limit, zero_fee=is_subscriber(user_addr)
        )

        if code != 0:
            extra = {
                "height": height,
                "user_addr": user_addr,
                "target": target,
                "amount": int(amount),
                "last_block_hash": last_block_hash,
                "difficulty": int(difficulty),
                "proof": int(proof),
            }
            return _tx_error(rid, "core/send_tokens", "MsgSendTokens", code, tx_hash, raw_log, extra)

        log_event(rid, "send_tokens.success", tx_hash=tx_hash)
        if user_addr.lower() != target.lower():
            event_key = donation_event_key(user_addr, target, tx_hash)
            inserted = record_inbox_event(
                event_key=event_key,
                recipient=target,
                actor=user_addr,
                event_type="donation",
                created_at=int(time.time()),
                amount=int(amount),
                tx_hash=tx_hash,
            )
            log_event(
                rid,
                "send_tokens.notify",
                recipient=target,
                actor=user_addr,
                amount=int(amount),
                tx_hash=tx_hash,
                inserted=inserted,
            )
            from routes.public import _invalidate_inbox_cache

            _invalidate_inbox_cache(target)
        return jsonify({"tx_hash": tx_hash, "code": code, "height": height, "raw_log": raw_log})
    except Exception as e:
        log_event(rid, "send_tokens.err", error=str(e))
        msg, status = _classify_exception(str(e))
        return jsonify({"error": msg}), status


@core_bp.route("/api/core/subscribe", methods=["POST"])
def core_subscribe():
    """Subscribe to a paid tier (self or gift).

    Required fields:
    - pubkey: Base64 encoded compressed public key
    - signature: Base64 encoded signature
    - last_block_hash: Recent block hash for replay protection
    - level: Target paid subscription level (1=Subscriber, 10=Agent)

    Optional fields:
    - target: Recipient address for gifting (omit or empty for self-subscribe)

    Note:
    - PoW is NOT allowed for MsgSubscribe. Users must pay with tokens.
    - To change auto-renewal without changing tier, use /api/core/set_auto_renewal instead.
    """
    rid = next_request_id()
    log_event(rid, "subscribe.begin")
    try:
        if is_node_catching_up():
            return api_error_code("node_catching_up", 503)
        data = request.get_json(force=True) or {}
        log_event(rid, "subscribe.data", data=data)
        pub_b64 = str(data.get("pubkey", "")).strip()
        sig_b64 = str(data.get("signature", "")).strip()
        last_block_hash = str(data.get("last_block_hash", "")).strip()
        target = str(data.get("target", "")).strip().lower()
        if "timestamp" not in data:
            return jsonify({"error": "timestamp required"}), 400
        try:
            timestamp = int(data.get("timestamp"))
        except (TypeError, ValueError):
            return jsonify({"error": "invalid timestamp"}), 400
        nonce, err = _parse_envelope_nonce(data)
        if err is not None:
            return err[0], err[1]
        level = int(data.get("level", 0))
        try:
            period_count = int(data.get("period_count", 1))
        except (TypeError, ValueError):
            period_count = 0

        if not (pub_b64 and sig_b64):
            return jsonify({"error": "missing required fields"}), 400

        if level != 1:
            return (
                jsonify({"error": "invalid level (must be 1; use set_auto_renewal to change auto-renewal)"}),
                400,
            )
        if period_count < 1 or period_count > 12:
            return jsonify({"error": "period_count must be in [1,12]"}), 400

        pub_dec = base64.b64decode(pub_b64)
        sig_dec = base64.b64decode(sig_b64)
        if len(sig_dec) == 65:
            sig_dec = sig_dec[:64]
        if len(pub_dec) != 33 or len(sig_dec) != 64:
            return jsonify({"error": "invalid relay fields"}), 400

        user_addr = derive_address_from_pubkey(pub_dec)
        if not user_addr:
            return jsonify({"error": "invalid pubkey"}), 400

        if target and not _is_valid_mirage_addr(target):
            return api_error_code("gift_invalid_target")

        is_gift = bool(target and target != user_addr)
        if is_gift:
            log_event(rid, "subscribe.gift", payer=user_addr, recipient=target)
            try:
                recipient_level = _db_get_profile_level(target) or 0
            except Exception as db_err:
                log_event(rid, "subscribe.db_error", error=str(db_err))
                return api_error_code("indexer_unavailable", 503)
            if recipient_level > level:
                return api_error_code("gift_rejected_higher_tier")

        validator_addr = require_runtime().validator_payer_addr

        # Backend precheck: ensure payer has enough balance
        p = expect_params()
        period_fee = 0
        try:
            tiers = p.get("tiers") or []
            tier_idx = {0: 0, 1: 1}.get(level, -1)
            if isinstance(tiers, list) and 0 <= tier_idx < len(tiers):
                tf = tiers[tier_idx] or {}
                period_fee = int(tf.get("period_fee", 0) or 0)
        except Exception:
            period_fee = 0
        if level > 0 and period_fee > 0:
            needed = int(period_fee) * int(period_count)
            try:
                bal = get_balance(user_addr)
                have = int(bal)
            except Exception as db_err:
                log_event(rid, "subscribe.db_error", error=str(db_err))
                return api_error_code("indexer_unavailable", 503)
            if have < needed:
                return api_error_code("insufficient_balance", balance=have, needed=needed)

        try:
            base = canon_base_subscribe(
                pub_dec,
                last_block_hash,
                0,
                timestamp,
                level,
                target=target if is_gift else "",
                nonce=nonce,
                period_count=period_count,
            )
            signed = canon_signed_with_pow(base, 0)
            if not _verify_signature(pub_dec, sig_dec, signed):
                log_event(rid, "subscribe.bad_signature", user=user_addr, period_count=period_count)
                return jsonify({"error": "invalid signature"}), 400
        except Exception as sig_exc:
            log_event(rid, "subscribe.signature_error", error=str(sig_exc))
            return jsonify({"error": "invalid signature"}), 400

        msg = MsgSubscribe()
        msg.authority = validator_addr
        msg.envelope_pubkey = pub_dec
        msg.envelope_block_hash = _hex_to_bytes(last_block_hash)
        msg.envelope_difficulty = 0
        msg.envelope_pow = 0
        msg.envelope_timestamp = int(timestamp)
        msg.envelope_nonce = nonce
        msg.envelope_signature = sig_dec
        msg.level = level
        msg.period_count = period_count
        if is_gift:
            msg.target = target

        any_msg = AnyPB()
        any_msg.type_url = "/mirage.core.v1.MsgSubscribe"
        any_msg.value = msg.SerializeToString()
        body = TxBody(messages=[any_msg], memo="")
        body_bytes = body.SerializeToString()
        gas_est = int(estimate_total_gas_limit(body_bytes, 0))
        tx_bytes_est = build_tx_bytes(body_bytes, gas_est, zero_fee=is_subscriber(user_addr))
        gas_used = int(simulate_gas(tx_bytes_est))
        gas_limit = max(gas_est, int(gas_used * GAS_BUFFER_MULTIPLIER))
        tx_hash, code, height, raw_log = build_and_broadcast_tx(
            body_bytes, gas_limit, zero_fee=is_subscriber(user_addr)
        )

        if code != 0:
            extra = {
                "height": height,
                "user_addr": user_addr,
                "level": int(level),
                "last_block_hash": last_block_hash,
                "target": target,
            }
            return _tx_error(rid, "core/subscribe", "MsgSubscribe", code, tx_hash, raw_log, extra)

        log_event(rid, "subscribe.success", tx_hash=tx_hash, is_gift=is_gift)
        if is_gift and user_addr.lower() != target.lower():
            try:
                target_level = _db_get_profile_level(target) or 0
                was_subscriber = target_level >= 1
                gifter_username = _get_username_for_owner(user_addr)
                event_key = subscription_gift_event_key(user_addr, target, tx_hash)
                inserted = record_inbox_event(
                    event_key=event_key,
                    recipient=target,
                    actor=user_addr,
                    event_type="subscription_gift",
                    created_at=int(time.time()),
                    amount=int(level),
                    tx_hash=tx_hash,
                )
                log_event(
                    rid,
                    "subscribe.inbox",
                    recipient=target,
                    actor=user_addr,
                    level=int(level),
                    was_subscriber=was_subscriber,
                    inserted=inserted,
                )
                from routes.public import _invalidate_inbox_cache

                _invalidate_inbox_cache(target)
            except Exception as push_err:
                log_event(rid, "subscribe.push_err", error=str(push_err))
        return jsonify({"tx_hash": tx_hash, "code": code, "height": height, "raw_log": raw_log})
    except Exception as e:
        log_event(rid, "subscribe.err", error=str(e))
        msg, status = _classify_exception(str(e))
        return jsonify({"error": msg}), status


@core_bp.route("/api/core/set_auto_renewal", methods=["POST"])
def core_set_auto_renewal():
    """Set auto_renew flag for an existing subscription.

    Required fields:
    - pubkey: Base64 encoded compressed public key
    - signature: Base64 encoded signature
    - last_block_hash: Recent block hash for replay protection (optional; no PoW)
    - auto_renew: Boolean flag (true to enable, false to disable)

    Notes:
    - PoW is NOT allowed for MsgSetAutoRenewal. Users must pay via reserve.
    - Only paid subscribers with an active subscription can enable auto-renew.
    """
    rid = next_request_id()
    log_event(rid, "set_auto_renewal.begin")
    try:
        if is_node_catching_up():
            return api_error_code("node_catching_up", 503)
        data = request.get_json(force=True) or {}
        log_event(rid, "set_auto_renewal.data", data=data)

        pub_b64 = str(data.get("pubkey", "")).strip()
        sig_b64 = str(data.get("signature", "")).strip()
        last_block_hash = str(data.get("last_block_hash", "")).strip()

        if "timestamp" not in data:
            return jsonify({"error": "timestamp required"}), 400
        try:
            timestamp = int(data.get("timestamp"))
        except (TypeError, ValueError):
            return jsonify({"error": "invalid timestamp"}), 400
        nonce, err = _parse_envelope_nonce(data)
        if err is not None:
            return err[0], err[1]

        if "auto_renew" not in data:
            return jsonify({"error": "auto_renew required"}), 400
        auto_renew = bool(data.get("auto_renew"))

        # PoW is never used for set_auto_renewal; difficulty/pow must be zero or omitted.
        difficulty = int(data.get("pow_difficulty", 0) or 0)
        proof = int(data.get("pow", 0) or 0)
        if difficulty != 0 or proof != 0:
            return jsonify({"error": "pow not allowed for set_auto_renewal"}), 400

        if not (pub_b64 and sig_b64):
            return jsonify({"error": "missing required fields"}), 400

        pub_dec = base64.b64decode(pub_b64)
        sig_dec = base64.b64decode(sig_b64)
        if len(sig_dec) == 65:
            sig_dec = sig_dec[:64]
        if len(pub_dec) != 33 or len(sig_dec) != 64:
            return jsonify({"error": "invalid relay fields"}), 400

        user_addr = derive_address_from_pubkey(pub_dec)
        if not user_addr:
            return jsonify({"error": "invalid pubkey"}), 400

        # Only subscribers can toggle auto-renewal; free users must upgrade first.
        if not is_subscriber(user_addr):
            return api_error_code("not_subscriber")

        validator_addr = require_runtime().validator_payer_addr

        # Backend signature verification (first line of defense)
        try:
            base = canon_base_set_auto_renewal(
                pub_dec,
                last_block_hash,
                0,
                timestamp,
                auto_renew,
                nonce=nonce,
            )
            signed = canon_signed_with_pow(base, 0)
            if not _verify_signature(pub_dec, sig_dec, signed):
                return jsonify({"error": "invalid signature"}), 400
        except Exception:
            return jsonify({"error": "invalid signature"}), 400

        msg = MsgSetAutoRenewal()
        msg.authority = validator_addr
        msg.envelope_pubkey = pub_dec
        msg.envelope_block_hash = _hex_to_bytes(last_block_hash)
        msg.envelope_difficulty = 0
        msg.envelope_pow = 0
        msg.envelope_timestamp = int(timestamp)
        msg.envelope_nonce = nonce
        msg.envelope_signature = sig_dec
        msg.auto_renew = auto_renew

        any_msg = AnyPB()
        any_msg.type_url = "/mirage.core.v1.MsgSetAutoRenewal"
        any_msg.value = msg.SerializeToString()
        body = TxBody(messages=[any_msg], memo="")
        body_bytes = body.SerializeToString()
        gas_est = int(estimate_total_gas_limit(body_bytes, 0))
        tx_bytes_est = build_tx_bytes(body_bytes, gas_est, zero_fee=is_subscriber(user_addr))
        gas_used = int(simulate_gas(tx_bytes_est))
        gas_limit = max(gas_est, int(gas_used * GAS_BUFFER_MULTIPLIER))
        tx_hash, code, height, raw_log = build_and_broadcast_tx(
            body_bytes, gas_limit, zero_fee=is_subscriber(user_addr)
        )

        if code != 0:
            extra = {
                "height": height,
                "user_addr": user_addr,
                "auto_renew": bool(auto_renew),
                "last_block_hash": last_block_hash,
            }
            return _tx_error(rid, "core/set_auto_renewal", "MsgSetAutoRenewal", code, tx_hash, raw_log, extra)

        log_event(rid, "set_auto_renewal.success", tx_hash=tx_hash)
        return jsonify({"tx_hash": tx_hash, "code": code, "height": height, "raw_log": raw_log})
    except Exception as e:
        log_event(rid, "set_auto_renewal.err", error=str(e))
        msg, status = _classify_exception(str(e))
        return jsonify({"error": msg}), status


@core_bp.route("/api/core/award", methods=["POST"])
def core_award():
    rid = next_request_id()
    log_event(rid, "award.begin")
    try:
        if is_node_catching_up():
            return api_error_code("node_catching_up", 503)
        data = request.get_json(force=True) or {}
        pub_b64 = str(data.get("pubkey", "")).strip()
        sig_b64 = str(data.get("signature", "")).strip()
        last_block_hash = str(data.get("last_block_hash", "")).strip()
        difficulty = int(data.get("pow_difficulty", 0) or 0)
        proof = int(data.get("pow", 0) or 0)
        target = str(data.get("target", "")).strip().lower()
        award_type = str(data.get("award_type", "")).strip()

        if "timestamp" not in data:
            return jsonify({"error": "timestamp required"}), 400
        try:
            timestamp = int(data.get("timestamp"))
        except (TypeError, ValueError):
            return jsonify({"error": "invalid timestamp"}), 400
        nonce, err = _parse_envelope_nonce(data)
        if err is not None:
            return err[0], err[1]

        if difficulty != 0 or proof != 0:
            return jsonify({"error": "pow not allowed for award"}), 400

        if not (pub_b64 and sig_b64 and target and award_type):
            return jsonify({"error": "missing required fields"}), 400

        if not _is_hex64(target):
            return jsonify({"error": "invalid target"}), 400

        pub_dec = base64.b64decode(pub_b64)
        sig_dec = base64.b64decode(sig_b64)
        if len(sig_dec) == 65:
            sig_dec = sig_dec[:64]
        if len(pub_dec) != 33 or len(sig_dec) != 64:
            return jsonify({"error": "invalid relay fields"}), 400

        user_addr = derive_address_from_pubkey(pub_dec)
        if not user_addr:
            return jsonify({"error": "invalid pubkey"}), 400

        p = expect_params()
        valid_types = {ac["name"] for ac in p.get("award_configs", [])}
        if award_type not in valid_types:
            return jsonify({"error": "unknown award type", "award_type": award_type}), 400

        post_owner = _get_post_owner(target)
        if not post_owner:
            return jsonify({"error": "target not found"}), 404

        if post_owner == user_addr.lower():
            return api_error_code("cannot_award_own_post")

        try:
            with connect_db(timeout=10.0, busy_timeout_ms=15000) as conn:
                cur = conn.cursor()
                cur.execute(
                    "SELECT 1 FROM awards WHERE LOWER(owner)=LOWER(%s) AND LOWER(target)=LOWER(%s) LIMIT 1",
                    (user_addr, target),
                )
                if cur.fetchone():
                    return api_error_code("already_awarded", 409)
        except Exception as e:
            log_event(rid, "award.dup_check_failed", error=str(e))
            return api_error_code("award_eligibility_failed", 503)

        validator_addr = require_runtime().validator_payer_addr

        try:
            base = canon_base_award(
                pub_dec,
                last_block_hash,
                0,
                timestamp,
                target,
                award_type,
                nonce=nonce,
            )
            signed = canon_signed_with_pow(base, 0)
            if not _verify_signature(pub_dec, sig_dec, signed):
                return jsonify({"error": "invalid signature"}), 400
        except Exception:
            return jsonify({"error": "invalid signature"}), 400

        msg = MsgAward()
        msg.authority = validator_addr
        msg.envelope_pubkey = pub_dec
        msg.envelope_block_hash = _hex_to_bytes(last_block_hash)
        msg.envelope_difficulty = 0
        msg.envelope_pow = 0
        msg.envelope_timestamp = int(timestamp)
        msg.envelope_nonce = nonce
        msg.envelope_signature = sig_dec
        msg.target = target
        msg.award_type = award_type

        any_msg = AnyPB()
        any_msg.type_url = "/mirage.core.v1.MsgAward"
        any_msg.value = msg.SerializeToString()
        body = TxBody(messages=[any_msg], memo="")
        body_bytes = body.SerializeToString()
        gas_est = int(estimate_total_gas_limit(body_bytes, 0))
        tx_bytes_est = build_tx_bytes(body_bytes, gas_est, zero_fee=is_subscriber(user_addr))
        gas_used = int(simulate_gas(tx_bytes_est))
        gas_limit = max(gas_est, int(gas_used * GAS_BUFFER_MULTIPLIER))
        tx_hash, code, height, raw_log = build_and_broadcast_tx(
            body_bytes, gas_limit, zero_fee=is_subscriber(user_addr)
        )

        if code != 0:
            extra = {
                "height": height,
                "user_addr": user_addr,
                "target": target,
                "award_type": award_type,
                "last_block_hash": last_block_hash,
            }
            return _tx_error(rid, "core/award", "MsgAward", code, tx_hash, raw_log, extra)

        log_event(rid, "award.success", tx_hash=tx_hash, target=target, award_type=award_type)

        try:
            from routes.public import _inbox_cache

            recipient = post_owner.lower()
            cached = _inbox_cache.get(recipient)
            if cached:
                _inbox_cache[recipient] = (cached[0] + 1, cached[1], cached[2] if len(cached) > 2 else 0)
            else:
                _inbox_cache.pop(recipient, None)
        except Exception:
            pass

        return jsonify({"tx_hash": tx_hash, "code": code, "height": height, "raw_log": raw_log})
    except Exception as e:
        log_event(rid, "award.err", error=str(e))
        msg, status = _classify_exception(str(e))
        return jsonify({"error": msg}), status


# ========== Push Token Endpoints ==========


@core_bp.route("/api/core/register_push_token", methods=["POST"])
def core_register_push_token():
    rid = next_request_id()
    log_event(rid, "register_push_token.begin")
    try:
        if not PUSH_NOTIFICATIONS_ENABLED:
            return jsonify({"error": "push notifications not enabled on this node"}), 404
        if is_node_catching_up():
            return api_error_code("node_catching_up", 503)

        data = request.get_json(force=True) or {}
        pub_b64 = str(data.get("pubkey", "")).strip()
        sig_b64 = str(data.get("signature", "")).strip()
        token = str(data.get("token", "")).strip()
        platform = str(data.get("platform", "")).strip()

        if "timestamp" not in data:
            return jsonify({"error": "timestamp required"}), 400
        try:
            timestamp = int(data.get("timestamp"))
        except (TypeError, ValueError):
            return jsonify({"error": "invalid timestamp"}), 400
        nonce, err = _parse_envelope_nonce(data)
        if err is not None:
            return err[0], err[1]

        if not (pub_b64 and sig_b64 and token and platform):
            return jsonify({"error": "missing required fields"}), 400

        if platform not in ("ios", "android"):
            return jsonify({"error": "platform must be ios or android"}), 400

        if len(token) > 200:
            return jsonify({"error": "invalid expo push token length"}), 400
        if not re.fullmatch(r"ExponentPushToken\[[A-Za-z0-9_-]+\]", token):
            return jsonify({"error": "invalid expo push token format"}), 400

        pub_dec = base64.b64decode(pub_b64)
        sig_dec = base64.b64decode(sig_b64)
        if len(sig_dec) == 65:
            sig_dec = sig_dec[:64]
        if len(pub_dec) != 33 or len(sig_dec) != 64:
            return jsonify({"error": "invalid relay fields"}), 400

        user_addr = derive_address_from_pubkey(pub_dec)
        if not user_addr:
            return jsonify({"error": "invalid pubkey"}), 400

        signed_payload = f"register_push_token:{token}:{platform}:{timestamp}:{nonce}"
        if not _verify_signature(pub_dec, sig_dec, signed_payload.encode("utf-8")):
            return jsonify({"error": "invalid signature"}), 400
        ok, err = _guard_push_request(user_addr, "register_push_token", timestamp, nonce)
        if not ok:
            return err[0], err[1]

        now_ts = int(time.time())
        with connect_backend_db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT owner FROM push_tokens WHERE token = %s LIMIT 1", (token,))
                existing = cur.fetchone()

                # Expo push tokens are device-scoped, not wallet-scoped: the same
                # device keeps its token across logout/reinstall. Registration is
                # last-writer-wins so the currently signed-in account reclaims the
                # device token even when a prior logout unregister failed (offline
                # or network error). Only a signed register from the active wallet
                # can reassign; unregister remains owner-scoped.
                is_transfer = bool(existing and existing[0] and existing[0].strip().lower() != user_addr.lower())
                if is_transfer:
                    log_event(
                        rid,
                        "register_push_token.transfer",
                        old_owner=existing[0].strip().lower(),
                        new_owner=user_addr.lower(),
                        token=token[:30],
                    )

                cur.execute(
                    """
                    INSERT INTO push_tokens (owner, token, platform, created_at, last_used_at)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (token) DO UPDATE SET
                        owner = EXCLUDED.owner,
                        platform = EXCLUDED.platform,
                        last_used_at = EXCLUDED.last_used_at
                    """,
                    (user_addr.lower(), token, platform, now_ts, now_ts),
                )

                # Registration validated token shape but never bounded how many an
                # owner could accumulate, and delivery builds one unchunked Expo
                # message per token against Expo's documented 100-message limit.
                # Evicting the least recently used keeps a real user's devices
                # working while bounding the fan-out.
                cur.execute(
                    """
                    DELETE FROM push_tokens
                    WHERE LOWER(owner) = %s
                      AND token NOT IN (
                        SELECT token FROM push_tokens
                        WHERE LOWER(owner) = %s
                        ORDER BY last_used_at DESC, token
                        LIMIT %s
                      )
                    """,
                    (user_addr.lower(), user_addr.lower(), MAX_PUSH_TOKENS_PER_OWNER),
                )
                if cur.rowcount:
                    log_event(rid, "register_push_token.evicted", owner=user_addr.lower(), evicted=cur.rowcount)

                # First push token for this account on this node: defer the
                # lively-topic push by ~24h. Each node tracks trending state in
                # its own backend DB, so without this a user who switches nodes
                # could receive a second lively push the same day from the
                # newly-connected node. The conditional upsert only seeds users
                # with no prior lively-push timestamp, so it never resets the
                # clock for someone already in the rotation. On a token transfer
                # the row exists but belongs to a different (new) owner, so the
                # new owner must be seeded too — the WHERE guard still protects
                # anyone already in the rotation.
                if not existing or is_transfer:
                    cur.execute(
                        """
                        INSERT INTO user_inbox_state (owner, trending_last_sent_at)
                        VALUES (%s, %s)
                        ON CONFLICT (owner) DO UPDATE
                        SET trending_last_sent_at = EXCLUDED.trending_last_sent_at
                        WHERE COALESCE(user_inbox_state.trending_last_sent_at, 0) <= 0
                        """,
                        (user_addr.lower(), now_ts),
                    )

        is_new = not existing
        log_event(rid, "register_push_token.ok", user=user_addr, platform=platform, token=token[:30], new=is_new)
        return jsonify({"ok": True})
    except Exception as e:
        log_event(rid, "register_push_token.err", error=str(e))
        msg, status = _classify_exception(str(e))
        return jsonify({"error": msg}), status


@core_bp.route("/api/core/unregister_push_token", methods=["POST"])
def core_unregister_push_token():
    rid = next_request_id()
    log_event(rid, "unregister_push_token.begin")
    try:
        if not PUSH_NOTIFICATIONS_ENABLED:
            return jsonify({"error": "push notifications not enabled on this node"}), 404
        if is_node_catching_up():
            return api_error_code("node_catching_up", 503)

        data = request.get_json(force=True) or {}
        pub_b64 = str(data.get("pubkey", "")).strip()
        sig_b64 = str(data.get("signature", "")).strip()
        token = str(data.get("token", "")).strip()

        if "timestamp" not in data:
            return jsonify({"error": "timestamp required"}), 400
        try:
            timestamp = int(data.get("timestamp"))
        except (TypeError, ValueError):
            return jsonify({"error": "invalid timestamp"}), 400
        nonce, err = _parse_envelope_nonce(data)
        if err is not None:
            return err[0], err[1]

        if not (pub_b64 and sig_b64 and token):
            return jsonify({"error": "missing required fields"}), 400

        pub_dec = base64.b64decode(pub_b64)
        sig_dec = base64.b64decode(sig_b64)
        if len(sig_dec) == 65:
            sig_dec = sig_dec[:64]
        if len(pub_dec) != 33 or len(sig_dec) != 64:
            return jsonify({"error": "invalid relay fields"}), 400

        user_addr = derive_address_from_pubkey(pub_dec)
        if not user_addr:
            return jsonify({"error": "invalid pubkey"}), 400

        signed_payload = f"unregister_push_token:{token}:{timestamp}:{nonce}"
        if not _verify_signature(pub_dec, sig_dec, signed_payload.encode("utf-8")):
            return jsonify({"error": "invalid signature"}), 400
        ok, err = _guard_push_request(user_addr, "unregister_push_token", timestamp, nonce)
        if not ok:
            return err[0], err[1]

        with connect_backend_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM push_tokens WHERE token = %s AND LOWER(owner) = LOWER(%s)",
                    (token, user_addr),
                )
                deleted = cur.rowcount

        log_event(rid, "unregister_push_token.ok", user=user_addr, token=token[:30], deleted=deleted)
        return jsonify({"ok": True})
    except Exception as e:
        log_event(rid, "unregister_push_token.err", error=str(e))
        msg, status = _classify_exception(str(e))
        return jsonify({"error": msg}), status


def _parse_relay_envelope(data: dict):
    pub_b64 = str(data.get("pubkey", "")).strip()
    sig_b64 = str(data.get("signature", "")).strip()
    last_block_hash = str(data.get("last_block_hash", "")).strip()
    try:
        difficulty = int(data.get("pow_difficulty", 0))
    except (TypeError, ValueError):
        return None, jsonify({"error": "invalid pow_difficulty"}), 400
    try:
        proof = int(data.get("pow", 0))
    except (TypeError, ValueError):
        return None, jsonify({"error": "invalid pow"}), 400
    if "timestamp" not in data:
        return None, jsonify({"error": "timestamp required"}), 400
    try:
        timestamp = int(data.get("timestamp"))
    except (TypeError, ValueError):
        return None, jsonify({"error": "invalid timestamp"}), 400
    nonce, err = _parse_envelope_nonce(data)
    if err is not None:
        return None, err[0], err[1]
    if not (pub_b64 and sig_b64):
        return None, jsonify({"error": "missing required fields"}), 400
    pub_dec = base64.b64decode(pub_b64)
    sig_dec = base64.b64decode(sig_b64)
    if len(sig_dec) == 65:
        sig_dec = sig_dec[:64]
    if len(pub_dec) != 33 or len(sig_dec) != 64:
        return None, jsonify({"error": "invalid relay fields"}), 400
    user_addr = derive_address_from_pubkey(pub_dec)
    if not user_addr:
        return None, jsonify({"error": "invalid pubkey"}), 400
    return (
        {
            "pub_dec": pub_dec,
            "sig_dec": sig_dec,
            "last_block_hash": last_block_hash,
            "difficulty": difficulty,
            "proof": proof,
            "timestamp": timestamp,
            "nonce": nonce,
            "user_addr": user_addr,
        },
        None,
        None,
    )


def _broadcast_core_msg(rid: str, log_name: str, type_url: str, msg, extra_len: int, user_addr: str):
    any_msg = AnyPB()
    any_msg.type_url = type_url
    any_msg.value = msg.SerializeToString()
    body = TxBody(messages=[any_msg], memo="")
    body_bytes = body.SerializeToString()
    gas_est = int(estimate_total_gas_limit(body_bytes, extra_len))
    tx_bytes_est = build_tx_bytes(body_bytes, gas_est, zero_fee=is_subscriber(user_addr))
    gas_used = int(simulate_gas(tx_bytes_est))
    gas_limit = max(gas_est, int(gas_used * GAS_BUFFER_MULTIPLIER))
    tx_hash, code, height, raw_log = build_and_broadcast_tx(body_bytes, gas_limit, zero_fee=is_subscriber(user_addr))
    if code != 0:
        extra = {"height": height, "user_addr": user_addr}
        return _tx_error(rid, f"core/{log_name}", type_url.rsplit(".", 1)[-1], code, tx_hash, raw_log, extra)
    log_event(rid, f"{log_name}.success", tx_hash=tx_hash)
    return jsonify({"tx_hash": tx_hash, "code": code, "height": height, "raw_log": raw_log})


def _fill_envelope(msg, env: dict, validator_addr: str):
    msg.authority = validator_addr
    msg.envelope_pubkey = env["pub_dec"]
    msg.envelope_block_hash = _hex_to_bytes(env["last_block_hash"])
    msg.envelope_difficulty = int(env["difficulty"])
    msg.envelope_pow = int(env["proof"])
    msg.envelope_timestamp = env["timestamp"]
    msg.envelope_nonce = env["nonce"]
    msg.envelope_signature = env["sig_dec"]


def _maybe_pow_precheck(rid, action, env, base_fn, *args):
    if is_subscriber(env["user_addr"]):
        return None
    try:
        base = base_fn(
            env["pub_dec"], env["last_block_hash"], int(env["difficulty"]), env["timestamp"], *args, nonce=env["nonce"]
        )
        digest = argon2_digest(base, env["last_block_hash"], env["proof"])
        if digest is not None:
            effective_required = _effective_difficulty(int(env["difficulty"]))
            if not check_pow_target(digest, effective_required, get_pow_base_bits(), _pow_factor()):
                return jsonify({"error": "insufficient pow (precheck)"}), 400
    except Exception as exc:
        _log_pow_precheck_error(rid, action, exc)
    return None


@core_bp.route("/api/core/join_community", methods=["POST"])
def core_join_community():
    rid = next_request_id()
    try:
        if is_node_catching_up():
            return api_error_code("node_catching_up", 503)
        data = request.get_json(force=True) or {}
        env, err, status = _parse_relay_envelope(data)
        if env is None:
            return err, status
        community = str(data.get("community", "")).strip().lower()
        if not community:
            return jsonify({"error": "community required"}), 400
        pow_err = _maybe_pow_precheck(rid, "join_community", env, canon_base_join_community, community)
        if pow_err:
            return pow_err
        msg = MsgJoinCommunity()
        _fill_envelope(msg, env, require_runtime().validator_payer_addr)
        msg.community = community
        return _broadcast_core_msg(
            rid, "join_community", "/mirage.core.v1.MsgJoinCommunity", msg, len(community), env["user_addr"]
        )
    except Exception as e:
        log_event(rid, "join_community.err", error=str(e))
        msg, status = _classify_exception(str(e))
        return jsonify({"error": msg}), status


@core_bp.route("/api/core/leave_community", methods=["POST"])
def core_leave_community():
    rid = next_request_id()
    try:
        if is_node_catching_up():
            return api_error_code("node_catching_up", 503)
        data = request.get_json(force=True) or {}
        env, err, status = _parse_relay_envelope(data)
        if env is None:
            return err, status
        community = str(data.get("community", "")).strip().lower()
        if not community:
            return jsonify({"error": "community required"}), 400
        pow_err = _maybe_pow_precheck(rid, "leave_community", env, canon_base_leave_community, community)
        if pow_err:
            return pow_err
        msg = MsgLeaveCommunity()
        _fill_envelope(msg, env, require_runtime().validator_payer_addr)
        msg.community = community
        return _broadcast_core_msg(
            rid, "leave_community", "/mirage.core.v1.MsgLeaveCommunity", msg, len(community), env["user_addr"]
        )
    except Exception as e:
        log_event(rid, "leave_community.err", error=str(e))
        msg, status = _classify_exception(str(e))
        return jsonify({"error": msg}), status


@core_bp.route("/api/core/block_community", methods=["POST"])
def core_block_community():
    rid = next_request_id()
    try:
        if is_node_catching_up():
            return api_error_code("node_catching_up", 503)
        data = request.get_json(force=True) or {}
        env, err, status = _parse_relay_envelope(data)
        if env is None:
            return err, status
        target = str(data.get("target", "")).strip().lower()
        community = str(data.get("community", "")).strip().lower()
        if not target or not community:
            return jsonify({"error": "target and community required"}), 400
        pow_err = _maybe_pow_precheck(rid, "block_community", env, canon_base_block_community, target, community)
        if pow_err:
            return pow_err
        msg = MsgBlockCommunity()
        _fill_envelope(msg, env, require_runtime().validator_payer_addr)
        msg.target = target
        msg.community = community
        return _broadcast_core_msg(
            rid,
            "block_community",
            "/mirage.core.v1.MsgBlockCommunity",
            msg,
            len(target) + len(community),
            env["user_addr"],
        )
    except Exception as e:
        log_event(rid, "block_community.err", error=str(e))
        msg, status = _classify_exception(str(e))
        return jsonify({"error": msg}), status


@core_bp.route("/api/core/unblock_community", methods=["POST"])
def core_unblock_community():
    rid = next_request_id()
    try:
        if is_node_catching_up():
            return api_error_code("node_catching_up", 503)
        data = request.get_json(force=True) or {}
        env, err, status = _parse_relay_envelope(data)
        if env is None:
            return err, status
        target = str(data.get("target", "")).strip().lower()
        community = str(data.get("community", "")).strip().lower()
        if not target or not community:
            return jsonify({"error": "target and community required"}), 400
        pow_err = _maybe_pow_precheck(rid, "unblock_community", env, canon_base_unblock_community, target, community)
        if pow_err:
            return pow_err
        msg = MsgUnblockCommunity()
        _fill_envelope(msg, env, require_runtime().validator_payer_addr)
        msg.target = target
        msg.community = community
        return _broadcast_core_msg(
            rid,
            "unblock_community",
            "/mirage.core.v1.MsgUnblockCommunity",
            msg,
            len(target) + len(community),
            env["user_addr"],
        )
    except Exception as e:
        log_event(rid, "unblock_community.err", error=str(e))
        msg, status = _classify_exception(str(e))
        return jsonify({"error": msg}), status


@core_bp.route("/api/core/create_community", methods=["POST"])
def core_create_community():
    rid = next_request_id()
    try:
        if is_node_catching_up():
            return api_error_code("node_catching_up", 503)
        data = request.get_json(force=True) or {}
        env, err, status = _parse_relay_envelope(data)
        if env is None:
            return err, status
        community = str(data.get("community", "")).strip().lower()
        title = str(data.get("title", "") or "")
        description = str(data.get("description", "") or "")
        original_team_name = str(data.get("original_team_name", "") or "")
        bio = str(data.get("bio", "") or "")
        policy = str(data.get("policy", "") or "")
        if not community:
            return jsonify({"error": "community required"}), 400
        pow_err = _maybe_pow_precheck(
            rid,
            "create_community",
            env,
            canon_base_create_community,
            community,
            title,
            description,
            original_team_name,
            bio,
            policy,
        )
        if pow_err:
            return pow_err
        msg = MsgCreateCommunity()
        _fill_envelope(msg, env, require_runtime().validator_payer_addr)
        msg.community = community
        msg.title = title
        msg.description = description
        msg.original_team_name = original_team_name
        msg.bio = bio
        msg.policy = policy
        return _broadcast_core_msg(
            rid,
            "create_community",
            "/mirage.core.v1.MsgCreateCommunity",
            msg,
            len(community) + len(title),
            env["user_addr"],
        )
    except Exception as e:
        log_event(rid, "create_community.err", error=str(e))
        msg, status = _classify_exception(str(e))
        return jsonify({"error": msg}), status


@core_bp.route("/api/core/set_community_metadata", methods=["POST"])
def core_set_community_metadata():
    rid = next_request_id()
    try:
        if is_node_catching_up():
            return api_error_code("node_catching_up", 503)
        data = request.get_json(force=True) or {}
        env, err, status = _parse_relay_envelope(data)
        if env is None:
            return err, status
        community = str(data.get("community", "")).strip().lower()
        title = str(data.get("title", "") or "")
        description = str(data.get("description", "") or "")
        if not community:
            return jsonify({"error": "community required"}), 400
        pow_err = _maybe_pow_precheck(
            rid, "set_community_metadata", env, canon_base_set_community_metadata, community, title, description
        )
        if pow_err:
            return pow_err
        msg = MsgSetCommunityMetadata()
        _fill_envelope(msg, env, require_runtime().validator_payer_addr)
        msg.community = community
        msg.title = title
        msg.description = description
        return _broadcast_core_msg(
            rid,
            "set_community_metadata",
            "/mirage.core.v1.MsgSetCommunityMetadata",
            msg,
            len(community),
            env["user_addr"],
        )
    except Exception as e:
        log_event(rid, "set_community_metadata.err", error=str(e))
        msg, status = _classify_exception(str(e))
        return jsonify({"error": msg}), status


@core_bp.route("/api/core/transfer_community", methods=["POST"])
def core_transfer_community():
    rid = next_request_id()
    try:
        if is_node_catching_up():
            return api_error_code("node_catching_up", 503)
        data = request.get_json(force=True) or {}
        env, err, status = _parse_relay_envelope(data)
        if env is None:
            return err, status
        community = str(data.get("community", "")).strip().lower()
        new_founder = str(data.get("new_founder", "")).strip().lower()
        if not community or not new_founder:
            return jsonify({"error": "community and new_founder required"}), 400
        pow_err = _maybe_pow_precheck(
            rid, "transfer_community", env, canon_base_transfer_community, community, new_founder
        )
        if pow_err:
            return pow_err
        msg = MsgTransferCommunity()
        _fill_envelope(msg, env, require_runtime().validator_payer_addr)
        msg.community = community
        msg.new_founder = new_founder
        return _broadcast_core_msg(
            rid, "transfer_community", "/mirage.core.v1.MsgTransferCommunity", msg, len(community), env["user_addr"]
        )
    except Exception as e:
        log_event(rid, "transfer_community.err", error=str(e))
        msg, status = _classify_exception(str(e))
        return jsonify({"error": msg}), status


@core_bp.route("/api/core/create_curation_team", methods=["POST"])
def core_create_curation_team():
    rid = next_request_id()
    try:
        if is_node_catching_up():
            return api_error_code("node_catching_up", 503)
        data = request.get_json(force=True) or {}
        env, err, status = _parse_relay_envelope(data)
        if env is None:
            return err, status
        community = str(data.get("community", "")).strip().lower()
        name = str(data.get("name", "") or "")
        bio = str(data.get("bio", "") or "")
        policy = str(data.get("policy", "") or "")
        if not community or not name:
            return jsonify({"error": "community and name required"}), 400
        pow_err = _maybe_pow_precheck(
            rid, "create_curation_team", env, canon_base_create_curation_team, community, name, bio, policy
        )
        if pow_err:
            return pow_err
        msg = MsgCreateCurationTeam()
        _fill_envelope(msg, env, require_runtime().validator_payer_addr)
        msg.community = community
        msg.name = name
        msg.bio = bio
        msg.policy = policy
        return _broadcast_core_msg(
            rid,
            "create_curation_team",
            "/mirage.core.v1.MsgCreateCurationTeam",
            msg,
            len(community) + len(name),
            env["user_addr"],
        )
    except Exception as e:
        log_event(rid, "create_curation_team.err", error=str(e))
        msg, status = _classify_exception(str(e))
        return jsonify({"error": msg}), status


@core_bp.route("/api/core/set_curation_preference", methods=["POST"])
def core_set_curation_preference():
    rid = next_request_id()
    try:
        if is_node_catching_up():
            return api_error_code("node_catching_up", 503)
        data = request.get_json(force=True) or {}
        env, err, status = _parse_relay_envelope(data)
        if env is None:
            return err, status
        community = str(data.get("community", "")).strip().lower()
        try:
            mode = int(data.get("mode", 0))
        except (TypeError, ValueError):
            return jsonify({"error": "invalid mode"}), 400
        try:
            pinned_team_id = int(data.get("pinned_team_id", 0) or 0)
        except (TypeError, ValueError):
            return jsonify({"error": "invalid pinned_team_id"}), 400
        if not community:
            return jsonify({"error": "community required"}), 400
        pow_err = _maybe_pow_precheck(
            rid, "set_curation_preference", env, canon_base_set_curation_preference, community, mode, pinned_team_id
        )
        if pow_err:
            return pow_err
        msg = MsgSetCurationPreference()
        _fill_envelope(msg, env, require_runtime().validator_payer_addr)
        msg.community = community
        msg.mode = mode
        msg.pinned_team_id = pinned_team_id
        return _broadcast_core_msg(
            rid,
            "set_curation_preference",
            "/mirage.core.v1.MsgSetCurationPreference",
            msg,
            len(community),
            env["user_addr"],
        )
    except Exception as e:
        log_event(rid, "set_curation_preference.err", error=str(e))
        msg, status = _classify_exception(str(e))
        return jsonify({"error": msg}), status


@core_bp.route("/api/core/claim_creator_rewards", methods=["POST"])
def core_claim_creator_rewards():
    rid = next_request_id()
    try:
        if is_node_catching_up():
            return api_error_code("node_catching_up", 503)
        data = request.get_json(force=True) or {}
        env, err, status = _parse_relay_envelope(data)
        if env is None:
            return err, status
        raw_ids = data.get("epoch_ids") or []
        if not isinstance(raw_ids, list) or not raw_ids:
            return jsonify({"error": "epoch_ids required"}), 400
        epoch_ids = [int(x) for x in raw_ids]
        if len(epoch_ids) > 30:
            return jsonify({"error": "at most 30 epoch_ids"}), 400
        if epoch_ids != sorted(set(epoch_ids)) or epoch_ids != sorted(epoch_ids):
            return jsonify({"error": "epoch_ids must be strictly increasing"}), 400
        prev = 0
        for eid in epoch_ids:
            if eid <= prev:
                return jsonify({"error": "epoch_ids must be strictly increasing"}), 400
            prev = eid
        pow_err = _maybe_pow_precheck(rid, "claim_creator_rewards", env, canon_base_claim_creator_rewards, epoch_ids)
        if pow_err:
            return pow_err
        msg = MsgClaimCreatorRewards()
        _fill_envelope(msg, env, require_runtime().validator_payer_addr)
        msg.epoch_ids.extend(epoch_ids)
        return _broadcast_core_msg(
            rid,
            "claim_creator_rewards",
            "/mirage.core.v1.MsgClaimCreatorRewards",
            msg,
            8 * len(epoch_ids),
            env["user_addr"],
        )
    except Exception as e:
        log_event(rid, "claim_creator_rewards.err", error=str(e))
        msg, status = _classify_exception(str(e))
        return jsonify({"error": msg}), status


def _curation_team_route(path, log_name, type_url, msg_cls, fields):
    """Register a signed-relay route whose payload is community + optional team_id/target/bools."""

    @core_bp.route(path, methods=["POST"], endpoint=log_name)
    def _handler():
        rid = next_request_id()
        try:
            if is_node_catching_up():
                return api_error_code("node_catching_up", 503)
            data = request.get_json(force=True) or {}
            env, err, status = _parse_relay_envelope(data)
            if env is None:
                return err, status
            msg = msg_cls()
            _fill_envelope(msg, env, require_runtime().validator_payer_addr)
            community = str(data.get("community", "")).strip().lower()
            if "community" in fields and not community:
                return jsonify({"error": "community required"}), 400
            if "community" in fields:
                msg.community = community
            if "team_id" in fields:
                msg.team_id = int(data.get("team_id", 0) or 0)
            if "target" in fields:
                msg.target = str(data.get("target", "")).strip().lower()
            if "new_owner" in fields:
                msg.new_owner = str(data.get("new_owner", "")).strip().lower()
            if "name" in fields:
                msg.name = str(data.get("name", "") or "")
            if "bio" in fields:
                msg.bio = str(data.get("bio", "") or "")
            if "policy" in fields:
                msg.policy = str(data.get("policy", "") or "")
            if "hidden" in fields:
                msg.hidden = bool(data.get("hidden"))
            if "locked" in fields:
                msg.locked = bool(data.get("locked"))
            if "enabled" in fields:
                msg.enabled = bool(data.get("enabled"))
            if "root_hash" in fields:
                msg.root_hash = str(data.get("root_hash", "") or "").strip().lower()
            return _broadcast_core_msg(rid, log_name, type_url, msg, 64, env["user_addr"])
        except Exception as e:
            log_event(rid, f"{log_name}.err", error=str(e))
            emsg, estatus = _classify_exception(str(e))
            return jsonify({"error": emsg}), estatus

    return _handler


_curation_team_route(
    "/api/core/set_curation_team_profile",
    "set_curation_team_profile",
    "/mirage.core.v1.MsgSetCurationTeamProfile",
    MsgSetCurationTeamProfile,
    {"community", "team_id", "name", "bio", "policy"},
)
_curation_team_route(
    "/api/core/invite_curator",
    "invite_curator",
    "/mirage.core.v1.MsgInviteCurator",
    MsgInviteCurator,
    {"community", "team_id", "target"},
)
_curation_team_route(
    "/api/core/revoke_curator_invite",
    "revoke_curator_invite",
    "/mirage.core.v1.MsgRevokeCuratorInvite",
    MsgRevokeCuratorInvite,
    {"community", "team_id", "target"},
)
_curation_team_route(
    "/api/core/accept_curator_invite",
    "accept_curator_invite",
    "/mirage.core.v1.MsgAcceptCuratorInvite",
    MsgAcceptCuratorInvite,
    {"community", "team_id"},
)
_curation_team_route(
    "/api/core/decline_curator_invite",
    "decline_curator_invite",
    "/mirage.core.v1.MsgDeclineCuratorInvite",
    MsgDeclineCuratorInvite,
    {"community", "team_id"},
)
_curation_team_route(
    "/api/core/leave_curation_team",
    "leave_curation_team",
    "/mirage.core.v1.MsgLeaveCurationTeam",
    MsgLeaveCurationTeam,
    {"community", "team_id"},
)
_curation_team_route(
    "/api/core/remove_curator",
    "remove_curator",
    "/mirage.core.v1.MsgRemoveCurator",
    MsgRemoveCurator,
    {"community", "team_id", "target"},
)
_curation_team_route(
    "/api/core/transfer_curation_team",
    "transfer_curation_team",
    "/mirage.core.v1.MsgTransferCurationTeam",
    MsgTransferCurationTeam,
    {"community", "team_id", "new_owner"},
)
_curation_team_route(
    "/api/core/delete_curation_team",
    "delete_curation_team",
    "/mirage.core.v1.MsgDeleteCurationTeam",
    MsgDeleteCurationTeam,
    {"community", "team_id"},
)
_curation_team_route(
    "/api/core/set_curation_post_hidden",
    "set_curation_post_hidden",
    "/mirage.core.v1.MsgSetCurationPostHidden",
    MsgSetCurationPostHidden,
    {"community", "team_id", "target", "hidden"},
)
_curation_team_route(
    "/api/core/set_curation_user_hidden",
    "set_curation_user_hidden",
    "/mirage.core.v1.MsgSetCurationUserHidden",
    MsgSetCurationUserHidden,
    {"community", "team_id", "target", "hidden"},
)
_curation_team_route(
    "/api/core/set_curation_thread_locked",
    "set_curation_thread_locked",
    "/mirage.core.v1.MsgSetCurationThreadLocked",
    MsgSetCurationThreadLocked,
    {"community", "team_id", "root_hash", "locked"},
)
_curation_team_route(
    "/api/core/set_curation_subscriber_only",
    "set_curation_subscriber_only",
    "/mirage.core.v1.MsgSetCurationSubscriberOnly",
    MsgSetCurationSubscriberOnly,
    {"community", "team_id", "enabled"},
)


__all__ = ["core_bp"]
