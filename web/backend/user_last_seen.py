from __future__ import annotations

import time

from db import connect_backend_db
from logging_utils import logger


def update_user_last_seen(address: str, source: str = "", ts: int | None = None) -> None:
    addr = str(address or "").strip().lower()
    if not addr or addr == "guest":
        return
    now_ts = int(ts or time.time())
    with connect_backend_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO user_last_seen (owner, last_seen_at)
                VALUES (%s, %s)
                ON CONFLICT (owner) DO UPDATE SET last_seen_at = EXCLUDED.last_seen_at
                """,
                (addr, now_ts),
            )
    if source:
        logger().debug("user_last_seen.update addr=%s ts=%d source=%s", addr[:16], now_ts, source)
    else:
        logger().debug("user_last_seen.update addr=%s ts=%d", addr[:16], now_ts)
