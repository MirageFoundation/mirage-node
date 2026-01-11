"""
Migration: Clean up orphaned files in data directory

Removes orphaned priv_validator_state.json from ~/.mirage/
(the correct location is ~/.mirage/main/data/priv_validator_state.json)
"""

from pathlib import Path

MIGRATION_KEY = "v1.7.6_cleanup_orphan_files"
DESCRIPTION = "Remove orphaned files from data directory"

# Files that shouldn't be in ~/.mirage/ root
ORPHAN_FILES = [
    "priv_validator_state.json",  # Should be in main/data/
    ".domain",  # Migrated to node.env by v1_7_6_domain_env
]


def run(config_dir: Path, logger) -> str:
    """Run the migration."""
    data_dir = config_dir.parent  # ~/.mirage

    removed = []
    for filename in ORPHAN_FILES:
        orphan = data_dir / filename
        if orphan.exists():
            orphan.unlink()
            removed.append(filename)
            logger.info(f"  Removed orphaned {filename}")

    if removed:
        return f"removed: {', '.join(removed)}"
    return "no orphaned files found"
