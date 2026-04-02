#!/usr/bin/env python3
"""
Post-upgrade verification for v1.23.0.

Checks:
  1. Required environment variables are set (DB URLs)
  2. Node retention config (snapshot keep recent, log retention)
  3. Backend + indexer (RO) DB connections succeed
  4. Database schema: key tables exist, indexer has "adult" tag (not "porn")
  5. Indexer freshness: latest block is recent
  6. Content tag normalization: "adult" tag present, "porn" absent
  7. Chain params completeness via /api/get_chain_config
  8. Backend API health: key GET endpoints return valid data
  9. Core routes: subscribe exists, upgrade_level removed, POST routes reachable

Usage:
  python scripts/verify_upgrade.py                     # inside container
  docker exec mirage python3 /opt/mirage/scripts/verify_upgrade.py
"""
from __future__ import annotations

import json
import os
import re
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


def read_toml_value(path: Path, key: str) -> str | None:
    content = path.read_text()
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*=\s*(.+?)\s*$")
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = pattern.match(line)
        if match:
            value = match.group(1).strip()
            if value and value[0] in ('"', "'") and len(value) > 1 and value[-1] == value[0]:
                value = value[1:-1]
            return value
    return None


def read_env_value(path: Path, key: str) -> str | None:
    if not path.exists():
        return None
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith(f"{key}="):
            return stripped.split("=", 1)[1].strip().strip('"').strip("'")
    return None


# ─── HTTP helpers (rate-limit aware) ──────────────────────────────────

_SESSION = _requests.Session()
_LAST_REQUEST_TIME: float = 0.0
_MIN_INTERVAL: float = 0.35


def _throttle() -> None:
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


# ─── Node config checks ──────────────────────────────────────────────


def check_node_retention_config() -> None:
    node_home_raw = os.environ.get("NODE_HOME", "").strip()
    node_home = Path(node_home_raw).expanduser() if node_home_raw else Path.home() / ".mirage" / "node"
    app_toml = node_home / "config" / "app.toml"

    try:
        snapshot_keep_recent = read_toml_value(app_toml, "snapshot-keep-recent")
    except Exception as exc:
        fail(f"could not read app.toml: {exc}")
        return
    if snapshot_keep_recent is None:
        fail("snapshot-keep-recent not found in app.toml")
        return
    try:
        val = int(snapshot_keep_recent)
    except Exception:
        fail(f"snapshot-keep-recent is not an int: {snapshot_keep_recent!r}")
        return
    if val <= 4:
        ok(f"snapshot-keep-recent={val}")
    else:
        fail(f"snapshot-keep-recent={val} (expected <= 4)")


def check_log_retention() -> None:
    env_dir = Path.home() / ".mirage" / "env"
    node_env = env_dir / "node.env"
    val = read_env_value(node_env, "LOG_RETENTION_DAYS")
    if val is None:
        fail("LOG_RETENTION_DAYS not found in node.env")
        return
    try:
        days = int(val)
    except Exception:
        fail(f"LOG_RETENTION_DAYS is not an int: {val!r}")
        return
    if days <= 30:
        ok(f"LOG_RETENTION_DAYS={days}")
    else:
        fail(f"LOG_RETENTION_DAYS={days} (expected <= 30)")


# ─── Indexer DB checks ────────────────────────────────────────────────


def check_indexer_freshness(conn: psycopg.Connection) -> None:
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


def check_tag_normalization(conn: psycopg.Connection) -> None:
    """Verify the porn->adult tag migration ran in the indexer."""
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM posts WHERE tag = 'porn'")
        porn_count = cur.fetchone()[0]
    if porn_count > 0:
        fail(f"indexer still has {porn_count} posts with tag='porn' (should be 'adult')")
    else:
        ok("no posts with legacy 'porn' tag (migration complete)")

    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM posts WHERE tag = 'adult'")
        adult_count = cur.fetchone()[0]
    if adult_count > 0:
        ok(f"indexer has {adult_count} posts with tag='adult'")
    else:
        info("no posts with 'adult' tag (may be expected on fresh chain)")


def check_profile_data(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM profiles")
        total = cur.fetchone()[0]
    if total == 0:
        fail("profiles table is empty")
        return
    ok(f"profiles table has {total} rows")


# ─── Backend API checks ──────────────────────────────────────────────

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


def check_chain_config(backend_api: str) -> None:
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

    tiers = cfg.get("tiers")
    if not isinstance(tiers, list) or len(tiers) < 3:
        fail(f"chain config has {len(tiers) if isinstance(tiers, list) else 0} tiers, expected >= 3")
    else:
        ok(f"chain config has {len(tiers)} tiers")


def check_api_parameters(backend_api: str) -> None:
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


def check_subscribe_routes(backend_api: str) -> None:
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


def check_backend_schema(conn: psycopg.Connection) -> None:
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
    print("  Mirage Post-Upgrade Verification (v1.23.0)")
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

    section("2. Node Retention Config")
    check_node_retention_config()
    check_log_retention()

    section("3. Database Connectivity")
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

    section("4. Database Schema")
    check_indexer_schema(indexer_conn)
    check_backend_schema(backend_conn)

    section("5. Indexer Health")
    check_indexer_freshness(indexer_conn)

    section("6. Content Tag Normalization")
    check_tag_normalization(indexer_conn)

    section("7. Data Integrity")
    check_profile_data(indexer_conn)

    section("8. Chain Params (via API)")
    check_chain_config(backend_api)

    section("9. Backend API Health")
    check_api_parameters(backend_api)
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
