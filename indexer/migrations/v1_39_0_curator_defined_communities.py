"""v1.39.0: remove claimed-community state and finalize curator projections."""

from indexer.migrations import run_db_migration

MIGRATION_KEY = "v1.39.0_curator_defined_communities"


def run(db, chain, logger):
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

        chain_teams = chain.list_all_curation_teams(include_deleted=True)
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
            members = chain.query_curation_team_members(team["community"], team["team_id"])
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

        # Paid/relay quota projection lives in v1_39_0_quota_paid_backfill.
        # This migration used to SELECT effective_paid=TRUE here, but that
        # column is still the DEFAULT FALSE from v1_39_0_communities at this
        # point in startup (KV sync runs only after all migrations), so the
        # loop always projected 0 paid profiles on real upgrades. Keep the
        # counter for the completion log/return string.
        paid_owners: list[str] = []

        cur.execute(
            """
            WITH expected AS (
                SELECT
                    t.community,
                    t.team_id,
                    COUNT(pr.owner)::NUMERIC(20,0) AS subscriber_count
                FROM curation_teams t
                LEFT JOIN community_curation_preferences p
                  ON p.community=t.community
                 AND p.mode=1
                 AND p.pinned_team_id=t.team_id
                LEFT JOIN profiles pr
                  ON LOWER(pr.owner)=LOWER(p.owner)
                 AND (pr.effective_paid=TRUE OR pr.level >= 100)
                WHERE t.deleted_height IS NULL
                GROUP BY t.community, t.team_id
            )
            UPDATE curation_teams t
            SET subscriber_count=e.subscriber_count
            FROM expected e
            WHERE t.community=e.community AND t.team_id=e.team_id
            """
        )
        cur.execute(
            """
            UPDATE curation_teams
            SET subscriber_count=0
            WHERE deleted_height IS NOT NULL AND subscriber_count<>0
            """
        )
        cur.execute(
            """
            SELECT community, team_id, subscriber_count
            FROM curation_teams
            ORDER BY community, team_id
            """
        )
        for community, team_id, subscriber_count in cur.fetchall():
            chain_team = chain.query_curation_team(community, int(team_id))
            chain_count = int(chain_team["subscriber_count"])
            if chain_count != int(subscriber_count):
                raise RuntimeError(
                    "curation subscriber count mismatch "
                    f"{community}/{team_id}: indexer={subscriber_count} chain={chain_count}"
                )

        # Column is still author_was_paid_at_creation here; the rename
        # migration (v1_39_0_was_subscriber_at_creation) runs after this file.
        cur.execute(
            """
            SELECT txhash
            FROM posts
            WHERE protocol_version=1
              AND (
                root_txhash IS NULL
                OR post_sequence IS NULL
                OR created_height IS NULL
                OR created_epoch IS NULL
                OR author_was_paid_at_creation IS NULL
              )
            ORDER BY created_at, txhash
            """
        )
        missing = [str(row[0]).lower() for row in cur.fetchall()]
        for txhash in missing:
            metadata = chain.query_post_metadata(txhash)
            cur.execute(
                """
                UPDATE posts
                SET community=%s,
                    root_community=%s,
                    root_txhash=%s,
                    root_post_id=%s,
                    post_sequence=%s,
                    created_height=%s,
                    created_epoch=%s,
                    author_was_paid_at_creation=%s,
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
            "[community] v1.39 cleanup projected %d teams, %d paid profiles, and backfilled %d protocol-1 posts",
            len(chain_teams),
            len(paid_owners),
            len(missing),
        )
        return (
            "curator-defined communities cleanup applied; "
            f"teams={len(chain_teams)} paid_profiles={len(paid_owners)} "
            f"post_metadata_backfilled={len(missing)}"
        )

    return run_db_migration(db, MIGRATION_KEY, _migrate, logger)
