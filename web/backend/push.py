"""
Expo push notification sender with budget enforcement and receipt processing.

Sends inline from request handlers — no cron or background workers.
Budget: max 3 pushes per user, resets when mark_inbox_viewed is called.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from typing import Optional

import requests as http_requests

from db import connect_db
from settings import PUSH_NOTIFICATIONS_ENABLED, EXPO_ACCESS_TOKEN

logger = logging.getLogger(__name__)

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"
EXPO_RECEIPTS_URL = "https://exp.host/--/api/v2/push/getReceipts"
MAX_BUDGET = 3
MAX_MENTION_PUSHES = 10
_MENTION_RE = re.compile(r"(?<!\w)@([A-Za-z0-9-]+)")
_FENCED_CODE_RE = re.compile(r"```[\s\S]*?```")
_INLINE_CODE_RE = re.compile(r"`[^`]+`")
RECEIPT_CHECK_AGE_SECONDS = 15 * 60
RECEIPT_CHECK_MIN_INTERVAL_SECONDS = 5 * 60
_last_receipt_check_ts = 0.0
_receipt_check_lock = threading.Lock()


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
        with connect_db(timeout=3.0, busy_timeout_ms=5000) as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM push_tokens WHERE token = %s", (token,))
        logger.info("[Push] Removed invalid token: %s…", token[:20])
    except Exception as e:
        logger.error("[Push] Failed to remove token: %s", e)


def _decrement_budget(owner: str) -> bool:
    """Atomically decrement push budget. Returns True if budget was available."""
    owner_lower = owner.lower()
    try:
        with connect_db(timeout=3.0, busy_timeout_ms=5000) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO push_budget (owner, remaining, last_reset_at)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (owner) DO UPDATE SET
                        remaining = push_budget.remaining - 1
                    WHERE push_budget.remaining > 0
                    RETURNING remaining
                    """,
                    (owner_lower, MAX_BUDGET - 1, int(time.time())),
                )
                row = cur.fetchone()
                return row is not None
    except Exception as e:
        logger.error("[Push] Budget check failed: %s", e)
        return False


def _store_receipt(ticket_id: str, token: str) -> None:
    try:
        with connect_db(timeout=3.0, busy_timeout_ms=5000) as conn:
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
        with connect_db(timeout=5.0, busy_timeout_ms=10000) as conn:
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
                    cur.execute(
                        "DELETE FROM push_receipts WHERE id = ANY(%s)", (ids_to_delete,)
                    )
    except Exception as e:
        logger.error("[Push] Receipt check failed: %s", e)


def _get_tokens_for_owner(owner: str) -> list[tuple[str, str]]:
    """Returns list of (token, platform) for an owner."""
    try:
        with connect_db(timeout=3.0, busy_timeout_ms=5000) as conn:
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
        with connect_db(timeout=3.0, busy_timeout_ms=5000) as conn:
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
        with connect_db(timeout=3.0, busy_timeout_ms=5000) as conn:
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
        with connect_db(timeout=3.0, busy_timeout_ms=5000) as conn:
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
    return text[:max_len - 1] + "…"


def _send_push_to_user(owner: str, title: str, body: str, data: dict) -> None:
    """Send push to all devices for an owner, respecting budget."""
    if not _decrement_budget(owner):
        logger.debug("[Push] Budget exhausted for %s", owner)
        return

    tokens = _get_tokens_for_owner(owner)
    if not tokens:
        return

    messages = [_build_expo_message(token, title, body, data) for token, _platform in tokens]
    tickets = _send_expo_push_batch(messages)
    for token, ticket_id in tickets:
        if ticket_id:
            _store_receipt(ticket_id, token)


def _fire_and_forget(fn, *args):
    """Run fn in a daemon thread so it doesn't block the request."""
    t = threading.Thread(target=fn, args=args, daemon=True)
    t.start()


def send_push_for_reply(
    poster_addr: str,
    poster_username: str,
    target_txhash: str,
    content: str,
    tx_hash: str,
) -> None:
    """Fire push for a reply/comment. Called after successful broadcast."""
    if not PUSH_NOTIFICATIONS_ENABLED:
        return

    _fire_and_forget(_do_reply_push, poster_addr, poster_username, target_txhash, content, tx_hash)


def _do_reply_push(
    poster_addr: str,
    poster_username: str,
    target_txhash: str,
    content: str,
    tx_hash: str,
) -> None:
    target_owner = _get_post_owner(target_txhash)
    if not target_owner:
        logger.warning("[Push] Missing reply target owner for %s", target_txhash)
        return
    if target_owner == poster_addr.lower():
        return
    root_post_id = _get_root_post_id(target_txhash)
    if not root_post_id:
        logger.warning("[Push] Missing root_post_id for reply target %s", target_txhash)
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
        return
    _fire_and_forget(_do_mentions_push, poster_addr, poster_username, content, tx_hash, target_txhash)

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
        return

    if post_owner == awarder_addr.lower():
        return
    _fire_and_forget(_do_award_push, awarder_addr, awarder_username, post_owner, target_txhash, award_type)


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


def reset_push_budget(owner: str) -> None:
    """Reset push budget to MAX_BUDGET. Called from mark_inbox_viewed."""
    if not PUSH_NOTIFICATIONS_ENABLED:
        return
    try:
        with connect_db(timeout=3.0, busy_timeout_ms=5000) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO push_budget (owner, remaining, last_reset_at)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (owner) DO UPDATE SET
                        remaining = %s,
                        last_reset_at = %s
                    """,
                    (owner.lower(), MAX_BUDGET, int(time.time()), MAX_BUDGET, int(time.time())),
                )
    except Exception as e:
        logger.error("[Push] Budget reset failed for %s: %s", owner, e)
