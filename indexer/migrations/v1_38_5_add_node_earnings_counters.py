"""Track what the node was actually paid, instead of inferring it from balances."""

from indexer.migrations import run_db_migration

MIGRATION_KEY = "v1.38.5_add_node_earnings_counters"


def run(db, chain, logger):
    def _add_columns(cur):
        cur.execute("ALTER TABLE supply_history ADD COLUMN IF NOT EXISTS node_minted_total BIGINT")
        cur.execute("ALTER TABLE supply_history ADD COLUMN IF NOT EXISTS node_fees_total BIGINT")
        return "added supply_history.node_minted_total, supply_history.node_fees_total"

    return run_db_migration(db, MIGRATION_KEY, _add_columns, logger)
