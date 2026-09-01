"""
Indexer Migration System

Migrations run automatically on indexer startup. Each migration:
1. Has a unique MIGRATION_KEY (e.g., "v1.7.5_subscription_expiry")
2. Checks the meta table to see if it's already been run
3. Runs once and records completion

To add a new migration:
1. Create a new file in this directory matching the current git tag version
   (e.g., v1_32_4_my_migration.py when the tag is v1.32.4)
2. Define MIGRATION_KEY and run(db, chain, logger) function
3. The migration will run automatically on next indexer startup

Migration files are executed in alphabetical order by filename.

Contract:
- Discovery/import failures are fatal (no skipping broken modules).
- Completed-set read failures are fatal (never treat as empty).
- Prefer run_db_migration() for database-only work so DDL/DML and the
  completion marker share one transaction.
- RPC/network backfills must be resumable via meta progress keys and only
  write the completion marker after all work finishes.
- A MIGRATION_KEY is an on-disk identity. Never change one: the completed set is
  keyed by it, so a new spelling re-runs the migration everywhere.
- An applied migration's file is checksummed and a mismatch is fatal. If a
  release must rewrite one anyway, declare it in _REPINNED_MIGRATION_KEYS.
"""

from __future__ import annotations

import hashlib
import importlib
import logging
import os
import pkgutil
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from indexer.database import DatabaseManager
    from indexer.chain_client import ChainClient

logger = logging.getLogger(__name__)

# Stable advisory lock key for indexer migrations (arbitrary but fixed).
_MIGRATION_ADVISORY_LOCK_KEY = 0x4D495247_49445801  # "MIRGIDX\x01"


def _migration_file_path(module_name: str) -> str:
    return os.path.join(os.path.dirname(__file__), f"{module_name}.py")


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _is_completion_marker_key(meta_key: str) -> bool:
    if not meta_key.startswith("migration_"):
        return False
    if meta_key.endswith("_checksum"):
        return False
    if meta_key.endswith("_progress"):
        return False
    return True


def discover_migrations() -> list[tuple[str, str, object]]:
    """
    Discover all migration modules in this package.

    Returns list of (filename, migration_key, module) tuples sorted by filename.
    Import/attribute errors are fatal.
    """
    migrations: list[tuple[str, str, object]] = []
    package_dir = os.path.dirname(__file__)
    seen_keys: set[str] = set()

    for _, module_name, _ in pkgutil.iter_modules([package_dir]):
        if module_name.startswith("_"):
            continue

        try:
            module = importlib.import_module(f"indexer.migrations.{module_name}")
        except Exception as e:
            raise RuntimeError(f"Failed to load migration {module_name}: {e}") from e

        if not hasattr(module, "MIGRATION_KEY"):
            raise RuntimeError(f"Migration {module_name} missing MIGRATION_KEY")
        if not hasattr(module, "run"):
            raise RuntimeError(f"Migration {module_name} missing run() function")

        migration_key = str(module.MIGRATION_KEY)
        if migration_key in seen_keys:
            raise RuntimeError(f"Duplicate MIGRATION_KEY: {migration_key}")
        seen_keys.add(migration_key)
        migrations.append((module_name, migration_key, module))

    migrations.sort(key=lambda x: x[0])
    return migrations


def get_completed_migrations(db: "DatabaseManager") -> set[str]:
    """Get set of migration keys that have already been completed. Fail hard on DB errors."""
    completed: set[str] = set()
    with db._connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT key FROM meta WHERE key LIKE 'migration_%'")
            for row in cur.fetchall():
                key = str(row[0])
                if not _is_completion_marker_key(key):
                    continue
                completed.add(key[len("migration_") :])
    return completed


def mark_migration_complete(db: "DatabaseManager", migration_key: str, result: str = "completed") -> None:
    """Mark a migration as completed in the meta table."""
    meta_key = f"migration_{migration_key}"
    with db._connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO meta(key, value) VALUES(%s, %s) ON CONFLICT(key) DO UPDATE SET value = EXCLUDED.value",
                (meta_key, result),
            )


def run_db_migration(
    db: "DatabaseManager",
    migration_key: str,
    fn: Callable,
    log: logging.Logger | None = None,
    result: str = "completed",
) -> str:
    """
    Run a database-only migration and its completion marker in one transaction.

    `fn` receives a psycopg cursor. On any exception the transaction rolls back
    and no marker is written.
    """
    log = log or logger
    if not hasattr(db, "transaction"):
        raise RuntimeError("DatabaseManager.transaction is required for run_db_migration")
    with db.transaction(label=f"migration:{migration_key}"):
        with db._connect() as conn:
            with conn.cursor() as cur:
                out = fn(cur)
                result_str = str(out) if out is not None else result
                cur.execute(
                    "INSERT INTO meta(key, value) VALUES(%s, %s) ON CONFLICT(key) DO UPDATE SET value = EXCLUDED.value",
                    (f"migration_{migration_key}", result_str),
                )
                log.info("Migration %s marker written in-transaction: %s", migration_key, result_str)
                return result_str


def _meta_get(db: "DatabaseManager", key: str) -> str | None:
    if hasattr(db, "get_meta"):
        return db.get_meta(key)
    with db._connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT value FROM meta WHERE key = %s", (key,))
            row = cur.fetchone()
            return str(row[0]) if row and row[0] is not None else None


def _meta_set(db: "DatabaseManager", key: str, value: str) -> None:
    if hasattr(db, "set_meta"):
        db.set_meta(key, value)
        return
    with db._connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO meta(key, value) VALUES(%s, %s) ON CONFLICT(key) DO UPDATE SET value = EXCLUDED.value",
                (key, value),
            )


# Applied migrations whose files a later release deliberately rewrote. The
# checksum guard below exists to catch an *unreviewed* edit, and it fails the
# whole start-up, so a reviewed rewrite has to be declared here or every node
# that already ran the migration refuses to boot. The rewrite must not change
# what the migration does to a database that already applied it.
#
# v1.39.0 renamed topic_content_stats -> community_content_stats and
# user_topic_stats -> user_community_stats. Schema init creates the new names, so
# every earlier migration touching those tables had to move with them or a fresh
# database would fail on an old migration.
_REPIN_RELEASE = "v1.39.0"
_REPINNED_MIGRATION_KEYS = (
    "v1.16.0_agent_edits",
    "v1.22.4_rename_porn_to_adult",
    "v1.33.0_rebuild_derived_stats",
    "v1.34.0_repair_topic_attribution",
    "v1.36.0_repair_deleted_post_standing",
    "v1.39.0_communities",
    "v1.39.0_legacy_vote_standing",
    "v1.39.0_repair_resurrected_posts",
)
_REPIN_MARKER_KEY = "migration_checksum_repin"


def _repin_rewritten_checksums(db: "DatabaseManager") -> None:
    """Drop the pinned checksums this release rewrote, once, so they re-pin."""
    if _meta_get(db, _REPIN_MARKER_KEY) == _REPIN_RELEASE:
        return
    with db._connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM meta WHERE key = ANY(%s)",
                ([f"migration_{key}_checksum" for key in _REPINNED_MIGRATION_KEYS],),
            )
            dropped = cur.rowcount
    _meta_set(db, _REPIN_MARKER_KEY, _REPIN_RELEASE)
    logger.info("Re-pinning %s migration checksums rewritten by %s", dropped, _REPIN_RELEASE)


def _pin_or_verify_checksum(db: "DatabaseManager", module_name: str, migration_key: str) -> None:
    """Pin checksum on first see of a completed migration; fail on later mismatch."""
    path = _migration_file_path(module_name)
    if not os.path.isfile(path):
        raise RuntimeError(f"Migration file missing for checksum: {path}")
    digest = _sha256_file(path)
    checksum_key = f"migration_{migration_key}_checksum"
    existing = _meta_get(db, checksum_key)
    if existing is None:
        _meta_set(db, checksum_key, digest)
        logger.info(
            "Pinned migration checksum for legacy marker key=%s sha256=%s",
            migration_key,
            digest[:16],
        )
        return
    if existing != digest:
        raise RuntimeError(
            f"migration file modified after apply: {migration_key} "
            f"expected_sha256={existing} actual_sha256={digest}"
        )


def _store_checksum(db: "DatabaseManager", module_name: str, migration_key: str) -> None:
    path = _migration_file_path(module_name)
    digest = _sha256_file(path)
    _meta_set(db, f"migration_{migration_key}_checksum", digest)
    logger.debug("Stored migration checksum key=%s sha256=%s", migration_key, digest[:16])


def run_migrations(db: "DatabaseManager", chain: "ChainClient") -> int:
    """
    Run all pending migrations under an advisory lock.

    The advisory lock is session-scoped: the connection that acquired it must
    stay open for the entire migration run, otherwise PostgreSQL releases it
    immediately on close.

    Returns:
        Number of migrations that were run
    """
    migrations = discover_migrations()
    if not migrations:
        logger.debug("No migrations found")
        return 0

    # Open a dedicated autocommit connection that outlives the lock.
    import psycopg

    lock_conn = psycopg.connect(db.database_url, autocommit=True)
    try:
        with lock_conn.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_lock(%s)", (_MIGRATION_ADVISORY_LOCK_KEY,))
            row = cur.fetchone()
            if not row or not row[0]:
                raise RuntimeError(
                    "Another process holds the indexer migration advisory lock; "
                    "exiting rather than waiting indefinitely"
                )
            logger.debug("Acquired migration advisory lock key=%s", _MIGRATION_ADVISORY_LOCK_KEY)

        _repin_rewritten_checksums(db)
        completed = get_completed_migrations(db)

        for module_name, migration_key, _module in migrations:
            if migration_key in completed:
                _pin_or_verify_checksum(db, module_name, migration_key)

        pending = [(name, key, mod) for name, key, mod in migrations if key not in completed]
        if not pending:
            logger.debug("All %s migrations already completed", len(migrations))
            return 0

        logger.info("Found %s pending migrations out of %s total", len(pending), len(migrations))

        run_count = 0
        for filename, migration_key, module in pending:
            logger.info("Running migration: %s (%s)", migration_key, filename)
            try:
                result = module.run(db, chain, logger)
                result_str = str(result) if result is not None else "completed"
                mark_migration_complete(db, migration_key, result_str)
                _store_checksum(db, filename, migration_key)
                logger.info("Migration %s completed: %s", migration_key, result_str)
                run_count += 1
            except Exception as e:
                logger.error("Migration %s failed: %s", migration_key, e, exc_info=True)
                raise RuntimeError(f"Migration {migration_key} failed: {e}") from e

        return run_count
    finally:
        try:
            with lock_conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_unlock(%s)", (_MIGRATION_ADVISORY_LOCK_KEY,))
        finally:
            lock_conn.close()
