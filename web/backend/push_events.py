from __future__ import annotations

import time

from db import connect_backend_db
from logging_utils import logger


def reply_event_key(tx_hash: str) -> str:
    return f"reply:{str(tx_hash or '').strip().lower()}"


def mention_event_key(tx_hash: str) -> str:
    return f"mention:{str(tx_hash or '').strip().lower()}"


def award_event_key(awarder: str, target_txhash: str) -> str:
    awarder_lc = str(awarder or "").strip().lower()
    target_lc = str(target_txhash or "").strip().lower()
    return f"award:{awarder_lc}:{target_lc}"


def mark_push_event_seen(event_key: str, event_type: str, ts: int | None = None) -> bool:
    if not event_key or not event_type:
        return False
    now_ts = int(ts or time.time())
    with connect_backend_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO push_event_seen (event_key, event_type, created_at)
                VALUES (%s, %s, %s)
                ON CONFLICT (event_key) DO NOTHING
                """,
                (event_key, event_type, now_ts),
            )
            inserted = cur.rowcount == 1
    logger().debug(
        "push.event_seen key=%s type=%s inserted=%s",
        event_key[:80],
        event_type,
        inserted,
    )
    return inserted
