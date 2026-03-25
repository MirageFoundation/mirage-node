#!/usr/bin/env python3
"""
Post-upgrade verification for the indexer/backend database split.

Checks:
  1. Both databases exist and are reachable
  2. Backend DB has all expected tables with correct schemas
  3. Indexer DB has all expected tables (chain-indexed state)
  4. Backend DB does NOT contain indexer tables (clean split)
  5. Indexer DB does NOT contain backend-owned tables
  6. Read-only role cannot write to indexer DB
  7. Backend can read from indexer via RO connection
  8. Push listener tables are functional
  9. user_last_seen table works
 10. stats_events table is gone
 11. API endpoints respond correctly
 12. /signup route exists (renamed from /create_account)

Usage:
  python scripts/verify_upgrade.py                     # inside container
  docker exec mirage python3 /opt/mirage/scripts/verify_upgrade.py
"""
from __future__ import annotations

import os
import sys
import time
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "web" / "backend"))

try:
    import psycopg
except ImportError:
    print("FATAL: psycopg not installed")
    sys.exit(1)

try:
    import requests
except ImportError:
    requests = None


BACKEND_API = os.environ.get("BACKEND_API", "http://127.0.0.1:5000")
FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://127.0.0.1")

BACKEND_TABLES = {
    "invite_codes",
    "referral_links",
    "referral_pending_rewards",
    "referral_trust_scores",
    "referral_analysis",
    "referral_user_accruals",
    "referral_state",
    "reports",
    "user_last_seen",
    "push_event_seen",
    "push_event_cursor",
    "user_similarity_cache",
    "push_tokens",
    "push_budget",
    "push_throttle",
    "push_receipts",
    "push_nonces",
    "user_daily_quests",
    "user_flash_quests",
    "user_quest_state",
    "user_achievements",
    "pending_rewards",
    "user_unlocks",
    "reward_suspensions",
    "user_inbox_state",
}

INDEXER_TABLES = {
    "meta",
    "posts",
    "votes",
    "tx_index",
    "awards",
    "preferences",
    "profiles",
    "enabled_agents",
    "followed_users",
    "followed_topics",
    "blocked_posts",
    "blocked_users",
    "blocked_topics",
    "difficulty_history",
    "supply_history",
    "topic_content_stats",
    "balances",
    "chain_stats",
    "recent_blocks",
    "pending_txs",
    "indexer_state",
    "user_topic_stats",
    "mentions",
    "agent_edits",
}

DEAD_TABLES = {"stats_events"}

BACKEND_SCHEMA_CHECKS = {
    "push_throttle": {"owner", "window_start", "sent_count", "suppressed_count", "cooldown_until"},
    "push_receipts": {"id", "ticket_id", "token", "created_at"},
    "push_nonces": {"id", "owner", "action", "nonce", "created_at"},
    "user_last_seen": {"owner", "last_seen_at"},
    "push_event_seen": {"event_key", "event_type", "created_at"},
    "push_event_cursor": {"event_type", "last_created_at", "last_id", "updated_at"},
    "user_daily_quests": {
        "owner",
        "day_utc",
        "quest_id",
        "progress",
        "progress_meta",
        "last_action_at",
        "completed_at",
    },
    "pending_rewards": {
        "id",
        "owner",
        "reward_type",
        "reward_data",
        "reason",
        "created_at",
        "claimed_at",
        "payout_amount",
    },
    "user_inbox_state": {"owner", "inbox_last_viewed_at"},
}

MIGRATED_TABLES = {
    "push_tokens",
    "push_budget",
    "push_throttle",
    "push_receipts",
    "push_nonces",
    "user_daily_quests",
    "user_flash_quests",
    "user_quest_state",
    "user_achievements",
    "pending_rewards",
    "user_unlocks",
    "reward_suspensions",
    "user_similarity_cache",
    "invite_codes",
    "reports",
    "user_inbox_state",
}

passed = 0
failed = 0
warnings = 0


def ok(msg: str) -> None:
    global passed
    passed += 1
    print(f"  ✓ {msg}")


def fail(msg: str) -> None:
    global failed
    failed += 1
    print(f"  ✗ {msg}")


def warn(msg: str) -> None:
    global warnings
    warnings += 1
    print(f"  ⚠ {msg}")


def get_row_count(conn: psycopg.Connection, table: str) -> int:
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            return cur.fetchone()[0]
    except Exception:
        return -1


def get_tables(conn: psycopg.Connection) -> set[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
        return {row[0] for row in cur.fetchall()}


def get_columns(conn: psycopg.Connection, table: str) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_schema = 'public' AND table_name = %s",
            (table,),
        )
        return {row[0] for row in cur.fetchall()}


def get_env(key: str) -> str:
    val = os.environ.get(key, "").strip()
    if not val:
        raise RuntimeError(f"{key} not set")
    return val


def section(title: str) -> None:
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print(f"{'─' * 60}")


def main() -> None:
    global passed, failed, warnings

    print("=" * 60)
    print("  Mirage Post-Upgrade Verification")
    print("=" * 60)

    # ── 1. Environment variables ──────────────────────────────
    section("1. Environment Variables")
    backend_url = indexer_url = indexer_ro_url = None
    for key in ("BACKEND_DB_URL", "INDEXER_DB_URL", "INDEXER_DB_RO_URL"):
        val = os.environ.get(key, "").strip()
        if val:
            ok(f"{key} is set")
            if key == "BACKEND_DB_URL":
                backend_url = val
            elif key == "INDEXER_DB_URL":
                indexer_url = val
            elif key == "INDEXER_DB_RO_URL":
                indexer_ro_url = val
        else:
            if key == "INDEXER_DB_URL":
                warn(f"{key} not set (only needed by indexer process)")
            else:
                fail(f"{key} not set")

    if not backend_url or not indexer_ro_url:
        print("\nFATAL: Cannot proceed without BACKEND_DB_URL and INDEXER_DB_RO_URL")
        sys.exit(1)

    # ── 2. Database connectivity ──────────────────────────────
    section("2. Database Connectivity")
    backend_conn = None
    indexer_conn = None
    try:
        backend_conn = psycopg.connect(backend_url, autocommit=True)
        ok("Backend DB reachable")
    except Exception as e:
        fail(f"Backend DB unreachable: {e}")

    try:
        indexer_conn = psycopg.connect(indexer_ro_url, autocommit=True)
        ok("Indexer DB (RO) reachable")
    except Exception as e:
        fail(f"Indexer DB (RO) unreachable: {e}")

    if not backend_conn or not indexer_conn:
        print("\nFATAL: Cannot proceed without database connections")
        sys.exit(1)

    # ── 3. Backend DB has all expected tables ─────────────────
    section("3. Backend DB Tables")
    backend_tables = get_tables(backend_conn)
    for t in sorted(BACKEND_TABLES):
        if t in backend_tables:
            ok(f"backend.{t} exists")
        else:
            fail(f"backend.{t} MISSING")

    # ── 4. Backend DB does NOT have indexer tables ────────────
    section("4. Backend DB Clean (no indexer tables)")
    leaked = INDEXER_TABLES & backend_tables
    if leaked:
        for t in sorted(leaked):
            fail(f"backend.{t} should NOT exist (indexer table leaked)")
    else:
        ok("No indexer tables found in backend DB")

    # ── 5. Dead tables removed ────────────────────────────────
    section("5. Dead Tables Removed")
    for t in sorted(DEAD_TABLES):
        if t in backend_tables:
            fail(f"backend.{t} still exists (should be removed)")
        else:
            ok(f"backend.{t} correctly absent")

    # ── 6. Indexer DB has expected tables ─────────────────────
    section("6. Indexer DB Tables")
    indexer_tables = get_tables(indexer_conn)
    for t in sorted(INDEXER_TABLES):
        if t in indexer_tables:
            ok(f"indexer.{t} exists")
        else:
            warn(f"indexer.{t} missing (may not be created yet)")

    # ── 7. Indexer DB does NOT have backend-only tables ───────
    section("7. Indexer DB Clean (no backend-only tables)")
    backend_only = {"user_last_seen", "push_event_seen", "push_event_cursor", "user_inbox_state"}
    leaked_to_indexer = backend_only & indexer_tables
    if leaked_to_indexer:
        for t in sorted(leaked_to_indexer):
            fail(f"indexer.{t} should NOT exist (backend table leaked)")
    else:
        ok("No backend-only tables found in indexer DB")

    # Tables that migrated from indexer may still exist there during transition
    migrated = {
        "push_tokens",
        "push_budget",
        "push_throttle",
        "push_receipts",
        "push_nonces",
        "user_daily_quests",
        "user_flash_quests",
        "user_quest_state",
        "user_achievements",
        "pending_rewards",
        "user_unlocks",
        "reward_suspensions",
        "user_similarity_cache",
    }
    still_in_indexer = migrated & indexer_tables
    if still_in_indexer:
        for t in sorted(still_in_indexer):
            warn(f"indexer.{t} still exists (migrated table, safe to drop after migration)")
    else:
        ok("Migrated tables already cleaned from indexer DB")

    # ── 8. Backend table schemas ──────────────────────────────
    section("8. Backend Table Schema Validation")
    for table, expected_cols in sorted(BACKEND_SCHEMA_CHECKS.items()):
        if table not in backend_tables:
            fail(f"backend.{table} missing, cannot check schema")
            continue
        actual_cols = get_columns(backend_conn, table)
        missing = expected_cols - actual_cols
        extra = actual_cols - expected_cols
        if missing:
            fail(f"backend.{table} missing columns: {sorted(missing)}")
        elif extra:
            warn(f"backend.{table} has extra columns: {sorted(extra)} (may be intentional)")
        else:
            ok(f"backend.{table} schema matches")

    # ── 9. Data migration verification ─────────────────────────
    section("9. Data Migration Verification")
    indexer_rw_url = os.environ.get("INDEXER_DB_URL", "").strip()
    indexer_for_counts = None
    if indexer_rw_url and indexer_rw_url != indexer_ro_url:
        try:
            indexer_for_counts = psycopg.connect(indexer_rw_url, autocommit=True)
        except Exception:
            pass
    if not indexer_for_counts:
        indexer_for_counts = indexer_conn

    data_issues = 0
    for t in sorted(MIGRATED_TABLES):
        src_count = get_row_count(indexer_for_counts, t)
        dst_count = get_row_count(backend_conn, t)

        if src_count < 0 and dst_count < 0:
            continue
        if dst_count < 0 and src_count > 0:
            fail(f"{t}: {src_count} rows in indexer but table MISSING in backend — DATA NOT MIGRATED")
            data_issues += 1
            continue
        if dst_count < 0 and src_count == 0:
            warn(f"{t}: table missing in backend (source empty, may be ok)")
            continue
        if src_count <= 0 and dst_count <= 0:
            ok(f"{t}: empty in both DBs")
            continue
        if src_count <= 0 and dst_count > 0:
            ok(f"{t}: {dst_count} rows in backend (source already cleaned)")
            continue
        if src_count > 0 and dst_count == 0:
            fail(f"{t}: {src_count} rows in indexer but 0 in backend — DATA NOT MIGRATED")
            data_issues += 1
            continue
        if dst_count < src_count:
            pct = (dst_count / src_count) * 100
            if pct < 90:
                fail(f"{t}: only {dst_count}/{src_count} rows migrated ({pct:.0f}%) — INCOMPLETE")
                data_issues += 1
            else:
                warn(f"{t}: {dst_count}/{src_count} rows ({pct:.0f}%) — minor difference")
        else:
            ok(f"{t}: {dst_count} rows in backend (source has {src_count})")

    if data_issues > 0:
        print(f"\n  ** {data_issues} table(s) have missing data. Run the migration: **")
        print(f"  ** python3 -m deploy.migrations --config-dir /root/.mirage/env **\n")

    if indexer_for_counts is not None and indexer_for_counts is not indexer_conn:
        indexer_for_counts.close()

    # ── 10. Read-only enforcement ──────────────────────────────
    section("10. Read-Only Enforcement (indexer via RO role)")
    try:
        with indexer_conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM profiles LIMIT 1")
            count = cur.fetchone()[0]
            ok(f"RO read from indexer.profiles works ({count} rows)")
    except Exception as e:
        fail(f"Cannot read indexer.profiles via RO: {e}")

    try:
        with indexer_conn.cursor() as cur:
            cur.execute("INSERT INTO profiles (owner, username) VALUES ('__verify_test__', '__verify_test__')")
            fail("RO role CAN WRITE to indexer DB (should be denied)")
            with indexer_conn.cursor() as cur2:
                cur2.execute("DELETE FROM profiles WHERE owner = '__verify_test__'")
    except psycopg.errors.InsufficientPrivilege:
        ok("RO role correctly denied write to indexer DB")
    except Exception as e:
        if "permission denied" in str(e).lower() or "read-only" in str(e).lower():
            ok(f"RO role correctly denied write to indexer DB ({type(e).__name__})")
        else:
            warn(f"Unexpected error testing RO write: {e}")
    finally:
        try:
            indexer_conn.rollback()
        except Exception:
            pass
        try:
            indexer_conn = psycopg.connect(indexer_ro_url, autocommit=True)
        except Exception:
            pass

    # ── 10. Backend DB write test ─────────────────────────────
    section("11. Backend DB Write Test")
    test_addr = "__verify_test__"
    try:
        with backend_conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO user_last_seen (owner, last_seen_at)
                VALUES (%s, %s)
                ON CONFLICT (owner) DO UPDATE SET last_seen_at = EXCLUDED.last_seen_at
                """,
                (test_addr, int(time.time())),
            )
            ok("Write to backend.user_last_seen succeeded")
            cur.execute("DELETE FROM user_last_seen WHERE owner = %s", (test_addr,))
            ok("Cleanup of test row succeeded")
    except Exception as e:
        fail(f"Backend write test failed: {e}")

    # ── 11. Push event tables functional ──────────────────────
    section("12. Push Event Tables")
    try:
        with backend_conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM push_event_cursor")
            count = cur.fetchone()[0]
            ok(f"push_event_cursor readable ({count} rows)")
            cur.execute("SELECT COUNT(*) FROM push_event_seen")
            count = cur.fetchone()[0]
            ok(f"push_event_seen readable ({count} rows)")
    except Exception as e:
        fail(f"Push event tables error: {e}")

    # ── 12. API Endpoint Checks ───────────────────────────────
    section("13. API Endpoints")
    if requests is None:
        warn("requests library not available, skipping API checks")
    else:
        api_checks = [
            ("GET", "/api/get_node_config", 200),
            ("GET", "/api/get_parameters", 200),
            ("GET", "/api/get_welcome_stats", 200),
        ]
        for method, path, expected_status in api_checks:
            try:
                resp = requests.request(method, f"{BACKEND_API}{path}", timeout=10)
                if resp.status_code == expected_status:
                    ok(f"{method} {path} -> {resp.status_code}")
                else:
                    fail(f"{method} {path} -> {resp.status_code} (expected {expected_status})")
            except Exception as e:
                fail(f"{method} {path} -> error: {e}")

        # stats_event endpoint should be disabled (410)
        try:
            resp = requests.post(
                f"{BACKEND_API}/api/stats/event",
                json={"event_type": "test"},
                timeout=10,
            )
            if resp.status_code == 410:
                ok("/api/stats/event correctly returns 410 (disabled)")
            else:
                fail(f"/api/stats/event returned {resp.status_code} (expected 410)")
        except Exception as e:
            fail(f"/api/stats/event error: {e}")

        # get_stats overview should return DAU data
        try:
            resp = requests.get(f"{BACKEND_API}/api/get_stats?tab=overview", timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if "dau_any_today" in data or "dau_today" in data:
                    ok("/api/get_stats?tab=overview returns DAU metrics")
                else:
                    warn(f"/api/get_stats?tab=overview missing DAU fields (keys: {list(data.keys())[:10]})")
            else:
                fail(f"/api/get_stats?tab=overview -> {resp.status_code}")
        except Exception as e:
            fail(f"/api/get_stats?tab=overview error: {e}")

    # ── 13. Frontend route check ──────────────────────────────
    section("14. Frontend Route Check (/signup)")
    if requests is None:
        warn("requests library not available, skipping route check")
    else:
        try:
            resp = requests.get(f"{FRONTEND_URL}/signup", timeout=10, allow_redirects=False)
            if resp.status_code == 200:
                body = resp.text[:2000]
                if "create_account" in body.lower():
                    fail("/signup page still references create_account")
                else:
                    ok("/signup serves frontend (200)")
            elif resp.status_code in (301, 302, 304):
                ok(f"/signup redirects ({resp.status_code})")
            else:
                warn(f"/signup returned {resp.status_code}")
        except Exception as e:
            warn(f"/signup check error: {e}")

        try:
            resp = requests.get(f"{FRONTEND_URL}/create_account", timeout=10, allow_redirects=False)
            if resp.status_code == 404:
                ok("/create_account correctly returns 404")
            elif resp.status_code == 200:
                warn("/create_account still serves content (SPA catch-all may route it)")
            else:
                ok(f"/create_account returns {resp.status_code} (not served)")
        except Exception as e:
            warn(f"/create_account check error: {e}")

    # ── 14. Cross-DB isolation sanity ─────────────────────────
    section("15. Cross-DB Isolation")
    try:
        with backend_conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM user_last_seen")
            ok("Backend can query its own user_last_seen")
    except Exception as e:
        fail(f"Backend cannot query user_last_seen: {e}")

    try:
        with indexer_conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM posts")
            count = cur.fetchone()[0]
            ok(f"Indexer has {count} posts (chain data intact)")
    except Exception as e:
        fail(f"Cannot read indexer.posts: {e}")

    try:
        with backend_conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM posts")
            fail("Backend DB has a 'posts' table (should only be in indexer)")
    except psycopg.errors.UndefinedTable:
        ok("Backend DB correctly has no 'posts' table")
    except Exception as e:
        if "does not exist" in str(e).lower() or "undefined" in str(e).lower():
            ok("Backend DB correctly has no 'posts' table")
        else:
            warn(f"Unexpected error checking posts in backend: {e}")
    finally:
        try:
            backend_conn = psycopg.connect(backend_url, autocommit=True)
        except Exception:
            pass

    # ── Cleanup ───────────────────────────────────────────────
    if backend_conn:
        backend_conn.close()
    if indexer_conn:
        indexer_conn.close()

    # ── Summary ───────────────────────────────────────────────
    print(f"\n{'=' * 60}")
    total = passed + failed + warnings
    print(f"  Results: {passed} passed, {failed} failed, {warnings} warnings ({total} total)")
    if failed == 0:
        print("  STATUS: ALL CHECKS PASSED")
    else:
        print(f"  STATUS: {failed} FAILURE(S) — review above")
    print(f"{'=' * 60}\n")
    sys.exit(1 if failed > 0 else 0)


if __name__ == "__main__":
    main()
