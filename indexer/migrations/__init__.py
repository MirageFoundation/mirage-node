"""
Indexer Migration System

Migrations run automatically on indexer startup. Each migration:
1. Has a unique MIGRATION_KEY (e.g., "v1.7.5_subscription_expiry")
2. Checks the meta table to see if it's already been run
3. Runs once and records completion

To add a new migration:
1. Create a new file in this directory (e.g., v1_8_0_my_migration.py)
2. Define MIGRATION_KEY and run(db, chain, logger) function
3. The migration will run automatically on next indexer startup

Migration files are executed in alphabetical order by filename.
"""

import importlib
import logging
import os
import pkgutil
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from indexer.database import DatabaseManager
    from indexer.chain_client import ChainClient

logger = logging.getLogger(__name__)


def discover_migrations() -> list[tuple[str, str, any]]:
    """
    Discover all migration modules in this package.
    
    Returns list of (filename, migration_key, module) tuples sorted by filename.
    """
    migrations = []
    package_dir = os.path.dirname(__file__)
    
    for _, module_name, _ in pkgutil.iter_modules([package_dir]):
        if module_name.startswith("_"):
            continue
        
        try:
            module = importlib.import_module(f"indexer.migrations.{module_name}")
            
            if not hasattr(module, "MIGRATION_KEY"):
                logger.warning(f"Migration {module_name} missing MIGRATION_KEY, skipping")
                continue
            
            if not hasattr(module, "run"):
                logger.warning(f"Migration {module_name} missing run() function, skipping")
                continue
            
            migrations.append((module_name, module.MIGRATION_KEY, module))
            
        except Exception as e:
            logger.error(f"Failed to load migration {module_name}: {e}")
            continue
    
    # Sort by filename for deterministic order
    migrations.sort(key=lambda x: x[0])
    return migrations


def get_completed_migrations(db: "DatabaseManager") -> set[str]:
    """Get set of migration keys that have already been completed."""
    completed = set()
    try:
        with db._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT key FROM meta WHERE key LIKE 'migration_%'")
                for row in cur.fetchall():
                    # Extract migration key from meta key (e.g., "migration_v1.7.5_foo" -> "v1.7.5_foo")
                    key = row[0]
                    if key.startswith("migration_"):
                        completed.add(key[len("migration_"):])
    except Exception as e:
        logger.error(f"Failed to get completed migrations: {e}")
    return completed


def mark_migration_complete(db: "DatabaseManager", migration_key: str, result: str = "completed") -> None:
    """Mark a migration as completed in the meta table."""
    meta_key = f"migration_{migration_key}"
    try:
        with db._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO meta(key, value) VALUES(%s, %s) ON CONFLICT(key) DO UPDATE SET value = EXCLUDED.value",
                    (meta_key, result),
                )
    except Exception as e:
        logger.error(f"Failed to mark migration {migration_key} complete: {e}")
        raise


def run_migrations(db: "DatabaseManager", chain: "ChainClient") -> int:
    """
    Run all pending migrations.
    
    Args:
        db: Database manager instance
        chain: Chain client instance for chain queries
        
    Returns:
        Number of migrations that were run
    """
    migrations = discover_migrations()
    if not migrations:
        logger.debug("No migrations found")
        return 0
    
    completed = get_completed_migrations(db)
    pending = [(name, key, mod) for name, key, mod in migrations if key not in completed]
    
    if not pending:
        logger.debug(f"All {len(migrations)} migrations already completed")
        return 0
    
    logger.info(f"Found {len(pending)} pending migrations out of {len(migrations)} total")
    
    run_count = 0
    for filename, migration_key, module in pending:
        logger.info(f"Running migration: {migration_key} ({filename})")
        try:
            result = module.run(db, chain, logger)
            result_str = str(result) if result is not None else "completed"
            mark_migration_complete(db, migration_key, result_str)
            logger.info(f"Migration {migration_key} completed: {result_str}")
            run_count += 1
        except Exception as e:
            logger.error(f"Migration {migration_key} failed: {e}", exc_info=True)
            raise RuntimeError(f"Migration {migration_key} failed: {e}") from e
    
    return run_count
