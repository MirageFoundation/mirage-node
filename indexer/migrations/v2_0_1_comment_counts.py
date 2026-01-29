"""
v2.0.1 Migration: Backfill comment_count for posts.

Computes descendant counts for all non-deleted posts, ignoring subtrees under deleted
ancestors to match runtime visibility rules.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from logging import Logger
    from indexer.database import DatabaseManager
    from indexer.chain_client import ChainClient

MIGRATION_KEY = "v2.0.1_comment_counts"


def run(db: "DatabaseManager", chain: "ChainClient", logger: "Logger") -> str:
    """Backfill comment_count values for all posts."""
    logger.info("v2.0.1 migration: Backfilling comment_count for posts...")

    with db._connect() as conn:
        with conn.cursor() as cur:
            # Reset counts for all non-deleted posts first
            cur.execute("UPDATE posts SET comment_count = 0 WHERE deleted = FALSE")

            cur.execute(
                """
                WITH RECURSIVE descendant_pairs AS (
                    -- Direct children
                    SELECT p.txhash AS ancestor, c.txhash AS descendant
                    FROM posts p
                    JOIN posts c ON c.target = p.txhash
                    WHERE p.deleted = FALSE AND c.deleted = FALSE
                    UNION ALL
                    -- Indirect descendants (only through non-deleted nodes)
                    SELECT dp.ancestor, c.txhash
                    FROM descendant_pairs dp
                    JOIN posts c ON c.target = dp.descendant
                    WHERE c.deleted = FALSE
                ),
                counts AS (
                    SELECT ancestor, COUNT(1) AS cnt
                    FROM descendant_pairs
                    GROUP BY ancestor
                )
                UPDATE posts p
                SET comment_count = c.cnt
                FROM counts c
                WHERE p.deleted = FALSE AND p.txhash = c.ancestor
                """
            )

            # Clear counts for deleted posts (not user-visible)
            cur.execute("UPDATE posts SET comment_count = 0 WHERE deleted = TRUE")

    logger.info("v2.0.1 migration: Backfill completed.")
    return "completed"

