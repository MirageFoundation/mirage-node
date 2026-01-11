"""
Migration: v1.7.9-directory-restructuring - Reorganize ~/.mirage directory

This migration:
1. Moves PostgreSQL data from ~/.mirage/main/data/postgres/ to ~/.mirage/postgres/
2. Renames ~/.mirage/main/ to ~/.mirage/node/

Target structure after migration:
~/.mirage/
├── node/          # renamed from main/
│   ├── config/
│   ├── data/      # blockchain data only (no postgres)
│   └── keyring-test/
├── postgres/      # moved from main/data/postgres/
├── env/           # unchanged
├── logs/          # unchanged
└── hermes/        # unchanged
"""

import shutil
from pathlib import Path

MIGRATION_KEY = "v1.7.8-directory-restructuring"
DESCRIPTION = "Reorganize ~/.mirage directory (main→node, postgres to top level)"


def run(config_dir: Path, logger) -> str:
    """Run the migration."""
    results = []
    data_dir = config_dir.parent  # ~/.mirage

    old_main = data_dir / "main"
    new_node = data_dir / "node"
    old_postgres = old_main / "data" / "postgres"
    new_postgres = data_dir / "postgres"

    # Skip if already migrated (node exists, main doesn't or is symlink)
    if new_node.exists() and (not old_main.exists() or old_main.is_symlink()):
        logger.info("    Directory structure already migrated")
        return "already migrated"

    # Skip if neither exists (fresh install with new code)
    if not old_main.exists() and not new_node.exists():
        logger.info("    Fresh install, no migration needed")
        return "fresh install"

    # Step 1: Move postgres data to top level (before renaming main)
    if old_postgres.exists() and old_postgres.is_dir():
        if new_postgres.exists():
            logger.warning(f"    Target postgres dir already exists: {new_postgres}")
            results.append("postgres: target exists, skipped")
        else:
            logger.info(f"    Moving postgres data: {old_postgres} -> {new_postgres}")
            shutil.move(str(old_postgres), str(new_postgres))
            results.append("moved postgres to top level")

    # Step 2: Rename main to node
    if old_main.exists() and not old_main.is_symlink():
        if new_node.exists():
            logger.warning(f"    Target node dir already exists: {new_node}")
            results.append("node: target exists, skipped")
        else:
            logger.info(f"    Renaming: {old_main} -> {new_node}")
            shutil.move(str(old_main), str(new_node))
            
            # Create symlink for backward compatibility
            try:
                old_main.symlink_to(new_node)
                logger.info(f"    Created symlink: {old_main} -> {new_node}")
                results.append("renamed main to node + symlink")
            except Exception as e:
                logger.warning(f"    Failed to create symlink: {e}")
                results.append("renamed main to node (symlink failed)")

    if results:
        return "; ".join(results)
    return "no changes needed"
