"""
v2.0.4 Migration: Add node_balance to supply_history

Tracks the validator node's liquid balance alongside total supply,
enabling per-node balance and income/spending charts.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from logging import Logger
    from indexer.database import DatabaseManager
    from indexer.chain_client import ChainClient

MIGRATION_KEY = "v2.0.4_node_balance"


def run(db: "DatabaseManager", chain: "ChainClient", logger: "Logger") -> str:
    """Add node_balance column to supply_history."""
    logger.info("v2.0.4 migration: Adding node_balance column to supply_history...")

    with db._connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                ALTER TABLE supply_history
                ADD COLUMN IF NOT EXISTS node_balance BIGINT
                """
            )

    logger.info("v2.0.4 migration: node_balance column added successfully")
    return "completed"
