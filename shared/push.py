"""
Expo push notification sender with sliding-window throttle and receipt processing.

Used by backend only; no cron or background workers.
Throttle: max 5 pushes per user per 30 minutes.  When throttled, suppressed
events are counted and a single summary push ("You have N unread messages")
is sent once the window expires. After a summary, pushes pause for 3 hours
or until the inbox is viewed.

Self-contained: reads backend + indexer DB URLs from shared.config.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from decimal import Decimal
from typing import Optional

import psycopg
import requests as http_requests

from shared.config import get_config
from shared.inbox import compute_unread_count, fetch_inbox_last_viewed_at

logger = logging.getLogger(__name__)

PUSH_NOTIFICATIONS_ENABLED: bool = os.environ.get("PUSH_NOTIFICATIONS_ENABLED", "").strip().lower() == "true"
EXPO_ACCESS_TOKEN: str = os.environ.get("EXPO_ACCESS_TOKEN", "")


def _connect_backend_db() -> psycopg.Connection:
    cfg = get_config()
    url = cfg.get_backend_db_url()
    return psycopg.connect(url, autocommit=True)


def _connect_indexer_ro() -> psycopg.Connection:
    cfg = get_config()
    url = cfg.get_indexer_ro_url()
    return psycopg.connect(url, autocommit=True)


EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"
EXPO_RECEIPTS_URL = "https://exp.host/--/api/v2/push/getReceipts"
THROTTLE_WINDOW_SECONDS = 30 * 60
THROTTLE_MAX_SENDS = 5
SUMMARY_COOLDOWN_SECONDS = 3 * 60 * 60
MAX_MENTION_PUSHES = 10
_MENTION_RE = re.compile(r"(?<!\w)@([A-Za-z0-9-]+)")
_FENCED_CODE_RE = re.compile(r"```[\s\S]*?```")
_INLINE_CODE_RE = re.compile(r"`[^`]+`")
RECEIPT_CHECK_AGE_SECONDS = 15 * 60
RECEIPT_CHECK_MIN_INTERVAL_SECONDS = 5 * 60
_last_receipt_check_ts = 0.0
_receipt_check_lock = threading.Lock()
_last_summary_flush_ts = 0.0
_summary_flush_lock = threading.Lock()


def _expo_headers() -> dict:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if EXPO_ACCESS_TOKEN:
        headers["Authorization"] = f"Bearer {EXPO_ACCESS_TOKEN}"
    return headers


def _build_expo_message(token: str, title: str, body: str, data: dict) -> dict:
    return {
        "to": token,
        "title": title,
        "body": body,
        "data": data,
        "sound": "default",
        "channelId": "inbox",
    }


def _send_expo_push_batch(messages: list[dict]) -> list[tuple[str, Optional[str]]]:
    """Send a batch of pushes via Expo. Returns list of (token, ticket_id)."""
    if not messages:
        return []
    try:
        resp = http_requests.post(EXPO_PUSH_URL, json=messages, headers=_expo_headers(), timeout=10)
        if resp.status_code != 200:
            logger.warning("[Push] Expo returned %d: %s", resp.status_code, resp.text[:200])
            return []
        result = resp.json()
        tickets = result.get("data", [])
        if not isinstance(tickets, list):
            logger.warning("[Push] Expo unexpected response: %s", str(result)[:200])
            return []
        if len(tickets) != len(messages):
            logger.warning("[Push] Expo ticket count mismatch: %d vs %d", len(tickets), len(messages))
        out: list[tuple[str, Optional[str]]] = []
        for msg, ticket in zip(messages, tickets):
            token = msg.get("to", "")
            if ticket.get("status") == "ok":
                out.append((token, ticket.get("id")))
            else:
                if ticket.get("details", {}).get("error") == "DeviceNotRegistered":
                    _remove_token(token)
                logger.warning("[Push] Expo ticket error: %s", ticket)
        return out
    except Exception as e:
        logger.error("[Push] Failed to send: %s", e)
        return []


def _remove_token(token: str) -> None:
    try:
        with _connect_backend_db() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM push_tokens WHERE token = %s", (token,))
        logger.info("[Push] Removed invalid token: %s…", token[:20])
    except Exception as e:
        logger.error("[Push] Failed to remove token: %s", e)


def _try_throttle_send(owner: str) -> bool:
    """Try to claim a send slot in the current 30-min window.

    If the window has expired **and** there are no pending suppressed events,
    resets the window and allows the send.  If suppressed events are still
    pending (summary hasn't been flushed yet), the new event is added to the
    suppressed count instead so the summary accurately reflects all missed
    events.
    """
    owner_lower = owner.lower()
    now = int(time.time())
    with _connect_backend_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT window_start, sent_count, suppressed_count, cooldown_until FROM push_throttle WHERE owner = %s",
                (owner_lower,),
            )
            row = cur.fetchone()
            if row is None:
                cur.execute(
                    "INSERT INTO push_throttle (owner, window_start, sent_count, suppressed_count, cooldown_until) "
                    "VALUES (%s, %s, 1, 0, 0)",
                    (owner_lower, now),
                )
                logger.debug("[Push][Throttle] New window for %s (1/%d)", owner_lower[:16], THROTTLE_MAX_SENDS)
                return True

            window_start, sent_count, suppressed_count, cooldown_until = (
                int(row[0]),
                int(row[1]),
                int(row[2]),
                int(row[3]),
            )

            if cooldown_until > now:
                cur.execute(
                    "UPDATE push_throttle SET suppressed_count = suppressed_count + 1 WHERE owner = %s",
                    (owner_lower,),
                )
                logger.debug("[Push][Throttle] Cooldown active for %s; suppressed", owner_lower[:16])
                return False

            window_expired = (now - window_start) >= THROTTLE_WINDOW_SECONDS
            if window_expired:
                if suppressed_count > 0:
                    cur.execute(
                        "UPDATE push_throttle SET suppressed_count = suppressed_count + 1 WHERE owner = %s",
                        (owner_lower,),
                    )
                    logger.debug(
                        "[Push][Throttle] Window expired for %s with pending summary (%d suppressed); suppressed",
                        owner_lower[:16],
                        suppressed_count,
                    )
                    return False

                cur.execute(
                    "UPDATE push_throttle SET window_start = %s, sent_count = 1, suppressed_count = 0 WHERE owner = %s",
                    (now, owner_lower),
                )
                logger.debug("[Push][Throttle] Window reset for %s (1/%d)", owner_lower[:16], THROTTLE_MAX_SENDS)
                return True

            if sent_count < THROTTLE_MAX_SENDS:
                cur.execute(
                    "UPDATE push_throttle SET sent_count = sent_count + 1 WHERE owner = %s",
                    (owner_lower,),
                )
                logger.debug(
                    "[Push][Throttle] Allowed for %s (%d/%d)", owner_lower[:16], sent_count + 1, THROTTLE_MAX_SENDS
                )
                return True

            cur.execute(
                "UPDATE push_throttle SET suppressed_count = suppressed_count + 1 WHERE owner = %s",
                (owner_lower,),
            )
            logger.debug("[Push][Throttle] Limit reached for %s; suppressed", owner_lower[:16])
            return False


def _store_receipt(ticket_id: str, token: str) -> None:
    try:
        with _connect_backend_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO push_receipts (ticket_id, token, created_at) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                    (ticket_id, token, int(time.time())),
                )
    except Exception:
        pass


def _check_old_receipts() -> None:
    """Opportunistically check receipts older than 15 minutes and remove invalid tokens."""
    try:
        global _last_receipt_check_ts
        now = time.time()
        if now - _last_receipt_check_ts < RECEIPT_CHECK_MIN_INTERVAL_SECONDS:
            return
        with _receipt_check_lock:
            if now - _last_receipt_check_ts < RECEIPT_CHECK_MIN_INTERVAL_SECONDS:
                return
            _last_receipt_check_ts = now
        cutoff = int(time.time()) - RECEIPT_CHECK_AGE_SECONDS
        with _connect_backend_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, ticket_id, token FROM push_receipts WHERE created_at < %s LIMIT 100",
                    (cutoff,),
                )
                rows = cur.fetchall()
                if not rows:
                    return

                ticket_map = {r[1]: (r[0], r[2]) for r in rows}
                ticket_ids = list(ticket_map.keys())

                try:
                    resp = http_requests.post(
                        EXPO_RECEIPTS_URL,
                        json={"ids": ticket_ids},
                        headers=_expo_headers(),
                        timeout=10,
                    )
                    if resp.status_code != 200:
                        return
                    receipts = resp.json().get("data", {})
                except Exception:
                    return

                ids_to_delete = []
                for tid, receipt in receipts.items():
                    if tid in ticket_map:
                        ids_to_delete.append(ticket_map[tid][0])
                        if receipt.get("details", {}).get("error") == "DeviceNotRegistered":
                            token = ticket_map[tid][1]
                            cur.execute("DELETE FROM push_tokens WHERE token = %s", (token,))
                            logger.info("[Push] Receipt: removed stale token %s…", token[:20])

                if ids_to_delete:
                    cur.execute("DELETE FROM push_receipts WHERE id = ANY(%s)", (ids_to_delete,))
    except Exception as e:
        logger.error("[Push] Receipt check failed: %s", e)


def _get_tokens_for_owner(owner: str) -> list[tuple[str, str]]:
    """Returns list of (token, platform) for an owner."""
    try:
        with _connect_backend_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT token, platform FROM push_tokens WHERE LOWER(owner) = LOWER(%s)",
                    (owner,),
                )
                return cur.fetchall()
    except Exception:
        return []


def _resolve_usernames_to_owners(usernames: list[str]) -> dict[str, str]:
    """Map usernames to owner addresses. Returns {username_lower: owner_lower}."""
    if not usernames:
        return {}
    try:
        with _connect_indexer_ro() as conn:
            with conn.cursor() as cur:
                placeholders = ",".join(["%s"] * len(usernames))
                cur.execute(
                    f"SELECT LOWER(username), LOWER(owner) FROM profiles WHERE LOWER(username) IN ({placeholders}) AND deleted_at IS NULL",
                    [u.lower() for u in usernames],
                )
                return {row[0]: row[1] for row in cur.fetchall()}
    except Exception:
        return {}


def _extract_mentions(content: str) -> list[str]:
    """Extract @username mentions from content, ignoring code blocks."""
    stripped = _FENCED_CODE_RE.sub("", content)
    stripped = _INLINE_CODE_RE.sub("", stripped)
    return sorted({m.lower() for m in _MENTION_RE.findall(stripped)})


def _get_post_owner(txhash: str) -> str | None:
    if not txhash:
        return None
    try:
        with _connect_indexer_ro() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT owner FROM posts WHERE LOWER(txhash)=LOWER(%s) LIMIT 1", (txhash,))
                row = cur.fetchone()
                return (row[0] or "").strip().lower() if row and row[0] else None
    except Exception:
        return None


def _get_root_post_id(target_txhash: str) -> str | None:
    if not target_txhash:
        return None
    try:
        with _connect_indexer_ro() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COALESCE(root_post_id, ''), COALESCE(target, '') FROM posts "
                    "WHERE LOWER(txhash)=LOWER(%s) LIMIT 1",
                    (target_txhash,),
                )
                row = cur.fetchone()
                if not row:
                    return None
                root_post_id = (row[0] or "").strip().lower()
                target = (row[1] or "").strip()
                if not target:
                    return target_txhash.strip().lower()
                if root_post_id:
                    return root_post_id
                return None
    except Exception:
        return None


def _truncate(text: str, max_len: int = 150) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def _send_push_to_user(owner: str, title: str, body: str, data: dict) -> None:
    """Send push to all devices for an owner, respecting the 5/30-min throttle."""
    tokens = _get_tokens_for_owner(owner)
    if not tokens:
        logger.debug("[Push] No tokens for %s, skipping", owner[:16])
        return

    if not _try_throttle_send(owner):
        logger.debug("[Push] Throttled for %s, suppressed", owner[:16])
        return

    messages = [_build_expo_message(token, title, body, data) for token, _platform in tokens]
    tickets = _send_expo_push_batch(messages)
    ok_count = 0
    for token, ticket_id in tickets:
        if ticket_id:
            _store_receipt(ticket_id, token)
            ok_count += 1
    logger.info("[Push] Sent %d/%d to %s: %s", ok_count, len(messages), owner[:16], title)


def _fire_and_forget(fn, *args):
    """Run fn in a daemon thread so it doesn't block the request."""
    t = threading.Thread(target=fn, args=args, daemon=True)
    t.start()


def _maybe_flush_pending_summaries() -> None:
    """Opportunistically flush pending summaries (at most once per 60s)."""
    if not PUSH_NOTIFICATIONS_ENABLED:
        return
    global _last_summary_flush_ts
    now = time.time()
    if now - _last_summary_flush_ts < 60:
        return
    with _summary_flush_lock:
        if now - _last_summary_flush_ts < 60:
            return
        _last_summary_flush_ts = now
    _fire_and_forget(flush_pending_summaries)


def send_push_for_reply(
    poster_addr: str,
    poster_username: str,
    target_txhash: str,
    content: str,
    tx_hash: str,
) -> None:
    """Fire push for a reply/comment. Called after successful broadcast."""
    if not PUSH_NOTIFICATIONS_ENABLED:
        logger.debug("[Push] Disabled, skipping reply push for %s", tx_hash[:16])
        return

    logger.info(
        "[Push] Firing reply push: poster=%s target=%s tx=%s", poster_addr[:16], target_txhash[:16], tx_hash[:16]
    )
    _fire_and_forget(_do_reply_push, poster_addr, poster_username, target_txhash, content, tx_hash)
    _maybe_flush_pending_summaries()


def _do_reply_push(
    poster_addr: str,
    poster_username: str,
    target_txhash: str,
    content: str,
    tx_hash: str,
) -> None:
    target_owner = _get_post_owner(target_txhash)
    if not target_owner:
        logger.warning("[Push] Missing reply target owner for %s", target_txhash[:16])
        return
    if target_owner == poster_addr.lower():
        logger.debug("[Push] Self-reply, skipping push for %s", tx_hash[:16])
        return
    root_post_id = _get_root_post_id(target_txhash)
    if not root_post_id:
        logger.warning("[Push] Missing root_post_id for reply target %s", target_txhash[:16])
        return

    display_name = f"@{poster_username}" if poster_username else poster_addr[:12]
    title = f"{display_name} replied"
    body = _truncate(content)
    data = {"type": "reply", "rootPostId": root_post_id, "replyId": tx_hash}

    _send_push_to_user(target_owner, title, body, data)
    _check_old_receipts()


def send_push_for_mentions(
    poster_addr: str,
    poster_username: str,
    content: str,
    tx_hash: str,
    target_txhash: str,
) -> None:
    """Fire pushes for @mentions in content. Called after successful broadcast."""
    if not PUSH_NOTIFICATIONS_ENABLED:
        logger.debug("[Push] Disabled, skipping mention push for %s", tx_hash[:16])
        return
    _fire_and_forget(_do_mentions_push, poster_addr, poster_username, content, tx_hash, target_txhash)
    _maybe_flush_pending_summaries()


def _do_mentions_push(
    poster_addr: str,
    poster_username: str,
    content: str,
    tx_hash: str,
    target_txhash: str,
) -> None:
    usernames = _extract_mentions(content)
    if not usernames:
        return

    username_to_owner = _resolve_usernames_to_owners(usernames)
    if not username_to_owner:
        return

    root_post_id = tx_hash
    reply_target_owner = None
    if target_txhash:
        reply_target_owner = _get_post_owner(target_txhash)
        root = _get_root_post_id(target_txhash)
        if not root:
            logger.warning("[Push] Missing root_post_id for mention target %s", target_txhash)
            return
        root_post_id = root

    poster_lower = poster_addr.lower()
    display_name = f"@{poster_username}" if poster_username else poster_addr[:12]
    owners = []
    for owner in username_to_owner.values():
        if owner == poster_lower:
            continue
        if reply_target_owner and owner == reply_target_owner:
            continue
        owners.append(owner)

    if not owners:
        return

    if len(owners) > MAX_MENTION_PUSHES:
        logger.info("[Push] Mention push capped: %d -> %d", len(owners), MAX_MENTION_PUSHES)
        owners = owners[:MAX_MENTION_PUSHES]

    for owner in owners:
        title = f"{display_name} mentioned you"
        body = _truncate(content)
        data = {"type": "mention", "rootPostId": root_post_id, "replyId": tx_hash}
        _send_push_to_user(owner, title, body, data)

    _check_old_receipts()


def send_push_for_award(
    awarder_addr: str,
    awarder_username: str,
    post_owner: str,
    target_txhash: str,
    award_type: str,
) -> None:
    """Fire push for an award. Called after successful broadcast."""
    if not PUSH_NOTIFICATIONS_ENABLED:
        logger.debug("[Push] Disabled, skipping award push for %s", target_txhash[:16])
        return

    if post_owner == awarder_addr.lower():
        return
    logger.info(
        "[Push] Firing award push: awarder=%s recipient=%s target=%s",
        awarder_addr[:16],
        post_owner[:16],
        target_txhash[:16],
    )
    _fire_and_forget(_do_award_push, awarder_addr, awarder_username, post_owner, target_txhash, award_type)
    _maybe_flush_pending_summaries()


def _do_award_push(
    awarder_addr: str,
    awarder_username: str,
    post_owner: str,
    target_txhash: str,
    award_type: str,
) -> None:
    display_name = f"@{awarder_username}" if awarder_username else awarder_addr[:12]
    title = f"{display_name} gave you an award"
    body = f"Your post received a {award_type} award"
    data = {"type": "award", "rootPostId": target_txhash, "replyId": ""}

    _send_push_to_user(post_owner, title, body, data)
    _check_old_receipts()


def send_push_for_follow(
    follower_addr: str,
    follower_username: str,
    target_owner: str,
) -> None:
    """Fire push for a follow. Called after successful broadcast."""
    if not PUSH_NOTIFICATIONS_ENABLED:
        logger.debug("[Push] Disabled, skipping follow push for %s", follower_addr[:16])
        return
    if target_owner == follower_addr.lower():
        return
    logger.info(
        "[Push] Firing follow push: follower=%s recipient=%s",
        follower_addr[:16],
        target_owner[:16],
    )
    _fire_and_forget(_do_follow_push, follower_addr, follower_username, target_owner)
    _maybe_flush_pending_summaries()


def _do_follow_push(
    follower_addr: str,
    follower_username: str,
    target_owner: str,
) -> None:
    display_name = f"@{follower_username}" if follower_username else follower_addr[:12]
    title = f"{display_name} followed you"
    body = "Tap to view their profile"
    data = {"type": "follow", "user": follower_addr.lower()}
    _send_push_to_user(target_owner, title, body, data)
    _check_old_receipts()


def _format_mirage_amount(amount_umirage: int) -> str:
    amount_int = int(amount_umirage)
    if amount_int < 0:
        raise RuntimeError("amount must be non-negative")
    value = Decimal(amount_int) / Decimal(1_000_000)
    quantized = value.quantize(Decimal("0.000001"))
    text = format(quantized, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if "." in text:
        int_part, dec_part = text.split(".", 1)
    else:
        int_part, dec_part = text, ""
    int_part_fmt = f"{int(int_part):,}"
    if dec_part:
        return f"{int_part_fmt}.{dec_part}"
    return int_part_fmt


def send_push_for_donation(
    sender_addr: str,
    sender_username: str,
    recipient_addr: str,
    amount: int,
) -> None:
    """Fire push for a donation. Called after successful broadcast."""
    if not PUSH_NOTIFICATIONS_ENABLED:
        logger.debug("[Push] Disabled, skipping donation push for %s", sender_addr[:16])
        return
    if recipient_addr == sender_addr.lower():
        return
    logger.info(
        "[Push] Firing donation push: sender=%s recipient=%s amount=%s",
        sender_addr[:16],
        recipient_addr[:16],
        amount,
    )
    _fire_and_forget(_do_donation_push, sender_addr, sender_username, recipient_addr, amount)
    _maybe_flush_pending_summaries()


def _do_donation_push(
    sender_addr: str,
    sender_username: str,
    recipient_addr: str,
    amount: int,
) -> None:
    amount_int = int(amount)
    display_name = f"@{sender_username}" if sender_username else sender_addr[:12]
    amount_display = _format_mirage_amount(amount_int)
    title = f"{display_name} donated {amount_display} MIRAGE"
    body = "You received a donation"
    data = {"type": "donation", "user": sender_addr.lower(), "amount": amount_int}
    _send_push_to_user(recipient_addr, title, body, data)
    _check_old_receipts()


def clear_push_throttle(owner: str) -> None:
    """Clear throttle state after the user views their inbox."""
    owner_lower = owner.lower()
    now = int(time.time())
    with _connect_backend_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO push_throttle (owner, window_start, sent_count, suppressed_count, cooldown_until)
                VALUES (%s, %s, 0, 0, 0)
                ON CONFLICT (owner) DO UPDATE SET
                    window_start = EXCLUDED.window_start,
                    sent_count = 0,
                    suppressed_count = 0,
                    cooldown_until = 0
                """,
                (owner_lower, now),
            )


def get_unread_count(owner: str) -> int:
    """Count replies + @mentions + awards after the user's last inbox view.

    Mirrors the logic in backend _get_new_inbox_count but runs against a fresh
    connection so it can be called from the indexer or push module.
    """
    with _connect_backend_db() as bconn:
        with bconn.cursor() as bcur:
            last_seen = fetch_inbox_last_viewed_at(owner, cur=bcur)
    with _connect_indexer_ro() as iconn:
        with iconn.cursor() as icur:
            count, _last_seen = compute_unread_count(icur, owner, last_seen)
            return count


def _send_summary_to_user(owner: str, unread_count: int) -> None:
    """Send an aggregated summary push (not subject to the throttle window)."""
    tokens = _get_tokens_for_owner(owner)
    if not tokens:
        logger.debug("[Push][Summary] No tokens for %s, skipping", owner[:16])
        return

    title = "Mirage"
    body = f"You have {unread_count} unread message{'s' if unread_count != 1 else ''}"
    data = {"type": "summary"}

    messages = [_build_expo_message(token, title, body, data) for token, _platform in tokens]
    tickets = _send_expo_push_batch(messages)
    ok_count = 0
    for token, ticket_id in tickets:
        if ticket_id:
            _store_receipt(ticket_id, token)
            ok_count += 1
    logger.info("[Push][Summary] Sent %d/%d to %s: %s", ok_count, len(messages), owner[:16], body)


def flush_pending_summaries() -> int:
    """Find owners whose throttle window expired with suppressed events and
    send them a summary push.  Resets their window afterwards.

    Called opportunistically by backend push paths.
    Returns the number of summaries sent.
    """
    if not PUSH_NOTIFICATIONS_ENABLED:
        return 0
    now = int(time.time())
    cutoff = now - THROTTLE_WINDOW_SECONDS
    sent = 0
    with _connect_backend_db() as bconn:
        with bconn.cursor() as bcur:
            bcur.execute(
                "SELECT owner FROM push_throttle "
                "WHERE suppressed_count > 0 AND window_start <= %s AND cooldown_until <= %s "
                "LIMIT 50",
                (cutoff, now),
            )
            owners = [r[0] for r in bcur.fetchall()]

            if not owners:
                return 0

            with _connect_indexer_ro() as iconn:
                with iconn.cursor() as icur:
                    for owner in owners:
                        last_seen = fetch_inbox_last_viewed_at(owner, cur=bcur)
                        unread, _last_seen = compute_unread_count(icur, owner, last_seen)
                        if unread > 0:
                            _send_summary_to_user(owner, unread)
                            sent += 1
                            cooldown_until = now + SUMMARY_COOLDOWN_SECONDS
                            bcur.execute(
                                "UPDATE push_throttle "
                                "SET window_start = %s, sent_count = 0, suppressed_count = 0, cooldown_until = %s "
                                "WHERE owner = %s",
                                (now, cooldown_until, owner),
                            )
                            logger.debug(
                                "[Push][Summary] Summary sent to %s (unread=%d), cooldown=%ds",
                                owner[:16],
                                unread,
                                SUMMARY_COOLDOWN_SECONDS,
                            )
                        else:
                            bcur.execute(
                                "UPDATE push_throttle "
                                "SET window_start = %s, sent_count = 0, suppressed_count = 0, cooldown_until = 0 "
                                "WHERE owner = %s",
                                (now, owner),
                            )
                            logger.debug("[Push][Summary] No unread for %s, cleared suppressed", owner[:16])

    if sent > 0:
        logger.info("[Push][Summary] Flushed %d summaries (checked %d owners)", sent, len(owners))
    return sent
