"""v1.39.0: communities, curation, creator pool, drop agents/topics lists."""

from indexer.migrations import run_db_migration

MIGRATION_KEY = "v1.39.0_communities"


def run(db, chain, logger):
    def _migrate(cur):
        cur.execute(
            """
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'posts' AND column_name = 'topic'
                ) AND NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'posts' AND column_name = 'community'
                ) THEN
                    ALTER TABLE posts RENAME COLUMN topic TO community;
                END IF;
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'posts' AND column_name = 'root_topic'
                ) AND NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'posts' AND column_name = 'root_community'
                ) THEN
                    ALTER TABLE posts RENAME COLUMN root_topic TO root_community;
                END IF;
            END $$;
            """
        )
        cur.execute("ALTER TABLE posts ADD COLUMN IF NOT EXISTS protocol_version SMALLINT NOT NULL DEFAULT 0")
        cur.execute("ALTER TABLE posts ADD COLUMN IF NOT EXISTS root_txhash TEXT")
        cur.execute("ALTER TABLE posts ADD COLUMN IF NOT EXISTS post_sequence NUMERIC(20,0)")
        cur.execute("ALTER TABLE posts ADD COLUMN IF NOT EXISTS created_height BIGINT")
        cur.execute("ALTER TABLE posts ADD COLUMN IF NOT EXISTS created_epoch BIGINT")
        cur.execute("ALTER TABLE posts ADD COLUMN IF NOT EXISTS author_was_paid_at_creation BOOLEAN")
        cur.execute("ALTER TABLE posts ADD COLUMN IF NOT EXISTS deleted_height BIGINT")
        cur.execute("ALTER TABLE posts ADD COLUMN IF NOT EXISTS deleted_epoch BIGINT")
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_posts_community_proto_ts "
            "ON posts(community, protocol_version, created_at DESC, txhash)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_posts_community_root_seq "
            "ON posts(community, root_txhash, post_sequence)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_posts_owner_proto_ts "
            "ON posts(owner, protocol_version, created_at DESC, txhash)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_posts_proto1_epoch "
            "ON posts(txhash, created_epoch) WHERE protocol_version = 1"
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS communities (
                community TEXT PRIMARY KEY,
                original_founder TEXT NOT NULL,
                current_founder TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                original_team_id NUMERIC(20,0) NOT NULL,
                current_default_team_id NUMERIC(20,0),
                default_count NUMERIC(20,0) NOT NULL DEFAULT 0,
                created_height BIGINT NOT NULL,
                created_order NUMERIC(20,0) NOT NULL
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_communities_founder ON communities(current_founder)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_communities_created ON communities(created_order)")

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS curation_teams (
                community TEXT NOT NULL,
                team_id NUMERIC(20,0) NOT NULL,
                owner TEXT NOT NULL,
                name TEXT NOT NULL,
                normalized_name TEXT NOT NULL,
                bio TEXT NOT NULL,
                is_original BOOLEAN NOT NULL,
                subscriber_only BOOLEAN NOT NULL DEFAULT FALSE,
                supporter_count NUMERIC(20,0) NOT NULL DEFAULT 0,
                created_height BIGINT NOT NULL,
                created_order NUMERIC(20,0) NOT NULL,
                deleted_height BIGINT,
                PRIMARY KEY (community, team_id)
            )
            """
        )
        cur.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_curation_teams_live_name "
            "ON curation_teams(community, normalized_name) WHERE deleted_height IS NULL"
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS curation_team_curators (
                community TEXT NOT NULL,
                team_id NUMERIC(20,0) NOT NULL,
                curator TEXT NOT NULL,
                accepted_order NUMERIC(20,0) NOT NULL,
                joined_height BIGINT NOT NULL,
                PRIMARY KEY (community, team_id, curator),
                UNIQUE (community, curator)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS curation_team_invitations (
                community TEXT NOT NULL,
                team_id NUMERIC(20,0) NOT NULL,
                invitee TEXT NOT NULL,
                inviter TEXT NOT NULL,
                status SMALLINT NOT NULL CHECK (status IN (0,1,2,3)),
                created_height BIGINT NOT NULL,
                resolved_height BIGINT,
                PRIMARY KEY (community, team_id, invitee)
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_curation_invites_invitee "
            "ON curation_team_invitations(invitee, status, created_height DESC)"
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS community_curation_preferences (
                owner TEXT NOT NULL,
                community TEXT NOT NULL,
                mode SMALLINT NOT NULL CHECK (mode IN (0,1,2)),
                pinned_team_id NUMERIC(20,0),
                updated_height BIGINT NOT NULL,
                PRIMARY KEY (owner, community),
                CHECK ((mode = 1 AND pinned_team_id IS NOT NULL) OR (mode <> 1 AND pinned_team_id IS NULL))
            )
            """
        )

        cur.execute(
            """
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'followed_topics') THEN
                    INSERT INTO community_curation_preferences (owner, community, mode, pinned_team_id, updated_height)
                    SELECT owner, topic, 0, NULL, 0
                    FROM followed_topics
                    ON CONFLICT (owner, community) DO NOTHING;
                END IF;
            END $$;
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS community_founder_history (
                community TEXT NOT NULL,
                sequence NUMERIC(20,0) NOT NULL,
                height BIGINT NOT NULL,
                tx_hash TEXT,
                old_founder TEXT,
                new_founder TEXT,
                authority TEXT,
                PRIMARY KEY (community, sequence)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS curation_team_history (
                community TEXT NOT NULL,
                team_id NUMERIC(20,0) NOT NULL,
                sequence NUMERIC(20,0) NOT NULL,
                height BIGINT NOT NULL,
                tx_hash TEXT,
                event_type TEXT,
                actor TEXT,
                target TEXT,
                accepted_order NUMERIC(20,0),
                authority TEXT,
                PRIMARY KEY (community, team_id, sequence)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS curation_hidden_posts (
                community TEXT NOT NULL,
                team_id NUMERIC(20,0) NOT NULL,
                target_txhash TEXT NOT NULL,
                actor TEXT,
                updated_height BIGINT,
                PRIMARY KEY (community, team_id, target_txhash)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS curation_hidden_users (
                community TEXT NOT NULL,
                team_id NUMERIC(20,0) NOT NULL,
                target_user TEXT NOT NULL,
                actor TEXT,
                updated_height BIGINT,
                PRIMARY KEY (community, team_id, target_user)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS curation_locks (
                community TEXT NOT NULL,
                team_id NUMERIC(20,0) NOT NULL,
                root_txhash TEXT NOT NULL,
                lock_sequence NUMERIC(20,0),
                actor TEXT,
                updated_height BIGINT,
                PRIMARY KEY (community, team_id, root_txhash)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS curation_action_history (
                height BIGINT NOT NULL,
                event_index INTEGER NOT NULL,
                tx_hash TEXT,
                community TEXT,
                team_id NUMERIC(20,0),
                actor TEXT,
                action TEXT,
                target TEXT,
                active BOOLEAN,
                PRIMARY KEY (height, event_index)
            )
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS creator_epochs (
                epoch_id BIGINT PRIMARY KEY,
                pool NUMERIC(78,0) NOT NULL,
                status SMALLINT NOT NULL,
                phase SMALLINT NOT NULL,
                gross_records NUMERIC(20,0) NOT NULL,
                active_engagers NUMERIC(20,0) NOT NULL,
                engager_slice NUMERIC(78,0) NOT NULL,
                allocated_total NUMERIC(78,0) NOT NULL,
                claimed_total NUMERIC(78,0) NOT NULL,
                finalized_epoch BIGINT,
                claim_window_days BIGINT,
                claim_deadline_epoch BIGINT,
                settlement_cursor BYTEA,
                partial_actor TEXT,
                partial_count NUMERIC(20,0) NOT NULL DEFAULT 0,
                prune_pending BOOLEAN NOT NULL DEFAULT FALSE,
                prune_complete BOOLEAN NOT NULL DEFAULT FALSE,
                updated_height BIGINT NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS creator_target_earnings (
                epoch_id BIGINT NOT NULL,
                target_txhash TEXT NOT NULL,
                creator TEXT NOT NULL,
                upvote_units NUMERIC(20,0) NOT NULL DEFAULT 0,
                direct_reply_units NUMERIC(20,0) NOT NULL DEFAULT 0,
                amount NUMERIC(78,0) NOT NULL,
                PRIMARY KEY (epoch_id, target_txhash)
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_creator_target_creator ON creator_target_earnings(creator, epoch_id)"
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS creator_accruals (
                creator TEXT NOT NULL,
                epoch_id BIGINT NOT NULL,
                earned NUMERIC(78,0) NOT NULL,
                claimed NUMERIC(78,0) NOT NULL DEFAULT 0,
                claim_deadline_epoch BIGINT,
                claimed_height BIGINT,
                claimed_txhash TEXT,
                PRIMARY KEY (creator, epoch_id)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS creator_claims (
                tx_hash TEXT PRIMARY KEY,
                creator TEXT NOT NULL,
                epoch_ids NUMERIC(20,0)[] NOT NULL,
                amount NUMERIC(78,0) NOT NULL,
                height BIGINT NOT NULL,
                created_at BIGINT NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS subscription_tranches (
                tranche_id NUMERIC(20,0) PRIMARY KEY,
                payer TEXT NOT NULL,
                recipient TEXT NOT NULL,
                source SMALLINT NOT NULL,
                period_count INTEGER NOT NULL,
                start_time BIGINT NOT NULL,
                end_time BIGINT NOT NULL,
                total_fee NUMERIC(78,0) NOT NULL,
                burn_amount NUMERIC(78,0) NOT NULL,
                creator_amount NUMERIC(78,0) NOT NULL,
                creator_bps INTEGER NOT NULL,
                created_height BIGINT NOT NULL,
                tx_hash TEXT
            )
            """
        )

        cur.execute("ALTER TABLE profiles ADD COLUMN IF NOT EXISTS effective_paid BOOLEAN NOT NULL DEFAULT FALSE")
        cur.execute("ALTER TABLE profiles ADD COLUMN IF NOT EXISTS subscriber_quota_epoch BIGINT")
        cur.execute("ALTER TABLE profiles ADD COLUMN IF NOT EXISTS subscriber_quota_used NUMERIC(20,0)")
        cur.execute("ALTER TABLE profiles ADD COLUMN IF NOT EXISTS renewal_next_attempt BIGINT")
        cur.execute("ALTER TABLE profiles ADD COLUMN IF NOT EXISTS renewal_last_attempt_epoch BIGINT")
        cur.execute("ALTER TABLE profiles ADD COLUMN IF NOT EXISTS renewal_warning_expiry BIGINT")
        cur.execute("ALTER TABLE profiles ADD COLUMN IF NOT EXISTS renewal_warning_sent BOOLEAN NOT NULL DEFAULT FALSE")

        cur.execute(
            """
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.tables WHERE table_name = 'blocked_topics'
                ) AND NOT EXISTS (
                    SELECT 1 FROM information_schema.tables WHERE table_name = 'blocked_communities'
                ) THEN
                    ALTER TABLE blocked_topics RENAME TO blocked_communities;
                    IF EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'blocked_communities' AND column_name = 'topic'
                    ) THEN
                        ALTER TABLE blocked_communities RENAME COLUMN topic TO community;
                    END IF;
                END IF;
            END $$;
            """
        )

        cur.execute("DROP TABLE IF EXISTS followed_topics")
        cur.execute("DROP TABLE IF EXISTS enabled_agents")
        cur.execute("DROP TABLE IF EXISTS agent_edits")
        cur.execute("INSERT INTO meta(key, value) VALUES('schema_v1_39_0', 'complete') ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value")
        return "v1.39.0 communities schema applied"

    return run_db_migration(db, MIGRATION_KEY, _migrate, logger)
