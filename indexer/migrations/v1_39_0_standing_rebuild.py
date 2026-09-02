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
        cur.execute(
            """
            SELECT
                ARRAY(
                    SELECT DISTINCT owner FROM (
                        SELECT owner FROM user_community_stats
                        UNION
                        SELECT LOWER(v.owner) FROM votes v
                        UNION
                        SELECT LOWER(p.owner)
                        FROM posts p
                        WHERE COALESCE(p.deleted, FALSE) = FALSE
                    ) owners
                    WHERE owner IS NOT NULL AND owner <> ''
                ),
                ARRAY(
                    SELECT DISTINCT community FROM (
                        SELECT community FROM user_community_stats
                        UNION
                        SELECT LOWER(COALESCE(NULLIF(p.root_community, ''), p.community))
                        FROM posts p
                        WHERE COALESCE(NULLIF(p.root_community, ''), p.community) <> ''
                    ) communities
                    WHERE community IS NOT NULL AND community <> ''
                )
            """
        )
        owners, communities = cur.fetchone()
        owners = [o for o in (owners or []) if o]
        communities = [c for c in (communities or []) if c]
        if not owners or not communities:
            logger.info("[standing] nothing to rebuild")
            return "nothing to rebuild"

        logger.info(
            "[standing] rebuilding user_community_stats owners=%d communities=%d",
            len(owners),
            len(communities),
        )
        db._recompute_community_stats(cur, owners, communities)
        cur.execute("SELECT count(*) FROM user_community_stats")
        rows = int(cur.fetchone()[0])
        logger.info("[standing] rebuilt user_community_stats rows=%d", rows)
        return f"rebuilt {rows} rows from {len(owners)} owners across {len(communities)} communities"

    return run_db_migration(db, MIGRATION_KEY, _migrate, logger)
