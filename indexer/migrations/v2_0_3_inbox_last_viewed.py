"""
v2.0.3 Migration: Add inbox_last_viewed_at to profiles

Stores the timestamp of when the user last viewed their inbox,
so the server can compute unread inbox count without client-side state.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from logging import Logger
    from indexer.database import DatabaseManager
    from indexer.chain_client import ChainClient

MIGRATION_KEY = "v2.0.3_inbox_last_viewed"


def run(db: "DatabaseManager", chain: "ChainClient", logger: "Logger") -> str:
    """Add inbox_last_viewed_at column to profiles."""
    logger.info("v2.0.3 migration: Adding inbox_last_viewed_at column to profiles...")

    with db._connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                ALTER TABLE profiles
                ADD COLUMN IF NOT EXISTS inbox_last_viewed_at BIGINT NOT NULL DEFAULT 0
                """
            )

    logger.info("v2.0.3 migration: inbox_last_viewed_at column added successfully")
    return "completed"
