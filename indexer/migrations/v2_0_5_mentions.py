"""
v2.0.5 Migration: Add mentions table

Stores @username mentions extracted from post/comment content,
enabling inbox notifications when a user is mentioned.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from logging import Logger
    from indexer.database import DatabaseManager
    from indexer.chain_client import ChainClient

MIGRATION_KEY = "v2.0.5_mentions"


def run(db: "DatabaseManager", chain: "ChainClient", logger: "Logger") -> str:
    """Create the mentions table and indexes."""
    logger.info("v2.0.5 migration: Creating mentions table...")

    with db._connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS mentions (
                    id SERIAL PRIMARY KEY,
                    post_txhash TEXT NOT NULL,
                    mentioned_address TEXT NOT NULL,
                    mentioner_address TEXT NOT NULL,
                    created_at BIGINT NOT NULL,
                    UNIQUE(post_txhash, mentioned_address)
                )
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_mentions_mentioned_at ON mentions(mentioned_address, created_at DESC)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_mentions_post ON mentions(post_txhash)"
            )

    logger.info("v2.0.5 migration: mentions table created successfully")
    return "completed"
