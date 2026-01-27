from __future__ import annotations

"""Quest and Achievement API endpoints.

User endpoints:
- GET /api/quests/daily: Get user's daily quest status
- GET /api/quests/flash: Get active flash quests and user progress
- GET /api/achievements: Get all achievements with unlock status
- GET /api/rewards/pending: Get user's pending/claimable rewards
- POST /api/rewards/claim: Claim pending rewards

Admin endpoints (require level >= 100):
- POST /api/admin/rewards/suspend: Suspend rewards for a user
- POST /api/admin/rewards/unsuspend: Unsuspend a user
- GET /api/admin/rewards/suspensions: List all suspended users
"""

import json
import time
from typing import Any, Dict, Optional

from flask import Blueprint, jsonify, request

from db import connect_db
from logging_utils import log_event, next_request_id
from node import derive_address_from_pubkey, require_runtime
from reward_distributor import get_distributor
from routes.core import get_user_level


quests_bp = Blueprint("quests", __name__)


def _get_utc_julian_day(ts: int) -> int:
    """Convert Unix timestamp to UTC Julian day number."""
    return 2440588 + (ts // 86400)


def _get_seconds_until_reset(ts: int) -> int:
    """Calculate seconds until next UTC midnight."""
    seconds_into_day = ts % 86400
    return 86400 - seconds_into_day


def _load_quest_definitions() -> Dict[str, Any]:
    """Load quest definitions from YAML file."""
    import os
    import yaml
    
    yaml_path = os.path.join(os.path.dirname(__file__), "../../..", "indexer/quests.yaml")
    yaml_path = os.path.abspath(yaml_path)
    
    if not os.path.exists(yaml_path):
        return {"daily_quests": [], "flash_quest_templates": [], "achievements": []}
    
    try:
        with open(yaml_path, "r") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {"daily_quests": [], "flash_quest_templates": [], "achievements": []}


def _get_user_reward_multiplier(owner: str, ts: int) -> float:
    """Calculate reward multiplier based on account age (1x to 5x over 30 days)."""
    with connect_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT created_at FROM profiles WHERE LOWER(owner) = LOWER(%s)",
                (owner,)
            )
            row = cur.fetchone()
            if not row or not row[0]:
                return 1.0  # Default to 1x for unknown accounts
            
            created_at = row[0]
            age_days = (ts - created_at) / 86400
            
            # Linear ramp from 1x to 5x over 30 days
            # progress goes from 0.0 (day 0) to 1.0 (day 30+)
            progress = min(1.0, max(0.0, age_days / 30))
            multiplier = 1.0 + (progress * 4.0)  # 1x + (0-4x) = 1x to 5x
            return multiplier


def _is_user_suspended(owner: str, ts: int) -> bool:
    """Check if user's rewards are suspended."""
    with connect_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT suspended_until FROM reward_suspensions WHERE LOWER(owner) = LOWER(%s)",
                (owner,)
            )
            row = cur.fetchone()
            if not row:
                return False
            return row[0] > ts


def _get_suspension_info(owner: str) -> Optional[Dict[str, Any]]:
    """Get suspension info for a user."""
    with connect_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT suspended_until, suspended_by, reason, updated_at
                FROM reward_suspensions
                WHERE LOWER(owner) = LOWER(%s)
                """,
                (owner,)
            )
            row = cur.fetchone()
            if not row:
                return None
            return {
                "suspended_until": row[0],
                "suspended_by": row[1],
                "reason": row[2],
                "updated_at": row[3],
            }


@quests_bp.route("/api/quests/daily", methods=["GET"])
def get_daily_quests():
    """Get user's daily quest status.
    
    Query params:
    - owner: User address (required)
    """
    rid = next_request_id()
    log_event(rid, "quests.daily.begin")
    
    try:
        owner = (request.args.get("owner") or "").strip().lower()
        if not owner:
            return jsonify({"error": "owner required"}), 400
        
        ts = int(time.time())
        day_utc = _get_utc_julian_day(ts)
        
        # Check if suspended
        if _is_user_suspended(owner, ts):
            suspension = _get_suspension_info(owner)
            return jsonify({
                "suspended": True,
                "suspension": suspension,
                "daily_quests": [],
                "seconds_until_reset": _get_seconds_until_reset(ts),
                "reward_multiplier": 1.0,
            })
        
        # Load quest definitions
        defs = _load_quest_definitions()
        daily_defs = {q["id"]: q for q in defs.get("daily_quests", [])}
        
        # Get user's assigned quests for today
        with connect_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT quest_id, progress, progress_meta, completed_at
                    FROM user_daily_quests
                    WHERE LOWER(owner) = LOWER(%s) AND day_utc = %s
                    """,
                    (owner, day_utc)
                )
                rows = cur.fetchall()
        
        daily_quests = []
        for row in rows:
            quest_id = row[0]
            progress = row[1]
            progress_meta = row[2] if isinstance(row[2], dict) else {}
            completed_at = row[3]
            
            quest_def = daily_defs.get(quest_id, {})
            if not quest_def:
                continue
            
            # Calculate target for balanced_vote
            if quest_def.get("action_type") == "balanced_vote":
                target = (quest_def.get("target_upvotes", 0) or 0) + (quest_def.get("target_downvotes", 0) or 0)
            else:
                target = quest_def.get("target_count", 1)
            
            daily_quests.append({
                "id": quest_id,
                "title": quest_def.get("title", ""),
                "description": quest_def.get("description", ""),
                "progress": progress,
                "target": target,
                "completed": completed_at is not None,
                "rewards": quest_def.get("rewards", []),
            })
        
        multiplier = _get_user_reward_multiplier(owner, ts)
        
        log_event(rid, "quests.daily.ok", owner=owner, quest_count=len(daily_quests))
        return jsonify({
            "suspended": False,
            "daily_quests": daily_quests,
            "seconds_until_reset": _get_seconds_until_reset(ts),
            "reward_multiplier": round(multiplier, 4),
        })
    except Exception as e:
        log_event(rid, "quests.daily.err", error=str(e))
        return jsonify({"error": str(e)}), 500


@quests_bp.route("/api/quests/flash", methods=["GET"])
def get_flash_quests():
    """Get active flash quests and user progress.
    
    Query params:
    - owner: User address (required)
    """
    rid = next_request_id()
    log_event(rid, "quests.flash.begin")
    
    try:
        owner = (request.args.get("owner") or "").strip().lower()
        if not owner:
            return jsonify({"error": "owner required"}), 400
        
        ts = int(time.time())
        
        # Check if suspended
        if _is_user_suspended(owner, ts):
            return jsonify({
                "suspended": True,
                "flash_quest": None,
            })
        
        # Load quest definitions
        defs = _load_quest_definitions()
        flash_defs = {q["id"]: q for q in defs.get("flash_quest_templates", [])}
        
        # Get user's active flash quest
        with connect_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT template_id, starts_at, ends_at, progress, progress_meta, completed_at
                    FROM user_flash_quests
                    WHERE LOWER(owner) = LOWER(%s)
                      AND ends_at > %s
                    ORDER BY starts_at DESC
                    LIMIT 1
                    """,
                    (owner, ts)
                )
                row = cur.fetchone()
        
        if not row:
            return jsonify({
                "suspended": False,
                "flash_quest": None,
            })
        
        template_id = row[0]
        starts_at = row[1]
        ends_at = row[2]
        progress = row[3]
        completed_at = row[5]
        
        quest_def = flash_defs.get(template_id, {})
        if not quest_def:
            return jsonify({
                "suspended": False,
                "flash_quest": None,
            })
        
        flash_quest = {
            "id": template_id,
            "title": quest_def.get("title", ""),
            "description": quest_def.get("description", ""),
            "progress": progress,
            "target": quest_def.get("target_count", 1),
            "completed": completed_at is not None,
            "starts_at": starts_at,
            "ends_at": ends_at,
            "seconds_remaining": max(0, ends_at - ts),
            "rewards": quest_def.get("rewards", []),
        }
        
        log_event(rid, "quests.flash.ok", owner=owner, template_id=template_id)
        return jsonify({
            "suspended": False,
            "flash_quest": flash_quest,
        })
    except Exception as e:
        log_event(rid, "quests.flash.err", error=str(e))
        return jsonify({"error": str(e)}), 500


@quests_bp.route("/api/achievements", methods=["GET"])
def get_achievements():
    """Get all achievements with unlock status.
    
    Query params:
    - owner: User address (required)
    """
    rid = next_request_id()
    log_event(rid, "achievements.begin")
    
    try:
        owner = (request.args.get("owner") or "").strip().lower()
        if not owner:
            return jsonify({"error": "owner required"}), 400
        
        # Load quest definitions
        defs = _load_quest_definitions()
        achievement_defs = defs.get("achievements", [])
        
        # Get user's unlocked achievements
        with connect_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT achievement_id, progress, unlocked_at
                    FROM user_achievements
                    WHERE LOWER(owner) = LOWER(%s)
                    """,
                    (owner,)
                )
                rows = cur.fetchall()
        
        user_achievements = {row[0]: {"progress": row[1], "unlocked_at": row[2]} for row in rows}
        
        achievements = []
        for achievement_def in achievement_defs:
            achievement_id = achievement_def["id"]
            user_data = user_achievements.get(achievement_id, {})
            
            achievements.append({
                "id": achievement_id,
                "title": achievement_def.get("title", ""),
                "description": achievement_def.get("description", ""),
                "progress": user_data.get("progress", 0),
                "target": achievement_def.get("target_count", 1),
                "unlocked": user_data.get("unlocked_at") is not None,
                "unlocked_at": user_data.get("unlocked_at"),
                "badge_icon": achievement_def.get("badge_icon"),
                "rewards": achievement_def.get("rewards", []),
            })
        
        log_event(rid, "achievements.ok", owner=owner, count=len(achievements))
        return jsonify({"achievements": achievements})
    except Exception as e:
        log_event(rid, "achievements.err", error=str(e))
        return jsonify({"error": str(e)}), 500


@quests_bp.route("/api/rewards/pending", methods=["GET"])
def get_pending_rewards():
    """Get user's pending/claimable rewards.
    
    Query params:
    - owner: User address (required)
    """
    rid = next_request_id()
    log_event(rid, "rewards.pending.begin")
    
    try:
        owner = (request.args.get("owner") or "").strip().lower()
        if not owner:
            return jsonify({"error": "owner required"}), 400
        
        ts = int(time.time())
        
        # Check if suspended
        if _is_user_suspended(owner, ts):
            suspension = _get_suspension_info(owner)
            return jsonify({
                "suspended": True,
                "suspension": suspension,
                "pending_rewards": [],
                "total_mirage": 0,
                "reward_multiplier": 1.0,
            })
        
        # Get pending rewards
        with connect_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, reward_type, reward_data, reason, created_at
                    FROM pending_rewards
                    WHERE LOWER(owner) = LOWER(%s) AND claimed_at IS NULL
                    ORDER BY created_at ASC
                    """,
                    (owner,)
                )
                rows = cur.fetchall()
        
        pending_rewards = []
        total_mirage = 0
        
        for row in rows:
            reward_data = row[2] if isinstance(row[2], dict) else {}
            reward = {
                "id": row[0],
                "type": row[1],
                "data": reward_data,
                "reason": row[3],
                "created_at": row[4],
            }
            pending_rewards.append(reward)
            
            if row[1] == "mirage":
                total_mirage += reward_data.get("amount", 0)
        
        multiplier = _get_user_reward_multiplier(owner, ts)
        
        log_event(rid, "rewards.pending.ok", owner=owner, count=len(pending_rewards), total_mirage=total_mirage)
        return jsonify({
            "suspended": False,
            "pending_rewards": pending_rewards,
            "total_mirage": total_mirage,
            "total_mirage_after_multiplier": int(total_mirage * multiplier),
            "reward_multiplier": round(multiplier, 4),
        })
    except Exception as e:
        log_event(rid, "rewards.pending.err", error=str(e))
        return jsonify({"error": str(e)}), 500


@quests_bp.route("/api/rewards/claim", methods=["POST"])
def claim_rewards():
    """Claim pending rewards.
    
    Body:
    - owner: User address (required)
    
    Returns:
    - success: bool
    - rewards: List of claimed rewards
    - tx_hash: Transaction hash for MIRAGE rewards (if any)
    """
    rid = next_request_id()
    log_event(rid, "rewards.claim.begin")
    
    try:
        data = request.get_json(force=True) or {}
        owner = str(data.get("owner", "")).strip().lower()
        
        if not owner:
            return jsonify({"error": "owner required"}), 400
        
        ts = int(time.time())
        
        # Check if suspended
        if _is_user_suspended(owner, ts):
            return jsonify({
                "success": False,
                "error": "suspended",
                "message": "Your rewards are suspended",
            }), 403
        
        # Use reward distributor to process claim
        distributor = get_distributor()
        result = distributor.claim_rewards(owner, ts)
        
        if not result["success"]:
            error_msg = result.get("error", "unknown_error")
            if error_msg == "no_rewards":
                log_event(rid, "rewards.claim.empty", owner=owner)
                return jsonify({
                    "success": False,
                    "error": "no_rewards",
                    "message": "No pending rewards to claim",
                })
            else:
                log_event(rid, "rewards.claim.failed", owner=owner, error=error_msg)
                return jsonify({
                    "success": False,
                    "error": error_msg,
                    "message": f"Failed to claim rewards: {error_msg}",
                }), 500
        
        log_event(
            rid,
            "rewards.claim.ok",
            owner=owner,
            reward_count=len(result.get("rewards", [])),
            tx_hash=result.get("tx_hash"),
        )
        return jsonify({
            "success": True,
            "rewards": result.get("rewards", []),
            "tx_hash": result.get("tx_hash"),
        })
    except Exception as e:
        log_event(rid, "rewards.claim.err", error=str(e))
        return jsonify({"error": str(e)}), 500


# ========== Admin Endpoints ==========

@quests_bp.route("/api/admin/rewards/suspend", methods=["POST"])
def admin_suspend_rewards():
    """Suspend rewards for a user (admin only, level >= 100).
    
    Body:
    - admin: Admin address (required)
    - target: User address to suspend (required)
    - duration_days: Suspension duration in days (required, 0 = permanent)
    - reason: Reason for suspension (required)
    """
    rid = next_request_id()
    log_event(rid, "admin.suspend.begin")
    
    try:
        data = request.get_json(force=True) or {}
        admin = str(data.get("admin", "")).strip().lower()
        target = str(data.get("target", "")).strip().lower()
        duration_days = data.get("duration_days")
        reason = str(data.get("reason", "")).strip()
        
        if not admin or not target or duration_days is None or not reason:
            return jsonify({"error": "admin, target, duration_days, and reason required"}), 400
        
        try:
            duration_days = int(duration_days)
        except (TypeError, ValueError):
            return jsonify({"error": "invalid duration_days"}), 400
        
        # Check admin level
        admin_level = get_user_level(admin)
        if admin_level < 100:
            return jsonify({"error": "unauthorized", "message": "Admin level required"}), 403
        
        ts = int(time.time())
        
        # Calculate suspended_until
        if duration_days == 0:
            # Permanent suspension (set to year 2100)
            suspended_until = 4102444800  # Jan 1, 2100
        else:
            suspended_until = ts + (duration_days * 86400)
        
        # Upsert suspension
        with connect_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO reward_suspensions (owner, suspended_until, suspended_by, reason, updated_at)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (owner) DO UPDATE SET
                        suspended_until = EXCLUDED.suspended_until,
                        suspended_by = EXCLUDED.suspended_by,
                        reason = EXCLUDED.reason,
                        updated_at = EXCLUDED.updated_at
                    """,
                    (target, suspended_until, admin, reason, ts)
                )
        
        log_event(
            rid,
            "admin.suspend.ok",
            admin=admin,
            target=target,
            duration_days=duration_days,
            suspended_until=suspended_until,
        )
        return jsonify({
            "success": True,
            "target": target,
            "suspended_until": suspended_until,
            "reason": reason,
        })
    except Exception as e:
        log_event(rid, "admin.suspend.err", error=str(e))
        return jsonify({"error": str(e)}), 500


@quests_bp.route("/api/admin/rewards/unsuspend", methods=["POST"])
def admin_unsuspend_rewards():
    """Unsuspend a user's rewards (admin only, level >= 100).
    
    Body:
    - admin: Admin address (required)
    - target: User address to unsuspend (required)
    - void_pending: Whether to void pending rewards (optional, default false)
    """
    rid = next_request_id()
    log_event(rid, "admin.unsuspend.begin")
    
    try:
        data = request.get_json(force=True) or {}
        admin = str(data.get("admin", "")).strip().lower()
        target = str(data.get("target", "")).strip().lower()
        void_pending = bool(data.get("void_pending", False))
        
        if not admin or not target:
            return jsonify({"error": "admin and target required"}), 400
        
        # Check admin level
        admin_level = get_user_level(admin)
        if admin_level < 100:
            return jsonify({"error": "unauthorized", "message": "Admin level required"}), 403
        
        ts = int(time.time())
        
        # Remove suspension (set suspended_until to 0)
        with connect_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE reward_suspensions
                    SET suspended_until = 0, updated_at = %s
                    WHERE LOWER(owner) = LOWER(%s)
                    """,
                    (ts, target)
                )
                
                # Optionally void pending rewards
                if void_pending:
                    cur.execute(
                        """
                        DELETE FROM pending_rewards
                        WHERE LOWER(owner) = LOWER(%s) AND claimed_at IS NULL
                        """,
                        (target,)
                    )
        
        log_event(
            rid,
            "admin.unsuspend.ok",
            admin=admin,
            target=target,
            void_pending=void_pending,
        )
        return jsonify({
            "success": True,
            "target": target,
            "void_pending": void_pending,
        })
    except Exception as e:
        log_event(rid, "admin.unsuspend.err", error=str(e))
        return jsonify({"error": str(e)}), 500


@quests_bp.route("/api/admin/rewards/suspensions", methods=["GET"])
def admin_list_suspensions():
    """List all currently suspended users (admin only, level >= 100).
    
    Query params:
    - admin: Admin address (required)
    """
    rid = next_request_id()
    log_event(rid, "admin.suspensions.begin")
    
    try:
        admin = (request.args.get("admin") or "").strip().lower()
        
        if not admin:
            return jsonify({"error": "admin required"}), 400
        
        # Check admin level
        admin_level = get_user_level(admin)
        if admin_level < 100:
            return jsonify({"error": "unauthorized", "message": "Admin level required"}), 403
        
        ts = int(time.time())
        
        # Get all active suspensions
        with connect_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT owner, suspended_until, suspended_by, reason, updated_at
                    FROM reward_suspensions
                    WHERE suspended_until > %s
                    ORDER BY updated_at DESC
                    """,
                    (ts,)
                )
                rows = cur.fetchall()
        
        suspensions = []
        for row in rows:
            suspensions.append({
                "owner": row[0],
                "suspended_until": row[1],
                "suspended_by": row[2],
                "reason": row[3],
                "updated_at": row[4],
            })
        
        log_event(rid, "admin.suspensions.ok", count=len(suspensions))
        return jsonify({"suspensions": suspensions})
    except Exception as e:
        log_event(rid, "admin.suspensions.err", error=str(e))
        return jsonify({"error": str(e)}), 500
