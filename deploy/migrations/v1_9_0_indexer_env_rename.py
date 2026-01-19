"""
Migration: v1.9.0 - Rename MIRAGE_INDEXER_* to INDEXER_*

This migration renames environment variables in indexer.env:
- MIRAGE_INDEXER_ENABLED -> INDEXER_ENABLED
- MIRAGE_INDEXER_DB_URL -> INDEXER_DB_URL

All operations are idempotent - safe to run multiple times.
"""

import re
from pathlib import Path

MIGRATION_KEY = "v1_9_0_indexer_env_rename"
DESCRIPTION = "Rename MIRAGE_INDEXER_* to INDEXER_*"

# Map of old key -> new key
RENAMES = {
    "MIRAGE_INDEXER_ENABLED": "INDEXER_ENABLED",
    "MIRAGE_INDEXER_DB_URL": "INDEXER_DB_URL",
}


def run(config_dir: Path, logger) -> str:
    """Run the migration."""
    config_dir = Path(config_dir)
    indexer_env = config_dir / "indexer.env"

    if not indexer_env.exists():
        logger.info("    indexer.env not found, skipping")
        return "skipped (no indexer.env)"

    content = indexer_env.read_text()
    renamed = []

    for old_key, new_key in RENAMES.items():
        # Check if old key exists and new key doesn't
        if re.search(rf"^{re.escape(old_key)}=", content, re.MULTILINE):
            if not re.search(rf"^{re.escape(new_key)}=", content, re.MULTILINE):
                # Rename the key
                content = re.sub(
                    rf"^{re.escape(old_key)}=",
                    f"{new_key}=",
                    content,
                    flags=re.MULTILINE,
                )
                renamed.append(f"{old_key} -> {new_key}")
                logger.info(f"    Renamed {old_key} -> {new_key}")

    if renamed:
        indexer_env.write_text(content)
        return f"renamed: {', '.join(renamed)}"

    return "no changes needed"
