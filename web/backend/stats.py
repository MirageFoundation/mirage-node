from __future__ import annotations

"""Mirage-owned analytics: the half of the funnel the chain cannot see.

Core model (see the Server Stats Redesign plan):

- One identity per person. It starts as an anonymous visitor id (sent by every
  client in the ``X-Mirage-Visitor`` header) and is bound to a Mirage address on
  authentication. The address always wins and is the only durable merge key.
  IP is never identity.
- ``stats_events`` stores only the signals the chain lacks: ``visit`` and
  ``engagement`` (active browsing, including logged-out lurkers).
- ``stats_visitors`` maps a (hashed) visitor id to its bound address plus
  first/last-touch UTM attribution.
- On-chain facts (signups, posts, comments) stay authoritative in the indexer
  and are queried there, never duplicated here.
- Every metric is a query over an arbitrary ``[start, end]`` window.
"""

import re
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import requests
from flask import has_request_context, request

from chain import get_connected_peers
from client_ip import hash_visitor_id
from db import connect_backend_db, connect_db

VISITOR_HEADER = "X-Mirage-Visitor"

DAY = 86400

# Active-browsing signals: a request to one of these means the person is
# actually reading Mirage content, not just loading a shell or polling config.
# Anything else under /api/ is a bare "visit". The implementer's discretion per
# the plan -- these are the sensible content-fetch endpoints.
_ENGAGEMENT_PREFIXES = (
    "/api/get_posts",
    "/api/get_comments",
    "/api/get_profile",
    "/api/get_topics",
    "/api/search",
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


# ── Identity ────────────────────────────────────────────────────────────────


def _clean_addr(addr: Optional[str]) -> Optional[str]:
    a = (addr or "").strip().lower()
    if not a or a == "guest":
        return None
    return a


def extract_identity() -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Return (visitor_hash, address, platform) for the current request.

    visitor_hash is the salted hash of the ``X-Mirage-Visitor`` header (raw id
    never stored). address is the authed Mirage address when present. Either may
    be None; if both are None the caller records nothing identity-bearing.
    """
    if not has_request_context():
        return None, None, None
    raw_visitor = request.headers.get(VISITOR_HEADER, "") if request else ""
    visitor_hash = hash_visitor_id(raw_visitor)
    address = _clean_addr(request.args.get("address") or request.args.get("admin_address"))
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


# ── Recording (throttled per identity; fails hard like update_user_last_seen) ─


def record_request_event(path: str) -> None:
    """Record a visit/engagement for the current request, deduped per minute.

    Fails hard like update_user_last_seen: a broken analytics write surfaces as a
    request error rather than being silently swallowed.
    """
    event_type = _classify_event(path)
    if event_type is None:
        return
    visitor_hash, address, platform = extract_identity()
    if not visitor_hash and not address:
        return
    identity_key = address or visitor_hash
    now_ts = int(time.time())
    if _should_skip(f"{identity_key}:{event_type}", now_ts):
        return
    _persist_event(event_type, visitor_hash, address, platform, path, now_ts)


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
                    """
                    INSERT INTO stats_visitors (visitor_hash, address, platform, first_seen_at, last_seen_at)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (visitor_hash) DO UPDATE SET
                        last_seen_at = EXCLUDED.last_seen_at,
                        platform = COALESCE(stats_visitors.platform, EXCLUDED.platform),
                        address = COALESCE(EXCLUDED.address, stats_visitors.address)
                    """,
                    (visitor_hash, address, platform, now_ts, now_ts),
                )
            elif address:
                # Authed client with no visitor header (e.g. v1 mobile). Track the
                # address as its own identity so logged-in DAU/retention still work.
                cur.execute(
                    """
                    INSERT INTO stats_visitors (visitor_hash, address, platform, first_seen_at, last_seen_at)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (visitor_hash) DO UPDATE SET
                        last_seen_at = EXCLUDED.last_seen_at,
                        platform = COALESCE(stats_visitors.platform, EXCLUDED.platform)
                    """,
                    (f"addr:{address}", address, platform, now_ts, now_ts),
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
    else the raw visitor hash. This dedupes an anonymous lurker and their later
    logged-in self into one identity.
    """
    return (
        "SELECT COALESCE(e.address, v.address, e.visitor_hash) AS ident, e.event_type, e.created_at, "
        "(e.address IS NOT NULL OR v.address IS NOT NULL) AS has_addr "
        "FROM stats_events e LEFT JOIN stats_visitors v ON v.visitor_hash = e.visitor_hash "
        "WHERE e.created_at BETWEEN %s AND %s"
    )


def _growth_visitors(start: int, end: int) -> Tuple[int, int, int]:
    """(visitors, active, signups) for the tracked-visitor population in the window:
    distinct identities with any event; with an engagement event (DAU-style); and
    that are bound to a Mirage address (i.e. signed up / authenticated). All three
    come from the same population so signups/visitors is a real conversion <= 100%."""
    with connect_backend_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                WITH ev AS ({_resolved_event_cte()})
                SELECT
                    COUNT(DISTINCT ident) FILTER (WHERE ident IS NOT NULL),
                    COUNT(DISTINCT ident) FILTER (WHERE ident IS NOT NULL AND event_type = 'engagement'),
                    COUNT(DISTINCT ident) FILTER (WHERE ident IS NOT NULL AND has_addr)
                FROM ev
                """,
                (start, end),
            )
            row = cur.fetchone()
            return int(row[0] or 0), int(row[1] or 0), int(row[2] or 0)


def _new_users(start: int, end: int) -> int:
    with connect_db() as conn:
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
    target are comments; votes live in a separate table and never count."""
    with connect_db() as conn:
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


def _retention(start: int, end: int, now_ts: int) -> Dict[str, Any]:
    """Forward retention for the signup cohort in [start, end].

    For each horizon N in {7,14,30}: eligible = users whose signup + N days has
    elapsed; retained = eligible users active (engagement OR post/comment) at or
    after signup + N days. "Active later" combines the indexer (posts/comments)
    and the backend engagement log, joined by address.
    """
    with connect_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT LOWER(owner), created_at FROM profiles
                WHERE created_at BETWEEN %s AND %s AND (deleted_at IS NULL OR deleted_at = 0)
                """,
                (start, end),
            )
            cohort = {r[0]: int(r[1]) for r in cur.fetchall()}

    result = {"cohort_size": len(cohort)}
    if not cohort:
        for n in (7, 14, 30):
            result[f"d{n}"] = {"eligible": 0, "retained": 0, "rate": 0.0}
        return result

    addrs = list(cohort.keys())
    last_chain: Dict[str, int] = {}
    with connect_db() as conn:
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
                "SELECT address, MAX(created_at) FROM stats_events "
                "WHERE event_type = 'engagement' AND address = ANY(%s) GROUP BY 1",
                (addrs,),
            )
            for r in cur.fetchall():
                if r[0]:
                    last_engage[r[0]] = int(r[1] or 0)

    for n in (7, 14, 30):
        horizon = n * DAY
        eligible = 0
        retained = 0
        for addr, signup_at in cohort.items():
            if signup_at + horizon > now_ts:
                continue  # not enough time elapsed to judge N-day retention
            eligible += 1
            last_active = max(last_chain.get(addr, 0), last_engage.get(addr, 0))
            if last_active >= signup_at + horizon:
                retained += 1
        rate = round(retained / eligible, 4) if eligible else 0.0
        result[f"d{n}"] = {"eligible": eligible, "retained": retained, "rate": rate}
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
        with connect_db() as conn:
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


def _daily_series(start: int, end: int) -> List[Dict[str, int]]:
    """Per-day buckets across the window for charting. On-chain lines (new_users,
    posts, comments) have full history; tracked lines (active) only populate after
    visitor tracking began. Always returns one point per day so charts are dense."""
    new_users_by_day: Dict[int, int] = {}
    posts_by_day: Dict[int, Tuple[int, int, int]] = {}
    with connect_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT (created_at/%s)*%s AS d, COUNT(*) FROM profiles "
                "WHERE created_at BETWEEN %s AND %s AND (deleted_at IS NULL OR deleted_at = 0) GROUP BY d",
                (DAY, DAY, start, end),
            )
            new_users_by_day = {int(d): int(n) for d, n in cur.fetchall()}
            cur.execute(
                "SELECT (created_at/%s)*%s AS d, "
                "COUNT(*) FILTER (WHERE COALESCE(target,'') = ''), "
                "COUNT(*) FILTER (WHERE COALESCE(target,'') <> ''), "
                "COUNT(DISTINCT LOWER(owner)) "
                "FROM posts WHERE created_at BETWEEN %s AND %s GROUP BY d",
                (DAY, DAY, start, end),
            )
            posts_by_day = {int(d): (int(p), int(c), int(ctrb)) for d, p, c, ctrb in cur.fetchall()}

    active_by_day: Dict[int, int] = {}
    with connect_backend_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"WITH ev AS ({_resolved_event_cte()}) "
                "SELECT (created_at/%s)*%s AS d, "
                "COUNT(DISTINCT ident) FILTER (WHERE event_type = 'engagement') "
                "FROM ev GROUP BY d",
                (start, end, DAY, DAY),
            )
            active_by_day = {int(d): int(a) for d, a in cur.fetchall()}

    out: List[Dict[str, int]] = []
    day = (start // DAY) * DAY
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
                "active": active_by_day.get(day, 0),
            }
        )
        day += DAY
    return out


def _tracking_since() -> Optional[int]:
    """Unix ts of the earliest recorded event on this node — i.e. when Mirage
    visitor tracking effectively began here. None if nothing is recorded yet.

    Everything in the "tracked" bucket (visitors/active/signups/campaigns and the
    browsing half of retention) is necessarily blank before this instant. On-chain
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
    visitors, active, signups = _growth_visitors(start, end)
    new_users = _new_users(start, end)
    contributors, posts, comments = _contributors(start, end)
    return {
        "server": local_server_label(),
        "generated_at": now_ts,
        # When visitor tracking began on this node. Tracked metrics below are
        # blank before this; on-chain metrics have full history regardless.
        "tracking_since": _tracking_since(),
        "window": {"start": start, "end": end},
        # Tracked-visitor funnel (only counts activity since visitor tracking began).
        "growth": {
            "visitors": visitors,
            "active": active,
            "signups": signups,
            "signup_conversion": round(signups / visitors, 4) if visitors else 0.0,
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
        "series": _daily_series(start, end),
    }


# ── Server discovery ─────────────────────────────────────────────────────────


def _normalize_moniker_url(moniker: str) -> Optional[str]:
    """Return an http(s) base URL for a validator moniker, or None if it is not
    a usable web endpoint. Mirrors the normalization used by get_peers."""
    m = (moniker or "").strip()
    if not m:
        return None
    if m.startswith("http://") or m.startswith("https://"):
        return m.rstrip("/")
    if any(ch.isspace() for ch in m) or "/" in m:
        return None
    host = m
    if ":" in host:
        maybe_host, maybe_port = host.rsplit(":", 1)
        if maybe_host and maybe_port.isdigit():
            host = maybe_host
    host = host.strip(".")
    if host.count(".") < 1:
        return None
    labels = host.split(".")
    for label in labels:
        if not label or len(label) > 63 or label[0] == "-" or label[-1] == "-":
            return None
        if not re.fullmatch(r"[A-Za-z0-9-]+", label):
            return None
    # Reject raw IPv4 (all-numeric labels): an IP is never a stats endpoint and
    # must never be used as an identity/merge key.
    if all(label.isdigit() for label in labels):
        return None
    return f"https://{m}"


def aggregate_server_stats(ok_servers: List[Dict[str, Any]], start: int, end: int) -> Dict[str, Any]:
    """Combine per-server stats into one fleet view.

    Two different combine rules, because the data has two natures:

    - Tracked metrics (visitors/active/signups, daily ``active``) are per-node:
      a visitor hits exactly one server, so these are SUMMED.
    - On-chain metrics (new_users/contributors/posts/comments, the retention
      cohort, daily new_users/posts/comments) are global chain facts that every
      full node indexes identically. Summing them would count the same rows once
      per server (~Nx inflation), so we take the MAX across nodes instead — max,
      not first, so a node that is behind/catching up can't drag the fleet view
      below the most-synced node's complete count.
    """
    visitors = active = signups = new_users = 0
    contributors = posts = comments = 0
    cohort_size = 0
    ret = {"d7": [0, 0], "d14": [0, 0], "d30": [0, 0]}  # [eligible, retained] (max)
    series_by_day: Dict[int, Dict[str, int]] = {}
    for s in ok_servers:
        st = s.get("stats") or {}
        g = st.get("growth") or {}
        o = st.get("onchain") or {}
        r = st.get("retention") or {}
        # tracked → sum
        visitors += int(g.get("visitors") or 0)
        active += int(g.get("active") or 0)
        signups += int(g.get("signups") or 0)
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
            agg_pt = series_by_day.setdefault(t, {"t": t, "new_users": 0, "contributors": 0, "posts": 0, "comments": 0, "active": 0})
            agg_pt["active"] += int(pt.get("active") or 0)  # tracked → sum
            for f in ("new_users", "contributors", "posts", "comments"):  # on-chain → max
                agg_pt[f] = max(agg_pt[f], int(pt.get(f) or 0))
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
            "active": active,
            "signups": signups,
            "signup_conversion": round(signups / visitors, 4) if visitors else 0.0,
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
    }


def _peer_endpoint(ip: str) -> Optional[str]:
    """Resolve a P2P peer IP to a fleet web endpoint, or None to skip it.

    A node that has its own domain serves https and redirects plain http to it
    (and is already represented by its validator domain moniker, possibly behind
    a CDN whose DNS hides the origin IP). A domain-less node (e.g. a bare
    validator) instead serves the API directly over http on its IP. So we probe
    http://<ip>: a redirect to https means "domain node — skip" (avoids listing
    the same node twice); a direct response means "this IP is its only endpoint".
    """
    if not re.fullmatch(r"(\d{1,3}\.){3}\d{1,3}", ip):
        return None
    try:
        resp = requests.get(f"http://{ip}/api/get_peers", timeout=3, allow_redirects=False)
    except requests.RequestException:
        # Can't probe it (down/filtered); surface it so it shows as unreachable
        # rather than silently vanishing from the fleet.
        return f"http://{ip}"
    if 300 <= resp.status_code < 400 and resp.headers.get("Location", "").startswith("https"):
        return None
    return f"http://{ip}"


def discover_servers() -> List[str]:
    """Full fleet, derived entirely from live network state — never hardcoded.

    Two on-chain sources are unioned: validators (which advertise a web endpoint
    via a domain moniker when they have one) and the same connected_peers list the
    /network page uses (every P2P peer this node sees, by network IP). Domain nodes
    come from validators; domain-less nodes are reached at their peer IP (see
    _peer_endpoint, which skips peers that are really a domain node). Server-to-
    server fan-out only; a peer IP is never an identity/merge key.
    """
    servers: List[str] = []
    seen: set = set()

    def add(url: Optional[str]) -> None:
        if not url:
            return
        key = url.rstrip("/")
        if key not in seen:
            seen.add(key)
            servers.append(key)

    local = local_server_label()
    if local.startswith("http"):
        add(local)

    with connect_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT value FROM chain_stats WHERE key = 'validators'")
            row = cur.fetchone()
            validators = row[0] if row and isinstance(row[0], list) else []

    for v in validators:
        add(_normalize_moniker_url(v.get("moniker", "") if isinstance(v, dict) else ""))

    for p in get_connected_peers():
        if not isinstance(p, dict):
            continue
        url = _normalize_moniker_url(p.get("moniker", ""))
        if not url:
            url = _peer_endpoint(str(p.get("ip", "") or "").strip())
        add(url)

    return servers
