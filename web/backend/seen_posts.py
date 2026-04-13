from __future__ import annotations

import re
import threading
import time

from db import connect_backend_db
from logging_utils import logger

SEEN_CACHE_TTL_SECONDS = 120
SEEN_CACHE_MAX_USERS = 10_000
SEEN_PER_USER_LIMIT = 1000
SEEN_MAX_BATCH = 100
_VALID_REASONS = frozenset({"open", "dwell", "glance", "vote", "reply", "view"})
_POST_ID_RE = re.compile(r"^[0-9a-f]{64}$")

_seen_cache: dict[str, tuple[dict[str, int], float]] = {}
_seen_cache_lock = threading.Lock()
_cleanup_counter = 0


def normalize_post_id(pid: str) -> str:
    raw = (pid or "").strip().lower()
    if not raw:
        return ""
    if _POST_ID_RE.match(raw):
        return raw
    return ""


def get_seen_map(owner: str) -> dict[str, int]:
    """Return {post_id: view_count} for the user (cached)."""
    addr = (owner or "").strip().lower()
    if not addr or addr == "guest":
        return {}

    now = time.time()
    with _seen_cache_lock:
        entry = _seen_cache.get(addr)
        if entry and (now - entry[1]) < SEEN_CACHE_TTL_SECONDS:
            return dict(entry[0])

    seen = _load_seen_from_db(addr)
    with _seen_cache_lock:
        _seen_cache[addr] = (seen, time.time())
        _maybe_evict_cache()
    logger().debug("seen_posts.cache_miss addr=%s count=%d", addr[:12], len(seen))
    return dict(seen)


def ingest_seen_batch(owner: str, seen_entries: list[tuple[str, str]] | list[str], reason: str = "view") -> int:
    """Bulk-insert seen post IDs. Returns count of IDs accepted."""
    addr = (owner or "").strip().lower()
    if not addr or addr == "guest":
        return 0
    if reason not in _VALID_REASONS:
        reason = "view"

    normalized: list[tuple[str, str]] = []
    for raw in (seen_entries or [])[:SEEN_MAX_BATCH]:
        if isinstance(raw, tuple):
            pid_raw, raw_reason = raw
        else:
            pid_raw, raw_reason = raw, reason
        pid = normalize_post_id(pid_raw)
        raw_reason = str(raw_reason or "").strip().lower()
        final_reason = raw_reason if raw_reason in _VALID_REASONS else reason
        if pid:
            normalized.append((pid, final_reason))
    if not normalized:
        return 0

    now_ts = int(time.time())
    with connect_backend_db() as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                args = [(addr, pid, now_ts, entry_reason) for pid, entry_reason in normalized]
                cur.executemany(
                    """
                    INSERT INTO user_seen_posts (owner, post_id, seen_at, reason)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (owner, post_id) DO UPDATE SET
                        view_count = user_seen_posts.view_count + 1,
                        seen_at = EXCLUDED.seen_at,
                        reason = EXCLUDED.reason
                    """,
                    args,
                )
                cur.execute(
                    """
                    DELETE FROM user_seen_posts
                    WHERE owner = %s AND post_id IN (
                        SELECT post_id FROM user_seen_posts
                        WHERE owner = %s
                        ORDER BY seen_at DESC
                        OFFSET %s
                    )
                    """,
                    (addr, addr, SEEN_PER_USER_LIMIT),
                )

    with _seen_cache_lock:
        entry = _seen_cache.get(addr)
        if entry:
            updated = dict(entry[0])
            for pid, _ in normalized:
                updated[pid] = updated.get(pid, 0) + 1
            _seen_cache[addr] = (updated, time.time())

    logger().debug(
        "seen_posts.ingest addr=%s batch=%d",
        addr[:12], len(normalized),
    )
    return len(normalized)


def cleanup_old_seen(owner: str | None = None) -> int:
    """Trim entries beyond SEEN_PER_USER_LIMIT (per user)."""
    removed = 0

    with connect_backend_db() as conn:
        with conn.cursor() as cur:
            if owner:
                addr = owner.strip().lower()
                cur.execute(
                    """
                    DELETE FROM user_seen_posts WHERE owner = %s AND post_id IN (
                        SELECT post_id FROM user_seen_posts
                        WHERE owner = %s
                        ORDER BY seen_at DESC
                        OFFSET %s
                    )
                    """,
                    (addr, addr, SEEN_PER_USER_LIMIT),
                )
                removed += cur.rowcount

    if removed > 0:
        logger().debug("seen_posts.cleanup owner=%s removed=%d", (owner or "all")[:12], removed)
    return removed


def parse_seen_param(raw: str) -> list[tuple[str, str]]:
    """Parse the `seen` query param (comma-separated `id:reason` entries)."""
    if not raw or not isinstance(raw, str):
        return []
    parts = raw.split(",")
    result: list[tuple[str, str]] = []
    for p in parts[:SEEN_MAX_BATCH]:
        raw_id, raw_reason = (p.split(":", 1) + ["view"])[:2]
        pid = normalize_post_id(raw_id)
        raw_reason = str(raw_reason or "").strip().lower()
        reason = raw_reason if raw_reason in _VALID_REASONS else "view"
        if pid:
            result.append((pid, reason))
    return result


def _load_seen_from_db(addr: str) -> dict[str, int]:
    with connect_backend_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT post_id, view_count FROM user_seen_posts WHERE owner = %s ORDER BY seen_at DESC LIMIT %s",
                (addr, SEEN_PER_USER_LIMIT),
            )
            return {row[0]: row[1] for row in cur.fetchall()}


def _maybe_evict_cache() -> None:
    global _cleanup_counter
    _cleanup_counter += 1
    if len(_seen_cache) <= SEEN_CACHE_MAX_USERS and _cleanup_counter < 100:
        return
    _cleanup_counter = 0
    now = time.time()
    expired = [k for k, (_, ts) in _seen_cache.items() if now - ts > SEEN_CACHE_TTL_SECONDS]
    for k in expired:
        _seen_cache.pop(k, None)
    if len(_seen_cache) > SEEN_CACHE_MAX_USERS:
        by_age = sorted(_seen_cache.items(), key=lambda x: x[1][1])
        to_remove = len(_seen_cache) - SEEN_CACHE_MAX_USERS
        for k, _ in by_age[:to_remove]:
            _seen_cache.pop(k, None)
