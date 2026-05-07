from pathlib import Path

from deploy.migrations._helpers import append_env_value, backup_file

MIGRATION_KEY = "v1.23.7-trending-push-env"
DESCRIPTION = "Add TRENDING_PUSH_ENABLED env var to indexer.env"


def run(config_dir, logger):
    config_dir = Path(config_dir)
    indexer_env = config_dir / "indexer.env"

    if not indexer_env.exists():
        return "indexer.env not found, skipping"

    backup_file(indexer_env)

    added = append_env_value(
        indexer_env,
        "TRENDING_PUSH_ENABLED",
        "false",
        comment="Trending post push notifications - set to true to enable the trending poller",
    )

    if added:
        logger.info("  Added TRENDING_PUSH_ENABLED=false")
        return "TRENDING_PUSH_ENABLED added"
    return "TRENDING_PUSH_ENABLED already present"
