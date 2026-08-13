"""
Repair vote/post standing left on the wrong topic by earlier root-topic edits.

`user_topic_stats` is maintained by deltas, but its meaning is defined by the
topic a post row carries now. Until v1.34.0, an edit that changed a root post's
topic recomputed `topic_content_stats` for both topics and moved nothing else, so
every delta already applied under the old topic — including the author's
post-time auto-upvote — stayed there permanently. Two rows were still drifted
when this was written: one topic read 3 against a canonical 2, another 8 against
9, from a post created in one topic and edited into another 35 seconds later.

Descendant comments are the second half of the same gap: they denormalise
`root_topic` at creation, so a root topic edit never reached them and a thread
could end up split across two topics. Those are corrected first, because the
canonical attribution of a vote on a comment is read from the comment's own row,
so the stats rebuild is only correct once the comments agree with their root.

The stats themselves are then rebuilt from the canonical tables by the v1.33.0
helpers rather than re-derived here, so there is exactly one definition of a
stats row in the tree. Idempotent: running it again recomputes the same values.
"""

from indexer.migrations import run_db_migration
from indexer.migrations.v1_33_0_rebuild_derived_stats import (
    _rebuild_preferences,
    _rebuild_topic_content_stats,
    _rebuild_user_topic_stats,
)

MIGRATION_KEY = "v1.34.0_repair_topic_attribution"


def run(db, chain, logger):
    del chain  # unused; signature required by the migration runner

    def _repair(cur):
        # Comments whose denormalised root_topic no longer matches the root post
        # they belong to. Root posts are excluded: theirs is authoritative.
        cur.execute(
            """
            UPDATE posts c
            SET root_topic = r.root_topic
            FROM posts r
            WHERE LOWER(c.root_post_id) = LOWER(r.txhash)
              AND LOWER(c.txhash) <> LOWER(r.txhash)
              AND COALESCE(r.root_topic, '') <> ''
              AND LOWER(COALESCE(c.root_topic, '')) <> LOWER(r.root_topic)
            """
        )
        comments_realigned = cur.rowcount
        logger.info("repair_topic_attribution comments_realigned=%s", comments_realigned)

        _rebuild_user_topic_stats(cur, logger)
        _rebuild_topic_content_stats(cur, logger)
        _rebuild_preferences(cur, logger)

        cur.execute(
            """
            SELECT COUNT(*) FROM (
                SELECT s.owner, s.topic
                FROM user_topic_stats s
                LEFT JOIN (
                    SELECT LOWER(v.owner) AS owner,
                           LOWER(COALESCE(NULLIF(p.root_topic, ''), p.topic)) AS topic,
                           SUM(CASE WHEN v.user_vote > 0 THEN 1 WHEN v.user_vote < 0 THEN -1 ELSE 0 END)::int AS net
                    FROM votes v
                    JOIN posts p ON LOWER(p.txhash) = LOWER(v.target)
                    WHERE COALESCE(NULLIF(p.root_topic, ''), p.topic) <> ''
                    GROUP BY 1, 2
                ) d ON d.owner = s.owner AND d.topic = s.topic
                WHERE s.net_votes <> COALESCE(d.net, 0)
            ) mismatched
            """
        )
        remaining = int(cur.fetchone()[0])
        if remaining:
            # The rebuild is the canonical definition, so a surviving mismatch
            # means the two disagree — that must surface, not be recorded as done.
            raise RuntimeError(f"net_votes still disagrees with canonical votes for {remaining} row(s) after repair")

        return f"realigned {comments_realigned} comment(s) and rebuilt derived stats"

    return run_db_migration(db, MIGRATION_KEY, _repair, logger)
