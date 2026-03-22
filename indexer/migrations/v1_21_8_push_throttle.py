"""
Replace push_budget (3-send budget reset on mark_inbox_viewed) with push_throttle
(5-per-30-minute sliding window with suppressed-event tracking for summary pushes).
"""

MIGRATION_KEY = "v1.21.8_push_throttle"


def run(db, chain, logger):
    with db._connect() as conn:
        with conn.cursor() as cur:
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
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_push_throttle_summary_due "
                "ON push_throttle (cooldown_until, window_start) WHERE suppressed_count > 0"
            )

    return "created push_throttle table"
