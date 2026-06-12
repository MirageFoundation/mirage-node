import os
from pathlib import Path

from deploy.migrations._helpers import backup_file, parse_env_file, update_env_value

MIGRATION_KEY = "v1.25.0-enable-trending-push"
DESCRIPTION = "Enable push notifications and reset trending push cooldowns"


def run(config_dir, logger):
    config_dir = Path(config_dir)
    indexer_env = config_dir / "indexer.env"

    if not indexer_env.exists():
        raise FileNotFoundError(f"indexer.env not found: {indexer_env}")

    backup_file(indexer_env)

    values = parse_env_file(indexer_env)
    changed = []

    for key in ("PUSH_NOTIFICATIONS_ENABLED", "TRENDING_PUSH_ENABLED"):
        current = values.get(key)
        if current is None:
            raise RuntimeError(f"{key} missing from indexer.env")
        if current == "true":
            logger.info(f"  {key} already true, leaving as-is")
            continue
        if not update_env_value(indexer_env, key, "true"):
            raise RuntimeError(f"Failed to update {key} in indexer.env")
        logger.info(f"  Updated {key}: {current!r} -> 'true'")
        changed.append(key)

    backend_url = os.environ.get("BACKEND_DB_URL", "").strip()
    if not backend_url:
        raise RuntimeError("BACKEND_DB_URL must be set")

    import psycopg

    with psycopg.connect(backend_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE user_inbox_state
                SET trending_last_sent_at = 0
                WHERE COALESCE(trending_last_sent_at, 0) <> 0
                """
            )
            reset_count = cur.rowcount

    logger.info("  Reset trending push cooldown state for %d users", reset_count)

    if changed:
        return f"enabled {', '.join(changed)}; reset trending state for {reset_count} users"
    return f"env already enabled; reset trending state for {reset_count} users"
