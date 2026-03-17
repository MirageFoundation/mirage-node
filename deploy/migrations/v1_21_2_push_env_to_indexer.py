from pathlib import Path

from deploy.migrations._helpers import parse_env_file, append_env_value, backup_file

MIGRATION_KEY = "v1.21.2-push-env-to-indexer"
DESCRIPTION = "Move push notification env vars from backend.env to indexer.env"


def run(config_dir, logger):
    config_dir = Path(config_dir)
    backend_env = config_dir / "backend.env"
    indexer_env = config_dir / "indexer.env"

    if not backend_env.exists():
        return "backend.env not found, skipping"

    backend_vals = parse_env_file(backend_env)

    push_enabled = backend_vals.get("PUSH_NOTIFICATIONS_ENABLED", "false")
    expo_token = backend_vals.get("EXPO_ACCESS_TOKEN", "")

    if not indexer_env.exists():
        return "indexer.env not found, skipping"

    backup_file(indexer_env)

    added_push = append_env_value(
        indexer_env,
        "PUSH_NOTIFICATIONS_ENABLED",
        push_enabled,
        comment="Push notifications - set to true to enable Expo push for inbox events",
    )
    added_expo = append_env_value(
        indexer_env,
        "EXPO_ACCESS_TOKEN",
        expo_token,
        comment="Expo access token (optional) - for Enhanced Push Security in EAS dashboard",
    )

    msgs = []
    if added_push:
        msgs.append(f"PUSH_NOTIFICATIONS_ENABLED={push_enabled}")
    if added_expo:
        msgs.append(f"EXPO_ACCESS_TOKEN={'(set)' if expo_token else '(empty)'}")

    if msgs:
        logger.info("  Moved to indexer.env: %s", ", ".join(msgs))
        return "push env vars moved to indexer.env"
    return "push env vars already in indexer.env"
