"""PostgreSQL database operations for the indexer (hard-fail, no fallbacks)."""

from __future__ import annotations

import logging
from typing import Optional, Tuple

import psycopg

logger = logging.getLogger(__name__)


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
                        root_post_id TEXT
                    )
                    """
                )
                cur.execute("ALTER TABLE posts ADD COLUMN IF NOT EXISTS tag TEXT NOT NULL DEFAULT ''")
                cur.execute("ALTER TABLE posts ADD COLUMN IF NOT EXISTS root_topic TEXT")
                cur.execute("ALTER TABLE posts ADD COLUMN IF NOT EXISTS root_post_id TEXT")
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

                # User similarity cache for home feed v2 (similar users recommendations)
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
                        is_moderator BOOLEAN NOT NULL DEFAULT FALSE,
                        biography TEXT NOT NULL DEFAULT '',
                        avatar TEXT NOT NULL DEFAULT '',
                        banner TEXT NOT NULL DEFAULT ''
                    )
                    """
                )
                cur.execute("CREATE INDEX IF NOT EXISTS idx_profiles_owner_lower ON profiles(LOWER(owner))")

                # followed_mods (with position for order)
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS followed_mods (
                        owner TEXT NOT NULL,
                        moderator TEXT NOT NULL,
                        position INTEGER NOT NULL DEFAULT 0,
                        PRIMARY KEY (owner, moderator)
                    )
                    """
                )
                cur.execute("ALTER TABLE followed_mods ADD COLUMN IF NOT EXISTS position INTEGER NOT NULL DEFAULT 0")
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_followed_mods_moderator_lower ON followed_mods(LOWER(moderator))"
                )

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

                # quality_posts (for v1.5)
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS quality_posts (
                        owner TEXT NOT NULL,
                        target TEXT NOT NULL,
                        position INTEGER NOT NULL DEFAULT 0,
                        PRIMARY KEY (owner, target)
                    )
                    """
                )
                cur.execute("CREATE INDEX IF NOT EXISTS idx_quality_posts_owner_lower ON quality_posts(LOWER(owner))")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_quality_posts_target_lower ON quality_posts(LOWER(target))")

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

                # stats_events
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS stats_events (
                        id SERIAL PRIMARY KEY,
                        event_type TEXT NOT NULL,
                        user_address TEXT,
                        session_id TEXT NOT NULL,
                        created_at BIGINT NOT NULL,
                        user_agent TEXT,
                        ip_hash TEXT,
                        referrer TEXT,
                        page_path TEXT
                    )
                    """
                )
                cur.execute("CREATE INDEX IF NOT EXISTS idx_stats_events_created_at ON stats_events(created_at DESC)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_stats_events_session_id ON stats_events(session_id)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_stats_events_user_address ON stats_events(user_address)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_stats_events_event_type ON stats_events(event_type)")

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

                # user_fingerprints: device fingerprints for fraud detection
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS user_fingerprints (
                        id SERIAL PRIMARY KEY,
                        user_address VARCHAR(128) NOT NULL,
                        ip_hash VARCHAR(64),
                        user_agent TEXT,
                        user_agent_hash VARCHAR(64),
                        screen_width INTEGER,
                        screen_height INTEGER,
                        color_depth INTEGER,
                        pixel_ratio REAL,
                        timezone VARCHAR(64),
                        timezone_offset INTEGER,
                        language VARCHAR(32),
                        languages TEXT,
                        platform VARCHAR(64),
                        hardware_concurrency INTEGER,
                        device_memory REAL,
                        touch_support BOOLEAN,
                        canvas_hash VARCHAR(64),
                        webgl_vendor VARCHAR(128),
                        webgl_renderer VARCHAR(256),
                        webgl_hash VARCHAR(64),
                        fingerprint_hash VARCHAR(64),
                        first_seen BIGINT,
                        last_seen BIGINT,
                        seen_count INTEGER DEFAULT 1,
                        attributes JSONB DEFAULT '{}'
                    )
                    """
                )
                cur.execute("CREATE INDEX IF NOT EXISTS idx_fingerprints_user ON user_fingerprints(user_address)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_fingerprints_hash ON user_fingerprints(fingerprint_hash)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_fingerprints_ip ON user_fingerprints(ip_hash)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_fingerprints_canvas ON user_fingerprints(canvas_hash)")
                # Add JSONB column if missing (migration for existing tables)
                cur.execute(
                    """
                    DO $$
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns 
                            WHERE table_name = 'user_fingerprints' AND column_name = 'attributes'
                        ) THEN
                            ALTER TABLE user_fingerprints ADD COLUMN attributes JSONB DEFAULT '{}';
                        END IF;
                    END $$;
                    """
                )

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
        """Get post by txhash. Returns (topic, title, content, target, paid, thumbnail_url, created_at)."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT topic, title, content, target, paid, COALESCE(thumbnail_url,''), created_at FROM posts WHERE txhash = %s",
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
    ) -> None:
        """Insert or update a post."""
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
                        root_post_id
                    )
                    VALUES(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                      root_post_id=COALESCE(EXCLUDED.root_post_id, posts.root_post_id)
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
                    ),
                )

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

    def upsert_profile(self, owner: str, username: str | None, level: int, updated_at: int) -> None:
        """Insert or update a profile (basic fields only)."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO profiles(owner, username, level, created_at, updated_at)
                    VALUES(%s, %s, %s, %s, %s)
                    ON CONFLICT(owner) DO UPDATE SET
                      username=EXCLUDED.username,
                      level=EXCLUDED.level,
                      updated_at=EXCLUDED.updated_at
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
        self, owner: str, level: int, subscription_expiry: int, updated_at: int
    ) -> bool:
        """Update level and subscription_expiry for a profile (used for renewals)."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE profiles
                    SET level=%s, subscription_expiry=%s, updated_at=%s
                    WHERE LOWER(owner) = LOWER(%s)
                    """,
                    (int(level), int(subscription_expiry), int(updated_at), owner),
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
        is_moderator: bool,
        biography: str,
        avatar: str,
        banner: str,
        updated_at: int,
    ) -> None:
        """Insert or update a profile with all fields."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO profiles(owner, username, level, created_at, subscription_expiry,
                                         auto_renew, is_moderator, biography, avatar, banner, updated_at)
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
                      is_moderator=EXCLUDED.is_moderator,
                      biography=EXCLUDED.biography,
                      avatar=EXCLUDED.avatar,
                      banner=EXCLUDED.banner,
                      updated_at=EXCLUDED.updated_at
                    """,
                    (
                        owner,
                        username,
                        int(level),
                        int(created_at),
                        int(subscription_expiry),
                        bool(auto_renew),
                        bool(is_moderator),
                        biography or "",
                        avatar or "",
                        banner or "",
                        int(updated_at),
                    ),
                )

    def update_profile_subscription(
        self, owner: str, level: int, subscription_expiry: int, auto_renew: bool, updated_at: int
    ) -> None:
        """Update subscription-related fields for a profile."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE profiles SET 
                        level = %s,
                        subscription_expiry = %s,
                        auto_renew = %s,
                        updated_at = %s
                    WHERE LOWER(owner) = LOWER(%s)
                    """,
                    (int(level), int(subscription_expiry), bool(auto_renew), int(updated_at), owner),
                )

    def update_profile_timestamp(self, owner: str, updated_at: int) -> None:
        """Update profile timestamp."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE profiles SET updated_at = %s WHERE LOWER(owner) = LOWER(%s)",
                    (int(updated_at), owner),
                )

    def set_moderators(self, owner: str, moderators: list[str]) -> None:
        """Set moderators for an owner."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM followed_mods WHERE LOWER(owner) = LOWER(%s)", (owner,))
                for mod_addr in moderators:
                    cur.execute(
                        "INSERT INTO followed_mods(owner, moderator) VALUES(%s, %s) ON CONFLICT DO NOTHING",
                        (owner, mod_addr),
                    )

    def follow_user(self, owner: str, target: str) -> None:
        """Follow a user (add to followed_users with next position)."""
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
        """Follow a topic (add to followed_topics with next position)."""
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

    def block_post(self, owner: str, target: str) -> None:
        """Block a post (add to blocked_posts with next position)."""
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

    def unblock_post(self, owner: str, target: str) -> None:
        """Unblock a post (remove from blocked_posts)."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM blocked_posts WHERE LOWER(owner) = LOWER(%s) AND LOWER(target) = LOWER(%s)",
                    (owner, target),
                )

    def block_user(self, owner: str, target: str) -> None:
        """Block a user (add to blocked_users with next position)."""
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

    def unblock_user(self, owner: str, target: str) -> None:
        """Unblock a user (remove from blocked_users)."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM blocked_users WHERE LOWER(owner) = LOWER(%s) AND LOWER(target) = LOWER(%s)",
                    (owner, target),
                )

    def delete_post(self, target: str, owner: str | None = None) -> int:
        """Delete a post. If owner is None, admin delete."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                if owner is None:
                    cur.execute("UPDATE posts SET deleted = TRUE WHERE txhash = %s", (target,))
                else:
                    cur.execute(
                        "UPDATE posts SET deleted = TRUE WHERE txhash = %s AND LOWER(owner) = LOWER(%s)",
                        (target, owner),
                    )
                return cur.rowcount

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
        user_agent: str | None = None,
        ip_hash: str | None = None,
        referrer: str | None = None,
        page_path: str | None = None,
    ) -> None:
        """Insert a stats event."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO stats_events(event_type, user_address, session_id, created_at, user_agent, ip_hash, referrer, page_path)
                    VALUES(%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (event_type, user_address, session_id, int(created_at), user_agent, ip_hash, referrer, page_path),
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

    def upsert_supply(self, height: int, total_supply: int, created_at: int) -> None:
        """Record total supply at a given block height (sampled hourly)."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO supply_history(height, total_supply, created_at)
                    VALUES(%s, %s, %s)
                    ON CONFLICT (height) DO UPDATE SET
                        total_supply = EXCLUDED.total_supply,
                        created_at = EXCLUDED.created_at
                    """,
                    (int(height), int(total_supply), int(created_at)),
                )

    def get_supply_history(self, since_ts: int) -> list[dict]:
        """Get supply history since a timestamp. Returns list of {height, total_supply, timestamp}."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT height, total_supply, created_at
                    FROM supply_history
                    WHERE created_at >= %s
                    ORDER BY height ASC
                    """,
                    (int(since_ts),),
                )
                rows = cur.fetchall()
                return [{"height": r[0], "total_supply": r[1], "timestamp": r[2]} for r in rows]

    def _compute_all_user_similarities(self, cur) -> None:
        """
        One-time migration: compute initial similarity scores for all users with enough preferences.
        This pre-populates the user_similarity_cache so users get recommendations immediately.
        """
        import math
        import random
        import time

        MIN_SHARED_SAME_SIGN = 5
        MIN_FINAL_SIMILARITY = 0.05
        MAX_SIMILAR_USERS = 30
        BASE_TTL_SECONDS = 1800
        JITTER_RANGE_SECONDS = 900
        CONFIDENCE_REFERENCE = 31

        def confidence_factor(shared_dims: int) -> float:
            if shared_dims < 1:
                return 0.0
            return math.log(shared_dims + 1) / math.log(CONFIDENCE_REFERENCE)

        def author_factor(author_pref: float) -> float:
            if author_pref < 0:
                return 1.0 / (1.0 + abs(author_pref))
            else:
                return 1.0 + min(author_pref * 0.05, 0.2)

        def compute_agreement_score(vec_a: dict, vec_b: dict) -> tuple:
            shared_keys = set(vec_a.keys()) & set(vec_b.keys())
            same_sign_keys = []
            opposite_count = 0
            for k in shared_keys:
                wa, wb = vec_a[k], vec_b[k]
                if (wa > 0 and wb > 0) or (wa < 0 and wb < 0):
                    same_sign_keys.append(k)
                else:
                    opposite_count += 1
            n = len(same_sign_keys)
            if n < MIN_SHARED_SAME_SIGN:
                return 0.0, n, opposite_count
            vals_a = [vec_a[k] for k in same_sign_keys]
            vals_b = [vec_b[k] for k in same_sign_keys]
            mean_a = sum(vals_a) / n
            mean_b = sum(vals_b) / n
            centered_a = [v - mean_a for v in vals_a]
            centered_b = [v - mean_b for v in vals_b]
            numerator = sum(a * b for a, b in zip(centered_a, centered_b))
            denom_a = math.sqrt(sum(a * a for a in centered_a))
            denom_b = math.sqrt(sum(b * b for b in centered_b))
            if denom_a == 0 or denom_b == 0:
                return 1.0, n, opposite_count
            return numerator / (denom_a * denom_b), n, opposite_count

        # Get all users with preferences
        cur.execute(
            """
            SELECT LOWER(owner), COUNT(*) as pref_count
            FROM preferences
            GROUP BY LOWER(owner)
            HAVING COUNT(*) >= %s
            """,
            (MIN_SHARED_SAME_SIGN,),
        )
        users_with_prefs = [row[0] for row in cur.fetchall()]
        logger.info(f"v1.6.3 similarity migration: Found {len(users_with_prefs)} users with enough preferences")

        if not users_with_prefs:
            logger.info("v1.6.3 similarity migration: No users to process")
            return

        # Load all preference vectors
        cur.execute("SELECT LOWER(owner), pref_type || ':' || target, weight FROM preferences")
        all_prefs = cur.fetchall()
        user_vecs: dict = {}
        for owner, key, weight in all_prefs:
            if owner not in user_vecs:
                user_vecs[owner] = {}
            user_vecs[owner][key] = weight

        now_ts = int(time.time())
        total_cached = 0

        for i, viewer in enumerate(users_with_prefs):
            if viewer not in user_vecs:
                continue
            viewer_vec = user_vecs[viewer]
            if len(viewer_vec) < MIN_SHARED_SAME_SIGN:
                continue

            # Extract author preferences
            viewer_author_prefs = {}
            for key, weight in viewer_vec.items():
                if key.startswith("author:"):
                    viewer_author_prefs[key[7:]] = weight

            # Compute similarities
            results = []
            for other_user, other_vec in user_vecs.items():
                if other_user == viewer:
                    continue
                pearson, same_sign_count, _ = compute_agreement_score(viewer_vec, other_vec)
                if same_sign_count < MIN_SHARED_SAME_SIGN:
                    continue
                conf = confidence_factor(same_sign_count)
                author_pref = viewer_author_prefs.get(other_user, 0.0)
                auth = author_factor(author_pref)
                final = min(1.0, pearson * conf * auth)
                if final > MIN_FINAL_SIMILARITY:
                    results.append((other_user, final, same_sign_count))

            results.sort(key=lambda x: x[1], reverse=True)
            top_results = results[:MAX_SIMILAR_USERS]

            if top_results:
                ttl = BASE_TTL_SECONDS + random.randint(0, JITTER_RANGE_SECONDS)
                expires_at = now_ts + ttl
                for other_user, sim, shared in top_results:
                    cur.execute(
                        """
                        INSERT INTO user_similarity_cache(owner, similar_user, similarity, shared_dims, computed_at, expires_at)
                        VALUES(%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (owner, similar_user) DO UPDATE SET
                            similarity = EXCLUDED.similarity,
                            shared_dims = EXCLUDED.shared_dims,
                            computed_at = EXCLUDED.computed_at,
                            expires_at = EXCLUDED.expires_at
                        """,
                        (viewer, other_user, sim, shared, now_ts, expires_at),
                    )
                total_cached += len(top_results)

            if (i + 1) % 100 == 0:
                logger.info(f"v1.6.3 similarity migration: Processed {i + 1}/{len(users_with_prefs)} users")

        logger.info(
            f"v1.6.3 similarity migration: Completed. Cached {total_cached} similarity entries for {len(users_with_prefs)} users"
        )
