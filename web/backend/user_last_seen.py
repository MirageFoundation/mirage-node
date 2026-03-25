from __future__ import annotations

import threading
import time

from flask import g, has_request_context

from db import connect_backend_db
from logging_utils import logger

LAST_SEEN_THROTTLE_SECONDS = 60
LAST_SEEN_CACHE_TTL_SECONDS = 60 * 60
LAST_SEEN_CACHE_MAX = 50000
_last_seen_cache: dict[str, int] = {}
_last_seen_cache_lock = threading.Lock()
_last_seen_cache_last_cleanup = 0


def update_user_last_seen(address: str, source: str = "", ts: int | None = None) -> None:
    addr = str(address or "").strip().lower()
    if not addr or addr == "guest":
        return
    now_ts = int(ts or time.time())
    if has_request_context():
        seen = getattr(g, "user_last_seen_addrs", None)
        if seen is None:
            seen = set()
            g.user_last_seen_addrs = seen
        if addr in seen:
            return
        seen.add(addr)
    if _should_skip_update(addr, now_ts):
        return
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


def _should_skip_update(addr: str, now_ts: int) -> bool:
    global _last_seen_cache_last_cleanup
    with _last_seen_cache_lock:
        last_ts = _last_seen_cache.get(addr)
        if last_ts and now_ts - last_ts < LAST_SEEN_THROTTLE_SECONDS:
            return True
        _last_seen_cache[addr] = now_ts
        if (
            len(_last_seen_cache) > LAST_SEEN_CACHE_MAX
            or now_ts - _last_seen_cache_last_cleanup > LAST_SEEN_CACHE_TTL_SECONDS
        ):
            cutoff = now_ts - LAST_SEEN_CACHE_TTL_SECONDS
            for key, value in list(_last_seen_cache.items()):
                if value < cutoff:
                    _last_seen_cache.pop(key, None)
            _last_seen_cache_last_cleanup = now_ts
    return False
