from pathlib import Path

from deploy.migrations._helpers import (
    append_env_value,
    backup_file,
    parse_env_file,
    update_env_value,
)

MIGRATION_KEY = "v1.17.0-pruning-env-update"
DESCRIPTION = "Set pruning keep recent and interval defaults"


def _set_env_value(node_env: Path, key: str, value: str, logger, update_if=None) -> bool:
    values = parse_env_file(node_env)
    current = values.get(key)
    logger.debug(f"  {key} current value: {current!r}")

    if current:
        if update_if and not update_if(current, values):
            logger.info(f"  {key} already set to {current}; leaving as-is")
            return False
        if not update_env_value(node_env, key, value):
            raise RuntimeError(f"Failed to update {key} in {node_env}")
        logger.info(f"  Updated {key} -> {value}")
        return True

    if not append_env_value(node_env, key, value):
        raise RuntimeError(f"Failed to append {key} to {node_env}")
    logger.info(f"  Added {key}={value}")
    return True


def run(config_dir, logger):
    config_dir = Path(config_dir)
    node_env = config_dir / "node.env"

    if not node_env.exists():
        raise FileNotFoundError(f"node.env not found: {node_env}")

    backup_file(node_env)
    logger.info("  Updating node.env pruning settings")

    changed = 0

    def keep_recent_update_if(current, values):
        return current == values.get("RETENTION_BLOCKS") or current == "201600"

    if _set_env_value(node_env, "PRUNING_KEEP_RECENT", "1000", logger, keep_recent_update_if):
        changed += 1

    def interval_update_if(current, values):
        return current == "1000"

    if _set_env_value(node_env, "PRUNING_INTERVAL", "100", logger, interval_update_if):
        changed += 1

    logger.info(f"  Pruning migration updates: {changed}")
    return f"updated {changed} key(s)"
