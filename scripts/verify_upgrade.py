#!/usr/bin/env python3
"""
Post-upgrade verification for v1.27.0.

Only v1.27.0-specific checks are included. Generic prior-upgrade checks
have been removed per the /upgrade workflow: keep only checks needed to
validate THIS upgrade.

What v1.27.0 actually changes
-----------------------------
The upgrade coordinates three divergence-hardening changes:
1) canonical IAVL reads are authoritative (fast-node no longer drives
   consensus reads),
2) EndBlock enforces supply == sum(balances) and halts on mismatch,
3) deploy/runtime forces iavl-disable-fastnode=true.

No store migrations, params, or new keys are introduced, but the behavior
change is consensus-critical and must activate at one height.

Checks
------
  1. Required environment variables are set (DB URLs)
  2. Database connectivity (backend + indexer RO)
  3. Upgrade handler ran:
       - node logs contain "Starting upgrade to v1.27.0"
       - node logs contain "Upgrade to v1.27.0 complete"
       - node logs contain the post-migration params validation line
  4. Runtime config hardening is active:
       - app.toml contains iavl-disable-fastnode = true
  5. Chain liveness post-upgrade (indexer freshness)
  6. Frontend version cross-check (version.txt == v1.27.0).

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


# Constants tied to THIS upgrade. If they change, this file must change.
UPGRADE_NAME = "v1.27.0"


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


# ─── Log discovery ────────────────────────────────────────────────────


def find_latest_log(log_dir: Path) -> Path:
    logs = sorted(log_dir.glob("*.log"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not logs:
        raise RuntimeError(f"no log files found in {log_dir}")
    return logs[0]


def resolve_node_log_dir() -> Path:
    """Resolve node log directory across local + container layouts."""
    explicit = os.environ.get("NODE_LOG_DIR", "").strip()
    if explicit:
        p = Path(explicit).expanduser()
        if p.exists():
            return p
        raise RuntimeError(f"NODE_LOG_DIR set but path does not exist: {p}")

    node_home_raw = os.environ.get("NODE_HOME", "").strip()
    node_home = Path(node_home_raw).expanduser() if node_home_raw else Path.home() / ".mirage" / "node"

    candidates = [
        node_home / "logs" / "node",
        node_home / "logs",
        Path.home() / ".mirage" / "node" / "logs" / "node",
        Path.home() / ".mirage" / "logs" / "node",
        Path("/root/.mirage/node/logs/node"),
        Path("/root/.mirage/logs/node"),
    ]
    for c in candidates:
        if c.exists():
            return c

    tried = ", ".join(str(c) for c in candidates)
    raise RuntimeError(f"node log dir not found; tried: {tried}")


# ─── v1.27.0 checks ──────────────────────────────────────────────────


def check_upgrade_handler_ran() -> None:
    try:
        log_dir = resolve_node_log_dir()
    except Exception as exc:
        fail(str(exc))
        return
    try:
        log_path = find_latest_log(log_dir)
    except Exception as exc:
        fail(str(exc))
        return

    content = log_path.read_text(errors="ignore")
    start_marker = f"Starting upgrade to {UPGRADE_NAME}"
    done_marker = f"Upgrade to {UPGRADE_NAME} complete"
    params_marker = f"{UPGRADE_NAME}: params validated post-migration"

    if start_marker in content:
        ok(f"{start_marker!r} present in node log")
    else:
        warn(f"{start_marker!r} not found in latest node log (may be in a rotated older file)")

    if done_marker in content:
        ok(f"{done_marker!r} present in node log")
    else:
        fail(f"{done_marker!r} not found — upgrade handler may not have run cleanly")

    if params_marker in content:
        ok(f"{params_marker!r} present in node log (post-migration params validation passed)")
    else:
        warn(
            f"{params_marker!r} not found — handler may have run but the post-migration "
            f"params sanity log line was not emitted (rotated log?)"
        )


def check_fastnode_disabled() -> None:
    candidates = [
        Path("/root/.mirage/node/config/app.toml"),
        Path.home() / ".mirage" / "node" / "config" / "app.toml",
        Path.cwd() / "main" / "config" / "app.toml",
    ]
    for path in candidates:
        if not path.exists():
            continue
        content = path.read_text(errors="ignore")
        m = re.search(r"(?m)^\s*iavl-disable-fastnode\s*=\s*(true|false)\s*$", content)
        if not m:
            fail(f"app.toml missing iavl-disable-fastnode ({path})")
            return
        if m.group(1) != "true":
            fail(f"app.toml has iavl-disable-fastnode={m.group(1)} (expected true) ({path})")
            return
        ok(f"app.toml enforces iavl-disable-fastnode=true ({path})")
        return
    fail("app.toml not found in known locations; cannot verify iavl-disable-fastnode")


def check_indexer_freshness(conn: psycopg.Connection) -> None:
    """Post-upgrade liveness proof for v1.27.0 divergence hardening.
    If the chain is producing fresh blocks after activation, the canonical-read
    and supply-invariant paths are executing without fatal mismatch."""
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
    """Cross-check that the frontend version.txt (shipped with this
    release) reports the upgrade target. Cheap proxy for 'we shipped the
    correct binary'."""
    candidates = [
        Path("/opt/mirage/web/frontend/public/version.txt"),
        Path.cwd() / "web" / "frontend" / "public" / "version.txt",
        Path(__file__).parent.parent / "web" / "frontend" / "public" / "version.txt",
    ]
    for p in candidates:
        if not p.exists():
            continue
        actual = p.read_text().strip()
        if actual == UPGRADE_NAME:
            ok(f"version.txt reports {actual} ({p})")
            return
        fail(f"version.txt at {p} reports {actual!r}, expected {UPGRADE_NAME!r}")
        return
    warn("version.txt not found in any known location; skipping frontend version cross-check")


# ─── Main ─────────────────────────────────────────────────────────────


def main() -> None:
    global passed, failed, warnings

    print("=" * 60)
    print(f"  Mirage Post-Upgrade Verification ({UPGRADE_NAME})")
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

    section(f"3. Upgrade Handler ({UPGRADE_NAME})")
    check_upgrade_handler_ran()

    section("4. Runtime Config Hardening")
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
