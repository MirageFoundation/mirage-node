#!/usr/bin/env python3
"""
Migrate a mirage node's databases from GoLevelDB to PebbleDB.

Converts ALL databases (application, blockstore, state, tx_index, evidence),
cleans up stale files (cs.wal, metadata.db), switches both app-db-backend
and db_backend to pebbledb, waits for catch-up, and runs verification.

Usage:
    ./scripts/migrate_pebbledb.py root@64.23.136.132
    ./scripts/migrate_pebbledb.py root@mirage.vote
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
BLOCKCHAIN_DIR = REPO_ROOT / "blockchain"

DATA_DIR = "$HOME/.mirage/node/data"
ENV_FILE = "$HOME/.mirage/env/node.env"
CONTAINER = "mirage"

ALL_DBS = ["application", "blockstore", "state", "tx_index", "evidence"]


# ---------------------------------------------------------------------------
# SSH / SCP helpers
# ---------------------------------------------------------------------------


def ssh(server: str, cmd: str, *, timeout: int = 30) -> tuple[int, str]:
    p = subprocess.run(
        ["ssh", server, cmd],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return p.returncode, (p.stdout + p.stderr).strip()


def ssh_ok(server: str, cmd: str, *, timeout: int = 30) -> str:
    rc, out = ssh(server, cmd, timeout=timeout)
    if rc != 0:
        raise RuntimeError(out or f"exit code {rc}")
    return out


def scp(local: str, remote: str) -> None:
    subprocess.run(["scp", local, remote], check=True)


def die(msg: str) -> None:
    print(f"\nERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def step(n: str, msg: str) -> None:
    print(f"\n{'='*60}")
    print(f"  Step {n}: {msg}")
    print(f"{'='*60}")


# ---------------------------------------------------------------------------
# Size snapshot helpers
# ---------------------------------------------------------------------------


def snapshot_sizes(server: str) -> dict[str, int]:
    """Capture byte sizes of all data directories on the server."""
    paths = [
        ("application.db", f"{DATA_DIR}/application.db"),
        ("blockstore.db", f"{DATA_DIR}/blockstore.db"),
        ("state.db", f"{DATA_DIR}/state.db"),
        ("tx_index.db", f"{DATA_DIR}/tx_index.db"),
        ("evidence.db", f"{DATA_DIR}/evidence.db"),
        ("cs.wal/", f"{DATA_DIR}/cs.wal"),
        ("snapshots/", f"{DATA_DIR}/snapshots"),
        ("data/ (total)", DATA_DIR),
    ]
    sizes: dict[str, int] = {}
    for label, path in paths:
        rc, out = ssh(server, f"du -sb {path} 2>/dev/null | cut -f1")
        if rc == 0 and out.strip().isdigit():
            sizes[label] = int(out.strip())
    rc, out = ssh(server, f"df -B1 {DATA_DIR} | tail -1")
    if rc == 0:
        parts = out.split()
        if len(parts) >= 4:
            sizes["_disk_used"] = int(parts[2])
            sizes["_disk_total"] = int(parts[1])
    return sizes


def fmt_bytes(b: int) -> str:
    if b >= 1 << 30:
        return f"{b / (1 << 30):.2f} GB"
    if b >= 1 << 20:
        return f"{b / (1 << 20):.1f} MB"
    if b >= 1 << 10:
        return f"{b / (1 << 10):.0f} KB"
    return f"{b} B"


def print_size_comparison(before: dict[str, int], after: dict[str, int]) -> None:
    print(f"\n{'─'*64}")
    print(f"  {'':30s} {'BEFORE':>10s}  {'AFTER':>10s}  {'CHANGE':>10s}")
    print(f"{'─'*64}")

    for label in before:
        if label.startswith("_"):
            continue
        b = before.get(label, 0)
        a = after.get(label, 0)
        if b == 0 and a == 0:
            continue
        diff = a - b
        if diff == 0:
            change = "—"
        elif diff < 0:
            pct = abs(diff) / b * 100 if b else 0
            change = f"-{fmt_bytes(abs(diff))} ({pct:.0f}%)"
        else:
            pct = diff / b * 100 if b else 0
            change = f"+{fmt_bytes(diff)} ({pct:.0f}%)"
        print(f"  {label:30s} {fmt_bytes(b):>10s}  {fmt_bytes(a):>10s}  {change}")

    b_disk = before.get("_disk_used", 0)
    a_disk = after.get("_disk_used", 0)
    t_disk = after.get("_disk_total", 0) or before.get("_disk_total", 0)
    if b_disk and a_disk:
        diff = a_disk - b_disk
        sign = "-" if diff < 0 else "+"
        print(f"{'─'*64}")
        print(f"  {'Disk used':30s} {fmt_bytes(b_disk):>10s}  {fmt_bytes(a_disk):>10s}  {sign}{fmt_bytes(abs(diff))}")
        if t_disk:
            print(f"  {'Disk total':30s} {fmt_bytes(t_disk):>10s}")
    print(f"{'─'*64}")


# ---------------------------------------------------------------------------
# RPC helpers
# ---------------------------------------------------------------------------


def get_sync_info(server: str) -> tuple[int, bool | None]:
    """Returns (height, catching_up). catching_up is None if RPC unavailable."""
    rc, out = ssh(server, "curl -sf http://localhost:26657/status 2>/dev/null")
    if rc != 0 or not out:
        return 0, None
    try:
        sync = json.loads(out).get("result", {}).get("sync_info", {})
        return int(sync.get("latest_block_height", 0)), sync.get("catching_up")
    except (json.JSONDecodeError, ValueError):
        return 0, None


def get_bond_denom(server: str) -> str:
    rc, out = ssh(
        server,
        f"docker exec {CONTAINER} curl -sf http://localhost:1317/cosmos/staking/v1beta1/params 2>/dev/null",
    )
    if rc != 0 or not out:
        return ""
    try:
        return json.loads(out).get("params", {}).get("bond_denom", "")
    except (json.JSONDecodeError, AttributeError):
        return ""


# ---------------------------------------------------------------------------
# Migration steps
# ---------------------------------------------------------------------------


def preflight(server: str) -> dict[str, int]:
    step("1/8", "Preflight checks")

    backend = ssh_ok(server, f"grep '^APP_DB_BACKEND=' {ENV_FILE} | cut -d= -f2-")
    if backend == "pebbledb":
        die(f"Already running PebbleDB on {server}")
    print(f"  Current backend: {backend}")

    height, catching_up = get_sync_info(server)
    if catching_up is None:
        die("Node RPC not available — is the container running?")
    print(f"  Node height: {height}, catching_up: {catching_up}")

    print("  Capturing file sizes (before)...")
    sizes = snapshot_sizes(server)
    for label, b in sizes.items():
        if not label.startswith("_"):
            print(f"    {label:30s} {fmt_bytes(b)}")
    disk_used = sizes.get("_disk_used", 0)
    disk_total = sizes.get("_disk_total", 0)
    if disk_used and disk_total:
        pct = disk_used / disk_total * 100
        print(f"    {'Disk':30s} {fmt_bytes(disk_used)} / {fmt_bytes(disk_total)} ({pct:.0f}%)")

    return sizes


def build_converter() -> str:
    step("2/8", "Cross-compiling convert-db for linux/amd64")

    env = {**os.environ, "GOOS": "linux", "GOARCH": "amd64"}
    p = subprocess.run(
        ["make", "build-convert-db"],
        cwd=str(BLOCKCHAIN_DIR),
        env=env,
        capture_output=True,
        text=True,
    )
    if p.returncode != 0:
        die(f"Build failed:\n{p.stderr}")

    binary = BLOCKCHAIN_DIR / "bin" / "convert-db"
    if not binary.exists():
        die(f"Binary not found at {binary}")

    size_mb = binary.stat().st_size / (1024 * 1024)
    print(f"  Built: {binary} ({size_mb:.1f} MB)")
    return str(binary)


def upload_converter(server: str, binary: str) -> None:
    step("3/8", f"Uploading convert-db to {server}")
    scp(binary, f"{server}:/tmp/convert-db")
    ssh_ok(server, "chmod +x /tmp/convert-db")
    print("  Uploaded to /tmp/convert-db")


def stop_and_convert(server: str) -> None:
    step("4/8", "Stopping container and converting all databases")
    ssh_ok(server, f"docker stop --timeout=30 {CONTAINER}", timeout=60)
    print("  Container stopped.\n")

    db_args = " ".join(ALL_DBS)
    p = subprocess.run(
        ["ssh", server, f"/tmp/convert-db {DATA_DIR} {db_args}"],
        timeout=1200,
    )
    if p.returncode != 0:
        print("  CONVERTER FAILED — restarting container with original DB")
        ssh(server, f"docker start {CONTAINER}")
        die("Conversion failed. Node restarted with GoLevelDB.")

    print("\n  Cleaning up stale files...")
    ssh(server, f"rm -rf {DATA_DIR}/snapshots/metadata.db")
    print("    Removed snapshots/metadata.db (recreated as PebbleDB)")
    ssh(server, f"rm -rf {DATA_DIR}/cs.wal")
    print("    Removed cs.wal/ (recreated on start)")

    print("  Removing GoLevelDB backups...")
    for db in ALL_DBS:
        ssh(server, f"rm -rf {DATA_DIR}/{db}.db.bak")
    print("    All .bak files removed.")


def switch_backend(server: str) -> None:
    step("5/8", "Setting database backends to pebbledb")

    ssh_ok(server, f"sed -i 's/^APP_DB_BACKEND=.*/APP_DB_BACKEND=pebbledb/' {ENV_FILE}")
    # COMET_DB_BACKEND — add if missing, update if present
    rc, _ = ssh(server, f"grep -q '^COMET_DB_BACKEND=' {ENV_FILE}")
    if rc == 0:
        ssh_ok(server, f"sed -i 's/^COMET_DB_BACKEND=.*/COMET_DB_BACKEND=pebbledb/' {ENV_FILE}")
    else:
        ssh_ok(server, f"echo 'COMET_DB_BACKEND=pebbledb' >> {ENV_FILE}")

    verify_app = ssh_ok(server, f"grep '^APP_DB_BACKEND=' {ENV_FILE} | cut -d= -f2-")
    verify_cmt = ssh_ok(server, f"grep '^COMET_DB_BACKEND=' {ENV_FILE} | cut -d= -f2-")
    if verify_app != "pebbledb" or verify_cmt != "pebbledb":
        die(f"Failed to update backends (APP_DB_BACKEND={verify_app}, COMET_DB_BACKEND={verify_cmt})")
    print(f"  APP_DB_BACKEND=pebbledb")
    print(f"  COMET_DB_BACKEND=pebbledb")


def start_and_wait(server: str) -> None:
    step("6/8", "Starting container and waiting for sync")
    ssh_ok(server, f"docker start {CONTAINER}")
    print("  Container started. Waiting for node to sync...\n")

    last_height = 0
    stall_count = 0

    for tick in range(1, 241):  # up to 20 minutes
        time.sleep(5)
        elapsed = tick * 5
        height, catching_up = get_sync_info(server)

        if catching_up is None:
            print(f"  [{elapsed:>4}s] RPC not ready...")
            continue

        if catching_up is False and height > 0:
            print(f"  [{elapsed:>4}s] ✓ Synced at height {height}")
            return

        if height > last_height:
            stall_count = 0
            last_height = height
        else:
            stall_count += 1

        status_str = "catching up" if catching_up else "syncing"
        print(f"  [{elapsed:>4}s] height={height} ({status_str})")

        if stall_count >= 6:
            print(f"\n  WARNING: No height progress for {stall_count * 5}s")
            stall_count = 0

    print("\n  WARNING: Timed out after 20 minutes. Node may still be catching up.")
    print(f"  Check: ssh {server} 'curl -s localhost:26657/status | jq .result.sync_info'")


def cleanup(server: str) -> None:
    step("7/8", "Cleanup")
    ssh(server, "rm -f /tmp/convert-db")
    ssh(server, f"rm -rf {DATA_DIR}/_pebble_convert_tmp*")
    print("  Removed converter binary and temp files.")


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------


def verify(server: str, before_sizes: dict[str, int]) -> int:
    step("8/8", "Verification")
    failures: list[str] = []

    # Container running
    print("  -> container status")
    rc, out = ssh(server, f"docker inspect -f '{{{{.State.Status}}}}' {CONTAINER}")
    if rc == 0 and out.strip() == "running":
        print("     [OK] running")
    else:
        print(f"     [FAIL] {out.strip()}")
        failures.append("container not running")

    # miraged process
    print("  -> miraged process")
    rc, _ = ssh(server, f"docker exec {CONTAINER} pgrep -x miraged")
    if rc == 0:
        print("     [OK] alive")
    else:
        print("     [FAIL] miraged not running")
        failures.append("miraged not running")

    print("  -> database backends")
    for var, label in [("APP_DB_BACKEND", "APP_DB_BACKEND"), ("COMET_DB_BACKEND", "COMET_DB_BACKEND")]:
        rc, out = ssh(server, f"grep '^{var}=' {ENV_FILE} | cut -d= -f2-")
        val = out.strip()
        if val == "pebbledb":
            print(f"     [OK] {label}=pebbledb")
        else:
            print(f"     [FAIL] {label}={val}")
            failures.append(f"{label}={val!r}")

    # All databases should be PebbleDB format
    print("  -> database formats")
    for db in ALL_DBS:
        rc, out = ssh(server, f"ls {DATA_DIR}/{db}.db/ 2>/dev/null")
        if rc != 0:
            continue
        files = out.strip().splitlines()
        has_sst = any(f.endswith(".sst") for f in files)
        has_ldb = any(f.endswith(".ldb") for f in files)
        has_manifest = any(f.startswith("MANIFEST") for f in files)
        if has_sst and has_manifest and not has_ldb:
            sst_count = sum(1 for f in files if f.endswith(".sst"))
            print(f"     [OK] {db}.db — PebbleDB ({sst_count} SST files)")
        elif has_ldb:
            print(f"     [FAIL] {db}.db — still GoLevelDB")
            failures.append(f"{db}.db is GoLevelDB")
        elif not files:
            print(f"     [OK] {db}.db — empty (will be created)")

    # snapshots/metadata.db
    print("  -> snapshots/metadata.db")
    rc, out = ssh(server, f"ls {DATA_DIR}/snapshots/metadata.db/*.ldb 2>/dev/null")
    if rc == 0 and out.strip():
        print("     [FAIL] GoLevelDB metadata.db still present")
        failures.append("metadata.db is GoLevelDB")
    else:
        print("     [OK] no GoLevelDB metadata")

    # cs.wal cleaned
    print("  -> cs.wal/")
    rc, out = ssh(server, f"du -sh {DATA_DIR}/cs.wal 2>/dev/null")
    if rc == 0:
        print(f"     [OK] {out.split()[0]} (freshly recreated)")
    else:
        print("     [OK] not yet created")

    # Artifacts
    print("  -> leftover artifacts")
    artifact_found = False
    for path, label in [
        (f"{DATA_DIR}/_pebble_convert_tmp*", "temp dirs"),
        ("/tmp/convert-db", "converter binary"),
    ]:
        rc, out = ssh(server, f"ls -d {path} 2>/dev/null")
        if rc == 0 and out.strip():
            print(f"     [FAIL] {label} still exists")
            failures.append(f"artifact: {label}")
            artifact_found = True
    for db in ALL_DBS:
        rc, _ = ssh(server, f"test -d {DATA_DIR}/{db}.db.bak")
        if rc == 0:
            print(f"     [FAIL] {db}.db.bak still exists")
            failures.append(f"artifact: {db}.db.bak")
            artifact_found = True
    if not artifact_found:
        print("     [OK] clean")

    # Node health
    print("  -> node health")
    height, catching_up = get_sync_info(server)
    if catching_up is False and height > 0:
        print(f"     [OK] synced at height {height}")
    elif catching_up is None:
        print("     [FAIL] RPC not available")
        failures.append("RPC unavailable")
    else:
        print(f"     [WARN] height={height} catching_up={catching_up}")
        failures.append(f"not synced: height={height}")

    # bond_denom
    print("  -> bond_denom")
    denom = get_bond_denom(server)
    if denom == "umirage":
        print("     [OK] umirage")
    elif not denom:
        print("     [WARN] cannot query (REST API may need more time)")
    else:
        print(f"     [FAIL] {denom!r}")
        failures.append(f"bond_denom={denom!r}")

    # FATAL errors
    print("  -> FATAL errors in today's log")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    logfile = f"$HOME/.mirage/logs/node/miraged-{today}.log"
    rc, out = ssh(server, f"grep -c FATAL {logfile} 2>/dev/null || echo 0")
    count = int(out.strip().splitlines()[-1]) if out.strip() else 0
    if count == 0:
        print("     [OK] none")
    else:
        _, fatals = ssh(server, f"grep FATAL {logfile} | tail -3")
        print(f"     [WARN] {count} FATAL error(s):")
        for line in fatals.strip().splitlines()[:3]:
            print(f"       {line.strip()[:120]}")
        failures.append(f"{count} FATAL error(s)")

    # Size comparison
    print("  -> file sizes (after)")
    after_sizes = snapshot_sizes(server)
    print_size_comparison(before_sizes, after_sizes)

    # Summary
    print()
    if failures:
        print(f"FAILED — {len(failures)} issue(s):")
        for f in failures:
            print(f"  - {f}")
        return 1

    print("PASSED — all databases migrated to PebbleDB. Node healthy, no artifacts.")
    return 0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate mirage node from GoLevelDB to PebbleDB")
    parser.add_argument("server", help="SSH target (e.g. root@64.23.136.132)")
    args = parser.parse_args()

    server = args.server

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\nPebbleDB Migration — {server} — {ts}\n")

    before_sizes = preflight(server)
    binary = build_converter()
    upload_converter(server, binary)
    stop_and_convert(server)
    switch_backend(server)
    start_and_wait(server)
    cleanup(server)
    return verify(server, before_sizes)


if __name__ == "__main__":
    raise SystemExit(main())
