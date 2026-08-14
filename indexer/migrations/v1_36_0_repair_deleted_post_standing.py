"""
Retract the topic standing granted by posts that were later deleted.

Until v1.36.0 `delete_post` soft-deleted the post row and its descendants and
fixed ancestor comment counts, but left `user_topic_stats` carrying the deltas
applied when the post was first indexed — the +1 `post_count` and the author's
post-time auto-upvote. Posting and deleting in a loop therefore accumulated the
standing that gates downvote weight, while leaving no visible content behind.

`delete_post` now recomputes the affected rows from the canonical tables, and the
canonical vote definition in `database.py` excludes an author's own vote on their
own deleted post. This migration applies that definition once to the rows written
before the fix.

Scoped to the (owner, topic) pairs that actually have deleted posts, and reuses
the live recompute helper so there stays exactly one definition of a stats row.
The frozen copy inside v1_33_0 is deliberately left alone: applied migration files
are checksum-pinned and editing one is a hard startup failure, so v1_33_0 keeps
rebuilding with the semantics of its own release and this migration supersedes it.

Idempotent: running it again recomputes the same values.
"""

from indexer.migrations import run_db_migration

MIGRATION_KEY = "v1.36.0_repair_deleted_post_standing"


def run(db, chain, logger):
    del chain  # unused; signature required by the migration runner

    def _repair(cur):
        cur.execute(
            """
            SELECT DISTINCT LOWER(owner), LOWER(COALESCE(NULLIF(root_topic, ''), topic))
            FROM posts
            WHERE COALESCE(deleted, FALSE) = TRUE
              AND COALESCE(owner, '') <> ''
              AND COALESCE(NULLIF(root_topic, ''), topic) <> ''
            """
        )
        pairs = [(r[0], r[1]) for r in cur.fetchall() if r[0] and r[1]]
        if not pairs:
            return "no deleted posts; nothing to retract"

        owners = sorted({o for o, _ in pairs})
        topics = sorted({t for _, t in pairs})
        db._recompute_topic_stats(cur, owners, topics)
        logger.info(
            "repair_deleted_post_standing owners=%s topics=%s pairs=%s",
            len(owners),
            len(topics),
            len(pairs),
        )

        # Every repaired row must now count only live posts. The rebuild is the
        # canonical definition, so a surviving mismatch means the two disagree —
        # that has to surface rather than be recorded as done.
        cur.execute(
            """
            SELECT COUNT(*) FROM (
                SELECT s.owner, s.topic
                FROM user_topic_stats s
                LEFT JOIN (
                    SELECT LOWER(p.owner) AS owner,
                           LOWER(COALESCE(NULLIF(p.root_topic, ''), p.topic)) AS topic,
                           COUNT(*)::int AS live
                    FROM posts p
                    WHERE COALESCE(p.deleted, FALSE) = FALSE
                    GROUP BY 1, 2
                ) d ON d.owner = s.owner AND d.topic = s.topic
                WHERE s.owner = ANY(%s) AND s.topic = ANY(%s)
                  AND s.post_count <> COALESCE(d.live, 0)
            ) mismatched
            """,
            (owners, topics),
        )
        remaining = int(cur.fetchone()[0])
        if remaining:
            raise RuntimeError(f"post_count still disagrees with live posts for {remaining} row(s) after repair")

        return f"retracted standing across {len(owners)} owner(s) and {len(topics)} topic(s)"

    return run_db_migration(db, MIGRATION_KEY, _repair, logger)
