#!/usr/bin/env python3
"""Full backup and restore for Mirage validator nodes.

This script creates a complete backup from one server and can restore it to any server.
Use this for disaster recovery - backup from mirage.vote, restore to all 4 servers if needed.

Usage:
    # Download full backup from mirage.vote
    python3 scripts/backup_restore.py backup --source mirage.vote

    # Restore to a server (can be same or different)
    python3 scripts/backup_restore.py restore --target mirage.vote
    python3 scripts/backup_restore.py restore --target mirage.talk
    python3 scripts/backup_restore.py restore --target validator3.example.com

    # List available backups
    python3 scripts/backup_restore.py list

What gets backed up:
    - ~/.mirage/node/data/       - Full blockchain data and state
    - ~/.mirage/node/config/     - Node configuration, genesis, validator keys
    - ~/.mirage/node/keyring-*   - Keyring (validator signing keys)
    - ~/.mirage/postgres/        - PostgreSQL data directory
    - ~/.mirage/env/             - Environment files
    - ~/.mirage/orchestrator/    - Orchestrator files (Solana keypair)
    - PostgreSQL dump            - Clean SQL dump for easy restore

WARNING: Backups are large (~5-10GB) and contain sensitive keys!
"""

import argparse
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

BACKUP_DIR = Path.home() / ".mirage" / "backups"
SSH_USER = "root"


def status(msg: str):
    print(f"==> {msg}", flush=True)


def run(cmd: str, check: bool = True, capture: bool = False) -> str:
    """Run a shell command."""
    result = subprocess.run(
        cmd,
        shell=True,
        check=check,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )
    return result.stdout.strip() if capture else ""


def backup(source_host: str, ssh_user: str = SSH_USER) -> Path:
    """Create full backup from a remote server."""
    conn = f"{ssh_user}@{source_host}"
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_name = f"mirage-backup-{timestamp}.tgz"
    
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    local_path = BACKUP_DIR / backup_name
    
    status(f"Creating full backup from {source_host}")
    
    # Step 1: Stop application services (but keep container running for pg_dump)
    status("Stopping application services...")
    run(f"ssh -o StrictHostKeyChecking=accept-new {conn} '"
        "docker exec mirage tmux send-keys -t mirage:node C-c 2>/dev/null || true; "
        "docker exec mirage tmux send-keys -t mirage:indexer C-c 2>/dev/null || true; "
        "docker exec mirage tmux send-keys -t mirage:backend C-c 2>/dev/null || true; "
        "docker exec mirage tmux send-keys -t mirage:orchestrator C-c 2>/dev/null || true; "
        "sleep 3; "
        "docker exec mirage pkill -9 -f miraged 2>/dev/null || true; "
        "docker exec mirage pkill -9 -f gunicorn 2>/dev/null || true; "
        "docker exec mirage pkill -9 -f orchestrator 2>/dev/null || true; "
        "sleep 2'")
    
    # Step 2: Dump PostgreSQL (services stopped, only postgres running)
    status("Dumping PostgreSQL database...")
    run(f"ssh {conn} '"
        "docker exec mirage bash -c \""
        "pg_ctlcluster 16 main start 2>/dev/null || true; "
        "sleep 2; "
        "PGPASSWORD=mirage pg_dump -h 127.0.0.1 -U mirage -d mirage > /root/.mirage/backup_indexer.sql"
        "\" 2>/dev/null || true'")
    
    # Step 3: Stop Docker container completely
    status("Stopping Docker container...")
    run(f"ssh {conn} 'docker stop mirage && sleep 2'")
    
    # Step 3: Stream tarball directly to local (no temp file on server - saves disk space)
    # Note: Some directories (orchestrator/) may not exist on pre-1.9.0 servers - that's fine
    # Excludes: tmp, logs, cs.wal (consensus WAL - regenerates on start)
    status("Calculating backup size...")
    size_output = run(f"ssh {conn} '"
        "cd /root && "
        "du -sb .mirage "
        "--exclude=\".mirage/tmp\" "
        "--exclude=\".mirage/logs\" "
        "--exclude=\".mirage/*.tgz\" "
        "--exclude=\".mirage/node/data/cs.wal\" "
        "--exclude=\".mirage/node/data/tx_index.db\" "
        "2>/dev/null | cut -f1"
        "'", capture=True)
    try:
        total_bytes = int(size_output.strip())
        size_str = f"{total_bytes / (1024**3):.1f} GB"
    except ValueError:
        total_bytes = 0
        size_str = "unknown size"
    
    status(f"Streaming backup to {local_path} ({size_str}, compressed)...")
    # Check if pv is available for progress display
    pv_available = subprocess.run("which pv", shell=True, capture_output=True).returncode == 0
    
    if total_bytes > 0 and pv_available:
        run(f"ssh {conn} '"
            "cd /root && "
            "tar cf - "
            "--exclude=\".mirage/tmp\" "
            "--exclude=\".mirage/logs\" "
            "--exclude=\".mirage/*.tgz\" "
            "--exclude=\".mirage/node/data/cs.wal\" "
            "--exclude=\".mirage/node/data/tx_index.db\" "
            ".mirage"
            f"' | pv -s {total_bytes} -p -e -r | gzip > '{local_path}'"
        )
    else:
        if not pv_available:
            print("    (install 'pv' for progress display: sudo pacman -S pv)")
        run(f"ssh {conn} '"
            "cd /root && "
            "tar czf - "
            "--exclude=\".mirage/tmp\" "
            "--exclude=\".mirage/logs\" "
            "--exclude=\".mirage/*.tgz\" "
            "--exclude=\".mirage/node/data/cs.wal\" "
            "--exclude=\".mirage/node/data/tx_index.db\" "
            ".mirage"
            f"' > '{local_path}'")
    
    # Step 4: Start container again
    status("Starting container...")
    run(f"ssh {conn} 'docker start mirage'")
    
    # Step 5: Cleanup remote (just the SQL dump)
    status("Cleaning up remote...")
    run(f"ssh {conn} 'rm -f /root/.mirage/backup_indexer.sql'")
    
    # Get file size
    size_bytes = local_path.stat().st_size
    size_gb = size_bytes / (1024 ** 3)
    
    status(f"Backup complete: {local_path} ({size_gb:.2f} GB)")
    return local_path


def restore(target_host: str, backup_file: Path | None = None, ssh_user: str = SSH_USER):
    """Restore a backup to a remote server."""
    conn = f"{ssh_user}@{target_host}"
    
    # Find backup file
    if backup_file is None:
        backup_file = find_latest_backup()
        if backup_file is None:
            print("ERROR: No backup file specified and no backups found.", file=sys.stderr)
            print(f"       Run 'backup' first or specify --file", file=sys.stderr)
            sys.exit(1)
    
    if not backup_file.exists():
        print(f"ERROR: Backup file not found: {backup_file}", file=sys.stderr)
        sys.exit(1)
    
    size_gb = backup_file.stat().st_size / (1024 ** 3)
    status(f"Restoring {backup_file.name} ({size_gb:.2f} GB) to {target_host}")
    
    # Confirm
    print(f"\nWARNING: This will OVERWRITE all data on {target_host}!")
    print("         The node will be stopped and all existing state replaced.")
    confirm = input("\nType 'yes' to continue: ")
    if confirm.lower() != "yes":
        print("Aborted.")
        sys.exit(0)
    
    # Step 1: Stop container on target
    status(f"Stopping container on {target_host}...")
    run(f"ssh -o StrictHostKeyChecking=accept-new {conn} '"
        "docker stop mirage 2>/dev/null || true; "
        "docker kill mirage 2>/dev/null || true; "
        "sleep 3'")
    
    # Step 2: DELETE old data first to free disk space
    status("Deleting old data to free disk space...")
    run(f"ssh {conn} '"
        "rm -rf /root/.mirage/node/data 2>/dev/null || true; "
        "rm -rf /root/.mirage/postgres 2>/dev/null || true; "
        "rm -rf /root/.mirage 2>/dev/null || true; "
        "rm -f /tmp/restore.tgz 2>/dev/null || true; "
        "find /tmp -maxdepth 1 -type f -delete 2>/dev/null || true; "
        "mkdir -p /root/.mirage'")
    
    # Step 3: Stream backup directly to tar (no temp file on target - saves disk space)
    status("Streaming and extracting backup (this may take a while)...")
    run(f"cat '{backup_file}' | ssh {conn} 'cd /root && tar xzf -'")
    
    # Step 4: Restore PostgreSQL
    status("Restoring PostgreSQL database...")
    run(f"ssh {conn} '"
        "docker start mirage; "
        "sleep 10; "  # Wait for container to start
        "docker exec mirage bash -c \""
        "pg_ctlcluster 16 main start 2>/dev/null || true; "
        "sleep 3; "
        "if [ -f /root/.mirage/backup_indexer.sql ]; then "
        "  su - postgres -c \\\"psql -c 'DROP DATABASE IF EXISTS mirage'\\\"; "
        "  su - postgres -c \\\"psql -c 'DROP ROLE IF EXISTS mirage'\\\"; "
        "  su - postgres -c \\\"psql -c \\\\\\\"CREATE ROLE mirage WITH LOGIN PASSWORD 'mirage'\\\\\\\"\\\"; "
        "  su - postgres -c \\\"psql -c 'CREATE DATABASE mirage OWNER mirage'\\\"; "
        "  su - postgres -c \\\"psql -d mirage -f /root/.mirage/backup_indexer.sql\\\"; "
        "  rm -f /root/.mirage/backup_indexer.sql; "
        "fi"
        "\"'", check=False)
    
    # Step 5: Restart container
    status("Restarting container...")
    run(f"ssh {conn} 'docker restart mirage'")
    
    # Step 6: Wait for services
    status("Waiting for node to start...")
    for i in range(60):
        try:
            result = run(f"ssh {conn} 'curl -sf http://127.0.0.1:26657/status 2>/dev/null'", 
                        check=False, capture=True)
            if "latest_block_height" in result:
                status("Node is running!")
                break
        except Exception:
            pass
        time.sleep(2)
    else:
        status("WARNING: Node may not be running. Check manually.")
    
    # Cleanup old backup
    run(f"ssh {conn} 'rm -rf /root/.mirage.old 2>/dev/null || true'", check=False)
    
    status(f"Restore complete on {target_host}")
    print("\nNext steps:")
    print("  1. Verify node is syncing: ssh {conn} 'docker exec mirage curl -s http://127.0.0.1:26657/status | jq .result.sync_info'")
    print("  2. Check validator status: ssh {conn} 'docker exec mirage miraged q staking validators --home /root/.mirage/node'")
    print("  3. Monitor logs: ssh {conn} 'docker exec mirage tmux attach -t mirage'")


def find_latest_backup() -> Path | None:
    """Find the most recent backup file."""
    if not BACKUP_DIR.exists():
        return None
    backups = sorted(BACKUP_DIR.glob("mirage-backup-*.tgz"), 
                     key=lambda p: p.stat().st_mtime, reverse=True)
    return backups[0] if backups else None


def list_backups():
    """List all available backups."""
    if not BACKUP_DIR.exists():
        print(f"No backups directory found at {BACKUP_DIR}")
        return
    
    backups = sorted(BACKUP_DIR.glob("mirage-backup-*.tgz"), 
                     key=lambda p: p.stat().st_mtime, reverse=True)
    
    if not backups:
        print("No backups found.")
        return
    
    print(f"Backups in {BACKUP_DIR}:\n")
    for b in backups:
        size_gb = b.stat().st_size / (1024 ** 3)
        mtime = datetime.fromtimestamp(b.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        marker = " (latest)" if b == backups[0] else ""
        print(f"  {b.name}  {size_gb:.2f} GB  {mtime}{marker}")


def main():
    parser = argparse.ArgumentParser(
        description="Full backup and restore for Mirage validator nodes.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Create backup from production
  %(prog)s backup --source mirage.vote

  # Restore to same server
  %(prog)s restore --target mirage.vote

  # Restore to different server (disaster recovery)
  %(prog)s restore --target mirage.talk

  # Restore specific backup
  %(prog)s restore --target mirage.talk --file ~/.mirage/backups/mirage-backup-20260121.tgz

  # List available backups
  %(prog)s list
"""
    )
    
    subparsers = parser.add_subparsers(dest="command", required=True)
    
    # Backup command
    backup_parser = subparsers.add_parser("backup", help="Create backup from a server")
    backup_parser.add_argument("--source", required=True, help="Source server hostname (e.g., mirage.vote)")
    backup_parser.add_argument("--user", default=SSH_USER, help=f"SSH user (default: {SSH_USER})")
    
    # Restore command
    restore_parser = subparsers.add_parser("restore", help="Restore backup to a server")
    restore_parser.add_argument("--target", required=True, help="Target server hostname")
    restore_parser.add_argument("--file", type=Path, help="Backup file (default: latest)")
    restore_parser.add_argument("--user", default=SSH_USER, help=f"SSH user (default: {SSH_USER})")
    
    # List command
    subparsers.add_parser("list", help="List available backups")
    
    args = parser.parse_args()
    
    if args.command == "backup":
        backup(args.source, args.user)
    elif args.command == "restore":
        restore(args.target, args.file, args.user)
    elif args.command == "list":
        list_backups()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nAborted.")
        sys.exit(130)
    except subprocess.CalledProcessError as e:
        print(f"ERROR: Command failed: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
