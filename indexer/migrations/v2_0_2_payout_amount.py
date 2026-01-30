"""
v2.0.2 Migration: Add payout_amount to pending_rewards

Stores the actual amount paid out (after multiplier) when rewards are claimed.
This allows the stats page to show the real MIRAGE distributed, not just base amounts.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from logging import Logger
    from indexer.database import DatabaseManager
    from indexer.chain_client import ChainClient

MIGRATION_KEY = "v2.0.2_payout_amount"


def run(db: "DatabaseManager", chain: "ChainClient", logger: "Logger") -> str:
    """Add payout_amount column to pending_rewards."""
    logger.info("v2.0.2 migration: Adding payout_amount column to pending_rewards...")

    with db._connect() as conn:
        with conn.cursor() as cur:
            # Add payout_amount column (nullable - only set when claimed)
            # This stores the actual amount sent after applying the multiplier
            cur.execute(
                """
                ALTER TABLE pending_rewards
                ADD COLUMN IF NOT EXISTS payout_amount BIGINT
                """
            )

    logger.info("v2.0.2 migration: payout_amount column added successfully")
    return "completed"
