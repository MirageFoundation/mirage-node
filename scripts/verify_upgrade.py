#!/usr/bin/env python3
"""
Post-upgrade verification for v1.22.x.

Checks:
  1. Required environment variables are set
  2. Backend + indexer (RO) DB connections succeed
  3. Successful send_tokens/multi tx_index rows have non-empty JSON raw_log
  4. Backend routes: /api/core/subscribe exists, /api/core/upgrade_level is removed

Usage:
  python scripts/verify_upgrade.py                     # inside container
  docker exec mirage python3 /opt/mirage/scripts/verify_upgrade.py
"""
from __future__ import annotations

import json
import os
import sys
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
    import requests
except ImportError:
    print("FATAL: requests not installed")
    sys.exit(1)


passed = 0
failed = 0


def ok(msg: str) -> None:
    global passed
    passed += 1
    print(f"  ✓ {msg}")


def fail(msg: str) -> None:
    global failed
    failed += 1
    print(f"  ✗ {msg}")


def info(msg: str) -> None:
    print(f"  • {msg}")


def section(title: str) -> None:
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print(f"{'─' * 60}")


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
        fail("tx_index has no send_tokens/multi rows to validate raw_log")
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


def check_subscribe_routes(backend_api: str) -> None:
    try:
        resp = requests.post(f"{backend_api}/api/core/subscribe", json={}, timeout=10)
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
        resp = requests.post(f"{backend_api}/api/core/upgrade_level", json={}, timeout=10)
    except Exception as exc:
        fail(f"/api/core/upgrade_level error: {exc}")
        return
    if resp.status_code == 404:
        ok("/api/core/upgrade_level removed (404)")
    else:
        fail(f"/api/core/upgrade_level still available ({resp.status_code})")


def main() -> None:
    global passed, failed

    print("=" * 60)
    print("  Mirage Post-Upgrade Verification (v1.22.x)")
    print("=" * 60)

    section("1. Environment Variables")
    try:
        backend_db_url = require_env("BACKEND_DB_URL")
        indexer_ro_url = require_env("INDEXER_DB_RO_URL")
        backend_api = require_env("BACKEND_API")
        ok("BACKEND_DB_URL is set")
        ok("INDEXER_DB_RO_URL is set")
        ok("BACKEND_API is set")
    except Exception as exc:
        fail(str(exc))
        print("\nFATAL: Missing required environment variables")
        sys.exit(1)

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

    section("3. tx_index raw_log validation")
    check_tx_index_raw_log(indexer_conn)

    section("4. Backend route checks")
    check_subscribe_routes(backend_api)

    if backend_conn:
        backend_conn.close()
    if indexer_conn:
        indexer_conn.close()

    print(f"\n{'=' * 60}")
    total = passed + failed
    print(f"  Results: {passed} passed, {failed} failed ({total} total)")
    if failed == 0:
        print("  STATUS: ALL CHECKS PASSED")
    else:
        print(f"  STATUS: {failed} FAILURE(S) — review above")
    print(f"{'=' * 60}\n")
    sys.exit(1 if failed > 0 else 0)


if __name__ == "__main__":
    main()
