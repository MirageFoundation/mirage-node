from pathlib import Path

from deploy.migrations._helpers import append_env_value, backup_file

MIGRATION_KEY = "v1.21.4-app-banners-env"
DESCRIPTION = "Add ANDROID_BANNER_ENABLED and IOS_BANNER_ENABLED env vars to frontend.env"


def run(config_dir, logger):
    config_dir = Path(config_dir)
    frontend_env = config_dir / "frontend.env"

    if not frontend_env.exists():
        raise FileNotFoundError(f"frontend.env not found: {frontend_env}")

    backup_file(frontend_env)

    added_android = append_env_value(
        frontend_env,
        "ANDROID_BANNER_ENABLED",
        "true",
        comment="App download banners (read by backend get_node_config at runtime)",
    )

    added_ios = append_env_value(
        frontend_env,
        "IOS_BANNER_ENABLED",
        "true",
    )

    if added_android:
        logger.info("  Added ANDROID_BANNER_ENABLED=true")
    else:
        logger.info("  ANDROID_BANNER_ENABLED already present")

    if added_ios:
        logger.info("  Added IOS_BANNER_ENABLED=true")
    else:
        logger.info("  IOS_BANNER_ENABLED already present")

    if added_android or added_ios:
        return "app banner env vars added"
    return "app banner env vars already present"
