from pathlib import Path

from deploy.migrations._helpers import append_env_value, backup_file

MIGRATION_KEY = "v1.21.4-app-banners-env"
DESCRIPTION = "Add ANDROID_BANNER_ENABLED and IOS_BANNER_ENABLED env vars to backend.env"


def run(config_dir, logger):
    config_dir = Path(config_dir)
    backend_env = config_dir / "backend.env"

    if not backend_env.exists():
        raise FileNotFoundError(f"backend.env not found: {backend_env}")

    backup_file(backend_env)

    added_android = append_env_value(
        backend_env,
        "ANDROID_BANNER_ENABLED",
        "true",
        comment="Android app download banner - set to false to hide on the web frontend",
    )

    added_ios = append_env_value(
        backend_env,
        "IOS_BANNER_ENABLED",
        "true",
        comment="iOS app download banner - set to false to hide on the web frontend",
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
