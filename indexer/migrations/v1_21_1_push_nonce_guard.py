"""
Create push_nonces table for replay protection on push endpoints.
"""

MIGRATION_KEY = "v1.21.1_push_nonce_guard"


def run(db, chain, logger):
    with db._connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS push_nonces (
                    id SERIAL PRIMARY KEY,
                    owner TEXT NOT NULL,
                    action TEXT NOT NULL,
                    nonce BIGINT NOT NULL,
                    created_at BIGINT NOT NULL,
                    UNIQUE(owner, action, nonce)
                )
                """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_push_nonces_owner_lower ON push_nonces(LOWER(owner))")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_push_nonces_created_at ON push_nonces(created_at)")
    return "created push_nonces table"
