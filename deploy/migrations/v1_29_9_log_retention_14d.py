from pathlib import Path

from deploy.migrations._helpers import backup_file, parse_env_file, update_env_value

MIGRATION_KEY = "v1.29.9-log-retention-14d"
DESCRIPTION = "Reduce LOG_RETENTION_DAYS from 30 to 14 (log files dwarfed chain data)"

TARGET_DAYS = "14"
# Only rewrite the values we shipped as defaults. A hand-tuned value (anything
# else) is an operator decision and is left alone.
SUPERSEDED_DEFAULTS = {"30", "90"}


def run(config_dir, logger):
    """Shrink log retention on already-deployed nodes.

    The env template sync deliberately preserves existing non-empty values, so
    bumping the template default alone never reaches a live node — this migration
    is what actually applies it. Safe to run repeatedly: once the value is 14 (or
    an operator-chosen number) it is a no-op.

    Context: miraged writes ~45 MB/day, so 30 days of logs held ~1.4 GB — larger
    than every chain database combined. Forensic coverage is unaffected: the
    watchdog trail keeps its own 90 days and divergence snapshots are separate.
    """
    config_dir = Path(config_dir)
    node_env = config_dir / "node.env"

    if not node_env.exists():
        raise FileNotFoundError(f"node.env not found: {node_env}")

    current = parse_env_file(node_env).get("LOG_RETENTION_DAYS")

    if current == TARGET_DAYS:
        logger.info(f"  LOG_RETENTION_DAYS already {TARGET_DAYS}")
        return f"already {TARGET_DAYS}"

    if current is not None and current not in SUPERSEDED_DEFAULTS:
        logger.info(f"  LOG_RETENTION_DAYS={current} is operator-set, leaving as-is")
        return f"skipped (operator-set {current})"

    backup_file(node_env)

    if not update_env_value(node_env, "LOG_RETENTION_DAYS", TARGET_DAYS):
        logger.info("  LOG_RETENTION_DAYS not present, nothing to update")
        return "key absent"

    logger.info(f"  LOG_RETENTION_DAYS {current} -> {TARGET_DAYS}")
    return f"{current} -> {TARGET_DAYS}"
