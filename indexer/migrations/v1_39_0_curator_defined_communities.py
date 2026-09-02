"""v1.39.0: remove claimed-community state and finalize curator projections."""

from indexer.migrations import run_db_migration

MIGRATION_KEY = "v1.39.0_curator_defined_communities"


def run(db, chain, logger):
    chain_teams = chain.list_all_curation_teams(include_deleted=True)
    members_by_team = {
        (team["community"], team["team_id"]): chain.query_curation_team_members(
            team["community"], team["team_id"]
        )
        for team in chain_teams
    }

    with db._connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name='posts'
                  AND column_name IN ('was_subscriber_at_creation', 'author_was_paid_at_creation')
                """
            )
            creation_flag_columns = {str(row[0]) for row in cur.fetchall()}
            if "was_subscriber_at_creation" in creation_flag_columns:
                creation_flag_column = "was_subscriber_at_creation"
            elif "author_was_paid_at_creation" in creation_flag_columns:
                creation_flag_column = "author_was_paid_at_creation"
            else:
                raise RuntimeError("posts is missing the subscriber-at-creation column")
            cur.execute(
                f"""
                SELECT txhash
                FROM posts
                WHERE protocol_version=1
                  AND (
                    root_txhash IS NULL
                    OR post_sequence IS NULL
                    OR created_height IS NULL
                    OR created_epoch IS NULL
                    OR {creation_flag_column} IS NULL
                  )
                ORDER BY created_at, txhash
                """
            )
            missing = [str(row[0]).lower() for row in cur.fetchall()]

    post_metadata = {txhash: chain.query_post_metadata(txhash) for txhash in missing}
    logger.info(
        "[community] prefetched migration snapshots teams=%d members=%d posts=%d",
        len(chain_teams),
        sum(len(members) for members in members_by_team.values()),
        len(post_metadata),
    )

    def _migrate(cur):
        cur.execute(
            """
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name='curation_teams' AND column_name='supporter_count'
                ) AND NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name='curation_teams' AND column_name='subscriber_count'
                ) THEN
                    ALTER TABLE curation_teams RENAME COLUMN supporter_count TO subscriber_count;
                END IF;
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name='curation_teams' AND column_name='bio'
                ) AND NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name='curation_teams' AND column_name='description'
                ) THEN
                    ALTER TABLE curation_teams RENAME COLUMN bio TO description;
                END IF;
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name='curation_teams' AND column_name='is_original'
                ) THEN
                    ALTER TABLE curation_teams DROP COLUMN is_original;
                END IF;
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name='curation_teams' AND column_name='policy'
                ) THEN
                    ALTER TABLE curation_teams DROP COLUMN policy;
                END IF;
            END $$;
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_curation_teams_live_default
            ON curation_teams(
                community,
                subscriber_count DESC,
                created_order ASC,
                team_id ASC
            )
            WHERE deleted_height IS NULL
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_curation_teams_live_lookup
            ON curation_teams(community, team_id)
            WHERE deleted_height IS NULL
            """
        )

        chain_team_keys = {(team["community"], team["team_id"]) for team in chain_teams}
        for team in chain_teams:
            cur.execute(
                """
                INSERT INTO curation_teams(
                    community, team_id, owner, name, normalized_name, description,
                    subscriber_only, subscriber_count, created_height, created_order, deleted_height
                ) VALUES(%s,%s,%s,%s,LOWER(TRIM(%s)),%s,%s,%s,%s,%s,NULLIF(%s,0))
                ON CONFLICT(community, team_id) DO UPDATE SET
                    owner=EXCLUDED.owner,
                    name=EXCLUDED.name,
                    normalized_name=EXCLUDED.normalized_name,
                    description=EXCLUDED.description,
                    subscriber_only=EXCLUDED.subscriber_only,
                    subscriber_count=EXCLUDED.subscriber_count,
                    created_height=EXCLUDED.created_height,
                    created_order=EXCLUDED.created_order,
                    deleted_height=EXCLUDED.deleted_height
                """,
                (
                    team["community"],
                    team["team_id"],
                    team["owner"],
                    team["name"],
                    team["name"],
                    team["description"],
                    team["subscriber_only"],
                    team["subscriber_count"],
                    team["created_height"],
                    team["created_order"],
                    team["deleted_height"],
                ),
            )
            members = members_by_team[(team["community"], team["team_id"])]
            cur.execute(
                "DELETE FROM curation_team_curators WHERE community=%s AND team_id=%s",
                (team["community"], team["team_id"]),
            )
            if members:
                cur.executemany(
                    """
                    INSERT INTO curation_team_curators(
                        community, team_id, curator, accepted_order, joined_height
                    ) VALUES(%s,%s,%s,%s,%s)
                    """,
                    [
                        (
                            team["community"],
                            team["team_id"],
                            member["address"],
                            member["accepted_order"],
                            team["created_height"],
                        )
                        for member in members
                    ],
                )
        cur.execute("SELECT community, team_id FROM curation_teams")
        db_team_keys = {(str(row[0]), int(row[1])) for row in cur.fetchall()}
        if db_team_keys != chain_team_keys:
            raise RuntimeError(
                "curation team key mismatch after backfill: "
                f"indexer_only={sorted(db_team_keys - chain_team_keys)} "
                f"chain_only={sorted(chain_team_keys - db_team_keys)}"
            )

        for txhash in missing:
            metadata = post_metadata[txhash]
            cur.execute(
                f"""
                UPDATE posts
                SET community=%s,
                    root_community=%s,
                    root_txhash=%s,
                    root_post_id=%s,
                    post_sequence=%s,
                    created_height=%s,
                    created_epoch=%s,
                    {creation_flag_column}=%s,
                    deleted_height=NULLIF(%s,0),
                    deleted_epoch=NULLIF(%s,0)
                WHERE LOWER(txhash)=%s AND protocol_version=1
                """,
                (
                    metadata["community"],
                    metadata["community"],
                    metadata["root_hash"],
                    metadata["root_hash"],
                    metadata["global_sequence"],
                    metadata["created_height"],
                    metadata["created_epoch"],
                    metadata["was_subscriber_at_creation"],
                    metadata["deleted_height"],
                    metadata["deleted_epoch"],
                    txhash,
                ),
            )
            if cur.rowcount != 1:
                raise RuntimeError(f"post metadata backfill target disappeared: {txhash}")

        cur.execute("DROP TABLE IF EXISTS community_founder_history")
        cur.execute("DROP TABLE IF EXISTS communities")
        cur.execute(
            """
            INSERT INTO meta(key, value)
            VALUES('schema_v1_39_0_curator_defined_communities', 'complete')
            ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value
            """
        )
        logger.info(
            "[community] v1.39 cleanup projected %d teams and backfilled %d protocol-1 posts",
            len(chain_teams),
            len(missing),
        )
        return (
            "curator-defined communities cleanup applied; "
            f"teams={len(chain_teams)} post_metadata_backfilled={len(missing)}"
        )

    return run_db_migration(db, MIGRATION_KEY, _migrate, logger)
