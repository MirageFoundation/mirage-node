from pathlib import Path

from deploy.migrations._helpers import append_env_value, backup_file

MIGRATION_KEY = "v1.21.2-log-retention-env"
DESCRIPTION = "Add LOG_RETENTION_DAYS to node.env"


def run(config_dir, logger):
    config_dir = Path(config_dir)
    node_env = config_dir / "node.env"

    if not node_env.exists():
        raise FileNotFoundError(f"node.env not found: {node_env}")

    backup_file(node_env)

    added = append_env_value(
        node_env,
        "LOG_RETENTION_DAYS",
        "90",
        comment="Log file retention (days) - files older than this are deleted daily",
    )

    if added:
        logger.info("  Added LOG_RETENTION_DAYS=90")
    else:
        logger.info("  LOG_RETENTION_DAYS already present")

    return "LOG_RETENTION_DAYS added" if added else "LOG_RETENTION_DAYS already present"
