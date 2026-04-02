from __future__ import annotations

import fcntl
import json
import os
import threading
import time

from db import connect_backend_db, connect_db
from logging_utils import logger
from settings import require_bool_env
from shared.inbox import donation_event_key, record_inbox_event
from shared.push import (
    send_push_for_award,
    send_push_for_donation,
    send_push_for_follow,
    send_push_for_mentions,
    send_push_for_reply,
    send_push_for_subscription_gift,
    _extract_mentions,
)
from push_events import award_event_key, mark_push_event_seen, mention_event_key, reply_event_key


PUSH_LISTENER_POLL_SECONDS = 5
PUSH_LISTENER_BATCH_SIZE = 200
PUSH_LISTENER_LOCK_PATH = os.environ.get("PUSH_LISTENER_LOCK_PATH", "/tmp/mirage_push_listener.lock")
PUSH_EVENT_SEEN_TTL_SECONDS = 7 * 24 * 60 * 60
PUSH_EVENT_SEEN_CLEANUP_INTERVAL = 60 * 60
PUSH_EVENT_SEEN_CLEANUP_BATCH = 5000
_last_seen_cleanup_ts = 0.0
_listener_lock_fp = None


def _acquire_listener_lock() -> bool:
    global _listener_lock_fp
    lock_path = PUSH_LISTENER_LOCK_PATH
    fp = open(lock_path, "w")
    try:
        fcntl.flock(fp, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        fp.close()
        return False
    _listener_lock_fp = fp
    return True


def start_push_listener() -> None:
    if not require_bool_env("PUSH_NOTIFICATIONS_ENABLED"):
        logger().info("push.listener.disabled")
        return
    if not _acquire_listener_lock():
        logger().info("push.listener.skipped lock_unavailable")
        return
    t = threading.Thread(target=_run_listener, daemon=True)
    t.start()
    logger().info("push.listener.started")


def _run_listener() -> None:
    logger().info("push.listener.run.begin")
    while True:
        try:
            processed = _poll_once()
        except Exception as exc:
            logger().error("push.listener.poll_err %s", exc)
            time.sleep(PUSH_LISTENER_POLL_SECONDS)
            continue
        if processed == 0:
            time.sleep(PUSH_LISTENER_POLL_SECONDS)


def _poll_once() -> int:
    total = 0
    total += _poll_posts()
    total += _poll_awards()
    total += _poll_send_tokens()
    total += _poll_inbox_events()
    _maybe_cleanup_seen()
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
            last_created_at, last_id = _bootstrap_cursor(event_type)
            now_ts = int(time.time())
            cur.execute(
                """
                INSERT INTO push_event_cursor (event_type, last_created_at, last_id, updated_at)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (event_type) DO NOTHING
                """,
                (event_type, int(last_created_at), str(last_id or ""), now_ts),
            )
            return int(last_created_at), str(last_id or "")


def _bootstrap_cursor(event_type: str) -> tuple[int, str]:
    if event_type == "posts":
        with connect_db(timeout=3.0, busy_timeout_ms=5000) as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT created_at, txhash
                FROM posts
                WHERE deleted = FALSE
                ORDER BY created_at DESC, txhash DESC
                LIMIT 1
                """
            )
            row = cur.fetchone()
        if row:
            return int(row[0]), str(row[1])
        return 0, ""
    if event_type == "awards":
        with connect_db(timeout=3.0, busy_timeout_ms=5000) as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT created_at, id
                FROM awards
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """
            )
            row = cur.fetchone()
        if row:
            return int(row[0] or 0), str(row[1] or "")
        return 0, ""
    if event_type == "send_tokens":
        with connect_db(timeout=3.0, busy_timeout_ms=5000) as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT created_at, txhash
                FROM tx_index
                ORDER BY created_at DESC, txhash DESC
                LIMIT 1
                """
            )
            row = cur.fetchone()
        if row:
            return int(row[0] or 0), str(row[1] or "")
        return 0, ""
    if event_type == "inbox_events":
        with connect_backend_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT created_at, event_key
                    FROM inbox_events
                    WHERE event_type IN ('follow', 'subscription_gift')
                    ORDER BY created_at DESC, event_key DESC
                    LIMIT 1
                    """
                )
                row = cur.fetchone()
        if row:
            return int(row[0] or 0), str(row[1] or "")
        return 0, ""
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

        created_ts = int(created_at or 0)

        if target_hash:
            reply_key = reply_event_key(txhash_lc)
            if mark_push_event_seen(reply_key, "reply", created_ts):
                send_push_for_reply(
                    owner_lc, poster_username, target_hash, content_text, txhash_lc, created_at=created_ts
                )

        if _extract_mentions(content_text):
            mention_key = mention_event_key(txhash_lc)
            if mark_push_event_seen(mention_key, "mention", created_ts):
                send_push_for_mentions(
                    owner_lc, poster_username, content_text, txhash_lc, target_hash, created_at=created_ts
                )

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
        created_ts = int(created_at or 0)
        award_key = award_event_key(owner_lc, target_lc)
        if mark_push_event_seen(award_key, "award", created_ts):
            awarder_username = str(username or "").strip()
            send_push_for_award(
                owner_lc, awarder_username, post_owner_lc, target_lc, str(award_type or ""), created_at=created_ts
            )

        processed += 1
        last_ts = int(created_at or last_ts)
        last_award_id = int(award_id or last_award_id)

    _update_cursor("awards", last_ts, str(last_award_id))
    logger().debug("push.listener.awards processed=%d last_ts=%d", processed, last_ts)
    return processed


def _get_username_for_owner(owner: str, cache: dict[str, str]) -> str:
    if owner is None:
        return ""
    owner_lc = str(owner).strip().lower()
    if not owner_lc:
        return ""
    if owner_lc in cache:
        return cache[owner_lc]
    with connect_db(timeout=3.0, busy_timeout_ms=5000) as conn:
        cur = conn.cursor()
        cur.execute("SELECT username FROM profiles WHERE LOWER(owner) = LOWER(%s) LIMIT 1", (owner_lc,))
        row = cur.fetchone()
    if not row or not row[0]:
        cache[owner_lc] = ""
        return ""
    username = str(row[0]).strip()
    cache[owner_lc] = username
    return username


def _event_attrs(event: dict) -> dict[str, str]:
    attrs = event.get("attributes")
    if not isinstance(attrs, list):
        return {}
    out: dict[str, str] = {}
    for attr in attrs:
        if not isinstance(attr, dict):
            continue
        key = attr.get("key")
        value = attr.get("value")
        if key is None or value is None:
            continue
        out[str(key)] = str(value)
    return out


def _extract_action(events: list[dict]) -> str:
    for event in events:
        if event.get("type") == "message":
            attrs = _event_attrs(event)
            action = attrs.get("action")
            if action:
                return str(action)
    return ""


def _is_send_tokens_action(action: str) -> bool:
    value = str(action).strip()
    if not value:
        return False
    return value in {
        "/mirage.core.v1.MsgSendTokens",
        "mirage.core.v1.MsgSendTokens",
        "send_tokens",
        "SendTokens",
    }


def _parse_umirage_amount(amount_str: str, tx_hash: str) -> int:
    if amount_str is None:
        raise RuntimeError(f"send_tokens amount missing in log tx={tx_hash}")
    raw = str(amount_str).strip()
    if not raw:
        raise RuntimeError(f"send_tokens amount missing in log tx={tx_hash}")
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    for part in parts:
        if part.endswith("umirage"):
            num = part[: -len("umirage")]
            if not num.isdigit():
                raise RuntimeError(f"send_tokens amount malformed in log tx={tx_hash}")
            amount = int(num)
            if amount <= 0:
                raise RuntimeError(f"send_tokens amount invalid in log tx={tx_hash}")
            return amount
    raise RuntimeError(f"send_tokens amount missing umirage denom tx={tx_hash}")


def _extract_send_tokens_transfers(raw_log: str, tx_hash: str) -> list[dict]:
    if raw_log is None or raw_log == "":
        raise RuntimeError(f"send_tokens raw_log missing tx={tx_hash}")
    try:
        parsed = json.loads(raw_log)
    except Exception as exc:
        raise RuntimeError(f"send_tokens raw_log invalid json tx={tx_hash}") from exc
    if not isinstance(parsed, list):
        raise RuntimeError(f"send_tokens raw_log unexpected format tx={tx_hash}")
    transfers: list[dict] = []
    for entry in parsed:
        if not isinstance(entry, dict):
            continue
        events = entry.get("events")
        if not isinstance(events, list):
            continue
        action = _extract_action(events)
        if not _is_send_tokens_action(action):
            continue
        transfer_events = [ev for ev in events if isinstance(ev, dict) and ev.get("type") == "transfer"]
        if not transfer_events:
            raise RuntimeError(f"send_tokens transfer event missing tx={tx_hash}")
        for ev in transfer_events:
            attrs = _event_attrs(ev)
            sender = attrs.get("sender")
            recipient = attrs.get("recipient")
            if not recipient:
                recipient = attrs.get("receiver")
            amount_str = attrs.get("amount")
            if not sender or not recipient or not amount_str:
                raise RuntimeError(f"send_tokens transfer missing fields tx={tx_hash}")
            amount = _parse_umirage_amount(amount_str, tx_hash)
            transfers.append(
                {
                    "sender": str(sender).strip().lower(),
                    "recipient": str(recipient).strip().lower(),
                    "amount": amount,
                }
            )
    return transfers


def _poll_send_tokens() -> int:
    last_ts, last_id = _load_cursor("send_tokens")
    with connect_db(timeout=3.0, busy_timeout_ms=5000) as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT txhash, tx_type, raw_log, created_at
            FROM tx_index
            WHERE code = 0
              AND (created_at > %s OR (created_at = %s AND txhash > %s))
              AND tx_type IN ('send_tokens', 'multi')
            ORDER BY created_at ASC, txhash ASC
            LIMIT %s
            """,
            (last_ts, last_ts, last_id, PUSH_LISTENER_BATCH_SIZE),
        )
        rows = cur.fetchall()

    if not rows:
        return 0

    processed = 0
    username_cache: dict[str, str] = {}
    for txhash, tx_type, raw_log, created_at in rows:
        if txhash is None:
            raise RuntimeError("send_tokens tx_index row missing txhash")
        txhash_lc = str(txhash).strip().lower()
        if not txhash_lc:
            raise RuntimeError("send_tokens tx_index row missing txhash")
        created_ts = int(created_at)
        transfers = _extract_send_tokens_transfers(raw_log, txhash_lc)
        if not transfers:
            if str(tx_type).strip().lower() == "send_tokens":
                raise RuntimeError(f"send_tokens log missing transfer tx={txhash_lc}")
            logger().debug("push.listener.send_tokens.skip tx=%s type=%s", txhash_lc[:16], tx_type)
            processed += 1
            last_ts = created_ts
            last_id = txhash_lc
            continue
        for transfer in transfers:
            sender = transfer["sender"]
            recipient = transfer["recipient"]
            amount = int(transfer["amount"])
            if sender == recipient:
                continue
            event_key = donation_event_key(sender, recipient, txhash_lc)
            inserted = record_inbox_event(
                event_key=event_key,
                recipient=recipient,
                actor=sender,
                event_type="donation",
                created_at=created_ts,
                amount=amount,
                tx_hash=txhash_lc,
            )
            logger().debug(
                "push.listener.send_tokens.event sender=%s recipient=%s amount=%s inserted=%s tx=%s",
                sender[:16],
                recipient[:16],
                amount,
                inserted,
                txhash_lc[:16],
            )
            if inserted:
                sender_username = _get_username_for_owner(sender, username_cache)
                if mark_push_event_seen(event_key, "donation", created_ts):
                    send_push_for_donation(
                        sender,
                        sender_username,
                        recipient,
                        amount,
                        event_key=event_key,
                        created_at=created_ts,
                    )
                from routes.public import _invalidate_inbox_cache

                _invalidate_inbox_cache(recipient)
        processed += 1
        last_ts = created_ts
        last_id = txhash_lc

    _update_cursor("send_tokens", last_ts, last_id)
    logger().debug("push.listener.send_tokens processed=%d last_ts=%d", processed, last_ts)
    return processed


def _poll_inbox_events() -> int:
    """Poll inbox_events for follow and subscription_gift events that need pushes."""
    last_ts, last_id = _load_cursor("inbox_events")
    with connect_backend_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT event_key, recipient, actor, event_type, created_at, amount, tx_hash
                FROM inbox_events
                WHERE event_type IN ('follow', 'subscription_gift')
                  AND (created_at > %s OR (created_at = %s AND event_key > %s))
                ORDER BY created_at ASC, event_key ASC
                LIMIT %s
                """,
                (last_ts, last_ts, last_id, PUSH_LISTENER_BATCH_SIZE),
            )
            rows = cur.fetchall()

    if not rows:
        return 0

    processed = 0
    username_cache: dict[str, str] = {}
    for event_key, recipient, actor, event_type, created_at, amount, tx_hash in rows:
        event_key_str = str(event_key or "").strip()
        recipient_lc = str(recipient or "").strip().lower()
        actor_lc = str(actor or "").strip().lower()
        event_type_str = str(event_type or "").strip()
        created_ts = int(created_at or 0)

        if not event_key_str or not recipient_lc or not actor_lc:
            processed += 1
            last_ts = created_ts
            last_id = event_key_str
            continue

        if actor_lc == recipient_lc:
            processed += 1
            last_ts = created_ts
            last_id = event_key_str
            continue

        push_seen_key = f"inbox_event:{event_key_str}"
        should_send = mark_push_event_seen(push_seen_key, event_type_str, created_ts)
        if should_send:
            actor_username = _get_username_for_owner(actor_lc, username_cache)
            if event_type_str == "follow":
                send_push_for_follow(
                    actor_lc,
                    actor_username,
                    recipient_lc,
                    event_key=event_key_str,
                    created_at=created_ts,
                )
            elif event_type_str == "subscription_gift":
                gift_level = int(amount) if amount is not None else 0
                if gift_level <= 0:
                    raise RuntimeError(f"subscription_gift missing level event_key={event_key_str}")
                recipient_level = 0
                with connect_db(timeout=3.0, busy_timeout_ms=5000) as iconn:
                    icur = iconn.cursor()
                    icur.execute(
                        "SELECT COALESCE(level, 0) FROM profiles WHERE LOWER(owner) = LOWER(%s) LIMIT 1",
                        (recipient_lc,),
                    )
                    lrow = icur.fetchone()
                    if lrow:
                        recipient_level = int(lrow[0] or 0)
                was_subscriber = recipient_level >= 1
                logger().debug(
                    "push.listener.subscription_gift level=%s was_subscriber=%s recipient=%s",
                    gift_level,
                    was_subscriber,
                    recipient_lc[:16],
                )
                send_push_for_subscription_gift(
                    actor_lc,
                    actor_username,
                    recipient_lc,
                    level=gift_level,
                    was_subscriber=was_subscriber,
                    event_key=event_key_str,
                    created_at=created_ts,
                )

        from routes.public import _invalidate_inbox_cache

        _invalidate_inbox_cache(recipient_lc)

        processed += 1
        last_ts = created_ts
        last_id = event_key_str

    _update_cursor("inbox_events", last_ts, last_id)
    logger().debug("push.listener.inbox_events processed=%d last_ts=%d", processed, last_ts)
    return processed


def _maybe_cleanup_seen() -> None:
    global _last_seen_cleanup_ts
    now = time.time()
    if now - _last_seen_cleanup_ts < PUSH_EVENT_SEEN_CLEANUP_INTERVAL:
        return
    _last_seen_cleanup_ts = now
    cutoff = int(now) - PUSH_EVENT_SEEN_TTL_SECONDS
    with connect_backend_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM push_event_seen
                WHERE ctid IN (
                    SELECT ctid FROM push_event_seen
                    WHERE created_at < %s
                    LIMIT %s
                )
                """,
                (cutoff, PUSH_EVENT_SEEN_CLEANUP_BATCH),
            )
            deleted = cur.rowcount
    logger().debug("push.listener.cleanup deleted=%d cutoff=%d", deleted, cutoff)
