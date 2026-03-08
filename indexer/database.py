"""PostgreSQL database operations for the indexer (hard-fail, no fallbacks)."""

from __future__ import annotations

import logging
from typing import Optional, Tuple

import psycopg

logger = logging.getLogger(__name__)

INDEXER_LIST_CAP = 100_000


class DatabaseManager:
    """Manages all database operations for the indexer."""

    # Allowed content tags for topic safety classification
    _ALLOWED_TOPIC_TAGS = {"sensitive", "gore", "violence", "death", "porn"}

    def __init__(self, db_url: str):
        if not db_url or not isinstance(db_url, str):
            raise RuntimeError("database_url is required")
        self.database_url = db_url
        self._init_db()

    def _connect(self) -> psycopg.Connection:
        """Create a new PostgreSQL connection with autocommit enabled."""
        return psycopg.connect(self.database_url, autocommit=True)

    def _init_db(self) -> None:
        """Initialize PostgreSQL schema (idempotent)."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                # meta
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS meta (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    )
                    """
                )
                cur.execute("INSERT INTO meta(key, value) VALUES('last_height','0') ON CONFLICT (key) DO NOTHING")

                # posts (with tag column for v1.5, root_topic/root_post_id for v2 feeds)
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS posts (
                        txhash TEXT PRIMARY KEY,
                        owner TEXT NOT NULL,
                        topic TEXT,
                        title TEXT,
                        content TEXT,
                        target TEXT,
                        created_at BIGINT NOT NULL,
                        edited_at BIGINT,
                        paid BOOLEAN NOT NULL DEFAULT FALSE,
                        deleted BOOLEAN NOT NULL DEFAULT FALSE,
                        thumbnail_url TEXT,
                        tag TEXT NOT NULL DEFAULT '',
                        root_topic TEXT,
                        root_post_id TEXT,
                        comment_count INTEGER NOT NULL DEFAULT 0,
                        media TEXT NOT NULL DEFAULT '[]'
                    )
                    """
                )
                cur.execute("ALTER TABLE posts ADD COLUMN IF NOT EXISTS tag TEXT NOT NULL DEFAULT ''")
                cur.execute("ALTER TABLE posts ADD COLUMN IF NOT EXISTS root_topic TEXT")
                cur.execute("ALTER TABLE posts ADD COLUMN IF NOT EXISTS root_post_id TEXT")
                cur.execute("ALTER TABLE posts ADD COLUMN IF NOT EXISTS comment_count INTEGER NOT NULL DEFAULT 0")
                # v1.12.0: dedicated media field (JSON array of URLs)
                cur.execute("ALTER TABLE posts ADD COLUMN IF NOT EXISTS media TEXT NOT NULL DEFAULT '[]'")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_posts_owner_lower ON posts(LOWER(owner))")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_posts_target_lower ON posts(LOWER(target))")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_posts_txhash_lower ON posts(LOWER(txhash))")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_posts_topic_lower ON posts(LOWER(topic))")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_posts_created_at ON posts(created_at DESC)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_posts_root ON posts((COALESCE(target,'') = ''))")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_posts_root_post_id ON posts(LOWER(root_post_id))")
                # Root posts always have their own topic as root_topic and their
                # own txhash as root_post_id; this backfill is idempotent.
                cur.execute(
                    """
                    UPDATE posts
                    SET root_topic = COALESCE(root_topic, topic),
                        root_post_id = COALESCE(root_post_id, txhash)
                    WHERE COALESCE(target, '') = ''
                    """
                )

                # v1.6: Drop post_topics table (cross-posting removed)
                cur.execute("DROP TABLE IF EXISTS post_topics")

                # votes
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS votes (
                        txhash TEXT PRIMARY KEY,
                        owner TEXT NOT NULL,
                        target TEXT,
                        user_vote DOUBLE PRECISION NOT NULL,
                        user_weight DOUBLE PRECISION NOT NULL DEFAULT 0,
                        created_at BIGINT NOT NULL,
                        paid BOOLEAN NOT NULL DEFAULT FALSE
                    )
                    """
                )
                # Migration: rename old column names to unified naming
                cur.execute(
                    """
                    DO $$
                    BEGIN
                        -- Legacy: direction -> preference_vote -> user_vote
                        IF EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'votes' AND column_name = 'direction'
                        ) AND NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'votes' AND column_name = 'user_vote'
                        ) THEN
                            ALTER TABLE votes RENAME COLUMN direction TO user_vote;
                        END IF;
                        IF EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'votes' AND column_name = 'preference_vote'
                        ) AND NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'votes' AND column_name = 'user_vote'
                        ) THEN
                            ALTER TABLE votes RENAME COLUMN preference_vote TO user_vote;
                        END IF;
                        -- Legacy: net_votes -> community_vote -> user_weight
                        IF EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'votes' AND column_name = 'net_votes'
                        ) AND NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'votes' AND column_name = 'user_weight'
                        ) THEN
                            ALTER TABLE votes RENAME COLUMN net_votes TO user_weight;
                        END IF;
                        IF EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'votes' AND column_name = 'community_vote'
                        ) AND NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'votes' AND column_name = 'user_weight'
                        ) THEN
                            ALTER TABLE votes RENAME COLUMN community_vote TO user_weight;
                        END IF;
                        -- Add user_weight if missing (legacy)
                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'votes' AND column_name = 'user_weight'
                        ) THEN
                            ALTER TABLE votes ADD COLUMN user_weight DOUBLE PRECISION NOT NULL DEFAULT 0;
                            UPDATE votes SET user_weight = user_vote;
                        END IF;
                        -- Note: user_topic_stats.net_votes is intentionally kept as-is.
                    END $$;
                    """
                )
                cur.execute("ALTER TABLE votes ALTER COLUMN user_vote TYPE DOUBLE PRECISION")
                cur.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uniq_votes_owner_target ON votes(LOWER(owner), LOWER(target))"
                )
                cur.execute("CREATE INDEX IF NOT EXISTS idx_votes_owner_lower ON votes(LOWER(owner))")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_votes_target_lower ON votes(LOWER(target))")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_votes_created_at ON votes(created_at DESC)")

                # Awards (burn-only signals on posts/comments)
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS awards (
                        id SERIAL PRIMARY KEY,
                        owner TEXT NOT NULL,
                        target TEXT NOT NULL,
                        award_type TEXT NOT NULL,
                        burned_amount BIGINT NOT NULL DEFAULT 0,
                        created_at BIGINT NOT NULL
                    )
                    """
                )
                cur.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uniq_awards_owner_target ON awards(LOWER(owner), LOWER(target))"
                )
                cur.execute("CREATE INDEX IF NOT EXISTS idx_awards_target_lower ON awards(LOWER(target))")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_awards_created_at ON awards(created_at DESC)")

                # Per-user preferences for topics and authors (for home feed recommendations)
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS preferences (
                        owner TEXT NOT NULL,
                        pref_type TEXT NOT NULL,
                        target TEXT NOT NULL,
                        weight DOUBLE PRECISION NOT NULL DEFAULT 0,
                        updated_at BIGINT NOT NULL,
                        PRIMARY KEY (owner, pref_type, target)
                    )
                    """
                )
                cur.execute("CREATE INDEX IF NOT EXISTS idx_preferences_owner_lower ON preferences(LOWER(owner))")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_preferences_type ON preferences(pref_type)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_preferences_type_target ON preferences(pref_type, target)")
                # Migrate old tables if they exist (wrapped in DO block to handle missing tables)
                cur.execute(
                    """
                    DO $$
                    BEGIN
                        IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'topic_preferences') THEN
                            INSERT INTO preferences(owner, pref_type, target, weight, updated_at)
                            SELECT owner, 'topic', topic, weight, updated_at FROM topic_preferences
                            ON CONFLICT DO NOTHING;
                        END IF;
                        IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'author_preferences') THEN
                            INSERT INTO preferences(owner, pref_type, target, weight, updated_at)
                            SELECT owner, 'author', author, weight, updated_at FROM author_preferences
                            ON CONFLICT DO NOTHING;
                        END IF;
                    END $$;
                    """
                )

                # User similarity cache for home feed (similar users recommendations)
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS user_similarity_cache (
                        owner TEXT NOT NULL,
                        similar_user TEXT NOT NULL,
                        similarity DOUBLE PRECISION NOT NULL,
                        shared_dims INT NOT NULL,
                        computed_at BIGINT NOT NULL,
                        expires_at BIGINT NOT NULL,
                        PRIMARY KEY (owner, similar_user)
                    )
                    """
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_similarity_owner_expires ON user_similarity_cache(LOWER(owner), expires_at)"
                )

                # profiles
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS profiles (
                        owner TEXT PRIMARY KEY,
                        username TEXT,
                        level INTEGER NOT NULL DEFAULT 0,
                        created_at BIGINT NOT NULL DEFAULT 0,
                        updated_at BIGINT NOT NULL DEFAULT 0,
                        subscription_expiry BIGINT NOT NULL DEFAULT 0,
                        auto_renew BOOLEAN NOT NULL DEFAULT FALSE,
                        biography TEXT NOT NULL DEFAULT '',
                        avatar TEXT NOT NULL DEFAULT '',
                        banner TEXT NOT NULL DEFAULT '',
                        flair TEXT NOT NULL DEFAULT '',
                        inbox_last_viewed_at BIGINT NOT NULL DEFAULT 0
                    )
                    """
                )
                cur.execute("CREATE INDEX IF NOT EXISTS idx_profiles_owner_lower ON profiles(LOWER(owner))")

                # Migration: add flair, remove is_moderator (moderator->agent refactor)
                cur.execute("ALTER TABLE profiles ADD COLUMN IF NOT EXISTS flair TEXT NOT NULL DEFAULT ''")
                cur.execute(
                    """
                    DO $$
                    BEGIN
                        IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'profiles' AND column_name = 'is_moderator') THEN
                            ALTER TABLE profiles DROP COLUMN is_moderator;
                        END IF;
                    END $$;
                    """
                )

                # Level remap: old tiers 0=Free,1=Trusted,2=Established,3=Distinguished
                # -> new levels 0=Free, 1=Subscriber, 10=Agent
                cur.execute(
                    """
                    UPDATE profiles SET level = CASE
                        WHEN level = 2 THEN 1
                        WHEN level = 3 THEN 10
                        ELSE level
                    END
                    WHERE level IN (2, 3)
                    """
                )

                # v1.14.0: soft-delete support for MsgDeleteUser
                cur.execute("ALTER TABLE profiles ADD COLUMN IF NOT EXISTS deleted_at BIGINT")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_profiles_deleted_at ON profiles(deleted_at)")
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_profiles_username_active "
                    "ON profiles(LOWER(username)) WHERE deleted_at IS NULL"
                )

                # enabled_agents (was followed_mods; moderator->agent refactor)
                # Migration first: rename followed_mods -> enabled_agents if it exists
                cur.execute(
                    """
                    DO $$
                    BEGIN
                        IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'followed_mods')
                           AND NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'enabled_agents') THEN
                            ALTER TABLE followed_mods RENAME TO enabled_agents;
                            IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'enabled_agents' AND column_name = 'moderator') THEN
                                ALTER TABLE enabled_agents RENAME COLUMN moderator TO agent;
                            END IF;
                        END IF;
                    END $$;
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS enabled_agents (
                        owner TEXT NOT NULL,
                        agent TEXT NOT NULL,
                        position INTEGER NOT NULL DEFAULT 0,
                        PRIMARY KEY (owner, agent)
                    )
                    """
                )
                cur.execute("ALTER TABLE enabled_agents ADD COLUMN IF NOT EXISTS position INTEGER NOT NULL DEFAULT 0")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_enabled_agents_agent_lower ON enabled_agents(LOWER(agent))")

                # followed_users (for v1.5 social graph)
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS followed_users (
                        owner TEXT NOT NULL,
                        target TEXT NOT NULL,
                        position INTEGER NOT NULL DEFAULT 0,
                        PRIMARY KEY (owner, target)
                    )
                    """
                )
                cur.execute("CREATE INDEX IF NOT EXISTS idx_followed_users_owner_lower ON followed_users(LOWER(owner))")
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_followed_users_target_lower ON followed_users(LOWER(target))"
                )

                # followed_topics (for v1.5 social graph)
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS followed_topics (
                        owner TEXT NOT NULL,
                        topic TEXT NOT NULL,
                        position INTEGER NOT NULL DEFAULT 0,
                        PRIMARY KEY (owner, topic)
                    )
                    """
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_followed_topics_owner_lower ON followed_topics(LOWER(owner))"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_followed_topics_topic_lower ON followed_topics(LOWER(topic))"
                )

                # blocked_posts (with position for order)
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS blocked_posts (
                        owner TEXT NOT NULL,
                        target TEXT NOT NULL,
                        position INTEGER NOT NULL DEFAULT 0,
                        PRIMARY KEY (owner, target)
                    )
                    """
                )
                cur.execute("ALTER TABLE blocked_posts ADD COLUMN IF NOT EXISTS position INTEGER NOT NULL DEFAULT 0")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_blocked_posts_owner_lower ON blocked_posts(LOWER(owner))")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_blocked_posts_target_lower ON blocked_posts(LOWER(target))")

                # blocked_users (with position for order)
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS blocked_users (
                        owner TEXT NOT NULL,
                        target TEXT NOT NULL,
                        position INTEGER NOT NULL DEFAULT 0,
                        PRIMARY KEY (owner, target)
                    )
                    """
                )
                cur.execute("ALTER TABLE blocked_users ADD COLUMN IF NOT EXISTS position INTEGER NOT NULL DEFAULT 0")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_blocked_users_owner_lower ON blocked_users(LOWER(owner))")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_blocked_users_target_lower ON blocked_users(LOWER(target))")

                # blocked_topics (with position for order)
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS blocked_topics (
                        owner TEXT NOT NULL,
                        target TEXT NOT NULL,
                        position INTEGER NOT NULL DEFAULT 0,
                        PRIMARY KEY (owner, target)
                    )
                    """
                )
                cur.execute("CREATE INDEX IF NOT EXISTS idx_blocked_topics_owner_lower ON blocked_topics(LOWER(owner))")
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_blocked_topics_target_lower ON blocked_topics(LOWER(target))"
                )

                # reports
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS reports (
                        id SERIAL PRIMARY KEY,
                        owner TEXT NOT NULL,
                        target TEXT NOT NULL,
                        reason TEXT NOT NULL,
                        created_at BIGINT NOT NULL
                    )
                    """
                )
                cur.execute("CREATE INDEX IF NOT EXISTS idx_reports_target_lower ON reports(LOWER(target))")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_reports_created_at ON reports(created_at DESC)")

                # stats_events (bot requests are filtered at ingest, no raw user-agent/IP stored)
                # browser_family, os_family, device_type are coarse categories only
                # (e.g. "Chrome", "Windows", "desktop") -- not identifying
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS stats_events (
                        id SERIAL PRIMARY KEY,
                        event_type TEXT NOT NULL,
                        user_address TEXT,
                        session_id TEXT NOT NULL,
                        created_at BIGINT NOT NULL,
                        page_path TEXT,
                        browser_family TEXT,
                        os_family TEXT,
                        device_type TEXT
                    )
                    """
                )
                cur.execute("CREATE INDEX IF NOT EXISTS idx_stats_events_created_at ON stats_events(created_at DESC)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_stats_events_session_id ON stats_events(session_id)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_stats_events_user_address ON stats_events(user_address)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_stats_events_event_type ON stats_events(event_type)")
                # Migration: add coarse UA category columns and drop invasive columns
                for col in ("browser_family", "os_family", "device_type"):
                    cur.execute(
                        f"""
                        DO $$
                        BEGIN
                            IF NOT EXISTS (
                                SELECT 1 FROM information_schema.columns
                                WHERE table_name = 'stats_events' AND column_name = '{col}'
                            ) THEN
                                ALTER TABLE stats_events ADD COLUMN {col} TEXT;
                            END IF;
                        END $$;
                        """
                    )
                # Drop columns that stored raw user-agent, IP hashes, and referrers
                for col in ("user_agent", "ip_hash", "referrer"):
                    cur.execute(
                        f"""
                        DO $$
                        BEGIN
                            IF EXISTS (
                                SELECT 1 FROM information_schema.columns
                                WHERE table_name = 'stats_events' AND column_name = '{col}'
                            ) THEN
                                ALTER TABLE stats_events DROP COLUMN {col};
                            END IF;
                        END $$;
                        """
                    )
                # Drop the entire fingerprints table if it exists
                cur.execute("DROP TABLE IF EXISTS user_fingerprints")

                # difficulty_history - tracks PoW difficulty and message count over time
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS difficulty_history (
                        height BIGINT PRIMARY KEY,
                        difficulty INTEGER NOT NULL,
                        msg_count INTEGER NOT NULL DEFAULT 0,
                        created_at BIGINT NOT NULL
                    )
                    """
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_difficulty_history_created_at ON difficulty_history(created_at DESC)"
                )
                # Add msg_count column if it doesn't exist (migration for existing tables)
                cur.execute(
                    """
                    DO $$
                    BEGIN
                        IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                                      WHERE table_name='difficulty_history' AND column_name='msg_count') THEN
                            ALTER TABLE difficulty_history ADD COLUMN msg_count INTEGER NOT NULL DEFAULT 0;
                        END IF;
                    END $$;
                    """
                )

                # supply_history - tracks total supply over time for burn/mint charts
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS supply_history (
                        height BIGINT PRIMARY KEY,
                        total_supply BIGINT NOT NULL,
                        created_at BIGINT NOT NULL
                    )
                    """
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_supply_history_created_at ON supply_history(created_at DESC)"
                )

                # topic_content_stats: per-topic content labels derived from post tags
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS topic_content_stats (
                        topic TEXT PRIMARY KEY,
                        total_posts INTEGER NOT NULL DEFAULT 0,
                        sensitive_count INTEGER NOT NULL DEFAULT 0,
                        gore_count INTEGER NOT NULL DEFAULT 0,
                        violence_count INTEGER NOT NULL DEFAULT 0,
                        death_count INTEGER NOT NULL DEFAULT 0,
                        porn_count INTEGER NOT NULL DEFAULT 0,
                        dominant_tag TEXT NOT NULL DEFAULT '',
                        dominant_ratio DOUBLE PRECISION NOT NULL DEFAULT 0
                    )
                    """
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_topic_content_stats_topic_lower ON topic_content_stats(LOWER(topic))"
                )

                # NOTE: Data migrations have been moved to indexer/migrations/
                # They run automatically on indexer startup via run_migrations()

                # ========== Referral System Tables (prefixed for easy cleanup) ==========
                # referral_links: who referred whom (immutable once set)
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS referral_links (
                        user_address VARCHAR(64) PRIMARY KEY,
                        referrer_address VARCHAR(64) NOT NULL,
                        referred_at BIGINT NOT NULL,
                        created_at BIGINT DEFAULT EXTRACT(EPOCH FROM NOW())
                    )
                    """
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_referral_links_referrer ON referral_links(referrer_address)"
                )

                # referral_pending_rewards: pending rewards per period
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS referral_pending_rewards (
                        id SERIAL PRIMARY KEY,
                        user_address VARCHAR(64) NOT NULL,
                        period_start BIGINT NOT NULL,
                        period_end BIGINT NOT NULL,
                        self_active_days INT DEFAULT 0,
                        self_reward DECIMAL(20,6) DEFAULT 0,
                        referral_reward DECIMAL(20,6) DEFAULT 0,
                        total_pending DECIMAL(20,6) DEFAULT 0,
                        status VARCHAR(20) DEFAULT 'pending',
                        admin_notes TEXT,
                        created_at BIGINT DEFAULT EXTRACT(EPOCH FROM NOW()),
                        approved_at BIGINT,
                        paid_at BIGINT,
                        paid_txhash VARCHAR(64),
                        UNIQUE(user_address, period_start)
                    )
                    """
                )

                # referral_trust_scores: referrer trust based on approval rate
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS referral_trust_scores (
                        referrer_address VARCHAR(64) PRIMARY KEY,
                        trust_score DECIMAL(5,2) DEFAULT 1.0,
                        total_referrals INT DEFAULT 0,
                        approved_referrals INT DEFAULT 0,
                        rejected_referrals INT DEFAULT 0,
                        last_updated BIGINT DEFAULT EXTRACT(EPOCH FROM NOW())
                    )
                    """
                )

                # referral_analysis: per-referee analysis results
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS referral_analysis (
                        id SERIAL PRIMARY KEY,
                        referee_address VARCHAR(64) NOT NULL,
                        referrer_address VARCHAR(64) NOT NULL,
                        analysis_date BIGINT NOT NULL,
                        classification VARCHAR(20),
                        confidence DECIMAL(3,2),
                        similarity_to_referrer DECIMAL(3,2),
                        flags TEXT[],
                        recommendation VARCHAR(20),
                        admin_decision VARCHAR(20),
                        decided_at BIGINT,
                        UNIQUE(referee_address, analysis_date)
                    )
                    """
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_referral_analysis_referrer ON referral_analysis(referrer_address)"
                )

                # referral_user_accruals: tracks actual accrued amounts per referee
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS referral_user_accruals (
                        beneficiary_address VARCHAR(64) NOT NULL,
                        referee_address VARCHAR(64) NOT NULL,
                        level INT NOT NULL,
                        pending DECIMAL(20,6) DEFAULT 0,
                        paid DECIMAL(20,6) DEFAULT 0,
                        denied DECIMAL(20,6) DEFAULT 0,
                        last_updated BIGINT DEFAULT EXTRACT(EPOCH FROM NOW()),
                        PRIMARY KEY (beneficiary_address, referee_address)
                    )
                    """
                )
                # Add denied column if it doesn't exist (for existing databases)
                cur.execute(
                    """
                    DO $$
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'referral_user_accruals' AND column_name = 'denied'
                        ) THEN
                            ALTER TABLE referral_user_accruals ADD COLUMN denied DECIMAL(20,6) DEFAULT 0;
                        END IF;
                    END $$;
                    """
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_referral_user_accruals_beneficiary ON referral_user_accruals(beneficiary_address)"
                )

                # user_topic_stats: per-user per-topic voting stats for vote weighting
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS user_topic_stats (
                        owner TEXT NOT NULL,
                        topic TEXT NOT NULL,
                        vote_count INTEGER NOT NULL DEFAULT 0,
                        net_votes INTEGER NOT NULL DEFAULT 0,
                        unique_root_posts INTEGER NOT NULL DEFAULT 0,
                        post_count INTEGER NOT NULL DEFAULT 0,
                        PRIMARY KEY (owner, topic)
                    )
                    """
                )
                cur.execute("CREATE INDEX IF NOT EXISTS idx_user_topic_stats_owner ON user_topic_stats(LOWER(owner))")
                # Legacy safety: if a past migration created 'score' instead of 'net_votes', rename it back.
                cur.execute(
                    """
                    DO $$
                    BEGIN
                        IF EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'user_topic_stats' AND column_name = 'score'
                        ) AND NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'user_topic_stats' AND column_name = 'net_votes'
                        ) THEN
                            ALTER TABLE user_topic_stats RENAME COLUMN score TO net_votes;
                        END IF;
                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'user_topic_stats' AND column_name = 'net_votes'
                        ) THEN
                            ALTER TABLE user_topic_stats ADD COLUMN net_votes INTEGER NOT NULL DEFAULT 0;
                        END IF;
                    END $$;
                    """
                )

                # One-time backfill from existing votes (idempotent via ON CONFLICT DO NOTHING)
                cur.execute(
                    """
                    INSERT INTO user_topic_stats (owner, topic, vote_count, net_votes, unique_root_posts, post_count)
                    SELECT
                        LOWER(v.owner),
                        LOWER(p.root_topic),
                        COUNT(*),
                        SUM(CASE WHEN v.user_vote > 0 THEN 1 WHEN v.user_vote < 0 THEN -1 ELSE 0 END),
                        COUNT(DISTINCT LOWER(p.root_post_id)),
                        0
                    FROM votes v
                    JOIN posts p ON LOWER(p.txhash) = LOWER(v.target)
                    WHERE p.root_topic IS NOT NULL AND p.root_topic != ''
                    GROUP BY LOWER(v.owner), LOWER(p.root_topic)
                    ON CONFLICT (owner, topic) DO NOTHING
                    """
                )

                # Backfill post_count from existing posts
                cur.execute(
                    """
                    INSERT INTO user_topic_stats (owner, topic, vote_count, net_votes, unique_root_posts, post_count)
                    SELECT
                        LOWER(owner),
                        LOWER(root_topic),
                        0, 0, 0,
                        COUNT(*)
                    FROM posts
                    WHERE root_topic IS NOT NULL AND root_topic != '' AND deleted = FALSE
                    GROUP BY LOWER(owner), LOWER(root_topic)
                    ON CONFLICT (owner, topic) DO UPDATE SET
                        post_count = EXCLUDED.post_count
                    """
                )

                # invite_codes: invite-only registration system
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS invite_codes (
                        code VARCHAR(9) PRIMARY KEY,
                        owner TEXT NOT NULL,
                        used_by TEXT,
                        created_at BIGINT NOT NULL,
                        used_at BIGINT
                    )
                    """
                )
                cur.execute("CREATE INDEX IF NOT EXISTS idx_invite_codes_owner ON invite_codes(LOWER(owner))")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_invite_codes_used_by ON invite_codes(LOWER(used_by))")

                # ========== Bridge Transaction Tables ==========
                # bridge_transactions: tracks all bridge-related messages for status queries
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS bridge_transactions (
                        id SERIAL PRIMARY KEY,
                        tx_hash TEXT NOT NULL,
                        direction TEXT NOT NULL,
                        msg_type TEXT NOT NULL,
                        source_chain TEXT,
                        destination_chain TEXT,
                        burn_id TEXT NOT NULL,
                        sender TEXT,
                        recipient TEXT,
                        amount BIGINT NOT NULL,
                        validator TEXT,
                        destination_tx TEXT,
                        minted BOOLEAN DEFAULT FALSE,
                        created_at BIGINT NOT NULL,
                        height BIGINT NOT NULL,
                        power BIGINT DEFAULT 0,
                        attested_power BIGINT DEFAULT 0,
                        required_power BIGINT DEFAULT 0
                    )
                    """
                )
                # Migration: add power columns if missing (for existing databases)
                for col in ["power", "attested_power", "required_power"]:
                    cur.execute(
                        f"""
                        DO $$ BEGIN
                            ALTER TABLE bridge_transactions ADD COLUMN {col} BIGINT DEFAULT 0;
                        EXCEPTION
                            WHEN duplicate_column THEN NULL;
                        END $$;
                    """
                    )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_bridge_burn_id ON bridge_transactions(burn_id, source_chain)"
                )
                cur.execute("CREATE INDEX IF NOT EXISTS idx_bridge_tx_hash ON bridge_transactions(LOWER(tx_hash))")
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_bridge_direction ON bridge_transactions(direction, created_at DESC)"
                )
                cur.execute("CREATE INDEX IF NOT EXISTS idx_bridge_recipient ON bridge_transactions(LOWER(recipient))")
                # Prevent duplicate entries during re-indexing
                cur.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS idx_bridge_unique_tx ON bridge_transactions(tx_hash, msg_type)"
                )

                # ========== Mentions Table ==========
                # mentions: @username mentions extracted from post/comment content
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS mentions (
                        id SERIAL PRIMARY KEY,
                        post_txhash TEXT NOT NULL,
                        mentioned_address TEXT NOT NULL,
                        mentioner_address TEXT NOT NULL,
                        created_at BIGINT NOT NULL,
                        UNIQUE(post_txhash, mentioned_address)
                    )
                    """
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_mentions_mentioned_at ON mentions(mentioned_address, created_at DESC)"
                )
                cur.execute("CREATE INDEX IF NOT EXISTS idx_mentions_post ON mentions(post_txhash)")

                # ========== Agent Edits Table ==========
                # agent_edits: per-agent overlay edits on posts (MsgAnnotate)
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS agent_edits (
                        post_txhash TEXT NOT NULL,
                        agent_address TEXT NOT NULL,
                        edit_txhash TEXT NOT NULL,
                        topic TEXT,
                        title TEXT,
                        content TEXT,
                        tag TEXT,
                        media TEXT,
                        appendix TEXT,
                        edited_at BIGINT NOT NULL,
                        PRIMARY KEY (post_txhash, agent_address)
                    )
                    """
                )
                cur.execute("CREATE INDEX IF NOT EXISTS idx_agent_edits_post ON agent_edits(post_txhash)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_agent_edits_agent ON agent_edits(LOWER(agent_address))")
                cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_edits_txhash ON agent_edits(edit_txhash)")

    def get_last_height(self) -> int:
        """Get last processed height from meta table."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT value FROM meta WHERE key='last_height'")
                row = cur.fetchone()
                if not row or row[0] is None:
                    return 0
                try:
                    return int(row[0])
                except Exception:
                    return 0

    def set_last_height(self, height: int) -> None:
        """Persist last processed height to meta table."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO meta(key, value) VALUES('last_height', %s)
                    ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
                    """,
                    (str(int(height)),),
                )

    def get_post(self, txhash: str):
        """Get post by txhash. Returns (topic, title, content, target, paid, thumbnail_url, created_at, media)."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT topic, title, content, target, paid, COALESCE(thumbnail_url,''), created_at, COALESCE(media,'[]') FROM posts WHERE txhash = %s",
                    (txhash,),
                )
                return cur.fetchone()

    def get_root_topic_for_post(self, txhash: str):
        """
        Return (root_topic, root_post_id) for a given post/comment, or (None, None) if not found.

        - For new data the posts table stores root_topic/root_post_id directly, so this is a
          single-row lookup.
        - For older rows without these fields populated we fall back to a bounded parent walk,
          and opportunistically backfill root_topic/root_post_id for the discovered root.
        """
        current_id = (txhash or "").strip().lower()
        if not current_id:
            return None, None

        with self._connect() as conn:
            with conn.cursor() as cur:
                visited: set[str] = set()
                max_depth = 100
                for _ in range(max_depth):
                    if not current_id or current_id in visited:
                        break
                    visited.add(current_id)
                    cur.execute(
                        """
                        SELECT
                            COALESCE(root_topic, ''),
                            COALESCE(root_post_id, ''),
                            COALESCE(topic, ''),
                            COALESCE(target, ''),
                            deleted
                        FROM posts
                        WHERE LOWER(txhash) = LOWER(%s)
                        LIMIT 1
                        """,
                        (current_id,),
                    )
                    row = cur.fetchone()
                    if not row:
                        break
                    root_topic, root_post_id, topic, target, _deleted = row
                    root_topic_str = str(root_topic or "").strip().lower()
                    root_post_str = str(root_post_id or "").strip().lower()
                    topic_str = str(topic or "").strip()
                    parent = str(target or "").strip().lower()

                    # Fast path: already denormalised.
                    if root_topic_str and root_post_str:
                        return root_topic_str, root_post_str

                    # Reached a root post (no parent) – derive and persist root_topic/root_post_id.
                    if not parent:
                        final_topic = topic_str.lower() if topic_str else None
                        final_root_id = current_id
                        try:
                            cur.execute(
                                "UPDATE posts SET root_topic = %s, root_post_id = %s WHERE LOWER(txhash) = LOWER(%s)",
                                (final_topic, final_root_id, current_id),
                            )
                        except Exception:
                            # Best-effort backfill; do not fail caller if this update fails.
                            pass
                        return final_topic, final_root_id

                    # Otherwise, walk up the parent chain.
                    current_id = parent

        return None, None

    @staticmethod
    def _evict_oldest(cur, table: str, value_col: str, owner: str) -> None:
        """Delete the oldest rows beyond INDEXER_LIST_CAP for an owner, ordered by position."""
        cur.execute(
            f"SELECT COUNT(*) FROM {table} WHERE LOWER(owner) = LOWER(%s)",
            (owner,),
        )
        count = cur.fetchone()[0]
        excess = count - INDEXER_LIST_CAP
        if excess > 0:
            cur.execute(
                f"""
                DELETE FROM {table}
                WHERE (owner, {value_col}) IN (
                    SELECT owner, {value_col} FROM {table}
                    WHERE LOWER(owner) = LOWER(%s)
                    ORDER BY position ASC
                    LIMIT %s
                )
                """,
                (owner, excess),
            )

    @staticmethod
    def _strip_nul(val: Optional[str]) -> Optional[str]:
        """PostgreSQL text fields cannot contain NUL (0x00) bytes."""
        if val is None:
            return None
        return val.replace("\x00", "")

    def upsert_post(
        self,
        txhash: str,
        owner: str,
        created_at: int,
        topic: str,
        title: str,
        content: str,
        target: str,
        paid: bool,
        edited_at: Optional[int] = None,
        deleted: bool = False,
        thumbnail_url: Optional[str] = None,
        tag: str = "",
        root_topic: Optional[str] = None,
        root_post_id: Optional[str] = None,
        media: Optional[list[str]] = None,
    ) -> None:
        """Insert or update a post."""
        import json as _json

        topic = self._strip_nul(topic) or ""
        title = self._strip_nul(title) or ""
        content = self._strip_nul(content) or ""
        target = self._strip_nul(target) or ""
        tag = self._strip_nul(tag) or ""
        thumbnail_url = self._strip_nul(thumbnail_url)
        root_topic = self._strip_nul(root_topic)
        root_post_id = self._strip_nul(root_post_id)
        media_json = _json.dumps(media or [])
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO posts(
                        txhash,
                        owner,
                        topic,
                        title,
                        content,
                        target,
                        created_at,
                        edited_at,
                        paid,
                        deleted,
                        thumbnail_url,
                        tag,
                        root_topic,
                        root_post_id,
                        media
                    )
                    VALUES(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT(txhash) DO UPDATE SET
                      owner=EXCLUDED.owner,
                      topic=EXCLUDED.topic,
                      title=EXCLUDED.title,
                      content=EXCLUDED.content,
                      target=EXCLUDED.target,
                      created_at=EXCLUDED.created_at,
                      edited_at=EXCLUDED.edited_at,
                      paid=EXCLUDED.paid,
                      deleted=EXCLUDED.deleted,
                      thumbnail_url=EXCLUDED.thumbnail_url,
                      tag=EXCLUDED.tag,
                      root_topic=COALESCE(EXCLUDED.root_topic, posts.root_topic),
                      root_post_id=COALESCE(EXCLUDED.root_post_id, posts.root_post_id),
                      media=EXCLUDED.media
                    """,
                    (
                        txhash,
                        owner,
                        topic or "",
                        title,
                        content,
                        target,
                        int(created_at),
                        int(edited_at) if edited_at else None,
                        bool(paid),
                        bool(deleted),
                        thumbnail_url,
                        tag or "",
                        (root_topic or None),
                        (root_post_id or None),
                        media_json,
                    ),
                )

    def upsert_agent_edit(
        self,
        post_txhash: str,
        agent_address: str,
        edit_txhash: str,
        edited_at: int,
        topic: Optional[str] = None,
        title: Optional[str] = None,
        content: Optional[str] = None,
        tag: Optional[str] = None,
        media: Optional[list[str]] = None,
        appendix: Optional[str] = None,
    ) -> None:
        """Insert or update an agent edit overlay. None = no change for that field."""
        import json as _json

        media_json = _json.dumps(media) if media is not None else None
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO agent_edits(
                        post_txhash, agent_address, edit_txhash,
                        topic, title, content, tag, media, appendix, edited_at
                    )
                    VALUES(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT(post_txhash, agent_address) DO UPDATE SET
                        edit_txhash = EXCLUDED.edit_txhash,
                        topic = COALESCE(EXCLUDED.topic, agent_edits.topic),
                        title = COALESCE(EXCLUDED.title, agent_edits.title),
                        content = COALESCE(EXCLUDED.content, agent_edits.content),
                        tag = COALESCE(EXCLUDED.tag, agent_edits.tag),
                        media = COALESCE(EXCLUDED.media, agent_edits.media),
                        appendix = COALESCE(EXCLUDED.appendix, agent_edits.appendix),
                        edited_at = EXCLUDED.edited_at
                    """,
                    (
                        post_txhash.lower(),
                        agent_address.lower(),
                        edit_txhash.lower(),
                        topic,
                        title,
                        content,
                        tag,
                        media_json,
                        appendix,
                        int(edited_at),
                    ),
                )

    def get_agent_edits_for_posts(
        self,
        post_txhashes: list[str],
        agent_addresses: list[str],
    ) -> list[tuple]:
        """Fetch agent edits for a batch of posts from specific agents.
        Returns rows of (post_txhash, agent_address, topic, title, content, tag, media, appendix).
        """
        if not post_txhashes or not agent_addresses:
            return []
        with self._connect() as conn:
            with conn.cursor() as cur:
                post_ph = ",".join(["%s"] * len(post_txhashes))
                agent_ph = ",".join(["%s"] * len(agent_addresses))
                cur.execute(
                    f"""SELECT post_txhash, agent_address, topic, title, content, tag, media, appendix
                        FROM agent_edits
                        WHERE post_txhash IN ({post_ph})
                          AND LOWER(agent_address) IN ({agent_ph})""",
                    [p.lower() for p in post_txhashes] + [a.lower() for a in agent_addresses],
                )
                return cur.fetchall()

    def insert_mentions(
        self,
        post_txhash: str,
        mentioner_address: str,
        mentioned_addresses: list[str],
        created_at: int,
    ) -> None:
        """Bulk-insert mentions for a post. Duplicates are silently ignored."""
        if not mentioned_addresses:
            return
        with self._connect() as conn:
            with conn.cursor() as cur:
                values = [
                    (post_txhash, addr.lower(), mentioner_address.lower(), int(created_at))
                    for addr in mentioned_addresses
                ]
                cur.executemany(
                    """
                    INSERT INTO mentions(post_txhash, mentioned_address, mentioner_address, created_at)
                    VALUES(%s, %s, %s, %s)
                    ON CONFLICT(post_txhash, mentioned_address) DO NOTHING
                    """,
                    values,
                )

    def delete_mentions_for_post(self, post_txhash: str) -> None:
        """Delete all mentions for a post (used before re-extracting on edit)."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM mentions WHERE post_txhash = %s", (post_txhash,))

    def resolve_usernames_to_addresses(self, usernames: list[str]) -> dict[str, str]:
        """Bulk-resolve usernames to addresses (active profiles only).
        Returns {lowercase_username: owner_address}.
        """
        if not usernames:
            return {}
        with self._connect() as conn:
            with conn.cursor() as cur:
                cleaned = list({u.lower() for u in usernames if u.strip()})
                if not cleaned:
                    return {}
                ph = ",".join(["%s"] * len(cleaned))
                cur.execute(
                    f"SELECT LOWER(username), owner FROM profiles "
                    f"WHERE LOWER(username) IN ({ph}) AND deleted_at IS NULL",
                    cleaned,
                )
                return {row[0]: row[1] for row in cur.fetchall() if row[0] and row[1]}

    @classmethod
    def _normalize_tag(cls, tag: str) -> str:
        """Return a normalized tag if allowed, else empty string."""
        t = str(tag or "").strip().lower()
        if t in cls._ALLOWED_TOPIC_TAGS:
            return t
        return ""

    @staticmethod
    def _compute_dominant_tag(
        total: int,
        sensitive: int,
        gore: int,
        violence: int,
        death: int,
        porn: int,
    ) -> Tuple[str, float]:
        """Compute dominant tag (>=50% of posts)."""
        if total <= 0:
            return "", 0.0

        counts = {
            "sensitive": int(sensitive or 0),
            "gore": int(gore or 0),
            "violence": int(violence or 0),
            "death": int(death or 0),
            "porn": int(porn or 0),
        }

        dominant_tag = ""
        dominant_ratio = 0.0
        for key, value in counts.items():
            ratio = float(value) / float(total)
            if ratio >= 0.5 and ratio > dominant_ratio:
                dominant_tag = key
                dominant_ratio = ratio
        return dominant_tag, dominant_ratio

    def update_topic_content_stats(self, topic: str, tag: str) -> None:
        """Increment per-topic content stats based on a new root post tag."""
        topic_norm = str(topic or "").strip().lower()
        if not topic_norm:
            return
        tag_norm = self._normalize_tag(tag)
        sensitive_inc = 1 if tag_norm == "sensitive" else 0
        gore_inc = 1 if tag_norm == "gore" else 0
        violence_inc = 1 if tag_norm == "violence" else 0
        death_inc = 1 if tag_norm == "death" else 0
        porn_inc = 1 if tag_norm == "porn" else 0

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO topic_content_stats(
                        topic,
                        total_posts,
                        sensitive_count,
                        gore_count,
                        violence_count,
                        death_count,
                        porn_count
                    ) VALUES(%s, 1, %s, %s, %s, %s, %s)
                    ON CONFLICT(topic) DO UPDATE SET
                        total_posts = topic_content_stats.total_posts + 1,
                        sensitive_count = topic_content_stats.sensitive_count + EXCLUDED.sensitive_count,
                        gore_count = topic_content_stats.gore_count + EXCLUDED.gore_count,
                        violence_count = topic_content_stats.violence_count + EXCLUDED.violence_count,
                        death_count = topic_content_stats.death_count + EXCLUDED.death_count,
                        porn_count = topic_content_stats.porn_count + EXCLUDED.porn_count
                    RETURNING total_posts, sensitive_count, gore_count, violence_count, death_count, porn_count
                    """,
                    (
                        topic_norm,
                        sensitive_inc,
                        gore_inc,
                        violence_inc,
                        death_inc,
                        porn_inc,
                    ),
                )
                row = cur.fetchone()
                if not row:
                    return
                total_posts, sensitive, gore, violence, death, porn = row
                dominant_tag, dominant_ratio = self._compute_dominant_tag(
                    total_posts, sensitive, gore, violence, death, porn
                )
                cur.execute(
                    """
                    UPDATE topic_content_stats
                    SET dominant_tag = %s,
                        dominant_ratio = %s
                    WHERE topic = %s
                    """,
                    (dominant_tag, float(dominant_ratio), topic_norm),
                )

    def recompute_topic_content_stats(self, topic: str) -> None:
        """Recompute stats for a topic from the posts table (root posts only)."""
        topic_norm = str(topic or "").strip().lower()
        if not topic_norm:
            return
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        COUNT(1) AS total_posts,
                        SUM(CASE WHEN LOWER(tag) = 'sensitive' THEN 1 ELSE 0 END) AS sensitive_count,
                        SUM(CASE WHEN LOWER(tag) = 'gore' THEN 1 ELSE 0 END) AS gore_count,
                        SUM(CASE WHEN LOWER(tag) = 'violence' THEN 1 ELSE 0 END) AS violence_count,
                        SUM(CASE WHEN LOWER(tag) = 'death' THEN 1 ELSE 0 END) AS death_count,
                        SUM(CASE WHEN LOWER(tag) = 'porn' THEN 1 ELSE 0 END) AS porn_count
                    FROM posts
                    WHERE COALESCE(target, '') = ''
                      AND deleted = FALSE
                      AND LOWER(COALESCE(topic, '')) = %s
                    """,
                    (topic_norm,),
                )
                row = cur.fetchone()
                if not row:
                    return
                total_posts, sensitive, gore, violence, death, porn = [int(x or 0) for x in row]
                if total_posts <= 0:
                    cur.execute("DELETE FROM topic_content_stats WHERE topic = %s", (topic_norm,))
                    return
                dominant_tag, dominant_ratio = self._compute_dominant_tag(
                    total_posts, sensitive, gore, violence, death, porn
                )
                cur.execute(
                    """
                    INSERT INTO topic_content_stats(
                        topic,
                        total_posts,
                        sensitive_count,
                        gore_count,
                        violence_count,
                        death_count,
                        porn_count,
                        dominant_tag,
                        dominant_ratio
                    ) VALUES(%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT(topic) DO UPDATE SET
                        total_posts = EXCLUDED.total_posts,
                        sensitive_count = EXCLUDED.sensitive_count,
                        gore_count = EXCLUDED.gore_count,
                        violence_count = EXCLUDED.violence_count,
                        death_count = EXCLUDED.death_count,
                        porn_count = EXCLUDED.porn_count,
                        dominant_tag = EXCLUDED.dominant_tag,
                        dominant_ratio = EXCLUDED.dominant_ratio
                    """,
                    (
                        topic_norm,
                        total_posts,
                        sensitive,
                        gore,
                        violence,
                        death,
                        porn,
                        dominant_tag,
                        float(dominant_ratio),
                    ),
                )

    def update_post_thumbnail(self, txhash: str, thumbnail_url: str | None) -> None:
        """Update thumbnail URL for a post."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE posts SET thumbnail_url = %s WHERE LOWER(txhash) = LOWER(%s)",
                    (thumbnail_url, txhash),
                )

    def upsert_auto_vote(
        self,
        autohash: str,
        owner: str,
        created_at: int,
        target: str,
        paid: bool,
        user_vote: float = 1.0,
        user_weight: float = 1.0,
    ) -> None:
        """Insert or update an auto-vote. Auto-votes always contribute to post points."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO votes(txhash, owner, target, user_vote, user_weight, created_at, paid)
                    VALUES(%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT(LOWER(owner), LOWER(target)) DO UPDATE SET
                      txhash=EXCLUDED.txhash,
                      user_vote=EXCLUDED.user_vote,
                      user_weight=EXCLUDED.user_weight,
                      created_at=EXCLUDED.created_at,
                      paid=EXCLUDED.paid
                    """,
                    (
                        autohash,
                        owner,
                        target,
                        float(user_vote),
                        float(user_weight),
                        int(created_at),
                        bool(paid),
                    ),
                )

    def post_exists(self, txhash: str) -> bool:
        """Check if a post exists."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM posts WHERE txhash = %s", (txhash,))
                return cur.fetchone() is not None

    def get_vote_by_owner_target(self, owner: str, target: str) -> Optional[Tuple[str, float, float]]:
        """Get existing vote by owner and target.

        Returns (txhash, user_vote, user_weight) or None if no vote exists.
        """
        owner_norm = str(owner or "").strip()
        target_norm = str(target or "").strip()
        if not owner_norm or not target_norm:
            return None
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT txhash, user_vote, user_weight
                    FROM votes
                    WHERE LOWER(owner) = LOWER(%s) AND LOWER(target) = LOWER(%s)
                    """,
                    (owner_norm, target_norm),
                )
                row = cur.fetchone()
                if row:
                    return (row[0], float(row[1]), float(row[2]))
                return None

    def get_target_vote_counts(self, target: str) -> tuple[int, int]:
        """Return (upvotes, downvotes) for a target post/comment."""
        target_norm = str(target or "").strip()
        if not target_norm:
            return (0, 0)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        COALESCE(SUM(CASE WHEN user_vote > 0 THEN 1 ELSE 0 END), 0) AS upvotes,
                        COALESCE(SUM(CASE WHEN user_vote < 0 THEN 1 ELSE 0 END), 0) AS downvotes
                    FROM votes
                    WHERE LOWER(target) = LOWER(%s)
                    """,
                    (target_norm,),
                )
                row = cur.fetchone()
                if not row:
                    return (0, 0)
                return (int(row[0] or 0), int(row[1] or 0))

    def upsert_vote(
        self,
        txhash: str,
        owner: str,
        created_at: int,
        target: str,
        user_vote: float,
        user_weight: float,
        paid: bool,
    ) -> None:
        """Insert or update a vote.

        user_vote: The user's vote direction (-1, 0, +1).
        user_weight: Weighted contribution to post points (0 if user doesn't follow topic).
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO votes(txhash, owner, target, user_vote, user_weight, created_at, paid)
                    VALUES(%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT(LOWER(owner), LOWER(target)) DO UPDATE SET
                      txhash=EXCLUDED.txhash,
                      user_vote=EXCLUDED.user_vote,
                      user_weight=EXCLUDED.user_weight,
                      created_at=EXCLUDED.created_at,
                      paid=EXCLUDED.paid
                    """,
                    (txhash, owner, target, float(user_vote), float(user_weight), int(created_at), bool(paid)),
                )

    def is_topic_followed(self, owner: str, topic: str) -> bool:
        """Return True if the owner currently follows the given topic."""
        owner_norm = str(owner or "").strip()
        topic_norm = str(topic or "").strip()
        if not owner_norm or not topic_norm:
            return False
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM followed_topics WHERE LOWER(owner) = LOWER(%s) AND LOWER(topic) = LOWER(%s) LIMIT 1",
                    (owner_norm, topic_norm),
                )
                return cur.fetchone() is not None

    def is_user_followed(self, owner: str, target: str) -> bool:
        """Return True if the owner currently follows the given user."""
        owner_norm = str(owner or "").strip()
        target_norm = str(target or "").strip()
        if not owner_norm or not target_norm:
            return False
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM followed_users WHERE LOWER(owner) = LOWER(%s) AND LOWER(target) = LOWER(%s) LIMIT 1",
                    (owner_norm, target_norm),
                )
                return cur.fetchone() is not None

    def get_user_topic_stats(self, owner: str, topic: str):
        """Get user's voting stats in a topic. Returns (vote_count, net_votes, unique_root_posts, post_count) or None."""
        owner_norm = str(owner or "").strip().lower()
        topic_norm = str(topic or "").strip().lower()
        if not owner_norm or not topic_norm:
            return None
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT vote_count, net_votes, unique_root_posts, post_count FROM user_topic_stats WHERE owner = %s AND topic = %s",
                    (owner_norm, topic_norm),
                )
                return cur.fetchone()

    def has_voted_on_root_post(self, owner: str, root_post_id: str) -> bool:
        """Check if user has already voted on any post/comment under this root post."""
        owner_norm = str(owner or "").strip().lower()
        root_norm = str(root_post_id or "").strip().lower()
        if not owner_norm or not root_norm:
            return False
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 1 FROM votes v
                    JOIN posts p ON LOWER(p.txhash) = LOWER(v.target)
                    WHERE LOWER(v.owner) = %s AND LOWER(p.root_post_id) = %s
                    LIMIT 1
                    """,
                    (owner_norm, root_norm),
                )
                return cur.fetchone() is not None

    def update_user_topic_stats(
        self,
        owner: str,
        topic: str,
        direction: int,
        root_post_id: str,
        is_new_vote: bool = True,
        post_increment: int = 0,
    ) -> None:
        """
        Update user's voting stats in a topic after a vote or post.

        vote_count: Only incremented for NEW votes (first vote on a target), not re-votes.
                    This prevents gaming by toggling votes on the same post.
        score: Updated by direction for every vote (tracks overall sentiment).
        unique_root_posts: Incremented if this is a new root post thread for this user.
        post_count: Incremented when post_increment > 0 (for new posts/comments).
        """
        owner_norm = str(owner or "").strip().lower()
        topic_norm = str(topic or "").strip().lower()
        root_norm = str(root_post_id or "").strip().lower()
        if not owner_norm or not topic_norm:
            return

        # Check if this root post is new for this user in this topic
        is_new_root = False
        if root_norm:
            is_new_root = not self.has_voted_on_root_post(owner_norm, root_norm)

        with self._connect() as conn:
            with conn.cursor() as cur:
                # Only increment counters for genuinely new votes
                vote_increment = 1 if is_new_vote else 0
                root_increment = 1 if is_new_root else 0
                cur.execute(
                    """
                    INSERT INTO user_topic_stats (owner, topic, vote_count, net_votes, unique_root_posts, post_count)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (owner, topic) DO UPDATE SET
                        vote_count = user_topic_stats.vote_count + %s,
                        net_votes = user_topic_stats.net_votes + %s,
                        unique_root_posts = user_topic_stats.unique_root_posts + %s,
                        post_count = user_topic_stats.post_count + %s
                    """,
                    (
                        owner_norm,
                        topic_norm,
                        vote_increment,
                        direction,
                        root_increment,
                        post_increment,
                        vote_increment,
                        direction,
                        root_increment,
                        post_increment,
                    ),
                )

    def update_preference(self, owner: str, pref_type: str, target: str, delta: float, updated_at: int) -> None:
        """
        Update per-user preference (topic or author) using exponential decay.

        pref_type: 'topic' or 'author'
        target: topic name or author address

        Uses a rolling score where recent votes matter more and old votes fade:
            new_weight = (old_weight * DECAY) + new_vote

        With DECAY = 0.9:
        - Most recent vote contributes 100%
        - 5 votes ago contributes ~59%
        - 10 votes ago contributes ~35%
        - 20 votes ago contributes ~12%
        """
        owner_norm = str(owner or "").strip().lower()
        target_norm = str(target or "").strip().lower()
        if not owner_norm or not target_norm or not delta:
            return
        # Don't track preference for your own posts
        if pref_type == "author" and owner_norm == target_norm:
            return

        DECAY = 0.9

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO preferences(owner, pref_type, target, weight, updated_at)
                    VALUES(%s, %s, %s, %s, %s)
                    ON CONFLICT(owner, pref_type, target) DO UPDATE SET
                      weight = GREATEST(LEAST((preferences.weight * %s) + EXCLUDED.weight, 10.0), -10.0),
                      updated_at = EXCLUDED.updated_at
                    """,
                    (owner_norm, pref_type, target_norm, float(delta), int(updated_at), DECAY),
                )

    def get_profile(self, owner: str):
        """Get profile by owner. Returns (username, level, created_at) or None."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT username, level, created_at FROM profiles WHERE LOWER(owner) = LOWER(%s)", (owner,))
                return cur.fetchone()

    def get_profile_level(self, owner: str) -> int | None:
        """Get profile level by owner address. Returns level or None if not found."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT level FROM profiles WHERE LOWER(owner) = LOWER(%s)", (owner,))
                row = cur.fetchone()
                return int(row[0]) if row else None

    def upsert_profile(self, owner: str, username: str | None, level: int, updated_at: int) -> None:
        """Insert or update a profile (basic fields only)."""
        username = self._strip_nul(username)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO profiles(owner, username, level, created_at, updated_at)
                    VALUES(%s, %s, %s, %s, %s)
                    ON CONFLICT(owner) DO UPDATE SET
                      username=EXCLUDED.username,
                      level=EXCLUDED.level,
                      updated_at=EXCLUDED.updated_at,
                      deleted_at=NULL
                    """,
                    (owner, username, int(level), int(updated_at), int(updated_at)),
                )

    def update_profile_level(self, owner: str, level: int, updated_at: int) -> bool:
        """Update only the level field for an existing profile (used for expiration/downgrade)."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                if level == 0:
                    cur.execute(
                        """
                        UPDATE profiles SET level=%s, subscription_expiry=0, updated_at=%s
                        WHERE LOWER(owner) = LOWER(%s)
                        """,
                        (int(level), int(updated_at), owner),
                    )
                else:
                    cur.execute(
                        """
                        UPDATE profiles SET level=%s, updated_at=%s
                        WHERE LOWER(owner) = LOWER(%s)
                        """,
                        (int(level), int(updated_at), owner),
                    )
                return cur.rowcount > 0

    def update_profile_subscription(
        self,
        owner: str,
        level: int,
        subscription_expiry: int,
        auto_renew: bool | None,
        updated_at: int,
    ) -> bool:
        """Update subscription-related fields for a profile.

        If auto_renew is None, it won't be changed (used for renewals).
        If auto_renew is a bool, it will be updated (used for user toggling).
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                if auto_renew is None:
                    # Preserve existing auto_renew value
                    cur.execute(
                        """
                        UPDATE profiles
                        SET level=%s, subscription_expiry=%s, updated_at=%s
                        WHERE LOWER(owner) = LOWER(%s)
                        """,
                        (int(level), int(subscription_expiry), int(updated_at), owner),
                    )
                else:
                    cur.execute(
                        """
                        UPDATE profiles
                        SET level=%s, subscription_expiry=%s, auto_renew=%s, updated_at=%s
                        WHERE LOWER(owner) = LOWER(%s)
                        """,
                        (int(level), int(subscription_expiry), bool(auto_renew), int(updated_at), owner),
                    )
                return cur.rowcount > 0

    def upsert_profile_full(
        self,
        owner: str,
        username: str | None,
        level: int,
        created_at: int,
        subscription_expiry: int,
        auto_renew: bool,
        biography: str,
        avatar: str,
        banner: str,
        flair: str,
        updated_at: int,
    ) -> None:
        """Insert or update a profile with all fields."""
        username = self._strip_nul(username)
        biography = self._strip_nul(biography) or ""
        avatar = self._strip_nul(avatar) or ""
        banner = self._strip_nul(banner) or ""
        flair = self._strip_nul(flair) or ""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO profiles(owner, username, level, created_at, subscription_expiry,
                                         auto_renew, biography, avatar, banner, flair, updated_at)
                    VALUES(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT(owner) DO UPDATE SET
                      username=EXCLUDED.username,
                      level=EXCLUDED.level,
                      created_at=CASE 
                          WHEN profiles.created_at > 0 THEN profiles.created_at 
                          WHEN EXCLUDED.created_at > 0 THEN EXCLUDED.created_at
                          ELSE profiles.created_at 
                      END,
                      subscription_expiry=EXCLUDED.subscription_expiry,
                      auto_renew=EXCLUDED.auto_renew,
                      biography=EXCLUDED.biography,
                      avatar=EXCLUDED.avatar,
                      banner=EXCLUDED.banner,
                      flair=EXCLUDED.flair,
                      updated_at=EXCLUDED.updated_at,
                      deleted_at=NULL
                    """,
                    (
                        owner,
                        username,
                        int(level),
                        int(created_at),
                        int(subscription_expiry),
                        bool(auto_renew),
                        biography or "",
                        avatar or "",
                        banner or "",
                        flair or "",
                        int(updated_at),
                    ),
                )

    def update_profile_timestamp(self, owner: str, updated_at: int) -> None:
        """Update profile timestamp."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE profiles SET updated_at = %s WHERE LOWER(owner) = LOWER(%s)",
                    (int(updated_at), owner),
                )

    def update_profile_biography(self, owner: str, biography: str, updated_at: int) -> None:
        """Update biography field on a profile."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE profiles SET biography = %s, updated_at = %s WHERE LOWER(owner) = LOWER(%s)",
                    (biography or "", int(updated_at), owner),
                )

    def soft_delete_profile(self, owner: str, deleted_at: int) -> int:
        """Mark a profile as deleted (soft-delete). Returns rows affected."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE profiles SET deleted_at = %s, updated_at = %s "
                    "WHERE LOWER(owner) = LOWER(%s) AND deleted_at IS NULL",
                    (int(deleted_at), int(deleted_at), owner),
                )
                return cur.rowcount

    def set_enabled_agents(self, owner: str, agents: list[str]) -> None:
        """Set enabled agents for an owner (full replace from chain state)."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM enabled_agents WHERE LOWER(owner) = LOWER(%s)", (owner,))
                for pos, agent_addr in enumerate(agents):
                    cur.execute(
                        "INSERT INTO enabled_agents(owner, agent, position) VALUES(%s, %s, %s) ON CONFLICT DO NOTHING",
                        (owner, agent_addr, pos),
                    )

    def set_followed_users(self, owner: str, users: list[str]) -> None:
        """Set followed users for an owner (full replace from chain state)."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM followed_users WHERE LOWER(owner) = LOWER(%s)", (owner,))
                for pos, user_addr in enumerate(users):
                    cur.execute(
                        """
                        INSERT INTO followed_users(owner, target, position)
                        VALUES(%s, %s, %s)
                        ON CONFLICT(owner, target) DO NOTHING
                        """,
                        (owner, user_addr, pos),
                    )

    def set_followed_topics(self, owner: str, topics: list[str]) -> None:
        """Set followed topics for an owner (full replace from chain state)."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM followed_topics WHERE LOWER(owner) = LOWER(%s)", (owner,))
                for pos, topic in enumerate(topics):
                    cur.execute(
                        """
                        INSERT INTO followed_topics(owner, topic, position)
                        VALUES(%s, %s, %s)
                        ON CONFLICT(owner, topic) DO NOTHING
                        """,
                        (owner, topic, pos),
                    )

    def follow_user(self, owner: str, target: str) -> None:
        """Follow a user (add to followed_users with next position, evict oldest beyond cap)."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COALESCE(MAX(position), -1) + 1 FROM followed_users WHERE LOWER(owner) = LOWER(%s)",
                    (owner,),
                )
                pos = cur.fetchone()[0]
                cur.execute(
                    """
                    INSERT INTO followed_users(owner, target, position)
                    VALUES(%s, %s, %s)
                    ON CONFLICT(owner, target) DO NOTHING
                    """,
                    (owner, target, pos),
                )

    def unfollow_user(self, owner: str, target: str) -> None:
        """Unfollow a user (remove from followed_users)."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM followed_users WHERE LOWER(owner) = LOWER(%s) AND LOWER(target) = LOWER(%s)",
                    (owner, target),
                )

    def follow_topic(self, owner: str, topic: str) -> None:
        """Follow a topic (add to followed_topics with next position, evict oldest beyond cap)."""
        topic = self._strip_nul(topic) or ""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COALESCE(MAX(position), -1) + 1 FROM followed_topics WHERE LOWER(owner) = LOWER(%s)",
                    (owner,),
                )
                pos = cur.fetchone()[0]
                cur.execute(
                    """
                    INSERT INTO followed_topics(owner, topic, position)
                    VALUES(%s, %s, %s)
                    ON CONFLICT(owner, topic) DO NOTHING
                    """,
                    (owner, topic, pos),
                )

    def unfollow_topic(self, owner: str, topic: str) -> None:
        """Unfollow a topic (remove from followed_topics)."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM followed_topics WHERE LOWER(owner) = LOWER(%s) AND LOWER(topic) = LOWER(%s)",
                    (owner, topic),
                )

    def unfollow_topics_matching(self, owner: str, topic_pattern: str) -> int:
        """Unfollow topics matching a glob pattern (* maps to SQL %)."""
        pattern = str(topic_pattern or "").strip().lower()
        if not pattern:
            raise ValueError("topic pattern cannot be empty")
        with self._connect() as conn:
            with conn.cursor() as cur:
                if "*" in pattern:
                    like_pat = pattern.replace("%", "\\%").replace("_", "\\_").replace("*", "%")
                    cur.execute(
                        "DELETE FROM followed_topics WHERE LOWER(owner) = LOWER(%s) AND LOWER(topic) LIKE %s",
                        (owner, like_pat),
                    )
                else:
                    cur.execute(
                        "DELETE FROM followed_topics WHERE LOWER(owner) = LOWER(%s) AND LOWER(topic) = LOWER(%s)",
                        (owner, pattern),
                    )
                return int(cur.rowcount or 0)

    def block_post(self, owner: str, target: str) -> None:
        """Block a post (add to blocked_posts with next position, evict oldest beyond cap)."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COALESCE(MAX(position), -1) + 1 FROM blocked_posts WHERE LOWER(owner) = LOWER(%s)",
                    (owner,),
                )
                pos = cur.fetchone()[0]
                cur.execute(
                    """
                    INSERT INTO blocked_posts(owner, target, position)
                    VALUES(%s, %s, %s)
                    ON CONFLICT(owner, target) DO NOTHING
                    """,
                    (owner, target, pos),
                )
                self._evict_oldest(cur, "blocked_posts", "target", owner)

    def unblock_post(self, owner: str, target: str) -> None:
        """Unblock a post (remove from blocked_posts)."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM blocked_posts WHERE LOWER(owner) = LOWER(%s) AND LOWER(target) = LOWER(%s)",
                    (owner, target),
                )

    def block_user(self, owner: str, target: str) -> None:
        """Block a user (add to blocked_users with next position, evict oldest beyond cap)."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COALESCE(MAX(position), -1) + 1 FROM blocked_users WHERE LOWER(owner) = LOWER(%s)",
                    (owner,),
                )
                pos = cur.fetchone()[0]
                cur.execute(
                    """
                    INSERT INTO blocked_users(owner, target, position)
                    VALUES(%s, %s, %s)
                    ON CONFLICT(owner, target) DO NOTHING
                    """,
                    (owner, target, pos),
                )
                self._evict_oldest(cur, "blocked_users", "target", owner)

    def unblock_user(self, owner: str, target: str) -> None:
        """Unblock a user (remove from blocked_users)."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM blocked_users WHERE LOWER(owner) = LOWER(%s) AND LOWER(target) = LOWER(%s)",
                    (owner, target),
                )

    def block_topic(self, owner: str, target: str) -> None:
        """Block a topic (add to blocked_topics with next position, evict oldest beyond cap)."""
        target = self._strip_nul(target) or ""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COALESCE(MAX(position), -1) + 1 FROM blocked_topics WHERE LOWER(owner) = LOWER(%s)",
                    (owner,),
                )
                pos = cur.fetchone()[0]
                cur.execute(
                    """
                    INSERT INTO blocked_topics(owner, target, position)
                    VALUES(%s, %s, %s)
                    ON CONFLICT(owner, target) DO NOTHING
                    """,
                    (owner, target, pos),
                )
                self._evict_oldest(cur, "blocked_topics", "target", owner)

    def unblock_topic(self, owner: str, target: str) -> None:
        """Unblock a topic (remove from blocked_topics)."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM blocked_topics WHERE LOWER(owner) = LOWER(%s) AND LOWER(target) = LOWER(%s)",
                    (owner, target),
                )

    def unblock_topics_matching(self, owner: str, topic: str) -> int:
        """Unblock topics whose pattern matches the topic."""
        t = str(topic or "").strip().lower()
        if not t:
            raise ValueError("topic cannot be empty")
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM blocked_topics
                    WHERE LOWER(owner) = LOWER(%s)
                      AND LOWER(%s) LIKE LOWER(REPLACE(target, '*', '%%'))
                    """,
                    (owner, t),
                )
                return int(cur.rowcount or 0)

    def delete_post(self, target: str, owner: str | None = None) -> int:
        """Delete a post. If owner is None, admin delete."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                # Fetch parent and current subtree size before deleting
                cur.execute(
                    "SELECT target, comment_count, deleted FROM posts WHERE LOWER(txhash) = LOWER(%s)",
                    (target,),
                )
                row = cur.fetchone()
                if not row:
                    return 0
                parent_id = row[0] if row[0] else None
                subtree_count = int(row[1] or 0)
                was_deleted = bool(row[2])
                if was_deleted:
                    return 0

                if owner is None:
                    cur.execute(
                        "UPDATE posts SET deleted = TRUE WHERE txhash = %s AND deleted = FALSE",
                        (target,),
                    )
                else:
                    cur.execute(
                        "UPDATE posts SET deleted = TRUE WHERE txhash = %s AND LOWER(owner) = LOWER(%s) AND deleted = FALSE",
                        (target, owner),
                    )
                deleted_count = cur.rowcount
                # Decrement comment_count for all ancestors if post was deleted
                if deleted_count > 0 and parent_id:
                    # Remove this post + its descendants from ancestor counts
                    self._update_ancestor_comment_counts(cur, parent_id, delta=-(1 + subtree_count))
                return deleted_count

    def increment_ancestor_comment_counts(self, target_post_id: str) -> None:
        """Increment comment_count for all ancestors of a new comment.

        Called when a new comment is indexed. target_post_id is the parent post
        that the new comment is replying to.
        """
        if not target_post_id:
            return
        with self._connect() as conn:
            with conn.cursor() as cur:
                self._update_ancestor_comment_counts(cur, target_post_id, delta=1)

    def _update_ancestor_comment_counts(self, cur, post_id: str, delta: int) -> None:
        """Update comment_count for all ancestors of a post by delta.

        Walks up the parent chain and adjusts comment_count.
        For new comments: delta=+1 (increment)
        For deleted posts: delta=-1 (decrement)
        """
        if not post_id or delta == 0:
            return
        # Walk up the chain and update the post and its ancestors
        visited = set()
        current = post_id
        while current and current not in visited:
            visited.add(current)
            cur.execute(
                """
                UPDATE posts 
                SET comment_count = GREATEST(0, comment_count + %s)
                WHERE LOWER(txhash) = LOWER(%s) AND deleted = FALSE
                RETURNING target
                """,
                (delta, current),
            )
            row = cur.fetchone()
            if not row:
                break
            current = row[0] if row[0] else None

    def get_user_level(self, owner: str) -> int:
        """Get user level."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT level FROM profiles WHERE LOWER(owner) = LOWER(%s)", (owner,))
                row = cur.fetchone()
                return int(row[0]) if row and row[0] is not None else 0

    def get_post_owner(self, txhash: str) -> str | None:
        """Return owner for a given post txhash or None."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT owner FROM posts WHERE LOWER(txhash)=LOWER(%s) LIMIT 1", (txhash,))
                row = cur.fetchone()
                return row[0] if row and row[0] else None

    def insert_stats_event(
        self,
        event_type: str,
        session_id: str,
        created_at: int,
        user_address: str | None = None,
        page_path: str | None = None,
        browser_family: str | None = None,
        os_family: str | None = None,
        device_type: str | None = None,
    ) -> None:
        """Insert a stats event."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO stats_events(event_type, user_address, session_id, created_at, page_path, browser_family, os_family, device_type)
                    VALUES(%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        event_type,
                        user_address,
                        session_id,
                        int(created_at),
                        page_path,
                        browser_family,
                        os_family,
                        device_type,
                    ),
                )

    def upsert_difficulty(self, height: int, difficulty: int, msg_count: int, created_at: int) -> None:
        """Record difficulty and message count at a given block height."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO difficulty_history(height, difficulty, msg_count, created_at)
                    VALUES(%s, %s, %s, %s)
                    ON CONFLICT (height) DO UPDATE SET 
                        difficulty = EXCLUDED.difficulty, 
                        msg_count = EXCLUDED.msg_count,
                        created_at = EXCLUDED.created_at
                    """,
                    (int(height), int(difficulty), int(msg_count), int(created_at)),
                )

    def get_difficulty_history(self, since_ts: int) -> list[dict]:
        """Get difficulty history since a timestamp. Returns list of {height, difficulty, msg_count, timestamp}."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT height, difficulty, msg_count, created_at
                    FROM difficulty_history
                    WHERE created_at >= %s
                    ORDER BY height ASC
                    """,
                    (int(since_ts),),
                )
                rows = cur.fetchall()
                return [{"height": r[0], "difficulty": r[1], "msg_count": r[2], "timestamp": r[3]} for r in rows]

    def upsert_supply(self, height: int, total_supply: int, created_at: int, node_balance: int | None = None) -> None:
        """Record total supply (and optionally node balance) at a given block height."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO supply_history(height, total_supply, created_at, node_balance)
                    VALUES(%s, %s, %s, %s)
                    ON CONFLICT (height) DO UPDATE SET
                        total_supply = EXCLUDED.total_supply,
                        created_at = EXCLUDED.created_at,
                        node_balance = COALESCE(EXCLUDED.node_balance, supply_history.node_balance)
                    """,
                    (int(height), int(total_supply), int(created_at), node_balance),
                )

    def get_supply_history(self, since_ts: int) -> list[dict]:
        """Get supply history since a timestamp. Returns list of {height, total_supply, timestamp, node_balance}."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT height, total_supply, created_at, node_balance
                    FROM supply_history
                    WHERE created_at >= %s
                    ORDER BY height ASC
                    """,
                    (int(since_ts),),
                )
                rows = cur.fetchall()
                return [{"height": r[0], "total_supply": r[1], "timestamp": r[2], "node_balance": r[3]} for r in rows]

    # ========== Bridge Transaction Methods ==========

    def insert_bridge_transaction(
        self,
        tx_hash: str,
        direction: str,
        msg_type: str,
        burn_id: str,
        amount: int,
        created_at: int,
        height: int,
        source_chain: Optional[str] = None,
        destination_chain: Optional[str] = None,
        sender: Optional[str] = None,
        recipient: Optional[str] = None,
        validator: Optional[str] = None,
        destination_tx: Optional[str] = None,
        minted: bool = False,
    ) -> bool:
        """Insert a bridge transaction record. Skips duplicates during re-indexing."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO bridge_transactions (
                        tx_hash, direction, msg_type, source_chain, destination_chain,
                        burn_id, sender, recipient, amount, validator, destination_tx,
                        minted, created_at, height
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (tx_hash, msg_type) DO NOTHING
                    """,
                    (
                        tx_hash,
                        direction,
                        msg_type,
                        source_chain,
                        destination_chain,
                        burn_id,
                        sender,
                        recipient,
                        amount,
                        validator,
                        destination_tx,
                        minted,
                        created_at,
                        height,
                    ),
                )
                return cur.rowcount > 0  # True if inserted, False if duplicate

    def get_bridge_attestation(self, source_chain: str, burn_id: str) -> dict:
        """Get inbound bridge attestation by source_chain and burn_id.

        Returns dict with: found, minted, tx_hash, recipient, amount, validator, created_at,
                          attestor_count, attested_power, required_power
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                # Get attestation details with aggregated power info
                cur.execute(
                    """
                    SELECT 
                        MAX(tx_hash) as tx_hash,
                        MAX(recipient) as recipient,
                        MAX(amount) as amount,
                        MAX(validator) as validator,
                        BOOL_OR(minted) as minted,
                        MAX(created_at) as created_at,
                        COUNT(DISTINCT validator) as attestor_count,
                        COALESCE(SUM(power), 0) as attested_power,
                        MAX(required_power) as required_power
                    FROM bridge_transactions
                    WHERE direction = 'in'
                      AND msg_type = 'attest_burned'
                      AND LOWER(source_chain) = LOWER(%s)
                      AND burn_id = %s
                    """,
                    (source_chain, burn_id),
                )
                row = cur.fetchone()
                if not row or row[6] == 0:  # attestor_count == 0 means no records
                    return {"found": False, "minted": False}
                return {
                    "found": True,
                    "minted": bool(row[4]),
                    "tx_hash": row[0],
                    "recipient": row[1],
                    "amount": row[2],
                    "validator": row[3],
                    "created_at": row[5],
                    "attestor_count": row[6],
                    "attested_power": row[7],
                    "required_power": row[8],
                }

    def get_bridge_burn(self, burn_id: str) -> dict:
        """Get outbound bridge burn by burn_id (tx_hash).

        Returns dict with: found, minted, destination_chain, destination_address,
                          destination_tx, amount, created_at, attestor_count,
                          attested_power, required_power
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                # First get the burn record
                cur.execute(
                    """
                    SELECT destination_chain, recipient, amount, created_at
                    FROM bridge_transactions
                    WHERE direction = 'out'
                      AND msg_type = 'burn'
                      AND LOWER(tx_hash) = LOWER(%s)
                    LIMIT 1
                    """,
                    (burn_id,),
                )
                burn_row = cur.fetchone()
                if not burn_row:
                    return {"found": False, "minted": False}

                # Get attestation info with aggregated power
                cur.execute(
                    """
                    SELECT 
                        MAX(destination_tx) as destination_tx,
                        MAX(created_at) as minted_at,
                        COUNT(DISTINCT validator) as attestor_count,
                        COALESCE(SUM(power), 0) as attested_power,
                        MAX(required_power) as required_power,
                        BOOL_OR(minted) as minted
                    FROM bridge_transactions
                    WHERE direction = 'out'
                      AND msg_type = 'attest_minted'
                      AND LOWER(burn_id) = LOWER(%s)
                    """,
                    (burn_id,),
                )
                attest_row = cur.fetchone()
                # attest_row will always return a row, check attestor_count for records
                has_attestations = attest_row and attest_row[2] > 0

                return {
                    "found": True,
                    "minted": bool(attest_row[5]) if has_attestations else False,
                    "destination_chain": burn_row[0],
                    "destination_address": burn_row[1],
                    "amount": burn_row[2],
                    "created_at": burn_row[3],
                    "destination_tx": attest_row[0] if has_attestations else None,
                    "minted_at": attest_row[1] if has_attestations else None,
                    "attestor_count": attest_row[2] if has_attestations else 0,
                    "attested_power": attest_row[3] if has_attestations else 0,
                    "required_power": attest_row[4] if has_attestations else 0,
                }

    def update_bridge_attestation_minted(self, source_chain: str, burn_id: str, minted: bool) -> bool:
        """Update the minted status of an inbound attestation record."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE bridge_transactions
                    SET minted = %s
                    WHERE direction = 'in'
                      AND msg_type = 'attest_burned'
                      AND LOWER(source_chain) = LOWER(%s)
                      AND burn_id = %s
                    """,
                    (minted, source_chain, burn_id),
                )
                return cur.rowcount > 0

    def update_bridge_mint_attestation_confirmed(self, burn_id: str, minted: bool) -> bool:
        """Update the minted status of outbound attestation records (threshold met)."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE bridge_transactions
                    SET minted = %s
                    WHERE direction = 'out'
                      AND msg_type = 'attest_minted'
                      AND LOWER(burn_id) = LOWER(%s)
                    """,
                    (minted, burn_id),
                )
                return cur.rowcount > 0

    def update_bridge_attestation_power_by_tx(
        self,
        tx_hash: str,
        msg_type: str,
        power: int,
        attested_power: int,
        required_power: int,
    ) -> bool:
        """Update power fields for a bridge attestation record by tx_hash + msg_type.

        Each attestation message has a unique tx_hash for its msg_type.
        Called when processing bridge_attest or bridge_attest_minted events.
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE bridge_transactions
                    SET power = %s, attested_power = %s, required_power = %s
                    WHERE LOWER(tx_hash) = LOWER(%s)
                      AND msg_type = %s
                    """,
                    (power, attested_power, required_power, tx_hash, msg_type),
                )
                return cur.rowcount > 0
