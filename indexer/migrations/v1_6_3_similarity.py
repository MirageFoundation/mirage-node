"""
v1.6.3 Migration: Initial similarity calculation for all users

Pre-populates the user_similarity_cache so users get recommendations immediately.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from logging import Logger
    from indexer.database import DatabaseManager
    from indexer.chain_client import ChainClient

MIGRATION_KEY = "v1.6.3_similarity"


def run(db: "DatabaseManager", chain: "ChainClient", logger: "Logger") -> str:
    """Compute initial similarity scores for all users with enough preferences."""
    logger.info("v1.6.3 migration: Starting initial similarity calculation...")
    
    with db._connect() as conn:
        with conn.cursor() as cur:
            db._compute_all_user_similarities(cur)
    
    return "completed"
