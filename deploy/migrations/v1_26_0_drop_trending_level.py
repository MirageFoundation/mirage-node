import os

MIGRATION_KEY = "v1.26.0-drop-trending-level"
DESCRIPTION = "Remove deprecated trending_level column from user_inbox_state"


def run(config_dir, logger):
    import psycopg

    backend_url = os.environ.get("BACKEND_DB_URL", "").strip()
    if not backend_url:
        raise RuntimeError("BACKEND_DB_URL must be set")

    with psycopg.connect(backend_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = 'user_inbox_state'
                """
            )
            if cur.fetchone() is None:
                raise RuntimeError("user_inbox_state table is missing")

            cur.execute(
                """
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'user_inbox_state'
                  AND column_name = 'trending_level'
                """
            )
            if cur.fetchone() is None:
                logger.info("  user_inbox_state.trending_level already absent")
                return "user_inbox_state.trending_level already absent"

            cur.execute("ALTER TABLE user_inbox_state DROP COLUMN trending_level")

    logger.info("  dropped user_inbox_state.trending_level")
    return "dropped user_inbox_state.trending_level"
