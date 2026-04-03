from pathlib import Path

from deploy.migrations._helpers import backup_file, parse_env_file, update_env_value

MIGRATION_KEY = "v1.22.4-log-retention-reduce"
DESCRIPTION = "Reduce LOG_RETENTION_DAYS from 90 to 30"


def run(config_dir, logger):
    config_dir = Path(config_dir)
    node_env = config_dir / "node.env"

    if not node_env.exists():
        raise FileNotFoundError(f"node.env not found: {node_env}")

    backup_file(node_env)

    values = parse_env_file(node_env)
    current = values.get("LOG_RETENTION_DAYS")

    if current != "90":
        logger.info(f"  LOG_RETENTION_DAYS is {current!r}, not 90 — leaving as-is")
        return f"skipped (current={current!r})"

    if not update_env_value(node_env, "LOG_RETENTION_DAYS", "30"):
        raise RuntimeError("Failed to update LOG_RETENTION_DAYS in node.env")

    logger.info("  Updated LOG_RETENTION_DAYS: 90 -> 30")
    return "updated 90 -> 30"
