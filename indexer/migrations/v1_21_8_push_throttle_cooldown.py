"""
Add cooldown_until column to push_throttle for summary cooldown.
"""

MIGRATION_KEY = "v1.21.8_push_throttle_cooldown"


def run(db, chain, logger):
    with db._connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "ALTER TABLE push_throttle " "ADD COLUMN IF NOT EXISTS cooldown_until BIGINT NOT NULL DEFAULT 0"
            )
            cur.execute("DROP INDEX IF EXISTS idx_push_throttle_summary_due")
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_push_throttle_summary_due "
                "ON push_throttle (cooldown_until, window_start) WHERE suppressed_count > 0"
            )

    return "added cooldown_until to push_throttle and refreshed summary index"
