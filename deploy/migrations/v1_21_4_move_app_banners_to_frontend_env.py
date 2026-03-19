from pathlib import Path

from deploy.migrations._helpers import append_env_value, backup_file, parse_env_file, remove_keys_from_file, update_env_value

MIGRATION_KEY = "v1.21.4-move-app-banners-to-frontend-env"
DESCRIPTION = "Move app banner env vars from backend.env to frontend.env"


def run(config_dir, logger):
    config_dir = Path(config_dir)
    backend_env = config_dir / "backend.env"
    frontend_env = config_dir / "frontend.env"

    if not backend_env.exists():
        raise FileNotFoundError(f"backend.env not found: {backend_env}")
    if not frontend_env.exists():
        raise FileNotFoundError(f"frontend.env not found: {frontend_env}")

    backup_file(backend_env)
    backup_file(frontend_env)

    backend_values = parse_env_file(backend_env)
    frontend_values = parse_env_file(frontend_env)

    added_android = False
    added_ios = False
    updated_android = False
    updated_ios = False

    if "ANDROID_BANNER_ENABLED" in backend_values:
        android_value = backend_values["ANDROID_BANNER_ENABLED"]
        updated_android = update_env_value(frontend_env, "ANDROID_BANNER_ENABLED", android_value)
        if not updated_android:
            added_android = append_env_value(
                frontend_env,
                "ANDROID_BANNER_ENABLED",
                android_value,
                comment="App download banners (read by backend get_node_config at runtime)",
            )
    else:
        if "ANDROID_BANNER_ENABLED" not in frontend_values:
            added_android = append_env_value(
                frontend_env,
                "ANDROID_BANNER_ENABLED",
                "true",
                comment="App download banners (read by backend get_node_config at runtime)",
            )

    if "IOS_BANNER_ENABLED" in backend_values:
        ios_value = backend_values["IOS_BANNER_ENABLED"]
        updated_ios = update_env_value(frontend_env, "IOS_BANNER_ENABLED", ios_value)
        if not updated_ios:
            added_ios = append_env_value(frontend_env, "IOS_BANNER_ENABLED", ios_value)
    else:
        if "IOS_BANNER_ENABLED" not in frontend_values:
            added_ios = append_env_value(frontend_env, "IOS_BANNER_ENABLED", "true")

    removed = remove_keys_from_file(
        backend_env,
        ["ANDROID_BANNER_ENABLED", "IOS_BANNER_ENABLED"],
        logger=logger,
    )

    if updated_android:
        logger.info("  Updated ANDROID_BANNER_ENABLED from backend.env")
    elif added_android:
        logger.info("  Added ANDROID_BANNER_ENABLED to frontend.env")
    else:
        logger.info("  ANDROID_BANNER_ENABLED already present in frontend.env")

    if updated_ios:
        logger.info("  Updated IOS_BANNER_ENABLED from backend.env")
    elif added_ios:
        logger.info("  Added IOS_BANNER_ENABLED to frontend.env")
    else:
        logger.info("  IOS_BANNER_ENABLED already present in frontend.env")

    if removed:
        logger.info(f"  Removed {removed} app banner keys from backend.env")
    else:
        logger.info("  No app banner keys found in backend.env")

    if added_android or added_ios or updated_android or updated_ios or removed:
        return "app banner env vars moved to frontend.env"
    return "app banner env vars already in frontend.env"
