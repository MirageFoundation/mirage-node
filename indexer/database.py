"""PostgreSQL database operations for the indexer (hard-fail, no fallbacks)."""

from __future__ import annotations

import contextvars
import logging
import time
from contextlib import contextmanager
from typing import Optional, Tuple
from urllib.parse import urlparse

import psycopg

logger = logging.getLogger(__name__)

INDEXER_LIST_CAP = 100_000
TX_INDEX_CAP = 5000

# Matches the max_depth of the root walk in get_root_community_for_post.
MAX_ANCESTOR_WALK_DEPTH = 100

# Meta keys forming the atomic block checkpoint.
META_LAST_HEIGHT = "last_height"
META_LAST_BLOCK_HASH = "last_block_hash"
META_CHAIN_ID = "chain_id"

# Set for the duration of DatabaseManager.transaction(); every _connect() inside
# the same context joins that connection instead of opening an autocommit one.
_active_conn: contextvars.ContextVar[psycopg.Connection | None] = contextvars.ContextVar(
    "indexer_active_conn", default=None
)


def format_db_target(url: str) -> str:
    """Return host:port/database for logging; never credentials."""
    parsed = urlparse(url)
    if not parsed.hostname or not parsed.path or parsed.path == "/":
        raise RuntimeError("database_url is not parseable into host/port/database")
    port = parsed.port or 5432
    return f"{parsed.hostname}:{port}{parsed.path}"


class DatabaseManager:
    """Manages all database operations for the indexer."""

    # Allowed content tags for community safety classification
    _ALLOWED_COMMUNITY_TAGS = {"sensitive", "gore", "violence", "death", "adult"}

    # TODO: remove "porn" alias once all clients send "adult"
    _TAG_ALIASES = {"porn": "adult"}

    def __init__(self, db_url: str):
        if not db_url or not isinstance(db_url, str):
            raise RuntimeError("database_url is required")
        self.database_url = db_url
        self._init_db()

    @contextmanager
    def _connect(self):
        """Yield the active block transaction connection, or a short-lived autocommit connection."""
        active = _active_conn.get()
        if active is not None:
            yield active
            return
        conn = psycopg.connect(self.database_url, autocommit=True)
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def transaction(self, label: str = "block", height: int | None = None):
        """Run a unit of work in one PostgreSQL transaction. Nesting is rejected."""
        if _active_conn.get() is not None:
            raise RuntimeError(f"nested transaction rejected label={label} height={height}")
        conn = psycopg.connect(self.database_url, autocommit=False)
        token = _active_conn.set(conn)
        t0 = time.time()
        logger.debug("db.transaction.begin label=%s height=%s", label, height)
        try:
            yield conn
            conn.commit()
            logger.debug(
                "db.transaction.commit label=%s height=%s elapsed_ms=%.1f",
                label,
                height,
                (time.time() - t0) * 1000,
            )
        except Exception:
            conn.rollback()
            logger.error(
                "db.transaction.rollback label=%s height=%s elapsed_ms=%.1f",
                label,
                height,
                (time.time() - t0) * 1000,
                exc_info=True,
            )
            raise
        finally:
            _active_conn.reset(token)
            conn.close()

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

                # posts (community/root_community from v1.39.0)
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS posts (
                        txhash TEXT PRIMARY KEY,
                        owner TEXT NOT NULL,
                        community TEXT,
                        title TEXT,
                        content TEXT,
                        target TEXT,
                        created_at BIGINT NOT NULL,
                        edited_at BIGINT,
                        paid BOOLEAN NOT NULL DEFAULT FALSE,
                        deleted BOOLEAN NOT NULL DEFAULT FALSE,
                        thumbnail_url TEXT,
                        tag TEXT NOT NULL DEFAULT '',
                        root_community TEXT,
                        root_post_id TEXT,
                        comment_count INTEGER NOT NULL DEFAULT 0,
                        media TEXT NOT NULL DEFAULT '[]'
                    )
                    """
                )
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
                cur.execute("ALTER TABLE posts ADD COLUMN IF NOT EXISTS tag TEXT NOT NULL DEFAULT ''")
                cur.execute("ALTER TABLE posts ADD COLUMN IF NOT EXISTS root_community TEXT")
                cur.execute("ALTER TABLE posts ADD COLUMN IF NOT EXISTS root_post_id TEXT")
                cur.execute("ALTER TABLE posts ADD COLUMN IF NOT EXISTS comment_count INTEGER NOT NULL DEFAULT 0")
                cur.execute("ALTER TABLE posts ADD COLUMN IF NOT EXISTS protocol_version SMALLINT NOT NULL DEFAULT 0")
                cur.execute("ALTER TABLE posts ADD COLUMN IF NOT EXISTS root_txhash TEXT")
                cur.execute("ALTER TABLE posts ADD COLUMN IF NOT EXISTS post_sequence NUMERIC(20,0)")
                cur.execute("ALTER TABLE posts ADD COLUMN IF NOT EXISTS created_height BIGINT")
                cur.execute("ALTER TABLE posts ADD COLUMN IF NOT EXISTS created_epoch BIGINT")
                cur.execute("ALTER TABLE posts ADD COLUMN IF NOT EXISTS was_subscriber_at_creation BOOLEAN")
                cur.execute("ALTER TABLE posts ADD COLUMN IF NOT EXISTS deleted_height BIGINT")
                cur.execute("ALTER TABLE posts ADD COLUMN IF NOT EXISTS deleted_epoch BIGINT")
                # v1.12.0: dedicated media field (JSON array of URLs)
                cur.execute("ALTER TABLE posts ADD COLUMN IF NOT EXISTS media TEXT NOT NULL DEFAULT '[]'")
                # v1.18.0: relayer (validator/node address)
                cur.execute("ALTER TABLE posts ADD COLUMN IF NOT EXISTS relayer TEXT")
                # v1.19.0: media_meta (JSON array of {w,h} objects parallel to media)
                cur.execute("ALTER TABLE posts ADD COLUMN IF NOT EXISTS media_meta TEXT NOT NULL DEFAULT '[]'")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_posts_owner_lower ON posts(LOWER(owner))")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_posts_target_lower ON posts(LOWER(target))")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_posts_txhash_lower ON posts(LOWER(txhash))")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_posts_community_lower ON posts(LOWER(community))")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_posts_created_at ON posts(created_at DESC)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_posts_root ON posts((COALESCE(target,'') = ''))")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_posts_root_post_id ON posts(LOWER(root_post_id))")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_posts_relayer_lower ON posts(LOWER(relayer))")
                cur.execute(
                    """
                    UPDATE posts
                    SET root_community = COALESCE(root_community, community),
                        root_post_id = COALESCE(root_post_id, txhash)
                    WHERE COALESCE(target, '') = ''
                    """
                )

                # v1.6: Drop post_communities table (cross-posting removed)
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
                cur.execute("ALTER TABLE votes ADD COLUMN IF NOT EXISTS relayer TEXT")
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
                        -- Note: user_community_stats.net_votes is intentionally kept as-is.
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
                cur.execute("CREATE INDEX IF NOT EXISTS idx_votes_relayer_lower ON votes(LOWER(relayer))")

                # tx_index: universal tx tracking (all types, success + failure)
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS tx_index (
                        txhash TEXT PRIMARY KEY,
                        tx_type TEXT NOT NULL DEFAULT 'unknown',
                        code INTEGER NOT NULL DEFAULT 0,
                        raw_log TEXT NOT NULL DEFAULT '',
                        height BIGINT NOT NULL DEFAULT 0,
                        created_at BIGINT NOT NULL DEFAULT 0
                    )
                    """
                )
                cur.execute("CREATE INDEX IF NOT EXISTS idx_tx_index_tx_type ON tx_index(tx_type)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_tx_index_created_at ON tx_index(created_at DESC)")

                # v1.36.1: net_tags — epoch-scoped network tag parsed from the
                # relay tx memo. Keyed by txhash so posts.txhash and votes.txhash
                # both join to it and no future action type needs its own copy.
                #
                # Deliberately NOT in tx_index: that table is capped at
                # TX_INDEX_CAP and pruned on every upsert, so tags kept there
                # would be deleted within hours. This table has the opposite
                # lifecycle — the whole point is historical farm analysis.
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS net_tags (
                        txhash TEXT PRIMARY KEY,
                        namespace TEXT NOT NULL,
                        epoch TEXT NOT NULL,
                        family SMALLINT NOT NULL,
                        tag TEXT NOT NULL,
                        net_class TEXT,
                        relayer TEXT,
                        height BIGINT NOT NULL DEFAULT 0,
                        created_at BIGINT NOT NULL DEFAULT 0
                    )
                    """
                )
                # tag is where every agent query starts; without this it is a scan.
                cur.execute("CREATE INDEX IF NOT EXISTS idx_net_tags_tag ON net_tags(tag)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_net_tags_created_at ON net_tags(created_at DESC)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_net_tags_relayer_lower ON net_tags(LOWER(relayer))")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_net_tags_epoch ON net_tags(epoch)")

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
                cur.execute("ALTER TABLE awards ADD COLUMN IF NOT EXISTS relayer TEXT")
                cur.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uniq_awards_owner_target ON awards(LOWER(owner), LOWER(target))"
                )
                cur.execute("CREATE INDEX IF NOT EXISTS idx_awards_target_lower ON awards(LOWER(target))")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_awards_created_at ON awards(created_at DESC)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_awards_relayer_lower ON awards(LOWER(relayer))")

                # Per-user preferences for communities and authors (for home feed recommendations)
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
                            ON CONFLICT(owner, pref_type, target) DO UPDATE SET
                                weight = CASE
                                    WHEN EXCLUDED.updated_at > preferences.updated_at
                                    THEN EXCLUDED.weight
                                    ELSE preferences.weight
                                END,
                                updated_at = GREATEST(EXCLUDED.updated_at, preferences.updated_at);
                        END IF;
                        IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'author_preferences') THEN
                            INSERT INTO preferences(owner, pref_type, target, weight, updated_at)
                            SELECT owner, 'author', author, weight, updated_at FROM author_preferences
                            ON CONFLICT DO NOTHING;
                        END IF;
                    END $$;
                    """
                )

                # TODO: backend-owned tables removed — see web/backend/db.py init_backend_schema()

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

                # reserve_funds for indexer-only backend reads
                cur.execute("ALTER TABLE profiles ADD COLUMN IF NOT EXISTS reserve_funds BIGINT NOT NULL DEFAULT 0")

                # v1.14.0: soft-delete support for MsgDeleteUser
                cur.execute("ALTER TABLE profiles ADD COLUMN IF NOT EXISTS deleted_at BIGINT")
                cur.execute(
                    "ALTER TABLE profiles ADD COLUMN IF NOT EXISTS effective_paid BOOLEAN NOT NULL DEFAULT FALSE"
                )
                cur.execute("ALTER TABLE profiles ADD COLUMN IF NOT EXISTS subscriber_quota_epoch BIGINT")
                cur.execute("ALTER TABLE profiles ADD COLUMN IF NOT EXISTS subscriber_quota_used NUMERIC(20,0)")
                cur.execute("ALTER TABLE profiles ADD COLUMN IF NOT EXISTS renewal_next_attempt BIGINT")
                cur.execute("ALTER TABLE profiles ADD COLUMN IF NOT EXISTS renewal_last_attempt_epoch BIGINT")
                cur.execute("ALTER TABLE profiles ADD COLUMN IF NOT EXISTS renewal_warning_expiry BIGINT")
                cur.execute(
                    "ALTER TABLE profiles ADD COLUMN IF NOT EXISTS renewal_warning_sent BOOLEAN NOT NULL DEFAULT FALSE"
                )
                cur.execute("CREATE INDEX IF NOT EXISTS idx_profiles_deleted_at ON profiles(deleted_at)")
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_profiles_username_active "
                    "ON profiles(LOWER(username)) WHERE deleted_at IS NULL"
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

                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS community_curation_preferences (
                        owner TEXT NOT NULL,
                        community TEXT NOT NULL,
                        mode SMALLINT NOT NULL DEFAULT 0 CHECK (mode IN (0,1,2)),
                        pinned_team_id NUMERIC(20,0),
                        updated_height BIGINT NOT NULL DEFAULT 0,
                        PRIMARY KEY (owner, community),
                        CHECK ((mode = 1 AND pinned_team_id IS NOT NULL) OR (mode <> 1 AND pinned_team_id IS NULL))
                    )
                    """
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_ccp_owner_lower ON community_curation_preferences(LOWER(owner))"
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
                cur.execute("ALTER TABLE blocked_posts ADD COLUMN IF NOT EXISTS blocked_at BIGINT NOT NULL DEFAULT 0")
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
                cur.execute("ALTER TABLE blocked_users ADD COLUMN IF NOT EXISTS blocked_at BIGINT NOT NULL DEFAULT 0")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_blocked_users_owner_lower ON blocked_users(LOWER(owner))")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_blocked_users_target_lower ON blocked_users(LOWER(target))")

                # blocked_communities (was blocked_communities)
                cur.execute(
                    """
                    DO $$
                    BEGIN
                        IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'blocked_topics')
                           AND NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'blocked_communities') THEN
                            ALTER TABLE blocked_topics RENAME TO blocked_communities;
                        END IF;
                    END $$;
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS blocked_communities (
                        owner TEXT NOT NULL,
                        target TEXT NOT NULL,
                        position INTEGER NOT NULL DEFAULT 0,
                        PRIMARY KEY (owner, target)
                    )
                    """
                )
                cur.execute(
                    "ALTER TABLE blocked_communities ADD COLUMN IF NOT EXISTS blocked_at BIGINT NOT NULL DEFAULT 0"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_blocked_communities_owner_lower ON blocked_communities(LOWER(owner))"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_blocked_communities_target_lower ON blocked_communities(LOWER(target))"
                )

                # TODO: backend-owned tables removed — see web/backend/db.py init_backend_schema()

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
                        created_at BIGINT NOT NULL,
                        node_balance BIGINT,
                        node_staked BIGINT
                    )
                    """
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_supply_history_created_at ON supply_history(created_at DESC)"
                )
                cur.execute(
                    """
                    ALTER TABLE supply_history ADD COLUMN IF NOT EXISTS node_balance BIGINT
                    """
                )
                # Cumulative, monotonic node earnings. Balance samples cannot say
                # WHY a balance moved, so diffing them counted every inbound
                # transfer as income and every up-tick separately, inflating the
                # figure far past anything earned. These are summed from block
                # events instead: minted is what the core module paid this node,
                # fees is what it paid to broadcast. Diffing a cumulative counter
                # over a window is exact regardless of sample rate.
                cur.execute("ALTER TABLE supply_history ADD COLUMN IF NOT EXISTS node_minted_total BIGINT")
                cur.execute("ALTER TABLE supply_history ADD COLUMN IF NOT EXISTS node_fees_total BIGINT")

                # v1.39.0: these two tables kept their `topic` names through the
                # community rename because their rows were already on disk. They are
                # renamed here rather than in a migration file: schema init runs
                # before run_migrations(), so the CREATE TABLE below would otherwise
                # create an empty community_content_stats and strand the populated
                # topic_content_stats beside it. Renames are metadata-only, and index
                # and primary-key names do not follow a table rename, so they are
                # renamed explicitly too. Every branch is guarded, so this is a no-op
                # on a fresh database and on every startup after the first.
                cur.execute(
                    """
                    DO $$
                    BEGIN
                        IF EXISTS (
                            SELECT 1 FROM information_schema.tables
                            WHERE table_name = 'topic_content_stats'
                        ) AND NOT EXISTS (
                            SELECT 1 FROM information_schema.tables
                            WHERE table_name = 'community_content_stats'
                        ) THEN
                            ALTER TABLE topic_content_stats RENAME TO community_content_stats;
                        END IF;

                        IF EXISTS (
                            SELECT 1 FROM information_schema.tables
                            WHERE table_name = 'user_topic_stats'
                        ) AND NOT EXISTS (
                            SELECT 1 FROM information_schema.tables
                            WHERE table_name = 'user_community_stats'
                        ) THEN
                            ALTER TABLE user_topic_stats RENAME TO user_community_stats;
                        END IF;

                        IF EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'community_content_stats' AND column_name = 'topic'
                        ) AND NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'community_content_stats' AND column_name = 'community'
                        ) THEN
                            ALTER TABLE community_content_stats RENAME COLUMN topic TO community;
                        END IF;

                        IF EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'user_community_stats' AND column_name = 'topic'
                        ) AND NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'user_community_stats' AND column_name = 'community'
                        ) THEN
                            ALTER TABLE user_community_stats RENAME COLUMN topic TO community;
                        END IF;

                        IF EXISTS (SELECT 1 FROM pg_class WHERE relname = 'idx_topic_content_stats_topic_lower')
                           AND NOT EXISTS (SELECT 1 FROM pg_class WHERE relname = 'idx_community_content_stats_community_lower') THEN
                            ALTER INDEX idx_topic_content_stats_topic_lower
                                RENAME TO idx_community_content_stats_community_lower;
                        END IF;

                        IF EXISTS (SELECT 1 FROM pg_class WHERE relname = 'idx_user_topic_stats_owner')
                           AND NOT EXISTS (SELECT 1 FROM pg_class WHERE relname = 'idx_user_community_stats_owner') THEN
                            ALTER INDEX idx_user_topic_stats_owner
                                RENAME TO idx_user_community_stats_owner;
                        END IF;

                        IF EXISTS (SELECT 1 FROM pg_class WHERE relname = 'topic_content_stats_pkey')
                           AND NOT EXISTS (SELECT 1 FROM pg_class WHERE relname = 'community_content_stats_pkey') THEN
                            ALTER INDEX topic_content_stats_pkey RENAME TO community_content_stats_pkey;
                        END IF;

                        IF EXISTS (SELECT 1 FROM pg_class WHERE relname = 'user_topic_stats_pkey')
                           AND NOT EXISTS (SELECT 1 FROM pg_class WHERE relname = 'user_community_stats_pkey') THEN
                            ALTER INDEX user_topic_stats_pkey RENAME TO user_community_stats_pkey;
                        END IF;
                    END $$;
                    """
                )

                # community_content_stats: per-community content labels derived from post tags
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS community_content_stats (
                        community TEXT PRIMARY KEY,
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
                    "CREATE INDEX IF NOT EXISTS idx_community_content_stats_community_lower ON community_content_stats(LOWER(community))"
                )
                # v1.22.4: rename porn -> adult
                cur.execute(
                    "ALTER TABLE community_content_stats ADD COLUMN IF NOT EXISTS adult_count INTEGER NOT NULL DEFAULT 0"
                )

                # NOTE: Data migrations have been moved to indexer/migrations/
                # They run automatically on indexer startup via run_migrations()

                # ========== Indexer-Only Backend Tables ==========
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS balances (
                        address TEXT PRIMARY KEY,
                        balance BIGINT NOT NULL DEFAULT 0,
                        updated_at BIGINT NOT NULL DEFAULT 0
                    )
                    """
                )
                cur.execute("CREATE INDEX IF NOT EXISTS idx_balances_address_lower ON balances(LOWER(address))")

                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS chain_stats (
                        key TEXT PRIMARY KEY,
                        value JSONB NOT NULL DEFAULT '{}'::jsonb,
                        updated_at BIGINT NOT NULL DEFAULT 0
                    )
                    """
                )

                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS recent_blocks (
                        height BIGINT PRIMARY KEY,
                        hash TEXT NOT NULL,
                        block_time BIGINT NOT NULL DEFAULT 0
                    )
                    """
                )

                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS indexer_state (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL DEFAULT '',
                        updated_at BIGINT NOT NULL DEFAULT 0
                    )
                    """
                )

                # TODO: backend-owned tables removed — see web/backend/db.py init_backend_schema()

                # user_community_stats: per-user per-community voting stats for vote weighting
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS user_community_stats (
                        owner TEXT NOT NULL,
                        community TEXT NOT NULL,
                        vote_count INTEGER NOT NULL DEFAULT 0,
                        net_votes INTEGER NOT NULL DEFAULT 0,
                        unique_root_posts INTEGER NOT NULL DEFAULT 0,
                        post_count INTEGER NOT NULL DEFAULT 0,
                        PRIMARY KEY (owner, community)
                    )
                    """
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_user_community_stats_owner ON user_community_stats(LOWER(owner))"
                )
                # Legacy safety: if a past migration created 'score' instead of 'net_votes', rename it back.
                cur.execute(
                    """
                    DO $$
                    BEGIN
                        IF EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'user_community_stats' AND column_name = 'score'
                        ) AND NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'user_community_stats' AND column_name = 'net_votes'
                        ) THEN
                            ALTER TABLE user_community_stats RENAME COLUMN score TO net_votes;
                        END IF;
                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'user_community_stats' AND column_name = 'net_votes'
                        ) THEN
                            ALTER TABLE user_community_stats ADD COLUMN net_votes INTEGER NOT NULL DEFAULT 0;
                        END IF;
                    END $$;
                    """
                )

                # There used to be a vote backfill here, labelled one-time but run on
                # every startup, carrying its own copy of the stats definition. Its
                # ON CONFLICT DO NOTHING only looked idempotent while the row existed:
                # v1_36_0_repair_deleted_post_standing deletes rows whose whole vote
                # set was an author's self-upvote on a post they later deleted, and the
                # backfill — which had no such exclusion — re-inserted them verbatim on
                # the next restart, undoing the repair on every node.
                #
                # _VOTE_STATS_FROM_CANONICAL is the single definition of a vote-derived
                # stats row. Nothing bootstraps that table here: a fresh database has no
                # votes yet at this point, and a legacy one is rebuilt by
                # v1_33_0_rebuild_derived_stats.

                # Backfill post_count from existing posts
                cur.execute(
                    """
                    INSERT INTO user_community_stats (owner, community, vote_count, net_votes, unique_root_posts, post_count)
                    SELECT
                        LOWER(owner),
                        LOWER(root_community),
                        0, 0, 0,
                        COUNT(*)
                    FROM posts
                    WHERE root_community IS NOT NULL AND root_community != '' AND deleted = FALSE
                    GROUP BY LOWER(owner), LOWER(root_community)
                    ON CONFLICT (owner, community) DO UPDATE SET
                        post_count = EXCLUDED.post_count
                    """
                )

                # TODO: backend-owned tables removed — see web/backend/db.py init_backend_schema()

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

                # TODO: backend-owned tables removed — see web/backend/db.py init_backend_schema()

    def get_meta(self, key: str) -> str | None:
        """Read a meta value. Returns None when the key is absent."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT value FROM meta WHERE key = %s", (key,))
                row = cur.fetchone()
                return row[0] if row else None

    def set_meta(self, key: str, value: str) -> None:
        """Write a meta value."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO meta(key, value) VALUES(%s, %s)
                    ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
                    """,
                    (key, str(value)),
                )

    def set_checkpoint(self, height: int, block_hash: str, chain_id: str) -> None:
        """Atomically set last_height, last_block_hash, chain_id in meta (must be inside transaction)."""
        if _active_conn.get() is None:
            raise RuntimeError(f"set_checkpoint must run inside a transaction height={height}")
        if not block_hash or not chain_id:
            raise RuntimeError(f"set_checkpoint requires block_hash and chain_id height={height}")
        rows = [
            (META_LAST_HEIGHT, str(int(height))),
            (META_LAST_BLOCK_HASH, str(block_hash)),
            (META_CHAIN_ID, str(chain_id)),
        ]
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.executemany(
                    """
                    INSERT INTO meta(key, value) VALUES(%s, %s)
                    ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
                    """,
                    rows,
                )
        logger.debug(
            "db.checkpoint.set height=%s block_hash=%s chain_id=%s",
            height,
            block_hash,
            chain_id,
        )

    def get_last_height(self) -> int:
        """Get last processed height from meta table."""
        value = self.get_meta(META_LAST_HEIGHT)
        if value is None:
            return 0
        return int(value)

    def set_last_height(self, height: int) -> None:
        """Removed as a public height cursor. Use set_checkpoint inside a block transaction."""
        raise RuntimeError(
            f"set_last_height({height}) is forbidden; write meta.last_height only via set_checkpoint "
            "inside a block transaction so chain_id and block hash stay atomic with the height"
        )

    def get_post(self, txhash: str):
        """Get post by txhash.

        Returns (community, title, content, target, paid, thumbnail_url, created_at,
        media, deleted). `deleted` is last so positional readers keep working.
        The edit handler needs it: a soft delete is terminal, and an edit that
        does not check it republishes the post.
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT community, title, content, target, paid, COALESCE(thumbnail_url,''), created_at, COALESCE(media,'[]'), COALESCE(deleted, FALSE) FROM posts WHERE txhash = %s",
                    (txhash,),
                )
                return cur.fetchone()

    def get_post_protocol_version(self, txhash: str) -> int:
        """Return the stored protocol version for an existing post."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT protocol_version FROM posts WHERE LOWER(txhash) = LOWER(%s)", (txhash,))
                row = cur.fetchone()
        if row is None:
            raise RuntimeError(f"post protocol version target is missing: {txhash}")
        return int(row[0])

    def get_root_community_for_post(self, txhash: str):
        """
        Return (root_community, root_post_id) for a given post/comment, or (None, None) if not found.

        - For new data the posts table stores root_community/root_post_id directly, so this is a
          single-row lookup.
        - For older rows without these fields populated we fall back to a bounded parent walk,
          and opportunistically backfill root_community/root_post_id for the discovered root.
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
                            COALESCE(root_community, ''),
                            COALESCE(root_post_id, ''),
                            COALESCE(community, ''),
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
                    root_community, root_post_id, community, target, _deleted = row
                    root_community_str = str(root_community or "").strip().lower()
                    root_post_str = str(root_post_id or "").strip().lower()
                    community_str = str(community or "").strip()
                    parent = str(target or "").strip().lower()

                    # Fast path: already denormalised.
                    if root_community_str and root_post_str:
                        return root_community_str, root_post_str

                    # Reached a root post (no parent) – derive and persist root_community/root_post_id.
                    if not parent:
                        final_community = community_str.lower() if community_str else None
                        final_root_id = current_id
                        # Best-effort backfill for legacy rows. This runs inside the
                        # block transaction, where a failed statement aborts the whole
                        # transaction — so swallowing the error is not enough to keep
                        # the caller alive, and the block would die later pointing at
                        # the wrong statement. The savepoint is what actually makes it
                        # best-effort.
                        cur.execute("SAVEPOINT root_community_backfill")
                        try:
                            cur.execute(
                                "UPDATE posts SET root_community = %s, root_post_id = %s WHERE LOWER(txhash) = LOWER(%s)",
                                (final_community, final_root_id, current_id),
                            )
                        except Exception:
                            cur.execute("ROLLBACK TO SAVEPOINT root_community_backfill")
                            logger.warning("root_community backfill failed for %s; continuing", current_id)
                        else:
                            cur.execute("RELEASE SAVEPOINT root_community_backfill")
                        return final_community, final_root_id

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

    @staticmethod
    def _sanitize_wh(w: int, h: int) -> dict:
        """Return {"w": w, "h": h} if both are valid ints in [1, 10000], else {}."""
        try:
            w, h = int(w), int(h)
        except (TypeError, ValueError):
            return {}
        if 1 <= w <= 10000 and 1 <= h <= 10000:
            return {"w": w, "h": h}
        return {}

    @staticmethod
    def _extract_media_meta(media_urls: list[str]) -> list[dict]:
        """Extract w/h metadata from media URL query params."""
        from urllib.parse import urlparse, parse_qs

        meta = []
        for url in media_urls or []:
            entry = {}
            try:
                parsed = urlparse(url)
                qs = parse_qs(parsed.query)
                w = int(qs["w"][0]) if "w" in qs else 0
                h = int(qs["h"][0]) if "h" in qs else 0
                entry = DatabaseManager._sanitize_wh(w, h)
            except (TypeError, ValueError, KeyError, IndexError):
                # Expected shapes of garbage in an attacker-supplied URL.
                pass
            except Exception:
                # Media URLs are attacker-controlled, so the list above is a
                # guess about which shapes exist. Missing w/h costs a layout
                # hint; an escaping raise stops indexing on every node at the
                # same block. Unexpected, so it keeps the traceback.
                logger.exception("[media_meta] unparseable media URL, no dimensions: %r", url)
            meta.append(entry)
        return meta

    def upsert_post(
        self,
        txhash: str,
        owner: str,
        created_at: int,
        community: str,
        title: str,
        content: str,
        target: str,
        paid: bool,
        relayer: Optional[str] = None,
        edited_at: Optional[int] = None,
        deleted: bool = False,
        thumbnail_url: Optional[str] = None,
        tag: str = "",
        root_community: Optional[str] = None,
        root_post_id: Optional[str] = None,
        media: Optional[list[str]] = None,
        protocol_version: int = 0,
    ) -> None:
        """Insert or update a post."""
        import json as _json

        community = self._strip_nul(community) or ""
        title = self._strip_nul(title) or ""
        content = self._strip_nul(content) or ""
        target = self._strip_nul(target) or ""
        tag = self._strip_nul(tag) or ""
        thumbnail_url = self._strip_nul(thumbnail_url)
        root_community = self._strip_nul(root_community)
        root_post_id = self._strip_nul(root_post_id)
        relayer = self._strip_nul(relayer)
        media_json = _json.dumps(media or [])
        media_meta_json = _json.dumps(self._extract_media_meta(media or []))
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO posts(
                        txhash,
                        owner,
                        community,
                        title,
                        content,
                        target,
                        created_at,
                        edited_at,
                        paid,
                        deleted,
                        thumbnail_url,
                        tag,
                        root_community,
                        root_post_id,
                        media,
                        relayer,
                        media_meta,
                        protocol_version
                    )
                    VALUES(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT(txhash) DO UPDATE SET
                      owner=EXCLUDED.owner,
                      -- A comment's MsgPost carries no community of its own, so a
                      -- replay would blank the one denormalized from its root and
                      -- drop the comment back out of every community feed. Same
                      -- reason root_community/root_post_id are coalesced below.
                      community=COALESCE(NULLIF(EXCLUDED.community, ''), posts.community),
                      title=EXCLUDED.title,
                      content=EXCLUDED.content,
                      target=EXCLUDED.target,
                      created_at=EXCLUDED.created_at,
                      edited_at=EXCLUDED.edited_at,
                      paid=EXCLUDED.paid,
                      deleted=EXCLUDED.deleted,
                      thumbnail_url=EXCLUDED.thumbnail_url,
                      tag=EXCLUDED.tag,
                      root_community=COALESCE(EXCLUDED.root_community, posts.root_community),
                      root_post_id=COALESCE(EXCLUDED.root_post_id, posts.root_post_id),
                      media=EXCLUDED.media,
                      relayer=EXCLUDED.relayer,
                      media_meta=EXCLUDED.media_meta,
                      protocol_version=EXCLUDED.protocol_version
                    """,
                    (
                        txhash,
                        owner,
                        community or "",
                        title,
                        content,
                        target,
                        int(created_at),
                        int(edited_at) if edited_at else None,
                        bool(paid),
                        bool(deleted),
                        thumbnail_url,
                        tag or "",
                        (root_community or None),
                        (root_post_id or None),
                        media_json,
                        relayer,
                        media_meta_json,
                        int(protocol_version),
                    ),
                )

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

    def update_post_protocol_metadata(self, txhash: str, metadata: dict) -> None:
        """Persist absolute chain metadata for a post that has it."""
        target = str(txhash).strip().lower()
        root_hash = str(metadata["root_hash"]).strip().lower()
        community = str(metadata["community"]).strip().lower()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE posts
                    SET community = %s,
                        root_community = %s,
                        root_txhash = %s,
                        root_post_id = %s,
                        post_sequence = %s,
                        created_height = %s,
                        created_epoch = %s,
                        was_subscriber_at_creation = %s,
                        deleted_height = NULLIF(%s, 0),
                        deleted_epoch = NULLIF(%s, 0)
                    WHERE LOWER(txhash) = %s
                    """,
                    (
                        community,
                        community,
                        root_hash,
                        root_hash,
                        int(metadata["global_sequence"]),
                        int(metadata["created_height"]),
                        int(metadata["created_epoch"]),
                        bool(metadata["was_subscriber_at_creation"]),
                        int(metadata["deleted_height"]),
                        int(metadata["deleted_epoch"]),
                        target,
                    ),
                )
                if cur.rowcount != 1:
                    raise RuntimeError(f"post metadata target is missing from posts: {target}")

    def update_subscription_runtime(self, owner: str, runtime: dict) -> None:
        """Persist quota and renewal state in the existing profile columns."""
        with self._connect() as conn:
            with conn.cursor() as cur:

                def _opt_int(key: str):
                    value = runtime[key]
                    return None if value is None else int(value)

                cur.execute(
                    """
                    UPDATE profiles
                    SET subscriber_quota_epoch=%s,
                        subscriber_quota_used=%s,
                        renewal_next_attempt=%s,
                        renewal_last_attempt_epoch=%s,
                        renewal_warning_expiry=%s,
                        renewal_warning_sent=%s
                    WHERE LOWER(owner)=LOWER(%s)
                    """,
                    (
                        int(runtime["quota_epoch"]),
                        int(runtime["quota_used"]),
                        _opt_int("renewal_next_attempt"),
                        _opt_int("renewal_last_attempt_epoch"),
                        _opt_int("renewal_expiry"),
                        # Column is NOT NULL DEFAULT FALSE — never write NULL.
                        bool(runtime["renewal_warning_sent"]),
                        owner,
                    ),
                )

    def filter_subscription_runtime_owners(self, addresses: set[str]) -> set[str]:
        """Return addresses whose indexed tier causes runtime refreshes."""
        normalized = sorted({str(value).strip().lower() for value in addresses if str(value).strip()})
        if not normalized:
            return set()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT LOWER(owner)
                    FROM profiles
                    WHERE LOWER(owner) = ANY(%s)
                      AND (effective_paid = TRUE OR level >= 100)
                    """,
                    (normalized,),
                )
                return {str(row[0]) for row in cur.fetchall() if row and row[0]}
                if cur.rowcount != 1:
                    raise RuntimeError(f"subscription runtime profile is missing: {owner}")

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
        t = cls._TAG_ALIASES.get(t, t)
        if t in cls._ALLOWED_COMMUNITY_TAGS:
            return t
        return ""

    @staticmethod
    def _compute_dominant_tag(
        total: int,
        sensitive: int,
        gore: int,
        violence: int,
        death: int,
        adult: int,
    ) -> Tuple[str, float]:
        """Compute dominant tag (>=50% of posts)."""
        if total <= 0:
            return "", 0.0

        counts = {
            "sensitive": int(sensitive or 0),
            "gore": int(gore or 0),
            "violence": int(violence or 0),
            "death": int(death or 0),
            "adult": int(adult or 0),
        }

        dominant_tag = ""
        dominant_ratio = 0.0
        for key, value in counts.items():
            ratio = float(value) / float(total)
            if ratio >= 0.5 and ratio > dominant_ratio:
                dominant_tag = key
                dominant_ratio = ratio
        return dominant_tag, dominant_ratio

    def update_community_content_stats(self, community: str, tag: str) -> None:
        """Increment per-community content stats based on a new root post tag.

        Counters here are cumulative and have no per-post guard, so callers MUST invoke
        this only for a root post that is genuinely new to the index. Calling it on an
        edit or a replay double-counts the post.
        """
        community_norm = str(community or "").strip().lower()
        if not community_norm:
            return
        tag_norm = self._normalize_tag(tag)
        sensitive_inc = 1 if tag_norm == "sensitive" else 0
        gore_inc = 1 if tag_norm == "gore" else 0
        violence_inc = 1 if tag_norm == "violence" else 0
        death_inc = 1 if tag_norm == "death" else 0
        adult_inc = 1 if tag_norm == "adult" else 0

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO community_content_stats(
                        community,
                        total_posts,
                        sensitive_count,
                        gore_count,
                        violence_count,
                        death_count,
                        adult_count
                    ) VALUES(%s, 1, %s, %s, %s, %s, %s)
                    ON CONFLICT(community) DO UPDATE SET
                        total_posts = community_content_stats.total_posts + 1,
                        sensitive_count = community_content_stats.sensitive_count + EXCLUDED.sensitive_count,
                        gore_count = community_content_stats.gore_count + EXCLUDED.gore_count,
                        violence_count = community_content_stats.violence_count + EXCLUDED.violence_count,
                        death_count = community_content_stats.death_count + EXCLUDED.death_count,
                        adult_count = community_content_stats.adult_count + EXCLUDED.adult_count
                    RETURNING total_posts, sensitive_count, gore_count, violence_count, death_count, adult_count
                    """,
                    (
                        community_norm,
                        sensitive_inc,
                        gore_inc,
                        violence_inc,
                        death_inc,
                        adult_inc,
                    ),
                )
                row = cur.fetchone()
                if not row:
                    return
                total_posts, sensitive, gore, violence, death, adult = row
                dominant_tag, dominant_ratio = self._compute_dominant_tag(
                    total_posts, sensitive, gore, violence, death, adult
                )
                cur.execute(
                    """
                    UPDATE community_content_stats
                    SET dominant_tag = %s,
                        dominant_ratio = %s
                    WHERE community = %s
                    """,
                    (dominant_tag, float(dominant_ratio), community_norm),
                )

    def recompute_community_content_stats(self, community: str) -> None:
        """Recompute stats for a community from the posts table (root posts only)."""
        community_norm = str(community or "").strip().lower()
        if not community_norm:
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
                        SUM(CASE WHEN LOWER(tag) IN ('adult', 'porn') THEN 1 ELSE 0 END) AS adult_count
                    FROM posts
                    WHERE COALESCE(target, '') = ''
                      AND deleted = FALSE
                      AND LOWER(COALESCE(community, '')) = %s
                    """,
                    (community_norm,),
                )
                row = cur.fetchone()
                if not row:
                    return
                total_posts, sensitive, gore, violence, death, adult = [int(x or 0) for x in row]
                if total_posts <= 0:
                    cur.execute("DELETE FROM community_content_stats WHERE community = %s", (community_norm,))
                    return
                dominant_tag, dominant_ratio = self._compute_dominant_tag(
                    total_posts, sensitive, gore, violence, death, adult
                )
                cur.execute(
                    """
                    INSERT INTO community_content_stats(
                        community,
                        total_posts,
                        sensitive_count,
                        gore_count,
                        violence_count,
                        death_count,
                        adult_count,
                        dominant_tag,
                        dominant_ratio
                    ) VALUES(%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT(community) DO UPDATE SET
                        total_posts = EXCLUDED.total_posts,
                        sensitive_count = EXCLUDED.sensitive_count,
                        gore_count = EXCLUDED.gore_count,
                        violence_count = EXCLUDED.violence_count,
                        death_count = EXCLUDED.death_count,
                        adult_count = EXCLUDED.adult_count,
                        dominant_tag = EXCLUDED.dominant_tag,
                        dominant_ratio = EXCLUDED.dominant_ratio
                    """,
                    (
                        community_norm,
                        total_posts,
                        sensitive,
                        gore,
                        violence,
                        death,
                        adult,
                        dominant_tag,
                        float(dominant_ratio),
                    ),
                )

    def select_redgifs_posts_missing_thumbnail(
        self, limit: int, exclude_txhashes: "list[str] | tuple[str, ...]" = ()
    ) -> list[tuple[str, str, str]]:
        """(txhash, media, content) for root posts linking RedGIFs with no thumbnail.

        Newest first: a post someone may still be looking at is worth more than
        one from last year, and the caller resolves only a small batch per pass.

        ``exclude_txhashes`` drops rows the caller has already found
        unresolvable. Without it a deleted gif is a permanent resident of this
        window — it can never gain a thumbnail and can never leave — so once
        enough of them accumulate at the head of the ordering, the window fills
        with rows that can never resolve and no older post is ever reached.
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT txhash, COALESCE(media, '[]'), COALESCE(content, '')
                    FROM posts
                    WHERE COALESCE(thumbnail_url, '') = ''
                      AND COALESCE(target, '') = ''
                      AND deleted = FALSE
                      AND (content ILIKE %s OR media ILIKE %s)
                      AND NOT (txhash = ANY(%s))
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    ("%redgifs.com%", "%redgifs.com%", list(exclude_txhashes), int(limit)),
                )
                return [(row[0], row[1], row[2]) for row in cur.fetchall()]

    def select_rumble_posts_needing_resolution(
        self, limit: int, exclude_txhashes: "list[str] | tuple[str, ...]" = ()
    ) -> list[tuple[str, str, str, str, str]]:
        """(txhash, media, content, media_meta, thumbnail_url) for unresolved Rumble posts.

        A post qualifies while it is missing either half of what one oEmbed
        answer provides: the thumbnail, or the embed id that the clients need
        in order to frame the right video. The embed test is a substring match
        because media_meta is TEXT; the caller re-checks it properly.
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT txhash, COALESCE(media, '[]'), COALESCE(content, ''),
                           COALESCE(media_meta, '[]'), COALESCE(thumbnail_url, '')
                    FROM posts
                    WHERE COALESCE(target, '') = ''
                      AND deleted = FALSE
                      AND (content ILIKE %s OR media ILIKE %s)
                      AND (COALESCE(thumbnail_url, '') = '' OR COALESCE(media_meta, '[]') NOT LIKE %s)
                      AND NOT (txhash = ANY(%s))
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    ("%rumble.com%", "%rumble.com%", '%"embed"%', list(exclude_txhashes), int(limit)),
                )
                return [(row[0], row[1], row[2], row[3], row[4]) for row in cur.fetchall()]

    def update_post_media_meta(self, txhash: str, media_meta_json: str) -> None:
        """Replace the derived per-media metadata for a post."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE posts SET media_meta = %s WHERE LOWER(txhash) = LOWER(%s)",
                    (media_meta_json, txhash),
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
        relayer: Optional[str] = None,
    ) -> None:
        """Insert or update a vote.

        user_vote: The user's vote direction (-1, 0, +1).
        user_weight: Weighted contribution to post points (0 if user doesn't follow community).
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO votes(txhash, owner, target, user_vote, user_weight, created_at, paid, relayer)
                    VALUES(%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT(LOWER(owner), LOWER(target)) DO UPDATE SET
                      txhash=EXCLUDED.txhash,
                      user_vote=EXCLUDED.user_vote,
                      user_weight=EXCLUDED.user_weight,
                      created_at=EXCLUDED.created_at,
                      paid=EXCLUDED.paid,
                      relayer=EXCLUDED.relayer
                    """,
                    (txhash, owner, target, float(user_vote), float(user_weight), int(created_at), bool(paid), relayer),
                )

    def upsert_tx_index(
        self,
        txhash: str,
        tx_type: str,
        code: int,
        raw_log: str,
        height: int,
        created_at: int,
    ) -> None:
        """Insert or update a tx in the universal tx_index (success + failure)."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO tx_index(txhash, tx_type, code, raw_log, height, created_at)
                    VALUES(%s, %s, %s, %s, %s, %s)
                    ON CONFLICT(txhash) DO UPDATE SET
                      tx_type=EXCLUDED.tx_type,
                      code=EXCLUDED.code,
                      raw_log=EXCLUDED.raw_log,
                      height=EXCLUDED.height,
                      created_at=EXCLUDED.created_at
                    """,
                    (
                        txhash,
                        self._strip_nul(str(tx_type or "unknown")),
                        int(code),
                        self._strip_nul(str(raw_log or "")),
                        int(height),
                        int(created_at),
                    ),
                )
                cur.execute("SELECT COUNT(*) FROM tx_index")
                total = int((cur.fetchone() or [0])[0] or 0)
                if total > TX_INDEX_CAP:
                    cur.execute(
                        """
                        DELETE FROM tx_index
                        WHERE txhash NOT IN (
                            SELECT txhash FROM tx_index
                            ORDER BY created_at DESC, height DESC
                            LIMIT %s
                        )
                        """,
                        (TX_INDEX_CAP,),
                    )
                    logger.debug("Pruned tx_index to cap=%s (total=%s)", TX_INDEX_CAP, total)

    def upsert_net_tag(
        self,
        txhash: str,
        namespace: str,
        epoch: str,
        family: int,
        tag: str,
        net_class: str | None,
        relayer: str,
        height: int,
        created_at: int,
    ) -> None:
        """Store the network tag a relayer published in a transaction's memo.

        Never pruned. Do not add a row-count cap here the way tx_index has one:
        the value of a tag is precisely that it can be correlated with activity
        weeks later, and the SELECT-COUNT-then-DELETE-NOT-IN pattern used there
        would also run a full count on every single indexed transaction. If this
        ever needs bounding, delete by created_at, not by rank.
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO net_tags(txhash, namespace, epoch, family, tag, net_class, relayer, height, created_at)
                    VALUES(%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT(txhash) DO UPDATE SET
                      namespace=EXCLUDED.namespace,
                      epoch=EXCLUDED.epoch,
                      family=EXCLUDED.family,
                      tag=EXCLUDED.tag,
                      net_class=EXCLUDED.net_class,
                      relayer=EXCLUDED.relayer,
                      height=EXCLUDED.height,
                      created_at=EXCLUDED.created_at
                    """,
                    (
                        txhash,
                        self._strip_nul(str(namespace or "")),
                        self._strip_nul(str(epoch or "")),
                        int(family),
                        self._strip_nul(str(tag or "")),
                        self._strip_nul(str(net_class)) if net_class else None,
                        self._strip_nul(str(relayer or "")),
                        int(height),
                        int(created_at),
                    ),
                )

    def is_community_joined(self, owner: str, community: str) -> bool:
        """Return True if the owner currently follows the given community."""
        owner_norm = str(owner or "").strip()
        community_norm = str(community or "").strip()
        if not owner_norm or not community_norm:
            return False
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM community_curation_preferences WHERE LOWER(owner) = LOWER(%s) AND LOWER(community) = LOWER(%s) LIMIT 1",
                    (owner_norm, community_norm),
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

    def get_user_community_stats(self, owner: str, community: str):
        """Get user's voting stats in a community. Returns (vote_count, net_votes, unique_root_posts, post_count) or None."""
        owner_norm = str(owner or "").strip().lower()
        community_norm = str(community or "").strip().lower()
        if not owner_norm or not community_norm:
            return None
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT vote_count, net_votes, unique_root_posts, post_count FROM user_community_stats WHERE owner = %s AND community = %s",
                    (owner_norm, community_norm),
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

    def update_user_community_stats(
        self,
        owner: str,
        community: str,
        net_votes_delta: int,
        root_post_id: str,
        is_new_vote: bool = True,
        post_increment: int = 0,
    ) -> None:
        """
        Update user's voting stats in a community after a vote or post.

        vote_count: Only incremented for NEW votes (first vote on a target), not re-votes.
                    This prevents gaming by toggling votes on the same post.
        net_votes: Shifted by net_votes_delta, which the caller MUST compute as
                   (new_direction - previous_direction) so re-votes and cleared votes
                   reverse their prior contribution. A repeated identical vote is delta 0.
        unique_root_posts: Incremented if this is a new root post thread for this user.
        post_count: Incremented when post_increment > 0 (for new posts/comments).
        """
        owner_norm = str(owner or "").strip().lower()
        community_norm = str(community or "").strip().lower()
        root_norm = str(root_post_id or "").strip().lower()
        if not owner_norm or not community_norm:
            return

        # Check if this root post is new for this user in this community
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
                    INSERT INTO user_community_stats (owner, community, vote_count, net_votes, unique_root_posts, post_count)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (owner, community) DO UPDATE SET
                        vote_count = user_community_stats.vote_count + %s,
                        net_votes = user_community_stats.net_votes + %s,
                        unique_root_posts = user_community_stats.unique_root_posts + %s,
                        post_count = user_community_stats.post_count + %s
                    """,
                    (
                        owner_norm,
                        community_norm,
                        vote_increment,
                        net_votes_delta,
                        root_increment,
                        post_increment,
                        vote_increment,
                        net_votes_delta,
                        root_increment,
                        post_increment,
                    ),
                )

    # Canonical definition of a (owner, community) stats row, shared by the live
    # re-attribution below and indexer/migrations/v1_33_0_rebuild_derived_stats.
    # Both must agree with tests indexer_hardening.net_votes_matches_canonical_votes.
    #
    # A deleted post grants its author no standing: post_count excludes deleted rows,
    # and so does the author's own vote on them (the post-time auto-upvote). Without
    # that, posting and deleting in a loop is a free way to manufacture the community
    # standing that gates downvote weight, leaving no visible content behind.
    # Votes cast by OTHER users on a post that was later deleted are deliberately
    # kept: they were earned by participating, and retracting them would let an
    # author strip a voter's standing by deleting their own content.
    # The first `%s` is a restrict flag: false rebuilds every community, true
    # limits both INSERTs to the owner/community arrays that follow.
    _VOTE_STATS_FROM_CANONICAL = """
        INSERT INTO user_community_stats (owner, community, vote_count, net_votes, unique_root_posts, post_count)
        SELECT
            LOWER(v.owner),
            LOWER(COALESCE(NULLIF(p.root_community, ''), p.community)),
            COUNT(*) FILTER (WHERE v.user_vote <> 0),
            COALESCE(SUM(CASE
                WHEN v.user_vote > 0 THEN 1
                WHEN v.user_vote < 0 THEN -1
                ELSE 0
            END), 0)::int,
            COUNT(DISTINCT LOWER(COALESCE(NULLIF(p.root_post_id, ''), p.txhash)))
                FILTER (WHERE v.user_vote <> 0),
            0
        FROM votes v
        JOIN posts p ON LOWER(p.txhash) = LOWER(v.target)
        WHERE NOT (COALESCE(p.deleted, FALSE) AND LOWER(v.owner) = LOWER(p.owner))
          AND COALESCE(NULLIF(p.root_community, ''), p.community) <> ''
          AND (
            NOT %s
            OR (
              LOWER(v.owner) = ANY(%s::text[])
              AND LOWER(COALESCE(NULLIF(p.root_community, ''), p.community)) = ANY(%s::text[])
            )
          )
        GROUP BY 1, 2
    """

    _POST_STATS_FROM_CANONICAL = """
        INSERT INTO user_community_stats (owner, community, vote_count, net_votes, unique_root_posts, post_count)
        SELECT
            LOWER(p.owner),
            LOWER(COALESCE(NULLIF(p.root_community, ''), p.community)),
            0, 0, 0,
            COUNT(*)::int
        FROM posts p
        WHERE COALESCE(p.deleted, FALSE) = FALSE
          AND COALESCE(NULLIF(p.root_community, ''), p.community) <> ''
          AND (
            NOT %s
            OR (
              LOWER(p.owner) = ANY(%s::text[])
              AND LOWER(COALESCE(NULLIF(p.root_community, ''), p.community)) = ANY(%s::text[])
            )
          )
        GROUP BY 1, 2
        ON CONFLICT (owner, community) DO UPDATE SET
            post_count = EXCLUDED.post_count
    """

    def _recompute_community_stats(self, cur, owners: list[str], communities: list[str]) -> None:
        """Rebuild user_community_stats for these (owner, community) pairs from the canonical rows.

        Used by every mutation that invalidates an already-applied delta — a community
        edit, or a delete — so the result is identical to a full rebuild instead of
        depending on a guessed reversal.
        """
        if not owners or not communities:
            return
        cur.execute(
            "DELETE FROM user_community_stats WHERE owner = ANY(%s) AND community = ANY(%s)",
            (owners, communities),
        )
        cur.execute(self._VOTE_STATS_FROM_CANONICAL, (True, owners, communities))
        cur.execute(self._POST_STATS_FROM_CANONICAL, (True, owners, communities))

    def _rebuild_all_community_stats(self, cur) -> None:
        """Wipe user_community_stats and rebuild every row from votes and posts."""
        cur.execute("DELETE FROM user_community_stats")
        cur.execute(self._VOTE_STATS_FROM_CANONICAL, (False, [], []))
        cur.execute(self._POST_STATS_FROM_CANONICAL, (False, [], []))

    def reattribute_community_stats(self, root_post_id: str, old_community: str, new_community: str) -> int:
        """Move a thread's vote/post standing after its root community changed.

        `user_community_stats` is maintained by deltas, but its meaning is defined by
        the community the post row carries *now*. An edit that changes a root post's
        community therefore silently invalidates every delta already applied under the
        old community — including the author's post-time auto-upvote — and the drift
        is permanent because nothing revisits it. Descendant comments denormalise
        `root_community` at creation, so they have to follow the root as well or the
        thread ends up split across two communities.

        Both affected communities are recomputed from the canonical tables rather than
        patched by a guessed delta, so the result is identical to a full rebuild
        no matter how many votes or edits came before. Returns the number of rows
        rewritten.
        """
        root_norm = str(root_post_id or "").strip().lower()
        old_norm = str(old_community or "").strip().lower()
        new_norm = str(new_community or "").strip().lower()
        if not root_norm or not new_norm or old_norm == new_norm:
            return 0

        communities = [t for t in (old_norm, new_norm) if t]
        with self._connect() as conn:
            with conn.cursor() as cur:
                # The root and every descendant share root_post_id, so the whole
                # thread follows the root in one statement.
                cur.execute(
                    "UPDATE posts SET community = %s, root_community = %s WHERE LOWER(root_post_id) = %s",
                    (new_norm, new_norm, root_norm),
                )
                threads_moved = cur.rowcount

                cur.execute(
                    """
                    SELECT LOWER(owner) FROM posts WHERE LOWER(root_post_id) = %s
                    UNION
                    SELECT LOWER(v.owner)
                    FROM votes v
                    JOIN posts p ON LOWER(p.txhash) = LOWER(v.target)
                    WHERE LOWER(p.root_post_id) = %s
                    """,
                    (root_norm, root_norm),
                )
                owners = [row[0] for row in cur.fetchall() if row[0]]
                if not owners:
                    return threads_moved

                self._recompute_community_stats(cur, owners, communities)

        logger.info(
            "user_community_stats reattributed root=%s %s->%s posts_moved=%d owners=%d",
            root_norm[:12],
            old_norm or "(none)",
            new_norm,
            threads_moved,
            len(owners),
        )
        return threads_moved

    def update_preference(self, owner: str, pref_type: str, target: str, delta: float, updated_at: int) -> None:
        """
        Update per-user preference (community or author) using exponential decay.

        pref_type: 'community' or 'author'
        target: community name or author address

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
        reserve_funds: int = 0,
        effective_paid: bool = False,
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
                                         auto_renew, biography, avatar, banner, flair, updated_at,
                                         reserve_funds, effective_paid)
                    VALUES(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                      reserve_funds=EXCLUDED.reserve_funds,
                      effective_paid=EXCLUDED.effective_paid
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
                        int(reserve_funds),
                        bool(effective_paid),
                    ),
                )

    def upsert_profiles_batch(self, profiles: list[tuple], updated_at: int) -> None:
        """Batch upsert profiles in a single connection.

        Each tuple: (owner, username, level, created_at, subscription_expiry,
                      auto_renew, biography, avatar, banner, flair, reserve_funds,
                      effective_paid)
        """
        if not profiles:
            return
        rows = []
        for p in profiles:
            (
                owner,
                username,
                level,
                created_at,
                sub_exp,
                auto_renew,
                bio,
                avatar,
                banner,
                flair,
                reserve_funds,
                effective_paid,
            ) = p
            rows.append(
                (
                    owner,
                    self._strip_nul(username),
                    int(level),
                    int(created_at),
                    int(sub_exp),
                    bool(auto_renew),
                    self._strip_nul(bio) or "",
                    self._strip_nul(avatar) or "",
                    self._strip_nul(banner) or "",
                    self._strip_nul(flair) or "",
                    int(updated_at),
                    int(reserve_funds),
                    bool(effective_paid),
                )
            )
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.executemany(
                    """
                    INSERT INTO profiles(owner, username, level, created_at, subscription_expiry,
                                         auto_renew, biography, avatar, banner, flair, updated_at,
                                         reserve_funds, effective_paid)
                    VALUES(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                      reserve_funds=EXCLUDED.reserve_funds,
                      effective_paid=EXCLUDED.effective_paid
                    """,
                    rows,
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

    def set_joined_communities(self, owner: str, communities: list[str]) -> None:
        """Reconcile membership without overwriting stored curation choices."""
        owner_norm = str(owner or "").strip().lower()
        normalized = sorted(
            {
                str(community or "").strip().lower()
                for community in communities
                if str(community or "").strip()
            }
        )
        with self._connect() as conn:
            with conn.cursor() as cur:
                if normalized:
                    cur.execute(
                        """
                        DELETE FROM community_curation_preferences
                        WHERE LOWER(owner) = %s
                          AND NOT (LOWER(community) = ANY(%s))
                        """,
                        (owner_norm, normalized),
                    )
                    cur.executemany(
                        """
                        INSERT INTO community_curation_preferences(
                            owner, community, mode, pinned_team_id, updated_height
                        ) VALUES(%s, %s, 0, NULL, 0)
                        ON CONFLICT(owner, community) DO NOTHING
                        """,
                        [(owner_norm, community) for community in normalized],
                    )
                else:
                    cur.execute(
                        "DELETE FROM community_curation_preferences WHERE LOWER(owner) = %s",
                        (owner_norm,),
                    )
        logger.debug(
            "[curation] reconciled joined communities owner=%s authoritative_count=%d",
            owner_norm,
            len(normalized),
        )

    def upsert_community_preference(
        self,
        owner: str,
        community: str,
        mode: int,
        pinned_team_id: int | None,
        updated_height: int,
    ) -> None:
        """Store one authoritative chain preference without losing its mode."""
        mode_value = int(mode)
        team_value = int(pinned_team_id or 0)
        if mode_value not in (0, 1, 2) or (mode_value == 1) != (team_value > 0):
            raise RuntimeError(
                f"invalid community preference owner={owner} community={community} "
                f"mode={mode_value} team={team_value}"
            )
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO community_curation_preferences(
                        owner, community, mode, pinned_team_id, updated_height
                    ) VALUES(%s,%s,%s,NULLIF(%s,0),%s)
                    ON CONFLICT(owner, community) DO UPDATE SET
                        mode=EXCLUDED.mode,
                        pinned_team_id=EXCLUDED.pinned_team_id,
                        updated_height=GREATEST(
                            community_curation_preferences.updated_height,
                            EXCLUDED.updated_height
                        )
                    """,
                    (
                        str(owner).strip().lower(),
                        str(community).strip().lower(),
                        mode_value,
                        team_value,
                        int(updated_height),
                    ),
                )

    def upsert_subscription_tranches(self, tranches: list[dict]) -> None:
        """Project authoritative tranche records idempotently."""
        if not tranches:
            return
        rows = [
            (
                int(value["tranche_id"]),
                str(value["payer"]).strip().lower(),
                str(value["recipient"]).strip().lower(),
                int(value["source"]),
                int(value["period_count"]),
                int(value["start_time"]),
                int(value["end_time"]),
                str(value["total_fee"]),
                str(value["burn_amount"]),
                str(value["creator_amount"]),
                int(value["creator_bps"]),
                int(value["created_height"]),
                value["tx_hash"],
            )
            for value in tranches
        ]
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.executemany(
                    """
                    INSERT INTO subscription_tranches(
                        tranche_id, payer, recipient, source, period_count,
                        start_time, end_time, total_fee, burn_amount, creator_amount,
                        creator_bps, created_height, tx_hash
                    ) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT(tranche_id) DO UPDATE SET
                        payer=EXCLUDED.payer,
                        recipient=EXCLUDED.recipient,
                        source=EXCLUDED.source,
                        period_count=EXCLUDED.period_count,
                        start_time=EXCLUDED.start_time,
                        end_time=EXCLUDED.end_time,
                        total_fee=EXCLUDED.total_fee,
                        burn_amount=EXCLUDED.burn_amount,
                        creator_amount=EXCLUDED.creator_amount,
                        creator_bps=EXCLUDED.creator_bps,
                        created_height=EXCLUDED.created_height,
                        tx_hash=EXCLUDED.tx_hash
                    """,
                    rows,
                )
        logger.debug("[subscription] upserted authoritative tranches count=%d", len(rows))

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

    def join_community(self, owner: str, community: str) -> None:
        """Join a community (LIVE_DEFAULT). Historical MsgFollowTopic writes here on reindex."""
        community = self._strip_nul(community) or ""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO community_curation_preferences(owner, community, mode, pinned_team_id, updated_height)
                    VALUES(%s, %s, 0, NULL, 0)
                    ON CONFLICT(owner, community) DO NOTHING
                    """,
                    (owner, community),
                )

    def leave_community(self, owner: str, community: str) -> None:
        """Leave a community."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM community_curation_preferences WHERE LOWER(owner) = LOWER(%s) AND LOWER(community) = LOWER(%s)",
                    (owner, community),
                )

    def leave_communities_matching(self, owner: str, community_pattern: str) -> int:
        """Leave communities matching a glob pattern (* maps to SQL %)."""
        pattern = str(community_pattern or "").strip().lower()
        if not pattern:
            raise ValueError("community pattern cannot be empty")
        with self._connect() as conn:
            with conn.cursor() as cur:
                if "*" in pattern:
                    like_pat = pattern.replace("%", "\\%").replace("_", "\\_").replace("*", "%")
                    cur.execute(
                        "DELETE FROM community_curation_preferences WHERE LOWER(owner) = LOWER(%s) AND LOWER(community) LIKE %s",
                        (owner, like_pat),
                    )
                else:
                    cur.execute(
                        "DELETE FROM community_curation_preferences WHERE LOWER(owner) = LOWER(%s) AND LOWER(community) = LOWER(%s)",
                        (owner, pattern),
                    )
                return int(cur.rowcount or 0)

    def block_post(self, owner: str, target: str, blocked_at: int = 0) -> None:
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
                    INSERT INTO blocked_posts(owner, target, position, blocked_at)
                    VALUES(%s, %s, %s, %s)
                    ON CONFLICT(owner, target) DO NOTHING
                    """,
                    (owner, target, pos, int(blocked_at)),
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

    def block_user(self, owner: str, target: str, blocked_at: int = 0) -> None:
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
                    INSERT INTO blocked_users(owner, target, position, blocked_at)
                    VALUES(%s, %s, %s, %s)
                    ON CONFLICT(owner, target) DO NOTHING
                    """,
                    (owner, target, pos, int(blocked_at)),
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

    def block_community(self, owner: str, target: str, blocked_at: int = 0) -> None:
        """Block a community (add to blocked_communities with next position, evict oldest beyond cap)."""
        target = self._strip_nul(target) or ""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COALESCE(MAX(position), -1) + 1 FROM blocked_communities WHERE LOWER(owner) = LOWER(%s)",
                    (owner,),
                )
                pos = cur.fetchone()[0]
                cur.execute(
                    """
                    INSERT INTO blocked_communities(owner, target, position, blocked_at)
                    VALUES(%s, %s, %s, %s)
                    ON CONFLICT(owner, target) DO NOTHING
                    """,
                    (owner, target, pos, int(blocked_at)),
                )
                self._evict_oldest(cur, "blocked_communities", "target", owner)

    def unblock_community(self, owner: str, target: str) -> None:
        """Unblock a community (remove from blocked_communities)."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM blocked_communities WHERE LOWER(owner) = LOWER(%s) AND LOWER(target) = LOWER(%s)",
                    (owner, target),
                )

    def unblock_communities_matching(self, owner: str, community: str) -> int:
        """Unblock communities whose pattern matches the community."""
        t = str(community or "").strip().lower()
        if not t:
            raise ValueError("community cannot be empty")
        with self._connect() as conn:
            with conn.cursor() as cur:
                # `target` is stored user content, so a literal % or _ in it would act
                # as a SQL wildcard and clear more blocks than the pattern names. Only
                # `*` is meant to be a wildcard. The pattern lives in a column rather
                # than a parameter, so the escaping has to happen in SQL: neutralise
                # %, _ and the escape character itself, then translate the glob.
                cur.execute(
                    """
                    DELETE FROM blocked_communities
                    WHERE LOWER(owner) = LOWER(%s)
                      AND LOWER(%s) LIKE LOWER(
                          REPLACE(REPLACE(REPLACE(REPLACE(target, '#', '##'), '%%', '#%%'), '_', '#_'), '*', '%%')
                      ) ESCAPE '#'
                    """,
                    (owner, t),
                )
                return int(cur.rowcount or 0)

    def delete_post(self, target: str, owner: str | None = None) -> int:
        """Delete a post and cascade to all descendants.

        When a comment is deleted, its entire subtree becomes orphaned
        (unreachable via the recursive parent->child walk used in the
        comment-tree endpoint).  To keep the flat root_post_id-based
        counts in the feed consistent, we soft-delete descendants too.
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
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

                _RETURN_STANDING = " RETURNING LOWER(owner), LOWER(COALESCE(NULLIF(root_community, ''), community))"
                if owner is None:
                    cur.execute(
                        "UPDATE posts SET deleted = TRUE WHERE txhash = %s AND deleted = FALSE" + _RETURN_STANDING,
                        (target,),
                    )
                else:
                    cur.execute(
                        "UPDATE posts SET deleted = TRUE WHERE txhash = %s AND LOWER(owner) = LOWER(%s) "
                        "AND deleted = FALSE" + _RETURN_STANDING,
                        (target, owner),
                    )
                affected = [(r[0], r[1]) for r in cur.fetchall() if r[0] and r[1]]
                deleted_count = len(affected)

                if deleted_count > 0:
                    # Cascade soft-delete to all descendants so orphaned
                    # children don't inflate the flat comment count in feeds.
                    cur.execute(
                        """
                        WITH RECURSIVE descendants(tx) AS (
                            SELECT txhash FROM posts
                            WHERE LOWER(target) = LOWER(%s) AND deleted = FALSE
                            UNION ALL
                            SELECT p.txhash FROM posts p
                            JOIN descendants d ON LOWER(p.target) = LOWER(d.tx)
                            WHERE p.deleted = FALSE
                        )
                        UPDATE posts SET deleted = TRUE
                        WHERE txhash IN (SELECT tx FROM descendants)
                          AND deleted = FALSE
                        RETURNING LOWER(owner), LOWER(COALESCE(NULLIF(root_community, ''), community))
                        """,
                        (target,),
                    )
                    affected.extend((r[0], r[1]) for r in cur.fetchall() if r[0] and r[1])

                    if parent_id:
                        self._update_ancestor_comment_counts(cur, parent_id, delta=-(1 + subtree_count))

                    # A deleted post grants no standing to its author, so every
                    # (owner, community) it contributed to has to be recomputed rather
                    # than left carrying the delta applied when it was indexed.
                    owners = sorted({o for o, _ in affected})
                    communities = sorted({t for _, t in affected})
                    self._recompute_community_stats(cur, owners, communities)
                    logger.debug(
                        "user_community_stats recomputed after delete target=%s owners=%d communities=%d",
                        str(target)[:12],
                        len(owners),
                        len(communities),
                    )
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
        # Walk up the chain and update the post and its ancestors. Bounded like the
        # root walk in get_root_community_for_post: this runs one UPDATE per level inside
        # the block transaction, so an unbounded chain makes indexing cost grow with
        # thread depth on every new comment.
        visited = set()
        current = post_id
        depth = 0
        while current and current not in visited and depth < MAX_ANCESTOR_WALK_DEPTH:
            visited.add(current)
            depth += 1
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

    # TODO: backend-owned tables removed — see web/backend/db.py init_backend_schema()

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

    def upsert_supply(
        self,
        height: int,
        total_supply: int,
        created_at: int,
        node_balance: int | None = None,
        node_staked: int | None = None,
        node_minted_total: int | None = None,
        node_fees_total: int | None = None,
    ) -> None:
        """Record total supply, validator liquid/staked balances and earnings counters."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO supply_history(
                        height, total_supply, created_at, node_balance, node_staked,
                        node_minted_total, node_fees_total
                    )
                    VALUES(%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (height) DO UPDATE SET
                        total_supply = EXCLUDED.total_supply,
                        created_at = EXCLUDED.created_at,
                        node_balance = COALESCE(EXCLUDED.node_balance, supply_history.node_balance),
                        node_staked = COALESCE(EXCLUDED.node_staked, supply_history.node_staked),
                        node_minted_total = COALESCE(
                            EXCLUDED.node_minted_total, supply_history.node_minted_total
                        ),
                        node_fees_total = COALESCE(EXCLUDED.node_fees_total, supply_history.node_fees_total)
                    """,
                    (
                        int(height),
                        int(total_supply),
                        int(created_at),
                        node_balance,
                        node_staked,
                        node_minted_total,
                        node_fees_total,
                    ),
                )

    def get_supply_history(self, since_ts: int) -> list[dict]:
        """Get supply history since a timestamp."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT height, total_supply, created_at, node_balance, node_staked,
                           node_minted_total, node_fees_total
                    FROM supply_history
                    WHERE created_at >= %s
                    ORDER BY height ASC
                    """,
                    (int(since_ts),),
                )
                rows = cur.fetchall()
                return [
                    {
                        "height": r[0],
                        "total_supply": r[1],
                        "timestamp": r[2],
                        "node_balance": r[3],
                        "node_staked": r[4],
                        "node_minted_total": r[5],
                        "node_fees_total": r[6],
                    }
                    for r in rows
                ]

    # ========== Balance Methods ==========

    def upsert_balance(self, address: str, balance: int, updated_at: int) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO balances(address, balance, updated_at)
                    VALUES(LOWER(%s), %s, %s)
                    ON CONFLICT(address) DO UPDATE SET
                      balance=EXCLUDED.balance,
                      updated_at=EXCLUDED.updated_at
                    """,
                    (address.lower(), int(balance), int(updated_at)),
                )

    def upsert_balances_batch(self, entries: list[tuple[str, int]], updated_at: int) -> None:
        """Batch upsert balances. entries = [(address, balance), ...]"""
        if not entries:
            return
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.executemany(
                    """
                    INSERT INTO balances(address, balance, updated_at)
                    VALUES(LOWER(%s), %s, %s)
                    ON CONFLICT(address) DO UPDATE SET
                      balance=EXCLUDED.balance,
                      updated_at=EXCLUDED.updated_at
                    """,
                    [(addr.lower(), int(bal), int(updated_at)) for addr, bal in entries],
                )

    def get_balance(self, address: str) -> int:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT balance FROM balances WHERE address = LOWER(%s)", (address,))
                row = cur.fetchone()
                return int(row[0]) if row and row[0] is not None else 0

    def get_balances_batch(self, addresses: list[str]) -> list[tuple[str, int]]:
        if not addresses:
            return []
        with self._connect() as conn:
            with conn.cursor() as cur:
                lower = [a.lower() for a in addresses]
                cur.execute("SELECT address, balance FROM balances WHERE address = ANY(%s)", (lower,))
                found = {r[0]: int(r[1]) for r in cur.fetchall()}
                return [(a, found.get(a.lower(), 0)) for a in addresses]

    # ========== Chain Stats Methods ==========

    def set_chain_stat(self, key: str, value, updated_at: int) -> None:
        import json as _json

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO chain_stats(key, value, updated_at)
                    VALUES(%s, %s::jsonb, %s)
                    ON CONFLICT(key) DO UPDATE SET
                      value=EXCLUDED.value,
                      updated_at=EXCLUDED.updated_at
                    """,
                    (key, _json.dumps(value), int(updated_at)),
                )

    def get_chain_stat(self, key: str):
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT value FROM chain_stats WHERE key = %s", (key,))
                row = cur.fetchone()
                return row[0] if row else None

    # ========== Recent Blocks Methods ==========

    def upsert_recent_block(self, height: int, block_hash: str, block_time: int) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO recent_blocks(height, hash, block_time)
                    VALUES(%s, %s, %s)
                    ON CONFLICT(height) DO UPDATE SET
                      hash=EXCLUDED.hash,
                      block_time=EXCLUDED.block_time
                    """,
                    (int(height), block_hash, int(block_time)),
                )

    def prune_old_blocks(self, keep: int = 1000) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM recent_blocks WHERE height < (SELECT COALESCE(MAX(height), 0) - %s FROM recent_blocks)",
                    (keep,),
                )

    def get_recent_block_hashes(self, limit: int = 100) -> list[dict]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT height, hash, block_time FROM recent_blocks ORDER BY height DESC LIMIT %s",
                    (limit,),
                )
                return [{"height": r[0], "hash": r[1], "block_time": r[2]} for r in cur.fetchall()]

    # ========== Indexer State Methods ==========

    def set_indexer_state(self, key: str, value: str, updated_at: int) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO indexer_state(key, value, updated_at)
                    VALUES(%s, %s, %s)
                    ON CONFLICT(key) DO UPDATE SET
                      value=EXCLUDED.value,
                      updated_at=EXCLUDED.updated_at
                    """,
                    (key, str(value), int(updated_at)),
                )

    def get_indexer_state(self, key: str) -> str | None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT value FROM indexer_state WHERE key = %s", (key,))
                row = cur.fetchone()
                return row[0] if row else None
