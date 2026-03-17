from pathlib import Path

from deploy.migrations._helpers import append_env_value, backup_file

MIGRATION_KEY = "v1.21.1-push-notifications-env"
DESCRIPTION = "Add push notification env vars to backend.env"


def run(config_dir, logger):
    config_dir = Path(config_dir)
    backend_env = config_dir / "backend.env"

    if not backend_env.exists():
        raise FileNotFoundError(f"backend.env not found: {backend_env}")

    backup_file(backend_env)

    added_push_enabled = append_env_value(
        backend_env,
        "PUSH_NOTIFICATIONS_ENABLED",
        "false",
        comment="Push notifications - set to true to enable Expo push for inbox events",
    )

    added_expo_token = append_env_value(
        backend_env,
        "EXPO_ACCESS_TOKEN",
        "",
        comment="Expo access token (optional) - for Enhanced Push Security in EAS dashboard",
    )

    if added_push_enabled:
        logger.info("  Added PUSH_NOTIFICATIONS_ENABLED=false")
    else:
        logger.info("  PUSH_NOTIFICATIONS_ENABLED already present")

    if added_expo_token:
        logger.info("  Added EXPO_ACCESS_TOKEN (empty)")
    else:
        logger.info("  EXPO_ACCESS_TOKEN already present")

    if added_push_enabled or added_expo_token:
        return "push notification env vars added"
    return "push notification env vars already present"
