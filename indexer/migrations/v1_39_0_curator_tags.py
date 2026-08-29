"""v1.39.0: community-wide curation tags and per-post curator tag overrides."""

from indexer.migrations import run_db_migration

MIGRATION_KEY = "v1.39.0_curator_tags"


def run(db, chain, logger):
    def _migrate(cur):
        cur.execute("ALTER TABLE curation_teams ADD COLUMN IF NOT EXISTS tag TEXT NOT NULL DEFAULT ''")
        # A row here is a curator's explicit decision. tag='' is a real decision
        # ("this post carries no tag"); no row means the team has no opinion and
        # the community tag, then the author's own tag, applies.
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS curation_post_tags (
                community TEXT NOT NULL,
                team_id NUMERIC(20,0) NOT NULL,
                target_txhash TEXT NOT NULL,
                tag TEXT NOT NULL,
                actor TEXT,
                updated_height BIGINT,
                PRIMARY KEY (community, team_id, target_txhash)
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_curation_post_tags_target "
            "ON curation_post_tags(target_txhash)"
        )
        logger.info("[community] v1.39 curator tag schema applied")
        return "curation_teams.tag and curation_post_tags created"

    return run_db_migration(db, MIGRATION_KEY, _migrate, logger)
