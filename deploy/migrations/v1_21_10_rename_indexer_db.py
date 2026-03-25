"""
One-time migration: rename indexer database and roles.

The actual DB/role renames (ALTER DATABASE, ALTER ROLE) require superuser and
are handled by entrypoint.sh's migrate_local_postgres_names().  This migration
entry exists solely to track that the rename step has been acknowledged by the
deployment pipeline.
"""

from __future__ import annotations

MIGRATION_KEY = "v1.21.10-rename-indexer-db"
DESCRIPTION = "Rename indexer DB mirage→mirage_indexer + roles (handled by entrypoint)"


def run(config_dir, logger):
    return "handled by entrypoint.sh (DB and role renames require superuser)"
