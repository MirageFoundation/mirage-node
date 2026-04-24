#!/usr/bin/env python3
"""
Post-upgrade verification for v1.24.0.

Only v1.24.0-specific checks are included. Generic prior-upgrade checks
(pruning logs, content tag normalization, log retention, etc.) have been
removed per the /upgrade workflow: keep only checks needed to validate
THIS upgrade.

Checks:
  1. Required environment variables are set (DB URLs)
  2. Database connectivity (backend + indexer RO)
  3. Upgrade handler ran:
       - node logs contain "Upgrade to v1.24.0 complete"
       - node logs do NOT contain "Upgrade to v1.24.0 complete" errors
  4. Never-halt invariant: chain is still producing blocks post-upgrade
     (indexer freshness) and no "panic" lines from the hardened code paths
     (core/GetParams, core/MintIfNeeded, EndBlock, BeginBlock) appear.
  5. Award cost cap (MaxAwardConfigCost = 1,000,000 MIRAGE):
       - /api/get_chain_config returns award_configs
       - every award_configs[i].cost <= 1_000_000_000_000 (umirage)
       - expected default AwardConfig names are present
  6. Cancel-unbonding ante rule: verify the binary is the v1.24.0 binary
     (version.txt frontend reports v1.24.0) — the actual rule is code-level
     and is enforced by compiled binary identity. An on-chain negative test
     (submit a non-self MsgCancelUnbondingDelegation, expect rejection)
     can be driven manually via scripts/integration tests.

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

try:
    import requests as _requests
except ImportError:
    print("FATAL: requests not installed")
    sys.exit(1)


# Constants tied to THIS upgrade. If they change, this file must change.
UPGRADE_NAME = "v1.24.0"
MAX_AWARD_CONFIG_COST_UMIRAGE = 1_000_000_000_000  # 1,000,000 MIRAGE
EXPECTED_AWARD_NAMES = {
    "quality_post",
    "original_content",
    "based",
    "receipts",
}

# Code paths hardened to never halt. A "panic:" line mentioning any of
# these strings in post-upgrade logs is a regression.
NEVER_HALT_SOURCE_HINTS = (
    "core/GetParams",
    "MintIfNeeded",
    "mint distribution",
    "BeginBlock",
    "EndBlock",
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


# ─── v1.24.0 checks ──────────────────────────────────────────────────


def find_latest_log(log_dir: Path) -> Path:
    logs = sorted(log_dir.glob("*.log"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not logs:
        raise RuntimeError(f"no log files found in {log_dir}")
    return logs[0]


def resolve_node_log_dir() -> Path:
    """Resolve node log directory across local + container layouts.

    Supported overrides/layouts:
    - NODE_LOG_DIR (explicit)
    - NODE_HOME/logs/node
    - NODE_HOME/logs
    - ~/.mirage/node/logs/node
    - ~/.mirage/logs/node
    - /root/.mirage/node/logs/node
    - /root/.mirage/logs/node
    """
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

    if start_marker in content:
        ok(f"{start_marker!r} present in node log")
    else:
        warn(f"{start_marker!r} not found in latest node log (may be in a rotated older file)")

    if done_marker in content:
        ok(f"{done_marker!r} present in node log")
    else:
        fail(f"{done_marker!r} not found — upgrade handler may not have run cleanly")


def check_never_halt_invariant() -> None:
    """A regression of the never-halt invariant would show up as a panic
    originating from BeginBlock/EndBlock/MintIfNeeded/GetParams code paths,
    NOT as a "chain continued on defaults" log line (those are expected and
    loud-but-benign). We scan for panic lines first, then for the benign
    fallback indicators as info."""
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
    regressions = []
    for i, line in enumerate(lines):
        lower = line.lower()
        if "panic:" not in lower and lower.strip() != "panic":
            continue

        # Go panics emit "panic: ..." and stack frames on subsequent lines.
        # Match source hints across a small post-panic window.
        window = "\n".join(lines[i : i + 40])
        for hint in NEVER_HALT_SOURCE_HINTS:
            if hint in window:
                regressions.append((line.strip()[:200], hint))
                break

    if regressions:
        fail(f"panic found in hardened code paths ({len(regressions)} lines)")
        for panic_line, hint in regressions[:5]:
            info(f"{panic_line} [matched hint: {hint}]")
    else:
        ok("no panic lines from hardened code paths (GetParams/MintIfNeeded/BeginBlock/EndBlock)")

    fallback_markers = [
        "falling back to defaults",
        "IterateValidators failed; skipping interval",
        "recipient slice length mismatch",
        "send failed; attempting to burn skipped reward",
        "BeginBlock:",
        "EndBlock:",
    ]
    hit_fallbacks = [m for m in fallback_markers if m in content]
    if hit_fallbacks:
        warn(
            f"benign never-halt log markers present ({len(hit_fallbacks)}: "
            f"{', '.join(hit_fallbacks)}) — investigate root cause separately"
        )
    else:
        info("no never-halt fallback markers fired (clean)")


def check_indexer_freshness(conn: psycopg.Connection) -> None:
    """Post-upgrade liveness proof: the chain is still producing blocks.
    This is the external confirmation that never-halt works in practice
    (if a halt had occurred we'd see a gap between wall clock and block
    time)."""
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
        fail(f"latest block is {age_sec:.0f}s old — chain may have halted")


def check_award_cost_cap(backend_api: str) -> None:
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

    awards = cfg.get("award_configs")
    if not isinstance(awards, list) or not awards:
        fail(
            "chain config has no award_configs (would imply fallback to defaults with empty list, or schema regression)"
        )
        return
    ok(f"chain config returned {len(awards)} award_configs")

    names_seen: set[str] = set()
    for i, entry in enumerate(awards):
        if not isinstance(entry, dict):
            fail(f"award_configs[{i}] is not an object: {type(entry).__name__}")
            continue
        name = entry.get("name", "")
        cost_raw = entry.get("cost")
        try:
            cost = int(cost_raw)
        except (TypeError, ValueError):
            fail(f"award_configs[{i}] cost is not an int: {cost_raw!r}")
            continue
        names_seen.add(name)
        if cost < 0:
            fail(f"award_configs[{i}] name={name!r} cost={cost} is negative")
        elif cost > MAX_AWARD_CONFIG_COST_UMIRAGE:
            fail(
                f"award_configs[{i}] name={name!r} cost={cost} umirage exceeds "
                f"MaxAwardConfigCost={MAX_AWARD_CONFIG_COST_UMIRAGE} — new Validate() should reject this"
            )
        else:
            ok(f"award_configs[{i}] name={name!r} cost={cost} umirage within cap")

    missing_defaults = EXPECTED_AWARD_NAMES - names_seen
    if missing_defaults:
        warn(
            f"default AwardConfig names missing: {sorted(missing_defaults)} "
            f"— chain may be on a custom governance-set table, verify manually"
        )
    else:
        ok(f"all expected default AwardConfig names present: {sorted(EXPECTED_AWARD_NAMES)}")


def check_binary_version() -> None:
    """Cross-check that the frontend version.txt (shipped with this release)
    reports v1.24.0. This is a cheap proxy for 'we shipped the correct
    binary' — operators running an older mirageapp static bundle will fail
    this check. It does NOT prove the on-chain binary version; that is
    implicit from the handler log check above."""
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

    section("4. Never-Halt Invariant (no panics from hardened paths)")
    check_never_halt_invariant()

    section("5. Chain Liveness (block production post-upgrade)")
    check_indexer_freshness(indexer_conn)

    section("6. Award Cost Cap (MaxAwardConfigCost = 1,000,000 MIRAGE)")
    check_award_cost_cap(backend_api)

    section("7. Binary Version Cross-Check")
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
