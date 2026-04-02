from __future__ import annotations

import logging
import os
import time

import psycopg

from shared.config import get_config

logger = logging.getLogger(__name__)

NEW_USER_HIGHLIGHT_DAYS = int(os.environ.get("NEW_USER_HIGHLIGHT_DAYS", "7"))
INBOX_PAYLOAD_CONTENT_MAX = 2000


def is_new_user(profile_created_at: int) -> bool:
    if NEW_USER_HIGHLIGHT_DAYS <= 0 or not profile_created_at:
        return False
    return (int(time.time()) - int(profile_created_at)) <= NEW_USER_HIGHLIGHT_DAYS * 86400


def _truncate_for_payload(text: str, max_len: int = INBOX_PAYLOAD_CONTENT_MAX) -> str:
    if not text or len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def parent_display_text(item_type: str, context_target: str, context_title: str, context_content: str) -> str:
    """Compute parent preview text exactly as /api/get_inbox does."""
    if item_type in ("follow", "donation", "subscription_gift"):
        return ""
    if item_type == "reply":
        if not context_target:
            return context_title or ""
        return context_content or ""
    if item_type == "award":
        return context_title or ""
    return context_title or context_content or ""


def build_inbox_reply(
    *,
    reply_id: str,
    reply_owner: str,
    reply_username: str,
    reply_timestamp: int,
    reply_author_level: int,
    reply_author_created_at: int,
    reply_content: str,
    parent_id: str,
    parent_content: str,
    parent_owner: str,
    root_post_id: str,
    award_type: str,
    item_type: str,
    amount: int | None,
) -> dict:
    """Build an inboxReply dict matching the exact shape returned by /api/get_inbox."""
    ptext = parent_content
    if len(ptext) > 200:
        ptext = ptext[:197] + "..."

    return {
        "reply_id": reply_id,
        "reply_owner": reply_owner,
        "reply_username": reply_username,
        "reply_author_level": reply_author_level,
        "reply_author_is_new": is_new_user(reply_author_created_at),
        "reply_content": _truncate_for_payload(reply_content),
        "reply_timestamp": int(reply_timestamp),
        "parent_id": parent_id,
        "parent_content": ptext,
        "parent_owner": parent_owner,
        "root_post_id": root_post_id,
        "award_type": award_type,
        "type": item_type,
        "amount": amount,
    }


def fetch_inbox_last_viewed_at(address: str, cur=None) -> int:
    if not address or address.lower() == "guest":
        return 0
    viewer = address.lower()
    if cur is None:
        cfg = get_config()
        url = cfg.get_backend_db_url()
        with psycopg.connect(url, autocommit=True) as conn:
            with conn.cursor() as cur_local:
                cur_local.execute(
                    "SELECT inbox_last_viewed_at FROM user_inbox_state WHERE LOWER(owner) = LOWER(%s)",
                    (viewer,),
                )
                row = cur_local.fetchone()
                return int(row[0]) if row and row[0] is not None else 0

    cur.execute(
        "SELECT inbox_last_viewed_at FROM user_inbox_state WHERE LOWER(owner) = LOWER(%s)",
        (viewer,),
    )
    row = cur.fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def follow_event_key(follower: str, target: str, tx_hash: str) -> str:
    follower_lc = str(follower or "").strip().lower()
    target_lc = str(target or "").strip().lower()
    tx_lc = str(tx_hash or "").strip().lower()
    if not follower_lc or not target_lc or not tx_lc:
        raise RuntimeError("follow_event_key requires follower, target, and tx_hash")
    return f"follow:{follower_lc}:{target_lc}:{tx_lc}"


def donation_event_key(sender: str, recipient: str, tx_hash: str) -> str:
    sender_lc = str(sender or "").strip().lower()
    recipient_lc = str(recipient or "").strip().lower()
    tx_lc = str(tx_hash or "").strip().lower()
    if not sender_lc or not recipient_lc or not tx_lc:
        raise RuntimeError("donation_event_key requires sender, recipient, and tx_hash")
    return f"donation:{sender_lc}:{recipient_lc}:{tx_lc}"


def subscription_gift_event_key(gifter: str, recipient: str, tx_hash: str) -> str:
    gifter_lc = str(gifter or "").strip().lower()
    recipient_lc = str(recipient or "").strip().lower()
    tx_lc = str(tx_hash or "").strip().lower()
    if not gifter_lc or not recipient_lc or not tx_lc:
        raise RuntimeError("subscription_gift_event_key requires gifter, recipient, and tx_hash")
    return f"subscription_gift:{gifter_lc}:{recipient_lc}:{tx_lc}"


def record_inbox_event(
    event_key: str,
    recipient: str,
    actor: str,
    event_type: str,
    created_at: int,
    amount: int | None = None,
    tx_hash: str | None = None,
) -> bool:
    if not event_key or not recipient or not actor or not event_type:
        raise RuntimeError("record_inbox_event requires event_key, recipient, actor, and event_type")
    recipient_lc = str(recipient).strip().lower()
    actor_lc = str(actor).strip().lower()
    if not recipient_lc or not actor_lc:
        raise RuntimeError("record_inbox_event requires recipient and actor")
    tx_lc = str(tx_hash or "").strip().lower() or None
    created_at = int(created_at)
    cfg = get_config()
    url = cfg.get_backend_db_url()
    with psycopg.connect(url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO inbox_events (event_key, recipient, actor, event_type, created_at, amount, tx_hash)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (event_key) DO NOTHING
                """,
                (event_key, recipient_lc, actor_lc, event_type, created_at, amount, tx_lc),
            )
            inserted = cur.rowcount == 1
    logger.debug(
        "inbox.event.record key=%s type=%s recipient=%s actor=%s inserted=%s",
        event_key[:80],
        event_type,
        recipient_lc[:16],
        actor_lc[:16],
        inserted,
    )
    return inserted


def _count_inbox_events(address: str, last_seen: int) -> int:
    if not address or address.lower() == "guest":
        return 0
    viewer = address.lower()
    cfg = get_config()
    url = cfg.get_backend_db_url()
    with psycopg.connect(url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) FROM inbox_events
                WHERE LOWER(recipient) = LOWER(%s)
                  AND LOWER(actor) != LOWER(%s)
                  AND created_at > %s
                  AND event_type IN ('follow', 'donation', 'subscription_gift')
                """,
                (viewer, viewer, int(last_seen)),
            )
            row = cur.fetchone()
            return int(row[0]) if row and row[0] is not None else 0


def compute_unread_count(cur, address: str, last_seen: int) -> tuple[int, int]:
    """Compute unread inbox items and return (count, last_seen_ts)."""
    if not address or address.lower() == "guest":
        return 0, 0

    viewer = address.lower()
    last_seen = int(last_seen)

    cur.execute(
        """
        SELECT COUNT(r.txhash)
        FROM profiles pr
        LEFT JOIN posts p ON LOWER(p.owner) = LOWER(pr.owner)
        LEFT JOIN posts r
          ON r.target = p.txhash
         AND LOWER(r.owner) != LOWER(pr.owner)
         AND r.deleted = FALSE
         AND r.created_at > %s
        WHERE LOWER(pr.owner) = %s
        """,
        (last_seen, viewer),
    )
    row = cur.fetchone()
    reply_count = int(row[0]) if row and row[0] else 0

    cur.execute(
        """
        SELECT COUNT(*) FROM mentions m
        JOIN posts p ON p.txhash = m.post_txhash AND p.deleted = FALSE
        WHERE LOWER(m.mentioned_address) = %s
          AND LOWER(m.mentioner_address) != %s
          AND m.created_at > %s
          AND NOT EXISTS (
              SELECT 1 FROM posts tp
              WHERE tp.txhash = p.target
                AND LOWER(tp.owner) = %s
          )
        """,
        (viewer, viewer, last_seen, viewer),
    )
    mrow = cur.fetchone()
    mention_count = int(mrow[0]) if mrow and mrow[0] else 0

    cur.execute(
        """
        SELECT COUNT(*) FROM awards a
        JOIN posts p ON p.txhash = a.target AND p.deleted = FALSE
        WHERE LOWER(p.owner) = %s
          AND LOWER(a.owner) != %s
          AND a.created_at > %s
        """,
        (viewer, viewer, last_seen),
    )
    arow = cur.fetchone()
    award_count = int(arow[0]) if arow and arow[0] else 0

    event_count = _count_inbox_events(viewer, last_seen)
    return reply_count + mention_count + award_count + event_count, last_seen
