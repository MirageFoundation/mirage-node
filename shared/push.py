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

import hashlib
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
from shared.inbox import build_inbox_reply, compute_unread_count, fetch_inbox_last_viewed_at, parent_display_text

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


# Delivery outcomes returned to the outbox. PUSH_DISCARD means "there is
# nothing to deliver and never will be" (no device, self-notification, throttled
# into the summary push); PUSH_RETRY means the attempt could still succeed.
PUSH_SENT = "sent"
PUSH_DISCARD = "discard"
PUSH_RETRY = "retry"

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


def _notification_identity(data: dict) -> tuple[str, str]:
    """Derive (notificationType, notificationId) so Android taps always carry an
    identifiable payload. Type-aware because this builder serves trending pushes
    too, not just inbox events."""
    notif_type = "trending" if data.get("type") == "trending" else "inbox"
    reply_id = data.get("replyId")
    root_post_id = data.get("rootPostId")
    if reply_id:
        return notif_type, f"{notif_type}-reply:{reply_id}"
    if root_post_id:
        return notif_type, f"{notif_type}-root:{root_post_id}"
    if data.get("type") == "summary":
        return notif_type, f"inbox-summary:{int(time.time())}"
    raise RuntimeError(f"cannot derive notificationId for push data: {data!r}")


def _build_expo_message(token: str, title: str, body: str, data: dict) -> dict:
    notif_type, notif_id = _notification_identity(data)
    enriched = dict(data)
    enriched["notificationType"] = notif_type
    enriched["notificationId"] = notif_id
    return {
        "to": token,
        "title": title,
        "body": body,
        "data": enriched,
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


def _token_fingerprint(token: str) -> str:
    """Stable, non-reversible tag for correlating log lines about one token.

    Push tokens are credentials for addressing a user's device, so logs carry a
    hash instead of a prefix of the token itself (L-7).
    """
    return hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()[:12]


def _remove_token(token: str) -> None:
    try:
        with _connect_backend_db() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM push_tokens WHERE token = %s", (token,))
        logger.info("[Push] Removed invalid token: fp=%s", _token_fingerprint(token))
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


def _release_throttle_send(owner: str) -> None:
    """Return a slot when Expo accepted no ticket for the attempted push."""
    owner_lower = owner.lower()
    with _connect_backend_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE push_throttle SET sent_count = GREATEST(sent_count - 1, 0) WHERE owner = %s",
                (owner_lower,),
            )
    logger.debug("[Push][Throttle] Released failed send slot for %s", owner_lower[:16])


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
                            logger.info("[Push] Receipt: removed stale token fp=%s", _token_fingerprint(token))

                if ids_to_delete:
                    cur.execute("DELETE FROM push_receipts WHERE id = ANY(%s)", (ids_to_delete,))
    except Exception as e:
        logger.error("[Push] Receipt check failed: %s", e)


def _get_tokens_for_owner(owner: str) -> list[tuple[str, str]]:
    """Returns list of (token, platform) for an owner."""
    with _connect_backend_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT token, platform FROM push_tokens WHERE LOWER(owner) = LOWER(%s)",
                (owner,),
            )
            return cur.fetchall()


def _resolve_usernames_to_owners(usernames: list[str], cur=None) -> dict[str, str]:
    """Map usernames to owner addresses. Returns {username_lower: owner_lower}."""
    if not usernames:
        return {}
    if cur is None:
        with _connect_indexer_ro() as conn:
            with conn.cursor() as cur_local:
                placeholders = ",".join(["%s"] * len(usernames))
                cur_local.execute(
                    f"SELECT LOWER(username), LOWER(owner) FROM profiles WHERE LOWER(username) IN ({placeholders}) "
                    "AND deleted_at IS NULL",
                    [u.lower() for u in usernames],
                )
                return {row[0]: row[1] for row in cur_local.fetchall()}
    placeholders = ",".join(["%s"] * len(usernames))
    cur.execute(
        f"SELECT LOWER(username), LOWER(owner) FROM profiles WHERE LOWER(username) IN ({placeholders}) "
        "AND deleted_at IS NULL",
        [u.lower() for u in usernames],
    )
    return {row[0]: row[1] for row in cur.fetchall()}


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


def _resolve_root_post_id(txhash: str, target: str, root_post_id: str) -> str | None:
    txhash_lc = str(txhash or "").strip().lower()
    if not txhash_lc:
        return None
    target_lc = str(target or "").strip().lower()
    root_lc = str(root_post_id or "").strip().lower()
    if not target_lc:
        return txhash_lc
    if root_lc:
        return root_lc
    return None


def _fetch_profile_info(owner: str, cur=None) -> dict | None:
    """Fetch (username, level, created_at) for an owner from the indexer DB."""
    if not owner:
        return None
    if cur is None:
        with _connect_indexer_ro() as conn:
            with conn.cursor() as cur_local:
                cur_local.execute(
                    "SELECT COALESCE(username, ''), COALESCE(level, 0), COALESCE(created_at, 0) "
                    "FROM profiles WHERE LOWER(owner) = LOWER(%s) AND deleted_at IS NULL LIMIT 1",
                    (owner,),
                )
                row = cur_local.fetchone()
    else:
        cur.execute(
            "SELECT COALESCE(username, ''), COALESCE(level, 0), COALESCE(created_at, 0) "
            "FROM profiles WHERE LOWER(owner) = LOWER(%s) AND deleted_at IS NULL LIMIT 1",
            (owner,),
        )
        row = cur.fetchone()
    if not row:
        return None
    return {
        "username": str(row[0] or "").strip(),
        "level": int(row[1]) if row[1] is not None else 0,
        "created_at": int(row[2]) if row[2] is not None else 0,
    }


def _fetch_post_context(txhash: str, cur=None) -> dict | None:
    """Fetch post context (content, title, target, owner, root_post_id) from indexer DB."""
    if not txhash:
        return None
    if cur is None:
        with _connect_indexer_ro() as conn:
            with conn.cursor() as cur_local:
                cur_local.execute(
                    "SELECT COALESCE(content, ''), COALESCE(title, ''), COALESCE(target, ''), "
                    "owner, COALESCE(root_post_id, '') "
                    "FROM posts WHERE LOWER(txhash) = LOWER(%s) AND deleted = FALSE LIMIT 1",
                    (txhash,),
                )
                row = cur_local.fetchone()
    else:
        cur.execute(
            "SELECT COALESCE(content, ''), COALESCE(title, ''), COALESCE(target, ''), "
            "owner, COALESCE(root_post_id, '') "
            "FROM posts WHERE LOWER(txhash) = LOWER(%s) AND deleted = FALSE LIMIT 1",
            (txhash,),
        )
        row = cur.fetchone()
    if not row:
        return None
    return {
        "content": str(row[0] or ""),
        "title": str(row[1] or ""),
        "target": str(row[2] or "").strip().lower(),
        "owner": str(row[3] or "").strip().lower(),
        "root_post_id": str(row[4] or "").strip().lower(),
    }


def _truncate(text: str, max_len: int = 150) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def _recipient_blocks_actor(recipient: str, actor: str) -> bool:
    """True if ``recipient`` has blocked ``actor``.

    Mirrors the inbox's own filter. The in-app inbox has always dropped items from
    blocked actors; push delivery had no reference to any blocked list at all, so
    replying to someone who blocked you or writing ``@them`` in any post put
    attacker-authored text on their lock screen while they saw nothing in-app to
    report.
    """
    recipient_lc = (recipient or "").strip().lower()
    actor_lc = (actor or "").strip().lower()
    if not recipient_lc or not actor_lc or recipient_lc == actor_lc:
        return False
    try:
        with _connect_indexer_ro() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 1
                    FROM blocked_users
                    WHERE LOWER(target) = %s AND LOWER(owner) = %s
                    LIMIT 1
                    """,
                    (actor_lc, recipient_lc),
                )
                return cur.fetchone() is not None
    except Exception as exc:  # noqa: BLE001
        # Fail closed: an unreadable block list must not become a delivered push.
        logger.warning("[Push] Block lookup failed for %s, suppressing: %s", recipient_lc[:16], exc)
        return True


def _send_push_to_user(
    owner: str,
    title: str,
    body: str,
    data: dict,
    *,
    actor: str = "",
    tokens: list[tuple[str, str]] | None = None,
    skip_throttle: bool = False,
) -> str:
    """Send push to all devices for an owner, respecting the 5/30-min throttle."""
    if actor and _recipient_blocks_actor(owner, actor):
        logger.info("[Push] Recipient %s blocks actor %s, suppressed", owner[:16], actor[:16])
        return PUSH_DISCARD

    if tokens is None:
        tokens = _get_tokens_for_owner(owner)
    if not tokens:
        logger.debug("[Push] No tokens for %s, skipping", owner[:16])
        return PUSH_DISCARD

    if not skip_throttle and not _try_throttle_send(owner):
        # The throttle counted this event; the summary push covers it, so
        # redelivering it later would double-notify.
        logger.debug("[Push] Throttled for %s, suppressed", owner[:16])
        return PUSH_DISCARD

    messages = [_build_expo_message(token, title, body, data) for token, _platform in tokens]
    tickets = _send_expo_push_batch(messages)
    ok_count = 0
    for token, ticket_id in tickets:
        if ticket_id:
            _store_receipt(ticket_id, token)
            ok_count += 1
    if ok_count == 0:
        if not skip_throttle:
            _release_throttle_send(owner)
        logger.debug("[Push] No successful tickets for %s", owner[:16])
        return PUSH_RETRY
    logger.info("[Push] Sent %d/%d to %s: %s", ok_count, len(messages), owner[:16], title)
    return PUSH_SENT


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
    created_at: int = 0,
) -> str:
    """Deliver a reply/comment push. Called by the outbox worker; returns an outcome."""
    if not PUSH_NOTIFICATIONS_ENABLED:
        logger.debug("[Push] Disabled, skipping reply push for %s", tx_hash[:16])
        return PUSH_DISCARD

    logger.info(
        "[Push] Firing reply push: poster=%s target=%s tx=%s", poster_addr[:16], target_txhash[:16], tx_hash[:16]
    )
    outcome = _do_reply_push(poster_addr, poster_username, target_txhash, content, tx_hash, created_at)
    _maybe_flush_pending_summaries()
    return outcome


def _do_reply_push(
    poster_addr: str,
    poster_username: str,
    target_txhash: str,
    content: str,
    tx_hash: str,
    created_at: int = 0,
) -> str:
    poster_lc = poster_addr.lower()
    with _connect_indexer_ro() as conn:
        with conn.cursor() as cur:
            # Content is snapshotted into the payload at enqueue and was never
            # re-validated, so deleting the reply within seconds of posting left
            # the inbox empty while the device still displayed it — and the
            # delivered text is unrecoverable. _fetch_post_context filters
            # deleted rows, so a missing reply here means deleted or not yet
            # indexed; either way there is nothing to deliver.
            if not _fetch_post_context(tx_hash, cur=cur):
                logger.info("[Push] Reply %s is gone or deleted, discarding push", tx_hash[:16])
                return PUSH_DISCARD
            parent_ctx = _fetch_post_context(target_txhash, cur=cur)
            if not parent_ctx:
                logger.warning("[Push] Missing parent post context for %s", target_txhash[:16])
                return PUSH_RETRY
            target_owner = parent_ctx["owner"]
            if target_owner == poster_lc:
                logger.debug("[Push] Self-reply, skipping push for %s", tx_hash[:16])
                return PUSH_DISCARD
            root_post_id = _resolve_root_post_id(target_txhash, parent_ctx["target"], parent_ctx["root_post_id"])
            if not root_post_id:
                logger.warning("[Push] Missing root_post_id for reply target %s", target_txhash[:16])
                return PUSH_RETRY
            profile = _fetch_profile_info(poster_addr, cur=cur)
            if not profile:
                logger.warning("[Push] Missing profile for reply poster %s", poster_addr[:16])
                return PUSH_RETRY
    logger.debug("[Push] Reply context resolved owner=%s root=%s", target_owner[:16], root_post_id[:16])
    poster_username = poster_username or profile["username"]

    p_display = parent_display_text("reply", parent_ctx["target"], parent_ctx["title"], parent_ctx["content"])

    ts = created_at or int(time.time())

    inbox_reply = build_inbox_reply(
        reply_id=tx_hash.lower(),
        reply_owner=poster_addr.lower(),
        reply_username=poster_username,
        reply_timestamp=ts,
        reply_author_level=profile["level"],
        reply_author_created_at=profile["created_at"],
        reply_content=content,
        parent_id=target_txhash.lower(),
        parent_content=p_display,
        parent_owner=parent_ctx["owner"],
        root_post_id=root_post_id,
        award_type="",
        item_type="reply",
        amount=None,
    )
    logger.debug("[Push] Built inboxReply for reply tx=%s", tx_hash[:16])

    display_name = f"@{poster_username}" if poster_username else poster_addr[:12]
    title = f"{display_name} replied"
    body = _truncate(content)
    data = {"type": "reply", "rootPostId": root_post_id, "replyId": tx_hash, "inboxReply": inbox_reply}

    outcome = _send_push_to_user(target_owner, title, body, data, actor=poster_addr)
    _check_old_receipts()
    return outcome


def send_push_for_mentions(
    poster_addr: str,
    poster_username: str,
    content: str,
    tx_hash: str,
    target_txhash: str,
    created_at: int = 0,
    mentioned_username: str = "",
) -> str:
    """Deliver @mention pushes. Called by the outbox worker; returns an outcome."""
    if not PUSH_NOTIFICATIONS_ENABLED:
        logger.debug("[Push] Disabled, skipping mention push for %s", tx_hash[:16])
        return PUSH_DISCARD
    outcome = _do_mentions_push(
        poster_addr,
        poster_username,
        content,
        tx_hash,
        target_txhash,
        created_at,
        mentioned_username,
    )
    _maybe_flush_pending_summaries()
    return outcome


def _do_mentions_push(
    poster_addr: str,
    poster_username: str,
    content: str,
    tx_hash: str,
    target_txhash: str,
    created_at: int = 0,
    mentioned_username: str = "",
) -> str:
    usernames = [mentioned_username.lower()] if mentioned_username else _extract_mentions(content)
    if not usernames:
        return PUSH_DISCARD
    root_post_id = tx_hash
    reply_target_owner = None
    post_ctx = None
    with _connect_indexer_ro() as conn:
        with conn.cursor() as cur:
            username_to_owner = _resolve_usernames_to_owners(usernames, cur=cur)
            if not username_to_owner:
                return PUSH_DISCARD
            if target_txhash:
                target_ctx = _fetch_post_context(target_txhash, cur=cur)
                if not target_ctx:
                    logger.warning("[Push] Missing target post context for %s", target_txhash)
                    return PUSH_RETRY
                reply_target_owner = target_ctx["owner"]
                root = _resolve_root_post_id(target_txhash, target_ctx["target"], target_ctx["root_post_id"])
                if not root:
                    logger.warning("[Push] Missing root_post_id for mention target %s", target_txhash)
                    return PUSH_RETRY
                root_post_id = root
            profile = _fetch_profile_info(poster_addr, cur=cur)
            if not profile:
                logger.warning("[Push] Missing profile for mention poster %s", poster_addr[:16])
                return PUSH_RETRY
            post_ctx = _fetch_post_context(tx_hash, cur=cur)
            # Previously this path explicitly tolerated the post being gone and
            # pushed the snapshotted text anyway, so a mention could be posted and
            # deleted within seconds and still land on the victim's lock screen
            # with nothing in-app to report.
            if not post_ctx:
                logger.info("[Push] Mention source %s is gone or deleted, discarding push", tx_hash[:16])
                return PUSH_DISCARD
    poster_username = poster_username or profile["username"]
    logger.debug("[Push] Mention context resolved root=%s", root_post_id[:16])
    p_display = ""
    parent_id = tx_hash.lower()
    parent_owner = poster_addr.lower()
    if post_ctx:
        p_display = parent_display_text("mention", post_ctx["target"], post_ctx["title"], post_ctx["content"])
        parent_owner = post_ctx["owner"]

    ts = created_at or int(time.time())

    inbox_reply = build_inbox_reply(
        reply_id=tx_hash.lower(),
        reply_owner=poster_addr.lower(),
        reply_username=poster_username,
        reply_timestamp=ts,
        reply_author_level=profile["level"],
        reply_author_created_at=profile["created_at"],
        reply_content=content,
        parent_id=parent_id,
        parent_content=p_display,
        parent_owner=parent_owner,
        root_post_id=root_post_id,
        award_type="",
        item_type="mention",
        amount=None,
    )
    logger.debug("[Push] Built inboxReply for mention tx=%s", tx_hash[:16])

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
        return PUSH_DISCARD

    if len(owners) > MAX_MENTION_PUSHES:
        logger.info("[Push] Mention push capped: %d -> %d", len(owners), MAX_MENTION_PUSHES)
        owners = owners[:MAX_MENTION_PUSHES]

    outcomes = []
    for owner in owners:
        title = f"{display_name} mentioned you"
        body = _truncate(content)
        data = {"type": "mention", "rootPostId": root_post_id, "replyId": tx_hash, "inboxReply": inbox_reply}
        outcomes.append(_send_push_to_user(owner, title, body, data, actor=poster_addr))

    _check_old_receipts()
    # New outbox rows target one username. The multi-owner aggregation remains
    # for legacy rows that were queued before per-recipient mention keys.
    if PUSH_SENT in outcomes:
        return PUSH_SENT
    if PUSH_RETRY in outcomes:
        return PUSH_RETRY
    return PUSH_DISCARD


def send_push_for_award(
    awarder_addr: str,
    awarder_username: str,
    post_owner: str,
    target_txhash: str,
    award_type: str,
    created_at: int = 0,
) -> str:
    """Deliver an award push. Called by the outbox worker; returns an outcome."""
    if not PUSH_NOTIFICATIONS_ENABLED:
        logger.debug("[Push] Disabled, skipping award push for %s", target_txhash[:16])
        return PUSH_DISCARD

    if post_owner == awarder_addr.lower():
        return PUSH_DISCARD
    logger.info(
        "[Push] Firing award push: awarder=%s recipient=%s target=%s",
        awarder_addr[:16],
        post_owner[:16],
        target_txhash[:16],
    )
    outcome = _do_award_push(awarder_addr, awarder_username, post_owner, target_txhash, award_type, created_at)
    _maybe_flush_pending_summaries()
    return outcome


def _do_award_push(
    awarder_addr: str,
    awarder_username: str,
    post_owner: str,
    target_txhash: str,
    award_type: str,
    created_at: int = 0,
) -> str:
    with _connect_indexer_ro() as conn:
        with conn.cursor() as cur:
            profile = _fetch_profile_info(awarder_addr, cur=cur)
            if not profile:
                logger.warning("[Push] Missing profile for awarder %s", awarder_addr[:16])
                return PUSH_RETRY
            post_ctx = _fetch_post_context(target_txhash, cur=cur)
            if not post_ctx:
                logger.warning("[Push] Missing post context for award target %s", target_txhash[:16])
                return PUSH_RETRY
    awarder_username = awarder_username or profile["username"]

    root_post_id = post_ctx["root_post_id"] or target_txhash.lower()
    p_display = parent_display_text("award", post_ctx["target"], post_ctx["title"], post_ctx["content"])

    ts = created_at or int(time.time())

    inbox_reply = build_inbox_reply(
        reply_id=target_txhash.lower(),
        reply_owner=awarder_addr.lower(),
        reply_username=awarder_username,
        reply_timestamp=ts,
        reply_author_level=profile["level"],
        reply_author_created_at=profile["created_at"],
        reply_content=post_ctx["content"],
        parent_id=target_txhash.lower(),
        parent_content=p_display,
        parent_owner=post_ctx["owner"],
        root_post_id=root_post_id,
        award_type=award_type,
        item_type="award",
        amount=None,
    )
    logger.debug("[Push] Built inboxReply for award target=%s", target_txhash[:16])

    display_name = f"@{awarder_username}" if awarder_username else awarder_addr[:12]
    title = f"{display_name} gave you an award"
    body = f"Your post received a {award_type} award"
    data = {"type": "award", "rootPostId": root_post_id, "replyId": target_txhash.lower(), "inboxReply": inbox_reply}

    outcome = _send_push_to_user(post_owner, title, body, data, actor=awarder_addr)
    _check_old_receipts()
    return outcome


def send_push_for_follow(
    follower_addr: str,
    follower_username: str,
    target_owner: str,
    event_key: str = "",
    created_at: int = 0,
) -> str:
    """Deliver a follow push. Called by the outbox worker; returns an outcome."""
    if not PUSH_NOTIFICATIONS_ENABLED:
        logger.debug("[Push] Disabled, skipping follow push for %s", follower_addr[:16])
        return PUSH_DISCARD
    if target_owner == follower_addr.lower():
        return PUSH_DISCARD
    logger.info(
        "[Push] Firing follow push: follower=%s recipient=%s",
        follower_addr[:16],
        target_owner[:16],
    )
    outcome = _do_follow_push(follower_addr, follower_username, target_owner, event_key, created_at)
    _maybe_flush_pending_summaries()
    return outcome


def _do_follow_push(
    follower_addr: str,
    follower_username: str,
    target_owner: str,
    event_key: str,
    created_at: int,
) -> str:
    profile = _fetch_profile_info(follower_addr)
    if not profile:
        logger.warning("[Push] Missing profile for follower %s", follower_addr[:16])
        return PUSH_RETRY
    follower_username = follower_username or profile["username"]

    reply_id = event_key or follower_addr.lower()
    ts = created_at or int(time.time())

    inbox_reply = build_inbox_reply(
        reply_id=reply_id,
        reply_owner=follower_addr.lower(),
        reply_username=follower_username,
        reply_timestamp=ts,
        reply_author_level=profile["level"],
        reply_author_created_at=profile["created_at"],
        reply_content="",
        parent_id="",
        parent_content="",
        parent_owner=target_owner.lower(),
        root_post_id="",
        award_type="",
        item_type="follow",
        amount=None,
    )
    logger.debug("[Push] Built inboxReply for follow actor=%s", follower_addr[:16])

    display_name = f"@{follower_username}" if follower_username else follower_addr[:12]
    title = f"{display_name} followed you"
    body = "Tap to view their profile"
    data = {"type": "follow", "user": follower_addr.lower(), "replyId": reply_id, "inboxReply": inbox_reply}
    outcome = _send_push_to_user(target_owner, title, body, data, actor=follower_addr)
    _check_old_receipts()
    return outcome


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
    event_key: str = "",
    created_at: int = 0,
) -> str:
    """Deliver a donation push. Called by the outbox worker; returns an outcome."""
    if not PUSH_NOTIFICATIONS_ENABLED:
        logger.debug("[Push] Disabled, skipping donation push for %s", sender_addr[:16])
        return PUSH_DISCARD
    if recipient_addr == sender_addr.lower():
        return PUSH_DISCARD
    logger.info(
        "[Push] Firing donation push: sender=%s recipient=%s amount=%s",
        sender_addr[:16],
        recipient_addr[:16],
        amount,
    )
    outcome = _do_donation_push(sender_addr, sender_username, recipient_addr, amount, event_key, created_at)
    _maybe_flush_pending_summaries()
    return outcome


def send_push_for_subscription_gift(
    gifter_addr: str,
    gifter_username: str,
    recipient_addr: str,
    level: int,
    was_subscriber: bool,
    event_key: str = "",
    created_at: int = 0,
) -> str:
    """Deliver a gifted-subscription push. Called by the outbox worker; returns an outcome."""
    if not PUSH_NOTIFICATIONS_ENABLED:
        logger.debug("[Push] Disabled, skipping subscription gift push for %s", gifter_addr[:16])
        return PUSH_DISCARD
    if recipient_addr == gifter_addr.lower():
        return PUSH_DISCARD
    logger.info(
        "[Push] Firing subscription gift push: gifter=%s recipient=%s level=%s was_sub=%s",
        gifter_addr[:16],
        recipient_addr[:16],
        level,
        was_subscriber,
    )
    outcome = _do_subscription_gift_push(
        gifter_addr,
        gifter_username,
        recipient_addr,
        level,
        was_subscriber,
        event_key,
        created_at,
    )
    _maybe_flush_pending_summaries()
    return outcome


def _do_subscription_gift_push(
    gifter_addr: str,
    gifter_username: str,
    recipient_addr: str,
    level: int,
    was_subscriber: bool,
    event_key: str,
    created_at: int,
) -> str:
    profile = _fetch_profile_info(gifter_addr)
    if not profile:
        logger.warning("[Push] Missing profile for gifter %s", gifter_addr[:16])
        return PUSH_RETRY
    gifter_username = gifter_username or profile["username"]

    reply_id = event_key or gifter_addr.lower()
    ts = created_at or int(time.time())

    inbox_reply = build_inbox_reply(
        reply_id=reply_id,
        reply_owner=gifter_addr.lower(),
        reply_username=gifter_username,
        reply_timestamp=ts,
        reply_author_level=profile["level"],
        reply_author_created_at=profile["created_at"],
        reply_content="",
        parent_id="",
        parent_content="",
        parent_owner=recipient_addr.lower(),
        root_post_id="",
        award_type="",
        item_type="subscription_gift",
        amount=int(level),
    )
    logger.debug("[Push] Built inboxReply for subscription_gift actor=%s level=%s", gifter_addr[:16], level)

    display_name = f"@{gifter_username}" if gifter_username else gifter_addr[:12]
    tier = "agent subscription" if int(level) == 10 else "subscription"
    if was_subscriber:
        title = f"{display_name} extended your {tier}"
        body = "Your subscription has been extended"
    else:
        title = f"{display_name} gifted you a {tier}"
        body = "Welcome to Mirage"
    data = {
        "type": "subscription_gift",
        "user": gifter_addr.lower(),
        "level": int(level),
        "replyId": reply_id,
        "inboxReply": inbox_reply,
    }
    outcome = _send_push_to_user(recipient_addr, title, body, data, actor=gifter_addr)
    _check_old_receipts()
    return outcome


def _do_donation_push(
    sender_addr: str,
    sender_username: str,
    recipient_addr: str,
    amount: int,
    event_key: str,
    created_at: int,
) -> str:
    amount_int = int(amount)

    profile = _fetch_profile_info(sender_addr)
    if not profile:
        logger.warning("[Push] Missing profile for donation sender %s", sender_addr[:16])
        return PUSH_RETRY
    sender_username = sender_username or profile["username"]

    reply_id = event_key or sender_addr.lower()
    ts = created_at or int(time.time())

    inbox_reply = build_inbox_reply(
        reply_id=reply_id,
        reply_owner=sender_addr.lower(),
        reply_username=sender_username,
        reply_timestamp=ts,
        reply_author_level=profile["level"],
        reply_author_created_at=profile["created_at"],
        reply_content="",
        parent_id="",
        parent_content="",
        parent_owner=recipient_addr.lower(),
        root_post_id="",
        award_type="",
        item_type="donation",
        amount=amount_int,
    )
    logger.debug("[Push] Built inboxReply for donation actor=%s amount=%d", sender_addr[:16], amount_int)

    display_name = f"@{sender_username}" if sender_username else sender_addr[:12]
    amount_display = _format_mirage_amount(amount_int)
    title = f"{display_name} donated {amount_display} MIRAGE"
    body = "You received a donation"
    data = {
        "type": "donation",
        "user": sender_addr.lower(),
        "amount": amount_int,
        "replyId": reply_id,
        "inboxReply": inbox_reply,
    }
    outcome = _send_push_to_user(recipient_addr, title, body, data, actor=sender_addr)
    _check_old_receipts()
    return outcome


def send_push_for_trending(
    recipient_owner: str,
    title_preview: str,
    tx_hash: str,
) -> bool:
    """Fire push for a trending post to a recipient.

    Trending pushes are capped by the listener's once-per-day policy and bypass
    inbox throttle windows so they don't interfere with inbox summary behavior.
    """
    if not PUSH_NOTIFICATIONS_ENABLED:
        logger.debug("[Push] Disabled, skipping trending push for %s", recipient_owner[:16])
        return False
    tokens = _get_tokens_for_owner(recipient_owner)
    if not tokens:
        logger.debug("[Push] No tokens for trending recipient=%s", recipient_owner[:16])
        return False
    logger.info(
        "[Push] Firing trending push: recipient=%s tx=%s",
        recipient_owner[:16],
        tx_hash[:16],
    )
    sent = _do_trending_push(recipient_owner, title_preview, tx_hash, tokens)
    if sent:
        _maybe_flush_pending_summaries()
        return True
    logger.debug("[Push] Trending delivery failed recipient=%s tx=%s", recipient_owner[:16], tx_hash[:16])
    return False


def _do_trending_push(
    recipient_owner: str,
    title_preview: str,
    tx_hash: str,
    tokens: list[tuple[str, str]],
) -> bool:
    owner_lc = recipient_owner.lower()
    title = "Trending on Mirage"
    if title_preview:
        display_title = _truncate(title_preview, 80)
        body = f"Lively discussion on '{display_title}'"
    else:
        body = "Lively discussion on a post you're missing"
    data = {
        "type": "trending",
        "postId": tx_hash.lower(),
        "rootPostId": tx_hash.lower(),
    }
    outcome = _send_push_to_user(owner_lc, title, body, data, tokens=tokens, skip_throttle=True)
    _check_old_receipts()
    return outcome == PUSH_SENT


def deliver_push_event(event_type: str, payload: dict) -> str:
    """Deliver one queued push outbox row. Returns PUSH_SENT/PUSH_DISCARD/PUSH_RETRY."""
    if event_type == "reply":
        return send_push_for_reply(
            payload["poster"],
            payload["poster_username"],
            payload["target_txhash"],
            payload["content"],
            payload["tx_hash"],
            created_at=int(payload["created_at"]),
        )
    if event_type == "mention":
        return send_push_for_mentions(
            payload["poster"],
            payload["poster_username"],
            payload["content"],
            payload["tx_hash"],
            payload["target_txhash"],
            created_at=int(payload["created_at"]),
            mentioned_username=str(payload.get("mentioned_username", "")),
        )
    if event_type == "award":
        return send_push_for_award(
            payload["awarder"],
            payload["awarder_username"],
            payload["post_owner"],
            payload["target_txhash"],
            payload["award_type"],
            created_at=int(payload["created_at"]),
        )
    if event_type == "donation":
        return send_push_for_donation(
            payload["sender"],
            payload["sender_username"],
            payload["recipient"],
            int(payload["amount"]),
            event_key=payload["event_key"],
            created_at=int(payload["created_at"]),
        )
    if event_type == "follow":
        return send_push_for_follow(
            payload["actor"],
            payload["actor_username"],
            payload["recipient"],
            event_key=payload["event_key"],
            created_at=int(payload["created_at"]),
        )
    if event_type == "subscription_gift":
        return send_push_for_subscription_gift(
            payload["actor"],
            payload["actor_username"],
            payload["recipient"],
            level=int(payload["level"]),
            was_subscriber=bool(payload["was_subscriber"]),
            event_key=payload["event_key"],
            created_at=int(payload["created_at"]),
        )
    raise RuntimeError(f"unknown push event_type={event_type!r}")


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
