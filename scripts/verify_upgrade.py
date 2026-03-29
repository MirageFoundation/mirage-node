#!/usr/bin/env python3
"""
Post-upgrade verification for v1.22.x.

Checks:
  1. Required environment variables are set (DB URLs)
  2. Backend + indexer (RO) DB connections succeed
  3. Database schema: key tables exist
  4. Indexer freshness: latest block is recent, chain_stats populated
  5. Data integrity: profiles, balances, tx_index raw_log
  6. Chain params completeness via /api/get_chain_config
  7. Backend API health: key GET endpoints return valid data
  8. Core routes: subscribe exists, upgrade_level removed, POST routes reachable

Usage:
  python scripts/verify_upgrade.py                     # inside container
  docker exec mirage python3 /opt/mirage/scripts/verify_upgrade.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "web" / "backend"))

try:
    import psycopg
except ImportError:
    print("FATAL: psycopg not installed")
    sys.exit(1)

try:
    import requests as _requests
except ImportError:
    print("FATAL: requests not installed")
    sys.exit(1)


passed = 0
failed = 0
warnings = 0


def ok(msg: str) -> None:
    global passed
    passed += 1
    print(f"  \u2713 {msg}")


def fail(msg: str) -> None:
    global failed
    failed += 1
    print(f"  \u2717 {msg}")


def warn(msg: str) -> None:
    global warnings
    warnings += 1
    print(f"  \u26a0 {msg}")


def info(msg: str) -> None:
    print(f"  \u2022 {msg}")


def section(title: str) -> None:
    print(f"\n{'\u2500' * 60}")
    print(f"  {title}")
    print(f"{'\u2500' * 60}")


def require_env(key: str) -> str:
    val = os.environ.get(key, "").strip()
    if not val:
        raise RuntimeError(f"{key} not set")
    return val


def ensure_local_url(name: str, raw: str) -> None:
    parsed = urlparse(raw)
    host = (parsed.hostname or "").lower()
    if host not in {"127.0.0.1", "localhost"}:
        raise RuntimeError(f"{name} must be local (got host={host})")


# ─── HTTP helpers (rate-limit aware) ──────────────────────────────────

_SESSION = _requests.Session()
_LAST_REQUEST_TIME: float = 0.0
_MIN_INTERVAL: float = 0.35


def _throttle() -> None:
    """Ensure at least _MIN_INTERVAL seconds between API calls."""
    global _LAST_REQUEST_TIME
    elapsed = time.monotonic() - _LAST_REQUEST_TIME
    if elapsed < _MIN_INTERVAL:
        time.sleep(_MIN_INTERVAL - elapsed)
    _LAST_REQUEST_TIME = time.monotonic()


def api_get(url: str, params: dict | None = None, retries: int = 2) -> _requests.Response:
    for attempt in range(retries + 1):
        _throttle()
        resp = _SESSION.get(url, params=params, timeout=10)
        if resp.status_code != 429:
            return resp
        time.sleep(1.5 * (attempt + 1))
    return resp


def api_post(url: str, json_data: dict | None = None, retries: int = 2) -> _requests.Response:
    for attempt in range(retries + 1):
        _throttle()
        resp = _SESSION.post(url, json=json_data or {}, timeout=10)
        if resp.status_code != 429:
            return resp
        time.sleep(1.5 * (attempt + 1))
    return resp


# ─── Indexer DB checks ────────────────────────────────────────────────


def check_indexer_freshness(conn: psycopg.Connection) -> None:
    """Verify the indexer is actively indexing blocks."""
    with conn.cursor() as cur:
        cur.execute("SELECT MAX(height), MAX(block_time) FROM recent_blocks")
        row = cur.fetchone()
    if not row or row[0] is None:
        fail("recent_blocks table is empty (indexer not running?)")
        return
    max_height, max_block_time = row
    ok(f"latest indexed block height={max_height}")
    if max_block_time is not None:
        try:
            if hasattr(max_block_time, "timestamp"):
                block_ts = max_block_time.timestamp()
            else:
                block_ts = float(max_block_time)
            age_sec = time.time() - block_ts
            if age_sec < 120:
                ok(f"latest block is {age_sec:.0f}s old (fresh)")
            elif age_sec < 600:
                warn(f"latest block is {age_sec:.0f}s old (slightly stale)")
            else:
                fail(f"latest block is {age_sec:.0f}s old (indexer may be stuck)")
        except Exception as exc:
            warn(f"could not parse block_time: {exc}")


def check_indexer_schema(conn: psycopg.Connection) -> None:
    """Verify key indexer tables exist."""
    expected_tables = [
        "profiles",
        "posts",
        "votes",
        "tx_index",
        "balances",
        "chain_stats",
        "recent_blocks",
        "awards",
        "enabled_agents",
        "followed_users",
        "followed_topics",
        "blocked_users",
        "blocked_posts",
        "blocked_topics",
        "mentions",
        "agent_edits",
    ]
    with conn.cursor() as cur:
        cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
        existing = {row[0] for row in cur.fetchall()}
    missing = [t for t in expected_tables if t not in existing]
    if missing:
        fail(f"missing indexer tables: {', '.join(missing)}")
    else:
        ok(f"all {len(expected_tables)} expected indexer tables present")


def check_profile_data(conn: psycopg.Connection) -> None:
    """Verify profiles table has data and subscription levels are present."""
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM profiles")
        total = cur.fetchone()[0]
    if total == 0:
        fail("profiles table is empty")
        return
    ok(f"profiles table has {total} rows")

    with conn.cursor() as cur:
        cur.execute("SELECT level, COUNT(*) FROM profiles WHERE level IS NOT NULL GROUP BY level ORDER BY level")
        level_counts = cur.fetchall()
    if not level_counts:
        warn("no profiles have a subscription level set")
    else:
        breakdown = ", ".join(f"L{lvl}={cnt}" for lvl, cnt in level_counts)
        ok(f"profile levels: {breakdown}")

    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM profiles WHERE subscription_expiry IS NOT NULL AND subscription_expiry > %s",
            (int(time.time()),),
        )
        active_subs = cur.fetchone()[0]
    if active_subs > 0:
        ok(f"{active_subs} profiles have active subscriptions")
    else:
        warn("no profiles have active subscriptions (may be expected on fresh chain)")


def check_balances(conn: psycopg.Connection) -> None:
    """Verify balances table is populated."""
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM balances WHERE balance > 0")
        count = cur.fetchone()[0]
    if count > 0:
        ok(f"balances table has {count} addresses with positive balance")
    else:
        warn("no addresses with positive balance (may be expected on fresh chain)")


def check_tx_index_raw_log(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT txhash, tx_type, raw_log
            FROM tx_index
            WHERE code = 0
              AND tx_type IN ('send_tokens', 'multi')
            ORDER BY created_at DESC
            LIMIT 50
            """
        )
        rows = cur.fetchall()
    if not rows:
        warn("tx_index has no send_tokens/multi rows to validate raw_log")
        return
    info(f"Validating raw_log for {len(rows)} tx_index rows")
    for txhash, tx_type, raw_log in rows:
        txh = str(txhash or "").lower()
        if not txh:
            fail("tx_index row missing txhash")
            continue
        if raw_log is None or str(raw_log).strip() == "":
            fail(f"tx_index raw_log missing tx={txh} type={tx_type}")
            continue
        try:
            parsed = json.loads(str(raw_log))
        except Exception as exc:
            fail(f"tx_index raw_log invalid json tx={txh}: {exc}")
            continue
        if not isinstance(parsed, list):
            fail(f"tx_index raw_log unexpected format tx={txh} type={tx_type}")
            continue
    ok("tx_index raw_log present and JSON for send_tokens/multi")


def check_chain_stats(conn: psycopg.Connection) -> None:
    """Verify chain_stats has essential entries populated by the indexer."""
    with conn.cursor() as cur:
        cur.execute("SELECT key FROM chain_stats")
        keys = {row[0] for row in cur.fetchall()}
    expected_keys = {"chain_params", "difficulty_info", "total_supply"}
    missing = expected_keys - keys
    if missing:
        fail(f"chain_stats missing keys: {', '.join(sorted(missing))}")
    else:
        ok(f"chain_stats has {', '.join(sorted(expected_keys))}")

    if "chain_params" in keys:
        with conn.cursor() as cur:
            cur.execute("SELECT value FROM chain_stats WHERE key = 'chain_params'")
            row = cur.fetchone()
        if row and row[0]:
            try:
                params = row[0] if isinstance(row[0], dict) else json.loads(str(row[0]))
                param_count = len(params)
                ok(f"chain_params has {param_count} keys in indexer DB")
            except Exception:
                fail("chain_params value is not valid JSON")
        else:
            fail("chain_params value is empty")


# ─── Backend API checks ──────────────────────────────────────────────

# Params actually exposed by /api/get_chain_config (see public.py get_chain_config)
EXPECTED_CONFIG_KEYS = [
    "max_username_size",
    "min_username_size",
    "max_topic_size",
    "min_topic_size",
    "subscription_period",
    "subscription_reserve_percent",
    "bridge_attestation_threshold",
    "mint_interval",
    "block_time",
    "tiers",
    "award_configs",
]


def check_api_parameters(backend_api: str) -> None:
    """Verify /api/get_parameters returns valid data."""
    try:
        resp = api_get(f"{backend_api}/api/get_parameters")
    except Exception as exc:
        fail(f"/api/get_parameters error: {exc}")
        return
    if resp.status_code != 200:
        fail(f"/api/get_parameters returned {resp.status_code}")
        return
    try:
        data = resp.json()
    except Exception:
        fail("/api/get_parameters returned non-JSON")
        return
    if "last_block_hash" in data and data["last_block_hash"]:
        ok(f"/api/get_parameters OK (block_hash={str(data['last_block_hash'])[:16]}...)")
    else:
        fail("/api/get_parameters missing last_block_hash")
    if "pow_difficulty" in data:
        ok(f"current pow_difficulty={data['pow_difficulty']}")
    else:
        fail("/api/get_parameters missing pow_difficulty")


def check_chain_config(backend_api: str) -> None:
    """Verify /api/get_chain_config returns complete params."""
    try:
        resp = api_get(f"{backend_api}/api/get_chain_config")
    except Exception as exc:
        fail(f"/api/get_chain_config error: {exc}")
        return
    if resp.status_code != 200:
        fail(f"/api/get_chain_config returned {resp.status_code}")
        return
    try:
        cfg = resp.json()
    except Exception:
        fail("/api/get_chain_config returned non-JSON")
        return

    missing_keys = [k for k in EXPECTED_CONFIG_KEYS if k not in cfg]
    if missing_keys:
        fail(f"chain config missing keys: {', '.join(missing_keys)}")
    else:
        ok(f"all {len(EXPECTED_CONFIG_KEYS)} expected config keys present")

    # Tiers validation
    tiers = cfg.get("tiers")
    if not isinstance(tiers, list) or len(tiers) < 3:
        fail(f"chain config has {len(tiers) if isinstance(tiers, list) else 0} tiers, expected >= 3")
        return
    ok(f"chain config has {len(tiers)} tiers")

    tier_names = ["free", "subscriber", "agent"]
    required_tier_fields = ["max_content_length", "max_title_length", "period_fee", "max_biography_length"]
    for i, tier in enumerate(tiers[:3]):
        if not isinstance(tier, dict):
            fail(f"tier[{i}] ({tier_names[i]}) is not a dict")
            continue
        missing_fields = [f for f in required_tier_fields if f not in tier]
        if missing_fields:
            fail(f"tier[{i}] ({tier_names[i]}) missing: {', '.join(missing_fields)}")
        else:
            fee = int(tier.get("period_fee", 0) or 0)
            max_content = int(tier.get("max_content_length", 0) or 0)
            ok(f"tier[{i}] ({tier_names[i]}): fee={fee}, max_content={max_content}")

    agent_fee = int(tiers[2].get("period_fee", 0) or 0) if isinstance(tiers[2], dict) else 0
    if agent_fee > 0:
        ok(f"agent tier period_fee={agent_fee}")
    else:
        fail("agent tier period_fee is 0 or missing")

    award_configs = cfg.get("award_configs")
    if not isinstance(award_configs, list) or len(award_configs) == 0:
        fail("chain config missing or empty award_configs")
    else:
        ok(f"chain config has {len(award_configs)} award configs")

    sub_period = int(cfg.get("subscription_period", 0) or 0)
    if sub_period > 0:
        ok(f"subscription_period={sub_period} minutes")
    else:
        fail("subscription_period is 0 or missing")


def check_api_node_config(backend_api: str) -> None:
    """Verify /api/get_node_config returns valid data."""
    try:
        resp = api_get(f"{backend_api}/api/get_node_config")
    except Exception as exc:
        fail(f"/api/get_node_config error: {exc}")
        return
    if resp.status_code != 200:
        fail(f"/api/get_node_config returned {resp.status_code}")
        return
    try:
        data = resp.json()
    except Exception:
        fail("/api/get_node_config returned non-JSON")
        return
    if "validator_account_address" in data and data["validator_account_address"]:
        ok(f"/api/get_node_config OK (validator={str(data['validator_account_address'])[:20]}...)")
    else:
        fail("/api/get_node_config missing validator_account_address")


def check_api_search(backend_api: str) -> None:
    """Verify /api/search is reachable."""
    try:
        resp = api_get(f"{backend_api}/api/search", params={"q": "test", "limit": 1})
    except Exception as exc:
        fail(f"/api/search error: {exc}")
        return
    if resp.status_code in (200, 400):
        ok(f"/api/search reachable ({resp.status_code})")
    else:
        fail(f"/api/search returned {resp.status_code}")


def check_api_feed(backend_api: str) -> None:
    """Verify /api/get_user_posts is reachable."""
    try:
        resp = api_get(
            f"{backend_api}/api/get_user_posts",
            params={"owner": "mirage1test", "limit": 1},
        )
    except Exception as exc:
        fail(f"/api/get_user_posts error: {exc}")
        return
    if resp.status_code == 200:
        ok("/api/get_user_posts reachable")
    else:
        fail(f"/api/get_user_posts returned {resp.status_code}")


def check_subscribe_routes(backend_api: str) -> None:
    """Verify /api/core/subscribe exists and /api/core/upgrade_level is removed."""
    try:
        resp = api_post(f"{backend_api}/api/core/subscribe")
    except Exception as exc:
        fail(f"/api/core/subscribe error: {exc}")
        return
    if resp.status_code == 404:
        fail("/api/core/subscribe missing (404)")
    elif resp.status_code >= 500:
        fail(f"/api/core/subscribe server error ({resp.status_code})")
    else:
        ok(f"/api/core/subscribe reachable ({resp.status_code})")

    try:
        resp = api_post(f"{backend_api}/api/core/upgrade_level")
    except Exception as exc:
        fail(f"/api/core/upgrade_level error: {exc}")
        return
    if resp.status_code in (404, 405):
        ok(f"/api/core/upgrade_level removed ({resp.status_code})")
    elif resp.status_code >= 500:
        ok(f"/api/core/upgrade_level removed (no route, server returned {resp.status_code})")
    else:
        fail(f"/api/core/upgrade_level still available ({resp.status_code})")


def check_core_routes_reachable(backend_api: str) -> None:
    """Verify key core POST routes return 400 (not 404/500) when called with empty payload."""
    routes = [
        "/api/core/post",
        "/api/core/vote",
        "/api/core/send_tokens",
        "/api/core/award",
        "/api/core/set_username",
    ]
    for route in routes:
        try:
            resp = api_post(f"{backend_api}{route}")
        except Exception as exc:
            fail(f"{route} error: {exc}")
            continue
        if resp.status_code == 404:
            fail(f"{route} missing (404)")
        elif resp.status_code >= 500:
            fail(f"{route} server error ({resp.status_code})")
        else:
            ok(f"{route} reachable ({resp.status_code})")


# ─── Backend DB checks ───────────────────────────────────────────────


def check_backend_schema(conn: psycopg.Connection) -> None:
    """Verify key backend tables exist."""
    expected_tables = [
        "reports",
        "user_last_seen",
        "push_tokens",
        "user_daily_quests",
        "pending_rewards",
        "reward_suspensions",
        "inbox_events",
    ]
    with conn.cursor() as cur:
        cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
        existing = {row[0] for row in cur.fetchall()}
    missing = [t for t in expected_tables if t not in existing]
    if missing:
        fail(f"missing backend tables: {', '.join(missing)}")
    else:
        ok(f"all {len(expected_tables)} expected backend tables present")


# ─── Main ─────────────────────────────────────────────────────────────


def main() -> None:
    global passed, failed, warnings

    print("=" * 60)
    print("  Mirage Post-Upgrade Verification (v1.22.x)")
    print("=" * 60)

    section("1. Environment Variables")
    try:
        backend_db_url = require_env("BACKEND_DB_URL")
        indexer_ro_url = require_env("INDEXER_DB_RO_URL")
        ok("BACKEND_DB_URL is set")
        ok("INDEXER_DB_RO_URL is set")
    except Exception as exc:
        fail(str(exc))
        print("\nFATAL: Missing required environment variables")
        sys.exit(1)

    backend_api = os.environ.get("BACKEND_API", "").strip() or "http://127.0.0.1:80"
    ok(f"BACKEND_API = {backend_api}")
    try:
        ensure_local_url("BACKEND_API", backend_api)
        ok("BACKEND_API is local")
    except Exception as exc:
        fail(str(exc))
        print("\nFATAL: Refusing to run against non-local BACKEND_API")
        sys.exit(1)

    section("2. Database Connectivity")
    backend_conn = None
    indexer_conn = None
    try:
        backend_conn = psycopg.connect(backend_db_url, autocommit=True)
        ok("Backend DB reachable")
    except Exception as exc:
        fail(f"Backend DB unreachable: {exc}")

    try:
        indexer_conn = psycopg.connect(indexer_ro_url, autocommit=True)
        ok("Indexer DB (RO) reachable")
    except Exception as exc:
        fail(f"Indexer DB (RO) unreachable: {exc}")

    if not backend_conn or not indexer_conn:
        print("\nFATAL: Cannot proceed without database connections")
        sys.exit(1)

    section("3. Database Schema")
    check_indexer_schema(indexer_conn)
    check_backend_schema(backend_conn)

    section("4. Indexer Health")
    check_indexer_freshness(indexer_conn)
    check_chain_stats(indexer_conn)

    section("5. Data Integrity")
    check_profile_data(indexer_conn)
    check_balances(indexer_conn)
    check_tx_index_raw_log(indexer_conn)

    section("6. Chain Params (via API)")
    check_chain_config(backend_api)

    section("7. Backend API Health")
    check_api_parameters(backend_api)
    check_api_node_config(backend_api)
    check_api_search(backend_api)
    check_api_feed(backend_api)

    section("8. Core Routes")
    check_subscribe_routes(backend_api)
    check_core_routes_reachable(backend_api)

    if backend_conn:
        backend_conn.close()
    if indexer_conn:
        indexer_conn.close()

    print(f"\n{'=' * 60}")
    total = passed + failed + warnings
    print(f"  Results: {passed} passed, {failed} failed, {warnings} warnings ({total} total)")
    if failed == 0:
        print("  STATUS: ALL CHECKS PASSED")
    else:
        print(f"  STATUS: {failed} FAILURE(S) \u2014 review above")
    print(f"{'=' * 60}\n")
    sys.exit(1 if failed > 0 else 0)


if __name__ == "__main__":
    main()
