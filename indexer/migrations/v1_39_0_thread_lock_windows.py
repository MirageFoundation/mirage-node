"""v1.39.0: keep the full lock history of a thread, not just the current lock.

A thread can be locked and unlocked repeatedly. The chain only stores the
cut-off of the window that is open right now, so unlocking used to delete the
row and every reply written while the thread was locked became visible at once.
The history of closed windows lives here instead: lock_windows accumulates
[start, end] pairs in global post-sequence space, and lock_sequence keeps its
meaning of "where the currently open window starts", now NULL when the thread
is not locked.

Rows that already exist describe a lock that is still open, so they backfill to
an empty history with lock_sequence untouched.
"""

from indexer.migrations import run_db_migration

MIGRATION_KEY = "v1.39.0_thread_lock_windows"


def run(db, chain, logger):
    def _migrate(cur):
        cur.execute(
            "ALTER TABLE curation_locks "
            "ADD COLUMN IF NOT EXISTS lock_windows JSONB NOT NULL DEFAULT '[]'::jsonb"
        )
        cur.execute("SELECT count(*) FROM curation_locks WHERE lock_sequence IS NOT NULL")
        open_locks = int(cur.fetchone()[0])
        logger.info(
            "[lock] v1.39 thread lock window history applied; %s open lock(s) carried over",
            open_locks,
        )
        return f"lock_windows added; {open_locks} open locks preserved"

    return run_db_migration(db, MIGRATION_KEY, _migrate, logger)
