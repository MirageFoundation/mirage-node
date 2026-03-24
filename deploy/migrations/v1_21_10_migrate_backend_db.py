"""
One-time migration: copy backend-owned tables from the shared indexer DB
to the new separate backend DB (indexer/backend DB split).

Runs automatically on container startup. Idempotent (ON CONFLICT DO NOTHING).
Skips gracefully if source tables don't exist or DBs are already separate.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

MIGRATION_KEY = "v1.21.10-migrate-backend-db-split"
DESCRIPTION = "Migrate backend-owned tables from indexer DB to new backend DB"

BACKEND_TABLES = [
    "invite_codes",
    "referral_links",
    "referral_pending_rewards",
    "referral_trust_scores",
    "referral_analysis",
    "referral_user_accruals",
    "referral_state",
    "reports",
    "user_similarity_cache",
    "push_tokens",
    "push_budget",
    "push_throttle",
    "push_receipts",
    "push_nonces",
    "user_daily_quests",
    "user_flash_quests",
    "user_quest_state",
    "pending_rewards",
    "reward_suspensions",
    "user_unlocks",
    "user_achievements",
    "user_inbox_state",
]


def run(config_dir, logger):
    import psycopg

    indexer_url = (
        os.environ.get("INDEXER_DB_URL", "").strip()
        or "postgresql://mirage:mirage@127.0.0.1:5432/mirage"
    )
    backend_url = (
        os.environ.get("BACKEND_DB_URL", "").strip()
        or "postgresql://mirage:mirage@127.0.0.1:5432/mirage_backend"
    )
    if indexer_url == backend_url:
        return "skipped: INDEXER_DB_URL == BACKEND_DB_URL (same DB, no split)"

    try:
        src = psycopg.connect(indexer_url, autocommit=True)
        dst = psycopg.connect(backend_url, autocommit=True)
    except Exception as e:
        logger.error(f"migrate_backend_db: connection failed: {e}")
        return f"error: {e}"

    start = time.time()
    total_migrated = 0
    skipped = 0

    for table in BACKEND_TABLES:
        try:
            result = _migrate_table(src, dst, table, logger)
            if result > 0:
                total_migrated += result
            else:
                skipped += 1
        except Exception as e:
            logger.error(f"  {table}: migration error: {e}")

    src.close()
    dst.close()
    elapsed = time.time() - start

    msg = f"migrated {total_migrated} rows across {len(BACKEND_TABLES) - skipped} tables in {elapsed:.1f}s ({skipped} skipped)"
    logger.info(f"migrate_backend_db: {msg}")
    return msg


def _table_exists(cur, table: str) -> bool:
    cur.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = %s",
        (table,),
    )
    return cur.fetchone() is not None


def _get_columns(cur, table: str) -> list[str]:
    cur.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = %s ORDER BY ordinal_position",
        (table,),
    )
    return [row[0] for row in cur.fetchall()]


def _get_column_types(cur, table: str) -> dict[str, str]:
    cur.execute(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = %s ORDER BY ordinal_position",
        (table,),
    )
    return {row[0]: row[1] for row in cur.fetchall()}


def _adapt_row(row: tuple, common: list[str], col_types: dict[str, str]) -> tuple:
    from psycopg.types.json import Json
    adapted = []
    for val, col in zip(row, common):
        if isinstance(val, (dict, list)) and col_types.get(col) == "jsonb":
            adapted.append(Json(val))
        else:
            adapted.append(val)
    return tuple(adapted)


def _migrate_table(src_conn, dst_conn, table: str, logger) -> int:
    src_cur = src_conn.cursor()
    dst_cur = dst_conn.cursor()

    if not _table_exists(src_cur, table):
        logger.debug(f"  {table}: not in source DB, skipping")
        return 0
    if not _table_exists(dst_cur, table):
        logger.warning(f"  {table}: not in destination DB (init_backend_schema may not have run), skipping")
        return 0

    src_cur.execute(f"SELECT COUNT(*) FROM {table}")
    src_count = src_cur.fetchone()[0]
    if src_count == 0:
        logger.debug(f"  {table}: empty in source, skipping")
        return 0

    dst_cur.execute(f"SELECT COUNT(*) FROM {table}")
    dst_before = dst_cur.fetchone()[0]

    src_col_types = _get_column_types(src_cur, table)
    dst_col_set = set(_get_columns(dst_cur, table))
    common = [c for c in src_col_types if c in dst_col_set]
    if not common:
        logger.warning(f"  {table}: no common columns between source/dest, skipping")
        return 0

    cols_str = ", ".join(common)
    placeholders = ", ".join(["%s"] * len(common))

    src_cur.execute(f"SELECT {cols_str} FROM {table}")
    rows = src_cur.fetchall()

    errors = 0
    for row in rows:
        try:
            adapted = _adapt_row(row, common, src_col_types)
            dst_cur.execute(
                f"INSERT INTO {table} ({cols_str}) VALUES ({placeholders}) ON CONFLICT DO NOTHING",
                adapted,
            )
        except Exception as e:
            errors += 1
            if errors <= 3:
                logger.warning(f"  {table}: insert error: {e}")
    if errors > 3:
        logger.warning(f"  {table}: {errors} total insert errors (showing first 3)")

    dst_cur.execute(f"SELECT COUNT(*) FROM {table}")
    dst_after = dst_cur.fetchone()[0]
    new_rows = dst_after - dst_before

    logger.info(f"  {table}: {src_count} source -> {new_rows} new ({dst_after} total in dest)")
    return new_rows
