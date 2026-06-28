"""
One-time migration: drop two dead referral tables that were defined and
migrated but never read or written by any runtime code:

  - referral_trust_scores
  - referral_analysis

They are remnants of a never-finished referral trust/analysis feature.
init_backend_schema() no longer creates them, so this removes the leftover
tables on existing nodes. Idempotent (DROP TABLE IF EXISTS).
"""

from __future__ import annotations

import os

MIGRATION_KEY = "v1.28.5-drop-dead-referral-tables"
DESCRIPTION = "Drop unused referral_trust_scores and referral_analysis tables"

DEAD_TABLES = ["referral_trust_scores", "referral_analysis"]


def run(config_dir, logger):
    import psycopg

    backend_url = os.environ.get("BACKEND_DB_URL", "").strip()
    if not backend_url:
        raise RuntimeError("BACKEND_DB_URL must be set")

    conn = psycopg.connect(backend_url, autocommit=True)
    try:
        cur = conn.cursor()
        dropped = []
        for table in DEAD_TABLES:
            cur.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
            dropped.append(table)
            logger.info(f"  dropped {table}")
    finally:
        conn.close()

    return f"dropped {len(dropped)} dead tables: {', '.join(dropped)}"
