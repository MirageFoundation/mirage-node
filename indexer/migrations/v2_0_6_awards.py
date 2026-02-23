"""
v2.0.6 Migration: Add awards table

Stores burn-only award signals given to posts/comments.
One award per unique owner+target, tracked for display and magic scoring.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from logging import Logger
    from indexer.database import DatabaseManager
    from indexer.chain_client import ChainClient

MIGRATION_KEY = "v2.0.6_awards"


def run(db: "DatabaseManager", chain: "ChainClient", logger: "Logger") -> str:
    """Create the awards table and indexes."""
    logger.info("v2.0.6 migration: Creating awards table...")

    with db._connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS awards (
                    id SERIAL PRIMARY KEY,
                    owner TEXT NOT NULL,
                    target TEXT NOT NULL,
                    award_type TEXT NOT NULL,
                    burned_amount BIGINT NOT NULL DEFAULT 0,
                    created_at BIGINT NOT NULL
                )
                """
            )
            cur.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS uniq_awards_owner_target ON awards(LOWER(owner), LOWER(target))"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_awards_target_lower ON awards(LOWER(target))"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_awards_created_at ON awards(created_at DESC)"
            )

    logger.info("v2.0.6 migration: awards table created successfully")
    return "completed"
