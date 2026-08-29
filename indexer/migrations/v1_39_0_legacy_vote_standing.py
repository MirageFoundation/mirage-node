"""v1.39.0: re-key the standing earned on comments that just gained a community.

``user_topic_stats`` keys on ``COALESCE(NULLIF(root_community,''), community)``,
so a comment carrying neither contributed its votes and its post count to no
community at all. The legacy community backfill gives those comments the one
they were always posted in, which moves that standing into a real bucket and
strands every delta already accumulated under the old key.

This is deliberately a separate migration rather than a step inside the backfill:
databases that already ran the backfill have its marker written, so a fix folded
into it would never execute there.

The affected rows stay identifiable afterwards — the backfill only ever sets
``community``, never ``root_community`` — so the set is recovered from current
state instead of from anything captured mid-update, and re-running is a no-op.
"""

from indexer.migrations import run_db_migration

MIGRATION_KEY = "v1.39.0_legacy_vote_standing"


def run(db, chain, logger):
    def _migrate(cur):
        cur.execute(
            """
            CREATE TEMP TABLE _rekeyed_comments ON COMMIT DROP AS
            SELECT LOWER(txhash) AS txhash,
                   LOWER(owner) AS owner,
                   LOWER(community) AS community
            FROM posts
            WHERE target IS NOT NULL AND target <> ''
              AND (root_community IS NULL OR root_community = '')
              AND community IS NOT NULL AND community <> ''
            """
        )
        cur.execute("SELECT count(*) FROM _rekeyed_comments")
        rekeyed = int(cur.fetchone()[0])
        if not rekeyed:
            logger.info("[community] no re-keyed comments; vote standing untouched")
            return "nothing to recompute"

        # Both the voter and the author earn standing in a community, so a comment
        # that changed community invalidates rows for whoever voted on it as well
        # as for who wrote it.
        cur.execute(
            """
            SELECT
                ARRAY(
                    SELECT DISTINCT o FROM (
                        SELECT owner AS o FROM _rekeyed_comments
                        UNION
                        SELECT LOWER(v.owner)
                        FROM votes v
                        JOIN _rekeyed_comments r ON LOWER(v.target) = r.txhash
                    ) owners WHERE o IS NOT NULL AND o <> ''
                ),
                ARRAY(SELECT DISTINCT community FROM _rekeyed_comments)
            """
        )
        owners, topics = cur.fetchone()
        owners = [o for o in (owners or [])]
        topics = [t for t in (topics or [])]
        if not owners or not topics:
            logger.info("[community] re-keyed comments have no owners or communities")
            return "nothing to recompute"

        # Recomputing from the canonical tables is what the live edit and delete
        # paths already do, and it is the definition
        # indexer_hardening.net_votes_matches_canonical_votes asserts against. A
        # hand-rolled reversal here would only be a second definition to keep in
        # sync with that one.
        db._recompute_topic_stats(cur, owners, topics)
        logger.info(
            "[community] re-keyed standing from %d comments: recomputed %d owners across %d communities",
            rekeyed,
            len(owners),
            len(topics),
        )
        return f"recomputed {len(owners)} owners across {len(topics)} communities from {rekeyed} re-keyed comments"

    return run_db_migration(db, MIGRATION_KEY, _migrate, logger)
