"""v1.39.0: give pre-upgrade comments the community they were always posted in.

A comment's MsgPost carries no community — the chain derives it from the parent —
so the indexer denormalizes it at write time. Comments indexed before that
denormalization existed still have an empty community, which kept them out of
every community feed and out of the tag precedence rules, since both key off it.

This recovers the value rather than inventing one: first from the root's
denormalized ``root_community``, then by walking up ``target`` to a parent that
has one. Both re-derive identically on a reindex, so nothing here fights the
chain. Comments whose root is not in the database at all keep an empty community;
there is no honest source for those and guessing would file them under the wrong
community forever.
"""

from indexer.migrations import run_db_migration

MIGRATION_KEY = "v1.39.0_legacy_post_community"

# A deep legacy chain has comments nested well past the display cap, but each
# pass only fixes rows whose parent is already resolved, so depth costs passes.
# The loop stops as soon as a pass changes nothing; this is the safety stop.
MAX_PASSES = 12


def run(db, chain, logger):
    def _migrate(cur):
        cur.execute(
            "SELECT count(*) FROM posts WHERE (community IS NULL OR community = '') "
            "AND target IS NOT NULL AND target <> ''"
        )
        before = int(cur.fetchone()[0])
        if not before:
            logger.info("[community] no comments missing a community")
            return "nothing to backfill"

        cur.execute(
            """
            UPDATE posts c
            SET community = c.root_community
            WHERE (c.community IS NULL OR c.community = '')
              AND c.target IS NOT NULL AND c.target <> ''
              AND c.root_community IS NOT NULL AND c.root_community <> ''
            """
        )
        from_root = cur.rowcount

        from_parent = 0
        for _ in range(MAX_PASSES):
            cur.execute(
                """
                UPDATE posts c
                SET community = p.community
                FROM posts p
                WHERE LOWER(p.txhash) = LOWER(c.target)
                  AND (c.community IS NULL OR c.community = '')
                  AND c.target IS NOT NULL AND c.target <> ''
                  AND p.community IS NOT NULL AND p.community <> ''
                """
            )
            if not cur.rowcount:
                break
            from_parent += cur.rowcount

        cur.execute(
            "SELECT count(*) FROM posts WHERE (community IS NULL OR community = '') "
            "AND target IS NOT NULL AND target <> ''"
        )
        remaining = int(cur.fetchone()[0])
        logger.info(
            "[community] legacy comment community backfill: %d from root, %d from parent, %d unresolved (of %d)",
            from_root,
            from_parent,
            remaining,
            before,
        )
        return f"backfilled {before - remaining} of {before} comments; {remaining} have no resolvable root"

    return run_db_migration(db, MIGRATION_KEY, _migrate, logger)
