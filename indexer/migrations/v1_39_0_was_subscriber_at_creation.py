"""v1.39.0: rename posts.author_was_paid_at_creation → was_subscriber_at_creation.

The flag means the author was an active subscriber when the post was created
(EffectivePaid snapshot), not that they earned creator-pool payouts. Proto field
8 was renamed the same way (wire-compatible).
"""

from indexer.migrations import run_db_migration

MIGRATION_KEY = "v1.39.0_was_subscriber_at_creation"

_OLD = "author_was_paid_at_creation"
_NEW = "was_subscriber_at_creation"


def run(db, chain, logger):
    def _has_column(cur, name: str) -> bool:
        cur.execute(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = 'posts'
              AND column_name = %s
            """,
            (name,),
        )
        return cur.fetchone() is not None

    def _migrate(cur):
        has_old = _has_column(cur, _OLD)
        has_new = _has_column(cur, _NEW)
        if has_old and not has_new:
            cur.execute(f"ALTER TABLE posts RENAME COLUMN {_OLD} TO {_NEW}")
            logger.info("[posts] renamed %s → %s", _OLD, _NEW)
            return f"renamed {_OLD} to {_NEW}"
        if has_old and has_new:
            # _init_db may have added the new name beside the populated old column.
            cur.execute(
                f"""
                SELECT COUNT(*) FROM posts
                WHERE {_OLD} IS NOT NULL
                  AND {_NEW} IS NOT NULL
                  AND {_OLD} IS DISTINCT FROM {_NEW}
                """
            )
            conflicts = int(cur.fetchone()[0])
            if conflicts:
                raise RuntimeError(
                    f"posts.{_OLD} and posts.{_NEW} disagree on {conflicts} rows"
                )
            cur.execute(
                f"""
                UPDATE posts
                SET {_NEW} = {_OLD}
                WHERE {_NEW} IS NULL AND {_OLD} IS NOT NULL
                """
            )
            copied = cur.rowcount
            cur.execute(f"ALTER TABLE posts DROP COLUMN {_OLD}")
            logger.info(
                "[posts] merged %s into %s (copied=%s) and dropped old column",
                _OLD,
                _NEW,
                copied,
            )
            return f"merged {_OLD} into {_NEW} copied={copied}"
        if has_new and not has_old:
            logger.info("[posts] %s already present; nothing to rename", _NEW)
            return f"{_NEW} already present"
        raise RuntimeError(f"posts missing both {_OLD} and {_NEW}")

    return run_db_migration(db, MIGRATION_KEY, _migrate, logger)
