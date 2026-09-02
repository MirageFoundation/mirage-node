"""v1.39.0: rebuild every user_community_stats row from canonical votes/posts.

The comment re-key (`v1.39.0_legacy_vote_standing`) only recomputes owners and
communities that appeared on comments that gained a community. Restored UAT
state still has drifted rows from older attribution bugs, community edits, and
the topic→community rename — 893 (owner, community) pairs disagreed with the
canonical sum after that partial rebuild.

This is the same definition `invariants.net_votes_matches_canonical_votes`
asserts, applied to the whole table. Idempotent: a second run deletes and
rewrites the same rows from the same sources.
"""

from indexer.migrations import run_db_migration

MIGRATION_KEY = "v1.39.0_standing_rebuild"


def run(db, chain, logger):
    del chain  # unused; signature required by the migration runner

    def _migrate(cur):
        # Wipe first so empty-community leftovers the partial re-key could not
        # see are gone. The canonical INSERT then rebuilds every real pair.
        logger.info("[standing] rebuilding all user_community_stats from canonical votes and posts")
        db._rebuild_all_community_stats(cur)
        cur.execute("SELECT count(*) FROM user_community_stats")
        rows = int(cur.fetchone()[0])
        logger.info("[standing] rebuilt user_community_stats rows=%d", rows)
        return f"rebuilt {rows} rows"

    return run_db_migration(db, MIGRATION_KEY, _migrate, logger)
