from pathlib import Path
import shutil

from deploy.migrations._helpers import backup_file, parse_env_file, update_env_value

MIGRATION_KEY = "v1.20.0-tx-index-cleanup"
DESCRIPTION = "Disable orchestrator and remove tx_index.db"


def run(config_dir, logger):
    config_dir = Path(config_dir)
    orchestrator_env = config_dir / "orchestrator.env"

    if orchestrator_env.exists():
        backup_file(orchestrator_env)
        values = parse_env_file(orchestrator_env)
        current = values.get("ORCHESTRATOR_ENABLED")
        logger.debug(f"  ORCHESTRATOR_ENABLED current value: {current!r}")

        if current is None:
            raise RuntimeError("ORCHESTRATOR_ENABLED missing in orchestrator.env")

        if current.lower() != "false":
            if not update_env_value(orchestrator_env, "ORCHESTRATOR_ENABLED", "false"):
                raise RuntimeError(f"Failed to update ORCHESTRATOR_ENABLED in {orchestrator_env}")
            logger.info("  Updated ORCHESTRATOR_ENABLED=false")
        else:
            logger.info("  ORCHESTRATOR_ENABLED already false")
    else:
        logger.info("  orchestrator.env absent; orchestrator already removed")

    tx_index_path = config_dir.parent / "node" / "data" / "tx_index.db"
    logger.debug(f"  tx_index.db path: {tx_index_path}")
    if tx_index_path.exists():
        logger.info(f"  Removing tx_index.db: {tx_index_path}")
        if tx_index_path.is_dir():
            shutil.rmtree(tx_index_path)
        else:
            tx_index_path.unlink()
        logger.info("  Removed tx_index.db")
    else:
        logger.info("  tx_index.db not found (already removed)")

    return "orchestrator disabled; tx_index.db removed"
