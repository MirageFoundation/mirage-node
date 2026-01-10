"""
v1.6.4 Migration: Fix incorrect profile created_at timestamps

The v1.6.3 migration incorrectly used 1730419200 (Nov 1, 2024) instead of
1761955200 (Nov 1, 2025). This migration fixes any profiles set to the wrong date,
and also corrects any created_at that is before the launch date.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from logging import Logger
    from indexer.database import DatabaseManager
    from indexer.chain_client import ChainClient

MIGRATION_KEY = "v1.6.4_fix_created_at"


def run(db: "DatabaseManager", chain: "ChainClient", logger: "Logger") -> str:
    """Fix incorrect profile created_at timestamps."""
    # Nov 1, 2025 00:00:00 UTC = 1761955200 (earliest possible account creation)
    launch_timestamp = 1761955200
    
    with db._connect() as conn:
        with conn.cursor() as cur:
            # Fix any profile with created_at before launch date
            cur.execute(
                "UPDATE profiles SET created_at = %s WHERE created_at < %s AND created_at > 0",
                (launch_timestamp, launch_timestamp),
            )
            updated_count = cur.rowcount
    
    logger.info(f"v1.6.4 migration: Fixed {updated_count} profiles with pre-launch created_at")
    return f"completed:{updated_count}"
