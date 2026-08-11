"""
Delete the orphaned indexer_state.last_processed_height row.

The v1.33.0 rework made `meta.last_height` the single height authority, written
atomically with the block it describes. Nothing has written or read
`indexer_state.last_processed_height` since, but deployed databases still carry
the last value it held — 98k blocks behind head on UAT when this was written.

It is not harmless debris. `docs/troubleshooting/divergence-recovery.md` told
operators to watch exactly that key to see a recovery gap close, so during an
incident it shows a permanently frozen height and invites the conclusion that
the indexer is stuck when it is at zero lag. The runbook now reads
`meta.last_height`; this removes the misleading row behind it.

Unlike v1.33.2, there is deliberately no "refuse if it looks alive" guard. No
code path writes the key, so any value is stale by definition, and a migration
failure is fatal to indexer startup — a cosmetic cleanup must never be able to
put a node into a restart loop. The old value goes into the result string, so
it stays recoverable from the migration marker and the logs.
"""

from indexer.migrations import run_db_migration

MIGRATION_KEY = "v1.33.8_drop_stale_indexer_state_height"


def run(db, chain, logger):
    def _drop(cur):
        cur.execute("SELECT value FROM indexer_state WHERE key = %s", ("last_processed_height",))
        row = cur.fetchone()
        if not row:
            return "no stale last_processed_height row"

        stale_value = str(row[0])
        cur.execute("SELECT value FROM meta WHERE key = %s", ("last_height",))
        meta_row = cur.fetchone()
        authoritative = str(meta_row[0]) if meta_row else "unset"

        cur.execute("DELETE FROM indexer_state WHERE key = %s", ("last_processed_height",))
        logger.info(
            "Dropped stale indexer_state.last_processed_height=%s (meta.last_height=%s)",
            stale_value,
            authoritative,
        )
        return f"dropped stale last_processed_height={stale_value} (meta.last_height={authoritative})"

    return run_db_migration(db, MIGRATION_KEY, _drop, logger)
