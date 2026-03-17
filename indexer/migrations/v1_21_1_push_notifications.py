"""
Create push_tokens, push_budget, and push_receipts tables for Expo push notifications.

push_tokens: stores Expo push tokens per user (multiple devices allowed).
push_budget: per-user notification budget (max 3, resets on mark_inbox_viewed).
push_receipts: Expo ticket IDs for opportunistic receipt checking.
"""

MIGRATION_KEY = "v1.21.1_push_notifications"


def run(db, chain, logger):
    with db._connect() as conn:
        with conn.cursor() as cur:
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
                    last_reset_at BIGINT NOT NULL DEFAULT 0
                )
                """
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
            cur.execute("CREATE INDEX IF NOT EXISTS idx_push_receipts_created_at ON push_receipts(created_at)")

    return "created push_tokens, push_budget, push_receipts tables"
