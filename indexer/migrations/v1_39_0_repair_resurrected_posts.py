"""Re-delete posts that an edit brought back, and rebuild the standing they skewed.

`upsert_post` writes `deleted` from its argument, which defaults to False, and
the MsgEdit handler called it without passing the stored flag. The chain keeps no
post body and so accepts an edit naming a deleted post, which means any author
could delete a post and then edit it to republish it. Two things went wrong at
once: the post reappeared in every feed, and `user_community_stats` stayed short,
because `delete_post` had already recomputed the row from the canonical tables
and an edit applies no delta. That is the drift
`indexer_hardening.net_votes_matches_canonical_votes` reports.

`deleted_height` is the repair key. It is only ever written by
`update_post_protocol_metadata` from the chain's own `PostMetadata`, and the
edit path never touched it, so `deleted = FALSE AND deleted_height IS NOT NULL`
means the indexer disagrees with the chain about whether the post is deleted.
Restoring the flag makes the projection match chain state again.

Only protocol-1 posts carry `deleted_height`, so a legacy post revived this way
is not recoverable here — nothing in the row records that it was ever deleted.
The handler fix stops any further ones.

Idempotent: once the flags are restored the selection is empty.
"""

from indexer.migrations import run_db_migration

MIGRATION_KEY = "v1.39.0_repair_resurrected_posts"


def run(db, chain, logger):
    del chain  # unused; signature required by the migration runner

    def _repair(cur):
        # Collect the affected standing keys before flipping the flag: the
        # canonical vote definition excludes an author's own vote on their own
        # deleted post, so these rows change meaning once `deleted` is restored.
        cur.execute(
            """
            SELECT DISTINCT LOWER(owner), LOWER(COALESCE(NULLIF(root_community, ''), community))
            FROM posts
            WHERE COALESCE(deleted, FALSE) = FALSE
              AND deleted_height IS NOT NULL
              AND COALESCE(owner, '') <> ''
              AND COALESCE(NULLIF(root_community, ''), community) <> ''
            """
        )
        pairs = [(r[0], r[1]) for r in cur.fetchall() if r[0] and r[1]]

        cur.execute(
            """
            UPDATE posts SET deleted = TRUE
            WHERE COALESCE(deleted, FALSE) = FALSE AND deleted_height IS NOT NULL
            """
        )
        restored = cur.rowcount
        if not restored:
            return "no resurrected posts; nothing to re-delete"

        owners = sorted({o for o, _ in pairs})
        communities = sorted({t for _, t in pairs})
        if owners and communities:
            db._recompute_community_stats(cur, owners, communities)

        logger.info(
            "repair_resurrected_posts re-deleted=%s owners=%s communities=%s",
            restored,
            len(owners),
            len(communities),
        )

        # The rebuild is the canonical definition, so a surviving disagreement
        # means the live path and the canonical query no longer match. Surface it
        # instead of recording the migration as done.
        if owners and communities:
            cur.execute(
                """
                SELECT COUNT(*) FROM (
                    SELECT s.owner, s.community
                    FROM user_community_stats s
                    LEFT JOIN (
                        SELECT LOWER(v.owner) AS owner,
                               LOWER(COALESCE(NULLIF(p.root_community, ''), p.community)) AS community,
                               SUM(CASE
                                   WHEN v.user_vote > 0 THEN 1
                                   WHEN v.user_vote < 0 THEN -1
                                   ELSE 0
                               END)::int AS net
                        FROM votes v
                        JOIN posts p ON LOWER(p.txhash) = LOWER(v.target)
                        WHERE COALESCE(NULLIF(p.root_community, ''), p.community) <> ''
                          AND NOT (COALESCE(p.deleted, FALSE) AND LOWER(v.owner) = LOWER(p.owner))
                        GROUP BY 1, 2
                    ) d ON d.owner = s.owner AND d.community = s.community
                    WHERE s.owner = ANY(%s) AND s.community = ANY(%s)
                      AND s.net_votes <> COALESCE(d.net, 0)
                ) mismatched
                """,
                (owners, communities),
            )
            remaining = int(cur.fetchone()[0])
            if remaining:
                raise RuntimeError(f"net_votes still disagrees with canonical votes for {remaining} row(s) after repair")

        return f"re-deleted {restored} post(s); rebuilt standing for {len(owners)} owner(s)"

    return run_db_migration(db, MIGRATION_KEY, _repair, logger)
