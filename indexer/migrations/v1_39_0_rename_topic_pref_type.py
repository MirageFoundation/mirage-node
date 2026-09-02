"""v1.39.0: repoint the stored 'topic' pref_type discriminator onto 'community'.

The table and column renames that go with this live in
`DatabaseManager._init_db`, not here: schema init runs before migrations, so a
`CREATE TABLE IF NOT EXISTS community_content_stats` would create an empty table
and strand the populated `topic_content_stats` beside it. Renaming there, ahead
of the CREATE, is the only ordering that preserves the rows.

This file carries the part that is genuinely data rather than schema: the
`preferences.pref_type` value every feed-personalisation read filters on.
"""

from indexer.migrations import run_db_migration

MIGRATION_KEY = "v1.39.0_rename_topic_pref_type"


def run(db, chain, logger):
    def _migrate(cur):
        cur.execute(
            """
            INSERT INTO preferences(owner, pref_type, target, weight, updated_at)
            SELECT owner, 'community', target, weight, updated_at
            FROM preferences
            WHERE pref_type = 'topic'
            ON CONFLICT(owner, pref_type, target) DO UPDATE SET
                weight = CASE
                    WHEN EXCLUDED.updated_at > preferences.updated_at
                    THEN EXCLUDED.weight
                    ELSE preferences.weight
                END,
                updated_at = GREATEST(EXCLUDED.updated_at, preferences.updated_at)
            """
        )
        merged = cur.rowcount
        cur.execute("DELETE FROM preferences WHERE pref_type = 'topic'")
        removed = cur.rowcount
        cur.execute("DROP TABLE IF EXISTS topic_preferences")
        logger.info(
            "[preferences] merged topic discriminator rows=%d removed_sources=%d",
            merged,
            removed,
        )
        return f"merged {merged} topic preferences; removed {removed} source rows"

    return run_db_migration(db, MIGRATION_KEY, _migrate, logger)
