from __future__ import annotations

import json
import time

from db import connect_backend_db
from logging_utils import logger

# A push is worth retrying briefly (Expo blip, indexer lag on the context read),
# never for hours: a notification that lands long after the event is noise, so
# stale or exhausted rows go terminal instead of retrying forever.
PUSH_OUTBOX_MAX_ATTEMPTS = 5
PUSH_OUTBOX_MAX_AGE_SECONDS = 30 * 60
PUSH_OUTBOX_BASE_BACKOFF_SECONDS = 30
PUSH_OUTBOX_MAX_BACKOFF_SECONDS = 15 * 60
PUSH_OUTBOX_LEASE_SECONDS = 120


def reply_event_key(tx_hash: str) -> str:
    return f"reply:{str(tx_hash or '').strip().lower()}"


def mention_event_key(tx_hash: str, username: str = "") -> str:
    tx_lc = str(tx_hash or "").strip().lower()
    username_lc = str(username or "").strip().lower()
    return f"mention:{tx_lc}:{username_lc}" if username_lc else f"mention:{tx_lc}"


def award_event_key(awarder: str, target_txhash: str) -> str:
    awarder_lc = str(awarder or "").strip().lower()
    target_lc = str(target_txhash or "").strip().lower()
    return f"award:{awarder_lc}:{target_lc}"


def enqueue_push_event(cur, event_key: str, event_type: str, payload: dict, ts: int) -> bool:
    """Queue one push for later delivery. Runs on the caller's cursor so the
    enqueue commits with the cursor advance that produced it."""
    if not event_key or not event_type:
        raise RuntimeError("enqueue_push_event requires event_key and event_type")
    if not isinstance(payload, dict):
        raise RuntimeError("enqueue_push_event requires an object payload")
    now_ts = int(ts)
    cur.execute(
        """
        INSERT INTO push_event_seen (
            event_key, event_type, created_at, payload, status, attempts, next_attempt_at
        )
        VALUES (%s, %s, %s, %s, 'pending', 0, %s)
        ON CONFLICT (event_key) DO NOTHING
        """,
        (event_key, event_type, now_ts, json.dumps(payload), now_ts),
    )
    inserted = cur.rowcount == 1
    logger().debug(
        "push.outbox.enqueue key=%s type=%s inserted=%s",
        event_key[:80],
        event_type,
        inserted,
    )
    return inserted


def fetch_due_push_events(limit: int, now_ts: int | None = None) -> list[dict]:
    """Lease a batch of due rows. Pushing `next_attempt_at` forward as part of
    the read means a worker that dies mid-delivery releases its rows on the
    lease instead of letting a second worker notify the same user twice."""
    now = int(now_ts or time.time())
    with connect_backend_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE push_event_seen
                SET next_attempt_at = %s
                WHERE event_key IN (
                    SELECT event_key
                    FROM push_event_seen
                    WHERE status = 'pending' AND next_attempt_at <= %s
                    ORDER BY next_attempt_at ASC, created_at ASC
                    LIMIT %s
                    FOR UPDATE SKIP LOCKED
                )
                RETURNING event_key, event_type, payload, attempts, created_at
                """,
                (now + PUSH_OUTBOX_LEASE_SECONDS, now, int(limit)),
            )
            rows = cur.fetchall()
    out: list[dict] = []
    for event_key, event_type, payload, attempts, created_at in rows:
        if not isinstance(payload, dict):
            raise RuntimeError(f"push outbox row has no payload event_key={event_key}")
        out.append(
            {
                "event_key": str(event_key),
                "event_type": str(event_type),
                "payload": payload,
                "attempts": int(attempts),
                "created_at": int(created_at),
            }
        )
    return out


def _settle_push_event(event_key: str, status: str, error: str, now_ts: int) -> None:
    with connect_backend_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE push_event_seen
                SET status = %s, completed_at = %s, last_error = %s
                WHERE event_key = %s AND status = 'pending'
                """,
                (status, now_ts, error or None, event_key),
            )
            updated = cur.rowcount
    if updated != 1:
        raise RuntimeError(f"push outbox settle lost pending row event_key={event_key}")


def mark_push_event_sent(event_key: str, now_ts: int | None = None) -> None:
    now = int(now_ts or time.time())
    _settle_push_event(event_key, "sent", "", now)
    logger().debug("push.outbox.sent key=%s", event_key[:80])


def mark_push_event_discarded(event_key: str, reason: str, now_ts: int | None = None) -> None:
    now = int(now_ts or time.time())
    _settle_push_event(event_key, "discarded", reason, now)
    logger().debug("push.outbox.discarded key=%s reason=%s", event_key[:80], reason)


def reschedule_push_event(
    event_key: str,
    attempts: int,
    created_at: int,
    error: str,
    now_ts: int | None = None,
) -> bool:
    """Back off one failed delivery. Returns False once the row goes terminal."""
    now = int(now_ts or time.time())
    next_attempts = int(attempts) + 1
    exhausted = next_attempts >= PUSH_OUTBOX_MAX_ATTEMPTS or (now - int(created_at)) >= PUSH_OUTBOX_MAX_AGE_SECONDS
    if exhausted:
        with connect_backend_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE push_event_seen
                    SET status = 'failed', attempts = %s, completed_at = %s, last_error = %s
                    WHERE event_key = %s AND status = 'pending'
                    """,
                    (next_attempts, now, error or None, event_key),
                )
                updated = cur.rowcount
        if updated != 1:
            raise RuntimeError(f"push outbox exhaustion lost pending row event_key={event_key}")
        logger().error(
            "push.outbox.exhausted key=%s attempts=%d age=%d error=%s",
            event_key[:80],
            next_attempts,
            now - int(created_at),
            error,
        )
        return False

    delay = min(
        PUSH_OUTBOX_BASE_BACKOFF_SECONDS * (2 ** (next_attempts - 1)),
        PUSH_OUTBOX_MAX_BACKOFF_SECONDS,
    )
    with connect_backend_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE push_event_seen
                SET attempts = %s, next_attempt_at = %s, last_error = %s
                WHERE event_key = %s AND status = 'pending'
                """,
                (next_attempts, now + delay, error or None, event_key),
            )
            updated = cur.rowcount
    if updated != 1:
        raise RuntimeError(f"push outbox retry lost pending row event_key={event_key}")
    logger().debug(
        "push.outbox.retry key=%s attempts=%d delay=%d error=%s",
        event_key[:80],
        next_attempts,
        delay,
        error,
    )
    return True
