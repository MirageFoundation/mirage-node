#!/usr/bin/env python3
"""Full backup and restore for Mirage validator nodes.

This script creates a complete backup from one server and can restore it to any server.
Use this for disaster recovery - backup from mirage.vote, restore to all 4 servers if needed.

Usage:
    # Download full backup from mirage.vote
    python3 scripts/backup_restore.py backup --source mirage.vote

    # Restore to a server (requires mnemonic for key re-derivation)
    python3 scripts/backup_restore.py restore --target mirage.vote --latest
    python3 scripts/backup_restore.py restore --target mirage.vote --file ~/.mirage/backups/mirage-backup-mirage-vote-20260123-120000.tgz

    # List available backups
    python3 scripts/backup_restore.py list

Backup naming:
    Backups include the source server in the filename:
    mirage-backup-{source-host}-{YYYYMMDD}-{HHMMSS}.tgz
    Example: mirage-backup-mirage-vote-20260123-143052.tgz

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
import getpass
import subprocess
import sys
from datetime import datetime
from pathlib import Path

BACKUP_DIR = Path.home() / ".mirage" / "backups"
SSH_USER = "root"


def status(msg: str):
    """Print a status message."""
    print(f"==> {msg}", flush=True)


def run(cmd: str, capture: bool = False) -> str:
    """Run a shell command. Fails immediately on non-zero exit."""
    result = subprocess.run(
        cmd,
        shell=True,
        check=True,  # Always fail on non-zero exit
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=None,  # Never suppress stderr
    )
    return result.stdout.strip() if capture else ""


def run_ssh(conn: str, script: str) -> str:
    """Run a script on remote via SSH stdin. Fails immediately on error."""
    result = subprocess.run(
        f"ssh {conn} 'bash -s'",
        shell=True,
        check=True,
        text=True,
        input=script,
        stdout=subprocess.PIPE,
        stderr=None,
    )
    return result.stdout.strip()


def validate_mnemonic(mnemonic: str) -> None:
    """Validate mnemonic is exactly 12 words. Exits on failure."""
    words = mnemonic.strip().split()
    if len(words) != 12:
        print(f"ERROR: Mnemonic must be exactly 12 words (got {len(words)}).", file=sys.stderr)
        sys.exit(1)


def find_latest_backup() -> Path:
    """Find the most recent backup file. Exits if none found."""
    if not BACKUP_DIR.exists():
        print(f"ERROR: Backups directory not found: {BACKUP_DIR}", file=sys.stderr)
        sys.exit(1)

    backups = sorted(
        BACKUP_DIR.glob("mirage-backup-*.tgz"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    if not backups:
        print(f"ERROR: No backups found in {BACKUP_DIR}", file=sys.stderr)
        sys.exit(1)

    return backups[0]


# =============================================================================
# BACKUP
# =============================================================================


def backup(source_host: str, ssh_user: str = SSH_USER) -> Path:
    """Create full backup from a remote server."""
    conn = f"{ssh_user}@{source_host}"
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    # Sanitize hostname for filename (replace dots with dashes)
    host_safe = source_host.replace(".", "-")
    backup_name = f"mirage-backup-{host_safe}-{timestamp}.tgz"
    remote_path = f"/tmp/{backup_name}"

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    local_path = BACKUP_DIR / backup_name

    status(f"Creating full backup from {source_host}")

    # Step 0: Ensure container is running (needed for pg_dump)
    status("Ensuring container is running...")
    run(f"ssh {conn} 'docker start mirage 2>/dev/null || true'")

    # Step 1: Stop application services (but keep container running for pg_dump)
    status("Stopping application services...")
    run_ssh(
        conn,
        """
        docker exec mirage tmux send-keys -t mirage:node C-c 2>/dev/null || true
        docker exec mirage tmux send-keys -t mirage:indexer C-c 2>/dev/null || true
        docker exec mirage tmux send-keys -t mirage:backend C-c 2>/dev/null || true
        docker exec mirage tmux send-keys -t mirage:orchestrator C-c 2>/dev/null || true
        sleep 3
        docker exec mirage pkill -9 -f miraged 2>/dev/null || true
        docker exec mirage pkill -9 -f gunicorn 2>/dev/null || true
        docker exec mirage pkill -9 -f orchestrator 2>/dev/null || true
        sleep 2
    """,
    )

    # Step 2: Dump PostgreSQL (services stopped, only postgres running)
    status("Dumping PostgreSQL database...")
    run_ssh(
        conn,
        """
        docker exec mirage bash -c '
            pg_ctlcluster 16 main start 2>/dev/null || true
            sleep 2
            PGPASSWORD=mirage pg_dump -h 127.0.0.1 -U mirage -d mirage > /root/.mirage/backup_indexer.sql
        '
    """,
    )

    # Step 3: Stop Docker container completely
    status("Stopping Docker container...")
    run(f"ssh {conn} 'docker stop mirage'")

    # Step 4: Create tarball on remote (excludes: tmp, logs, cs.wal, tx_index.db)
    status("Creating backup tarball on remote...")
    run_ssh(
        conn,
        f"""
        cd /root
        tar czf {remote_path} \\
            --exclude=".mirage/tmp" \\
            --exclude=".mirage/logs" \\
            --exclude=".mirage/*.tgz" \\
            --exclude=".mirage/node/data/cs.wal" \\
            --exclude=".mirage/node/data/tx_index.db" \\
            .mirage
    """,
    )

    # Step 5: Download backup to local
    status(f"Downloading backup to {local_path}...")
    run(f"scp {conn}:{remote_path} '{local_path}'")

    # Step 6: Start container again
    status("Starting container...")
    run(f"ssh {conn} 'docker start mirage'")

    # Step 7: Cleanup remote
    status("Cleaning up remote...")
    run(f"ssh {conn} 'rm -f {remote_path} /root/.mirage/backup_indexer.sql'")

    # Report size
    size_gb = local_path.stat().st_size / (1024**3)
    status(f"Backup complete: {local_path} ({size_gb:.2f} GB)")

    return local_path


# =============================================================================
# RESTORE
# =============================================================================


def restore(
    target_host: str, backup_file: Path, ssh_user: str = SSH_USER, force: bool = False, debug_skip: bool = False
):
    """Restore a backup to a remote server."""
    conn = f"{ssh_user}@{target_host}"

    # Validate backup file exists
    if not backup_file.exists():
        print(f"ERROR: Backup file not found: {backup_file}", file=sys.stderr)
        sys.exit(1)

    size_gb = backup_file.stat().st_size / (1024**3)
    status(f"Restoring {backup_file.name} ({size_gb:.2f} GB) to {target_host}")

    # -------------------------------------------------------------------------
    # Step 1: Warning and mnemonic prompt (fail fast before any uploads)
    # -------------------------------------------------------------------------
    if debug_skip:
        status("DEBUG MODE: Skipping mnemonic prompt")
        mnemonic = None
    else:
        print(f"\nWARNING: This will OVERWRITE all data on {target_host}!")
        print("         The node will be stopped and all existing state replaced.")
        print("         Validator keys will be re-derived from your mnemonic.")
        print("\nEnter your validator mnemonic to continue (Ctrl+C to abort).")
        mnemonic = getpass.getpass("12-word mnemonic: ")
        validate_mnemonic(mnemonic)
        status("Mnemonic validated (12 words)")

    # -------------------------------------------------------------------------
    # Step 2: Get Docker image name BEFORE stopping (needed for key derivation later)
    # -------------------------------------------------------------------------
    status("Getting Docker image name...")
    image = run(
        f"ssh -o StrictHostKeyChecking=accept-new {conn} \"docker inspect mirage --format '{{{{.Config.Image}}}}'\"",
        capture=True,
    )
    if not image:
        print("ERROR: Could not get Docker image name from container 'mirage'", file=sys.stderr)
        sys.exit(1)
    status(f"Will use image: {image}")

    if debug_skip:
        status("DEBUG MODE: Skipping steps 3-9")
    else:
        # -------------------------------------------------------------------------
        # Step 3: Stop container (disable restart policy first to prevent restart loop)
        # -------------------------------------------------------------------------
        status(f"Stopping container on {target_host}...")
        run(
            f"ssh {conn} 'docker update --restart=no mirage 2>/dev/null || true; docker stop mirage 2>/dev/null || true'"
        )

        # -------------------------------------------------------------------------
        # Step 4: Delete old data, prune docker (except needed image), clean up disk space
        # -------------------------------------------------------------------------
        status("Deleting old data and cleaning up disk space...")
        run_ssh(
            conn,
            f"""
            rm -rf /root/.mirage
            # Remove all docker images EXCEPT the one we need
            docker images -q | grep -v "$(docker images -q '{image}' 2>/dev/null)" | xargs -r docker rmi -f 2>/dev/null || true
            docker image prune -f >/dev/null 2>&1 || true
            journalctl --vacuum-size=100M >/dev/null 2>&1 || true
        """,
        )

        # Check available disk space
        avail_output = run(f'ssh {conn} "df / --output=avail | tail -1"', capture=True)
        avail_kb = int(avail_output.strip())
        avail_gb = avail_kb / (1024 * 1024)
        needed_gb = (size_gb * 2) + 1  # tarball + extracted + buffer
        if avail_gb < needed_gb:
            if force:
                status(
                    f"WARNING: Low disk space ({avail_gb:.1f}GB available, need ~{needed_gb:.1f}GB) - continuing anyway (--force)"
                )
            else:
                print(f"ERROR: Not enough disk space. Need ~{needed_gb:.1f}GB, have {avail_gb:.1f}GB", file=sys.stderr)
                print("       Use --force to skip this check", file=sys.stderr)
                sys.exit(1)
        else:
            status(f"Disk space OK: {avail_gb:.1f}GB available")

        # -------------------------------------------------------------------------
        # Step 5: Upload backup to /tmp/restore.tgz (skip if already exists with correct size)
        # -------------------------------------------------------------------------
        local_size = backup_file.stat().st_size
        remote_size_output = run(f"ssh {conn} 'stat -c %s /tmp/restore.tgz 2>/dev/null || echo 0'", capture=True)
        remote_size = int(remote_size_output.strip())

        if remote_size == local_size:
            status(f"Backup already on server ({size_gb:.2f} GB) - skipping upload")
        else:
            status("Uploading backup to server...")
            run(f"scp '{backup_file}' {conn}:/tmp/restore.tgz")

        # -------------------------------------------------------------------------
        # Step 6: Extract backup
        # -------------------------------------------------------------------------
        status("Extracting backup...")
        run(f"ssh {conn} 'cd /root && tar xzf /tmp/restore.tgz'")

        # -------------------------------------------------------------------------
        # Step 7: Delete node_key.json (will be regenerated) and remove self from persistent_peers
        # -------------------------------------------------------------------------
        status("Deleting node_key.json (will be regenerated with new P2P identity)...")
        run(f"ssh {conn} 'rm -f /root/.mirage/node/config/node_key.json'")

        status("Removing self from persistent_peers...")
        # Remove any entry matching *@<target_host>:26656
        run_ssh(
            conn,
            f"""
            CONFIG="/root/.mirage/node/config/config.toml"
            if [ -f "$CONFIG" ]; then
                sed -i 's/[^,]*@{target_host}:26656,//g' "$CONFIG"
                sed -i 's/,[^,]*@{target_host}:26656//g' "$CONFIG"
                sed -i 's/[^"]*@{target_host}:26656//g' "$CONFIG"
            fi
        """,
        )

        # -------------------------------------------------------------------------
        # Step 8: Delete identity files (priv_validator_key.json, keyring-*)
        # -------------------------------------------------------------------------
        status("Deleting old identity files...")
        run(f"ssh {conn} 'rm -f /root/.mirage/node/config/priv_validator_key.json'")
        run(f"ssh {conn} 'rm -rf /root/.mirage/node/keyring-*'")

        # -------------------------------------------------------------------------
        # Step 9: Derive consensus key (one-shot container)
        # -------------------------------------------------------------------------
        status("Deriving consensus key...")
        derive_cmd = f"""docker run --rm -i \\
            --entrypoint python3 \\
            -v ~/.mirage:/root/.mirage \\
            '{image}' /opt/mirage/deploy/derive_consensus_key.py"""

        result = subprocess.run(
            f"ssh {conn} '{derive_cmd}'",
            shell=True,
            check=True,
            text=True,
            input=mnemonic,
        )

    # -------------------------------------------------------------------------
    # Step 10: Restore PostgreSQL (temporary container, avoid full entrypoint)
    # -------------------------------------------------------------------------
    # Check if SQL file exists (skip if already restored in previous debug run)
    sql_exists = run(
        f"ssh {conn} 'test -f /root/.mirage/backup_indexer.sql && echo yes || echo no'", capture=True
    ).strip()
    if sql_exists != "yes":
        status("PostgreSQL already restored (no SQL file) - skipping")
    else:
        status("Restoring PostgreSQL database...")

        # Write the restore script to a temp file, copy to server, run in container
        pg_restore_script = r"""#!/bin/bash
set -e

PG_DATA_DIR="/root/.mirage/postgres"
PG_CONF="/etc/postgresql/16/main/postgresql.conf"

if [ ! -f "$PG_DATA_DIR/PG_VERSION" ]; then
    echo "ERROR: PostgreSQL data directory missing: $PG_DATA_DIR" >&2
    exit 1
fi

echo "DEBUG: Making /root traversable for postgres user"
chmod o+x /root /root/.mirage

echo "DEBUG: Ensuring postgres owns $PG_DATA_DIR"
chown -R postgres:postgres "$PG_DATA_DIR"
chmod 700 "$PG_DATA_DIR"

echo "DEBUG: Pointing postgres to $PG_DATA_DIR"
sed -i "s|^data_directory = .*|data_directory = '$PG_DATA_DIR'|" "$PG_CONF"

echo "Starting PostgreSQL..."
pg_ctlcluster 16 main start
sleep 3

if [ ! -f /root/.mirage/backup_indexer.sql ]; then
    echo "ERROR: /root/.mirage/backup_indexer.sql not found" >&2
    exit 1
fi

echo "Dropping and recreating database..."
su - postgres -c "psql -c 'DROP DATABASE IF EXISTS mirage'"
su - postgres -c "psql -c 'DROP ROLE IF EXISTS mirage'"
su - postgres -c "psql -c \"CREATE ROLE mirage WITH LOGIN PASSWORD 'mirage'\""
su - postgres -c "psql -c 'CREATE DATABASE mirage OWNER mirage'"

echo "Restoring SQL dump..."
su - postgres -c "psql -v ON_ERROR_STOP=1 -d mirage -f /root/.mirage/backup_indexer.sql"

echo "Cleaning up SQL dump..."
rm -f /root/.mirage/backup_indexer.sql

echo "Stopping PostgreSQL..."
pg_ctlcluster 16 main stop -m fast

echo "PostgreSQL restore complete"
"""

        # Copy script to server and run in container
        run_ssh(conn, f"cat > /tmp/pg_restore.sh << 'SCRIPT_EOF'\n{pg_restore_script}\nSCRIPT_EOF")
        run(
            f"ssh {conn} \"docker run --rm -v /root/.mirage:/root/.mirage -v /tmp/pg_restore.sh:/tmp/pg_restore.sh --entrypoint /bin/bash '{image}' /tmp/pg_restore.sh\""
        )

    # -------------------------------------------------------------------------
    # Step 11: Import validator key (recreate container with SKIP_VALIDATOR_CHECK=1)
    # -------------------------------------------------------------------------
    if mnemonic:
        status("Stopping and removing old container...")
        run(f"ssh {conn} 'docker rm -f mirage 2>/dev/null || true'")

        status("Starting temporary container (SKIP_VALIDATOR_CHECK=1)...")
        # Start container with skip flag so init.sh doesn't fail on missing key
        run_ssh(
            conn,
            f"""
            docker run -d --name mirage \\
                -e SKIP_VALIDATOR_CHECK=1 \\
                -v /root/.mirage:/root/.mirage \\
                -p 26656:26656 -p 26657:26657 -p 1317:1317 -p 9090:9090 -p 5000:5000 -p 80:80 -p 443:443 \\
                '{image}'
        """,
        )

        # Wait for container to be running
        status("Waiting for container to be ready...")
        import time

        for _ in range(60):
            result = run(f"ssh {conn} 'docker exec mirage echo ready 2>/dev/null || echo not_ready'", capture=True)
            if "ready" in result:
                break
            time.sleep(2)
        else:
            print("WARNING: Container may not be ready", file=sys.stderr)

        # Detect miraged path (old vs new image layout)
        miraged_path = run(
            f"ssh {conn} 'docker exec mirage sh -c \"test -x /opt/mirage/blockchain/bin/miraged && echo /opt/mirage/blockchain/bin/miraged || echo /opt/mirage/blockchain/miraged\"'",
            capture=True,
        ).strip()
        status(f"Using miraged at: {miraged_path}")

        status("Importing validator account key...")
        subprocess.run(
            f"ssh {conn} 'docker exec -i mirage {miraged_path} keys add validator --recover --home /root/.mirage/node --keyring-backend test'",
            shell=True,
            check=True,
            text=True,
            input=mnemonic,
        )
        # Clear mnemonic from memory
        mnemonic = None

        # Recreate container without SKIP_VALIDATOR_CHECK
        status("Recreating container (normal mode)...")
        run(f"ssh {conn} 'docker rm -f mirage'")
        run_ssh(
            conn,
            f"""
            docker run -d --name mirage --restart unless-stopped \\
                -v /root/.mirage:/root/.mirage \\
                -v /root/.caddy:/root/.local/share/caddy \\
                -p 26656:26656 -p 26657:26657 -p 1317:1317 -p 9090:9090 -p 5000:5000 -p 80:80 -p 443:443 \\
                '{image}'
        """,
        )
    else:
        status("DEBUG MODE: Skipping key import (no mnemonic)")
        # Just restart the existing container
        status("Restarting container...")
        run(f"ssh {conn} 'docker update --restart=unless-stopped mirage && docker restart mirage'")

    # -------------------------------------------------------------------------
    # Step 13: Wait for node to start
    # -------------------------------------------------------------------------
    status("Waiting for node to start (15s)...")
    import time

    for i in range(5):
        time.sleep(3)
        try:
            result = subprocess.run(
                f"ssh {conn} 'curl -sf http://127.0.0.1:26657/status'",
                shell=True,
                check=False,
                capture_output=True,
                text=True,
            )
            if result.returncode == 0 and "latest_block_height" in result.stdout:
                status("Node is running!")
                break
        except Exception:
            pass
    else:
        print("WARNING: Node not responding after 15s. Check manually.", file=sys.stderr)

    # -------------------------------------------------------------------------
    # Step 14: Verification
    # -------------------------------------------------------------------------
    status(f"Restore complete on {target_host}")
    print("\nVerification commands:")
    print(f"  # Check peers:")
    print(f"  ssh {conn} 'docker exec mirage curl -sf http://127.0.0.1:26657/net_info | jq .result.n_peers'")
    print(f"  # Check sync status:")
    print(f"  ssh {conn} 'docker exec mirage curl -sf http://127.0.0.1:26657/status | jq .result.sync_info'")
    print(f"  # Check backend health:")
    print(f"  ssh {conn} 'docker exec mirage curl -sf http://127.0.0.1:5000/health'")

    # -------------------------------------------------------------------------
    # Step 15: Prompt to delete backup from server
    # -------------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("Backup file is still on server at /tmp/restore.tgz")
    print("Test that everything works, then confirm deletion.")
    print("=" * 60)
    cleanup = input("\nType 'confirm' to delete /tmp/restore.tgz (or Ctrl+C to keep it): ")
    if cleanup.lower() == "confirm":
        run(f"ssh {conn} 'rm -f /tmp/restore.tgz'")
        status("Deleted /tmp/restore.tgz from server")
    else:
        print("Keeping /tmp/restore.tgz on server for potential re-runs.")


# =============================================================================
# LIST
# =============================================================================


def parse_backup_source(filename: str) -> str | None:
    """Extract source host from backup filename. Returns None for old-format backups."""
    # New format: mirage-backup-{host-with-dashes}-{YYYYMMDD}-{HHMMSS}.tgz
    # Old format: mirage-backup-{YYYYMMDD}-{HHMMSS}.tgz
    import re

    # Try new format first: mirage-backup-{host}-YYYYMMDD-HHMMSS.tgz
    # Host part is everything between "mirage-backup-" and the timestamp
    match = re.match(r"mirage-backup-(.+)-(\d{8})-(\d{6})\.tgz$", filename)
    if match:
        host_part = match.group(1)
        # Convert dashes back to dots for display
        return host_part.replace("-", ".")

    return None


def list_backups():
    """List all available backups."""
    if not BACKUP_DIR.exists():
        print(f"No backups directory found at {BACKUP_DIR}")
        return

    backups = sorted(
        BACKUP_DIR.glob("mirage-backup-*.tgz"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    if not backups:
        print("No backups found.")
        return

    print(f"Backups in {BACKUP_DIR}:\n")
    for b in backups:
        size_gb = b.stat().st_size / (1024**3)
        mtime = datetime.fromtimestamp(b.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        marker = " (latest)" if b == backups[0] else ""
        source = parse_backup_source(b.name)
        source_str = f"  [{source}]" if source else ""
        print(f"  {b.name}  {size_gb:.2f} GB  {mtime}{marker}{source_str}")


# =============================================================================
# MAIN
# =============================================================================


def main():
    parser = argparse.ArgumentParser(
        description="Full backup and restore for Mirage validator nodes.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Create backup from production
  %(prog)s backup --source mirage.vote

  # Restore using latest backup
  %(prog)s restore --target mirage.vote --latest

  # Restore using specific backup file
  %(prog)s restore --target mirage.vote --file ~/.mirage/backups/mirage-backup-mirage-vote-20260123-143052.tgz

  # List available backups
  %(prog)s list
""",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # Backup command
    backup_parser = subparsers.add_parser("backup", help="Create backup from a server")
    backup_parser.add_argument("--source", required=True, help="Source server hostname (e.g., mirage.vote)")
    backup_parser.add_argument("--user", default=SSH_USER, help=f"SSH user (default: {SSH_USER})")

    # Restore command
    restore_parser = subparsers.add_parser("restore", help="Restore backup to a server")
    restore_parser.add_argument("--target", required=True, help="Target server hostname")
    restore_parser.add_argument("--user", default=SSH_USER, help=f"SSH user (default: {SSH_USER})")
    restore_parser.add_argument("--force", action="store_true", help="Skip disk space check")
    restore_parser.add_argument("--debug-skip", action="store_true", help="Debug mode: skip steps 3-9 and mnemonic")

    # Mutually exclusive: --file or --latest
    backup_source = restore_parser.add_mutually_exclusive_group(required=True)
    backup_source.add_argument("--file", type=Path, help="Backup file to restore")
    backup_source.add_argument("--latest", action="store_true", help="Use latest backup from ~/.mirage/backups/")

    # List command
    subparsers.add_parser("list", help="List available backups")

    args = parser.parse_args()

    if args.command == "backup":
        backup(args.source, args.user)
    elif args.command == "restore":
        # Determine backup file
        if args.latest:
            backup_file = find_latest_backup()
            status(f"Using latest backup: {backup_file.name}")
        else:
            backup_file = args.file

        restore(args.target, backup_file, args.user, args.force, args.debug_skip)
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
