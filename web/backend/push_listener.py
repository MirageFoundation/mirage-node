from __future__ import annotations

import threading
import time

from db import connect_backend_db, connect_db
from logging_utils import logger
from settings import PUSH_NOTIFICATIONS_ENABLED
from shared.push import send_push_for_award, send_push_for_mentions, send_push_for_reply
from push_events import award_event_key, mark_push_event_seen, mention_event_key, reply_event_key


PUSH_LISTENER_POLL_SECONDS = 5
PUSH_LISTENER_BATCH_SIZE = 200


def start_push_listener() -> None:
    if not PUSH_NOTIFICATIONS_ENABLED:
        logger().info("push.listener.disabled")
        return
    t = threading.Thread(target=_run_listener, daemon=True)
    t.start()
    logger().info("push.listener.started")


def _run_listener() -> None:
    logger().info("push.listener.run.begin")
    while True:
        processed = _poll_once()
        if processed == 0:
            time.sleep(PUSH_LISTENER_POLL_SECONDS)


def _poll_once() -> int:
    total = 0
    total += _poll_posts()
    total += _poll_awards()
    logger().debug("push.listener.poll total=%d", total)
    return total


def _load_cursor(event_type: str) -> tuple[int, str]:
    with connect_backend_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT last_created_at, last_id FROM push_event_cursor WHERE event_type = %s",
                (event_type,),
            )
            row = cur.fetchone()
            if row:
                return int(row[0]), str(row[1] or "")
            now_ts = int(time.time())
            cur.execute(
                """
                INSERT INTO push_event_cursor (event_type, last_created_at, last_id, updated_at)
                VALUES (%s, 0, '', %s)
                ON CONFLICT (event_type) DO NOTHING
                """,
                (event_type, now_ts),
            )
            return 0, ""


def _update_cursor(event_type: str, last_created_at: int, last_id: str) -> None:
    now_ts = int(time.time())
    with connect_backend_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE push_event_cursor
                SET last_created_at = %s, last_id = %s, updated_at = %s
                WHERE event_type = %s
                """,
                (int(last_created_at), str(last_id or ""), now_ts, event_type),
            )


def _poll_posts() -> int:
    last_ts, last_id = _load_cursor("posts")
    with connect_db(timeout=3.0, busy_timeout_ms=5000) as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                p.txhash,
                p.owner,
                COALESCE(p.content, ''),
                COALESCE(p.target, ''),
                p.created_at,
                COALESCE(pr.username, '')
            FROM posts p
            LEFT JOIN profiles pr ON LOWER(pr.owner) = LOWER(p.owner)
            WHERE p.deleted = FALSE
              AND (p.created_at > %s OR (p.created_at = %s AND p.txhash > %s))
            ORDER BY p.created_at ASC, p.txhash ASC
            LIMIT %s
            """,
            (last_ts, last_ts, last_id, PUSH_LISTENER_BATCH_SIZE),
        )
        rows = cur.fetchall()

    if not rows:
        return 0

    processed = 0
    for txhash, owner, content, target, created_at, username in rows:
        txhash_lc = str(txhash or "").lower()
        owner_lc = str(owner or "").lower()
        if not txhash_lc or not owner_lc:
            continue
        target_hash = str(target or "").strip().lower()
        poster_username = str(username or "").strip()
        content_text = str(content or "")

        if target_hash:
            reply_key = reply_event_key(txhash_lc)
            if mark_push_event_seen(reply_key, "reply", int(created_at or 0)):
                send_push_for_reply(owner_lc, poster_username, target_hash, content_text, txhash_lc)

        mention_key = mention_event_key(txhash_lc)
        if mark_push_event_seen(mention_key, "mention", int(created_at or 0)):
            send_push_for_mentions(owner_lc, poster_username, content_text, txhash_lc, target_hash)

        processed += 1
        last_ts = int(created_at or last_ts)
        last_id = txhash_lc

    _update_cursor("posts", last_ts, last_id)
    logger().debug("push.listener.posts processed=%d last_ts=%d", processed, last_ts)
    return processed


def _poll_awards() -> int:
    last_ts, last_id = _load_cursor("awards")
    last_award_id = int(last_id or 0)
    with connect_db(timeout=3.0, busy_timeout_ms=5000) as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                a.id,
                a.owner,
                a.target,
                a.award_type,
                a.created_at,
                COALESCE(pr.username, ''),
                p.owner AS post_owner
            FROM awards a
            JOIN posts p ON LOWER(p.txhash) = LOWER(a.target)
            LEFT JOIN profiles pr ON LOWER(pr.owner) = LOWER(a.owner)
            WHERE a.created_at > %s OR (a.created_at = %s AND a.id > %s)
            ORDER BY a.created_at ASC, a.id ASC
            LIMIT %s
            """,
            (last_ts, last_ts, last_award_id, PUSH_LISTENER_BATCH_SIZE),
        )
        rows = cur.fetchall()

    if not rows:
        return 0

    processed = 0
    for award_id, owner, target, award_type, created_at, username, post_owner in rows:
        owner_lc = str(owner or "").lower()
        target_lc = str(target or "").lower()
        post_owner_lc = str(post_owner or "").lower()
        if not owner_lc or not target_lc or not post_owner_lc:
            continue
        award_key = award_event_key(owner_lc, target_lc)
        if mark_push_event_seen(award_key, "award", int(created_at or 0)):
            awarder_username = str(username or "").strip()
            send_push_for_award(owner_lc, awarder_username, post_owner_lc, target_lc, str(award_type or ""))

        processed += 1
        last_ts = int(created_at or last_ts)
        last_award_id = int(award_id or last_award_id)

    _update_cursor("awards", last_ts, str(last_award_id))
    logger().debug("push.listener.awards processed=%d last_ts=%d", processed, last_ts)
    return processed
