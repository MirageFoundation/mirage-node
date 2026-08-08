"""
Drop the obsolete pending_txs table (indexer review 2026-08-07, I-3).

The indexer stopped reading or writing pending_txs in the v1.33.0 remediation
and fresh databases no longer create it, but deployed ones still carry the
table. Both prod and UAT held zero rows when this was written; the table is
dead weight that still looks like a queue to anyone reading the schema.

IF EXISTS is required rather than defensive: databases created after v1.33.0
never had the table, so the migration must be a no-op there.
"""

from indexer.migrations import run_db_migration

MIGRATION_KEY = "v1.33.2_drop_pending_txs"


def run(db, chain, logger):
    def _drop(cur):
        cur.execute("SELECT to_regclass('public.pending_txs') IS NOT NULL")
        existed = bool(cur.fetchone()[0])
        if not existed:
            return "no pending_txs table present"

        # Counted rather than assumed: a non-empty table would mean something
        # still writes to it, which would contradict the premise for dropping.
        cur.execute("SELECT count(*) FROM pending_txs")
        rows = int(cur.fetchone()[0])
        if rows:
            raise RuntimeError(
                f"pending_txs holds {rows} rows; refusing to drop a table that is not dead. "
                "Investigate what is writing to it before re-running."
            )

        cur.execute("DROP TABLE pending_txs")
        return "dropped pending_txs"

    return run_db_migration(db, MIGRATION_KEY, _drop, logger)
