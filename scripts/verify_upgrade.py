#!/usr/bin/env python3
"""
Post-upgrade verification for v1.25.0.

Only v1.25.0-specific checks are included. Generic prior-upgrade checks
have been removed per the /upgrade workflow: keep only checks needed
to validate THIS upgrade.

Checks:
  1. Required environment variables are set (DB URLs)
  2. Database connectivity (backend + indexer RO)
  3. Upgrade handler ran:
       - node logs contain "Starting upgrade to v1.25.0"
       - node logs contain "Upgrade to v1.25.0 complete"
       - node logs contain the post-migration params validation line
  4. Fail-fast contract is dormant (regression check):
       - no "panic:" + "CONSENSUS_FATAL:" co-occurrence in node logs
         after the upgrade height. CONSENSUS_FATAL is the new tag for
         deliberate halts on consensus-critical decode failures; in
         healthy steady state it MUST NOT fire.
  5. Chain liveness post-upgrade (indexer freshness): the chain is
     producing fresh blocks, which is the external proof that
     BeginBlock is successfully writing the new on-chain
     recent_block_hashes window every block.
  6. Frontend version cross-check (version.txt == v1.25.0).

Usage:
  python scripts/verify_upgrade.py                     # inside container
  docker exec mirage python3 /opt/mirage/scripts/verify_upgrade.py
"""
from __future__ import annotations

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


# Constants tied to THIS upgrade. If they change, this file must change.
UPGRADE_NAME = "v1.25.0"

# Tag prefix used by every fail-fast site introduced in v1.25.0
# (core.GetParams, deductRelayGasFee, processSubscriptions, PoW ante).
# In a healthy node this string MUST NOT appear after the upgrade height
# unless an operator deliberately corrupted state for testing.
CONSENSUS_FATAL_TAG = "CONSENSUS_FATAL:"

# Specific tags expected to never fire in steady state. We list them so
# that if a new tag is added in a future release without updating this
# checklist, we still catch it via the prefix scan above.
KNOWN_FATAL_TAGS = (
    "CONSENSUS_FATAL:PARAMS_STORE_GET",
    "CONSENSUS_FATAL:PARAMS_EMPTY",
    "CONSENSUS_FATAL:PARAMS_UNMARSHAL",
    "CONSENSUS_FATAL:PARAMS_VALIDATE",
    "CONSENSUS_FATAL:PROFILE_GET",
    "CONSENSUS_FATAL:PROFILE_MISSING",
    "CONSENSUS_FATAL:PROFILE_DECODE",
    "CONSENSUS_FATAL:RECENT_HASHES_GET",
    "CONSENSUS_FATAL:RECENT_HASHES_DECODE",
    "CONSENSUS_FATAL:RECENT_HASHES_WRITE",
)


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


# ─── v1.25.0 checks ──────────────────────────────────────────────────


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
        ok(f"{params_marker!r} present in node log (fail-fast GetParams sanity check passed)")
    else:
        warn(
            f"{params_marker!r} not found — handler may have run but the post-migration "
            f"params sanity log line was not emitted (rotated log?)"
        )


def check_no_consensus_fatal() -> None:
    """The whole point of v1.25.0 is that CONSENSUS_FATAL paths exist as
    a safety mechanism. In normal operation they MUST NOT fire — if they
    do, either we have a real bug or a real corruption event that needs
    investigation. Either way, the deploy is not green."""
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
    lines = content.splitlines()

    fatal_hits: list[tuple[int, str]] = []
    for i, line in enumerate(lines):
        if CONSENSUS_FATAL_TAG in line:
            fatal_hits.append((i + 1, line.strip()[:200]))

    if fatal_hits:
        fail(
            f"{CONSENSUS_FATAL_TAG} appeared {len(fatal_hits)} time(s) in latest node log — "
            f"one of the new fail-fast paths fired"
        )
        for lineno, snippet in fatal_hits[:5]:
            info(f"line {lineno}: {snippet}")
        if len(fatal_hits) > 5:
            info(f"... and {len(fatal_hits) - 5} more")
        return

    ok(f"no {CONSENSUS_FATAL_TAG} occurrences in latest node log")
    info(
        f"watched tags ({len(KNOWN_FATAL_TAGS)}): "
        f"{', '.join(t.split(':', 1)[1] for t in KNOWN_FATAL_TAGS)}"
    )


def check_indexer_freshness(conn: psycopg.Connection) -> None:
    """Post-upgrade liveness proof. Also serves as the implicit check
    that BeginBlock's RecordRecentBlockHash write is not failing — a
    failure there would propagate as a non-nil error from BeginBlock,
    halt the chain, and freeze the indexer."""
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
        ok(f"latest block is {age_sec:.0f}s old — chain is live, BeginBlock writes succeeding")
    elif age_sec < 600:
        warn(f"latest block is {age_sec:.0f}s old (slightly stale)")
    else:
        fail(f"latest block is {age_sec:.0f}s old — chain may have halted (check for CONSENSUS_FATAL)")


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

    section(f"4. CONSENSUS_FATAL Dormant (no fail-fast paths fired)")
    check_no_consensus_fatal()

    section("5. Chain Liveness (block production post-upgrade)")
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
