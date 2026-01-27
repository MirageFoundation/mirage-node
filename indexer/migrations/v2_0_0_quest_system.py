"""
v2.0.0 Migration: Quest and Achievement System

Creates tables for the quest/achievement gamification system:
- user_daily_quests: Per-user daily quest assignment (2 random per day)
- user_flash_quests: Per-user flash quest (1 active at a time)
- user_quest_state: Flash quest timing state
- user_achievements: Achievement unlock tracking
- pending_rewards: Rewards waiting to be claimed (extensible for cosmetics)
- user_unlocks: Cosmetic unlocks (icons, badges, frames - future)
- reward_suspensions: Admin moderation for suspended users
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from logging import Logger
    from indexer.database import DatabaseManager
    from indexer.chain_client import ChainClient

MIGRATION_KEY = "v2.0.0_quest_system"


def run(db: "DatabaseManager", chain: "ChainClient", logger: "Logger") -> str:
    """Create quest system tables."""
    logger.info("v2.0.0 migration: Creating quest system tables...")

    with db._connect() as conn:
        with conn.cursor() as cur:
            # Per-user daily quest assignment (2 random quests per user per day)
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS user_daily_quests (
                    owner TEXT NOT NULL,
                    day_utc INTEGER NOT NULL,
                    quest_id TEXT NOT NULL,
                    progress INTEGER NOT NULL DEFAULT 0,
                    progress_meta JSONB NOT NULL DEFAULT '{}',
                    last_action_at BIGINT,
                    completed_at BIGINT,
                    PRIMARY KEY (owner, day_utc, quest_id)
                )
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_user_daily_quests_owner ON user_daily_quests(LOWER(owner))"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_user_daily_quests_day ON user_daily_quests(day_utc DESC)"
            )

            # Per-user flash quest (1 active at a time, random ~6h interval)
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS user_flash_quests (
                    owner TEXT NOT NULL,
                    template_id TEXT NOT NULL,
                    starts_at BIGINT NOT NULL,
                    ends_at BIGINT NOT NULL,
                    progress INTEGER NOT NULL DEFAULT 0,
                    progress_meta JSONB NOT NULL DEFAULT '{}',
                    last_action_at BIGINT,
                    completed_at BIGINT,
                    PRIMARY KEY (owner, starts_at)
                )
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_user_flash_quests_owner ON user_flash_quests(LOWER(owner))"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_user_flash_quests_ends ON user_flash_quests(ends_at)"
            )

            # User quest state (timing for flash quests)
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS user_quest_state (
                    owner TEXT PRIMARY KEY,
                    next_flash_at BIGINT NOT NULL DEFAULT 0
                )
                """
            )

            # User achievements (tracks which achievements each user has unlocked)
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS user_achievements (
                    owner TEXT NOT NULL,
                    achievement_id TEXT NOT NULL,
                    unlocked_at BIGINT NOT NULL,
                    progress INTEGER NOT NULL DEFAULT 0,
                    progress_meta JSONB NOT NULL DEFAULT '{}',
                    PRIMARY KEY (owner, achievement_id)
                )
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_user_achievements_owner ON user_achievements(LOWER(owner))"
            )

            # Pending rewards (extensible for multiple reward types)
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS pending_rewards (
                    id SERIAL PRIMARY KEY,
                    owner TEXT NOT NULL,
                    reward_type TEXT NOT NULL,
                    reward_data JSONB NOT NULL,
                    reason TEXT NOT NULL,
                    created_at BIGINT NOT NULL,
                    claimed_at BIGINT
                )
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_pending_rewards_owner ON pending_rewards(LOWER(owner))"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_pending_rewards_unclaimed ON pending_rewards(owner) WHERE claimed_at IS NULL"
            )

            # User unlocks (for cosmetic rewards - icons, badges, frames)
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS user_unlocks (
                    owner TEXT NOT NULL,
                    unlock_type TEXT NOT NULL,
                    unlock_id TEXT NOT NULL,
                    unlocked_at BIGINT NOT NULL,
                    source TEXT NOT NULL,
                    PRIMARY KEY (owner, unlock_type, unlock_id)
                )
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_user_unlocks_owner ON user_unlocks(LOWER(owner))"
            )

            # Reward suspensions (admin moderation)
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS reward_suspensions (
                    owner TEXT PRIMARY KEY,
                    suspended_until BIGINT NOT NULL,
                    suspended_by TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    updated_at BIGINT NOT NULL
                )
                """
            )

    logger.info("v2.0.0 migration: Quest system tables created successfully")
    return "completed"
