"""
v1.6.3 Migration: Backfill missing profile created_at

Some profiles have created_at=0 due to older indexing.
Sets them to Nov 1, 2025 UTC midnight (launch date).

NOTE: Original migration incorrectly used 1730419200 (Nov 1, 2024). Fixed in v1.6.4.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from logging import Logger
    from indexer.database import DatabaseManager
    from indexer.chain_client import ChainClient

MIGRATION_KEY = "v1.6.3_profile_dates"


def run(db: "DatabaseManager", chain: "ChainClient", logger: "Logger") -> str:
    """Backfill missing profile created_at timestamps."""
    # Nov 1, 2025 00:00:00 UTC = 1761955200
    default_created_at = 1761955200
    
    with db._connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE profiles SET created_at = %s WHERE created_at = 0 OR created_at IS NULL",
                (default_created_at,),
            )
            updated_count = cur.rowcount
    
    logger.info(f"v1.6.3 migration: Updated {updated_count} profiles with default created_at")
    return f"completed:{updated_count}"
