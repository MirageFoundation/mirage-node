from __future__ import annotations

"""
PostgreSQL connection helpers for the Mirage backend.

Two databases:
- Indexer DB (read-only): chain-indexed state (posts, votes, profiles, etc.)
- Backend DB (read-write): operational tables (quests, invites, referrals,
  stats, reports, push, similarity, inbox state)
"""

import logging
import psycopg
from typing import Any, Dict

from shared.config import get_config

logger = logging.getLogger(__name__)


def connect_db(timeout: float = 10.0, busy_timeout_ms: int = 15000) -> psycopg.Connection:
    """
    Open a READ-ONLY connection to the indexer PostgreSQL database.
    timeout and busy_timeout_ms are ignored for PostgreSQL and kept for API compatibility.
    """
    cfg = get_config()
    url = cfg.get_indexer_ro_url()
    return psycopg.connect(url, autocommit=True)


def connect_backend_db() -> psycopg.Connection:
    """Open a read-write connection to the backend-owned PostgreSQL database."""
    cfg = get_config()
    url = cfg.get_backend_db_url()
    return psycopg.connect(url, autocommit=True)


def init_backend_schema() -> None:
    """Create all backend-owned tables (idempotent). Called at backend startup."""
    conn = connect_backend_db()
    try:
        logger.debug("backend.schema.init.begin")
        with conn.cursor() as cur:

            def _assert_table_schema(
                table: str,
                expected_cols: set[str],
                expected_types: Dict[str, str] | None = None,
            ) -> None:
                cur.execute(
                    """
                    SELECT column_name, data_type
                    FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = %s
                    """,
                    (table,),
                )
                rows = cur.fetchall()
                if not rows:
                    raise RuntimeError(f"{table} schema mismatch: table missing")
                cols = {row[0]: row[1] for row in rows}
                missing = expected_cols - cols.keys()
                extra = cols.keys() - expected_cols
                if missing or extra:
                    raise RuntimeError(f"{table} schema mismatch: missing={sorted(missing)} extra={sorted(extra)}")
                if expected_types:
                    bad = {col: cols.get(col) for col, dtype in expected_types.items() if cols.get(col) != dtype}
                    if bad:
                        raise RuntimeError(f"{table} schema mismatch: types={bad}")

            # ── Invite codes ─────────────────────────────────────────────
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS invite_codes (
                    code VARCHAR(9) PRIMARY KEY,
                    owner VARCHAR(64) NOT NULL,
                    used_by VARCHAR(64),
                    created_at BIGINT NOT NULL,
                    used_at BIGINT
                )
            """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_invite_codes_owner ON invite_codes(LOWER(owner))")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_invite_codes_used_by ON invite_codes(LOWER(used_by))")

            # ── Referral system ──────────────────────────────────────────
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS referral_links (
                    user_address VARCHAR(64) PRIMARY KEY,
                    referrer_address VARCHAR(64) NOT NULL,
                    referred_at BIGINT NOT NULL,
                    created_at BIGINT DEFAULT EXTRACT(EPOCH FROM NOW()),
                    client_hash TEXT
                )
            """
            )
            cur.execute("ALTER TABLE referral_links ADD COLUMN IF NOT EXISTS client_hash TEXT")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_referral_links_referrer ON referral_links(referrer_address)")
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_referral_links_client_hash ON referral_links(client_hash) WHERE client_hash IS NOT NULL"
            )

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
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_referral_user_accruals_beneficiary ON referral_user_accruals(beneficiary_address)"
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS referral_state (
                    key VARCHAR(64) PRIMARY KEY,
                    value BIGINT NOT NULL,
                    updated_at BIGINT DEFAULT EXTRACT(EPOCH FROM NOW())
                )
            """
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS referral_user_settings (
                    owner TEXT PRIMARY KEY,
                    precheck_enabled BOOLEAN NOT NULL DEFAULT FALSE,
                    updated_at BIGINT NOT NULL,
                    CONSTRAINT referral_user_settings_owner_lower CHECK (owner = LOWER(owner))
                )
            """
            )
            _assert_table_schema(
                "referral_user_settings",
                {"owner", "precheck_enabled", "updated_at"},
            )

            # ── Reports ──────────────────────────────────────────────────
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

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS user_last_seen (
                    owner TEXT PRIMARY KEY,
                    last_seen_at BIGINT NOT NULL,
                    CONSTRAINT user_last_seen_owner_lower CHECK (owner = LOWER(owner))
                )
            """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_user_last_seen_seen_at ON user_last_seen(last_seen_at DESC)")
            _assert_table_schema("user_last_seen", {"owner", "last_seen_at"})

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS push_event_seen (
                    event_key TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    created_at BIGINT NOT NULL
                )
            """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_push_event_seen_type ON push_event_seen(event_type)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_push_event_seen_created_at ON push_event_seen(created_at DESC)")
            _assert_table_schema("push_event_seen", {"event_key", "event_type", "created_at"})

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS push_event_cursor (
                    event_type TEXT PRIMARY KEY,
                    last_created_at BIGINT NOT NULL,
                    last_id TEXT NOT NULL,
                    updated_at BIGINT NOT NULL
                )
            """
            )
            _assert_table_schema("push_event_cursor", {"event_type", "last_created_at", "last_id", "updated_at"})

            # ── User similarity cache ────────────────────────────────────
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS user_similarity_cache (
                    owner TEXT NOT NULL,
                    similar_user TEXT NOT NULL,
                    similarity DOUBLE PRECISION NOT NULL,
                    shared_dims INT NOT NULL DEFAULT 0,
                    computed_at BIGINT NOT NULL,
                    expires_at BIGINT NOT NULL,
                    PRIMARY KEY (owner, similar_user)
                )
            """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_similarity_owner_expires ON user_similarity_cache(LOWER(owner), expires_at)"
            )

            # ── Push notifications ───────────────────────────────────────
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS push_tokens (
                    id SERIAL PRIMARY KEY,
                    owner TEXT NOT NULL,
                    token TEXT NOT NULL UNIQUE,
                    platform TEXT NOT NULL,
                    created_at BIGINT NOT NULL,
                    last_used_at BIGINT NOT NULL
                )
            """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_push_tokens_owner_lower ON push_tokens(LOWER(owner))")

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS push_budget (
                    owner TEXT PRIMARY KEY,
                    remaining INT NOT NULL DEFAULT 3,
                    last_reset_at BIGINT NOT NULL DEFAULT 0,
                    CONSTRAINT push_budget_owner_lower CHECK (owner = LOWER(owner))
                )
            """
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS push_throttle (
                    owner TEXT PRIMARY KEY,
                    window_start BIGINT NOT NULL DEFAULT 0,
                    sent_count INT NOT NULL DEFAULT 0,
                    suppressed_count INT NOT NULL DEFAULT 0,
                    cooldown_until BIGINT NOT NULL DEFAULT 0,
                    CONSTRAINT push_throttle_owner_lower CHECK (owner = LOWER(owner))
                )
            """
            )
            _assert_table_schema(
                "push_throttle",
                {"owner", "window_start", "sent_count", "suppressed_count", "cooldown_until"},
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_push_throttle_summary_due "
                "ON push_throttle (cooldown_until, window_start) WHERE suppressed_count > 0"
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS push_receipts (
                    id SERIAL PRIMARY KEY,
                    ticket_id TEXT NOT NULL UNIQUE,
                    token TEXT NOT NULL,
                    created_at BIGINT NOT NULL
                )
            """
            )
            _assert_table_schema("push_receipts", {"id", "ticket_id", "token", "created_at"})
            cur.execute("CREATE INDEX IF NOT EXISTS idx_push_receipts_created_at ON push_receipts(created_at)")

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS push_nonces (
                    id SERIAL PRIMARY KEY,
                    owner TEXT NOT NULL,
                    action TEXT NOT NULL,
                    nonce BIGINT NOT NULL,
                    created_at BIGINT NOT NULL,
                    CONSTRAINT push_nonces_owner_lower CHECK (owner = LOWER(owner)),
                    UNIQUE(owner, action, nonce)
                )
            """
            )
            _assert_table_schema(
                "push_nonces",
                {"id", "owner", "action", "nonce", "created_at"},
                {"nonce": "bigint"},
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_push_nonces_owner_lower ON push_nonces(LOWER(owner))")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_push_nonces_created_at ON push_nonces(created_at)")

            # ── Quest / reward system ────────────────────────────────────
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS user_daily_quests (
                    owner TEXT NOT NULL,
                    day_utc INTEGER NOT NULL,
                    quest_id TEXT NOT NULL,
                    progress INTEGER NOT NULL DEFAULT 0,
                    progress_meta JSONB NOT NULL DEFAULT '{}',
                    last_action_at BIGINT,
                    completed_at BIGINT,
                    PRIMARY KEY (owner, day_utc, quest_id)
                )
            """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_user_daily_quests_owner ON user_daily_quests(LOWER(owner))")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_user_daily_quests_day ON user_daily_quests(day_utc DESC)")
            _assert_table_schema(
                "user_daily_quests",
                {
                    "owner",
                    "day_utc",
                    "quest_id",
                    "progress",
                    "progress_meta",
                    "last_action_at",
                    "completed_at",
                },
                {"progress_meta": "jsonb"},
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS user_flash_quests (
                    owner TEXT NOT NULL,
                    template_id TEXT NOT NULL,
                    starts_at BIGINT NOT NULL,
                    ends_at BIGINT NOT NULL,
                    progress INTEGER NOT NULL DEFAULT 0,
                    progress_meta JSONB NOT NULL DEFAULT '{}',
                    last_action_at BIGINT,
                    completed_at BIGINT,
                    PRIMARY KEY (owner, starts_at)
                )
            """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_user_flash_quests_owner ON user_flash_quests(LOWER(owner))")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_user_flash_quests_ends ON user_flash_quests(ends_at)")
            cur.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_user_flash_quests_owner_start ON user_flash_quests(owner, starts_at)"
            )
            _assert_table_schema(
                "user_flash_quests",
                {
                    "owner",
                    "template_id",
                    "starts_at",
                    "ends_at",
                    "progress",
                    "progress_meta",
                    "last_action_at",
                    "completed_at",
                },
                {"progress_meta": "jsonb"},
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS user_quest_state (
                    owner TEXT PRIMARY KEY,
                    next_flash_at BIGINT NOT NULL DEFAULT 0
                )
            """
            )
            _assert_table_schema("user_quest_state", {"owner", "next_flash_at"})

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS user_achievements (
                    owner TEXT NOT NULL,
                    achievement_id TEXT NOT NULL,
                    unlocked_at BIGINT NOT NULL,
                    progress INTEGER NOT NULL DEFAULT 0,
                    progress_meta JSONB NOT NULL DEFAULT '{}',
                    PRIMARY KEY (owner, achievement_id)
                )
            """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_user_achievements_owner ON user_achievements(LOWER(owner))")
            _assert_table_schema(
                "user_achievements",
                {"owner", "achievement_id", "unlocked_at", "progress", "progress_meta"},
                {"progress_meta": "jsonb"},
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS pending_rewards (
                    id SERIAL PRIMARY KEY,
                    owner TEXT NOT NULL,
                    reward_type TEXT NOT NULL,
                    reward_data JSONB NOT NULL,
                    reason TEXT NOT NULL,
                    created_at BIGINT NOT NULL,
                    claimed_at BIGINT,
                    payout_amount BIGINT
                )
            """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_pending_rewards_owner ON pending_rewards(LOWER(owner))")
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_pending_rewards_unclaimed "
                "ON pending_rewards(owner) WHERE claimed_at IS NULL"
            )
            _assert_table_schema(
                "pending_rewards",
                {
                    "id",
                    "owner",
                    "reward_type",
                    "reward_data",
                    "reason",
                    "created_at",
                    "claimed_at",
                    "payout_amount",
                },
                {"reward_data": "jsonb"},
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS user_unlocks (
                    owner TEXT NOT NULL,
                    unlock_type TEXT NOT NULL,
                    unlock_id TEXT NOT NULL,
                    unlocked_at BIGINT NOT NULL,
                    source TEXT NOT NULL,
                    PRIMARY KEY (owner, unlock_type, unlock_id)
                )
            """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_user_unlocks_owner ON user_unlocks(LOWER(owner))")
            _assert_table_schema(
                "user_unlocks",
                {"owner", "unlock_type", "unlock_id", "unlocked_at", "source"},
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS reward_suspensions (
                    owner TEXT PRIMARY KEY,
                    suspended_until BIGINT NOT NULL,
                    suspended_by TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    updated_at BIGINT NOT NULL
                )
            """
            )
            _assert_table_schema(
                "reward_suspensions",
                {"owner", "suspended_until", "suspended_by", "reason", "updated_at"},
            )

            # ── Inbox state (replaces profiles.inbox_last_viewed_at) ─────
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS user_inbox_state (
                    owner TEXT PRIMARY KEY,
                    inbox_last_viewed_at BIGINT NOT NULL DEFAULT 0
                )
            """
            )

            # ── Fix SERIAL sequences after data migration ─────────────────
            # The DB-split migration inserts rows with explicit id values but
            # doesn't advance the sequences.  Reset each SERIAL sequence to
            # MAX(id) so the next INSERT without an explicit id won't collide.
            _SERIAL_TABLES = [
                ("pending_rewards", "id"),
                ("referral_pending_rewards", "id"),
                ("referral_analysis", "id"),
                ("reports", "id"),
                ("push_tokens", "id"),
                ("push_receipts", "id"),
                ("push_nonces", "id"),
            ]
            for table, col in _SERIAL_TABLES:
                seq_name = f"{table}_{col}_seq"
                cur.execute(
                    f"SELECT setval(pg_get_serial_sequence(%s, %s), GREATEST(COALESCE((SELECT MAX({col}) FROM {table}), 0), 1))",
                    (table, col),
                )
                new_val = cur.fetchone()[0]
                if new_val > 1:
                    logger.info("backend.schema.seq_reset table=%s seq=%s val=%s", table, seq_name, new_val)

        logger.debug("backend.schema.init.ok")
        logger.info("Backend schema initialized successfully")
    finally:
        conn.close()


__all__ = ["connect_db", "connect_backend_db", "init_backend_schema"]
