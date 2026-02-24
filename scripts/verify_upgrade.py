#!/usr/bin/env python3
"""
Post-migration verification for mirage nodes.

Checks that PebbleDB migration completed successfully and no artifacts remain.
Runs from a local machine, SSHing into the target server(s).

Usage:
  ./scripts/verify_upgrade.py root@64.23.136.132
  ./scripts/verify_upgrade.py root@64.23.136.132 root@159.203.114.27
  ./scripts/verify_upgrade.py --all
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone


ALL_SERVERS = [
    "root@159.203.114.27",
    "root@64.23.136.132",
    "root@146.190.108.140",
    "root@139.59.9.96",
]

DATA_DIR = "$HOME/.mirage/node/data"
ENV_FILE = "$HOME/.mirage/env/node.env"
CONTAINER = "mirage"


def ssh(server: str, cmd: str, *, quiet: bool = False) -> tuple[int, str]:
    p = subprocess.run(
        ["ssh", server, cmd],
        capture_output=True, text=True, timeout=30,
    )
    out = (p.stdout + p.stderr).strip()
    if not quiet and p.returncode != 0 and out:
        pass  # caller handles
    return p.returncode, out


def ssh_ok(server: str, cmd: str) -> str:
    rc, out = ssh(server, cmd)
    if rc != 0:
        raise RuntimeError(out or f"exit {rc}")
    return out


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def check_app_db_backend(server: str, failures: list[str]) -> None:
    print("  -> APP_DB_BACKEND in node.env")
    try:
        out = ssh_ok(server, f"grep '^APP_DB_BACKEND=' {ENV_FILE} | cut -d= -f2-")
        if out == "pebbledb":
            print(f"     [OK] {out}")
        else:
            print(f"     [FAIL] {out} (expected pebbledb)")
            failures.append(f"APP_DB_BACKEND={out!r}, expected 'pebbledb'")
    except Exception as e:
        print(f"     [FAIL] {e}")
        failures.append(f"cannot read APP_DB_BACKEND: {e}")


def check_application_db_format(server: str, failures: list[str]) -> None:
    print("  -> application.db format")
    try:
        out = ssh_ok(server, f"ls {DATA_DIR}/application.db/ 2>/dev/null | head -5")
        files = out.strip().splitlines()
        has_ldb = any(f.endswith(".ldb") for f in files)
        has_sst = any(f.endswith(".sst") for f in files)
        has_manifest = any(f.startswith("MANIFEST") for f in files)

        if has_sst and has_manifest and not has_ldb:
            count = ssh_ok(server, f"ls {DATA_DIR}/application.db/*.sst 2>/dev/null | wc -l").strip()
            print(f"     [OK] PebbleDB ({count} SST files)")
        elif has_ldb:
            print("     [FAIL] GoLevelDB format (.ldb files present)")
            failures.append("application.db is still GoLevelDB")
        else:
            print(f"     [WARN] unexpected contents: {files[:5]}")
            failures.append(f"application.db unexpected format: {files[:5]}")
    except Exception as e:
        print(f"     [FAIL] {e}")
        failures.append(f"cannot check application.db: {e}")


def check_snapshots_metadata(server: str, failures: list[str]) -> None:
    print("  -> snapshots/metadata.db")
    try:
        rc, out = ssh(server, f"ls {DATA_DIR}/snapshots/metadata.db/*.ldb 2>/dev/null | wc -l", quiet=True)
        ldb_count = int(out.strip()) if rc == 0 else 0

        if ldb_count > 0:
            print(f"     [FAIL] GoLevelDB metadata.db still present ({ldb_count} .ldb files)")
            failures.append("snapshots/metadata.db is still GoLevelDB — will cause panic")
        else:
            rc2, out2 = ssh(server, f"test -d {DATA_DIR}/snapshots/metadata.db && echo exists || echo missing", quiet=True)
            if "missing" in out2:
                print("     [OK] removed (will be recreated as PebbleDB)")
            else:
                rc3, out3 = ssh(server, f"ls {DATA_DIR}/snapshots/metadata.db/*.sst 2>/dev/null | wc -l", quiet=True)
                sst_count = int(out3.strip()) if rc3 == 0 else 0
                if sst_count > 0:
                    print(f"     [OK] PebbleDB format ({sst_count} SST files)")
                else:
                    print("     [OK] exists, no .ldb files")
    except Exception as e:
        print(f"     [FAIL] {e}")
        failures.append(f"cannot check metadata.db: {e}")


def check_no_artifacts(server: str, failures: list[str]) -> None:
    print("  -> leftover artifacts")
    clean = True

    for path, label in [
        (f"{DATA_DIR}/application.db.bak", "application.db.bak"),
        (f"{DATA_DIR}/_pebble_convert_tmp", "_pebble_convert_tmp"),
        ("/tmp/convert-db", "/tmp/convert-db"),
    ]:
        rc, _ = ssh(server, f"test -e {path}", quiet=True)
        if rc == 0:
            print(f"     [FAIL] {label} still exists")
            failures.append(f"artifact: {label}")
            clean = False

    if clean:
        print("     [OK] no artifacts")


def check_node_health(server: str, failures: list[str]) -> None:
    print("  -> node health (RPC)")
    try:
        out = ssh_ok(server, "curl -sf http://localhost:26657/status 2>/dev/null")
        data = json.loads(out)
        sync = data.get("result", {}).get("sync_info", {})
        height = sync.get("latest_block_height", "0")
        catching_up = sync.get("catching_up", True)

        if not catching_up and int(height) > 0:
            print(f"     [OK] synced at height {height}")
        else:
            print(f"     [FAIL] height={height} catching_up={catching_up}")
            failures.append(f"node not synced: height={height} catching_up={catching_up}")
    except Exception as e:
        print(f"     [FAIL] {e}")
        failures.append(f"cannot check node health: {e}")


def check_bond_denom(server: str, failures: list[str]) -> None:
    print("  -> bond_denom validation")
    try:
        out = ssh_ok(
            server,
            f"docker exec {CONTAINER} curl -sf http://localhost:1317/cosmos/staking/v1beta1/params 2>/dev/null",
        )
        data = json.loads(out)
        denom = data.get("params", {}).get("bond_denom", "")

        if denom == "umirage":
            print(f"     [OK] bond_denom={denom}")
        elif not denom:
            print("     [WARN] bond_denom empty (REST API may not be ready)")
            failures.append("bond_denom empty — verify manually")
        else:
            print(f"     [FAIL] bond_denom={denom!r} (expected 'umirage')")
            failures.append(f"bond_denom={denom!r}, expected 'umirage'")
    except Exception as e:
        print(f"     [WARN] cannot query bond_denom: {e}")


def check_no_fatal_errors(server: str, failures: list[str]) -> None:
    print("  -> FATAL errors in today's log")
    try:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        logfile = f"$HOME/.mirage/logs/node/miraged-{today}.log"
        rc, out = ssh(server, f"grep -c FATAL {logfile} 2>/dev/null || echo 0", quiet=True)
        count = int(out.strip().splitlines()[-1])

        if count == 0:
            print("     [OK] no FATAL errors")
        else:
            rc2, fatals = ssh(server, f"grep FATAL {logfile} | tail -3", quiet=True)
            print(f"     [WARN] {count} FATAL error(s) in today's log:")
            for line in fatals.strip().splitlines()[:3]:
                print(f"       {line.strip()[:120]}")
            failures.append(f"{count} FATAL error(s) in today's log")
    except Exception as e:
        print(f"     [FAIL] {e}")
        failures.append(f"cannot check logs: {e}")


def check_db_size(server: str, _failures: list[str]) -> None:
    print("  -> database sizes")
    try:
        out = ssh_ok(server, f"du -sh {DATA_DIR}/application.db 2>/dev/null || echo 'not found'")
        print(f"     application.db: {out.split()[0]}")
        out2 = ssh_ok(server, f"df -h {DATA_DIR} | tail -1")
        parts = out2.split()
        if len(parts) >= 5:
            print(f"     disk: {parts[2]} used / {parts[1]} total ({parts[4]})")
    except Exception as e:
        print(f"     [WARN] {e}")


def check_container_running(server: str, failures: list[str]) -> None:
    print("  -> container status")
    try:
        out = ssh_ok(server, f"docker inspect -f '{{{{.State.Status}}}}' {CONTAINER} 2>/dev/null")
        if out.strip() == "running":
            print("     [OK] container running")
        else:
            print(f"     [FAIL] container status: {out.strip()}")
            failures.append(f"container not running: {out.strip()}")
    except Exception as e:
        print(f"     [FAIL] {e}")
        failures.append(f"cannot check container: {e}")


def check_miraged_process(server: str, failures: list[str]) -> None:
    print("  -> miraged process")
    try:
        rc, out = ssh(server, f"docker exec {CONTAINER} pgrep -x miraged", quiet=True)
        if rc == 0 and out.strip():
            print("     [OK] miraged running")
        else:
            print("     [FAIL] miraged not running inside container")
            failures.append("miraged process not found")
    except Exception as e:
        print(f"     [FAIL] {e}")
        failures.append(f"cannot check miraged process: {e}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def verify_server(server: str) -> list[str]:
    failures: list[str] = []

    check_container_running(server, failures)
    check_miraged_process(server, failures)
    check_app_db_backend(server, failures)
    check_application_db_format(server, failures)
    check_snapshots_metadata(server, failures)
    check_no_artifacts(server, failures)
    check_node_health(server, failures)
    check_bond_denom(server, failures)
    check_no_fatal_errors(server, failures)
    check_db_size(server, failures)

    return failures


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify PebbleDB migration completed successfully",
    )
    parser.add_argument("servers", nargs="*", help="SSH targets (e.g. root@64.23.136.132)")
    parser.add_argument("--all", action="store_true", help="Check all known servers")
    args = parser.parse_args()

    servers = ALL_SERVERS if args.all else args.servers
    if not servers:
        parser.error("provide server(s) or use --all")

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print("=" * 60)
    print(f"PebbleDB Migration Verification — {ts}")
    print("=" * 60)

    all_failures: dict[str, list[str]] = {}

    for server in servers:
        print(f"\n{'─' * 60}")
        print(f"Server: {server}")
        print("─" * 60)
        failures = verify_server(server)
        if failures:
            all_failures[server] = failures

    print(f"\n{'=' * 60}")
    if all_failures:
        total = sum(len(f) for f in all_failures.values())
        print(f"FAILED — {total} issue(s) on {len(all_failures)} server(s):\n")
        for srv, fails in all_failures.items():
            print(f"  {srv}:")
            for f in fails:
                print(f"    - {f}")
        return 1

    print(f"PASSED — all {len(servers)} server(s) verified.")
    print("PebbleDB migration complete. No artifacts. Nodes healthy.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
