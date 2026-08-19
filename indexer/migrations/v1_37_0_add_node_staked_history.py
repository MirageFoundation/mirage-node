"""Track validator staking so liquid transfers are not mislabeled as spending."""

from indexer.migrations import run_db_migration

MIGRATION_KEY = "v1.37.0_add_node_staked_history"


def run(db, chain, logger):
    def _add_column(cur):
        cur.execute("ALTER TABLE supply_history ADD COLUMN IF NOT EXISTS node_staked BIGINT")
        return "added supply_history.node_staked"

    return run_db_migration(db, MIGRATION_KEY, _add_column, logger)
