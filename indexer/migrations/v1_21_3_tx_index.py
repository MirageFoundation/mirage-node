"""
Replace tx_receipts with tx_index — universal tx tracking for all types (success + failure).

tx_index stores every on-chain tx hash with its type, result code, and raw_log.
get_tx_status uses this as the fallback after rich post/vote detail lookups.
"""

MIGRATION_KEY = "v1.21.3_tx_index"


def run(db, chain, logger):
    with db._connect() as conn:
        with conn.cursor() as cur:
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

            cur.execute("DROP TABLE IF EXISTS tx_receipts")

    return "created tx_index, dropped tx_receipts"
