from pathlib import Path

from deploy.migrations._helpers import backup_file, parse_env_file, update_env_value

MIGRATION_KEY = "v1.26.1-open-registration"
DESCRIPTION = "Open signup on all nodes: REGISTRATION_ENABLED=true, REGISTRATION_INVITE_CODE_REQUIRED=false"


def run(config_dir, logger):
    config_dir = Path(config_dir)
    backend_env = config_dir / "backend.env"

    if not backend_env.exists():
        raise FileNotFoundError(f"backend.env not found: {backend_env}")

    backup_file(backend_env)

    targets = {
        "REGISTRATION_ENABLED": "true",
        "REGISTRATION_INVITE_CODE_REQUIRED": "false",
    }

    values = parse_env_file(backend_env)
    changed = []

    for key, target in targets.items():
        current = values.get(key)
        if current is None:
            raise RuntimeError(f"{key} missing from backend.env")
        if current == target:
            logger.info(f"  {key} already {target!r}, leaving as-is")
            continue
        if not update_env_value(backend_env, key, target):
            raise RuntimeError(f"Failed to update {key} in backend.env")
        logger.info(f"  Updated {key}: {current!r} -> {target!r}")
        changed.append(key)

    if changed:
        return f"opened registration ({', '.join(changed)})"
    return "registration already open"
