#!/usr/bin/env python3
"""
Post-deploy verification for v1.31.0.

Per the /upgrade workflow this file is rewritten every release to check ONLY
what THIS release changes — generic/prior-upgrade checks are removed so a green
run is a precise statement about the current rollout. It is a manual post-deploy
probe (not run automatically by deploy/deploy.sh):

  python scripts/verify_upgrade.py                       # inside container
  docker exec mirage python3 /opt/mirage/scripts/verify_upgrade.py

What v1.31.0 actually changes (deploy-visible, and therefore checked here)
-------------------------------------------------------------------------
v1.31.0 permanently removes the Solana bridge and orchestrator:

  1. Frontend version.txt reports v1.31.0.
  2. Indexer DB no longer has a bridge_transactions table
     (deploy/migrations/v1_31_0_drop_bridge_tables.py).
  3. Orchestrator is absent — no orchestrator.env, ~/.mirage/orchestrator,
     or ~/.orchestrator directory, and no orchestrator process / tmux window
     (deploy/migrations/v1_31_0_remove_orchestrator.py).
  4. Chain params no longer expose bridge_chains /
     bridge_attestation_threshold (removed in the v1.31.0 upgrade handler).
  5. The core KV store no longer contains bridge prefixes or scalar state.
  6. The chain is live after the rolling restart (indexer freshness).

Config paths are resolved from ENV_DIR (entrypoint sets this to
~/.mirage/env), or from the current user's home for local runs. DB URLs for
this script's own connections come from os.environ (create-time --env-file).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "web" / "backend"))

try:
    import psycopg
except ImportError:
    print("FATAL: psycopg not installed")
    sys.exit(1)


# ─── Constants tied to THIS release. If any change, this file must change. ─────

RELEASE_VERSION = "v1.31.0"

REMOVED_PARAM_FIELDS = ("bridge_chains", "bridge_attestation_threshold")

PARAMS_URL = "http://127.0.0.1:1317/mirage/core/v1/params"
COMET_RPC_URL = "http://127.0.0.1:26657"
BRIDGE_PREFIXES = (
    b"bridge_attestations/",
    b"bridge_attestors/",
    b"bridge_mint_attestations/",
    b"bridge_mint_attestors/",
    b"bridge_mint_fee_pending/",
    b"bridge_mint_fee_failures/",
    b"bridge_burns/",
    b"bridge_mints/",
    b"bridge_sequence/",
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
    # DB URLs for THIS script's own connections come from os.environ (create-time
    # --env-file), which is correct and present — they are not migration-managed.
    val = os.environ.get(key, "").strip()
    if not val:
        raise RuntimeError(f"{key} not set")
    return val


def mirage_home() -> Path:
    env_dir = os.environ.get("ENV_DIR", "").strip()
    if env_dir:
        return Path(env_dir).parent
    return Path.home() / ".mirage"


def env_dir() -> Path:
    env_dir_raw = os.environ.get("ENV_DIR", "").strip()
    if env_dir_raw:
        return Path(env_dir_raw)
    return mirage_home() / "env"


# ─── v1.31.0 checks ───────────────────────────────────────────────────────────


def check_frontend_version() -> None:
    """Require the deployed build version in-container, or the source version locally."""
    install_root = Path("/opt/mirage")
    if install_root.exists():
        version_path = install_root / "web" / "frontend" / "build" / "version.txt"
    else:
        version_path = Path(__file__).parent.parent / "web" / "frontend" / "public" / "version.txt"

    if not version_path.exists():
        fail(f"required version file is missing: {version_path}")
        return

    actual = version_path.read_text().strip()
    if actual != RELEASE_VERSION:
        fail(f"version.txt at {version_path} reports {actual!r}, expected {RELEASE_VERSION!r}")
        return
    ok(f"version.txt reports {actual} ({version_path})")


def check_bridge_table_gone(conn: psycopg.Connection) -> None:
    """bridge_transactions must be absent after v1_31_0_drop_bridge_tables."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_name = 'bridge_transactions'
            """
        )
        row = cur.fetchone()
    if row is None:
        ok("bridge_transactions table absent from indexer DB")
        return
    fail("bridge_transactions table still present in indexer DB — v1.31.0 drop migration not applied")


def check_orchestrator_absent() -> None:
    """Orchestrator files, process, and tmux window must all be gone."""
    home = mirage_home()
    orch_env = env_dir() / "orchestrator.env"
    orch_dir = home / "orchestrator"
    registry_dir = home.parent / ".orchestrator"

    if orch_env.exists():
        fail(f"orchestrator.env still present at {orch_env}")
    else:
        ok(f"orchestrator.env absent ({orch_env})")

    if orch_dir.exists():
        fail(f"orchestrator directory still present at {orch_dir}")
    else:
        ok(f"orchestrator directory absent ({orch_dir})")

    if registry_dir.exists():
        fail(f"legacy orchestrator registry still present at {registry_dir}")
    else:
        ok(f"legacy orchestrator registry absent ({registry_dir})")

    # Process check — match the same cmdline pattern the migration pkills.
    try:
        proc = subprocess.run(
            ["pgrep", "-af", "blockchain/bin/orchestrator"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except FileNotFoundError:
        fail("pgrep not available; cannot verify orchestrator process absence")
        proc = None
    except Exception as exc:
        fail(f"pgrep orchestrator check failed: {exc}")
        proc = None

    if proc is not None:
        if proc.returncode == 1:
            ok("no orchestrator process running")
        elif proc.returncode == 0:
            hits = [ln.strip() for ln in (proc.stdout or "").splitlines() if ln.strip() and "verify_upgrade" not in ln]
            if hits:
                fail(f"orchestrator process still running: {hits[0]}")
            else:
                fail("pgrep matched an orchestrator process but returned no usable process line")
        else:
            fail(f"pgrep orchestrator check failed: {(proc.stderr or '').strip() or proc.returncode}")

    # tmux window check — fail if session exists and lists an orchestrator window.
    try:
        list_result = subprocess.run(
            ["tmux", "list-windows", "-t", "mirage", "-F", "#{window_name}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except FileNotFoundError:
        info("tmux not available; skipping orchestrator window check")
        return
    except Exception as exc:
        fail(f"tmux list-windows failed: {exc}")
        return

    if list_result.returncode != 0:
        stderr = (list_result.stderr or "").strip()
        if (
            "no server running" in stderr.lower()
            or "can't find" in stderr.lower()
            or "session not found" in stderr.lower()
        ):
            ok("no mirage tmux session (orchestrator window absent)")
            return
        fail(f"tmux list-windows -t mirage failed: {stderr or list_result.returncode}")
        return

    windows = [w.strip() for w in (list_result.stdout or "").splitlines() if w.strip()]
    if "orchestrator" in windows:
        fail("tmux mirage session still has an 'orchestrator' window")
    else:
        ok(f"tmux mirage session has no orchestrator window ({len(windows)} window(s))")


def _abci_query(path: str, key: bytes) -> str | None:
    query = urllib.parse.urlencode(
        {
            "path": json.dumps(path),
            "data": f"0x{key.hex()}",
            "prove": "false",
        }
    )
    url = f"{COMET_RPC_URL}/abci_query?{query}"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            payload = json.loads(resp.read().decode("utf-8", "replace"))
    except Exception as exc:
        fail(f"ABCI query failed for {path} key={key!r}: {exc}")
        return None

    response = payload.get("result", {}).get("response", {})
    try:
        code = int(response.get("code", 0))
    except (TypeError, ValueError):
        fail(f"ABCI query returned invalid code for {path} key={key!r}: {response.get('code')!r}")
        return None
    if code != 0:
        fail(f"ABCI query failed for {path} key={key!r}: code={code} log={response.get('log', '')}")
        return None
    return str(response.get("value", "") or "")


def check_bridge_kv_absent() -> None:
    """The live core store must not retain any removed bridge state."""
    for prefix in BRIDGE_PREFIXES:
        value = _abci_query("/store/core/subspace", prefix)
        if value is None:
            continue
        if value:
            fail(f"core store still contains keys under removed prefix {prefix.decode()}")
        else:
            ok(f"core store prefix absent: {prefix.decode()}")

    scalar = _abci_query("/store/core/key", b"bridge_pending_count")
    if scalar is None:
        return
    if scalar:
        fail("core store still contains removed key bridge_pending_count")
    else:
        ok("core store key absent: bridge_pending_count")


def check_bridge_params_absent() -> None:
    """Live chain params must not still expose removed bridge fields."""
    try:
        with urllib.request.urlopen(PARAMS_URL, timeout=10) as resp:
            body = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        fail(f"GET {PARAMS_URL} returned HTTP {exc.code}")
        return
    except Exception as exc:
        fail(f"GET {PARAMS_URL} failed: {exc}")
        return

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        fail(f"params response is not JSON: {exc}")
        return

    params = payload.get("params")
    if not isinstance(params, dict):
        fail(f"params response missing object at .params (got {type(params).__name__})")
        return

    still_present = [k for k in REMOVED_PARAM_FIELDS if k in params]
    if still_present:
        fail(
            f"chain params still expose removed bridge field(s): {', '.join(still_present)} "
            f"— v1.31.0 upgrade handler not applied or old binary still running"
        )
        return

    # Also fail if the raw body somehow still names them outside .params keys.
    raw_hits = [k for k in REMOVED_PARAM_FIELDS if k in body]
    if raw_hits:
        fail(f"params JSON body still contains removed field name(s): {', '.join(raw_hits)}")
        return

    ok("chain params lack bridge_chains / bridge_attestation_threshold " f"({len(params)} param field(s) present)")


def check_indexer_freshness(conn: psycopg.Connection) -> None:
    """Post-restart liveness proof: if the chain is producing fresh blocks after
    the rolling restart, the deploy's consensus-neutral changes are executing
    without a fatal mismatch."""
    with conn.cursor() as cur:
        cur.execute("SELECT height, block_time FROM recent_blocks ORDER BY height DESC LIMIT 1")
        row = cur.fetchone()
    if not row or row[0] is None:
        fail("recent_blocks table is empty (indexer not running?)")
        return
    latest_height, latest_block_time = row
    ok(f"latest indexed block height={latest_height}")
    if latest_block_time is None:
        fail("block_time is NULL on latest block — cannot verify chain liveness")
        return
    try:
        if hasattr(latest_block_time, "timestamp"):
            block_ts = latest_block_time.timestamp()
        else:
            block_ts = float(latest_block_time)
    except Exception as exc:
        fail(f"could not parse block_time: {exc}")
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


# ─── Main ─────────────────────────────────────────────────────────────────────


def main() -> None:
    global passed, failed, warnings

    print("=" * 60)
    print(f"  Mirage Post-Deploy Verification ({RELEASE_VERSION})")
    print("=" * 60)

    section("1. Environment Variables")
    try:
        indexer_ro_url = require_env("INDEXER_DB_RO_URL")
        ok("INDEXER_DB_RO_URL is set")
    except Exception as exc:
        fail(str(exc))
        print("\nFATAL: Missing required environment variables")
        sys.exit(1)

    section("2. Database Connectivity")
    indexer_conn = None
    try:
        indexer_conn = psycopg.connect(indexer_ro_url, autocommit=True)
        ok("Indexer DB (RO) reachable")
    except Exception as exc:
        fail(f"Indexer DB (RO) unreachable: {exc}")
    if not indexer_conn:
        print("\nFATAL: Cannot proceed without indexer database connection")
        sys.exit(1)

    section("3. Frontend Version")
    check_frontend_version()

    section("4. Bridge Table Removed")
    check_bridge_table_gone(indexer_conn)

    section("5. Orchestrator Absent")
    check_orchestrator_absent()

    section("6. Bridge Params Removed")
    check_bridge_params_absent()

    section("7. Bridge KV State Removed")
    check_bridge_kv_absent()

    section("8. Chain Liveness")
    check_indexer_freshness(indexer_conn)

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
