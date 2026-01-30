from __future__ import annotations

"""Core message relay endpoints.

Endpoints:
- POST /api/core/set_username: Relay meta-signed username message.
- POST /api/core/block_post: Relay meta-signed block post message.
- POST /api/core/block_user: Relay meta-signed block user message.
- POST /api/core/post: Relay meta-signed post/comment message.
- POST /api/core/vote: Relay meta-signed vote message.
"""

import base64
import re
from typing import Any, Dict
import time

from flask import Blueprint, jsonify, request
from google.protobuf.any_pb2 import Any as AnyPB
from cosmpy.protos.cosmos.tx.v1beta1.tx_pb2 import TxBody, AuthInfo, Fee, TxRaw, SignerInfo, ModeInfo
from cosmpy.protos.cosmos.tx.signing.v1beta1.signing_pb2 import SignMode
from cosmpy.protos.cosmos.base.v1beta1.coin_pb2 import Coin
from cosmpy.protos.cosmos.bank.v1beta1.tx_pb2 import MsgSend

from shared.datatypes import (
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
    MsgSendTokens,
    MsgPost,
    MsgVote,
    MsgEdit,
    MsgUpgradeLevel,
    MsgSetAutoRenewal,
)

from logging_utils import log_event, next_request_id
from node import derive_address_from_pubkey, min_gas_price_umirage, require_runtime
from params import expect_params, load_params
from db import connect_db
from pow import (
    argon2_digest,
    canon_base_post,
    canon_base_edit,
    canon_base_vote,
    canon_base_set_username,
    canon_base_follow_moderator,
    canon_base_unfollow_moderator,
    canon_base_follow_user,
    canon_base_unfollow_user,
    canon_base_follow_topic,
    canon_base_unfollow_topic,
    canon_base_block_post,
    canon_base_unblock_post,
    canon_base_block_user,
    canon_base_unblock_user,
    canon_base_report,
    canon_base_delete,
    canon_base_send_tokens,
    canon_base_upgrade_level,
    canon_base_set_auto_renewal,
    count_leading_zero_bits,
    decode_b64,
)
from shared.canon import canon_signed_with_pow
from tx import estimate_total_gas_limit, build_tx_bytes, simulate_gas, broadcast_tx
from chain import (
    classify_reject,
    get_current_pow_difficulty,
    get_difficulty_info,
    is_node_catching_up,
    is_valid_recent_block_hash,
)
from bank import get_balance
import hashlib
import json
import socket
import urllib.request as _ur
from psycopg.types.json import Jsonb


core_bp = Blueprint("core", __name__)

# Gas estimation buffer (multiplier). Simulation can underestimate due to
# state changes between simulation and execution, and storage write costs
# (WriteFlat) that vary based on key/value sizes.
GAS_BUFFER_MULTIPLIER = 1.30  # 30% buffer


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


def _get_utc_julian_day(ts: int) -> int:
    """Convert Unix timestamp to UTC Julian day number."""
    return 2440588 + (ts // 86400)


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
    
    with connect_db() as conn:
        with conn.cursor() as cur:
            # Step 1: Find the invite code used by this new user
            cur.execute(
                """
                SELECT owner, code FROM invite_codes
                WHERE LOWER(used_by) = LOWER(%s)
                ORDER BY used_at DESC
                LIMIT 1
                """,
                (new_user_addr,)
            )
            invite_row = cur.fetchone()
            
            if not invite_row:
                log_event(rid, "invite_quest.no_invite_code", new_user=new_user_addr)
                return
            
            referrer_addr, invite_code = invite_row
            referrer_addr = referrer_addr.lower()
            log_event(rid, "invite_quest.found_referrer", new_user=new_user_addr, referrer=referrer_addr, code=invite_code)
            
            # Step 2: Check if referrer has invite_recruit quest for today, not completed
            cur.execute(
                """
                SELECT quest_id, completed_at FROM user_daily_quests
                WHERE LOWER(owner) = LOWER(%s) AND day_utc = %s AND quest_id = 'invite_recruit'
                """,
                (referrer_addr, day_utc)
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
                (now_ts, referrer_addr, day_utc)
            )
            
            # Step 4: Insert pending reward for referrer (10k MIRAGE = 10,000,000,000 umirage)
            reward_amount_umirage = 10000 * 1_000_000  # 10k MIRAGE
            cur.execute(
                """
                INSERT INTO pending_rewards (owner, reward_type, reward_data, reason, created_at)
                VALUES (%s, 'mirage', %s, 'quest:invite_recruit', %s)
                """,
                (referrer_addr, json.dumps({"amount": reward_amount_umirage, "apply_multiplier": False}), now_ts)
            )
            log_event(rid, "invite_quest.referrer_reward_created", referrer=referrer_addr, amount=reward_amount_umirage)
            
            # Step 5: Insert invite_referred quest for new user (already completed)
            cur.execute(
                """
                INSERT INTO user_daily_quests (owner, day_utc, quest_id, progress, progress_meta, completed_at)
                VALUES (%s, %s, 'invite_referred', 1, '{}', %s)
                ON CONFLICT (owner, day_utc, quest_id) DO NOTHING
                """,
                (new_user_addr, day_utc, now_ts)
            )
            
            # Step 6: Insert pending reward for new user (10k MIRAGE)
            cur.execute(
                """
                INSERT INTO pending_rewards (owner, reward_type, reward_data, reason, created_at)
                VALUES (%s, 'mirage', %s, 'quest:invite_referred', %s)
                """,
                (new_user_addr, json.dumps({"amount": reward_amount_umirage, "apply_multiplier": False}), now_ts)
            )
            log_event(rid, "invite_quest.referee_reward_created", new_user=new_user_addr, amount=reward_amount_umirage)
            
            log_event(rid, "invite_quest.completed", referrer=referrer_addr, new_user=new_user_addr)


def _hex_to_bytes(s: str) -> bytes:
    """Convert hex string to bytes for envelope_block_hash."""
    try:
        return bytes.fromhex(s.strip()) if s else b""
    except Exception:
        return b""


def _effective_pow_bits(declared: int) -> int:
    """
    Mirror chain's validatePoWBytesArgon2 threshold logic.

    Uses current/previous difficulty and pow_difficulty_allowance so backend
    precheck never rejects a solution the chain would accept.
    """
    try:
        info = get_difficulty_info()
        current = int(info.get("current_difficulty", 10))
        prev = int(info.get("previous_difficulty", current))
        last_change = int(info.get("last_change_height", 0))
        height = int(info.get("current_height", 0))

        try:
            p = expect_params()
            allowance = int(p.get("pow_difficulty_allowance", 0))
        except Exception:
            allowance = 0

        min_required = current
        if allowance > 0 and last_change > 0 and height - last_change <= allowance:
            if prev < min_required:
                min_required = prev

        eff = int(declared)
        if eff < min_required:
            eff = min_required
        if eff < 1:
            eff = 1
        if eff > 256:
            eff = 256
        return eff
    except Exception:
        # Fallback: preserve previous behaviour if difficulty query fails
        required = get_current_pow_difficulty()
        eff = max(int(declared), int(required))
        if eff < 1:
            eff = 1
        if eff > 256:
            eff = 256
        return eff


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
            # Prefer case-insensitive match via LOWER()
            cur.execute("SELECT level FROM profiles WHERE LOWER(owner) = LOWER(%s) LIMIT 1", (addr_lc,))
            row = cur.fetchone()
            level = int(row[0]) if row and row[0] is not None else 0
            is_sub = level >= 1
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
        return True
    except Exception:
        return False


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
            return jsonify({"error": "node_catching_up"}), 503
        data = request.get_json(force=True) or {}
        log_event(rid, "set_username.data", data=data)
        pub_b64 = str(data.get("pubkey", "").strip())
        sig_b64 = str(data.get("signature", "").strip())
        username = str(data.get("username", "").strip())
        last_block_hash = str(data.get("last_block_hash", "").strip())
        difficulty = int(data.get("pow_difficulty", 0))
        proof = int(data.get("pow", 0))
        if "timestamp" not in data:
            return jsonify({"error": "timestamp required"}), 400
        try:
            timestamp = int(data.get("timestamp"))
        except (TypeError, ValueError):
            return jsonify({"error": "invalid timestamp"}), 400

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
            return jsonify({"error": "username too short"}), 400
        if len(username) > max_u:
            return jsonify({"error": "username too long"}), 400
        if not re.fullmatch(r"[A-Za-z0-9-]+", username):
            return jsonify({"error": "invalid username format"}), 400

        # Free users require PoW; subscribers must NOT use PoW
        if not is_subscriber(user_addr):
            if not (last_block_hash and int(difficulty) > 0 and int(proof) > 0):
                return jsonify({"error": "missing required fields"}), 400
            try:
                base = canon_base_set_username(
                    pub_dec,
                    last_block_hash,
                    int(difficulty),
                    timestamp,
                    user_addr,
                    username,
                )
                digest = argon2_digest(base, last_block_hash, proof)
                if digest is not None:
                    effective_required = _effective_pow_bits(int(difficulty))
                    if count_leading_zero_bits(digest) < effective_required:
                        return jsonify({"error": "insufficient pow (precheck)"}), 400
            except Exception:
                pass
        else:
            if int(difficulty) > 0 or int(proof) > 0:
                return jsonify({"error": "pow not allowed for subscribers"}), 400
        # Verify signature over canonical signed bytes
        try:
            base = canon_base_set_username(
                pub_dec,
                last_block_hash,
                int(difficulty),
                timestamp,
                user_addr,
                username,
            )
            signed = canon_signed_with_pow(base, int(proof))
            if not _verify_signature(pub_dec, sig_dec, signed):
                return jsonify({"error": "invalid signature"}), 400
        except Exception:
            return jsonify({"error": "invalid signature"}), 400

        msg = MsgSetUsername()
        # authority is the validator/node address relaying this transaction, NOT the user's address
        msg.authority = validator_addr
        msg.envelope_pubkey = pub_dec
        msg.envelope_block_hash = _hex_to_bytes(last_block_hash)
        msg.envelope_difficulty = int(difficulty)
        msg.envelope_pow = int(proof)
        msg.envelope_timestamp = timestamp
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
        tx_bytes_est = build_tx_bytes(body_bytes, gas_est)
        gas_used = int(simulate_gas(tx_bytes_est))
        gas_limit = max(gas_est, int(gas_used * GAS_BUFFER_MULTIPLIER))
        tx_bytes = build_tx_bytes(body_bytes, gas_limit)
        tx_hash, code, height, raw_log = broadcast_tx(tx_bytes)
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

        # Record referral if provided and valid (referral system)
        referrer = str(data.get("referrer", "")).strip().lower()
        if referrer and referrer.startswith("mirage1") and len(referrer) >= 39:
            # Don't allow self-referral
            if referrer != user_addr.lower():
                try:
                    now_ts = int(time.time())
                    with connect_db() as conn:
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

        # Check for invite quest completion (referrer has invite_recruit, new user used their code)
        try:
            _process_invite_quest_completion(rid, user_addr.lower())
        except Exception as invite_err:
            log_event(rid, "set_username.invite_quest_error", error=str(invite_err))

        return jsonify({"tx_hash": tx_hash, "code": code, "height": height, "raw_log": raw_log})
    except Exception as e:
        log_event(rid, "set_username.err", error=str(e))
        return jsonify({"error": str(e)}), 500


@core_bp.route("/api/core/follow_moderator", methods=["POST"])
def core_follow_moderator():
    rid = next_request_id()
    log_event(rid, "follow_moderator.begin")
    try:
        if is_node_catching_up():
            return jsonify({"error": "node_catching_up"}), 503
        data = request.get_json(force=True) or {}
        log_event(rid, "follow_moderator.data", data=data)
        pub_b64 = str(data.get("pubkey", "").strip())
        sig_b64 = str(data.get("signature", "").strip())
        moderator = str(data.get("moderator", "").strip())
        last_block_hash = str(data.get("last_block_hash", "").strip())
        difficulty = int(data.get("pow_difficulty", 0))
        proof = int(data.get("pow", 0))
        if "timestamp" not in data:
            return jsonify({"error": "timestamp required"}), 400
        try:
            timestamp = int(data.get("timestamp"))
        except (TypeError, ValueError):
            return jsonify({"error": "invalid timestamp"}), 400

        if not (pub_b64 and sig_b64 and moderator):
            return jsonify({"error": "missing required fields"}), 400
        if not _is_valid_mirage_addr(moderator):
            return jsonify({"error": "invalid moderator address"}), 400

        pub_dec = base64.b64decode(pub_b64)
        sig_dec = base64.b64decode(sig_b64)
        if len(sig_dec) == 65:
            sig_dec = sig_dec[:64]
        if len(pub_dec) != 33 or len(sig_dec) != 64:
            return jsonify({"error": "invalid relay fields"}), 400

        user_addr = derive_address_from_pubkey(pub_dec)
        if not user_addr:
            return jsonify({"error": "invalid pubkey"}), 400

        # Check if moderator is already followed
        try:
            profile = _query_chain_profile_full(user_addr)
            if profile:
                followed_mods = [m.lower() for m in (profile.get("followed_moderators") or [])]
                if moderator.lower() in followed_mods:
                    log_event(rid, "follow_moderator.already_followed", moderator=moderator, user_addr=user_addr)
                    return jsonify({"error": "moderator is already followed"}), 400
        except Exception:
            pass

        validator_addr = require_runtime().validator_payer_addr

        if not is_subscriber(user_addr):
            try:
                base = canon_base_follow_moderator(
                    pub_dec, last_block_hash, int(difficulty), timestamp, user_addr, moderator
                )
                digest = argon2_digest(base, last_block_hash, proof)
                if digest is not None:
                    effective_required = _effective_pow_bits(int(difficulty))
                    if count_leading_zero_bits(digest) < effective_required:
                        return jsonify({"error": "insufficient pow (precheck)"}), 400
            except Exception:
                pass
        else:
            if int(difficulty) > 0 or int(proof) > 0:
                return jsonify({"error": "pow not allowed for subscribers"}), 400

        msg = MsgFollowModerator()
        msg.authority = validator_addr
        msg.envelope_pubkey = pub_dec
        msg.envelope_block_hash = _hex_to_bytes(last_block_hash)
        msg.envelope_difficulty = int(difficulty)
        msg.envelope_pow = int(proof)
        msg.envelope_timestamp = timestamp
        msg.envelope_signature = sig_dec
        msg.target = user_addr
        msg.moderator = moderator

        any_msg = AnyPB()
        any_msg.type_url = "/mirage.core.v1.MsgFollowModerator"
        any_msg.value = msg.SerializeToString()
        body = TxBody(messages=[any_msg], memo="")
        body_bytes = body.SerializeToString()
        gas_est = int(estimate_total_gas_limit(body_bytes, len(moderator)))
        tx_bytes_est = build_tx_bytes(body_bytes, gas_est)
        gas_used = int(simulate_gas(tx_bytes_est))
        gas_limit = max(gas_est, int(gas_used * GAS_BUFFER_MULTIPLIER))
        tx_bytes = build_tx_bytes(body_bytes, gas_limit)
        tx_hash, code, height, raw_log = broadcast_tx(tx_bytes)
        if code != 0:
            extra = {
                "height": height,
                "user_addr": user_addr,
                "moderator": moderator,
                "last_block_hash": last_block_hash,
                "difficulty": int(difficulty),
                "proof": int(proof),
            }
            return _tx_error(rid, "core/follow_moderator", "MsgFollowModerator", code, tx_hash, raw_log, extra)
        return jsonify({"tx_hash": tx_hash, "code": code, "height": height, "raw_log": raw_log})
    except Exception as e:
        log_event(rid, "follow_moderator.err", error=str(e))
        return jsonify({"error": str(e)}), 500


@core_bp.route("/api/core/unfollow_moderator", methods=["POST"])
def core_unfollow_moderator():
    rid = next_request_id()
    log_event(rid, "unfollow_moderator.begin")
    try:
        if is_node_catching_up():
            return jsonify({"error": "node_catching_up"}), 503
        data = request.get_json(force=True) or {}
        pub_b64 = str(data.get("pubkey", "").strip())
        sig_b64 = str(data.get("signature", "").strip())
        moderator = str(data.get("moderator", "").strip())
        last_block_hash = str(data.get("last_block_hash", "").strip())
        difficulty = int(data.get("pow_difficulty", 0))
        proof = int(data.get("pow", 0))
        if "timestamp" not in data:
            return jsonify({"error": "timestamp required"}), 400
        try:
            timestamp = int(data.get("timestamp"))
        except (TypeError, ValueError):
            return jsonify({"error": "invalid timestamp"}), 400

        if not (pub_b64 and sig_b64 and moderator):
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
            required = get_current_pow_difficulty()
            if int(difficulty) < int(required):
                return jsonify({"error": "insufficient pow (precheck)"}), 400
            if not _is_hex64(last_block_hash):
                return jsonify({"error": "invalid last_block_hash"}), 400
            if not is_valid_recent_block_hash(last_block_hash):
                return jsonify({"error": "invalid last_block_hash"}), 400
            try:
                base = canon_base_unfollow_moderator(
                    pub_dec, last_block_hash, int(difficulty), timestamp, user_addr, moderator
                )
                digest = argon2_digest(base, last_block_hash, proof)
                if digest is not None and count_leading_zero_bits(digest) < int(difficulty):
                    return jsonify({"error": "insufficient pow (precheck)"}), 400
            except Exception:
                pass
        else:
            if int(difficulty) > 0 or int(proof) > 0:
                return jsonify({"error": "pow not allowed for subscribers"}), 400

        msg = MsgUnfollowModerator()
        msg.authority = validator_addr
        msg.envelope_pubkey = pub_dec
        msg.envelope_block_hash = _hex_to_bytes(last_block_hash)
        msg.envelope_difficulty = int(difficulty)
        msg.envelope_pow = int(proof)
        msg.envelope_timestamp = timestamp
        msg.envelope_signature = sig_dec
        msg.target = user_addr
        msg.moderator = moderator

        any_msg = AnyPB()
        any_msg.type_url = "/mirage.core.v1.MsgUnfollowModerator"
        any_msg.value = msg.SerializeToString()
        body = TxBody(messages=[any_msg], memo="")
        body_bytes = body.SerializeToString()
        gas_est = int(estimate_total_gas_limit(body_bytes, len(moderator)))
        tx_bytes_est = build_tx_bytes(body_bytes, gas_est)
        gas_used = int(simulate_gas(tx_bytes_est))
        gas_limit = max(gas_est, int(gas_used * GAS_BUFFER_MULTIPLIER))
        tx_bytes = build_tx_bytes(body_bytes, gas_limit)
        tx_hash, code, height, raw_log = broadcast_tx(tx_bytes)
        if code != 0:
            extra = {
                "height": height,
                "user_addr": user_addr,
                "moderator": moderator,
                "last_block_hash": last_block_hash,
                "difficulty": int(difficulty),
                "proof": int(proof),
            }
            return _tx_error(rid, "core/unfollow_moderator", "MsgUnfollowModerator", code, tx_hash, raw_log, extra)
        return jsonify({"tx_hash": tx_hash, "code": code, "height": height, "raw_log": raw_log})
    except Exception as e:
        log_event(rid, "unfollow_moderator.err", error=str(e))
        return jsonify({"error": str(e)}), 500


@core_bp.route("/api/core/block_post", methods=["POST"])
def core_block_post():
    rid = next_request_id()
    log_event(rid, "block_post.begin")
    try:
        if is_node_catching_up():
            return jsonify({"error": "node_catching_up"}), 503
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

        # Check if post is already blocked
        try:
            profile = _query_chain_profile_full(user_addr)
            if profile:
                blocked_posts = [p.lower() for p in (profile.get("blocked_posts") or [])]
                if target in blocked_posts:
                    log_event(rid, "block_post.already_blocked", target=target, user_addr=user_addr)
                    return jsonify({"error": "post is already blocked"}), 400
        except Exception:
            pass

        validator_addr = require_runtime().validator_payer_addr

        if not is_subscriber(user_addr):
            try:
                base = canon_base_block_post(pub_dec, last_block_hash, int(difficulty), timestamp, target)
                digest = argon2_digest(base, last_block_hash, proof)
                if digest is not None:
                    effective_required = _effective_pow_bits(int(difficulty))
                    if count_leading_zero_bits(digest) < effective_required:
                        return jsonify({"error": "insufficient pow (precheck)"}), 400
            except Exception:
                pass
        else:
            if int(difficulty) > 0 or int(proof) > 0:
                return jsonify({"error": "pow not allowed for subscribers"}), 400

        msg = MsgBlockPost()
        msg.authority = validator_addr
        msg.envelope_pubkey = pub_dec
        msg.envelope_block_hash = _hex_to_bytes(last_block_hash)
        msg.envelope_difficulty = int(difficulty)
        msg.envelope_pow = int(proof)
        msg.envelope_timestamp = int(timestamp)
        msg.envelope_signature = sig_dec
        msg.target = target

        any_msg = AnyPB()
        any_msg.type_url = "/mirage.core.v1.MsgBlockPost"
        any_msg.value = msg.SerializeToString()
        body = TxBody(messages=[any_msg], memo="")
        body_bytes = body.SerializeToString()
        gas_est = int(estimate_total_gas_limit(body_bytes, len(target)))
        tx_bytes_est = build_tx_bytes(body_bytes, gas_est)
        gas_used = int(simulate_gas(tx_bytes_est))
        gas_limit = max(gas_est, int(gas_used * GAS_BUFFER_MULTIPLIER))
        tx_bytes = build_tx_bytes(body_bytes, gas_limit)
        tx_hash, code, height, raw_log = broadcast_tx(tx_bytes)
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
        return jsonify({"error": str(e)}), 500


@core_bp.route("/api/core/block_user", methods=["POST"])
def core_block_user():
    rid = next_request_id()
    log_event(rid, "block_user.begin")
    try:
        if is_node_catching_up():
            return jsonify({"error": "node_catching_up"}), 503
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

        # Check if user is already blocked
        try:
            profile = _query_chain_profile_full(user_addr)
            if profile:
                blocked_users = [u.lower() for u in (profile.get("blocked_users") or [])]
                if target in blocked_users:
                    log_event(rid, "block_user.already_blocked", target=target, user_addr=user_addr)
                    return jsonify({"error": "user is already blocked"}), 400
        except Exception:
            pass

        validator_addr = require_runtime().validator_payer_addr

        if not is_subscriber(user_addr):
            try:
                base = canon_base_block_user(pub_dec, last_block_hash, int(difficulty), timestamp, target)
                digest = argon2_digest(base, last_block_hash, proof)
                if digest is not None:
                    effective_required = _effective_pow_bits(int(difficulty))
                    if count_leading_zero_bits(digest) < effective_required:
                        return jsonify({"error": "insufficient pow (precheck)"}), 400
            except Exception:
                pass
        else:
            if int(difficulty) > 0 or int(proof) > 0:
                return jsonify({"error": "pow not allowed for subscribers"}), 400

        msg = MsgBlockUser()
        msg.authority = validator_addr
        msg.envelope_pubkey = pub_dec
        msg.envelope_block_hash = _hex_to_bytes(last_block_hash)
        msg.envelope_difficulty = int(difficulty)
        msg.envelope_pow = int(proof)
        msg.envelope_timestamp = int(timestamp)
        msg.envelope_signature = sig_dec
        msg.target = target

        any_msg = AnyPB()
        any_msg.type_url = "/mirage.core.v1.MsgBlockUser"
        any_msg.value = msg.SerializeToString()
        body = TxBody(messages=[any_msg], memo="")
        body_bytes = body.SerializeToString()
        gas_est = int(estimate_total_gas_limit(body_bytes, len(target)))
        tx_bytes_est = build_tx_bytes(body_bytes, gas_est)
        gas_used = int(simulate_gas(tx_bytes_est))
        gas_limit = max(gas_est, int(gas_used * GAS_BUFFER_MULTIPLIER))
        tx_bytes = build_tx_bytes(body_bytes, gas_limit)
        tx_hash, code, height, raw_log = broadcast_tx(tx_bytes)
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
        return jsonify({"error": str(e)}), 500


@core_bp.route("/api/core/unblock_post", methods=["POST"])
def core_unblock_post():
    rid = next_request_id()
    log_event(rid, "unblock_post.begin")
    try:
        if is_node_catching_up():
            return jsonify({"error": "node_catching_up"}), 503
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
                base = canon_base_unblock_post(pub_dec, last_block_hash, int(difficulty), timestamp, target)
                digest = argon2_digest(base, last_block_hash, proof)
                if digest is not None:
                    effective_required = _effective_pow_bits(int(difficulty))
                    if count_leading_zero_bits(digest) < effective_required:
                        return jsonify({"error": "insufficient pow (precheck)"}), 400
            except Exception:
                pass
        else:
            if int(difficulty) > 0 or int(proof) > 0:
                return jsonify({"error": "pow not allowed for subscribers"}), 400

        msg = MsgUnblockPost()
        msg.authority = validator_addr
        msg.envelope_pubkey = pub_dec
        msg.envelope_block_hash = _hex_to_bytes(last_block_hash)
        msg.envelope_difficulty = int(difficulty)
        msg.envelope_pow = int(proof)
        msg.envelope_timestamp = int(timestamp)
        msg.envelope_signature = sig_dec
        msg.target = target

        any_msg = AnyPB()
        any_msg.type_url = "/mirage.core.v1.MsgUnblockPost"
        any_msg.value = msg.SerializeToString()
        body = TxBody(messages=[any_msg], memo="")
        body_bytes = body.SerializeToString()
        gas_est = int(estimate_total_gas_limit(body_bytes, len(target)))
        tx_bytes_est = build_tx_bytes(body_bytes, gas_est)
        gas_used = int(simulate_gas(tx_bytes_est))
        gas_limit = max(gas_est, int(gas_used * GAS_BUFFER_MULTIPLIER))
        tx_bytes = build_tx_bytes(body_bytes, gas_limit)
        tx_hash, code, height, raw_log = broadcast_tx(tx_bytes)
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
        return jsonify({"error": str(e)}), 500


@core_bp.route("/api/core/unblock_user", methods=["POST"])
def core_unblock_user():
    rid = next_request_id()
    log_event(rid, "unblock_user.begin")
    try:
        if is_node_catching_up():
            return jsonify({"error": "node_catching_up"}), 503
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
                base = canon_base_unblock_user(pub_dec, last_block_hash, int(difficulty), timestamp, target)
                digest = argon2_digest(base, last_block_hash, proof)
                if digest is not None:
                    effective_required = _effective_pow_bits(int(difficulty))
                    if count_leading_zero_bits(digest) < effective_required:
                        return jsonify({"error": "insufficient pow (precheck)"}), 400
            except Exception:
                pass
        else:
            if int(difficulty) > 0 or int(proof) > 0:
                return jsonify({"error": "pow not allowed for subscribers"}), 400

        msg = MsgUnblockUser()
        msg.authority = validator_addr
        msg.envelope_pubkey = pub_dec
        msg.envelope_block_hash = _hex_to_bytes(last_block_hash)
        msg.envelope_difficulty = int(difficulty)
        msg.envelope_pow = int(proof)
        msg.envelope_timestamp = int(timestamp)
        msg.envelope_signature = sig_dec
        msg.target = target

        any_msg = AnyPB()
        any_msg.type_url = "/mirage.core.v1.MsgUnblockUser"
        any_msg.value = msg.SerializeToString()
        body = TxBody(messages=[any_msg], memo="")
        body_bytes = body.SerializeToString()
        gas_est = int(estimate_total_gas_limit(body_bytes, len(target)))
        tx_bytes_est = build_tx_bytes(body_bytes, gas_est)
        gas_used = int(simulate_gas(tx_bytes_est))
        gas_limit = max(gas_est, int(gas_used * GAS_BUFFER_MULTIPLIER))
        tx_bytes = build_tx_bytes(body_bytes, gas_limit)
        tx_hash, code, height, raw_log = broadcast_tx(tx_bytes)
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
        return jsonify({"error": str(e)}), 500


@core_bp.route("/api/core/follow_user", methods=["POST"])
def core_follow_user():
    rid = next_request_id()
    log_event(rid, "follow_user.begin")
    try:
        if is_node_catching_up():
            return jsonify({"error": "node_catching_up"}), 503
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

        # Check if user is already followed
        try:
            profile = _query_chain_profile_full(user_addr)
            if profile:
                followed_users = [u.lower() for u in (profile.get("followed_users") or [])]
                if user in followed_users:
                    log_event(rid, "follow_user.already_followed", user=user, user_addr=user_addr)
                    return jsonify({"error": "user is already followed"}), 400
        except Exception:
            pass

        validator_addr = require_runtime().validator_payer_addr

        if not is_subscriber(user_addr):
            try:
                base = canon_base_follow_user(pub_dec, last_block_hash, int(difficulty), timestamp, target, user)
                digest = argon2_digest(base, last_block_hash, proof)
                if digest is not None:
                    effective_required = _effective_pow_bits(int(difficulty))
                    if count_leading_zero_bits(digest) < effective_required:
                        return jsonify({"error": "insufficient pow (precheck)"}), 400
            except Exception:
                pass

        msg = MsgFollowUser()
        msg.authority = validator_addr
        msg.envelope_pubkey = pub_dec
        msg.envelope_block_hash = _hex_to_bytes(last_block_hash)
        msg.envelope_difficulty = int(difficulty)
        msg.envelope_pow = int(proof)
        msg.envelope_timestamp = timestamp
        msg.envelope_signature = sig_dec
        msg.target = target
        msg.user = user

        any_msg = AnyPB()
        any_msg.type_url = "/mirage.core.v1.MsgFollowUser"
        any_msg.value = msg.SerializeToString()
        body = TxBody(messages=[any_msg], memo="")
        body_bytes = body.SerializeToString()
        gas_est = int(estimate_total_gas_limit(body_bytes, len(target) + len(user)))
        tx_bytes_est = build_tx_bytes(body_bytes, gas_est)
        gas_used = int(simulate_gas(tx_bytes_est))
        gas_limit = max(gas_est, int(gas_used * GAS_BUFFER_MULTIPLIER))
        tx_bytes = build_tx_bytes(body_bytes, gas_limit)
        tx_hash, code, height, raw_log = broadcast_tx(tx_bytes)
        if code != 0:
            extra = {
                "height": height,
                "user_addr": user_addr,
                "last_block_hash": last_block_hash,
                "difficulty": int(difficulty),
                "proof": int(proof),
            }
            return _tx_error(rid, "core/follow_user", "MsgFollowUser", code, tx_hash, raw_log, extra)
        return jsonify({"tx_hash": tx_hash, "code": code, "height": height, "raw_log": raw_log})
    except Exception as e:
        log_event(rid, "follow_user.err", error=str(e))
        return jsonify({"error": str(e)}), 500


@core_bp.route("/api/core/unfollow_user", methods=["POST"])
def core_unfollow_user():
    rid = next_request_id()
    log_event(rid, "unfollow_user.begin")
    try:
        if is_node_catching_up():
            return jsonify({"error": "node_catching_up"}), 503
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
                base = canon_base_unfollow_user(pub_dec, last_block_hash, int(difficulty), timestamp, target, user)
                digest = argon2_digest(base, last_block_hash, proof)
                if digest is not None:
                    effective_required = _effective_pow_bits(int(difficulty))
                    if count_leading_zero_bits(digest) < effective_required:
                        return jsonify({"error": "insufficient pow (precheck)"}), 400
            except Exception:
                pass

        msg = MsgUnfollowUser()
        msg.authority = validator_addr
        msg.envelope_pubkey = pub_dec
        msg.envelope_block_hash = _hex_to_bytes(last_block_hash)
        msg.envelope_difficulty = int(difficulty)
        msg.envelope_pow = int(proof)
        msg.envelope_timestamp = timestamp
        msg.envelope_signature = sig_dec
        msg.target = target
        msg.user = user

        any_msg = AnyPB()
        any_msg.type_url = "/mirage.core.v1.MsgUnfollowUser"
        any_msg.value = msg.SerializeToString()
        body = TxBody(messages=[any_msg], memo="")
        body_bytes = body.SerializeToString()
        gas_est = int(estimate_total_gas_limit(body_bytes, len(target) + len(user)))
        tx_bytes_est = build_tx_bytes(body_bytes, gas_est)
        gas_used = int(simulate_gas(tx_bytes_est))
        gas_limit = max(gas_est, int(gas_used * GAS_BUFFER_MULTIPLIER))
        tx_bytes = build_tx_bytes(body_bytes, gas_limit)
        tx_hash, code, height, raw_log = broadcast_tx(tx_bytes)
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
        return jsonify({"error": str(e)}), 500


@core_bp.route("/api/core/follow_topic", methods=["POST"])
def core_follow_topic():
    rid = next_request_id()
    log_event(rid, "follow_topic.begin")
    try:
        if is_node_catching_up():
            return jsonify({"error": "node_catching_up"}), 503
        data = request.get_json(force=True) or {}
        pub_b64 = str(data.get("pubkey", "").strip())
        sig_b64 = str(data.get("signature", "").strip())
        target = str(data.get("target", "").strip()).lower()
        topic = str(data.get("topic", "").strip()).lower()
        last_block_hash = str(data.get("last_block_hash", "").strip())
        difficulty = int(data.get("pow_difficulty", 0))
        proof = int(data.get("pow", 0))
        timestamp = int(data.get("timestamp", 0)) or int(time.time() * 1000)

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

        # Check if topic is already followed
        try:
            profile = _query_chain_profile_full(user_addr)
            if profile:
                followed_topics = [t.lower() for t in (profile.get("followed_topics") or [])]
                if topic in followed_topics:
                    log_event(rid, "follow_topic.already_followed", topic=topic, user_addr=user_addr)
                    return jsonify({"error": "topic is already followed"}), 400
        except Exception:
            pass

        validator_addr = require_runtime().validator_payer_addr

        if not is_subscriber(user_addr):
            try:
                base = canon_base_follow_topic(pub_dec, last_block_hash, int(difficulty), timestamp, target, topic)
                digest = argon2_digest(base, last_block_hash, proof)
                if digest is not None:
                    effective_required = _effective_pow_bits(int(difficulty))
                    if count_leading_zero_bits(digest) < effective_required:
                        return jsonify({"error": "insufficient pow (precheck)"}), 400
            except Exception:
                pass

        msg = MsgFollowTopic()
        msg.authority = validator_addr
        msg.envelope_pubkey = pub_dec
        msg.envelope_block_hash = _hex_to_bytes(last_block_hash)
        msg.envelope_difficulty = int(difficulty)
        msg.envelope_pow = int(proof)
        msg.envelope_timestamp = timestamp
        msg.envelope_signature = sig_dec
        msg.target = target
        msg.topic = topic

        any_msg = AnyPB()
        any_msg.type_url = "/mirage.core.v1.MsgFollowTopic"
        any_msg.value = msg.SerializeToString()
        body = TxBody(messages=[any_msg], memo="")
        body_bytes = body.SerializeToString()
        gas_est = int(estimate_total_gas_limit(body_bytes, len(target) + len(topic)))
        tx_bytes_est = build_tx_bytes(body_bytes, gas_est)
        gas_used = int(simulate_gas(tx_bytes_est))
        gas_limit = max(gas_est, int(gas_used * GAS_BUFFER_MULTIPLIER))
        tx_bytes = build_tx_bytes(body_bytes, gas_limit)
        tx_hash, code, height, raw_log = broadcast_tx(tx_bytes)
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
        return jsonify({"error": str(e)}), 500


@core_bp.route("/api/core/unfollow_topic", methods=["POST"])
def core_unfollow_topic():
    rid = next_request_id()
    log_event(rid, "unfollow_topic.begin")
    try:
        if is_node_catching_up():
            return jsonify({"error": "node_catching_up"}), 503
        data = request.get_json(force=True) or {}
        pub_b64 = str(data.get("pubkey", "").strip())
        sig_b64 = str(data.get("signature", "").strip())
        target = str(data.get("target", "").strip()).lower()
        topic = str(data.get("topic", "").strip()).lower()
        last_block_hash = str(data.get("last_block_hash", "").strip())
        difficulty = int(data.get("pow_difficulty", 0))
        proof = int(data.get("pow", 0))
        timestamp = int(data.get("timestamp", 0)) or int(time.time() * 1000)

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
                base = canon_base_unfollow_topic(pub_dec, last_block_hash, int(difficulty), timestamp, target, topic)
                digest = argon2_digest(base, last_block_hash, proof)
                if digest is not None:
                    effective_required = _effective_pow_bits(int(difficulty))
                    if count_leading_zero_bits(digest) < effective_required:
                        return jsonify({"error": "insufficient pow (precheck)"}), 400
            except Exception:
                pass

        msg = MsgUnfollowTopic()
        msg.authority = validator_addr
        msg.envelope_pubkey = pub_dec
        msg.envelope_block_hash = _hex_to_bytes(last_block_hash)
        msg.envelope_difficulty = int(difficulty)
        msg.envelope_pow = int(proof)
        msg.envelope_timestamp = timestamp
        msg.envelope_signature = sig_dec
        msg.target = target
        msg.topic = topic

        any_msg = AnyPB()
        any_msg.type_url = "/mirage.core.v1.MsgUnfollowTopic"
        any_msg.value = msg.SerializeToString()
        body = TxBody(messages=[any_msg], memo="")
        body_bytes = body.SerializeToString()
        gas_est = int(estimate_total_gas_limit(body_bytes, len(target) + len(topic)))
        tx_bytes_est = build_tx_bytes(body_bytes, gas_est)
        gas_used = int(simulate_gas(tx_bytes_est))
        gas_limit = max(gas_est, int(gas_used * GAS_BUFFER_MULTIPLIER))
        tx_bytes = build_tx_bytes(body_bytes, gas_limit)
        tx_hash, code, height, raw_log = broadcast_tx(tx_bytes)
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
        return jsonify({"error": str(e)}), 500


@core_bp.route("/api/core/delete_post", methods=["POST"])
def core_delete_post():
    rid = next_request_id()
    log_event(rid, "delete_post.begin")
    try:
        if is_node_catching_up():
            return jsonify({"error": "node_catching_up"}), 503
        # Ensure params cache is initialized (avoids 'params cache uninitialized' until profile is visited)
        try:
            load_params(force=False)
        except Exception:
            pass
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
            required = get_current_pow_difficulty()
            if int(difficulty) < int(required):
                return jsonify({"error": "insufficient pow (precheck)"}), 400
            if not _is_hex64(last_block_hash):
                return jsonify({"error": "invalid last_block_hash"}), 400
            if not is_valid_recent_block_hash(last_block_hash):
                return jsonify({"error": "invalid last_block_hash"}), 400
            try:
                base = canon_base_delete(pub_dec, last_block_hash, int(difficulty), timestamp, target)
                digest = argon2_digest(base, last_block_hash, proof)
                if digest is not None and count_leading_zero_bits(digest) < int(difficulty):
                    return jsonify({"error": "insufficient pow (precheck)"}), 400
            except Exception:
                pass

        # Ownership/admin precheck:
        # - Owner can always delete their own post
        # - Admins (level >= 100) may delete any post
        owner = _get_post_owner(target)
        if owner is None:
            return jsonify({"error": "target not found"}), 404
        user_level = get_user_level(user_addr)
        if owner != user_addr.strip().lower() and user_level < 100:
            return jsonify({"error": "forbidden"}), 403

        # No fee precheck

        msg = MsgDelete()
        # AUTHORITY IS ALWAYS THE VALIDATOR NODE (or gov), NEVER the user
        msg.authority = validator_addr
        msg.envelope_pubkey = pub_dec
        msg.envelope_block_hash = _hex_to_bytes(last_block_hash)
        msg.envelope_difficulty = int(difficulty)
        msg.envelope_pow = int(proof)
        msg.envelope_timestamp = int(timestamp)
        msg.envelope_signature = sig_dec
        msg.target = target

        any_msg = AnyPB()
        any_msg.type_url = "/mirage.core.v1.MsgDelete"
        any_msg.value = msg.SerializeToString()
        body = TxBody(messages=[any_msg], memo="")
        body_bytes = body.SerializeToString()
        gas_est = int(estimate_total_gas_limit(body_bytes, len(target)))
        tx_bytes_est = build_tx_bytes(body_bytes, gas_est)
        gas_used = int(simulate_gas(tx_bytes_est))
        gas_limit = max(gas_est, int(gas_used * GAS_BUFFER_MULTIPLIER))
        tx_bytes = build_tx_bytes(body_bytes, gas_limit)
        tx_hash, code, height, raw_log = broadcast_tx(tx_bytes)
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
            with connect_db(timeout=10.0, busy_timeout_ms=15000) as conn:
                cur = conn.cursor()
                cur.execute("DELETE FROM reports WHERE LOWER(target) = LOWER(%s)", (target,))
                conn.commit()
                deleted_count = cur.rowcount
                log_event(rid, "delete_post.reports_removed", target=target[:16], count=deleted_count)
        except Exception as e:
            log_event(rid, "delete_post.reports_cleanup_failed", error=str(e))

        return jsonify({"tx_hash": tx_hash, "code": code, "height": height, "raw_log": raw_log})
    except Exception as e:
        log_event(rid, "delete_post.err", error=str(e))
        return jsonify({"error": str(e)}), 500


@core_bp.route("/api/core/report", methods=["POST"])
def core_report():
    rid = next_request_id()
    log_event(rid, "report.begin")
    try:
        if is_node_catching_up():
            return jsonify({"error": "node_catching_up"}), 503
        import time

        data = request.get_json(force=True) or {}
        log_event(rid, "report.data", data=data)
        pub_b64 = str(data.get("pubkey", "").strip())
        sig_b64 = str(data.get("signature", "").strip())
        last_block_hash = str(data.get("last_block_hash", "").strip())
        difficulty = int(data.get("pow_difficulty", 0))
        proof = int(data.get("pow", 0))
        target = str(data.get("target", "").strip()).lower()
        reason_raw = str(data.get("reason", "").strip())

        if "timestamp" not in data:
            return jsonify({"error": "timestamp required"}), 400
        try:
            timestamp = int(data.get("timestamp"))
        except (TypeError, ValueError):
            return jsonify({"error": "invalid timestamp"}), 400

        reason = "".join(c for c in reason_raw if ord(c) >= 32 and ord(c) < 127 or ord(c) >= 160)
        reason = reason.strip()

        if not (pub_b64 and sig_b64 and last_block_hash and difficulty > 0 and proof and target and reason):
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
            base = canon_base_report(pub_dec, last_block_hash, int(difficulty), timestamp, target, reason)
            digest = argon2_digest(base, last_block_hash, proof)
            if digest is not None:
                effective_required = _effective_pow_bits(int(difficulty))
                if count_leading_zero_bits(digest) < effective_required:
                    return jsonify({"error": "insufficient pow (precheck)"}), 400
        except Exception:
            pass

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

            base = canon_base_report(pub_dec, last_block_hash, int(difficulty), timestamp, target, reason)
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

        conn = connect_db(timeout=10.0, busy_timeout_ms=15000)
        try:
            cur = conn.cursor()
            ts = int(time.time())
            cur.execute(
                "INSERT INTO reports(owner, target, reason, created_at) VALUES(%s, %s, %s, %s) RETURNING id",
                (owner_addr.lower(), target, reason, ts),
            )
            row = cur.fetchone()
            report_id = row[0] if row else 0
            conn.commit()
        finally:
            try:
                conn.close()
            except Exception:
                pass

        return jsonify({"success": True, "id": int(report_id)})
    except Exception as e:
        log_event(rid, "report.err", error=str(e))
        return jsonify({"error": str(e)}), 500


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

        conn = connect_db(timeout=10.0, busy_timeout_ms=15000)
        try:
            cur = conn.cursor()
            cur.execute("SELECT level FROM profiles WHERE LOWER(owner)=LOWER(%s) LIMIT 1", (address,))
            row = cur.fetchone()
            level = int(row[0]) if row and row[0] is not None else 0
            if level < 100:
                return jsonify({"error": "forbidden"}), 403
            cur.execute("DELETE FROM reports WHERE id = %s", (int(report_id),))
            conn.commit()
        finally:
            try:
                conn.close()
            except Exception:
                pass
        return jsonify({"success": True})
    except Exception as e:
        log_event(rid, "resolve_report.err", error=str(e))
        return jsonify({"error": str(e)}), 500


@core_bp.route("/api/core/edit", methods=["POST"])
def core_edit():
    rid = next_request_id()
    log_event(rid, "edit.begin")
    try:
        if is_node_catching_up():
            return jsonify({"error": "node_catching_up"}), 503
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
        target = str(data.get("target", "")).strip()
        topic = str(data.get("topic", "")).strip()
        title = str(data.get("title", "")).strip()
        content = str(data.get("content", "")).strip()
        override = str(data.get("override", "")).strip().lower()
        tag = str(data.get("tag", "")).strip()
        # no client-provided fees

        if tag not in ALLOWED_TAGS:
            return jsonify({"error": f"invalid tag: {tag}"}), 400
        if len(tag) > 50:
            return jsonify({"error": "tag too long"}), 400

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
                from params import expect_params as _expect_params

                max_topic = int(_expect_params().get("max_topic_size", 50))
            except Exception:
                max_topic = 50
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
        try:
            conn = connect_db(timeout=10.0, busy_timeout_ms=15000)
            cur = conn.cursor()
            cur.execute(
                "SELECT owner, COALESCE(target, '') FROM posts WHERE LOWER(txhash)=LOWER(%s) LIMIT 1", (override,)
            )
            row = cur.fetchone()
            conn.close()
            if not row or not row[0]:
                return jsonify({"error": "override not found"}), 404
            owner_of_override = (row[0] or "").lower()
            if owner_of_override != user_addr.lower():
                return jsonify({"error": "forbidden"}), 403
        except Exception:
            # If DB check fails, let chain proceed; indexer will enforce
            pass

        validator_addr = require_runtime().validator_payer_addr

        # Free users require PoW; subscribers must NOT use PoW
        if not is_subscriber(user_addr):
            if not (last_block_hash and int(difficulty) > 0 and int(proof) > 0):
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
                )
                digest = argon2_digest(base, last_block_hash, proof)
                if digest is not None:
                    effective_required = _effective_pow_bits(int(difficulty))
                    if count_leading_zero_bits(digest) < effective_required:
                        return jsonify({"error": "insufficient pow (precheck)"}), 400
            except Exception:
                pass
        else:
            if int(difficulty) > 0 or int(proof) > 0:
                return jsonify({"error": "pow not allowed for subscribers"}), 400
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
        msg.envelope_signature = sig_dec
        msg.target = target
        log_event(rid, "edit.debug", is_comment=is_comment, topic=topic, target=target)
        msg.topic = topic_for_canon
        msg.title = title
        msg.content = content
        msg.tag = tag
        msg.override = override

        any_msg = AnyPB()
        any_msg.type_url = "/mirage.core.v1.MsgEdit"
        any_msg.value = msg.SerializeToString()
        body = TxBody(messages=[any_msg], memo="")
        body_bytes = body.SerializeToString()
        content_len = len(target) + len(topic) + len(title) + len(content) + len(tag)
        gas_est = int(estimate_total_gas_limit(body_bytes, content_len))
        tx_bytes_est = build_tx_bytes(body_bytes, gas_est)
        gas_used = int(simulate_gas(tx_bytes_est))
        gas_limit = max(gas_est, int(gas_used * GAS_BUFFER_MULTIPLIER))
        tx_bytes = build_tx_bytes(body_bytes, gas_limit)
        tx_hash, code, height, raw_log = broadcast_tx(tx_bytes)
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
                "last_block_hash": last_block_hash,
                "difficulty": int(difficulty),
                "proof": int(proof),
            }
            return _tx_error(rid, "core/edit", "MsgEdit", code, tx_hash, raw_log, extra)
        return jsonify({"tx_hash": tx_hash, "code": code, "height": height, "raw_log": raw_log})
    except Exception as e:
        log_event(rid, "edit.err", error=str(e))
        return jsonify({"error": str(e)}), 500


ALLOWED_TAGS = {"", "sensitive", "porn", "gore", "violence", "death"}


@core_bp.route("/api/core/post", methods=["POST"])
def core_post():
    rid = next_request_id()
    log_event(rid, "post.begin")
    try:
        if is_node_catching_up():
            return jsonify({"error": "node_catching_up"}), 503
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
        target = str(data.get("target", ""))
        topic = str(data.get("topic", "")).strip()
        title = str(data.get("title", ""))
        content = str(data.get("content", ""))
        tag = str(data.get("tag", "")).strip()
        # Validate tag
        if tag not in ALLOWED_TAGS:
            return jsonify({"error": f"invalid tag: {tag}"}), 400
        if len(tag) > 50:
            return jsonify({"error": "tag too long"}), 400

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
                from params import expect_params as _expect_params

                p = _expect_params()
                max_topic = int(p.get("max_topic_size", 50))
                min_topic = int(p.get("min_topic_size", 3))
            except Exception:
                max_topic = 50
                min_topic = 3
            if len(topic) < min_topic:
                return jsonify({"error": "topic too short"}), 400
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

        validator_addr = require_runtime().validator_payer_addr

        # Enforce tier limits (title/content) based on user's subscription level
        try:
            p = expect_params()
            tiers = p.get("tiers") or []
            level = get_user_level(user_addr)
            # Admins (level >= 100) are allowed to post without a subscription.
            # Map admins to the highest defined tier for length limits.
            if level >= 100:
                idx = len(tiers) - 1
            else:
                if level < 0 or level >= len(tiers):
                    return jsonify({"error": "invalid user level"}), 400
                idx = level
            tier_cfg = tiers[idx] or {}
            max_title = int(tier_cfg.get("max_title_length", 0))
            max_content = int(tier_cfg.get("max_content_length", 0))
        except Exception:
            return jsonify({"error": "backend not initialized"}), 503

        # Comments: only content limit applies; Root posts: both title and content
        if is_comment:
            if len(content) > max_content:
                return (
                    jsonify({"error": f"content exceeds limit: {len(content)} > {max_content} (tier level={level})"}),
                    400,
                )
        else:
            if len(title) > max_title:
                return (
                    jsonify({"error": f"title exceeds limit: {len(title)} > {max_title} (tier level={level})"}),
                    400,
                )
            if len(content) > max_content:
                return (
                    jsonify({"error": f"content exceeds limit: {len(content)} > {max_content} (tier level={level})"}),
                    400,
                )

        # Free users require PoW; subscribers must NOT use PoW
        if not is_subscriber(user_addr):
            if not (int(difficulty) > 0 and proof):
                return jsonify({"error": "missing required fields"}), 400
            required = get_current_pow_difficulty()
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
                )
                digest = argon2_digest(base, last_block_hash, proof)
                if digest is not None:
                    if count_leading_zero_bits(digest) < int(difficulty):
                        return jsonify({"error": "insufficient pow (precheck)"}), 400
            except Exception:
                pass
        else:
            if int(difficulty) > 0 or int(proof) > 0:
                return jsonify({"error": "pow not allowed for subscribers"}), 400

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
        msg.envelope_signature = sig_dec
        msg.target = target
        msg.topic = topic
        msg.title = title
        msg.content = content
        msg.tag = tag

        any_msg = AnyPB()
        any_msg.type_url = "/mirage.core.v1.MsgPost"
        any_msg.value = msg.SerializeToString()
        body = TxBody(messages=[any_msg], memo="")
        body_bytes = body.SerializeToString()
        content_len = len(target) + len(topic) + len(title) + len(content)
        gas_est = int(estimate_total_gas_limit(body_bytes, content_len))
        tx_bytes_est = build_tx_bytes(body_bytes, gas_est)
        gas_used = int(simulate_gas(tx_bytes_est))
        gas_limit = max(gas_est, int(gas_used * GAS_BUFFER_MULTIPLIER))
        tx_bytes = build_tx_bytes(body_bytes, gas_limit)
        tx_hash, code, height, raw_log = broadcast_tx(tx_bytes)
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
        return jsonify({"tx_hash": tx_hash, "code": code, "height": height, "raw_log": raw_log})
    except Exception as e:
        log_event(rid, "post.err", error=str(e))
        return jsonify({"error": str(e)}), 500


@core_bp.route("/api/core/vote", methods=["POST"])
def core_vote():
    rid = next_request_id()
    log_event(rid, "vote.begin")
    try:
        if is_node_catching_up():
            return jsonify({"error": "node_catching_up"}), 503
        data = request.get_json(force=True) or {}
        pub_b64 = str(data.get("pubkey", "")).strip()
        sig_b64 = str(data.get("signature", "")).strip()
        last_block_hash = str(data.get("last_block_hash", "")).strip()
        difficulty = int(data.get("pow_difficulty", 0))
        proof = int(data.get("pow", 0))
        target = str(data.get("target", ""))
        direction = int(data.get("direction", 0))
        if "timestamp" not in data:
            return jsonify({"error": "timestamp required"}), 400
        try:
            timestamp = int(data.get("timestamp"))
        except (TypeError, ValueError):
            return jsonify({"error": "invalid timestamp"}), 400
        # no client-provided fees
        # Minimal fields; last_block_hash/difficulty/proof only needed for PoW path
        if not (pub_b64 and sig_b64 and target):
            log_event(rid, "vote.missing_fields", has_pubkey=bool(pub_b64), has_signature=bool(sig_b64), has_target=bool(target))
            return jsonify({"error": "missing required fields", "details": f"pubkey={bool(pub_b64)}, signature={bool(sig_b64)}, target={bool(target)}"}), 400
        if not _is_hex64(target.strip()):
            return jsonify({"error": "invalid target"}), 400

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

        # Free users require PoW; subscribers must NOT use PoW
        user_is_sub = is_subscriber(user_addr)
        log_event(rid, "vote.subscriber_check", user_addr=user_addr, is_subscriber=user_is_sub, pow_difficulty=difficulty)
        if not user_is_sub:
            if not (int(difficulty) > 0 and proof):
                log_event(rid, "vote.pow_required", user_addr=user_addr, difficulty=difficulty, proof=proof)
                return jsonify({"error": "pow_required", "details": "Non-subscriber must provide valid PoW. Your subscription may have expired."}), 400
            if not _is_hex64(last_block_hash):
                return jsonify({"error": "invalid last_block_hash"}), 400
            if not is_valid_recent_block_hash(last_block_hash):
                return jsonify({"error": "invalid last_block_hash"}), 400
            # PoW precheck: mirror chain's validatePoWBytesArgon2 threshold
            try:
                base = canon_base_vote(pub_dec, last_block_hash, int(difficulty), timestamp, target, int(direction))
                digest = argon2_digest(base, last_block_hash, proof)
                if digest is not None:
                    effective_required = _effective_pow_bits(int(difficulty))
                    if count_leading_zero_bits(digest) < effective_required:
                        return jsonify({"error": "insufficient pow (precheck)"}), 400
            except Exception:
                # If PoW precheck fails unexpectedly, let chain ante decide
                pass

            # Verify signature for PoW users (chain also verifies via ante handler)
            try:
                base = canon_base_vote(
                    pub_dec,
                    last_block_hash,
                    int(difficulty),
                    timestamp,
                    target,
                    int(direction),
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
            if int(difficulty) > 0 or int(proof) > 0:
                return jsonify({"error": "pow not allowed for subscribers"}), 400
            # Subscribers: skip backend signature verification - chain verifies via ante handler
        msg = MsgVote()
        # authority is the validator/node address relaying this transaction, NOT the user's address
        msg.authority = validator_addr
        msg.envelope_pubkey = pub_dec
        msg.envelope_block_hash = _hex_to_bytes(last_block_hash)
        msg.envelope_difficulty = int(difficulty)
        msg.envelope_pow = int(proof)
        msg.envelope_timestamp = timestamp
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
        tx_bytes_est = build_tx_bytes(body_bytes, gas_est)
        gas_used = int(simulate_gas(tx_bytes_est))
        gas_limit = max(gas_est, int(gas_used * GAS_BUFFER_MULTIPLIER))
        tx_bytes = build_tx_bytes(body_bytes, gas_limit)
        tx_hash, code, height, raw_log = broadcast_tx(tx_bytes)
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
        return jsonify({"tx_hash": tx_hash, "code": code, "height": height, "raw_log": raw_log})
    except Exception as e:
        log_event(rid, "vote.err", error=str(e))
        return jsonify({"error": str(e)}), 500


@core_bp.route("/api/core/send_tokens", methods=["POST"])
def core_send_tokens():
    rid = next_request_id()
    log_event(rid, "send_tokens.begin")
    try:
        if is_node_catching_up():
            return jsonify({"error": "node_catching_up"}), 503
        # Ensure params cache is initialized for fee checks
        try:
            load_params(force=False)
        except Exception:
            pass
        data = request.get_json(force=True) or {}
        log_event(rid, "send_tokens.data", data=data)

        pub_b64 = str(data.get("pubkey", "")).strip()
        sig_b64 = str(data.get("signature", "")).strip()
        last_block_hash = str(data.get("last_block_hash", "")).strip()
        difficulty = int(data.get("pow_difficulty", 0))
        proof = int(data.get("pow", 0))
        target = str(data.get("target", "")).strip().lower()
        amount = int(data.get("amount", 0))
        if "timestamp" not in data:
            return jsonify({"error": "timestamp required"}), 400
        try:
            timestamp = int(data.get("timestamp"))
        except (TypeError, ValueError):
            return jsonify({"error": "invalid timestamp"}), 400
        # no client-provided fees

        log_event(rid, "send_tokens.parsed", target=target, amount=amount)

        if not (pub_b64 and sig_b64 and target and amount > 0):
            log_event(rid, "send_tokens.missing_fields")
            return jsonify({"error": "missing required fields"}), 400

        # Validate target is a mirage1 address
        if not target.startswith("mirage1"):
            return jsonify({"error": "target must be a valid mirage1 address"}), 400

        pub_dec = base64.b64decode(pub_b64)
        sig_dec = base64.b64decode(sig_b64)
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
        except Exception:
            have = 0
        if int(amount) > have:
            return jsonify({"error": f"insufficient balance: have {have}, need {int(amount)}"}), 400

        # Free users require PoW; subscribers must NOT use PoW
        if not is_subscriber(user_addr):
            if not (last_block_hash and int(difficulty) > 0 and int(proof) > 0):
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
                )
                digest = argon2_digest(base, last_block_hash, proof)
                if digest is not None:
                    effective_required = _effective_pow_bits(int(difficulty))
                    if count_leading_zero_bits(digest) < effective_required:
                        return jsonify({"error": "insufficient pow (precheck)"}), 400
            except Exception:
                pass
        else:
            if int(difficulty) > 0 or int(proof) > 0:
                return jsonify({"error": "pow not allowed for subscribers"}), 400

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
        tx_bytes_est = build_tx_bytes(body_bytes, gas_est)
        gas_used = int(simulate_gas(tx_bytes_est))
        gas_limit = max(gas_est, int(gas_used * GAS_BUFFER_MULTIPLIER))
        tx_bytes = build_tx_bytes(body_bytes, gas_limit)
        tx_hash, code, height, raw_log = broadcast_tx(tx_bytes)

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
        return jsonify({"tx_hash": tx_hash, "code": code, "height": height, "raw_log": raw_log})
    except Exception as e:
        log_event(rid, "send_tokens.err", error=str(e))
        return jsonify({"error": str(e)}), 500


@core_bp.route("/api/core/upgrade_level", methods=["POST"])
def core_upgrade_level():
    """Upgrade user subscription level (tier).

    Required fields:
    - pubkey: Base64 encoded compressed public key
    - signature: Base64 encoded signature
    - last_block_hash: Recent block hash for replay protection
    - level: Target paid subscription level (1-3)

    Note:
    - PoW is NOT allowed for MsgUpgradeLevel. Users must pay with tokens.
    - To change auto-renewal without changing tier, use /api/core/set_auto_renewal instead.
    """
    rid = next_request_id()
    log_event(rid, "upgrade_level.begin")
    try:
        if is_node_catching_up():
            return jsonify({"error": "node_catching_up"}), 503
        data = request.get_json(force=True) or {}
        log_event(rid, "upgrade_level.data", data=data)
        pub_b64 = str(data.get("pubkey", "")).strip()
        sig_b64 = str(data.get("signature", "")).strip()
        last_block_hash = str(data.get("last_block_hash", "")).strip()
        # PoW is not used for upgrade_level; difficulty/pow must be zero.
        # Client MUST provide timestamp for replay protection; no backend fallback.
        if "timestamp" not in data:
            return jsonify({"error": "timestamp required"}), 400
        try:
            timestamp = int(data.get("timestamp"))
        except (TypeError, ValueError):
            return jsonify({"error": "invalid timestamp"}), 400
        level = int(data.get("level", 0))
        # no client-provided fees

        # Minimal fields; last_block_hash is optional (no PoW for upgrade)
        if not (pub_b64 and sig_b64):
            return jsonify({"error": "missing required fields"}), 400

        if level < 1 or level > 3:
            return jsonify({"error": "invalid level (must be 1-3; use set_auto_renewal to change auto-renewal)"}), 400

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

        # PoW is NOT allowed for upgrade_level - must pay with tokens. No upfront fee field required.

        # Backend precheck: ensure user has enough balance for the target tier's period fee
        try:
            p = load_params(force=False)
        except Exception:
            p = {}
        period_fee = 0
        try:
            tiers = p.get("tiers") or []
            if isinstance(tiers, list) and level > 0 and level < len(tiers):
                tf = tiers[level] or {}
                period_fee = int(tf.get("period_fee", 0) or 0)
        except Exception:
            period_fee = 0
        if level > 0 and period_fee > 0:
            bal = get_balance(user_addr)
            try:
                have = int(bal)
            except Exception:
                have = 0
            if have < period_fee:
                return jsonify({"error": "insufficient balance", "balance": have, "needed": int(period_fee)}), 400

        # Verify relay signature matches shared canonical bytes (with timestamp)
        try:
            base = canon_base_upgrade_level(
                pub_dec,
                last_block_hash,
                0,  # difficulty always 0 for upgrade_level
                timestamp,
                level,
            )
            signed = canon_signed_with_pow(base, 0)
            if not _verify_signature(pub_dec, sig_dec, signed):
                return jsonify({"error": "invalid signature"}), 400
        except Exception:
            return jsonify({"error": "invalid signature"}), 400

        msg = MsgUpgradeLevel()
        msg.authority = validator_addr
        msg.envelope_pubkey = pub_dec
        # Use client-provided last_block_hash (may be empty); no PoW for upgrade
        msg.envelope_block_hash = _hex_to_bytes(last_block_hash)
        msg.envelope_difficulty = 0  # No PoW for upgrade
        msg.envelope_pow = 0  # No PoW for upgrade
        msg.envelope_timestamp = int(timestamp)
        msg.envelope_signature = sig_dec
        msg.level = level

        any_msg = AnyPB()
        any_msg.type_url = "/mirage.core.v1.MsgUpgradeLevel"
        any_msg.value = msg.SerializeToString()
        body = TxBody(messages=[any_msg], memo="")
        body_bytes = body.SerializeToString()
        gas_est = int(estimate_total_gas_limit(body_bytes, 0))
        tx_bytes_est = build_tx_bytes(body_bytes, gas_est)
        gas_used = int(simulate_gas(tx_bytes_est))
        gas_limit = max(gas_est, int(gas_used * GAS_BUFFER_MULTIPLIER))
        tx_bytes = build_tx_bytes(body_bytes, gas_limit)
        tx_hash, code, height, raw_log = broadcast_tx(tx_bytes)

        if code != 0:
            extra = {
                "height": height,
                "user_addr": user_addr,
                "level": int(level),
                "last_block_hash": last_block_hash,
            }
            return _tx_error(rid, "core/upgrade_level", "MsgUpgradeLevel", code, tx_hash, raw_log, extra)

        log_event(rid, "upgrade_level.success", tx_hash=tx_hash)
        return jsonify({"tx_hash": tx_hash, "code": code, "height": height, "raw_log": raw_log})
    except Exception as e:
        log_event(rid, "upgrade_level.err", error=str(e))
        return jsonify({"error": str(e)}), 500


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
            return jsonify({"error": "node_catching_up"}), 503
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
            return jsonify({"error": "not_subscriber"}), 400

        validator_addr = require_runtime().validator_payer_addr

        # Backend signature verification (first line of defense)
        try:
            base = canon_base_set_auto_renewal(
                pub_dec,
                last_block_hash,
                0,
                timestamp,
                auto_renew,
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
        msg.envelope_signature = sig_dec
        msg.auto_renew = auto_renew

        any_msg = AnyPB()
        any_msg.type_url = "/mirage.core.v1.MsgSetAutoRenewal"
        any_msg.value = msg.SerializeToString()
        body = TxBody(messages=[any_msg], memo="")
        body_bytes = body.SerializeToString()
        gas_est = int(estimate_total_gas_limit(body_bytes, 0))
        tx_bytes_est = build_tx_bytes(body_bytes, gas_est)
        gas_used = int(simulate_gas(tx_bytes_est))
        gas_limit = max(gas_est, int(gas_used * GAS_BUFFER_MULTIPLIER))
        tx_bytes = build_tx_bytes(body_bytes, gas_limit)
        tx_hash, code, height, raw_log = broadcast_tx(tx_bytes)

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
        return jsonify({"error": str(e)}), 500


def _lookup_ip_info(ip: str) -> dict:
    """Lookup IP metadata using ip-api.com (free, no API key).

    Returns dict with: country, countryCode, isp, org, mobile, proxy, hosting, reverse DNS.
    On failure, returns empty dict (non-blocking).

    Rate limit: 45 requests/minute on free tier.
    """
    if not ip or ip in ("127.0.0.1", "::1", "localhost"):
        return {}

    result = {}

    # Try reverse DNS first (fast, local)
    try:
        hostname = socket.gethostbyaddr(ip)[0]
        result["rdns"] = hostname
    except (socket.herror, socket.gaierror, OSError):
        pass

    # Lookup via ip-api.com (free tier, no key needed)
    try:
        url = (
            f"http://ip-api.com/json/{ip}?fields=status,country,countryCode,region,city,isp,org,as,mobile,proxy,hosting"
        )
        req = _ur.Request(url, headers={"User-Agent": "mirage-backend/1.0"})
        with _ur.urlopen(req, timeout=2) as resp:
            data = json.loads(resp.read().decode())
            if data.get("status") == "success":
                result["country"] = data.get("country")
                result["countryCode"] = data.get("countryCode")
                result["region"] = data.get("region")
                result["city"] = data.get("city")
                result["isp"] = data.get("isp")
                result["org"] = data.get("org")
                result["asn"] = data.get("as")
                result["mobile"] = data.get("mobile", False)
                result["proxy"] = data.get("proxy", False)
                result["hosting"] = data.get("hosting", False)
    except Exception:
        # Non-blocking - if lookup fails, we just don't have the metadata
        pass

    return result


def _compute_fp_hash(data: dict, attributes: dict) -> str:
    """Compute fingerprint hash from material fields.

    Includes both legacy fields and key attributes from the extended JSONB blob.
    """
    parts = [
        str(data.get("ip_hash") or ""),
        str(data.get("canvas_hash") or ""),
        str(data.get("webgl_hash") or ""),
        str(data.get("screen_width") or ""),
        str(data.get("screen_height") or ""),
        str(data.get("timezone") or ""),
        str(data.get("user_agent_hash") or ""),
    ]
    # Add key attributes from extended fingerprint
    if attributes:
        plugins = attributes.get("plugins", {})
        webgl = attributes.get("webgl", {})
        audio = attributes.get("audio", {})
        parts.extend(
            [
                str(plugins.get("hash") or ""),
                str(webgl.get("extensionsHash") or ""),
                str(audio.get("codecsHash") or ""),
                str(attributes.get("mathHash") or ""),
            ]
        )
    combined = "|".join(parts)
    return hashlib.sha256(combined.encode()).hexdigest()[:32]


@core_bp.route("/api/core/fp", methods=["POST"])
def save_fingerprint():
    """Save device fingerprint for fraud detection. Appends new record on material change."""
    try:
        data = request.get_json() or {}
        user_address = (data.get("user_address") or "").strip().lower()
        if not user_address:
            return jsonify({"error": "missing user_address"}), 400

        now_ts = int(time.time())

        # Extract from request headers
        ip_raw = request.headers.get("X-Forwarded-For", request.headers.get("X-Real-IP", request.remote_addr or ""))
        ip_raw = ip_raw.split(",")[0].strip() if ip_raw else ""
        ip_hash = hashlib.sha256(ip_raw.encode()).hexdigest()[:32] if ip_raw else None

        # Lookup IP metadata (country, ISP, proxy detection, etc.)
        ip_info = _lookup_ip_info(ip_raw) if ip_raw else {}

        user_agent = request.headers.get("User-Agent", "")[:500]
        user_agent_hash = hashlib.sha256(user_agent.encode()).hexdigest()[:32] if user_agent else None

        # Capture additional HTTP headers for fingerprinting
        http_headers = {
            "accept": request.headers.get("Accept", ""),
            "acceptLanguage": request.headers.get("Accept-Language", ""),
            "acceptEncoding": request.headers.get("Accept-Encoding", ""),
            "dnt": request.headers.get("DNT", ""),
            "secChUa": request.headers.get("Sec-CH-UA", ""),
            "secChUaPlatform": request.headers.get("Sec-CH-UA-Platform", ""),
            "secChUaMobile": request.headers.get("Sec-CH-UA-Mobile", ""),
        }

        # Frontend-provided data (legacy fields for indexed columns)
        fp_data = {
            "ip_hash": ip_hash,
            "user_agent": user_agent,
            "user_agent_hash": user_agent_hash,
            "screen_width": data.get("screenWidth"),
            "screen_height": data.get("screenHeight"),
            "color_depth": data.get("colorDepth"),
            "pixel_ratio": data.get("pixelRatio"),
            "timezone": data.get("timezone"),
            "timezone_offset": data.get("timezoneOffset"),
            "language": data.get("language"),
            "languages": json.dumps(data.get("languages")) if data.get("languages") else None,
            "platform": data.get("platform"),
            "hardware_concurrency": data.get("hardwareConcurrency"),
            "device_memory": data.get("deviceMemory"),
            "touch_support": data.get("touchSupport"),
            "canvas_hash": data.get("canvasHash"),
            "webgl_vendor": data.get("webglVendor"),
            "webgl_renderer": data.get("webglRenderer"),
            "webgl_hash": data.get("webglHash"),
        }

        # Extended attributes from frontend (stored as JSONB)
        frontend_attributes = data.get("attributes", {})

        # Combine frontend attributes with server-side captured data
        attributes = {
            **frontend_attributes,
            "httpHeaders": http_headers,
            "serverTimestamp": now_ts,
        }

        # Add IP metadata if available (country, ISP, proxy/VPN detection)
        if ip_info:
            attributes["ipInfo"] = ip_info

        fingerprint_hash = _compute_fp_hash(fp_data, attributes)
        attributes_jsonb = Jsonb(attributes or {})

        with connect_db() as conn:
            with conn.cursor() as cur:
                # Check for existing fingerprint with same hash
                cur.execute(
                    """
                    SELECT id, fingerprint_hash FROM user_fingerprints
                    WHERE user_address = %s
                    ORDER BY last_seen DESC
                    LIMIT 1
                    """,
                    (user_address,),
                )
                row = cur.fetchone()

                if row and row[1] == fingerprint_hash:
                    # Same fingerprint, update last_seen, seen_count, and attributes
                    cur.execute(
                        """
                        UPDATE user_fingerprints
                        SET last_seen = %s, seen_count = seen_count + 1, attributes = %s
                        WHERE id = %s
                        """,
                        (now_ts, attributes_jsonb, row[0]),
                    )
                else:
                    # New or changed fingerprint, insert new row
                    cur.execute(
                        """
                        INSERT INTO user_fingerprints (
                            user_address, ip_hash, user_agent, user_agent_hash,
                            screen_width, screen_height, color_depth, pixel_ratio,
                            timezone, timezone_offset, language, languages,
                            platform, hardware_concurrency, device_memory, touch_support,
                            canvas_hash, webgl_vendor, webgl_renderer, webgl_hash,
                            fingerprint_hash, first_seen, last_seen, seen_count, attributes
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1, %s
                        )
                        """,
                        (
                            user_address,
                            fp_data["ip_hash"],
                            fp_data["user_agent"],
                            fp_data["user_agent_hash"],
                            fp_data["screen_width"],
                            fp_data["screen_height"],
                            fp_data["color_depth"],
                            fp_data["pixel_ratio"],
                            fp_data["timezone"],
                            fp_data["timezone_offset"],
                            fp_data["language"],
                            fp_data["languages"],
                            fp_data["platform"],
                            fp_data["hardware_concurrency"],
                            fp_data["device_memory"],
                            fp_data["touch_support"],
                            fp_data["canvas_hash"],
                            fp_data["webgl_vendor"],
                            fp_data["webgl_renderer"],
                            fp_data["webgl_hash"],
                            fingerprint_hash,
                            now_ts,
                            now_ts,
                            attributes_jsonb,
                        ),
                    )

        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


__all__ = ["core_bp"]
