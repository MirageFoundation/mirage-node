from __future__ import annotations

"""Admin stats: signed access, attribution ingest, and pure metric logic.

These cover the half of the funnel the chain can't see. The admin endpoints are
strictly admin-only (level >= 100), so the integration tests assert the negative
paths (no/invalid signature, and a valid signature from a non-admin wallet ->
403). The pure-function tests verify metric math, server discovery normalization,
and event classification without a live DB.
"""

import os
import sys

from tests.common import (
    _pass,
    _fail,
    _skip,
    _get,
    _post,
    _b64,
    _rand_str,
    _now_ms,
    _fresh_nonce,
    _generate_wallet,
    sign_canonical,
)


def _signed_stats_payload(wallet, ts: int, nonce: int) -> dict:
    addr = str(wallet.address())
    pub = wallet.public_key().public_key_bytes
    signed = f"stats:{addr.lower()}:{ts}:{nonce}".encode("utf-8")
    sig = sign_canonical(wallet, signed)
    return {
        "pubkey": _b64(pub),
        "signature": _b64(sig),
        "address": addr,
        "timestamp": ts,
        "envelope_nonce": str(nonce),
    }


def test_stats_admin_auth(backend):
    # 1. Missing signature fields -> 400.
    code, resp = _post(f"{backend}/api/admin/stats/export", {"start": 0, "end": _now_ms() // 1000})
    if code == 400:
        _pass("stats.export_requires_auth", code=code)
    else:
        _fail("stats.export_requires_auth", f"expected 400, got {code}: {resp}")

    # 2. Valid signature from a non-admin wallet -> 403 (signature verified, but
    #    the caller is not an admin). This proves both the signature path and the
    #    admin gate in one shot.
    wallet = _generate_wallet()
    ts = _now_ms()
    nonce = _fresh_nonce()
    payload = _signed_stats_payload(wallet, ts, nonce)
    payload.update({"start": 0, "end": ts // 1000})
    code, resp = _post(f"{backend}/api/admin/stats/export", payload)
    if code == 403:
        _pass("stats.export_non_admin_forbidden", code=code)
    else:
        _fail("stats.export_non_admin_forbidden", f"expected 403, got {code}: {resp}")

    # 3. Invalid signature (signed for a different nonce) -> 400. Signature is
    #    verified before the replay guard, so this fails closed.
    ts2 = _now_ms()
    good_nonce = _fresh_nonce()
    payload2 = _signed_stats_payload(wallet, ts2, good_nonce)
    payload2["envelope_nonce"] = str(_fresh_nonce())  # mismatch -> signature invalid
    payload2.update({"start": 0, "end": ts2 // 1000})
    code, resp = _post(f"{backend}/api/admin/stats/export", payload2)
    if code == 400:
        _pass("stats.export_invalid_signature", code=code)
    else:
        _fail("stats.export_invalid_signature", f"expected 400, got {code}: {resp}")

    # 4. Aggregate endpoint is gated the same way.
    code, resp = _post(f"{backend}/api/admin/stats/aggregate", {"start": 0, "end": ts // 1000})
    if code == 400:
        _pass("stats.aggregate_requires_auth", code=code)
    else:
        _fail("stats.aggregate_requires_auth", f"expected 400, got {code}: {resp}")


def test_stats_attribution(backend):
    # Missing visitor_id -> 400.
    code, resp = _post(f"{backend}/api/stats/visitor_attribution", {"utm_source": "x"})
    if code == 400:
        _pass("stats.attribution_requires_visitor", code=code)
    else:
        _fail("stats.attribution_requires_visitor", f"expected 400, got {code}: {resp}")

    # First-touch ingest succeeds and is idempotent (second call also ok).
    vid = f"test-visitor-{_rand_str(10)}"
    body = {"visitor_id": vid, "platform": "web", "utm_source": "instagram", "utm_campaign": f"camp_{_rand_str(4)}"}
    code, resp = _post(f"{backend}/api/stats/visitor_attribution", body)
    ok1 = code == 200 and isinstance(resp, dict) and resp.get("ok") is True
    code2, resp2 = _post(f"{backend}/api/stats/visitor_attribution", body)
    ok2 = code2 == 200 and isinstance(resp2, dict) and resp2.get("ok") is True
    if ok1 and ok2:
        _pass("stats.attribution_first_touch_idempotent")
    else:
        _fail("stats.attribution_first_touch_idempotent", f"call1=({code},{resp}) call2=({code2},{resp2})")


def test_stats_pure(backend):
    """Pure metric/discovery/classification logic, no DB required."""
    backend_src = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "web",
        "backend",
    )
    if backend_src not in sys.path:
        sys.path.insert(0, backend_src)
    # client_ip fails hard without a salt, which used to skip this whole
    # category on a host run. The salt only has to exist for these pure
    # functions; the production fail-hard path is asserted by hash_salt.
    os.environ.setdefault("CLIENT_HASH_SALT", "00" * 16)
    try:
        import stats as st
        from client_ip import hash_visitor_id
    except Exception as e:
        _fail("stats.pure", f"backend modules not importable: {e}")
        return

    # Moniker -> URL normalization for server discovery.
    cases = {
        "mirage.vote": "https://mirage.vote",
        "https://mirage.talk": "https://mirage.talk",
        "192.0.2.1": None,  # raw IP is never a stats endpoint
        "no-dot": None,
    }
    bad = {m: st._normalize_moniker_url(m) for m, exp in cases.items() if st._normalize_moniker_url(m) != exp}
    if not bad:
        _pass("stats.moniker_normalization")
    else:
        _fail("stats.moniker_normalization", f"mismatches: {bad}")

    # Event classification: engagement vs visit vs ignored.
    klass = {
        "/api/get_posts": "engagement",
        "/api/get_comments": "engagement",
        "/api/get_profile": "engagement",
        "/api/search": "engagement",
        "/api/core/vote": "engagement",
        "/api/get_node_config": "visit",
        "/api/admin/stats/export": None,
        "/static/app.js": None,
    }
    cbad = {p: st._classify_event(p) for p, exp in klass.items() if st._classify_event(p) != exp}
    if not cbad:
        _pass("stats.event_classification")
    else:
        _fail("stats.event_classification", f"mismatches: {cbad}")

    # The query-time CTE must still null the profile-view address, so rows
    # recorded while a query address counted as identity self-correct instead of
    # permanently inflating the logged-in counts with everyone who got viewed.
    cte = st._resolved_event_cte()
    if "/api/get_profile" in cte:
        _pass("stats.resolved_cte_profile_guard")
    else:
        _fail("stats.resolved_cte_profile_guard", f"guard missing from CTE: {cte}")

    # Growth buckets: visitors are logged-out identities; lurkers are
    # logged-in engagement identities that did not post/comment in-window.
    class _FakeCursor:
        def execute(self, *_args, **_kwargs):
            return None

        def fetchall(self):
            return [
                ("visitor_hash", False, False),
                ("later_bound_addr", False, False),
                ("addr_lurker", True, True),
                ("addr_contrib", True, True),
                ("addr_config_only", True, False),
            ]

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    class _FakeConn:
        def cursor(self):
            return _FakeCursor()

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    orig_backend_db = st.connect_backend_db
    orig_contributors = st._contributor_addresses
    try:
        st.connect_backend_db = lambda: _FakeConn()
        st._contributor_addresses = lambda _start, _end: {"addr_contrib"}
        buckets = st._growth_visitors(0, 100)
    finally:
        st.connect_backend_db = orig_backend_db
        st._contributor_addresses = orig_contributors
    if buckets == (2, 1):
        _pass("stats.growth_buckets")
    else:
        _fail("stats.growth_buckets", f"expected (2, 1), got {buckets}")

    # Reads are unsigned, so a logged-in reader's events carry no address of
    # their own. Before the device binding was consulted, every one of them fell
    # through to the logged-out branch: on Aug 10 2026 web lurkers went to zero
    # fleet-wide and the same users inflated "logged-out visitors" instead. This
    # exercises the real SQL, because the fix lives in the CTE, not in Python.
    #
    # Window sits far in the future so it can never overlap live traffic, and
    # so the rows cannot move MIN(created_at) while they exist — _tracking_since
    # reads that, and these categories run in parallel against a shared DB.
    win_start, win_end = 4_000_000_000, 4_000_000_999
    fixtures = [
        # (visitor_hash, bound_at, [event times]) — one device bound mid-window
        # with a read after the bind, one bound only after the window's reads.
        ("t_bound_before", 4_000_000_500, [4_000_000_400, 4_000_000_600]),
        ("t_bound_after", 4_000_000_900, [4_000_000_400]),
    ]
    try:
        with st.connect_backend_db() as conn:
            with conn.cursor() as cur:
                for vh, ba, times in fixtures:
                    cur.execute(
                        "INSERT INTO stats_visitors "
                        "(visitor_hash, address, address_bound_at, platform, first_seen_at, last_seen_at) "
                        "VALUES (%s, %s, %s, 'web', %s, %s) ON CONFLICT (visitor_hash) DO UPDATE SET "
                        "address = EXCLUDED.address, address_bound_at = EXCLUDED.address_bound_at",
                        (vh, f"mirage1{vh}", ba, win_start, win_end),
                    )
                    for t in times:
                        cur.execute(
                            "INSERT INTO stats_events (created_at, event_type, visitor_hash, address, path) "
                            "VALUES (%s, 'engagement', %s, NULL, '/api/get_posts')",
                            (t, vh),
                        )
        orig_contributors = st._contributor_addresses
        try:
            st._contributor_addresses = lambda _s, _e: set()
            got = st._growth_visitors(win_start, win_end)
        finally:
            st._contributor_addresses = orig_contributors
        # The device bound mid-window is a lurker (its post-bind read counts);
        # the one bound later is still just a logged-out visitor.
        if got == (1, 1):
            _pass("stats.lurker_uses_device_binding")
        else:
            _fail("stats.lurker_uses_device_binding", f"expected (1 visitor, 1 lurker), got {got}")

        # Same rows with no bind timestamp reproduce the broken state exactly:
        # both logged-in readers read as logged-out visitors. This is also the
        # standing limit of the fix — a device we cannot date the bind for stays
        # invisible until it signs something, rather than being credited with
        # history we cannot demonstrate.
        with st.connect_backend_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE stats_visitors SET address_bound_at = NULL WHERE visitor_hash = ANY(%s)",
                    ([f[0] for f in fixtures],),
                )
        try:
            st._contributor_addresses = lambda _s, _e: set()
            undated = st._growth_visitors(win_start, win_end)
        finally:
            st._contributor_addresses = orig_contributors
        if undated == (2, 0):
            _pass("stats.lurker_requires_dated_binding")
        else:
            _fail("stats.lurker_requires_dated_binding", f"expected (2 visitors, 0 lurkers), got {undated}")
    finally:
        hashes = [f[0] for f in fixtures]
        with st.connect_backend_db() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM stats_events WHERE visitor_hash = ANY(%s)", (hashes,))
                cur.execute("DELETE FROM stats_visitors WHERE visitor_hash = ANY(%s)", (hashes,))

    # Visitor hashing: deterministic, salted, None on empty.
    h1 = hash_visitor_id("abc")
    h2 = hash_visitor_id("abc")
    if h1 and h1 == h2 and hash_visitor_id("") is None and hash_visitor_id("abc") != hash_visitor_id("abd"):
        _pass("stats.visitor_hash_deterministic")
    else:
        _fail("stats.visitor_hash_deterministic", f"h1={h1} h2={h2}")

    # Retention cohort windows: when the selected range is too young for a
    # horizon (e.g. "last 30d" asked for D30), slide a same-width window back so
    # the horizon still has a matured cohort instead of 0/0. Historical ranges
    # that are already old enough stay put (only clipped at now - N days).
    now = 1_700_000_000
    day = st.DAY
    # Last-30d preset vs D30 → slide back to [now-60d, now-30d]
    w30 = st._matured_cohort_window(now - 30 * day, now, now, 30)
    # Last-7d preset vs D30 → [now-37d, now-30d]
    w7 = st._matured_cohort_window(now - 7 * day, now, now, 30)
    # Historical January-style range already past D30 → keep (clipped only)
    hist_start, hist_end = now - 90 * day, now - 60 * day
    wh = st._matured_cohort_window(hist_start, hist_end, now, 30)
    # Partially young window (last 45d) vs D30 → clip end, keep start
    wp = st._matured_cohort_window(now - 45 * day, now, now, 30)
    window_checks = [
        w30 == (now - 60 * day, now - 30 * day),
        w7 == (now - 37 * day, now - 30 * day),
        wh == (hist_start, hist_end),
        wp == (now - 45 * day, now - 30 * day),
    ]
    if all(window_checks):
        _pass("stats.matured_cohort_window")
    else:
        _fail("stats.matured_cohort_window", f"w30={w30} w7={w7} wh={wh} wp={wp} checks={window_checks}")

    # Aggregation sums additive metrics and recomputes rates from summed parts.
    servers = [
        {
            "status": "ok",
            "stats": {
                "growth": {"visitors": 100, "lurkers": 40},
                "onchain": {"new_users": 80, "contributors": 5, "posts": 20, "comments": 30},
                "retention": {
                    "cohort_size": 10,
                    "d7": {"eligible": 8, "retained": 4},
                    "d14": {"eligible": 6, "retained": 3},
                    "d30": {"eligible": 4, "retained": 1},
                },
            },
        },
        {
            "status": "ok",
            "stats": {
                "growth": {"visitors": 50, "lurkers": 10},
                "onchain": {"new_users": 20, "contributors": 5, "posts": 0, "comments": 10},
                "retention": {
                    "cohort_size": 5,
                    "d7": {"eligible": 2, "retained": 1},
                    "d14": {"eligible": 0, "retained": 0},
                    "d30": {"eligible": 0, "retained": 0},
                },
            },
        },
    ]
    # Add per-day series so we can assert series combine rules too: on-chain
    # fields max, tracked 'lurkers' sums.
    servers[0]["stats"]["series"] = [
        {"t": 0, "new_users": 80, "posts": 20, "comments": 30, "lurkers": 40, "d7_eligible": 10, "d7_retained": 6}
    ]
    servers[1]["stats"]["series"] = [
        {"t": 0, "new_users": 20, "posts": 0, "comments": 10, "lurkers": 10, "d7_eligible": 3, "d7_retained": 1}
    ]
    agg = st.aggregate_server_stats(servers, 0, 100)
    checks = [
        # tracked metrics SUM across nodes
        agg["growth"]["visitors"] == 150,
        agg["growth"]["lurkers"] == 50,
        # on-chain metrics are identical per node -> MAX, never summed
        agg["onchain"]["new_users"] == 80,
        agg["onchain"]["contributors"] == 5,
        agg["onchain"]["posts"] == 20,
        agg["onchain"]["comments"] == 30,
        agg["onchain"]["posts_per_contributor"] == round(50 / 5, 2),
        # retention cohort/eligible/retained are chain-derived -> MAX
        agg["retention"]["cohort_size"] == 10,
        agg["retention"]["d7"]["eligible"] == 8,
        agg["retention"]["d7"]["retained"] == 4,
        agg["retention"]["d7"]["rate"] == round(4 / 8, 4),
        agg["servers_counted"] == 2,
        # series: on-chain max, tracked lurkers summed
        agg["series"][0]["new_users"] == 80,
        agg["series"][0]["posts"] == 20,
        agg["series"][0]["comments"] == 30,
        agg["series"][0]["lurkers"] == 50,
        # per-day D7 cohort outcome is chain-derived -> MAX
        agg["series"][0]["d7_eligible"] == 10,
        agg["series"][0]["d7_retained"] == 6,
    ]
    if all(checks):
        _pass("stats.aggregate_math")
    else:
        _fail("stats.aggregate_math", f"agg={agg} checks={checks}")

    # Fleet tracking_since is the earliest across reporting nodes; None when no
    # node has recorded anything yet (so the UI can say "tracking hasn't started").
    s_a = {"status": "ok", "stats": {"tracking_since": 5000}}
    s_b = {"status": "ok", "stats": {"tracking_since": 3000}}
    s_none = {"status": "ok", "stats": {}}
    earliest = st.aggregate_server_stats([s_a, s_b, s_none], 0, 100)["tracking_since"]
    blank = st.aggregate_server_stats([s_none], 0, 100)["tracking_since"]
    if earliest == 3000 and blank is None:
        _pass("stats.aggregate_tracking_since")
    else:
        _fail("stats.aggregate_tracking_since", f"earliest={earliest} blank={blank}")
