from __future__ import annotations

"""Mirage-owned analytics: the half of the funnel the chain cannot see.

Core model (see the Server Stats Redesign plan):

- One identity per user. It starts as an anonymous visitor id (sent by every
  client in the ``X-Mirage-Visitor`` header) and is bound to a Mirage address on
  authentication. The address always wins and is the only durable merge key.
  IP is never identity.
- ``stats_events`` stores request activity signals: ``visit`` and
  ``engagement`` (active logged-in use such as browsing or voting).
- ``stats_visitors`` maps a (hashed) visitor id to its bound address plus
  first/last-touch UTM attribution.
- On-chain facts (signups, posts, comments) stay authoritative in the indexer
  and are queried there, never duplicated here.
- Every metric is a query over an arbitrary ``[start, end]`` window.
"""

import logging
import re
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from flask import g, has_request_context, request

from client_ip import hash_visitor_id
from db import connect_backend_db, connect_db
from fleet_url import validate_fleet_endpoint
from settings import STATS_FLEET_ROSTER

logger = logging.getLogger(__name__)

# Statement budget for the admin aggregations in this module. They are the only
# callers that relied on connect_db(timeout=STATS_QUERY_TIMEOUT_SEC)'s default, and unlike a feed query they are
# genuinely allowed to be slow: several scan the full posts or votes table for an
# infrequent, admin-facing dashboard. Stated explicitly so arming the default
# timeout does not quietly convert a slow dashboard into a broken one.
STATS_QUERY_TIMEOUT_SEC = 60.0

VISITOR_HEADER = "X-Mirage-Visitor"

DAY = 86400

# Lookback for the DAU baseline. Fixed, never derived from the selected window.
DAU_WINDOW_DAYS = 30

# Active-use signals: a request to one of these means a human is looking at
# Mirage content. Anyone logged in who does anything to view Mirage is active,
# so the list covers reading you can only do with the app open — including the
# ones the client sends on your behalf while you read (seen_posts as you scroll,
# mark_inbox_viewed as you read replies). Anything else under /api/ is a bare
# "visit": config polling, push-token housekeeping, health, landing-page stats.
#
# Keeping the read markers out of this list silently deleted most lurkers.
# "Lurker" needs one event that is both engagement and provably logged in, and
# for a large slice of users those two facts never land on the same row: their
# get_posts reads are unsigned (and, from a header-less client, not recorded at
# all), while their signed reads were classified as mere visits. On 2026-08-10
# prod counted 25 lurkers when 86 distinct addresses had signed seen_posts that
# day against 54 contributors.
_ENGAGEMENT_PREFIXES = (
    "/api/bootstrap",
    "/api/get_posts",
    "/api/get_comments",
    "/api/get_comment_context",
    "/api/get_inbox",
    "/api/get_profile",
    "/api/get_topics",
    "/api/get_user_posts",
    "/api/mark_inbox_viewed",
    "/api/search",
    "/api/seen_posts",
    "/api/core/vote",
)

# Paths that are never browsing (our own analytics/admin plumbing, health).
_SKIP_PREFIXES = (
    "/api/admin/stats",
    "/api/stats/",
)

# Throttle event/visitor writes per identity+type, like user_last_seen, to keep
# one write per identity per minute instead of one per request.
EVENT_THROTTLE_SECONDS = 60
EVENT_CACHE_TTL = 3600
EVENT_CACHE_MAX = 100000
_event_cache: dict[str, int] = {}
_event_cache_lock = threading.Lock()
_event_cache_last_cleanup = 0

# stats_visitors.address_bound_at on upsert: keep the first bind, except when
# the device switches accounts — then the new address was bound now, and the
# previous account's window ends here. A row arriving without an address (every
# unsigned read) leaves the stored value untouched.
_BOUND_AT_ON_CONFLICT = (
    "CASE WHEN EXCLUDED.address IS NOT NULL "
    "AND EXCLUDED.address IS DISTINCT FROM stats_visitors.address "
    "THEN EXCLUDED.address_bound_at "
    "ELSE COALESCE(stats_visitors.address_bound_at, EXCLUDED.address_bound_at) END"
)


# ── Identity ────────────────────────────────────────────────────────────────


def _clean_addr(addr: Optional[str]) -> Optional[str]:
    a = (addr or "").strip().lower()
    if not a or a == "guest":
        return None
    return a


def _raw_visitor_id() -> str:
    """The client's analytics id: the header when it can be set, else the body.

    `navigator.sendBeacon` cannot attach custom headers, so the seen_posts
    beacon — our single best proof that a signed-in user is reading — arrived
    with no visitor id at all. The device never bound to the address, and one
    human split into two identities: an address that looked logged in but idle,
    and a browser hash that looked like a logged-out visitor. Both halves were
    counted, so lurkers were understated and visitors overstated by the same
    people.

    The body is exactly as client-supplied as the header, so reading it grants
    no trust the header did not already have: the value is salted and hashed
    before storage and authenticates nothing. The JSON guard keeps this off the
    upload paths, where parsing the body here would be wasteful and pointless.
    """
    raw = (request.headers.get(VISITOR_HEADER, "") or "").strip()
    if raw:
        return raw
    if request.mimetype != "application/json":
        return ""
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return ""
    return str(body.get("visitor_id") or "").strip()


def extract_identity(signed_request_verified: bool = False) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Return (visitor_hash, address, platform) for the current request.

    visitor_hash is the salted hash of the ``X-Mirage-Visitor`` header (raw id
    never stored). address is set only when the request proved it, by signing
    with the matching public key; a query ``address`` is client-supplied text
    and binding it here let anyone attribute their browsing to another account.
    Either may be None; if both are None the caller records nothing
    identity-bearing.
    """
    if not has_request_context():
        return None, None, None
    visitor_hash = hash_visitor_id(_raw_visitor_id())
    # Merely presenting a public key proves nothing. The shared signature
    # verifier records the derived address only after cryptographic validation,
    # and only a successful route's after-request hook opts into attribution.
    address = _clean_addr(getattr(g, "verified_request_address", None)) if signed_request_verified else None
    platform = _platform_from_request()
    return visitor_hash, address, platform


def _platform_from_request() -> Optional[str]:
    explicit = (request.headers.get("X-Mirage-Platform", "") or "").strip().lower()
    if explicit in ("ios", "android", "web"):
        return explicit
    ua = (request.headers.get("User-Agent", "") or "").lower()
    if not ua:
        return None
    if "android" in ua:
        return "android"
    if "iphone" in ua or "ipad" in ua or "ios" in ua:
        return "ios"
    return "web"


def _classify_event(path: str) -> Optional[str]:
    """'engagement' for content browsing, 'visit' for other /api loads, else None."""
    if not path or not path.startswith("/api/"):
        return None
    for p in _SKIP_PREFIXES:
        if path.startswith(p):
            return None
    for p in _ENGAGEMENT_PREFIXES:
        if path.startswith(p):
            return "engagement"
    return "visit"


def _should_skip(key: str, now_ts: int) -> bool:
    global _event_cache_last_cleanup
    with _event_cache_lock:
        last = _event_cache.get(key)
        if last and now_ts - last < EVENT_THROTTLE_SECONDS:
            return True
        _event_cache[key] = now_ts
        if len(_event_cache) > EVENT_CACHE_MAX or now_ts - _event_cache_last_cleanup > EVENT_CACHE_TTL:
            cutoff = now_ts - EVENT_CACHE_TTL
            for k, v in list(_event_cache.items()):
                if v < cutoff:
                    _event_cache.pop(k, None)
            _event_cache_last_cleanup = now_ts
    return False


def _release_failed_throttle(key: str, now_ts: int) -> None:
    with _event_cache_lock:
        if _event_cache.get(key) == now_ts:
            _event_cache.pop(key, None)


# ── Recording (throttled per identity; fails hard like update_user_last_seen) ─


def record_request_event(path: str, signed_request_verified: bool = False) -> None:
    """Record a visit/engagement for the current request, deduped per minute.

    Fails hard like update_user_last_seen: a broken analytics write surfaces as a
    request error rather than being silently swallowed.
    """
    event_type = _classify_event(path)
    if event_type is None:
        return
    visitor_hash, address, platform = extract_identity(signed_request_verified=signed_request_verified)
    if not visitor_hash and not address:
        return
    identity_key = address or visitor_hash
    now_ts = int(time.time())
    throttle_key = f"{identity_key}:{event_type}"
    if _should_skip(throttle_key, now_ts):
        return
    try:
        _persist_event(event_type, visitor_hash, address, platform, path, now_ts)
    except Exception:
        _release_failed_throttle(throttle_key, now_ts)
        raise


def bind_verified_request_identity(path: str) -> None:
    """Bind a successful signed request to its derived address.

    The anonymous event was already recorded by the before-request hook. When a
    visitor id exists, updating its mapping is enough for metrics to resolve
    that event to the address without inserting a duplicate.
    """
    event_type = _classify_event(path)
    if event_type is None:
        return
    visitor_hash, address, platform = extract_identity(signed_request_verified=True)
    if not address:
        return
    now_ts = int(time.time())
    if not visitor_hash:
        throttle_key = f"{address}:{event_type}"
        if _should_skip(throttle_key, now_ts):
            return
        try:
            _persist_event(event_type, None, address, platform, path, now_ts)
        except Exception:
            _release_failed_throttle(throttle_key, now_ts)
            raise
        return
    with connect_backend_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO stats_visitors
                    (visitor_hash, address, address_bound_at, platform, first_seen_at, last_seen_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (visitor_hash) DO UPDATE SET
                    address = EXCLUDED.address,
                    last_seen_at = EXCLUDED.last_seen_at,
                    platform = COALESCE(stats_visitors.platform, EXCLUDED.platform),
                    address_bound_at = {_BOUND_AT_ON_CONFLICT}
                """,
                (visitor_hash, address, now_ts, platform, now_ts, now_ts),
            )


def _persist_event(
    event_type: str,
    visitor_hash: Optional[str],
    address: Optional[str],
    platform: Optional[str],
    path: str,
    now_ts: int,
) -> None:
    with connect_backend_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO stats_events (created_at, event_type, visitor_hash, address, path)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (now_ts, event_type, visitor_hash, address, path[:200]),
            )
            if visitor_hash:
                cur.execute(
                    f"""
                    INSERT INTO stats_visitors
                        (visitor_hash, address, address_bound_at, platform, first_seen_at, last_seen_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (visitor_hash) DO UPDATE SET
                        last_seen_at = EXCLUDED.last_seen_at,
                        platform = COALESCE(stats_visitors.platform, EXCLUDED.platform),
                        address = COALESCE(EXCLUDED.address, stats_visitors.address),
                        address_bound_at = {_BOUND_AT_ON_CONFLICT}
                    """,
                    (visitor_hash, address, now_ts if address else None, platform, now_ts, now_ts),
                )
            elif address:
                # Authed client with no visitor header (e.g. v1 mobile). Track the
                # address as its own identity so logged-in DAU/retention still work.
                cur.execute(
                    """
                    INSERT INTO stats_visitors
                        (visitor_hash, address, address_bound_at, platform, first_seen_at, last_seen_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (visitor_hash) DO UPDATE SET
                        last_seen_at = EXCLUDED.last_seen_at,
                        platform = COALESCE(stats_visitors.platform, EXCLUDED.platform),
                        address_bound_at = COALESCE(stats_visitors.address_bound_at, EXCLUDED.address_bound_at)
                    """,
                    (f"addr:{address}", address, now_ts, platform, now_ts, now_ts),
                )


def record_attribution(raw_visitor_id: str, platform: Optional[str], utm: Dict[str, str], ref: str = "") -> bool:
    """Persist first-touch UTM for a visitor. Idempotent: first-touch is never
    overwritten; last-touch always updates. Returns True if the visitor row was
    created or updated.
    """
    visitor_hash = hash_visitor_id(raw_visitor_id)
    if not visitor_hash:
        return False
    now_ts = int(time.time())
    src = (utm.get("utm_source") or "").strip()[:200] or None
    med = (utm.get("utm_medium") or "").strip()[:200] or None
    camp = (utm.get("utm_campaign") or "").strip()[:200] or None
    cont = (utm.get("utm_content") or "").strip()[:200] or None
    term = (utm.get("utm_term") or "").strip()[:200] or None
    ref_v = (ref or "").strip()[:300] or None
    has_touch = any([src, med, camp, cont, term, ref_v])
    with connect_backend_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO stats_visitors (
                    visitor_hash, platform, first_seen_at, last_seen_at,
                    first_touch_at, first_touch_utm_source, first_touch_utm_medium,
                    first_touch_utm_campaign, first_touch_utm_content, first_touch_utm_term,
                    first_touch_ref, last_touch_at, last_touch_utm_source, last_touch_utm_campaign
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (visitor_hash) DO UPDATE SET
                    last_seen_at = EXCLUDED.last_seen_at,
                    platform = COALESCE(stats_visitors.platform, EXCLUDED.platform),
                    last_touch_at = CASE WHEN %s THEN EXCLUDED.last_touch_at ELSE stats_visitors.last_touch_at END,
                    last_touch_utm_source = CASE WHEN %s THEN EXCLUDED.last_touch_utm_source ELSE stats_visitors.last_touch_utm_source END,
                    last_touch_utm_campaign = CASE WHEN %s THEN EXCLUDED.last_touch_utm_campaign ELSE stats_visitors.last_touch_utm_campaign END,
                    first_touch_at = COALESCE(stats_visitors.first_touch_at, EXCLUDED.first_touch_at),
                    first_touch_utm_source = COALESCE(stats_visitors.first_touch_utm_source, EXCLUDED.first_touch_utm_source),
                    first_touch_utm_medium = COALESCE(stats_visitors.first_touch_utm_medium, EXCLUDED.first_touch_utm_medium),
                    first_touch_utm_campaign = COALESCE(stats_visitors.first_touch_utm_campaign, EXCLUDED.first_touch_utm_campaign),
                    first_touch_utm_content = COALESCE(stats_visitors.first_touch_utm_content, EXCLUDED.first_touch_utm_content),
                    first_touch_utm_term = COALESCE(stats_visitors.first_touch_utm_term, EXCLUDED.first_touch_utm_term),
                    first_touch_ref = COALESCE(stats_visitors.first_touch_ref, EXCLUDED.first_touch_ref)
                """,
                (
                    visitor_hash,
                    platform,
                    now_ts,
                    now_ts,
                    now_ts if has_touch else None,
                    src,
                    med,
                    camp,
                    cont,
                    term,
                    ref_v,
                    now_ts if has_touch else None,
                    src,
                    camp,
                    has_touch,
                    has_touch,
                    has_touch,
                ),
            )
    return True


# ── Metrics (queries over [start, end]) ──────────────────────────────────────


def _resolved_event_cte() -> str:
    """SQL CTE that resolves each event to its canonical identity.

    identity = event address, else the address the visitor is now bound to,
    else the raw visitor hash.

    ``has_addr`` means the event was made by a logged-in user. An event proves
    that itself only when the request was signed, which reads never are — so
    requiring it would count every logged-in reader as a logged-out visitor.
    The second clause reads the device's binding instead, restricted to events
    at or after the bind: that keeps a device's pre-login browsing out of the
    logged-in counts, so old anonymous events still do not become active users
    after a later signup.

    The address on a profile-view event is the profile being looked at, not the
    viewer, so it is nulled out here: rows recorded while the query address was
    still treated as identity self-correct instead of permanently inflating the
    logged-in counts with everyone who got viewed.
    """
    viewer_addr = "(CASE WHEN e.path LIKE '/api/get_profile%%' THEN NULL ELSE e.address END)"
    bound_before_event = (
        "(v.address IS NOT NULL AND v.address_bound_at IS NOT NULL AND e.created_at >= v.address_bound_at)"
    )
    return (
        "SELECT COALESCE(" + viewer_addr + ", v.address, e.visitor_hash) AS ident, "
        "e.event_type, e.created_at, "
        "(" + viewer_addr + " IS NOT NULL OR " + bound_before_event + ") AS has_addr "
        "FROM stats_events e LEFT JOIN stats_visitors v ON v.visitor_hash = e.visitor_hash "
        "WHERE e.created_at BETWEEN %s AND %s"
    )


def _growth_visitors(start: int, end: int) -> Tuple[int, int]:
    """(visitors, lurkers) for the tracked population in the window.

    Two of the three audience categories (the third, contributors, is a chain
    fact from the indexer):
    - visitors: logged-out identities with any tracked event.
    - lurkers: logged-in identities with an engagement event who did NOT
      post/comment in the same window (contributors are excluded so the three
      categories never overlap).
    """
    contributor_addresses = _contributor_addresses(start, end)
    with connect_backend_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                WITH ev AS ({_resolved_event_cte()})
                SELECT
                    ident,
                    BOOL_OR(has_addr),
                    BOOL_OR(event_type = 'engagement' AND has_addr)
                FROM ev
                WHERE ident IS NOT NULL
                GROUP BY ident
                """,
                (start, end),
            )
            rows = cur.fetchall()
    visitors = lurkers = 0
    for ident, has_addr, has_engagement in rows:
        ident_lc = str(ident or "").lower()
        if has_addr:
            if has_engagement and ident_lc not in contributor_addresses:
                lurkers += 1
        else:
            visitors += 1
    return visitors, lurkers


def _contributor_addresses(start: int, end: int) -> set[str]:
    with connect_db(timeout=STATS_QUERY_TIMEOUT_SEC) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT LOWER(owner)
                FROM posts
                WHERE created_at BETWEEN %s AND %s
                """,
                (start, end),
            )
            return {str(r[0]).lower() for r in cur.fetchall() if r and r[0]}


def _new_users(start: int, end: int) -> int:
    with connect_db(timeout=STATS_QUERY_TIMEOUT_SEC) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) FROM profiles
                WHERE created_at BETWEEN %s AND %s AND (deleted_at IS NULL OR deleted_at = 0)
                """,
                (start, end),
            )
            return int(cur.fetchone()[0] or 0)


def _contributors(start: int, end: int) -> Tuple[int, int, int]:
    """(contributors, posts, comments) in window from the indexer. Posts with a
    target are comments; votes are active usage, not contribution."""
    with connect_db(timeout=STATS_QUERY_TIMEOUT_SEC) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    COUNT(DISTINCT LOWER(owner)),
                    COUNT(*) FILTER (WHERE COALESCE(target, '') = ''),
                    COUNT(*) FILTER (WHERE COALESCE(target, '') <> '')
                FROM posts
                WHERE created_at BETWEEN %s AND %s
                """,
                (start, end),
            )
            row = cur.fetchone()
            return int(row[0] or 0), int(row[1] or 0), int(row[2] or 0)


def _matured_cohort_window(start: int, end: int, now_ts: int, n_days: int) -> Tuple[int, int]:
    """Signup window used to judge N-day retention.

    Prefer the selected ``[start, end]``, clipped so every member is at least
    N days old. When the whole selection is still too young for that horizon
    (e.g. preset "7d" / "30d" asked for D30), slide a same-width window back
    so D7 / D14 / D30 always report a real matured cohort instead of 0/0.
    """
    horizon = n_days * DAY
    c_end = min(end, now_ts - horizon)
    c_start = start
    if c_end <= c_start:
        width = max(end - start, 0)
        c_end = now_ts - horizon
        c_start = c_end - width
    return c_start, c_end


def _retention(start: int, end: int, now_ts: int) -> Dict[str, Any]:
    """Forward retention for matured signup cohorts matching the selected range.

    For each horizon N in {7,14,30} the cohort is ``_matured_cohort_window`` —
    same width as ``[start, end]`` when possible, always old enough to judge.
    Retained = cohort members active (engagement OR post/comment) at or after
    signup + N days. "Active later" combines the indexer (posts/comments) and
    the backend engagement log, joined by address.
    """
    with connect_db(timeout=STATS_QUERY_TIMEOUT_SEC) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) FROM profiles
                WHERE created_at BETWEEN %s AND %s AND (deleted_at IS NULL OR deleted_at = 0)
                """,
                (start, end),
            )
            cohort_size = int(cur.fetchone()[0] or 0)

    windows = {n: _matured_cohort_window(start, end, now_ts, n) for n in (7, 14, 30)}
    span_start = min(w[0] for w in windows.values())
    span_end = max(w[1] for w in windows.values())
    logger.debug(
        "stats.retention windows start=%s end=%s now=%s d7=%s d14=%s d30=%s selected_cohort=%s",
        start,
        end,
        now_ts,
        windows[7],
        windows[14],
        windows[30],
        cohort_size,
    )

    profiles: Dict[str, int] = {}
    with connect_db(timeout=STATS_QUERY_TIMEOUT_SEC) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT LOWER(owner), created_at FROM profiles
                WHERE created_at BETWEEN %s AND %s AND (deleted_at IS NULL OR deleted_at = 0)
                """,
                (span_start, span_end),
            )
            profiles = {r[0]: int(r[1]) for r in cur.fetchall()}

    result: Dict[str, Any] = {"cohort_size": cohort_size}
    if not profiles:
        for n in (7, 14, 30):
            result[f"d{n}"] = {"eligible": 0, "retained": 0, "rate": 0.0}
        return result

    addrs = list(profiles.keys())
    last_chain: Dict[str, int] = {}
    with connect_db(timeout=STATS_QUERY_TIMEOUT_SEC) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT LOWER(owner), MAX(created_at) FROM posts WHERE LOWER(owner) = ANY(%s) GROUP BY 1",
                (addrs,),
            )
            for r in cur.fetchall():
                last_chain[r[0]] = int(r[1] or 0)

    last_engage: Dict[str, int] = {}
    with connect_backend_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COALESCE(e.address, v.address) AS address, MAX(e.created_at) "
                "FROM stats_events e LEFT JOIN stats_visitors v ON v.visitor_hash = e.visitor_hash "
                "WHERE e.event_type = 'engagement' AND COALESCE(e.address, v.address) = ANY(%s) "
                "GROUP BY 1",
                (addrs,),
            )
            for r in cur.fetchall():
                if r[0]:
                    last_engage[r[0]] = int(r[1] or 0)

    for n in (7, 14, 30):
        horizon = n * DAY
        c_start, c_end = windows[n]
        eligible = 0
        retained = 0
        for addr, signup_at in profiles.items():
            if signup_at < c_start or signup_at > c_end:
                continue
            eligible += 1
            last_active = max(last_chain.get(addr, 0), last_engage.get(addr, 0))
            if last_active >= signup_at + horizon:
                retained += 1
        rate = round(retained / eligible, 4) if eligible else 0.0
        result[f"d{n}"] = {"eligible": eligible, "retained": retained, "rate": rate}
        logger.debug(
            "stats.retention.horizon d%s window=[%s,%s] eligible=%s retained=%s rate=%s",
            n,
            c_start,
            c_end,
            eligible,
            retained,
            rate,
        )
    return result


def _campaigns(start: int, end: int, limit: int = 50) -> List[Dict[str, Any]]:
    """First-touch campaign overlay for visitors first seen in [start, end].

    Funnel per campaign: visitors -> signups (distinct bound Mirage addresses) ->
    contributors (those addresses that posted/commented in the window). A single
    Mirage address is never double-counted across visitor IDs. Retention is left to
    the global date-range cohort; campaign attribution is an overlay on top of it."""
    campaign_addrs: Dict[Tuple[str, str], set] = {}
    with connect_backend_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    COALESCE(first_touch_utm_source, ''),
                    COALESCE(first_touch_utm_campaign, ''),
                    COUNT(*),
                    COUNT(DISTINCT LOWER(address))
                FROM stats_visitors
                WHERE first_touch_utm_campaign IS NOT NULL
                  AND first_seen_at BETWEEN %s AND %s
                GROUP BY 1, 2
                ORDER BY COUNT(*) DESC
                LIMIT %s
                """,
                (start, end, limit),
            )
            agg = cur.fetchall()
            # Bound-address set per campaign so we can resolve contributors below.
            cur.execute(
                """
                SELECT
                    COALESCE(first_touch_utm_source, ''),
                    COALESCE(first_touch_utm_campaign, ''),
                    LOWER(address)
                FROM stats_visitors
                WHERE first_touch_utm_campaign IS NOT NULL
                  AND address IS NOT NULL
                  AND first_seen_at BETWEEN %s AND %s
                """,
                (start, end),
            )
            for src, camp, addr in cur.fetchall():
                if addr:
                    campaign_addrs.setdefault((src, camp), set()).add(addr)

    # Which of those addresses actually contributed (post/comment) in the window.
    all_addrs = sorted({a for addrs in campaign_addrs.values() for a in addrs})
    contributor_set: set = set()
    if all_addrs:
        with connect_db(timeout=STATS_QUERY_TIMEOUT_SEC) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT DISTINCT LOWER(owner) FROM posts "
                    "WHERE LOWER(owner) = ANY(%s) AND created_at BETWEEN %s AND %s",
                    (all_addrs, start, end),
                )
                contributor_set = {r[0] for r in cur.fetchall()}

    out = []
    for src, camp, visitors_raw, signups_raw in agg:
        visitors = int(visitors_raw or 0)
        signups = int(signups_raw or 0)
        addrs = campaign_addrs.get((src, camp), set())
        contributors = sum(1 for a in addrs if a in contributor_set)
        out.append(
            {
                "source": src,
                "campaign": camp,
                "visitors": visitors,
                "signups": signups,
                "contributors": contributors,
                "signup_conversion": round(signups / visitors, 4) if visitors else 0.0,
                "contributor_conversion": round(contributors / signups, 4) if signups else 0.0,
            }
        )
    return out


def _contributors_by_day(start: int, end: int) -> Dict[int, set[str]]:
    """Distinct on-chain posters/commenters per UTC day."""
    out: Dict[int, set[str]] = {}
    with connect_db(timeout=STATS_QUERY_TIMEOUT_SEC) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT (created_at/%s)*%s AS d, LOWER(owner) "
                "FROM posts WHERE created_at BETWEEN %s AND %s GROUP BY d, LOWER(owner)",
                (DAY, DAY, start, end),
            )
            for d, owner in cur.fetchall():
                out.setdefault(int(d), set()).add(str(owner).lower())
    return out


def _lurkers_by_day(start: int, end: int, contributors_by_day: Dict[int, set[str]]) -> Dict[int, int]:
    """Signed-in identities with tracked engagement per UTC day, excluding that
    day's contributors so the two categories never count the same person twice."""
    out: Dict[int, int] = {}
    with connect_backend_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"WITH ev AS ({_resolved_event_cte()}) "
                "SELECT (created_at/%s)*%s AS d, "
                "ident, "
                "BOOL_OR(has_addr), "
                "BOOL_OR(event_type = 'engagement' AND has_addr) "
                "FROM ev WHERE ident IS NOT NULL GROUP BY d, ident",
                (start, end, DAY, DAY),
            )
            for d, ident, has_addr, has_engagement in cur.fetchall():
                day_key = int(d)
                ident_lc = str(ident or "").lower()
                if has_addr and has_engagement and ident_lc not in contributors_by_day.get(day_key, set()):
                    out[day_key] = out.get(day_key, 0) + 1
    return out


def _daily_series(start: int, end: int, now_ts: int) -> List[Dict[str, int]]:
    """Per-day buckets across the window for charting. On-chain lines (new_users,
    contributors, posts, comments) have full history; tracked lines (lurkers) only
    populate after visitor tracking began. Each bucket also carries per-signup-day
    D7 cohort retention (d7_retained / d7_eligible_users): of the users who signed
    up that day whose 7-day horizon has elapsed, how many were still active at/after
    signup+7d. Always returns one point per day so charts are dense.

    Buckets are whole UTC days, so the queries start at the first bucket's own
    midnight rather than at the window start. A preset like "7d" starts at
    now-7*24h, which is the middle of a day: counting only that day's tail
    rendered the leftmost bar as a near-empty stub (2026-08-11, prod: 8/4 showed
    0 of its 6 signups, because all 6 landed before the 23:33 UTC cutoff). The
    window still governs which days are shown; it must not decide how much of a
    shown day counts.
    """
    series_start = (start // DAY) * DAY
    new_users_by_day: Dict[int, int] = {}
    posts_by_day: Dict[int, Tuple[int, int, int]] = {}
    cohort: Dict[str, int] = {}
    with connect_db(timeout=STATS_QUERY_TIMEOUT_SEC) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT (created_at/%s)*%s AS d, COUNT(*) FROM profiles "
                "WHERE created_at BETWEEN %s AND %s AND (deleted_at IS NULL OR deleted_at = 0) GROUP BY d",
                (DAY, DAY, series_start, end),
            )
            new_users_by_day = {int(d): int(n) for d, n in cur.fetchall()}
            cur.execute(
                "SELECT (created_at/%s)*%s AS d, "
                "COUNT(*) FILTER (WHERE COALESCE(target,'') = ''), "
                "COUNT(*) FILTER (WHERE COALESCE(target,'') <> ''), "
                "COUNT(DISTINCT LOWER(owner)) "
                "FROM posts WHERE created_at BETWEEN %s AND %s GROUP BY d",
                (DAY, DAY, series_start, end),
            )
            posts_by_day = {int(d): (int(p), int(c), int(ctrb)) for d, p, c, ctrb in cur.fetchall()}
            cur.execute(
                "SELECT LOWER(owner), created_at FROM profiles "
                "WHERE created_at BETWEEN %s AND %s AND (deleted_at IS NULL OR deleted_at = 0)",
                (series_start, end),
            )
            cohort = {r[0]: int(r[1]) for r in cur.fetchall()}

    contributors_by_day = _contributors_by_day(series_start, end)
    lurkers_by_day = _lurkers_by_day(series_start, end, contributors_by_day)

    # Last-active timestamp per cohort member (on-chain post/comment OR tracked
    # engagement), used to judge whether each signup was retained at D7.
    last_active: Dict[str, int] = {}
    if cohort:
        addrs = list(cohort.keys())
        with connect_db(timeout=STATS_QUERY_TIMEOUT_SEC) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT LOWER(owner), MAX(created_at) FROM posts WHERE LOWER(owner) = ANY(%s) GROUP BY 1",
                    (addrs,),
                )
                for o, mx in cur.fetchall():
                    last_active[o] = int(mx or 0)
        with connect_backend_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COALESCE(e.address, v.address) AS address, MAX(e.created_at) "
                    "FROM stats_events e LEFT JOIN stats_visitors v ON v.visitor_hash = e.visitor_hash "
                    "WHERE e.event_type = 'engagement' AND COALESCE(e.address, v.address) = ANY(%s) "
                    "GROUP BY 1",
                    (addrs,),
                )
                for a, mx in cur.fetchall():
                    if a:
                        last_active[a] = max(last_active.get(a, 0), int(mx or 0))

    d7_eligible_by_day: Dict[int, int] = {}
    d7_retained_by_day: Dict[int, int] = {}
    horizon = 7 * DAY
    for addr, signup_at in cohort.items():
        if signup_at + horizon > now_ts:
            continue  # D7 horizon hasn't elapsed yet for this signup
        day = (signup_at // DAY) * DAY
        d7_eligible_by_day[day] = d7_eligible_by_day.get(day, 0) + 1
        if last_active.get(addr, 0) >= signup_at + horizon:
            d7_retained_by_day[day] = d7_retained_by_day.get(day, 0) + 1

    out: List[Dict[str, int]] = []
    day = series_start
    last = (end // DAY) * DAY
    while day <= last:
        posts, comments, contributors = posts_by_day.get(day, (0, 0, 0))
        out.append(
            {
                "t": day,
                "new_users": new_users_by_day.get(day, 0),
                "contributors": contributors,
                "posts": posts,
                "comments": comments,
                "lurkers": lurkers_by_day.get(day, 0),
                "d7_eligible": d7_eligible_by_day.get(day, 0),
                "d7_retained": d7_retained_by_day.get(day, 0),
            }
        )
        day += DAY
    return out


def _summarize_dau(days: List[Dict[str, int]]) -> Dict[str, Any]:
    """Attach active/avg/peak/latest to a per-day active series.

    Split out from `_daily_active` because the fleet aggregate has to redo the
    arithmetic after merging nodes: averaging each node's average would weight a
    quiet node the same as a busy one.
    """
    rows = [
        {
            "t": int(d.get("t") or 0),
            "contributors": int(d.get("contributors") or 0),
            "lurkers": int(d.get("lurkers") or 0),
            "active": int(d.get("contributors") or 0) + int(d.get("lurkers") or 0),
        }
        for d in days
    ]
    actives = [r["active"] for r in rows]
    return {
        "window_days": len(rows),
        "days": rows,
        "avg": round(sum(actives) / len(actives), 1) if actives else 0.0,
        "peak": max(actives) if actives else 0,
        "latest": actives[-1] if actives else 0,
    }


def _daily_active(now_ts: int) -> Dict[str, Any]:
    """Signed-in actives per UTC day over the last `DAU_WINDOW_DAYS` complete days.

    Takes no window on purpose. DAU is the baseline you read every other number
    against, so it has to mean the same thing whichever period the selector is
    on — a "DAU" that silently becomes a 24h total when you pick 24h and a
    monthly total when you pick 30d is what made the dashboard's active-user
    numbers unreadable in the first place.

    Active = the same population as the Active users tile (contributors from the
    chain + lurkers from tracked engagement), just resolved per day instead of
    per window. Today is excluded because it is still building.
    """
    today = (now_ts // DAY) * DAY
    start = today - DAU_WINDOW_DAYS * DAY
    end = today - 1
    contributors_by_day = _contributors_by_day(start, end)
    lurkers_by_day = _lurkers_by_day(start, end, contributors_by_day)
    days = [
        {
            "t": day,
            "contributors": len(contributors_by_day.get(day, ())),
            "lurkers": lurkers_by_day.get(day, 0),
        }
        for day in range(start, today, DAY)
    ]
    return _summarize_dau(days)


def _tracking_since() -> Optional[int]:
    """Unix ts of the earliest recorded event on this node — i.e. when Mirage
    visitor tracking effectively began here. None if nothing is recorded yet.

    Everything in the "tracked" bucket (visitors/lurkers/campaigns and the
    tracked-engagement half of retention) is necessarily blank before this instant. On-chain
    metrics are unaffected: the chain has full history regardless.
    """
    with connect_backend_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT MIN(created_at) FROM stats_events")
            row = cur.fetchone()
            return int(row[0]) if row and row[0] is not None else None


def local_server_label() -> str:
    import os

    domain = (os.environ.get("DOMAIN", "") or "").strip()
    if domain:
        return f"https://{domain}"
    moniker = (os.environ.get("MONIKER", "") or "").strip()
    if moniker:
        return moniker
    if has_request_context() and request:
        return request.host_url.rstrip("/")
    return "local"


def compute_local_stats(start: int, end: int) -> Dict[str, Any]:
    """Full metric bundle for this server over [start, end]."""
    now_ts = int(time.time())
    visitors, lurkers = _growth_visitors(start, end)
    new_users = _new_users(start, end)
    contributors, posts, comments = _contributors(start, end)
    return {
        "server": local_server_label(),
        "generated_at": now_ts,
        # When visitor tracking began on this node. Tracked metrics below are
        # blank before this; on-chain metrics have full history regardless.
        "tracking_since": _tracking_since(),
        "window": {"start": start, "end": end},
        # Tracked audience (only counts activity since visitor tracking began).
        # contributors is a chain fact and lives in "onchain" below.
        "growth": {
            "visitors": visitors,
            "lurkers": lurkers,
        },
        # On-chain facts over the window (full history, independent of visitor tracking).
        "onchain": {
            "new_users": new_users,
            "contributors": contributors,
            "posts": posts,
            "comments": comments,
            "posts_per_contributor": round((posts + comments) / contributors, 2) if contributors else 0.0,
        },
        "retention": _retention(start, end, now_ts),
        "campaigns": _campaigns(start, end),
        "series": _daily_series(start, end, now_ts),
        # Fixed 30-day baseline, deliberately not scoped to [start, end].
        "dau30": _daily_active(now_ts),
    }


# ── Server discovery ─────────────────────────────────────────────────────────


def _normalize_moniker_url(moniker: str) -> Optional[str]:
    """Return an http(s) base URL for a validator moniker, or None to skip it.

    A moniker is attacker-influenced text, so a schemed one gets the same
    hostname and address checks as a bare one. An IP is never a stats endpoint
    and must never be used as an identity/merge key.
    """
    endpoint = validate_fleet_endpoint(moniker)
    return endpoint.url if endpoint else None


def aggregate_server_stats(ok_servers: List[Dict[str, Any]], start: int, end: int) -> Dict[str, Any]:
    """Combine per-server stats into one fleet view.

    Two different combine rules, because the data has two natures:

    - Tracked metrics (visitors/lurkers, daily ``lurkers``) are per-node:
      a visitor hits exactly one server, so these are SUMMED.
    - On-chain metrics (new_users/contributors/posts/comments, the retention
      cohort, daily new_users/posts/comments) are global chain facts that every
      full node indexes identically. Summing them would count the same rows once
      per server (~Nx inflation), so we take the MAX across nodes instead — max,
      not first, so a node that is behind/catching up can't drag the fleet view
      below the most-synced node's complete count.
    """
    visitors = lurkers = new_users = 0
    contributors = posts = comments = 0
    cohort_size = 0
    ret = {"d7": [0, 0], "d14": [0, 0], "d30": [0, 0]}  # [eligible, retained] (max)
    series_by_day: Dict[int, Dict[str, int]] = {}
    dau_by_day: Dict[int, Dict[str, int]] = {}
    for s in ok_servers:
        st = s.get("stats") or {}
        g = st.get("growth") or {}
        o = st.get("onchain") or {}
        r = st.get("retention") or {}
        # tracked → sum
        visitors += int(g.get("visitors") or 0)
        lurkers += int(g.get("lurkers") or 0)
        # on-chain → max (identical across nodes; never sum)
        new_users = max(new_users, int(o.get("new_users") or 0))
        contributors = max(contributors, int(o.get("contributors") or 0))
        posts = max(posts, int(o.get("posts") or 0))
        comments = max(comments, int(o.get("comments") or 0))
        cohort_size = max(cohort_size, int(r.get("cohort_size") or 0))
        for k in ("d7", "d14", "d30"):
            d = r.get(k) or {}
            ret[k][0] = max(ret[k][0], int(d.get("eligible") or 0))
            ret[k][1] = max(ret[k][1], int(d.get("retained") or 0))
        for pt in st.get("series") or []:
            t = int(pt.get("t") or 0)
            agg_pt = series_by_day.setdefault(
                t,
                {
                    "t": t,
                    "new_users": 0,
                    "contributors": 0,
                    "posts": 0,
                    "comments": 0,
                    "lurkers": 0,
                    "d7_eligible": 0,
                    "d7_retained": 0,
                },
            )
            agg_pt["lurkers"] += int(pt.get("lurkers") or 0)  # tracked → sum
            for f in ("new_users", "contributors", "posts", "comments", "d7_eligible", "d7_retained"):  # on-chain → max
                agg_pt[f] = max(agg_pt[f], int(pt.get(f) or 0))
        for pt in (st.get("dau30") or {}).get("days") or []:
            t = int(pt.get("t") or 0)
            agg_dau = dau_by_day.setdefault(t, {"t": t, "contributors": 0, "lurkers": 0})
            agg_dau["lurkers"] += int(pt.get("lurkers") or 0)  # tracked → sum
            agg_dau["contributors"] = max(agg_dau["contributors"], int(pt.get("contributors") or 0))  # on-chain → max
    retention = {"cohort_size": cohort_size}
    for k in ("d7", "d14", "d30"):
        eligible, retained = ret[k]
        retention[k] = {
            "eligible": eligible,
            "retained": retained,
            "rate": round(retained / eligible, 4) if eligible else 0.0,
        }
    # Earliest moment any reporting node began tracking — the fleet-wide boundary
    # before which all tracked metrics are blank.
    since_vals = [
        int((s.get("stats") or {}).get("tracking_since"))
        for s in ok_servers
        if (s.get("stats") or {}).get("tracking_since")
    ]
    tracking_since = min(since_vals) if since_vals else None
    return {
        "window": {"start": start, "end": end},
        "servers_counted": len(ok_servers),
        "tracking_since": tracking_since,
        "growth": {
            "visitors": visitors,
            "lurkers": lurkers,
        },
        "onchain": {
            "new_users": new_users,
            "contributors": contributors,
            "posts": posts,
            "comments": comments,
            "posts_per_contributor": round((posts + comments) / contributors, 2) if contributors else 0.0,
        },
        "retention": retention,
        "series": [series_by_day[t] for t in sorted(series_by_day)],
        "dau30": _summarize_dau([dau_by_day[t] for t in sorted(dau_by_day)]),
    }


def fleet_fanout_targets() -> List[str]:
    """Destinations the admin stats fan-out may forward the admin's proof to.

    This used to be ``discover_servers()``, which unioned validator monikers with
    live P2P peer monikers and IPs. Every one of those is self-declared text from
    an unauthenticated source: peering with a node and setting your moniker to a
    domain you own put your host in this list, and the aggregate route then POSTed
    the admin's live signature proof to it. The proof is deliberately replayable
    across fleet nodes, so one harvested copy worked against siblings that had
    never seen the nonce.

    The roster is operator configuration instead. Nothing an outsider can write
    reaches this list, and https is enforced by the parser rather than preferred,
    since the discovery path also synthesised ``http://`` endpoints.
    """
    targets: List[str] = []
    seen: set = set()
    for url in STATS_FLEET_ROSTER:
        key = url.rstrip("/")
        if key not in seen:
            seen.add(key)
            targets.append(key)
    return targets


def _coerce_count(value: Any, field: str) -> int:
    """Coerce a peer-supplied counter, rejecting anything that is not a number.

    ``aggregate_server_stats`` used bare ``int()`` on these outside any try/except,
    so a peer returning a non-numeric field raised straight out of the admin
    endpoint and 500'd it for as long as that peer stayed in the list.
    """
    if value is None:
        return 0
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a number, got {type(value).__name__}")
    ivalue = int(value)
    if ivalue < 0:
        raise ValueError(f"{field} must not be negative, got {ivalue}")
    return ivalue


# A peer can otherwise return an arbitrarily long series and make the aggregation
# allocate on its behalf. A window is at most a few years of daily points.
MAX_PEER_SERIES_POINTS = 4000


def validate_peer_stats(payload: Any) -> Dict[str, Any]:
    """Return a normalized copy of a peer's stats response, or raise ValueError.

    Only known keys survive, every counter is checked to be a number, and the two
    series are length-bounded. Validating before the merge is what keeps a hostile
    or simply broken peer from deciding the shape of the admin's dashboard.
    """
    if not isinstance(payload, dict):
        raise ValueError(f"peer stats must be an object, got {type(payload).__name__}")

    def _section(key: str) -> Dict[str, Any]:
        # Checked before defaulting: `or {}` would swallow a falsy wrong type such
        # as [] or 0 and treat a malformed section as an absent one.
        raw = payload.get(key)
        if raw is None:
            return {}
        if not isinstance(raw, dict):
            raise ValueError(f"{key} must be an object, got {type(raw).__name__}")
        return raw

    growth_raw, onchain_raw, retention_raw = _section("growth"), _section("onchain"), _section("retention")

    growth = {f: _coerce_count(growth_raw.get(f), f"growth.{f}") for f in ("visitors", "lurkers")}
    onchain = {
        f: _coerce_count(onchain_raw.get(f), f"onchain.{f}") for f in ("new_users", "contributors", "posts", "comments")
    }
    retention: Dict[str, Any] = {
        "cohort_size": _coerce_count(retention_raw.get("cohort_size"), "retention.cohort_size")
    }
    for k in ("d7", "d14", "d30"):
        bucket = retention_raw.get(k)
        if bucket is None:
            bucket = {}
        if not isinstance(bucket, dict):
            raise ValueError(f"retention.{k} must be an object, got {type(bucket).__name__}")
        retention[k] = {
            "eligible": _coerce_count(bucket.get("eligible"), f"retention.{k}.eligible"),
            "retained": _coerce_count(bucket.get("retained"), f"retention.{k}.retained"),
        }

    def _points(raw: Any, label: str, fields: tuple[str, ...]) -> List[Dict[str, int]]:
        if raw is None:
            return []
        if not isinstance(raw, list):
            raise ValueError(f"{label} must be a list, got {type(raw).__name__}")
        if len(raw) > MAX_PEER_SERIES_POINTS:
            raise ValueError(f"{label} has {len(raw)} points, limit {MAX_PEER_SERIES_POINTS}")
        out: List[Dict[str, int]] = []
        for i, pt in enumerate(raw):
            if not isinstance(pt, dict):
                raise ValueError(f"{label}[{i}] must be an object, got {type(pt).__name__}")
            point = {"t": _coerce_count(pt.get("t"), f"{label}[{i}].t")}
            for f in fields:
                point[f] = _coerce_count(pt.get(f), f"{label}[{i}].{f}")
            out.append(point)
        return out

    series = _points(
        payload.get("series"),
        "series",
        ("new_users", "contributors", "posts", "comments", "lurkers", "d7_eligible", "d7_retained"),
    )
    dau30_raw = payload.get("dau30")
    if dau30_raw is None:
        dau30_raw = {}
    if not isinstance(dau30_raw, dict):
        raise ValueError(f"dau30 must be an object, got {type(dau30_raw).__name__}")
    dau_days = _points(dau30_raw.get("days"), "dau30.days", ("contributors", "lurkers"))

    return {
        "growth": growth,
        "onchain": onchain,
        "retention": retention,
        "series": series,
        "dau30": {"days": dau_days},
    }
