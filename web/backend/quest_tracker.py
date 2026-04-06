"""
Quest and Achievement Tracker

Handles:
- Loading quest definitions from YAML
- Per-user quest assignment (daily + flash)
- Progress tracking with anti-gaming rules
- Achievement checking
- Adding rewards to pending_rewards table
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import random
from dataclasses import dataclass, field
from typing import Optional

import yaml

import quest_settings as settings

logger = logging.getLogger(__name__)


@dataclass
class QuestDefinition:
    """Quest definition loaded from YAML."""

    id: str
    title: str
    description: str
    action_type: str
    target_count: int = 1
    rewards: list = field(default_factory=list)

    # Optional parameters
    time_spacing_minutes: Optional[int] = None
    min_content_length: Optional[int] = None
    unique_target: bool = False
    unique_topic: bool = False  # Require unique topics (for topic_explorer quest)
    unique_topics_min: Optional[int] = None
    allow_self: bool = True
    count_vote_changes: bool = False
    quality_threshold: Optional[int] = None
    unique_root_post: bool = False

    # For balanced_vote quest type
    target_upvotes: Optional[int] = None
    target_downvotes: Optional[int] = None

    # For flash quests
    time_window_minutes: Optional[int] = None


@dataclass
class QuestProgress:
    """User progress on a quest."""

    progress: int = 0
    progress_meta: dict = field(default_factory=dict)
    last_action_at: Optional[int] = None
    completed_at: Optional[int] = None


class QuestTracker:
    """Tracks quest and achievement progress for users."""

    def __init__(self, connect_fn):
        self._connect = connect_fn
        self.daily_quests: list[QuestDefinition] = []
        self.flash_templates: list[QuestDefinition] = []
        self.achievements: list[QuestDefinition] = []
        self.special_quests: list[QuestDefinition] = []  # Special quests with custom gating
        self._load_definitions()

    def _load_definitions(self) -> None:
        """Load quest definitions from YAML file."""
        yaml_path = os.path.join(os.path.dirname(__file__), "quests.yaml")

        if not os.path.exists(yaml_path):
            logger.warning(f"Quest definitions not found at {yaml_path}")
            return

        try:
            with open(yaml_path, "r") as f:
                data = yaml.safe_load(f)

            # Load daily quests
            for q in data.get("daily_quests", []):
                self.daily_quests.append(QuestDefinition(**q))

            # Load flash quest templates
            for q in data.get("flash_quest_templates", []):
                self.flash_templates.append(QuestDefinition(**q))

            # Load achievements
            for q in data.get("achievements", []):
                self.achievements.append(QuestDefinition(**q))

            # Load special quests (excluded from random pool, have custom gating)
            for q in data.get("special_quests", []):
                self.special_quests.append(QuestDefinition(**q))

            logger.info(
                f"Loaded {len(self.daily_quests)} daily quests, "
                f"{len(self.flash_templates)} flash templates, "
                f"{len(self.achievements)} achievements, "
                f"{len(self.special_quests)} special quests"
            )
        except Exception as e:
            logger.error(f"Failed to load quest definitions: {e}")

    def _utc_julian_day(self, ts: int) -> int:
        """Convert Unix timestamp to UTC Julian day number."""
        # Julian day 0 = Jan 1, 4713 BC
        # Unix epoch (Jan 1, 1970) = Julian day 2440588
        return 2440588 + (ts // 86400)

    def _is_user_suspended(self, owner: str, ts: int) -> bool:
        """Check if user's rewards are suspended."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT suspended_until FROM reward_suspensions WHERE LOWER(owner) = LOWER(%s)", (owner,))
                row = cur.fetchone()
                if not row:
                    return False
                suspended_until = row[0]
                # 0 means not suspended, any future timestamp means suspended
                return suspended_until > ts

    def _get_daily_quest_progress(self, owner: str, quest_id: str, day_utc: int) -> QuestProgress:
        """Get user's progress on a daily quest."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT progress, progress_meta, last_action_at, completed_at
                    FROM user_daily_quests
                    WHERE LOWER(owner) = LOWER(%s) AND day_utc = %s AND quest_id = %s
                    """,
                    (owner, day_utc, quest_id),
                )
                row = cur.fetchone()
                if not row:
                    return QuestProgress()
                return QuestProgress(
                    progress=row[0],
                    progress_meta=row[1] if isinstance(row[1], dict) else {},
                    last_action_at=row[2],
                    completed_at=row[3],
                )

    def _update_daily_quest_progress(
        self,
        owner: str,
        quest_id: str,
        day_utc: int,
        progress: int,
        progress_meta: dict,
        last_action_at: int,
        completed_at: Optional[int],
    ) -> None:
        """Update user's daily quest progress."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO user_daily_quests (owner, day_utc, quest_id, progress, progress_meta, last_action_at, completed_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (owner, day_utc, quest_id) DO UPDATE SET
                        progress = EXCLUDED.progress,
                        progress_meta = EXCLUDED.progress_meta,
                        last_action_at = EXCLUDED.last_action_at,
                        completed_at = EXCLUDED.completed_at
                    """,
                    (owner, day_utc, quest_id, progress, json.dumps(progress_meta), last_action_at, completed_at),
                )

    def _get_user_assigned_quests(self, owner: str, day_utc: int) -> list[str]:
        """Get the quest IDs assigned to a user for a given day."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT DISTINCT quest_id FROM user_daily_quests
                    WHERE LOWER(owner) = LOWER(%s) AND day_utc = %s
                    """,
                    (owner, day_utc),
                )
                return [row[0] for row in cur.fetchall()]

    def _has_unused_invite_codes(self, owner: str) -> bool:
        """Check if user has at least one unused invite code."""
        with self._connect() as conn:
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

    def _get_completed_quest_count(self, owner: str) -> int:
        """Get total number of completed quests for a user."""
        with self._connect() as conn:
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

    def _get_invite_earner_completed_count(self, owner: str) -> int:
        """Get total number of completed invite_earner quests for a user.

        Counts claimed invite_code rewards from invite_earner quests, which is more
        reliable than counting quest completions (which can be reset via debug panel).
        """
        with self._connect() as conn:
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

    def _is_invite_earner_eligible(self, owner: str, day_utc: int) -> bool:
        """Check if user is eligible for invite_earner quest.

        User is eligible if:
        1. completed_count >= (invite_earner_completed + 1) * interval
        2. 30% daily roll passes
        """
        completed_count = self._get_completed_quest_count(owner)
        invite_earner_completed = self._get_invite_earner_completed_count(owner)
        next_milestone = (invite_earner_completed + 1) * settings.QUESTS_INVITE_EARNER_INTERVAL

        if completed_count < next_milestone:
            return False

        # 30% daily roll
        roll = self._deterministic_roll(owner, day_utc, "invite_earner")
        return roll < settings.QUESTS_INVITE_EARNER_CHANCE

    def _deterministic_roll(self, owner: str, day_utc: int, roll_type: str) -> float:
        """Generate a deterministic random value (0-1) based on owner, day, and roll type."""
        seed_str = f"{owner.lower()}:{day_utc}:{roll_type}"
        seed_hash = hashlib.sha256(seed_str.encode()).hexdigest()
        # Use first 8 hex chars as seed (32 bits)
        seed_int = int(seed_hash[:8], 16)
        rng = random.Random(seed_int)
        return rng.random()

    def _assign_daily_quests(self, owner: str, day_utc: int, ts: int) -> list[str]:
        """Assign random daily quests to a user for the day, including special quest gating."""
        if not self.daily_quests:
            return []

        quest_ids = []
        special_quest_assigned = False

        # Check for invite_recruit eligibility (30% roll if user has unused codes)
        if not special_quest_assigned and self._has_unused_invite_codes(owner):
            roll = self._deterministic_roll(owner, day_utc, "invite_recruit")
            logger.debug(
                f"invite_recruit roll for {owner}: {roll:.3f} (threshold: {settings.QUESTS_INVITE_RECRUIT_CHANCE})"
            )
            if roll < settings.QUESTS_INVITE_RECRUIT_CHANCE:
                # Find invite_recruit in special quests
                invite_recruit = next((q for q in self.special_quests if q.id == "invite_recruit"), None)
                if invite_recruit:
                    quest_ids.append(invite_recruit.id)
                    special_quest_assigned = True
                    logger.info(f"Assigned special quest invite_recruit to {owner} (roll passed)")

        # Check for invite_earner eligibility (every N completed quests + 30% roll)
        if not special_quest_assigned:
            if self._is_invite_earner_eligible(owner, day_utc):
                invite_earner = next((q for q in self.special_quests if q.id == "invite_earner"), None)
                if invite_earner:
                    completed_count = self._get_completed_quest_count(owner)
                    quest_ids.append(invite_earner.id)
                    special_quest_assigned = True
                    logger.info(f"Assigned special quest invite_earner to {owner} (completed {completed_count} quests)")

        # Fill remaining slots with random daily quests
        remaining_slots = settings.QUESTS_DAILY_COUNT - len(quest_ids)
        if remaining_slots > 0 and self.daily_quests:
            count = min(remaining_slots, len(self.daily_quests))
            selected = random.sample(self.daily_quests, count)
            quest_ids.extend([q.id for q in selected])

        # Insert initial progress records
        with self._connect() as conn:
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

        # Delay flash quest by at least 1h after daily quests are first assigned
        min_flash_at = ts + 3600
        next_flash = self._get_next_flash_time(owner)
        if next_flash < min_flash_at:
            self._set_next_flash_time(owner, min_flash_at)
            logger.info(f"Pushed flash quest eligibility to {min_flash_at} for {owner} (1h after daily assignment)")

        logger.info(f"Assigned daily quests {quest_ids} to {owner} for day {day_utc}")
        return quest_ids

    def _get_quest_by_id(self, quest_id: str) -> Optional[QuestDefinition]:
        """Get quest definition by ID."""
        for q in self.daily_quests:
            if q.id == quest_id:
                return q
        for q in self.flash_templates:
            if q.id == quest_id:
                return q
        for q in self.achievements:
            if q.id == quest_id:
                return q
        for q in self.special_quests:
            if q.id == quest_id:
                return q
        return None

    # ==================== Flash Quest Methods ====================

    def _get_active_flash_quest(self, owner: str, ts: int) -> Optional[dict]:
        """Get the user's currently active (non-expired, non-completed) flash quest."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT template_id, starts_at, ends_at, progress, progress_meta, last_action_at, completed_at
                    FROM user_flash_quests
                    WHERE LOWER(owner) = LOWER(%s)
                      AND ends_at > %s
                      AND completed_at IS NULL
                    ORDER BY starts_at DESC
                    LIMIT 1
                    """,
                    (owner, ts),
                )
                row = cur.fetchone()
                if row:
                    return {
                        "template_id": row[0],
                        "starts_at": row[1],
                        "ends_at": row[2],
                        "progress": row[3],
                        "progress_meta": row[4] if row[4] else {},
                        "last_action_at": row[5],
                        "completed_at": row[6],
                    }
                return None

    def _get_next_flash_time(self, owner: str) -> int:
        """Get the timestamp when user can receive their next flash quest."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT next_flash_at FROM user_quest_state WHERE LOWER(owner) = LOWER(%s)", (owner,))
                row = cur.fetchone()
                return row[0] if row else 0

    def _set_next_flash_time(self, owner: str, next_ts: int) -> None:
        """Set when the user can receive their next flash quest."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO user_quest_state (owner, next_flash_at)
                    VALUES (%s, %s)
                    ON CONFLICT (owner) DO UPDATE SET next_flash_at = EXCLUDED.next_flash_at
                    """,
                    (owner, next_ts),
                )

    def _maybe_assign_flash_quest(self, owner: str, ts: int) -> Optional[dict]:
        """
        Assign a flash quest if enough time has passed since the last one.
        Returns the newly assigned flash quest or None.
        """
        if not self.flash_templates:
            return None

        # Check if user already has an active flash quest
        active = self._get_active_flash_quest(owner, ts)
        if active:
            return None

        # Check if enough time has passed
        next_flash_at = self._get_next_flash_time(owner)

        # New user check: if no next_flash_at record exists (returns 0),
        # initialize it with minimum interval delay so new users don't get flash quests immediately
        if next_flash_at == 0:
            initial_delay = settings.QUESTS_FLASH_MIN_INTERVAL_HOURS * 3600
            self._set_next_flash_time(owner, ts + initial_delay)
            logger.info(f"New user {owner}: initialized flash quest delay to {initial_delay}s")
            return None

        if ts < next_flash_at:
            return None

        # Select a random flash quest template
        template = random.choice(self.flash_templates)

        # Calculate duration based on time_window_minutes (default 60 min)
        duration_seconds = (template.time_window_minutes or 60) * 60
        ends_at = ts + duration_seconds

        # Insert the flash quest
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO user_flash_quests (owner, template_id, starts_at, ends_at, progress, progress_meta)
                    VALUES (%s, %s, %s, %s, 0, '{}')
                    """,
                    (owner, template.id, ts, ends_at),
                )

        # Schedule next flash quest (random interval between MIN and MAX hours)
        min_hours = settings.QUESTS_FLASH_MIN_INTERVAL_HOURS
        max_hours = settings.QUESTS_FLASH_MAX_INTERVAL_HOURS
        next_interval_seconds = random.randint(min_hours * 3600, max_hours * 3600)
        self._set_next_flash_time(owner, ts + next_interval_seconds)

        logger.info(f"Assigned flash quest {template.id} to {owner}, ends at {ends_at}")

        return {
            "template_id": template.id,
            "starts_at": ts,
            "ends_at": ends_at,
            "progress": 0,
            "progress_meta": {},
            "last_action_at": None,
            "completed_at": None,
        }

    def _get_flash_quest_progress(self, owner: str, starts_at: int) -> QuestProgress:
        """Get progress for a specific flash quest."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT progress, progress_meta, last_action_at, completed_at
                    FROM user_flash_quests
                    WHERE LOWER(owner) = LOWER(%s) AND starts_at = %s
                    """,
                    (owner, starts_at),
                )
                row = cur.fetchone()
                if row:
                    return QuestProgress(
                        progress=row[0],
                        progress_meta=row[1] if row[1] else {},
                        last_action_at=row[2],
                        completed_at=row[3],
                    )
                return QuestProgress()

    def _update_flash_quest_progress(
        self,
        owner: str,
        starts_at: int,
        progress: int,
        progress_meta: dict,
        last_action_at: int,
        completed_at: Optional[int],
    ) -> None:
        """Update flash quest progress."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE user_flash_quests
                    SET progress = %s, progress_meta = %s, last_action_at = %s, completed_at = %s
                    WHERE LOWER(owner) = LOWER(%s) AND starts_at = %s
                    """,
                    (progress, json.dumps(progress_meta), last_action_at, completed_at, owner, starts_at),
                )

    def _flash_quest_has_target(self, owner: str, starts_at: int, target: str) -> bool:
        """Check if target is already counted for this flash quest."""
        progress = self._get_flash_quest_progress(owner, starts_at)
        targets = progress.progress_meta.get("targets", [])
        return target.lower() in [t.lower() for t in targets]

    def _flash_quest_has_root(self, owner: str, starts_at: int, root_post_id: str) -> bool:
        """Check if root post is already counted for this flash quest."""
        progress = self._get_flash_quest_progress(owner, starts_at)
        roots = progress.progress_meta.get("roots", [])
        return root_post_id.lower() in [r.lower() for r in roots]

    def _flash_quest_has_topic(self, owner: str, starts_at: int, topic: str) -> bool:
        """Check if topic is already counted for this flash quest."""
        progress = self._get_flash_quest_progress(owner, starts_at)
        topics = progress.progress_meta.get("unique_topics", [])
        return topic.lower() in [t.lower() for t in topics]

    def _increment_flash_progress(
        self, owner: str, quest: QuestDefinition, flash_data: dict, ts: int, **kwargs
    ) -> None:
        """
        Increment flash quest progress if conditions are met.
        Similar to _increment_daily_progress but for flash quests.
        """
        starts_at = flash_data["starts_at"]
        progress = self._get_flash_quest_progress(owner, starts_at)

        logger.info(
            f"_increment_flash_progress: quest={quest.id}, progress={progress.progress}/{quest.target_count}, kwargs={kwargs}"
        )

        # Already completed
        if progress.completed_at is not None:
            logger.info(f"Flash quest {quest.id} already completed")
            return

        # Enforce minimum content length if configured
        if quest.min_content_length:
            content_length = kwargs.get("content_length", 0)
            if content_length < quest.min_content_length:
                logger.info(
                    f"Flash quest {quest.id} rejected: content_length {content_length} < {quest.min_content_length}"
                )
                return

        # Check quality threshold if applicable
        if quest.quality_threshold:
            if "quality" not in kwargs:
                raise ValueError(f"Flash quest {quest.id} requires quality, but none provided")
            quality = kwargs.get("quality")
            if quality is None:
                raise ValueError(f"Flash quest {quest.id} requires quality, but got None")
            if quality < quest.quality_threshold:
                return

        # Enforce unique root thread for comment quests
        if quest.unique_root_post:
            root_post_id = kwargs.get("root_post_id")
            if root_post_id and self._flash_quest_has_root(owner, starts_at, root_post_id):
                logger.info(f"Flash quest {quest.id} rejected: duplicate root_post_id {root_post_id}")
                return

        # Reject self-target interactions if configured
        if not quest.allow_self:
            target_owner = kwargs.get("target_owner")
            if target_owner and target_owner.lower() == owner.lower():
                logger.info(f"Flash quest {quest.id} rejected: self-interaction (owner={owner})")
                return

        # Ignore vote changes if configured
        if not quest.count_vote_changes:
            vote_is_change = kwargs.get("vote_is_change", False)
            if vote_is_change:
                logger.info(f"Flash quest {quest.id} rejected: vote_is_change=True")
                return

        # Enforce unique targets if configured
        if quest.unique_target:
            target = kwargs.get("target")
            if target and self._flash_quest_has_target(owner, starts_at, target):
                logger.info(f"Flash quest {quest.id} rejected: duplicate target {target}")
                return

        # Enforce unique topics if configured (for topic_explorer quest)
        if quest.unique_topic:
            topic = kwargs.get("topic")
            if topic and self._flash_quest_has_topic(owner, starts_at, topic):
                logger.info(f"Flash quest {quest.id} rejected: duplicate topic {topic}")
                return

        # Check time spacing
        if quest.time_spacing_minutes:
            if progress.last_action_at:
                elapsed_minutes = (ts - progress.last_action_at) / 60
                if elapsed_minutes < quest.time_spacing_minutes:
                    logger.info(
                        f"Flash quest {quest.id} rejected: time_spacing {elapsed_minutes:.1f}m < {quest.time_spacing_minutes}m"
                    )
                    return

        # Update progress_meta
        meta = progress.progress_meta.copy()

        # Track unique targets
        if quest.unique_target:
            target = kwargs.get("target")
            if target:
                targets = meta.get("targets", [])
                targets.append(target.lower())
                meta["targets"] = targets

        # Track unique roots
        if quest.unique_root_post:
            root_post_id = kwargs.get("root_post_id")
            if root_post_id:
                roots = meta.get("roots", [])
                roots.append(root_post_id.lower())
                meta["roots"] = roots

        # Track unique topics (for topic_explorer quest)
        if quest.unique_topic:
            topic = kwargs.get("topic")
            if topic:
                unique_topics = meta.get("unique_topics", [])
                unique_topics.append(topic.lower())
                meta["unique_topics"] = unique_topics

        # Track unique topics for vote quests
        if quest.unique_topics_min:
            target_topic = kwargs.get("target_topic")
            if target_topic:
                topics = set(meta.get("topics", []))
                topics.add(target_topic.lower())
                meta["topics"] = list(topics)

        # Increment progress
        new_progress = progress.progress
        completed = False

        if quest.action_type == "balanced_vote":
            target_up = quest.target_upvotes or 0
            target_down = quest.target_downvotes or 0
            target_total = target_up + target_down
            if target_total <= 0:
                raise ValueError(f"Flash quest {quest.id} requires non-zero balanced_vote targets")

            vote_direction = kwargs.get("vote_direction", 0)
            if vote_direction > 0:
                meta["upvotes"] = meta.get("upvotes", 0) + 1
            elif vote_direction < 0:
                meta["downvotes"] = meta.get("downvotes", 0) + 1

            new_progress = meta.get("upvotes", 0) + meta.get("downvotes", 0)
            completed = meta.get("upvotes", 0) >= target_up and meta.get("downvotes", 0) >= target_down

            if not completed and new_progress >= target_total:
                new_progress = target_total - 1
        else:
            new_progress = progress.progress + 1
            completed = new_progress >= quest.target_count

            if quest.unique_topics_min:
                if len(meta.get("topics", [])) < quest.unique_topics_min:
                    completed = False
                    if new_progress >= quest.target_count:
                        new_progress = quest.target_count - 1

        # Update progress
        self._update_flash_quest_progress(owner, starts_at, new_progress, meta, ts, ts if completed else None)

        logger.info(f"Flash quest progress: {owner} {quest.id} {new_progress}/{quest.target_count}")

        # Add rewards if completed
        if completed:
            for reward in quest.rewards:
                reward_type = reward.get("type", "mirage")
                if reward_type == "mirage":
                    # YAML stores MIRAGE, DB stores umirage (1 MIRAGE = 1,000,000 umirage)
                    amount_umirage = reward.get("amount", 0) * 1_000_000
                    apply_multiplier = reward.get("apply_multiplier", True)
                    reward_data = {"amount": amount_umirage, "apply_multiplier": apply_multiplier}
                else:
                    reward_data = {"id": reward.get("id")}

                self._add_pending_reward(owner, reward_type, reward_data, f"flash:{quest.id}", ts)

            logger.info(f"Flash quest completed: {owner} finished {quest.id}")

    def _add_pending_reward(self, owner: str, reward_type: str, reward_data: dict, reason: str, ts: int) -> None:
        """Add a pending reward for a user."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO pending_rewards (owner, reward_type, reward_data, reason, created_at)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (owner, reward_type, json.dumps(reward_data), reason, ts),
                )
        logger.info(f"Added pending reward for {owner}: {reward_type} - {reason}")

    def _quest_has_target(self, owner: str, quest_id: str, day_utc: int, target: str) -> bool:
        """Check if target is already counted for this quest/day."""
        progress = self._get_daily_quest_progress(owner, quest_id, day_utc)
        targets = progress.progress_meta.get("targets", [])
        return target.lower() in [t.lower() for t in targets]

    def _quest_has_root(self, owner: str, quest_id: str, day_utc: int, root_post_id: str) -> bool:
        """Check if root post is already counted for this quest/day."""
        progress = self._get_daily_quest_progress(owner, quest_id, day_utc)
        roots = progress.progress_meta.get("roots", [])
        return root_post_id.lower() in [r.lower() for r in roots]

    def _quest_has_topic(self, owner: str, quest_id: str, day_utc: int, topic: str) -> bool:
        """Check if topic is already counted for this quest/day."""
        progress = self._get_daily_quest_progress(owner, quest_id, day_utc)
        topics = progress.progress_meta.get("unique_topics", [])
        return topic.lower() in [t.lower() for t in topics]

    def _increment_daily_progress(self, owner: str, quest: QuestDefinition, day_utc: int, ts: int, **kwargs) -> None:
        """Increment progress on a daily quest if requirements are met."""
        progress = self._get_daily_quest_progress(owner, quest.id, day_utc)

        # Already completed
        if progress.completed_at is not None:
            return

        # Enforce minimum content length if configured
        if quest.min_content_length:
            content_length = kwargs.get("content_length", 0)
            if content_length < quest.min_content_length:
                return

        # Check quality threshold if applicable
        if quest.quality_threshold:
            if "quality" not in kwargs:
                raise ValueError(f"Quest {quest.id} requires quality, but none provided")
            quality = kwargs.get("quality")
            if quality is None:
                raise ValueError(f"Quest {quest.id} requires quality, but got None")
            if quality < quest.quality_threshold:
                return

        # Enforce unique root thread for comment quests
        if quest.unique_root_post:
            root_post_id = kwargs.get("root_post_id")
            if root_post_id and self._quest_has_root(owner, quest.id, day_utc, root_post_id):
                return

        # Reject self-target interactions if configured
        if not quest.allow_self:
            target_owner = kwargs.get("target_owner")
            if target_owner and target_owner.lower() == owner.lower():
                return

        # Ignore vote changes if configured
        if not quest.count_vote_changes:
            vote_is_change = kwargs.get("vote_is_change", False)
            if vote_is_change:
                return

        # Enforce unique targets if configured
        if quest.unique_target:
            target = kwargs.get("target")
            if target and self._quest_has_target(owner, quest.id, day_utc, target):
                return

        # Enforce unique topics if configured (for topic_explorer quest)
        if quest.unique_topic:
            topic = kwargs.get("topic")
            if topic and self._quest_has_topic(owner, quest.id, day_utc, topic):
                return

        # Check time spacing
        if quest.time_spacing_minutes:
            if progress.last_action_at:
                elapsed_minutes = (ts - progress.last_action_at) / 60
                if elapsed_minutes < quest.time_spacing_minutes:
                    return

        # Update progress_meta
        meta = progress.progress_meta.copy()

        # Track unique targets
        if quest.unique_target:
            target = kwargs.get("target")
            if target:
                targets = meta.get("targets", [])
                targets.append(target.lower())
                meta["targets"] = targets

        # Track unique roots
        if quest.unique_root_post:
            root_post_id = kwargs.get("root_post_id")
            if root_post_id:
                roots = meta.get("roots", [])
                roots.append(root_post_id.lower())
                meta["roots"] = roots

        # Track unique topics (for topic_explorer quest)
        if quest.unique_topic:
            topic = kwargs.get("topic")
            if topic:
                unique_topics = meta.get("unique_topics", [])
                unique_topics.append(topic.lower())
                meta["unique_topics"] = unique_topics

        # Track unique topics for vote quests
        if quest.unique_topics_min:
            target_topic = kwargs.get("target_topic")
            if target_topic:
                topics = set(meta.get("topics", []))
                topics.add(target_topic.lower())
                meta["topics"] = list(topics)

        # Increment progress
        new_progress = progress.progress
        completed = False

        if quest.action_type == "balanced_vote":
            target_up = quest.target_upvotes or 0
            target_down = quest.target_downvotes or 0
            target_total = target_up + target_down
            if target_total <= 0:
                raise ValueError(f"Quest {quest.id} requires non-zero balanced_vote targets")

            vote_direction = kwargs.get("vote_direction", 0)
            if vote_direction > 0:
                meta["upvotes"] = meta.get("upvotes", 0) + 1
            elif vote_direction < 0:
                meta["downvotes"] = meta.get("downvotes", 0) + 1

            new_progress = meta.get("upvotes", 0) + meta.get("downvotes", 0)

            completed = meta.get("upvotes", 0) >= target_up and meta.get("downvotes", 0) >= target_down

            if not completed and new_progress >= target_total:
                new_progress = target_total - 1
        else:
            new_progress = progress.progress + 1
            completed = new_progress >= quest.target_count

            if quest.unique_topics_min:
                if len(meta.get("topics", [])) < quest.unique_topics_min:
                    completed = False
                    if new_progress >= quest.target_count:
                        new_progress = quest.target_count - 1

        # Update progress
        self._update_daily_quest_progress(owner, quest.id, day_utc, new_progress, meta, ts, ts if completed else None)

        # Add rewards if completed
        if completed:
            for reward in quest.rewards:
                reward_type = reward.get("type", "mirage")
                if reward_type == "mirage":
                    # YAML stores MIRAGE, DB stores umirage (1 MIRAGE = 1,000,000 umirage)
                    amount_umirage = reward.get("amount", 0) * 1_000_000
                    apply_multiplier = reward.get("apply_multiplier", True)
                    reward_data = {"amount": amount_umirage, "apply_multiplier": apply_multiplier}
                elif reward_type == "invite_code":
                    # Invite code rewards are handled at claim time
                    reward_data = {"amount": reward.get("amount", 1)}
                else:
                    reward_data = {"id": reward.get("id")}

                self._add_pending_reward(owner, reward_type, reward_data, f"quest:{quest.id}", ts)

            logger.info(f"Quest completed: {owner} finished {quest.id}")

    def _check_achievement_progress(self, owner: str, achievement: QuestDefinition, ts: int, **kwargs) -> None:
        """Check and update achievement progress."""
        # Get current progress
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT progress, progress_meta, unlocked_at
                    FROM user_achievements
                    WHERE LOWER(owner) = LOWER(%s) AND achievement_id = %s
                    """,
                    (owner, achievement.id),
                )
                row = cur.fetchone()

                if row and row[2] is not None:
                    # Already unlocked
                    return

                current_progress = row[0] if row else 0
                meta = row[1] if row and isinstance(row[1], dict) else {}

        # Check quality threshold if applicable
        if achievement.quality_threshold:
            if "quality" not in kwargs:
                raise ValueError(f"Achievement {achievement.id} requires quality, but none provided")
            quality = kwargs.get("quality")
            if quality is None:
                raise ValueError(f"Achievement {achievement.id} requires quality, but got None")
            if quality < achievement.quality_threshold:
                return

        target_norm = None
        if achievement.unique_target:
            target = kwargs.get("target")
            if not target:
                raise ValueError(f"Achievement {achievement.id} requires target, but none provided")
            target_norm = str(target).strip().lower()
            targets = meta.get("targets", [])
            if target_norm in [t.lower() for t in targets]:
                return

        # Increment progress
        new_progress = current_progress + 1
        completed = new_progress >= achievement.target_count

        if achievement.unique_target and target_norm:
            targets = meta.get("targets", [])
            targets.append(target_norm)
            meta["targets"] = targets

        # Update achievement
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO user_achievements (owner, achievement_id, progress, progress_meta, unlocked_at)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (owner, achievement_id) DO UPDATE SET
                        progress = EXCLUDED.progress,
                        progress_meta = EXCLUDED.progress_meta,
                        unlocked_at = EXCLUDED.unlocked_at
                    """,
                    (owner, achievement.id, new_progress, json.dumps(meta), ts if completed else None),
                )

        # Add rewards if completed
        if completed:
            for reward in achievement.rewards:
                reward_type = reward.get("type", "mirage")
                if reward_type == "mirage":
                    # YAML stores MIRAGE, DB stores umirage (1 MIRAGE = 1,000,000 umirage)
                    amount_umirage = reward.get("amount", 0) * 1_000_000
                    apply_multiplier = reward.get("apply_multiplier", True)
                    reward_data = {"amount": amount_umirage, "apply_multiplier": apply_multiplier}
                else:
                    reward_data = {"id": reward.get("id")}

                self._add_pending_reward(owner, reward_type, reward_data, f"achievement:{achievement.id}", ts)

            logger.info(f"Achievement unlocked: {owner} earned {achievement.id}")

    def update_progress(self, owner: str, action_type: str, ts: int, **kwargs) -> None:
        """
        Update quest progress for a user action.

        Called by message_processor when handling posts, votes, etc.

        Args:
            owner: User address
            action_type: Type of action (post, vote, comment, etc.)
            ts: Unix timestamp
            **kwargs: Action-specific data (target, topic, content_length, etc.)
        """
        # Check feature flags
        if not settings.QUESTS_ENABLED and not settings.ACHIEVEMENTS_ENABLED:
            return

        # Check if user is suspended
        if self._is_user_suspended(owner, ts):
            return

        day_utc = self._utc_julian_day(ts)

        # Process daily quests
        if settings.QUESTS_ENABLED:
            # Ensure user has assigned quests for today
            assigned_ids = self._get_user_assigned_quests(owner, day_utc)
            if not assigned_ids:
                assigned_ids = self._assign_daily_quests(owner, day_utc, ts)

            # Check progress on each assigned quest
            for quest_id in assigned_ids:
                quest = self._get_quest_by_id(quest_id)
                if quest and quest.action_type == action_type:
                    self._increment_daily_progress(owner, quest, day_utc, ts, **kwargs)

            # Handle flash quests
            flash_data = self._get_active_flash_quest(owner, ts)
            if flash_data:
                flash_quest = self._get_quest_by_id(flash_data["template_id"])
                logger.info(
                    f"Flash quest check: template={flash_data['template_id']}, quest_action={flash_quest.action_type if flash_quest else 'None'}, incoming_action={action_type}"
                )
                if flash_quest and flash_quest.action_type == action_type:
                    self._increment_flash_progress(owner, flash_quest, flash_data, ts, **kwargs)
                elif flash_quest:
                    logger.info(f"Flash quest action mismatch: expected {flash_quest.action_type}, got {action_type}")

        # Process achievements
        if settings.ACHIEVEMENTS_ENABLED:
            for achievement in self.achievements:
                if achievement.action_type == action_type:
                    self._check_achievement_progress(owner, achievement, ts, **kwargs)

    def get_user_quests(self, owner: str, ts: int) -> dict:
        """
        Get user's current quest status.

        Returns dict with daily quests, flash quest, and achievements.
        """
        day_utc = self._utc_julian_day(ts)

        # Ensure user has assigned quests
        assigned_ids = self._get_user_assigned_quests(owner, day_utc)
        if not assigned_ids:
            assigned_ids = self._assign_daily_quests(owner, day_utc, ts)

        # Get daily quest progress
        daily_quests = []
        for quest_id in assigned_ids:
            quest = self._get_quest_by_id(quest_id)
            if not quest:
                continue

            progress = self._get_daily_quest_progress(owner, quest_id, day_utc)

            # Calculate target for balanced_vote
            if quest.action_type == "balanced_vote":
                target = (quest.target_upvotes or 0) + (quest.target_downvotes or 0)
            else:
                target = quest.target_count

            daily_quests.append(
                {
                    "id": quest.id,
                    "title": quest.title,
                    "description": quest.description,
                    "progress": progress.progress,
                    "target": target,
                    "completed": progress.completed_at is not None,
                    "rewards": quest.rewards,
                }
            )

        # Get achievement status
        achievements = []
        for achievement in self.achievements:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT progress, unlocked_at
                        FROM user_achievements
                        WHERE LOWER(owner) = LOWER(%s) AND achievement_id = %s
                        """,
                        (owner, achievement.id),
                    )
                    row = cur.fetchone()
                    progress = row[0] if row else 0
                    unlocked = row[1] is not None if row else False

            achievements.append(
                {
                    "id": achievement.id,
                    "title": achievement.title,
                    "description": achievement.description,
                    "progress": progress,
                    "target": achievement.target_count,
                    "unlocked": unlocked,
                    "rewards": achievement.rewards,
                }
            )

        # Calculate time until daily reset (next UTC midnight)
        seconds_into_day = ts % 86400
        seconds_until_reset = 86400 - seconds_into_day

        # Get flash quest (may assign one if eligible)
        flash_quest_data = None
        flash_data = self._get_active_flash_quest(owner, ts)
        if not flash_data:
            # Try to assign a new flash quest
            flash_data = self._maybe_assign_flash_quest(owner, ts)

        if flash_data:
            template = self._get_quest_by_id(flash_data["template_id"])
            if template:
                # Calculate target
                if template.action_type == "balanced_vote":
                    target = (template.target_upvotes or 0) + (template.target_downvotes or 0)
                else:
                    target = template.target_count

                flash_quest_data = {
                    "id": template.id,
                    "title": template.title,
                    "description": template.description,
                    "progress": flash_data["progress"],
                    "target": target,
                    "completed": flash_data["completed_at"] is not None,
                    "rewards": template.rewards,
                    "starts_at": flash_data["starts_at"],
                    "ends_at": flash_data["ends_at"],
                    "seconds_remaining": max(0, flash_data["ends_at"] - ts),
                }

        return {
            "daily_quests": daily_quests,
            "flash_quest": flash_quest_data,
            "achievements": achievements,
            "seconds_until_reset": seconds_until_reset,
        }
