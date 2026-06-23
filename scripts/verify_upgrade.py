#!/usr/bin/env python3
"""
Post-deploy verification for v1.28.2.

Only v1.28.2-specific checks are included. Generic prior-upgrade checks
have been removed per the /upgrade workflow: keep only checks needed to
validate THIS release.

What v1.28.2 actually changes
-----------------------------
This is a rolling PATCH release (no on-chain upgrade handler, no governance
proposal, no chain halt) — every change is consensus-neutral, halt-on-error,
disk-GC, or pure ops. The deploy-visible effects this script verifies:

  1. inter-block-cache = false in node app.toml (divergence mitigation,
     applied by deploy/migrations/v1_28_2_disable_inter_block_cache.py).
  2. iavl-disable-fastnode = true is still enforced (carried divergence knob).
  3. The chain is live after the rolling restart (indexer freshness).
  4. The shipped binary/frontend reports the release version.

Not verified here (no runtime signature):
  - store/v2 commit-info pruning drains over many prune passes; it is exercised
    by rootmulti/commit_info_prune_test.go, not observable in a point check.
  - consensus-path fail-fast reads + IAVL prune-hole guard only fire on an
    actual storage error; covered by Go tests (never_halt_test.go,
    nodedb_prune_fail_fast_test.go).

Usage:
  python scripts/verify_upgrade.py                     # inside container
  docker exec mirage python3 /opt/mirage/scripts/verify_upgrade.py
"""
from __future__ import annotations

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


# Constant tied to THIS release. If it changes, this file must change.
RELEASE_VERSION = "v1.28.2"


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


# ─── app.toml discovery ───────────────────────────────────────────────


def find_app_toml() -> Path | None:
    candidates = [
        Path("/root/.mirage/node/config/app.toml"),
        Path.home() / ".mirage" / "node" / "config" / "app.toml",
        Path.cwd() / "main" / "config" / "app.toml",
    ]
    for path in candidates:
        if path.exists():
            return path
    return None


def _read_toml_bool(content: str, key: str) -> str | None:
    m = re.search(rf"(?m)^\s*{re.escape(key)}\s*=\s*(true|false)\s*$", content)
    return m.group(1) if m else None


# ─── v1.28.2 checks ──────────────────────────────────────────────────


def check_inter_block_cache_disabled() -> None:
    """The primary v1.28.2 mitigation: the shared cross-block CommitKVStore
    cache must be off on disk so the next/already-applied restart runs without
    it. Fail hard — this is the headline change."""
    path = find_app_toml()
    if path is None:
        fail("app.toml not found in known locations; cannot verify inter-block-cache")
        return
    content = path.read_text(errors="ignore")
    val = _read_toml_bool(content, "inter-block-cache")
    if val is None:
        # Absent means the SDK default (enabled) applies — the migration should
        # have inserted an explicit false. Treat as failure.
        fail(f"app.toml has no inter-block-cache key (SDK default is ENABLED) ({path})")
        return
    if val != "false":
        fail(f"app.toml has inter-block-cache={val} (expected false) ({path})")
        return
    ok(f"app.toml enforces inter-block-cache=false ({path})")


def check_fastnode_disabled() -> None:
    """Carried divergence knob from v1.27/v1.28.0 — must remain enforced."""
    path = find_app_toml()
    if path is None:
        fail("app.toml not found in known locations; cannot verify iavl-disable-fastnode")
        return
    content = path.read_text(errors="ignore")
    val = _read_toml_bool(content, "iavl-disable-fastnode")
    if val is None:
        fail(f"app.toml missing iavl-disable-fastnode ({path})")
        return
    if val != "true":
        fail(f"app.toml has iavl-disable-fastnode={val} (expected true) ({path})")
        return
    ok(f"app.toml enforces iavl-disable-fastnode=true ({path})")


def check_indexer_freshness(conn: psycopg.Connection) -> None:
    """Post-restart liveness proof. If the chain is producing fresh blocks
    after the rolling restart, the consensus-neutral changes (store/v2 prune,
    fail-fast reads, cache disable) are executing without a fatal mismatch."""
    with conn.cursor() as cur:
        cur.execute("SELECT MAX(height), MAX(block_time) FROM recent_blocks")
        row = cur.fetchone()
    if not row or row[0] is None:
        fail("recent_blocks table is empty (indexer not running?)")
        return
    max_height, max_block_time = row
    ok(f"latest indexed block height={max_height}")
    if max_block_time is None:
        warn("block_time is NULL on latest block")
        return
    try:
        if hasattr(max_block_time, "timestamp"):
            block_ts = max_block_time.timestamp()
        else:
            block_ts = float(max_block_time)
    except Exception as exc:
        warn(f"could not parse block_time: {exc}")
        return
    age_sec = time.time() - block_ts
    if age_sec < 120:
        ok(f"latest block is {age_sec:.0f}s old — chain is live")
    elif age_sec < 600:
        warn(f"latest block is {age_sec:.0f}s old (slightly stale)")
    else:
        fail(
            f"latest block is {age_sec:.0f}s old — chain may have halted "
            f"(check node logs for CONSENSUS_FATAL or panic)"
        )


def check_binary_version() -> None:
    """Cross-check that the frontend version.txt (shipped with this release)
    reports the release version. Cheap proxy for 'we shipped the correct
    binary'."""
    candidates = [
        Path("/opt/mirage/web/frontend/build/version.txt"),
        Path("/opt/mirage/web/frontend/public/version.txt"),
        Path.cwd() / "web" / "frontend" / "build" / "version.txt",
        Path.cwd() / "web" / "frontend" / "public" / "version.txt",
        Path(__file__).parent.parent / "web" / "frontend" / "build" / "version.txt",
        Path(__file__).parent.parent / "web" / "frontend" / "public" / "version.txt",
    ]
    for p in candidates:
        if not p.exists():
            continue
        actual = p.read_text().strip()
        if actual == RELEASE_VERSION:
            ok(f"version.txt reports {actual} ({p})")
            return
        fail(f"version.txt at {p} reports {actual!r}, expected {RELEASE_VERSION!r}")
        return
    warn("version.txt not found in any known location; skipping frontend version cross-check")


# ─── Main ─────────────────────────────────────────────────────────────


def main() -> None:
    global passed, failed, warnings

    print("=" * 60)
    print(f"  Mirage Post-Deploy Verification ({RELEASE_VERSION})")
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

    section("2. Database Connectivity")
    indexer_conn = None
    backend_conn = None
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
    if not indexer_conn or not backend_conn:
        print("\nFATAL: Cannot proceed without database connections")
        sys.exit(1)

    section("3. inter-block-cache disabled (v1.28.2 mitigation)")
    check_inter_block_cache_disabled()

    section("4. iavl-disable-fastnode still enforced")
    check_fastnode_disabled()

    section("5. Chain Liveness")
    check_indexer_freshness(indexer_conn)

    section("6. Binary Version Cross-Check")
    check_binary_version()

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
