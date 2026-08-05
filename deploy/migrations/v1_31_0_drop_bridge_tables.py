"""
One-time migration: drop the bridge_transactions table (and its indexes via
CASCADE) from the indexer DB. The bridge/orchestrator path is being removed.

Idempotent (DROP TABLE IF EXISTS).
"""

from __future__ import annotations

import os

MIGRATION_KEY = "v1.31.0-drop-bridge-tables"
DESCRIPTION = "Drop unused bridge_transactions table from indexer DB"


def run(config_dir, logger):
    import psycopg

    indexer_url = os.environ.get("INDEXER_DB_URL", "").strip()
    if not indexer_url:
        raise RuntimeError("INDEXER_DB_URL must be set")

    conn = psycopg.connect(indexer_url, autocommit=True)
    try:
        cur = conn.cursor()
        cur.execute("DROP TABLE IF EXISTS bridge_transactions CASCADE")
        logger.info("  dropped bridge_transactions")
    finally:
        conn.close()

    return "dropped bridge_transactions"
