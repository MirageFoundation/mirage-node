"""Daily and flash quest assignment.

The route path and the post/vote action path both need to hand a user their
quests for the day. They used to do it with two separate implementations, each
reading, deciding and inserting over several autocommit connections, so two
concurrent first requests could each assign a full set and leave the user above
the configured cap. Assignment now happens here, once, inside a single
transaction guarded by a per-owner advisory lock.

Progress tracking stays in `quest_tracker.py`; only assignment lives here.
"""

from __future__ import annotations

import hashlib
import random
from contextlib import contextmanager
from typing import Any, Dict, List, Optional

from db import connect_backend_db
from logging_utils import log_event
from settings import (
    QUESTS_DAILY_COUNT,
    QUESTS_FLASH_COUNT,
    QUESTS_FLASH_MAX_INTERVAL_HOURS,
    QUESTS_FLASH_MIN_INTERVAL_HOURS,
    QUESTS_INVITE_EARNER_CHANCE,
    QUESTS_INVITE_EARNER_INTERVAL,
    QUESTS_INVITE_RECRUIT_CHANCE,
)

# Flash quests may not start until an hour after the day's first assignment.
FLASH_INITIAL_DELAY_SECONDS = 3600


@contextmanager
def _locked_transaction(lock_key: str):
    """Run one backend transaction while holding a per-owner advisory lock.

    `pg_advisory_xact_lock` releases at commit or rollback, so the lock cannot
    outlive the work it guards. The db helper hands out autocommit connections,
    which have no transaction to attach the lock to.
    """
    with connect_backend_db() as conn:
        conn.autocommit = False
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (lock_key,))
                yield cur
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.autocommit = True


def deterministic_roll(owner: str, day_utc: int, roll_type: str) -> float:
    """Stable per (owner, day, roll_type) value in [0, 1).

    Stable so a user cannot re-roll a special quest by reloading.
    """
    seed_str = f"{owner.lower()}:{day_utc}:{roll_type}"
    seed_int = int(hashlib.sha256(seed_str.encode()).hexdigest()[:8], 16)
    return random.Random(seed_int).random()


def _assigned_quest_ids(cur, owner: str, day_utc: int) -> List[str]:
    cur.execute(
        """
        SELECT DISTINCT quest_id FROM user_daily_quests
        WHERE LOWER(owner) = LOWER(%s) AND day_utc = %s
        ORDER BY quest_id ASC
        """,
        (owner, day_utc),
    )
    return [row[0] for row in cur.fetchall()]


def _has_unused_invite_codes(cur, owner: str) -> bool:
    cur.execute(
        "SELECT 1 FROM invite_codes WHERE LOWER(owner) = LOWER(%s) AND used_by IS NULL LIMIT 1",
        (owner,),
    )
    return cur.fetchone() is not None


def _completed_quest_count(cur, owner: str) -> int:
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
    return int(row[0]) if row else 0


def _invite_earner_completed_count(cur, owner: str) -> int:
    """Claimed invite_earner rewards, which the debug panel's quest reset cannot alter."""
    cur.execute(
        """
        SELECT COUNT(*) FROM pending_rewards
        WHERE LOWER(owner) = LOWER(%s) AND reason = 'quest:invite_earner' AND claimed_at IS NOT NULL
        """,
        (owner,),
    )
    row = cur.fetchone()
    return int(row[0]) if row else 0


def _get_next_flash_at(cur, owner: str) -> int:
    cur.execute("SELECT next_flash_at FROM user_quest_state WHERE LOWER(owner) = LOWER(%s)", (owner,))
    row = cur.fetchone()
    return int(row[0]) if row else 0


def _set_next_flash_at(cur, owner: str, next_ts: int) -> None:
    cur.execute(
        """
        INSERT INTO user_quest_state (owner, next_flash_at)
        VALUES (%s, %s)
        ON CONFLICT (owner) DO UPDATE SET next_flash_at = EXCLUDED.next_flash_at
        """,
        (owner, next_ts),
    )


def _choose_special_quest(
    cur,
    owner: str,
    day_utc: int,
    special_defs: Dict[str, Any],
    use_random_rolls: bool,
) -> Optional[str]:
    def roll(roll_type: str) -> float:
        return random.random() if use_random_rolls else deterministic_roll(owner, day_utc, roll_type)

    if "invite_recruit" in special_defs and _has_unused_invite_codes(cur, owner):
        value = roll("invite_recruit")
        log_event(
            None,
            "quest.invite_recruit.roll",
            owner=owner,
            roll=round(value, 3),
            threshold=QUESTS_INVITE_RECRUIT_CHANCE,
        )
        if value < QUESTS_INVITE_RECRUIT_CHANCE:
            log_event(None, "quest.invite_recruit.assigned", owner=owner)
            return "invite_recruit"

    if "invite_earner" in special_defs:
        completed = _completed_quest_count(cur, owner)
        milestone = (_invite_earner_completed_count(cur, owner) + 1) * QUESTS_INVITE_EARNER_INTERVAL
        if completed >= milestone:
            value = roll("invite_earner")
            log_event(
                None,
                "quest.invite_earner.roll",
                owner=owner,
                roll=round(value, 3),
                threshold=QUESTS_INVITE_EARNER_CHANCE,
            )
            if value < QUESTS_INVITE_EARNER_CHANCE:
                log_event(None, "quest.invite_earner.assigned", owner=owner, completed_count=completed)
                return "invite_earner"

    return None


def assign_daily_quests_if_needed(
    owner: str,
    day_utc: int,
    ts: int,
    daily_defs: Dict[str, Any],
    special_defs: Optional[Dict[str, Any]] = None,
    use_random_rolls: bool = False,
) -> List[str]:
    """Return the user's quest IDs for `day_utc`, assigning them once if absent.

    `use_random_rolls` exists so local testing can re-roll special quests; in
    production the roll is deterministic per (owner, day).
    """
    owner_lc = (owner or "").strip().lower()
    if not owner_lc:
        raise ValueError("assign_daily_quests_if_needed requires an owner")
    special_defs = special_defs or {}

    # Daily assignment also initializes the flash cooldown, so both assignment
    # paths must share one owner lock or a first flash request can race past it.
    with _locked_transaction(f"quest_assignment:{owner_lc}") as cur:
        existing = _assigned_quest_ids(cur, owner_lc, day_utc)
        if existing:
            log_event(None, "quest.daily.reuse", owner=owner_lc, day=day_utc, count=len(existing))
            return existing

        quest_ids: List[str] = []
        special_id = _choose_special_quest(cur, owner_lc, day_utc, special_defs, use_random_rolls)
        if special_id:
            quest_ids.append(special_id)

        remaining = QUESTS_DAILY_COUNT - len(quest_ids)
        available = [qid for qid in daily_defs if qid not in quest_ids]
        if remaining > 0 and available:
            quest_ids.extend(random.sample(available, min(remaining, len(available))))

        for quest_id in quest_ids:
            cur.execute(
                """
                INSERT INTO user_daily_quests (owner, day_utc, quest_id, progress, progress_meta)
                VALUES (%s, %s, %s, 0, '{}')
                ON CONFLICT (owner, day_utc, quest_id) DO NOTHING
                """,
                (owner_lc, day_utc, quest_id),
            )

        committed = _assigned_quest_ids(cur, owner_lc, day_utc)
        if len(committed) > QUESTS_DAILY_COUNT:
            raise RuntimeError(
                f"daily quest cap exceeded for {owner_lc} on day {day_utc}: "
                f"{len(committed)} assigned, cap {QUESTS_DAILY_COUNT}"
            )

        min_flash_at = ts + FLASH_INITIAL_DELAY_SECONDS
        if _get_next_flash_at(cur, owner_lc) < min_flash_at:
            _set_next_flash_at(cur, owner_lc, min_flash_at)
            log_event(None, "quest.flash_delayed", owner=owner_lc, min_flash_at=min_flash_at)

        log_event(None, "quest.daily.assigned", owner=owner_lc, day=day_utc, quests=",".join(committed))
        return committed


def assign_flash_quest_if_eligible(owner: str, ts: int, flash_defs: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Assign one flash quest if the cap and cooldown allow it."""
    owner_lc = (owner or "").strip().lower()
    if not owner_lc:
        raise ValueError("assign_flash_quest_if_eligible requires an owner")
    if not flash_defs or QUESTS_FLASH_COUNT <= 0:
        return None

    with _locked_transaction(f"quest_assignment:{owner_lc}") as cur:
        cur.execute(
            "SELECT COUNT(1) FROM user_flash_quests WHERE LOWER(owner) = LOWER(%s) AND ends_at > %s",
            (owner_lc, ts),
        )
        active = int((cur.fetchone() or [0])[0] or 0)
        if active >= QUESTS_FLASH_COUNT:
            log_event(None, "quest.flash.at_cap", owner=owner_lc, active=active, cap=QUESTS_FLASH_COUNT)
            return None

        next_flash_at = _get_next_flash_at(cur, owner_lc)
        if next_flash_at == 0:
            # First sighting of this user: start the cooldown instead of handing
            # out a flash quest the moment they arrive.
            initial = ts + QUESTS_FLASH_MIN_INTERVAL_HOURS * 3600
            _set_next_flash_at(cur, owner_lc, initial)
            log_event(None, "quest.flash.cooldown_started", owner=owner_lc, next_flash_at=initial)
            return None
        if ts < next_flash_at:
            return None

        template_id = random.choice(sorted(flash_defs))
        template = flash_defs[template_id]
        window_minutes = template.get("time_window_minutes") or 60
        ends_at = ts + window_minutes * 60

        cur.execute(
            """
            INSERT INTO user_flash_quests (owner, template_id, starts_at, ends_at, progress, progress_meta)
            VALUES (%s, %s, %s, %s, 0, '{}')
            ON CONFLICT (owner, starts_at) DO NOTHING
            RETURNING template_id
            """,
            (owner_lc, template_id, ts, ends_at),
        )
        if cur.fetchone() is None:
            # This owner already has a flash quest starting in this same second,
            # which only the multi-quest cap allows. Nothing new to hand out.
            log_event(None, "quest.flash.same_second_exists", owner=owner_lc, starts_at=ts)
            return None

        next_interval = random.randint(QUESTS_FLASH_MIN_INTERVAL_HOURS * 3600, QUESTS_FLASH_MAX_INTERVAL_HOURS * 3600)
        _set_next_flash_at(cur, owner_lc, ts + next_interval)
        log_event(None, "quest.flash.assigned", owner=owner_lc, template=template_id, ends_at=ends_at)

        return {
            "template_id": template_id,
            "starts_at": ts,
            "ends_at": ends_at,
            "progress": 0,
            "progress_meta": {},
            "last_action_at": None,
            "completed_at": None,
        }
