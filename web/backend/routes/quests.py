from __future__ import annotations

"""Quest and Rewards API endpoints.

User endpoints:
- GET /api/rewards/summary: Daily quests, flash quest, and pending rewards in one call
- GET /api/rewards/achievements: Get all achievements with unlock status
- POST /api/rewards/claim: Claim pending rewards

Admin endpoints (require level >= 100):
- POST /api/admin/rewards/suspend: Suspend rewards for a user
- POST /api/admin/rewards/unsuspend: Unsuspend a user
- GET /api/admin/rewards/suspensions: List all suspended users

Note: Reward stats moved to GET /api/get_stats?tab=rewards
      Reward history moved to GET /api/get_stats?tab=rewards_history
"""

import hashlib
import ipaddress
import json
import os
import random
import time
from typing import Any, Dict, List, Optional

from flask import Blueprint, jsonify, request


def _get_balance(address) -> int:
    """Read balance from indexer DB."""
    if not address:
        return 0
    with connect_db(timeout=3.0, busy_timeout_ms=5000) as conn:
        cur = conn.cursor()
        cur.execute("SELECT balance FROM balances WHERE address = LOWER(%s)", (str(address),))
        row = cur.fetchone()
        return int(row[0]) if row and row[0] is not None else 0


from db import connect_backend_db, connect_db
from error_utils import api_error_code, safe_error
from logging_utils import log_event, next_request_id
from node import derive_address_from_pubkey, require_runtime
from quest_multiplier import get_reward_multiplier
from reward_distributor import get_distributor
from routes.core import get_user_level
from settings import QUESTS_ENABLED, require_bool_env
from user_last_seen import update_user_last_seen


def _inject_balance(resp: dict, addr: str) -> dict:
    """Add balance to response dict if address is provided."""
    if addr and addr.lower() != "guest":
        resp["balance"] = int(_get_balance(addr))
    return resp


quests_bp = Blueprint("quests", __name__)

# Backend debug switch
BACKEND_DEBUG = require_bool_env("BACKEND_DEBUG")

# Quest system configuration (from environment — crash if missing)
QUESTS_DAILY_COUNT = int(os.environ["QUESTS_DAILY_COUNT"])
QUESTS_FLASH_COUNT = int(os.environ["QUESTS_FLASH_COUNT"])
QUESTS_FLASH_MIN_INTERVAL_HOURS = int(os.environ["QUESTS_FLASH_MIN_INTERVAL_HOURS"])
QUESTS_FLASH_MAX_INTERVAL_HOURS = int(os.environ["QUESTS_FLASH_MAX_INTERVAL_HOURS"])

# Special quest gating
QUESTS_INVITE_RECRUIT_CHANCE = float(os.environ["QUESTS_INVITE_RECRUIT_CHANCE"])
QUESTS_INVITE_EARNER_INTERVAL = int(os.environ["QUESTS_INVITE_EARNER_INTERVAL"])
QUESTS_INVITE_EARNER_CHANCE = float(os.environ["QUESTS_INVITE_EARNER_CHANCE"])


def _get_utc_julian_day(ts: int) -> int:
    """Convert Unix timestamp to UTC Julian day number."""
    return 2440588 + (ts // 86400)


def _get_seconds_until_reset(ts: int) -> int:
    """Calculate seconds until next UTC midnight."""
    seconds_into_day = ts % 86400
    return 86400 - seconds_into_day


def _load_quest_definitions() -> Dict[str, Any]:
    """Load quest definitions from YAML file."""
    import yaml
    from pathlib import Path

    yaml_path = Path(__file__).resolve().parents[1] / "quests.yaml"
    if not yaml_path.exists():
        raise FileNotFoundError(f"quests.yaml not found at {yaml_path}")

    with yaml_path.open("r", encoding="utf-8") as f:
        defs = yaml.safe_load(f)

    if not isinstance(defs, dict):
        raise ValueError("quests.yaml must define a top-level mapping")
    return defs


def _get_user_reward_multiplier(owner: str) -> float:
    """Calculate reward multiplier based on completed quest count (1x at 0, 5x at 50)."""
    return get_reward_multiplier(owner)


def _is_user_suspended(owner: str, ts: int) -> bool:
    """Check if user's rewards are suspended."""
    with connect_backend_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT suspended_until FROM reward_suspensions WHERE LOWER(owner) = LOWER(%s)", (owner,))
            row = cur.fetchone()
            if not row:
                return False
            return row[0] > ts


def _get_next_flash_time(owner: str) -> int:
    """Get the timestamp when user can receive their next flash quest."""
    with connect_backend_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT next_flash_at FROM user_quest_state WHERE LOWER(owner) = LOWER(%s)", (owner,))
            row = cur.fetchone()
            return row[0] if row else 0


def _set_next_flash_time(owner: str, next_ts: int) -> None:
    """Set when the user can receive their next flash quest."""
    with connect_backend_db() as conn:
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
    if QUESTS_FLASH_COUNT <= 0:
        return None

    # Check if user already has the max number of active flash quests
    with connect_backend_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(1)
                FROM user_flash_quests
                WHERE LOWER(owner) = LOWER(%s) AND ends_at > %s
                """,
                (owner, ts),
            )
            active_count = int((cur.fetchone() or [0])[0] or 0)
            if active_count >= QUESTS_FLASH_COUNT:
                return None  # Already has max active quests

    # Check if enough time has passed since last flash quest
    next_flash_at = _get_next_flash_time(owner)

    # New user check: if no next_flash_at record exists (returns 0),
    # initialize it with minimum interval delay so new users don't get flash quests immediately
    if next_flash_at == 0:
        initial_delay = QUESTS_FLASH_MIN_INTERVAL_HOURS * 3600
        _set_next_flash_time(owner, ts + initial_delay)
        return None

    if ts < next_flash_at:
        return None

    # Select a random flash quest template
    template_id = random.choice(list(flash_defs.keys()))
    template = flash_defs[template_id]

    # Calculate duration based on time_window_minutes (default 60 min)
    duration_seconds = (template.get("time_window_minutes") or 60) * 60
    ends_at = ts + duration_seconds

    # Insert the flash quest
    with connect_backend_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO user_flash_quests (owner, template_id, starts_at, ends_at, progress, progress_meta)
                VALUES (%s, %s, %s, %s, 0, '{}')
                """,
                (owner, template_id, ts, ends_at),
            )

    # Schedule next flash quest (random interval between MIN and MAX hours)
    next_interval_seconds = random.randint(
        QUESTS_FLASH_MIN_INTERVAL_HOURS * 3600, QUESTS_FLASH_MAX_INTERVAL_HOURS * 3600
    )
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
    with connect_backend_db() as conn:
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
    with connect_backend_db() as conn:
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
    """Get total number of completed quests/achievements for a user (daily + flash + achievements)."""
    with connect_backend_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM user_daily_quests WHERE LOWER(owner) = LOWER(%s) AND completed_at IS NOT NULL)
                  + (SELECT COUNT(*) FROM user_flash_quests WHERE LOWER(owner) = LOWER(%s) AND completed_at IS NOT NULL)
                  + (SELECT COUNT(*) FROM user_achievements WHERE LOWER(owner) = LOWER(%s) AND unlocked_at IS NOT NULL)
                """,
                (owner, owner, owner),
            )
            row = cur.fetchone()
            return row[0] if row else 0


def _get_invite_earner_completed_count(owner: str) -> int:
    """Get total number of completed invite_earner quests for a user.

    Counts claimed invite_code rewards from invite_earner quests, which is more
    reliable than counting quest completions (which can be reset via debug panel).
    """
    with connect_backend_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) FROM pending_rewards
                WHERE LOWER(owner) = LOWER(%s) AND reason = 'quest:invite_earner' AND claimed_at IS NOT NULL
                """,
                (owner,),
            )
            row = cur.fetchone()
            return row[0] if row else 0


def _is_invite_earner_eligible(owner: str, day_utc: int) -> bool:
    """Check if user is eligible for invite_earner quest.

    User is eligible if:
    1. completed_count >= (invite_earner_completed + 1) * interval
    2. 30% daily roll passes
    """
    completed_count = _get_completed_quest_count(owner)
    invite_earner_completed = _get_invite_earner_completed_count(owner)
    next_milestone = (invite_earner_completed + 1) * QUESTS_INVITE_EARNER_INTERVAL

    if completed_count < next_milestone:
        return False

    # 30% daily roll
    roll = _deterministic_roll(owner, day_utc, "invite_earner")
    return roll < QUESTS_INVITE_EARNER_CHANCE


def _deterministic_roll(owner: str, day_utc: int, roll_type: str) -> float:
    """Generate a deterministic random value (0-1) based on owner, day, and roll type."""
    seed_str = f"{owner.lower()}:{day_utc}:{roll_type}"
    seed_hash = hashlib.sha256(seed_str.encode()).hexdigest()
    # Use first 8 hex chars as seed (32 bits)
    seed_int = int(seed_hash[:8], 16)
    rng = random.Random(seed_int)
    return rng.random()


def _assign_daily_quests_if_needed(
    owner: str,
    day_utc: int,
    ts: int,
    daily_defs: Dict[str, Any],
    special_defs: Dict[str, Any] = None,
    use_random_rolls: bool = False,
) -> List[str]:
    """Assign daily quests to a user if they don't have any for today.

    Includes special quest gating logic:
    - invite_recruit: 30% chance if user has unused invite codes
    - invite_earner: appears every N completed quests + 30% roll

    Args:
        use_random_rolls: If True, use random.random() instead of deterministic rolls (for localhost testing)

    Returns the list of assigned quest IDs.
    """
    if special_defs is None:
        special_defs = {}

    def get_roll(roll_type: str) -> float:
        """Get roll value - random on localhost, deterministic in production."""
        if use_random_rolls:
            return random.random()
        return _deterministic_roll(owner, day_utc, roll_type)

    with connect_backend_db() as conn:
        with conn.cursor() as cur:
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

    quest_ids = []
    special_quest_assigned = False

    if not special_quest_assigned and "invite_recruit" in special_defs:
        if _has_unused_invite_codes(owner):
            roll = get_roll("invite_recruit")
            log_event(
                None,
                "quest.invite_recruit.roll",
                owner=owner,
                roll=round(roll, 3),
                threshold=QUESTS_INVITE_RECRUIT_CHANCE,
            )
            if roll < QUESTS_INVITE_RECRUIT_CHANCE:
                quest_ids.append("invite_recruit")
                special_quest_assigned = True
                log_event(None, "quest.invite_recruit.assigned", owner=owner)

    if not special_quest_assigned and "invite_earner" in special_defs:
        completed_count = _get_completed_quest_count(owner)
        invite_earner_completed = _get_invite_earner_completed_count(owner)
        next_milestone = (invite_earner_completed + 1) * QUESTS_INVITE_EARNER_INTERVAL
        if completed_count >= next_milestone:
            roll = get_roll("invite_earner")
            log_event(
                None,
                "quest.invite_earner.roll",
                owner=owner,
                roll=round(roll, 3),
                threshold=QUESTS_INVITE_EARNER_CHANCE,
            )
            if roll < QUESTS_INVITE_EARNER_CHANCE:
                quest_ids.append("invite_earner")
                special_quest_assigned = True
                log_event(None, "quest.invite_earner.assigned", owner=owner, completed_count=completed_count)

    if not daily_defs:
        return quest_ids

    remaining_slots = QUESTS_DAILY_COUNT - len(quest_ids)
    if remaining_slots > 0:
        available_ids = list(daily_defs.keys())
        count = min(remaining_slots, len(available_ids))
        selected_ids = random.sample(available_ids, count)
        quest_ids.extend(selected_ids)

    with connect_backend_db() as conn:
        with conn.cursor() as cur:
            for quest_id in quest_ids:
                cur.execute(
                    """
                    INSERT INTO user_daily_quests (owner, day_utc, quest_id, progress, progress_meta)
                    VALUES (%s, %s, %s, 0, '{}')
                    ON CONFLICT (owner, day_utc, quest_id) DO NOTHING
                    """,
                    (owner, day_utc, quest_id),
                )

    min_flash_at = ts + 3600
    next_flash = _get_next_flash_time(owner)
    if next_flash < min_flash_at:
        _set_next_flash_time(owner, min_flash_at)
        log_event(None, "quest.flash_delayed", owner=owner, min_flash_at=min_flash_at)

    return quest_ids


@quests_bp.route("/api/rewards/summary", methods=["GET"])
def get_rewards_summary():
    """Combined endpoint: daily quests + flash quest + pending rewards in one call.

    Query params:
    - owner: User address (required)
    """
    rid = next_request_id()
    log_event(rid, "rewards.summary.begin")

    # -- disabled check --
    if not QUESTS_ENABLED:
        return jsonify(
            {
                "disabled": True,
                "daily_quests": [],
                "flash_quest": None,
                "pending_rewards": [],
                "seconds_until_reset": 0,
                "reward_multiplier": 1,
                "total_mirage": 0,
                "total_mirage_after_multiplier": 0,
                "pending_invite_codes": 0,
                "claiming_available": False,
                "debug": BACKEND_DEBUG,
            }
        )

    try:
        owner = (request.args.get("owner") or "").strip().lower()
        if not owner:
            return jsonify({"error": "owner required"}), 400

        ts = int(time.time())
        day_utc = _get_utc_julian_day(ts)

        # -- suspension check (shared across all sections) --
        if _is_user_suspended(owner, ts):
            suspension = _get_suspension_info(owner)
            return jsonify(
                {
                    "suspended": True,
                    "suspension": suspension,
                    "daily_quests": [],
                    "flash_quest": None,
                    "pending_rewards": [],
                    "seconds_until_reset": _get_seconds_until_reset(ts),
                    "reward_multiplier": 1.0,
                    "total_mirage": 0,
                    "total_mirage_after_multiplier": 0,
                    "pending_invite_codes": 0,
                    "claiming_available": False,
                    "debug": BACKEND_DEBUG,
                }
            )

        # -- load quest definitions once --
        defs = _load_quest_definitions()
        daily_defs = {q["id"]: q for q in defs.get("daily_quests", [])}
        special_defs = {q["id"]: q for q in defs.get("special_quests", [])}
        flash_defs = {q["id"]: q for q in defs.get("flash_quest_templates", [])}
        all_defs = {**daily_defs, **special_defs}

        # ===== DAILY QUESTS =====
        _assign_daily_quests_if_needed(owner, day_utc, ts, daily_defs, special_defs, use_random_rolls=_is_localhost())

        with connect_backend_db() as conn:
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
                daily_rows = cur.fetchall()

        daily_quests = []
        for row in daily_rows:
            quest_id = row[0]
            progress = row[1]
            progress_meta = row[2] if isinstance(row[2], dict) else {}
            completed_at = row[3]
            quest_def = all_defs.get(quest_id, {})
            if not quest_def:
                continue
            quest_data = {
                "id": quest_id,
                "title": quest_def.get("title", ""),
                "description": quest_def.get("description", ""),
                "action_type": quest_def.get("action_type", ""),
                "progress": progress,
                "completed": completed_at is not None,
                "rewards": quest_def.get("rewards", []),
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
                quest_data["upvotes"] = progress_meta.get("upvotes", 0)
                quest_data["downvotes"] = progress_meta.get("downvotes", 0)
                quest_data["target_upvotes"] = target_up
                quest_data["target_downvotes"] = target_down
            else:
                quest_data["target"] = quest_def.get("target_count", 1)
            daily_quests.append(quest_data)

        # ===== FLASH QUEST =====
        flash_quest_data = None
        with connect_backend_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT template_id, starts_at, ends_at, progress, progress_meta, completed_at
                    FROM user_flash_quests
                    WHERE LOWER(owner) = LOWER(%s) AND ends_at > %s
                    ORDER BY starts_at DESC
                    LIMIT 1
                    """,
                    (owner, ts),
                )
                flash_row = cur.fetchone()

        if not flash_row:
            assigned = _maybe_assign_flash_quest(owner, ts, flash_defs)
            if assigned:
                with connect_backend_db() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            SELECT template_id, starts_at, ends_at, progress, progress_meta, completed_at
                            FROM user_flash_quests
                            WHERE LOWER(owner) = LOWER(%s) AND ends_at > %s
                            ORDER BY starts_at DESC
                            LIMIT 1
                            """,
                            (owner, ts),
                        )
                        flash_row = cur.fetchone()

        if flash_row:
            template_id = flash_row[0]
            quest_def = flash_defs.get(template_id, {})
            if quest_def:
                flash_quest_data = {
                    "id": template_id,
                    "title": quest_def.get("title", ""),
                    "description": quest_def.get("description", ""),
                    "action_type": quest_def.get("action_type", ""),
                    "progress": flash_row[3],
                    "target": quest_def.get("target_count", 1),
                    "completed": flash_row[5] is not None,
                    "starts_at": flash_row[1],
                    "ends_at": flash_row[2],
                    "seconds_remaining": max(0, flash_row[2] - ts),
                    "rewards": quest_def.get("rewards", []),
                    "min_content_length": quest_def.get("min_content_length"),
                    "time_spacing_minutes": quest_def.get("time_spacing_minutes"),
                    "unique_target": quest_def.get("unique_target"),
                    "unique_topics_min": quest_def.get("unique_topics_min"),
                    "quality_threshold": quest_def.get("quality_threshold"),
                    "count_vote_changes": quest_def.get("count_vote_changes", True),
                }

        # ===== PENDING REWARDS =====
        with connect_backend_db() as conn:
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
                reward_rows = cur.fetchall()

        pending_rewards = []
        total_mirage_with_multiplier = 0
        total_mirage_no_multiplier = 0
        pending_invite_codes = 0

        for row in reward_rows:
            reward_data = row[2] if isinstance(row[2], dict) else {}
            pending_rewards.append(
                {
                    "id": row[0],
                    "type": row[1],
                    "data": reward_data,
                    "reason": row[3],
                    "created_at": row[4],
                }
            )
            if row[1] == "mirage":
                amount = reward_data.get("amount", 0)
                apply_multiplier = reward_data.get("apply_multiplier", True)
                if apply_multiplier:
                    total_mirage_with_multiplier += amount
                else:
                    total_mirage_no_multiplier += amount
            elif row[1] == "invite_code":
                pending_invite_codes += reward_data.get("amount", 1)

        # -- shared multiplier --
        multiplier = _get_user_reward_multiplier(owner)
        total_mirage = total_mirage_with_multiplier + total_mirage_no_multiplier
        total_mirage_after_multiplier = int(total_mirage_with_multiplier * multiplier) + total_mirage_no_multiplier

        distributor = get_distributor()
        claiming_available = distributor.is_configured()

        log_event(
            rid,
            "rewards.summary.ok",
            owner=owner,
            daily=len(daily_quests),
            flash=flash_quest_data is not None,
            pending=len(pending_rewards),
        )
        resp = {
            "suspended": False,
            "daily_quests": daily_quests,
            "flash_quest": flash_quest_data,
            "pending_rewards": pending_rewards,
            "seconds_until_reset": _get_seconds_until_reset(ts),
            "reward_multiplier": round(multiplier, 4),
            "total_mirage": total_mirage,
            "total_mirage_after_multiplier": total_mirage_after_multiplier,
            "pending_invite_codes": pending_invite_codes,
            "claiming_available": claiming_available,
            "debug": BACKEND_DEBUG,
        }
        return jsonify(_inject_balance(resp, owner))
    except Exception as e:
        log_event(rid, "rewards.summary.err", error=str(e))
        return safe_error(e)


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
        with connect_backend_db() as conn:
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
                    "rewards": achievement_def.get("rewards", []),
                }
            )

        log_event(rid, "achievements.ok", owner=owner, count=len(achievements))
        resp = {"achievements": achievements}
        return jsonify(_inject_balance(resp, owner))
    except Exception as e:
        log_event(rid, "achievements.err", error=str(e))
        return safe_error(e)


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
        update_user_last_seen(owner, source=request.path)

        ts = int(time.time())

        # Check if suspended
        if _is_user_suspended(owner, ts):
            return api_error_code("suspended", 403, success=False)

        # Use reward distributor to process claim
        distributor = get_distributor()

        # Check if rewards distribution is properly configured
        if not distributor.is_configured():
            log_event(rid, "rewards.claim.not_configured", owner=owner)
            return api_error_code("not_configured", 503, success=False)

        result = distributor.claim_rewards(owner, ts)

        if not result["success"]:
            error_msg = result.get("error", "unknown_error")
            if error_msg == "no_rewards":
                log_event(rid, "rewards.claim.empty", owner=owner)
                return api_error_code("no_rewards", 200, success=False)
            elif error_msg == "insufficient_pool_balance":
                log_event(rid, "rewards.claim.insufficient_funds", owner=owner)
                return api_error_code("insufficient_funds", 503, success=False)
            elif error_msg == "rewards_pool_key_not_configured":
                log_event(rid, "rewards.claim.pool_not_configured", owner=owner)
                return api_error_code("pool_not_configured", 503, success=False)
            elif error_msg == "sequence_mismatch_retry":
                log_event(rid, "rewards.claim.sequence_mismatch", owner=owner)
                return api_error_code("retry", 503, success=False)
            elif error_msg == "payout_transaction_failed":
                log_event(rid, "rewards.claim.tx_failed", owner=owner)
                return api_error_code("payout_failed", 503, success=False)
            else:
                log_event(rid, "rewards.claim.failed", owner=owner, error=error_msg)
                return api_error_code("internal_error", 500, success=False)

        log_event(
            rid,
            "rewards.claim.ok",
            owner=owner,
            reward_count=len(result.get("rewards", [])),
            tx_hash=result.get("tx_hash"),
        )
        resp = {
            "success": True,
            "rewards": result.get("rewards", []),
            "tx_hash": result.get("tx_hash"),
        }
        return jsonify(_inject_balance(resp, owner))
    except Exception as e:
        log_event(rid, "rewards.claim.err", error=str(e))
        return safe_error(e)


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
        update_user_last_seen(admin, source=request.path)

        # Check admin level
        admin_level = get_user_level(admin)
        if admin_level < 100:
            return api_error_code("unauthorized", 403)

        ts = int(time.time())

        # Calculate suspended_until
        if duration_days == 0:
            # Permanent suspension (set to year 2100)
            suspended_until = 4102444800  # Jan 1, 2100
        else:
            suspended_until = ts + (duration_days * 86400)

        # Upsert suspension
        with connect_backend_db() as conn:
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
        return safe_error(e)


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
        update_user_last_seen(admin, source=request.path)

        # Check admin level
        admin_level = get_user_level(admin)
        if admin_level < 100:
            return api_error_code("unauthorized", 403)

        ts = int(time.time())

        # Remove suspension (set suspended_until to 0)
        with connect_backend_db() as conn:
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
        return safe_error(e)


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
        update_user_last_seen(admin, source=request.path)

        # Check admin level
        admin_level = get_user_level(admin)
        if admin_level < 100:
            return api_error_code("unauthorized", 403)

        ts = int(time.time())

        # Get all active suspensions
        with connect_backend_db() as conn:
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
        return safe_error(e)


# ==================== Debug Endpoints (localhost only) ====================


def _is_private_or_loopback_ip(ip: str) -> bool:
    try:
        parsed = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return parsed.is_private or parsed.is_loopback


def _is_debug_enabled() -> bool:
    return BACKEND_DEBUG and _is_localhost()


def _is_localhost() -> bool:
    """Check if request is from localhost/private network."""
    remote_ip = request.remote_addr or ""
    forwarded_for = request.headers.get("X-Forwarded-For", "")
    if forwarded_for:
        forwarded_ips = [ip.strip() for ip in forwarded_for.split(",") if ip.strip()]
        if not forwarded_ips:
            return False
        if any(not _is_private_or_loopback_ip(ip) for ip in forwarded_ips):
            return False
    return _is_private_or_loopback_ip(remote_ip)


@quests_bp.route("/api/rewards/debug", methods=["GET"])
def debug_quests_info():
    """Get quest debug info for a user. Localhost only.

    Query params:
    - owner: User address (required)
    """
    if not _is_debug_enabled():
        return jsonify({"error": "debug endpoints only available on localhost"}), 403

    rid = next_request_id()
    log_event(rid, "debug.quests.info.begin")

    try:
        owner = (request.args.get("owner") or "").strip().lower()
        if not owner:
            return jsonify({"error": "owner required"}), 400

        ts = int(time.time())
        day_utc = _get_utc_julian_day(ts)

        with connect_backend_db() as conn:
            with conn.cursor() as cur:
                # Get total completed quests count
                cur.execute(
                    """
                    SELECT COUNT(*) FROM user_daily_quests
                    WHERE LOWER(owner) = LOWER(%s) AND completed_at IS NOT NULL
                    """,
                    (owner,),
                )
                completed_count = cur.fetchone()[0] or 0

                # Get today's quests
                cur.execute(
                    """
                    SELECT quest_id, progress, completed_at FROM user_daily_quests
                    WHERE LOWER(owner) = LOWER(%s) AND day_utc = %s
                    """,
                    (owner, day_utc),
                )
                today_quests = [
                    {"quest_id": row[0], "progress": row[1], "completed": row[2] is not None} for row in cur.fetchall()
                ]

                # Check invite_recruit eligibility
                cur.execute(
                    """
                    SELECT COUNT(*) FROM invite_codes
                    WHERE LOWER(owner) = LOWER(%s) AND used_by IS NULL
                    """,
                    (owner,),
                )
                unused_invite_codes = cur.fetchone()[0] or 0

                # Check invite_recruit - just show if prerequisites are met (has unused codes)
                invite_recruit_has_codes = unused_invite_codes > 0
                invite_recruit_assigned = any(q["quest_id"] == "invite_recruit" for q in today_quests)

                # Check invite_earner eligibility (milestone-based)
                # Count claimed invite_code rewards (more reliable than quest completions)
                cur.execute(
                    """
                    SELECT COUNT(*) FROM pending_rewards
                    WHERE LOWER(owner) = LOWER(%s) AND reason = 'quest:invite_earner' AND claimed_at IS NOT NULL
                    """,
                    (owner,),
                )
                invite_earner_completed = cur.fetchone()[0] or 0
                invite_earner_next_milestone = (invite_earner_completed + 1) * QUESTS_INVITE_EARNER_INTERVAL
                invite_earner_milestone_reached = completed_count >= invite_earner_next_milestone
                invite_earner_assigned = any(q["quest_id"] == "invite_earner" for q in today_quests)

        log_event(rid, "debug.quests.info.ok", owner=owner)
        return jsonify(
            {
                "owner": owner,
                "day_utc": day_utc,
                "completed_count": completed_count,
                "today_quests": today_quests,
                "unused_invite_codes": unused_invite_codes,
                "invite_recruit": {
                    "has_codes": invite_recruit_has_codes,
                    "chance": f"{int(QUESTS_INVITE_RECRUIT_CHANCE * 100)}%",
                    "assigned": invite_recruit_assigned,
                },
                "invite_earner": {
                    "interval": QUESTS_INVITE_EARNER_INTERVAL,
                    "completed": invite_earner_completed,
                    "next_milestone": invite_earner_next_milestone,
                    "milestone_reached": invite_earner_milestone_reached,
                    "chance": f"{int(QUESTS_INVITE_EARNER_CHANCE * 100)}%",
                    "assigned": invite_earner_assigned,
                },
            }
        )
    except Exception as e:
        log_event(rid, "debug.quests.info.err", error=str(e))
        return safe_error(e)


@quests_bp.route("/api/rewards/debug/complete", methods=["POST"])
def debug_complete_quest():
    """Instantly complete a quest. Localhost only.

    Body:
    - owner: User address (required)
    - quest_id: Quest ID to complete (required)
    """
    if not _is_debug_enabled():
        return jsonify({"error": "debug endpoints only available on localhost"}), 403

    rid = next_request_id()
    log_event(rid, "debug.quests.complete.begin")

    try:
        data = request.get_json(force=True) or {}
        owner = str(data.get("owner", "")).strip().lower()
        quest_id = str(data.get("quest_id", "")).strip()

        if not owner:
            return jsonify({"error": "owner required"}), 400
        if not quest_id:
            return jsonify({"error": "quest_id required"}), 400

        ts = int(time.time())
        day_utc = _get_utc_julian_day(ts)

        # Load quest definitions to get reward info
        defs = _load_quest_definitions()
        daily_defs = {q["id"]: q for q in defs.get("daily_quests", [])}
        special_defs = {q["id"]: q for q in defs.get("special_quests", [])}
        all_defs = {**daily_defs, **special_defs}

        quest_def = all_defs.get(quest_id)
        if not quest_def:
            return jsonify({"error": "unknown quest_id", "quest_id": quest_id}), 400

        with connect_backend_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT completed_at FROM user_daily_quests
                    WHERE LOWER(owner) = LOWER(%s) AND day_utc = %s AND quest_id = %s
                    """,
                    (owner, day_utc, quest_id),
                )
                row = cur.fetchone()

                if not row:
                    return jsonify({"error": "quest not assigned", "quest_id": quest_id}), 400

                if row[0] is not None:
                    return jsonify({"error": "quest already completed", "quest_id": quest_id}), 400

        target = quest_def.get("target_count", 1)
        rewards = quest_def.get("rewards", [])
        with connect_backend_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE user_daily_quests
                    SET progress = %s, completed_at = %s
                    WHERE LOWER(owner) = LOWER(%s) AND day_utc = %s AND quest_id = %s
                    """,
                    (target, ts, owner, day_utc, quest_id),
                )

                for reward in rewards:
                    reward_type = reward.get("type", "mirage")
                    if reward_type == "mirage":
                        amount_umirage = reward.get("amount", 0) * 1_000_000
                        apply_multiplier = reward.get("apply_multiplier", True)
                        reward_data = {"amount": amount_umirage, "apply_multiplier": apply_multiplier}
                    elif reward_type == "invite_code":
                        reward_data = {"amount": reward.get("amount", 1)}
                    else:
                        reward_data = {"id": reward.get("id")}

                    cur.execute(
                        """
                        INSERT INTO pending_rewards (owner, reward_type, reward_data, reason, created_at)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (owner, reward_type, json.dumps(reward_data), f"quest:{quest_id}", ts),
                    )

        log_event(rid, "debug.quests.complete.ok", owner=owner, quest_id=quest_id)
        return jsonify({"success": True, "quest_id": quest_id})
    except Exception as e:
        log_event(rid, "debug.quests.complete.err", error=str(e))
        return safe_error(e)


@quests_bp.route("/api/rewards/debug/reset", methods=["POST"])
def debug_reset_quests():
    """Reset today's quests for a user. Localhost only.

    Body:
    - owner: User address (required)
    """
    if not _is_debug_enabled():
        return jsonify({"error": "debug endpoints only available on localhost"}), 403

    rid = next_request_id()
    log_event(rid, "debug.quests.reset.begin")

    try:
        data = request.get_json(force=True) or {}
        owner = str(data.get("owner", "")).strip().lower()

        if not owner:
            return jsonify({"error": "owner required"}), 400
        update_user_last_seen(owner, source=request.path)

        ts = int(time.time())
        day_utc = _get_utc_julian_day(ts)

        with connect_backend_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM user_daily_quests
                    WHERE LOWER(owner) = LOWER(%s) AND day_utc = %s
                    """,
                    (owner, day_utc),
                )
                deleted_count = cur.rowcount

        log_event(rid, "debug.quests.reset.ok", owner=owner, deleted=deleted_count)
        return jsonify({"success": True, "deleted_count": deleted_count})
    except Exception as e:
        log_event(rid, "debug.quests.reset.err", error=str(e))
        return safe_error(e)


@quests_bp.route("/api/rewards/debug/set_completed", methods=["POST"])
def debug_set_completed_count():
    """Set the completed quest count by adding fake completed quests. Localhost only.

    Body:
    - owner: User address (required)
    - count: Target completed count (required)
    """
    if not _is_debug_enabled():
        return jsonify({"error": "debug endpoints only available on localhost"}), 403

    rid = next_request_id()
    log_event(rid, "debug.quests.set_completed.begin")

    try:
        data = request.get_json(force=True) or {}
        owner = str(data.get("owner", "")).strip().lower()
        target_count = int(data.get("count", 0))

        if not owner:
            return jsonify({"error": "owner required"}), 400
        if target_count < 0:
            return jsonify({"error": "count must be >= 0"}), 400

        ts = int(time.time())

        with connect_backend_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COUNT(*) FROM user_daily_quests
                    WHERE LOWER(owner) = LOWER(%s) AND completed_at IS NOT NULL
                    """,
                    (owner,),
                )
                current_count = cur.fetchone()[0] or 0

        if target_count > current_count:
            to_add = target_count - current_count
            with connect_backend_db() as conn:
                with conn.cursor() as cur:
                    for i in range(to_add):
                        fake_day = -(i + 1 + current_count)
                        cur.execute(
                            """
                            INSERT INTO user_daily_quests (owner, day_utc, quest_id, progress, progress_meta, completed_at)
                            VALUES (%s, %s, %s, 1, '{}', %s)
                            ON CONFLICT (owner, day_utc, quest_id) DO NOTHING
                            """,
                            (owner, fake_day, "debug_fake_quest", ts),
                        )
        elif target_count < current_count:
            with connect_backend_db() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        DELETE FROM user_daily_quests
                        WHERE LOWER(owner) = LOWER(%s) AND day_utc < 0
                        """,
                        (owner,),
                    )

        # Get new count
        with connect_backend_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COUNT(*) FROM user_daily_quests
                    WHERE LOWER(owner) = LOWER(%s) AND completed_at IS NOT NULL
                    """,
                    (owner,),
                )
                new_count = cur.fetchone()[0] or 0

        log_event(rid, "debug.quests.set_completed.ok", owner=owner, old=current_count, new=new_count)
        return jsonify({"success": True, "old_count": current_count, "new_count": new_count})
    except Exception as e:
        log_event(rid, "debug.quests.set_completed.err", error=str(e))
        return safe_error(e)
