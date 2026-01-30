from __future__ import annotations

"""Quest and Rewards API endpoints.

User endpoints:
- GET /api/rewards/daily: Get user's daily quest status
- GET /api/rewards/flash: Get active flash quests and user progress
- GET /api/rewards/achievements: Get all achievements with unlock status
- GET /api/rewards/pending: Get user's pending/claimable rewards
- POST /api/rewards/claim: Claim pending rewards
- GET /api/rewards/stats: Get reward statistics (public)
- GET /api/rewards/history: Get reward history (public)

Admin endpoints (require level >= 100):
- POST /api/admin/rewards/suspend: Suspend rewards for a user
- POST /api/admin/rewards/unsuspend: Unsuspend a user
- GET /api/admin/rewards/suspensions: List all suspended users
"""

import hashlib
import json
import os
import random
import time
from typing import Any, Dict, List, Optional

from flask import Blueprint, jsonify, request

from db import connect_db
from logging_utils import log_event, next_request_id
from node import derive_address_from_pubkey, require_runtime
from reward_distributor import get_distributor
from routes.core import get_user_level


quests_bp = Blueprint("quests", __name__)

# Quest system configuration (from environment)
QUESTS_ENABLED = os.environ.get("QUESTS_ENABLED", "").lower() == "true"
DAILY_QUESTS_COUNT = int(os.environ.get("DAILY_QUESTS_COUNT", "2"))
FLASH_QUESTS_COUNT = int(os.environ.get("FLASH_QUESTS_COUNT", "1"))
FLASH_QUEST_MIN_INTERVAL_HOURS = int(os.environ.get("FLASH_QUEST_MIN_INTERVAL_HOURS", "5"))
FLASH_QUEST_MAX_INTERVAL_HOURS = int(os.environ.get("FLASH_QUEST_MAX_INTERVAL_HOURS", "7"))

# Special quest gating
INVITE_RECRUIT_CHANCE = float(os.environ.get("INVITE_RECRUIT_CHANCE", "0.30"))
INVITE_EARNER_QUEST_INTERVAL = int(os.environ.get("INVITE_EARNER_QUEST_INTERVAL", "15"))


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
            cur.execute("SELECT created_at FROM profiles WHERE LOWER(owner) = LOWER(%s)", (owner,))
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
            cur.execute("SELECT suspended_until FROM reward_suspensions WHERE LOWER(owner) = LOWER(%s)", (owner,))
            row = cur.fetchone()
            if not row:
                return False
            return row[0] > ts


def _get_next_flash_time(owner: str) -> int:
    """Get the timestamp when user can receive their next flash quest."""
    with connect_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT next_flash_at FROM user_quest_state WHERE LOWER(owner) = LOWER(%s)", (owner,))
            row = cur.fetchone()
            return row[0] if row else 0


def _set_next_flash_time(owner: str, next_ts: int) -> None:
    """Set when the user can receive their next flash quest."""
    with connect_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO user_quest_state (owner, next_flash_at)
                VALUES (%s, %s)
                ON CONFLICT (owner) DO UPDATE SET next_flash_at = EXCLUDED.next_flash_at
                """,
                (owner, next_ts),
            )


def _maybe_assign_flash_quest(owner: str, ts: int, flash_defs: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Assign a flash quest if eligible. Returns the quest data or None."""
    if not flash_defs:
        return None

    # Check if user already has an active flash quest
    with connect_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 1 FROM user_flash_quests
                WHERE LOWER(owner) = LOWER(%s) AND ends_at > %s
                LIMIT 1
                """,
                (owner, ts),
            )
            if cur.fetchone():
                return None  # Already has an active quest

    # Check if enough time has passed since last flash quest
    next_flash_at = _get_next_flash_time(owner)
    if ts < next_flash_at:
        return None

    # Select a random flash quest template
    template_id = random.choice(list(flash_defs.keys()))
    template = flash_defs[template_id]

    # Calculate duration based on time_window_minutes (default 60 min)
    duration_seconds = (template.get("time_window_minutes") or 60) * 60
    ends_at = ts + duration_seconds

    # Insert the flash quest
    with connect_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO user_flash_quests (owner, template_id, starts_at, ends_at, progress, progress_meta)
                VALUES (%s, %s, %s, %s, 0, '{}')
                """,
                (owner, template_id, ts, ends_at),
            )

    # Schedule next flash quest (random interval between MIN and MAX hours)
    next_interval_seconds = random.randint(FLASH_QUEST_MIN_INTERVAL_HOURS * 3600, FLASH_QUEST_MAX_INTERVAL_HOURS * 3600)
    _set_next_flash_time(owner, ts + next_interval_seconds)

    return {
        "template_id": template_id,
        "starts_at": ts,
        "ends_at": ends_at,
        "progress": 0,
        "progress_meta": {},
        "completed_at": None,
    }


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
                (owner,),
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


def _has_unused_invite_codes(owner: str) -> bool:
    """Check if user has at least one unused invite code."""
    with connect_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 1 FROM invite_codes
                WHERE LOWER(owner) = LOWER(%s) AND used_by IS NULL
                LIMIT 1
                """,
                (owner,),
            )
            return cur.fetchone() is not None


def _get_completed_quest_count(owner: str) -> int:
    """Get total number of completed quests for a user."""
    with connect_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) FROM user_daily_quests
                WHERE LOWER(owner) = LOWER(%s) AND completed_at IS NOT NULL
                """,
                (owner,),
            )
            row = cur.fetchone()
            return row[0] if row else 0


def _deterministic_roll(owner: str, day_utc: int, roll_type: str) -> float:
    """Generate a deterministic random value (0-1) based on owner, day, and roll type."""
    seed_str = f"{owner.lower()}:{day_utc}:{roll_type}"
    seed_hash = hashlib.sha256(seed_str.encode()).hexdigest()
    # Use first 8 hex chars as seed (32 bits)
    seed_int = int(seed_hash[:8], 16)
    rng = random.Random(seed_int)
    return rng.random()


def _assign_daily_quests_if_needed(owner: str, day_utc: int, daily_defs: Dict[str, Any], special_defs: Dict[str, Any] = None) -> List[str]:
    """Assign daily quests to a user if they don't have any for today.

    Includes special quest gating logic:
    - invite_recruit: 30% chance if user has unused invite codes
    - invite_earner: appears every N completed quests

    Returns the list of assigned quest IDs.
    """
    if special_defs is None:
        special_defs = {}

    with connect_db() as conn:
        with conn.cursor() as cur:
            # Check if user already has quests for today
            cur.execute(
                """
                SELECT DISTINCT quest_id FROM user_daily_quests
                WHERE LOWER(owner) = LOWER(%s) AND day_utc = %s
                """,
                (owner, day_utc),
            )
            existing = [row[0] for row in cur.fetchall()]

            if existing:
                return existing

            # No quests assigned yet - check special quests first
            quest_ids = []
            special_quest_assigned = False

            # Check for invite_recruit eligibility (30% roll if user has unused codes)
            if not special_quest_assigned and "invite_recruit" in special_defs:
                if _has_unused_invite_codes(owner):
                    roll = _deterministic_roll(owner, day_utc, "invite_recruit")
                    log_event(None, "quest.invite_recruit.roll", owner=owner, roll=round(roll, 3), threshold=INVITE_RECRUIT_CHANCE)
                    if roll < INVITE_RECRUIT_CHANCE:
                        quest_ids.append("invite_recruit")
                        special_quest_assigned = True
                        log_event(None, "quest.invite_recruit.assigned", owner=owner)

            # Check for invite_earner eligibility (every N completed quests)
            if not special_quest_assigned and "invite_earner" in special_defs:
                completed_count = _get_completed_quest_count(owner)
                if completed_count > 0 and completed_count % INVITE_EARNER_QUEST_INTERVAL == 0:
                    quest_ids.append("invite_earner")
                    special_quest_assigned = True
                    log_event(None, "quest.invite_earner.assigned", owner=owner, completed_count=completed_count)

            # Fill remaining slots with random daily quests
            if not daily_defs:
                return quest_ids

            remaining_slots = DAILY_QUESTS_COUNT - len(quest_ids)
            if remaining_slots > 0:
                available_ids = list(daily_defs.keys())
                count = min(remaining_slots, len(available_ids))
                selected_ids = random.sample(available_ids, count)
                quest_ids.extend(selected_ids)

            # Insert initial progress records
            for quest_id in quest_ids:
                cur.execute(
                    """
                    INSERT INTO user_daily_quests (owner, day_utc, quest_id, progress, progress_meta)
                    VALUES (%s, %s, %s, 0, '{}')
                    ON CONFLICT (owner, day_utc, quest_id) DO NOTHING
                    """,
                    (owner, day_utc, quest_id),
                )

            return quest_ids


@quests_bp.route("/api/rewards/daily", methods=["GET"])
def get_daily_quests():
    """Get user's daily quest status.

    Query params:
    - owner: User address (required)
    """
    rid = next_request_id()
    log_event(rid, "quests.daily.begin")

    # Check if quests are enabled
    if not QUESTS_ENABLED:
        return jsonify(
            {
                "disabled": True,
                "daily_quests": [],
                "seconds_until_reset": 0,
                "reward_multiplier": 1,
            }
        )

    try:
        owner = (request.args.get("owner") or "").strip().lower()
        if not owner:
            return jsonify({"error": "owner required"}), 400

        ts = int(time.time())
        day_utc = _get_utc_julian_day(ts)

        # Check if suspended
        if _is_user_suspended(owner, ts):
            suspension = _get_suspension_info(owner)
            return jsonify(
                {
                    "suspended": True,
                    "suspension": suspension,
                    "daily_quests": [],
                    "seconds_until_reset": _get_seconds_until_reset(ts),
                    "reward_multiplier": 1.0,
                }
            )

        # Load quest definitions
        defs = _load_quest_definitions()
        daily_defs = {q["id"]: q for q in defs.get("daily_quests", [])}
        special_defs = {q["id"]: q for q in defs.get("special_quests", [])}

        # Assign quests if user doesn't have any for today
        _assign_daily_quests_if_needed(owner, day_utc, daily_defs, special_defs)

        # Get user's assigned quests for today
        with connect_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT quest_id, progress, progress_meta, completed_at
                    FROM user_daily_quests
                    WHERE LOWER(owner) = LOWER(%s) AND day_utc = %s
                    ORDER BY quest_id ASC
                    """,
                    (owner, day_utc),
                )
                rows = cur.fetchall()

        # Merge daily_defs and special_defs for lookup
        all_defs = {**daily_defs, **special_defs}

        daily_quests = []
        for row in rows:
            quest_id = row[0]
            progress = row[1]
            progress_meta = row[2] if isinstance(row[2], dict) else {}
            completed_at = row[3]

            quest_def = all_defs.get(quest_id, {})
            if not quest_def:
                continue

            # Calculate target for balanced_vote
            quest_data = {
                "id": quest_id,
                "title": quest_def.get("title", ""),
                "description": quest_def.get("description", ""),
                "action_type": quest_def.get("action_type", ""),
                "progress": progress,
                "completed": completed_at is not None,
                "rewards": quest_def.get("rewards", []),
                # Additional requirements for display
                "min_content_length": quest_def.get("min_content_length"),
                "time_spacing_minutes": quest_def.get("time_spacing_minutes"),
                "unique_target": quest_def.get("unique_target"),
                "unique_topics_min": quest_def.get("unique_topics_min"),
                "quality_threshold": quest_def.get("quality_threshold"),
                "count_vote_changes": quest_def.get("count_vote_changes", True),
            }

            if quest_def.get("action_type") == "balanced_vote":
                target_up = quest_def.get("target_upvotes", 0) or 0
                target_down = quest_def.get("target_downvotes", 0) or 0
                quest_data["target"] = target_up + target_down
                # Include breakdown for balanced_vote quests
                quest_data["upvotes"] = progress_meta.get("upvotes", 0)
                quest_data["downvotes"] = progress_meta.get("downvotes", 0)
                quest_data["target_upvotes"] = target_up
                quest_data["target_downvotes"] = target_down
            else:
                quest_data["target"] = quest_def.get("target_count", 1)

            daily_quests.append(quest_data)

        multiplier = _get_user_reward_multiplier(owner, ts)

        log_event(rid, "quests.daily.ok", owner=owner, quest_count=len(daily_quests))
        return jsonify(
            {
                "suspended": False,
                "daily_quests": daily_quests,
                "seconds_until_reset": _get_seconds_until_reset(ts),
                "reward_multiplier": round(multiplier, 4),
            }
        )
    except Exception as e:
        log_event(rid, "quests.daily.err", error=str(e))
        return jsonify({"error": str(e)}), 500


@quests_bp.route("/api/rewards/flash", methods=["GET"])
def get_flash_quests():
    """Get active flash quests and user progress.

    Query params:
    - owner: User address (required)
    """
    rid = next_request_id()
    log_event(rid, "quests.flash.begin")

    # Check if quests are enabled
    if not QUESTS_ENABLED:
        return jsonify(
            {
                "disabled": True,
                "flash_quest": None,
            }
        )

    try:
        owner = (request.args.get("owner") or "").strip().lower()
        if not owner:
            return jsonify({"error": "owner required"}), 400

        ts = int(time.time())

        # Check if suspended
        if _is_user_suspended(owner, ts):
            return jsonify(
                {
                    "suspended": True,
                    "flash_quest": None,
                }
            )

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
                    (owner, ts),
                )
                row = cur.fetchone()

        # If no active flash quest, try to assign one
        if not row:
            assigned = _maybe_assign_flash_quest(owner, ts, flash_defs)
            if assigned:
                # Re-query the newly assigned quest
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
                            (owner, ts),
                        )
                        row = cur.fetchone()

        if not row:
            return jsonify(
                {
                    "suspended": False,
                    "flash_quest": None,
                }
            )

        template_id = row[0]
        starts_at = row[1]
        ends_at = row[2]
        progress = row[3]
        completed_at = row[5]

        quest_def = flash_defs.get(template_id, {})
        if not quest_def:
            return jsonify(
                {
                    "suspended": False,
                    "flash_quest": None,
                }
            )

        flash_quest = {
            "id": template_id,
            "title": quest_def.get("title", ""),
            "description": quest_def.get("description", ""),
            "action_type": quest_def.get("action_type", ""),
            "progress": progress,
            "target": quest_def.get("target_count", 1),
            "completed": completed_at is not None,
            "starts_at": starts_at,
            "ends_at": ends_at,
            "seconds_remaining": max(0, ends_at - ts),
            "rewards": quest_def.get("rewards", []),
            # Additional requirements for display
            "min_content_length": quest_def.get("min_content_length"),
            "time_spacing_minutes": quest_def.get("time_spacing_minutes"),
            "unique_target": quest_def.get("unique_target"),
            "unique_topics_min": quest_def.get("unique_topics_min"),
            "quality_threshold": quest_def.get("quality_threshold"),
            "count_vote_changes": quest_def.get("count_vote_changes", True),
        }

        log_event(rid, "quests.flash.ok", owner=owner, template_id=template_id)
        return jsonify(
            {
                "suspended": False,
                "flash_quest": flash_quest,
            }
        )
    except Exception as e:
        log_event(rid, "quests.flash.err", error=str(e))
        return jsonify({"error": str(e)}), 500


@quests_bp.route("/api/rewards/achievements", methods=["GET"])
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
                    (owner,),
                )
                rows = cur.fetchall()

        user_achievements = {row[0]: {"progress": row[1], "unlocked_at": row[2]} for row in rows}

        achievements = []
        for achievement_def in achievement_defs:
            achievement_id = achievement_def["id"]
            user_data = user_achievements.get(achievement_id, {})

            achievements.append(
                {
                    "id": achievement_id,
                    "title": achievement_def.get("title", ""),
                    "description": achievement_def.get("description", ""),
                    "progress": user_data.get("progress", 0),
                    "target": achievement_def.get("target_count", 1),
                    "unlocked": user_data.get("unlocked_at") is not None,
                    "unlocked_at": user_data.get("unlocked_at"),
                    "badge_icon": achievement_def.get("badge_icon"),
                    "rewards": achievement_def.get("rewards", []),
                }
            )

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
            return jsonify(
                {
                    "suspended": True,
                    "suspension": suspension,
                    "pending_rewards": [],
                    "total_mirage": 0,
                    "reward_multiplier": 1.0,
                }
            )

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
                    (owner,),
                )
                rows = cur.fetchall()

        pending_rewards = []
        total_mirage_with_multiplier = 0
        total_mirage_no_multiplier = 0

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
                amount = reward_data.get("amount", 0)
                apply_multiplier = reward_data.get("apply_multiplier", True)
                if apply_multiplier:
                    total_mirage_with_multiplier += amount
                else:
                    total_mirage_no_multiplier += amount

        multiplier = _get_user_reward_multiplier(owner, ts)
        total_mirage = total_mirage_with_multiplier + total_mirage_no_multiplier
        # Apply multiplier only to rewards that allow it
        total_mirage_after_multiplier = int(total_mirage_with_multiplier * multiplier) + total_mirage_no_multiplier

        # Check if claiming is available
        distributor = get_distributor()
        claiming_available = distributor.is_configured()

        log_event(rid, "rewards.pending.ok", owner=owner, count=len(pending_rewards), total_mirage=total_mirage)
        return jsonify(
            {
                "suspended": False,
                "pending_rewards": pending_rewards,
                "total_mirage": total_mirage,
                "total_mirage_after_multiplier": total_mirage_after_multiplier,
                "reward_multiplier": round(multiplier, 4),
                "claiming_available": claiming_available,
            }
        )
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
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "suspended",
                        "message": "Your rewards are suspended",
                    }
                ),
                403,
            )

        # Use reward distributor to process claim
        distributor = get_distributor()

        # Check if rewards distribution is properly configured
        if not distributor.is_configured():
            log_event(rid, "rewards.claim.not_configured", owner=owner)
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "not_configured",
                        "message": "Reward distribution is not yet configured. Please try again later.",
                    }
                ),
                503,
            )  # Service Unavailable

        result = distributor.claim_rewards(owner, ts)

        if not result["success"]:
            error_msg = result.get("error", "unknown_error")
            if error_msg == "no_rewards":
                log_event(rid, "rewards.claim.empty", owner=owner)
                return jsonify(
                    {
                        "success": False,
                        "error": "no_rewards",
                        "message": "No pending rewards to claim",
                    }
                )
            elif error_msg == "insufficient_pool_balance":
                log_event(rid, "rewards.claim.insufficient_funds", owner=owner)
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "insufficient_funds",
                            "message": "Payout temporarily unavailable due to low funds in the rewards pool. Please notify the admins.",
                        }
                    ),
                    503,
                )  # Service Unavailable
            else:
                log_event(rid, "rewards.claim.failed", owner=owner, error=error_msg)
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": error_msg,
                            "message": f"Failed to claim rewards: {error_msg}",
                        }
                    ),
                    500,
                )

        log_event(
            rid,
            "rewards.claim.ok",
            owner=owner,
            reward_count=len(result.get("rewards", [])),
            tx_hash=result.get("tx_hash"),
        )
        return jsonify(
            {
                "success": True,
                "rewards": result.get("rewards", []),
                "tx_hash": result.get("tx_hash"),
            }
        )
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
                    (target, suspended_until, admin, reason, ts),
                )

        log_event(
            rid,
            "admin.suspend.ok",
            admin=admin,
            target=target,
            duration_days=duration_days,
            suspended_until=suspended_until,
        )
        return jsonify(
            {
                "success": True,
                "target": target,
                "suspended_until": suspended_until,
                "reason": reason,
            }
        )
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
                    (ts, target),
                )

                # Optionally void pending rewards
                if void_pending:
                    cur.execute(
                        """
                        DELETE FROM pending_rewards
                        WHERE LOWER(owner) = LOWER(%s) AND claimed_at IS NULL
                        """,
                        (target,),
                    )

        log_event(
            rid,
            "admin.unsuspend.ok",
            admin=admin,
            target=target,
            void_pending=void_pending,
        )
        return jsonify(
            {
                "success": True,
                "target": target,
                "void_pending": void_pending,
            }
        )
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
                    (ts,),
                )
                rows = cur.fetchall()

        suspensions = []
        for row in rows:
            suspensions.append(
                {
                    "owner": row[0],
                    "suspended_until": row[1],
                    "suspended_by": row[2],
                    "reason": row[3],
                    "updated_at": row[4],
                }
            )

        log_event(rid, "admin.suspensions.ok", count=len(suspensions))
        return jsonify({"suspensions": suspensions})
    except Exception as e:
        log_event(rid, "admin.suspensions.err", error=str(e))
        return jsonify({"error": str(e)}), 500


@quests_bp.route("/api/rewards/stats", methods=["GET"])
def reward_stats():
    """Get comprehensive reward statistics (public).

    Returns:
    - summary: Overall stats (total earned, claimed, pending, pool balance)
    - users: Per-user breakdown with earnings data
    """
    rid = next_request_id()
    log_event(rid, "rewards.stats.begin")

    try:
        ts = int(time.time())

        # Get pool balance
        distributor = get_distributor()
        pool_balance = distributor.get_pool_balance() if distributor.is_configured() else 0

        with connect_db() as conn:
            with conn.cursor() as cur:
                # Get overall stats
                # For claimed rewards, use payout_amount (actual amount with multiplier)
                # For pending rewards, use base amount from reward_data
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
                    "payouts_enabled": distributor.is_configured(),
                }

                # Calculate daily rate (last 7 days) - use actual payout amounts
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

                # Get per-user stats - use actual payout amounts for claimed rewards
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
                        earnings_per_day = total_earned  # Single day

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

        log_event(rid, "rewards.stats.ok", user_count=len(users))
        return jsonify(
            {
                "summary": summary,
                "users": users,
            }
        )
    except Exception as e:
        log_event(rid, "rewards.stats.err", error=str(e))
        return jsonify({"error": str(e)}), 500


@quests_bp.route("/api/rewards/history", methods=["GET"])
def reward_history():
    """Get paginated list of all rewards (public).

    Query params:
    - offset: Pagination offset (default 0)
    - limit: Number of items to return (default 50, max 100)

    Returns:
    - rewards: List of reward records
    - has_more: Whether there are more records
    """
    rid = next_request_id()
    log_event(rid, "rewards.history.begin")

    try:
        offset = int(request.args.get("offset", 0))
        limit = min(int(request.args.get("limit", 50)), 100)

        with connect_db() as conn:
            with conn.cursor() as cur:
                # Get all rewards with pagination (newest first)
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
                )  # Fetch one extra to check if there's more
                reward_rows = cur.fetchall()

                has_more = len(reward_rows) > limit
                if has_more:
                    reward_rows = reward_rows[:limit]

                rewards = []
                for row in reward_rows:
                    reward_data = row[3] if isinstance(row[3], dict) else {}
                    base_amount = reward_data.get("amount", 0)
                    payout_amount = row[7]  # Actual amount paid (with multiplier)
                    # Use payout_amount if claimed, otherwise base_amount
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

        log_event(rid, "rewards.history.ok", count=len(rewards), offset=offset)
        return jsonify(
            {
                "rewards": rewards,
                "has_more": has_more,
            }
        )
    except Exception as e:
        log_event(rid, "rewards.history.err", error=str(e))
        return jsonify({"error": str(e)}), 500
