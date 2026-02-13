"""
Deploy Migration System

Runs automatically on container startup (via entrypoint.sh):
1. One-time migrations (tracked in .migrations file)
2. Env file sync (runs every time to keep files up-to-date with templates)

To add a new one-time migration:
1. Create a new file in this directory (e.g., v1_8_0_my_migration.py)
2. Define MIGRATION_KEY and run(config_dir, logger) function
3. The migration will run automatically on next container startup

Migration files are executed in alphabetical order by filename.
"""

import importlib
import logging
import os
import pkgutil
from pathlib import Path
from datetime import datetime
from typing import Callable

logger = logging.getLogger(__name__)


def discover_migrations() -> list[tuple[str, str, any]]:
    """
    Discover all migration modules in this package.

    Returns list of (filename, migration_key, module) tuples sorted by filename.
    """
    migrations = []
    package_dir = os.path.dirname(__file__)

    for _, module_name, _ in pkgutil.iter_modules([package_dir]):
        # Skip internal modules (starting with _)
        if module_name.startswith("_"):
            continue

        try:
            module = importlib.import_module(f"deploy.migrations.{module_name}")

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


def get_migrations_file(config_dir: Path) -> Path:
    """Get path to migrations tracking file."""
    return config_dir / ".migrations"


def get_completed_migrations(config_dir: Path) -> set[str]:
    """Get set of migration keys that have already been completed."""
    migrations_file = get_migrations_file(config_dir)
    completed = set()

    if migrations_file.exists():
        try:
            with open(migrations_file, "r") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        # Format: "migration_key|timestamp|result"
                        parts = line.split("|")
                        if parts:
                            completed.add(parts[0])
        except Exception as e:
            logger.error(f"Failed to read migrations file: {e}")

    return completed


def mark_migration_complete(config_dir: Path, migration_key: str, result: str = "completed") -> None:
    """Mark a migration as completed."""
    migrations_file = get_migrations_file(config_dir)
    timestamp = datetime.now().isoformat()

    try:
        with open(migrations_file, "a") as f:
            f.write(f"{migration_key}|{timestamp}|{result}\n")
    except Exception as e:
        logger.error(f"Failed to mark migration {migration_key} complete: {e}")
        raise


def run_one_time_migrations(config_dir: Path) -> int:
    """
    Run all pending one-time migrations.

    Args:
        config_dir: Path to env directory (e.g., ~/.mirage/env)

    Returns:
        Number of migrations that were run
    """
    config_dir = Path(config_dir)

    if not config_dir.exists():
        config_dir.mkdir(parents=True, exist_ok=True)

    migrations = discover_migrations()
    if not migrations:
        logger.debug("No migrations found")
        return 0

    # Fresh deployment: no .migrations file means templates already have correct
    # defaults — mark all existing migrations as completed so they don't run.
    migrations_file = get_migrations_file(config_dir)
    if not migrations_file.exists():
        logger.info("Fresh deployment detected (no .migrations file) — skipping all existing migrations")
        for _, key, module in migrations:
            mark_migration_complete(config_dir, key, "skipped (fresh deploy)")
        return 0

    completed = get_completed_migrations(config_dir)
    pending = [(name, key, mod) for name, key, mod in migrations if key not in completed]

    if not pending:
        logger.debug(f"All {len(migrations)} migrations already completed")
        return 0

    logger.info(f"Found {len(pending)} pending deploy migrations")

    run_count = 0
    for filename, migration_key, module in pending:
        description = getattr(module, "DESCRIPTION", "")
        logger.info(f"Running migration: {migration_key} - {description}")
        try:
            result = module.run(config_dir, logger)
            result_str = str(result) if result is not None else "completed"
            mark_migration_complete(config_dir, migration_key, result_str)
            logger.info(f"Migration {migration_key} completed: {result_str}")
            run_count += 1
        except Exception as e:
            logger.error(f"Migration {migration_key} failed: {e}", exc_info=True)
            # Don't fail the whole startup, just log and continue
            # Mark as failed so we can retry
            mark_migration_complete(config_dir, migration_key, f"FAILED: {e}")
            continue

    return run_count


def run_env_sync(config_dir: Path) -> None:
    """Sync env files with latest templates."""
    from deploy.migrations._helpers import sync_all

    config_dir = Path(config_dir)
    templates_root = Path(__file__).parent.parent / "templates"
    templates_dir = templates_root / "env" if (templates_root / "env").exists() else templates_root

    if not templates_dir.exists():
        logger.warning(f"Templates directory not found: {templates_dir}")
        return

    if not config_dir.exists():
        config_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Syncing env files with templates...")
    sync_all(templates_dir, config_dir)


def run_node_cleanup(config_dir: Path) -> None:
    """Clean up node temp files (runs every deploy)."""
    from deploy.migrations._helpers import cleanup_node_temp_files

    config_dir = Path(config_dir)
    cleanup_node_temp_files(config_dir, logger)


def run_migrations(config_dir: Path) -> int:
    """
    Run all migrations, sync env files, and clean up temp files.

    Args:
        config_dir: Path to env directory (e.g., ~/.mirage/env)

    Returns:
        Number of one-time migrations that were run
    """
    # Step 0: Migrate config/ -> env/ (one-time directory rename)
    config_dir = Path(config_dir)
    old_config_dir = config_dir.parent / "config"
    if old_config_dir.exists() and old_config_dir.is_dir():
        if not config_dir.exists():
            # Simple rename
            logger.info(f"Renaming {old_config_dir} -> {config_dir}")
            old_config_dir.rename(config_dir)
        else:
            # Both exist - copy any missing files from old to new, then delete old
            logger.info(f"Merging {old_config_dir} -> {config_dir}")
            import shutil

            for item in old_config_dir.iterdir():
                dest = config_dir / item.name
                if not dest.exists():
                    if item.is_file():
                        shutil.copy2(item, dest)
                    elif item.is_dir():
                        shutil.copytree(item, dest)
            # Delete old config/ directory
            shutil.rmtree(old_config_dir)
            logger.info(f"Deleted old {old_config_dir}")

    # Step 1: Run one-time migrations
    count = run_one_time_migrations(config_dir)

    # Step 2: Sync env files with templates (runs every time)
    run_env_sync(config_dir)

    # Step 3: Clean up node temp files (runs every time)
    run_node_cleanup(config_dir)

    return count


def main():
    """CLI entry point for running migrations."""
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    parser = argparse.ArgumentParser(description="Run deploy migrations")
    parser.add_argument(
        "--config-dir",
        type=Path,
        default=Path.home() / ".mirage" / "env",
        help="Path to env directory (default: ~/.mirage/env)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List all migrations and their status",
    )
    args = parser.parse_args()

    if args.list:
        migrations = discover_migrations()
        completed = get_completed_migrations(args.config_dir)

        print(f"\nDeploy Migrations ({args.config_dir}):")
        print("=" * 60)
        for filename, key, module in migrations:
            status = "✓" if key in completed else "○"
            desc = getattr(module, "DESCRIPTION", "")
            print(f"  {status} {key}: {desc}")
        print()
        return

    count = run_migrations(args.config_dir)
    if count > 0:
        print(f"\nRan {count} migration(s)")
    else:
        print("\nNo pending migrations")


if __name__ == "__main__":
    main()
