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

        cur.execute(
            """
            WITH RECURSIVE resolved(txhash, root_txhash, community, path) AS (
                SELECT
                    LOWER(txhash),
                    LOWER(txhash),
                    LOWER(COALESCE(NULLIF(root_community, ''), NULLIF(community, ''))),
                    ARRAY[LOWER(txhash)]
                FROM posts
                WHERE COALESCE(target, '') = ''
                  AND COALESCE(NULLIF(root_community, ''), NULLIF(community, '')) IS NOT NULL
                UNION ALL
                SELECT
                    LOWER(child.txhash),
                    parent.root_txhash,
                    parent.community,
                    parent.path || LOWER(child.txhash)
                FROM resolved parent
                JOIN posts child ON LOWER(child.target) = parent.txhash
                WHERE NOT LOWER(child.txhash) = ANY(parent.path)
            )
            UPDATE posts child
            SET community = COALESCE(NULLIF(child.community, ''), resolved.community),
                root_community = resolved.community,
                root_post_id = COALESCE(child.root_post_id, resolved.root_txhash)
            FROM resolved
            WHERE LOWER(child.txhash) = resolved.txhash
              AND child.target IS NOT NULL
              AND child.target <> ''
              AND (
                child.community IS NULL
                OR child.community = ''
                OR child.root_community IS NULL
                OR child.root_community = ''
                OR child.root_post_id IS NULL
                OR child.root_post_id = ''
              )
            """
        )
        from_parent = cur.rowcount

        cur.execute(
            "SELECT count(*) FROM posts WHERE (community IS NULL OR community = '') "
            "AND target IS NOT NULL AND target <> ''"
        )
        remaining = int(cur.fetchone()[0])
        cur.execute(
            """
            WITH RECURSIVE ancestry(start_hash, current_hash, path, resolved) AS (
                SELECT
                    LOWER(txhash),
                    LOWER(target),
                    ARRAY[LOWER(txhash)],
                    FALSE
                FROM posts
                WHERE (community IS NULL OR community = '')
                  AND target IS NOT NULL
                  AND target <> ''
                UNION ALL
                SELECT
                    ancestry.start_hash,
                    LOWER(parent.target),
                    ancestry.path || LOWER(parent.txhash),
                    COALESCE(NULLIF(parent.community, ''), NULLIF(parent.root_community, '')) IS NOT NULL
                FROM ancestry
                JOIN posts parent ON LOWER(parent.txhash) = ancestry.current_hash
                WHERE NOT ancestry.resolved
                  AND NOT LOWER(parent.txhash) = ANY(ancestry.path)
            )
            SELECT COUNT(DISTINCT start_hash)
            FROM ancestry
            WHERE resolved
            """
        )
        still_resolvable = int(cur.fetchone()[0])
        if still_resolvable:
            raise RuntimeError(
                f"legacy comment migration left {still_resolvable} comments with resolvable ancestors"
            )
        logger.info(
            "[community] legacy comment community backfill: %d from root, %d recursively, %d true orphans (of %d)",
            from_root,
            from_parent,
            remaining,
            before,
        )
        return f"backfilled {before - remaining} of {before} comments; {remaining} have no resolvable root"

    return run_db_migration(db, MIGRATION_KEY, _migrate, logger)
