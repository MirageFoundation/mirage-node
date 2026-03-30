from pathlib import Path

from deploy.migrations._helpers import backup_file, parse_env_file, update_env_value

MIGRATION_KEY = "v1.22.0-snapshot-keep-recent"
DESCRIPTION = "Reduce SNAPSHOT_KEEP_RECENT from 28 to 4"


def run(config_dir, logger):
    config_dir = Path(config_dir)
    node_env = config_dir / "node.env"

    if not node_env.exists():
        raise FileNotFoundError(f"node.env not found: {node_env}")

    backup_file(node_env)

    values = parse_env_file(node_env)
    current = values.get("SNAPSHOT_KEEP_RECENT")

    if current != "28":
        logger.info(f"  SNAPSHOT_KEEP_RECENT is {current!r}, not 28 — leaving as-is")
        return f"skipped (current={current!r})"

    if not update_env_value(node_env, "SNAPSHOT_KEEP_RECENT", "4"):
        raise RuntimeError("Failed to update SNAPSHOT_KEEP_RECENT in node.env")

    logger.info("  Updated SNAPSHOT_KEEP_RECENT: 28 -> 4")
    return "updated 28 -> 4"
