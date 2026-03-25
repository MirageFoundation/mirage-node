#!/usr/bin/env python3
"""Full backup and restore for Mirage validator nodes.

This script creates a complete backup from one server and can restore it to any server.
Use this for disaster recovery - backup from mirage.vote, restore to all 4 servers if needed.

Usage:
    # Download full backup from mirage.vote
    python3 scripts/backup_restore.py backup --source mirage.vote

    # Backup all 4 production servers
    python3 scripts/backup_restore.py backup --all

    # Restore to same server (uses keys from backup - no mnemonic needed)
    python3 scripts/backup_restore.py restore --target mirage.vote --latest
    python3 scripts/backup_restore.py restore --target mirage.vote --file ~/.mirage/backups/mirage.vote/mirage.vote-20260123-120000.tgz

    # Restore to DIFFERENT server using another server's backup data (requires mnemonic)
    python3 scripts/backup_restore.py restore --target 139.59.9.96 --file ~/.mirage/backups/mirage.vote/mirage.vote-20260123-120000.tgz --migrate

    # List available backups
    python3 scripts/backup_restore.py list

Backup storage:
    Backups are organized by source server in folders:
    ~/.mirage/backups/{server}/{server}-{YYYYMMDD}-{HHMMSS}.tgz

    Example:
    ~/.mirage/backups/mirage.vote/mirage.vote-20260123-143052.tgz
    ~/.mirage/backups/139.59.9.96/139.59.9.96-20260123-144530.tgz

What gets backed up:
    - ~/.mirage/node/data/       - Full blockchain data and state
    - ~/.mirage/node/config/     - Node configuration, genesis, validator keys (priv_validator_key.json)
    - ~/.mirage/node/keyring-*   - Keyring (validator account key)
    - ~/.mirage/postgres/        - PostgreSQL data directory
    - ~/.mirage/env/             - Environment files
    - ~/.mirage/orchestrator/    - Orchestrator files (Solana keypair)
    - PostgreSQL dump            - Clean SQL dump for easy restore

Restore modes:
    Default (no --migrate):
        Restores everything from backup including identity files.
        Use when restoring the SAME server from its own backup.
        No mnemonic needed - keys come from backup.
        --latest finds the most recent backup in ~/.mirage/backups/{target}/

    --migrate:
        Use when restoring a DIFFERENT server using another server's backup data.
        The backup's identity files (priv_validator_key.json, keyring) are deleted
        and new ones are derived from your mnemonic.
        You'll still need to manually set up the orchestrator afterward.
        Must use --file to specify which server's backup to use.

WARNING: Backups are large (~5-10GB) and contain sensitive keys!
"""

import argparse
import getpass
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

BACKUP_DIR = Path.home() / ".mirage" / "backups"
SSH_USER = "root"

# All production servers (same as deploy_all_prod.sh)
ALL_SERVERS = [
    "mirage.vote",
    "146.190.108.140",
    "139.59.9.96",
    "mirage.talk",
]


def status(msg: str):
    """Print a status message."""
    print(f"==> {msg}", flush=True)


def verify_server_health(host: str, ssh_user: str = SSH_USER, timeout: int = 120) -> None:
    """Verify a server is fully healthy after backup.

    Curls the real endpoints directly (no SSH) to test end-to-end connectivity.

    Checks:
    - RPC is responding
    - Node has peers
    - Node is not stuck (block height increasing)

    Raises exception if health check fails.
    """
    start_time = time.time()

    rpc_status_url = f"http://{host}/chain/rpc/status"
    rpc_net_info_url = f"http://{host}/chain/rpc/net_info"

    # Wait for RPC to be available (max 60s)
    status(f"  Waiting for RPC on {host} ({rpc_status_url})...")
    rpc_ready = False
    for _ in range(20):
        try:
            result = subprocess.run(
                ["curl", "-sfL", rpc_status_url],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0 and "latest_block_height" in result.stdout:
                rpc_ready = True
                break
        except Exception:
            pass
        time.sleep(3)

    if not rpc_ready:
        raise RuntimeError(f"RPC not responding on {host} after 60s")
    status(f"  RPC is responding on {host}")

    # Check node has peers
    try:
        result = subprocess.run(
            ["curl", "-sfL", rpc_net_info_url],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        net_info = json.loads(result.stdout)
        n_peers = int(net_info.get("result", {}).get("n_peers", 0))
        if n_peers < 1:
            status(f"  WARNING: {host} has {n_peers} peers (may take time to connect)")
        else:
            status(f"  {host} has {n_peers} peer(s)")
    except Exception as e:
        status(f"  WARNING: Could not check peers on {host}: {e}")

    # Check block height is increasing (node not stuck)
    try:
        result1 = subprocess.run(
            ["curl", "-sfL", rpc_status_url],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        status1 = json.loads(result1.stdout)
        height1 = int(status1.get("result", {}).get("sync_info", {}).get("latest_block_height", 0))

        time.sleep(6)  # Wait for at least 1 block

        result2 = subprocess.run(
            ["curl", "-sfL", rpc_status_url],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        status2 = json.loads(result2.stdout)
        height2 = int(status2.get("result", {}).get("sync_info", {}).get("latest_block_height", 0))

        if height2 > height1:
            status(f"  Node is progressing: {height1} -> {height2}")
        else:
            status(f"  WARNING: Block height not increasing on {host} ({height1} -> {height2})")
    except Exception as e:
        status(f"  WARNING: Could not verify block progression on {host}: {e}")

    elapsed = time.time() - start_time
    status(f"  Health check complete for {host} ({elapsed:.0f}s)")


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


def find_latest_backup(target_host: str) -> Path:
    """Find the most recent backup file for a specific server.

    Args:
        target_host: Server hostname - looks in BACKUP_DIR/{target_host}/

    Exits if none found.
    """
    server_dir = BACKUP_DIR / target_host

    if not server_dir.exists():
        print(f"ERROR: No backup folder for '{target_host}'", file=sys.stderr)
        print(f"       Expected: {server_dir}", file=sys.stderr)
        # Show available servers
        if BACKUP_DIR.exists():
            servers = [d.name for d in BACKUP_DIR.iterdir() if d.is_dir()]
            if servers:
                print(f"       Available servers: {', '.join(servers)}", file=sys.stderr)
        sys.exit(1)

    backups = sorted(
        server_dir.glob("*.tgz"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    if not backups:
        print(f"ERROR: No backups found in {server_dir}", file=sys.stderr)
        sys.exit(1)

    return backups[0]


# =============================================================================
# BACKUP
# =============================================================================


def backup(source_host: str, ssh_user: str = SSH_USER) -> Path:
    """Create full backup from a remote server.

    Streams tar directly to local machine to avoid needing disk space on remote.
    Saves to BACKUP_DIR/{source_host}/{source_host}-{timestamp}.tgz
    """
    conn = f"{ssh_user}@{source_host}"
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_name = f"{source_host}-{timestamp}.tgz"

    # Create server-specific backup folder
    server_dir = BACKUP_DIR / source_host
    server_dir.mkdir(parents=True, exist_ok=True)
    local_path = server_dir / backup_name

    status(f"Creating full backup from {source_host}")

    # Step 0: Clean up /tmp on remote (old backups, restore files)
    status("Cleaning up /tmp on remote...")
    run(f"ssh {conn} 'rm -f /tmp/mirage-backup-*.tgz /tmp/restore.tgz /tmp/pg_restore.sh /tmp/node_key.json'")

    # Step 0.5: Ensure container is running (needed for pg_dump and image name)
    status("Ensuring container is running...")
    run(f"ssh {conn} 'docker start mirage 2>/dev/null || true'")

    # Step 0.6: Save Docker image name to metadata file (needed for restore)
    status("Saving Docker image name...")
    image = run(
        f"ssh {conn} \"docker inspect mirage --format '{{{{.Config.Image}}}}'\"",
        capture=True,
    )
    run(f"ssh {conn} 'echo \"{image}\" > ~/.mirage/docker_image'")

    # Step 1: Stop application services (but keep container running for pg_dump)
    # SIGTERM first so PebbleDB flushes WAL/manifest cleanly, then SIGKILL stragglers.
    status("Stopping application services...")
    run_ssh(
        conn,
        """
        docker exec mirage tmux send-keys -t mirage:node C-c 2>/dev/null || true
        docker exec mirage tmux send-keys -t mirage:indexer C-c 2>/dev/null || true
        docker exec mirage tmux send-keys -t mirage:backend C-c 2>/dev/null || true
        docker exec mirage tmux send-keys -t mirage:orchestrator C-c 2>/dev/null || true
        sleep 5
        docker exec mirage pkill -f miraged 2>/dev/null || true
        docker exec mirage pkill -f gunicorn 2>/dev/null || true
        docker exec mirage pkill -f orchestrator 2>/dev/null || true
        sleep 5
        docker exec mirage pkill -9 -f miraged 2>/dev/null || true
        docker exec mirage pkill -9 -f gunicorn 2>/dev/null || true
        docker exec mirage pkill -9 -f orchestrator 2>/dev/null || true
        sleep 2
    """,
    )

    # Step 2: Dump PostgreSQL databases (services stopped, only postgres running)
    status("Dumping PostgreSQL databases (indexer + backend)...")
    run_ssh(
        conn,
        """
        docker exec mirage bash -c '
            pg_ctlcluster 16 main start 2>/dev/null || true
            sleep 2
            PGPASSWORD=mirage pg_dump -h 127.0.0.1 -U mirage -d mirage_indexer > /root/.mirage/backup_indexer.sql
            PGPASSWORD=mirage pg_dump -h 127.0.0.1 -U mirage -d mirage_backend > /root/.mirage/backup_backend.sql 2>/dev/null || true
        '
    """,
    )

    # Step 3: Stop Docker container completely
    status("Stopping Docker container...")
    run(f"ssh {conn} 'docker stop mirage'")

    # Step 4: Stream tarball directly to local (avoids needing remote disk space)
    # Get estimated size for progress bar (uncompressed, so actual will be smaller)
    status("Calculating backup size...")
    size_output = run(
        f"ssh {conn} 'du -sb ~/.mirage "
        '--exclude=".mirage/tmp" '
        '--exclude=".mirage/logs" '
        '--exclude=".mirage/*.tgz" '
        '--exclude=".mirage/node/data/cs.wal" '
        '--exclude=".mirage/node/data/tx_index.db" '
        "2>/dev/null | cut -f1'",
        capture=True,
    )
    uncompressed_bytes = int(size_output.strip()) if size_output.strip() else 0
    # Estimate compressed size (~60% of uncompressed for gzip on database files)
    estimated_bytes = int(uncompressed_bytes * 0.6)
    estimated_gb = estimated_bytes / (1024**3)
    status(f"Streaming backup to {local_path} (~{estimated_gb:.1f} GB compressed)...")

    # Stream: remote tar | gzip | pv (local progress) | local file
    tar_cmd = (
        "cd /root && tar cf - "
        '--exclude=".mirage/tmp" '
        '--exclude=".mirage/logs" '
        '--exclude=".mirage/*.tgz" '
        '--exclude=".mirage/node/data/cs.wal" '
        '--exclude=".mirage/node/data/tx_index.db" '
        ".mirage | gzip"
    )
    with open(local_path, "wb") as f:
        # ssh -> pv (progress) -> file
        ssh_proc = subprocess.Popen(
            ["ssh", conn, tar_cmd],
            stdout=subprocess.PIPE,
            stderr=None,
        )
        pv_proc = subprocess.Popen(
            ["pv", "-s", str(estimated_bytes), "-N", "Downloading"],
            stdin=ssh_proc.stdout,
            stdout=f,
            stderr=None,
        )
        ssh_proc.stdout.close()  # Allow ssh_proc to receive SIGPIPE if pv exits
        pv_proc.wait()
        ssh_ret = ssh_proc.wait()
        if ssh_ret != 0:
            raise subprocess.CalledProcessError(ssh_ret, "ssh")

    # Step 5: Start container again
    status("Starting container...")
    run(f"ssh {conn} 'docker start mirage'")

    # Step 6: Cleanup remote (SQL dumps, no tarball to clean)
    status("Cleaning up remote...")
    run(f"ssh {conn} 'rm -f /root/.mirage/backup_indexer.sql /root/.mirage/backup_backend.sql'")

    # Report size
    size_gb = local_path.stat().st_size / (1024**3)
    status(f"Backup complete: {local_path} ({size_gb:.2f} GB)")

    return local_path


# =============================================================================
# RESTORE
# =============================================================================


def restore(
    target_host: str,
    backup_file: Path,
    ssh_user: str = SSH_USER,
    force: bool = False,
    debug_skip: bool = False,
    migrate: bool = False,
    image_override: str | None = None,
):
    """Restore a backup to a remote server.

    Args:
        target_host: Server hostname to restore to
        backup_file: Path to backup .tgz file
        ssh_user: SSH username
        force: Skip disk space check
        debug_skip: Debug mode - skip steps 3-9 and mnemonic
        migrate: If True, this is a cross-server restore (delete identity files, require mnemonic)
        image_override: Docker image to use (overrides auto-detection)
    """
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
    mnemonic = None

    if debug_skip:
        status("DEBUG MODE: Skipping mnemonic prompt")
    elif migrate:
        # Cross-server restore: need mnemonic to derive new identity
        print(f"\nWARNING: --migrate mode: This will OVERWRITE all data on {target_host}!")
        print("         The backup's identity files will be DELETED and new keys")
        print("         will be derived from your mnemonic.")
        print("\n         Use this when restoring a DIFFERENT server using another")
        print("         server's backup data.")
        print("\nEnter your validator mnemonic to continue (Ctrl+C to abort).")
        mnemonic = getpass.getpass("12-word mnemonic: ")
        validate_mnemonic(mnemonic)
        status("Mnemonic validated (12 words)")
    else:
        # Same-server restore: use keys from backup
        print(f"\nWARNING: This will OVERWRITE all data on {target_host}!")
        print("         The node will be stopped and all existing state replaced.")
        print("         Identity files (priv_validator_key.json, keyring) will be")
        print("         restored from the backup.")
        print("\n         If you're restoring to a DIFFERENT server, use --migrate instead.")
        confirm = input("\nType 'confirm' to proceed (Ctrl+C to abort): ")
        if confirm.lower() != "confirm":
            print("Aborted.")
            sys.exit(0)

    # -------------------------------------------------------------------------
    # Step 2: Try to get Docker image name from existing container (may not exist)
    # -------------------------------------------------------------------------
    image = image_override
    if not image:
        status("Checking for existing container...")
        try:
            image = run(
                f"ssh -o StrictHostKeyChecking=accept-new {conn} \"docker inspect mirage --format '{{{{.Config.Image}}}}'\"",
                capture=True,
            )
            if image:
                status(f"Found existing image: {image}")
        except subprocess.CalledProcessError:
            status("No existing container found (will read image from backup)")

    if debug_skip:
        status("DEBUG MODE: Skipping steps 3-9")
    else:
        # -------------------------------------------------------------------------
        # Step 3: Stop and remove container
        # -------------------------------------------------------------------------
        status(f"Stopping and removing container on {target_host}...")
        run(
            f"ssh {conn} 'docker update --restart=no mirage 2>/dev/null || true; docker stop mirage 2>/dev/null || true; docker rm -f mirage 2>/dev/null || true'"
        )

        # -------------------------------------------------------------------------
        # Step 4: Delete old data, clean up disk space
        # -------------------------------------------------------------------------
        status("Deleting old data and cleaning up disk space...")
        run_ssh(
            conn,
            """
            rm -rf /root/.mirage
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
            status(f"Uploading backup to server ({size_gb:.2f} GB)...")
            # Use pv for progress: pv file | ssh cat > remote
            with open(backup_file, "rb") as f:
                pv_proc = subprocess.Popen(
                    ["pv", "-s", str(local_size), "-N", "Uploading"],
                    stdin=f,
                    stdout=subprocess.PIPE,
                    stderr=None,
                )
                ssh_proc = subprocess.Popen(
                    ["ssh", conn, "cat > /tmp/restore.tgz"],
                    stdin=pv_proc.stdout,
                    stdout=None,
                    stderr=None,
                )
                pv_proc.stdout.close()
                ssh_ret = ssh_proc.wait()
                pv_proc.wait()
                if ssh_ret != 0:
                    raise subprocess.CalledProcessError(ssh_ret, "ssh")

        # -------------------------------------------------------------------------
        # Step 6: Extract backup
        # -------------------------------------------------------------------------
        status("Extracting backup (this may take a few minutes)...")
        run(f"ssh {conn} 'cd /root && tar xzf /tmp/restore.tgz'")

        # -------------------------------------------------------------------------
        # Step 6.5: Get Docker image from backup metadata (if not already known)
        # -------------------------------------------------------------------------
        if not image:
            status("Reading Docker image from backup metadata...")
            image = run(
                f"ssh {conn} 'cat /root/.mirage/docker_image 2>/dev/null || echo \"\"'",
                capture=True,
            ).strip()
            if image:
                status(f"Using image from backup: {image}")
            else:
                print("ERROR: No Docker image found. Use --image to specify.", file=sys.stderr)
                print("       Example: --image mirage:dev-20260115", file=sys.stderr)
                sys.exit(1)

        if migrate:
            # -------------------------------------------------------------------------
            # Step 7: Delete identity files for --migrate (cross-server restore)
            # node_key.json = P2P identity, priv_validator_key.json = validator identity
            # -------------------------------------------------------------------------
            status("Deleting identity files from backup (--migrate mode)...")
            run(f"ssh {conn} 'rm -f /root/.mirage/node/config/node_key.json'")
            run(f"ssh {conn} 'rm -f /root/.mirage/node/config/priv_validator_key.json'")
            run(f"ssh {conn} 'rm -rf /root/.mirage/node/keyring-*'")

            # Remove target host from persistent_peers (backup may have it as a peer)
            status("Removing self from persistent_peers...")
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
            # Step 8: Derive consensus key (one-shot container)
            # -------------------------------------------------------------------------
            status("Deriving consensus key from mnemonic...")
            derive_cmd = f"""docker run --rm -i \\
                --entrypoint python3 \\
                -v ~/.mirage:/root/.mirage \\
                '{image}' /opt/mirage/deploy/derive_consensus_key.py"""

            subprocess.run(
                f"ssh {conn} '{derive_cmd}'",
                shell=True,
                check=True,
                text=True,
                input=mnemonic,
            )
        else:
            status("Keeping all identity files from backup (same-server restore)")

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

echo "Dropping and recreating databases..."
su - postgres -c "psql -c 'DROP DATABASE IF EXISTS mirage_indexer'"
su - postgres -c "psql -c 'DROP DATABASE IF EXISTS mirage_backend'"
su - postgres -c "psql -c 'DROP ROLE IF EXISTS mirage_indexer_ro'"
su - postgres -c "psql -c 'DROP ROLE IF EXISTS mirage_indexer'"
su - postgres -c "psql -c 'DROP ROLE IF EXISTS mirage_backend'"
su - postgres -c "psql -c 'DROP ROLE IF EXISTS mirage_ro'"
su - postgres -c "psql -c 'DROP ROLE IF EXISTS mirage'"
su - postgres -c "psql -c \"CREATE ROLE mirage_indexer WITH LOGIN PASSWORD 'mirage_indexer'\""
su - postgres -c "psql -c \"CREATE ROLE mirage_indexer_ro WITH LOGIN PASSWORD 'mirage_indexer_ro'\""
su - postgres -c "psql -c \"CREATE ROLE mirage_backend WITH LOGIN PASSWORD 'mirage_backend'\""
su - postgres -c "psql -c 'CREATE DATABASE mirage_indexer OWNER mirage_indexer'"
su - postgres -c "psql -c 'CREATE DATABASE mirage_backend OWNER mirage_backend'"

echo "Restoring indexer SQL dump..."
su - postgres -c "psql -v ON_ERROR_STOP=1 -d mirage_indexer -f /root/.mirage/backup_indexer.sql"

echo "Granting read-only access on indexer DB..."
su - postgres -c "psql -d mirage_indexer -c 'GRANT CONNECT ON DATABASE mirage_indexer TO mirage_indexer_ro'"
su - postgres -c "psql -d mirage_indexer -c 'GRANT USAGE ON SCHEMA public TO mirage_indexer_ro'"
su - postgres -c "psql -d mirage_indexer -c 'GRANT SELECT ON ALL TABLES IN SCHEMA public TO mirage_indexer_ro'"
su - postgres -c "psql -d mirage_indexer -c \"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO mirage_indexer_ro\""

if [ -f /root/.mirage/backup_backend.sql ]; then
    echo "Restoring backend SQL dump..."
    su - postgres -c "psql -v ON_ERROR_STOP=1 -d mirage_backend -f /root/.mirage/backup_backend.sql"
else
    echo "No backend SQL dump found, backend DB will be initialized by the application"
fi

echo "Cleaning up SQL dumps..."
rm -f /root/.mirage/backup_indexer.sql /root/.mirage/backup_backend.sql

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
    # Step 11: Start container (and import validator key if --migrate)
    # -------------------------------------------------------------------------
    if migrate and mnemonic:
        # Cross-server restore: need to import validator key from mnemonic
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

        status("Importing validator account key from mnemonic...")
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
    elif debug_skip:
        status("DEBUG MODE: Skipping key import")
        # Just restart the existing container
        status("Restarting container...")
        run(f"ssh {conn} 'docker update --restart=unless-stopped mirage && docker restart mirage'")
    else:
        # Same-server restore: keys already in backup, just start container
        status("Starting container (identity files restored from backup)...")
        run(f"ssh {conn} 'docker rm -f mirage 2>/dev/null || true'")
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

    # -------------------------------------------------------------------------
    # Step 13: Wait for node to start
    # -------------------------------------------------------------------------
    rpc_url = f"http://{target_host}/chain/rpc/status"
    status(f"Waiting for node to start ({rpc_url})...")
    for i in range(5):
        time.sleep(3)
        try:
            result = subprocess.run(
                ["curl", "-sfL", rpc_url],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
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
    print(f"  curl -sf http://{target_host}/chain/rpc/net_info | jq .result.n_peers")
    print(f"  # Check sync status:")
    print(f"  curl -sf http://{target_host}/chain/rpc/status | jq .result.sync_info")
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


def list_backups():
    """List all available backups, organized by server."""
    if not BACKUP_DIR.exists():
        print(f"No backups directory found at {BACKUP_DIR}")
        return

    # Get all server directories
    server_dirs = sorted([d for d in BACKUP_DIR.iterdir() if d.is_dir()])

    if not server_dirs:
        print("No backups found.")
        return

    print(f"Backups in {BACKUP_DIR}:\n")

    for server_dir in server_dirs:
        backups = sorted(
            server_dir.glob("*.tgz"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

        if not backups:
            continue

        print(f"  {server_dir.name}/")
        for i, b in enumerate(backups):
            size_gb = b.stat().st_size / (1024**3)
            mtime = datetime.fromtimestamp(b.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            marker = " (latest)" if i == 0 else ""
            print(f"    {b.name}  {size_gb:.2f} GB  {mtime}{marker}")
        print()


# =============================================================================
# MAIN
# =============================================================================


def main():
    parser = argparse.ArgumentParser(
        description="Full backup and restore for Mirage validator nodes.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Create backup from a server
  %(prog)s backup --source mirage.vote

  # Backup all 4 production servers
  %(prog)s backup --all

  # Restore SAME server using its own backup (no mnemonic needed)
  %(prog)s restore --target mirage.vote --latest

  # Restore using specific backup file
  %(prog)s restore --target mirage.vote --file ~/.mirage/backups/mirage.vote/mirage.vote-20260123-143052.tgz

  # Restore DIFFERENT server using another server's backup (requires mnemonic)
  %(prog)s restore --target 139.59.9.96 --file ~/.mirage/backups/mirage.vote/mirage.vote-20260123-143052.tgz --migrate

  # List available backups
  %(prog)s list
""",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # Backup command
    backup_parser = subparsers.add_parser("backup", help="Create backup from a server")
    backup_source = backup_parser.add_mutually_exclusive_group(required=True)
    backup_source.add_argument("--source", help="Source server hostname (e.g., mirage.vote)")
    backup_source.add_argument(
        "--all",
        action="store_true",
        help=f"Backup all 4 production servers: {', '.join(ALL_SERVERS)}",
    )
    backup_parser.add_argument("--user", default=SSH_USER, help=f"SSH user (default: {SSH_USER})")

    # Restore command
    restore_parser = subparsers.add_parser("restore", help="Restore backup to a server")
    restore_parser.add_argument("--target", required=True, help="Target server hostname")
    restore_parser.add_argument("--user", default=SSH_USER, help=f"SSH user (default: {SSH_USER})")
    restore_parser.add_argument("--force", action="store_true", help="Skip disk space check")
    restore_parser.add_argument("--debug-skip", action="store_true", help="Debug mode: skip steps 3-9 and mnemonic")
    restore_parser.add_argument(
        "--migrate",
        action="store_true",
        help="Cross-server restore: delete identity files from backup and derive new keys from mnemonic. "
        "Use when restoring a DIFFERENT server using another server's backup data.",
    )
    restore_parser.add_argument(
        "--image",
        help="Docker image to use (e.g., mirage:dev-20260115). "
        "Only needed if container doesn't exist and backup lacks metadata.",
    )

    # Mutually exclusive: --file or --latest
    backup_source = restore_parser.add_mutually_exclusive_group(required=True)
    backup_source.add_argument("--file", type=Path, help="Backup file to restore")
    backup_source.add_argument(
        "--latest",
        action="store_true",
        help="Use latest backup from ~/.mirage/backups/{target}/. "
        "Only for same-server restore (incompatible with --migrate).",
    )

    # List command
    subparsers.add_parser("list", help="List available backups")

    args = parser.parse_args()

    if args.command == "backup":
        if args.all:
            # Backup all 4 servers
            status(f"Backing up all {len(ALL_SERVERS)} servers: {', '.join(ALL_SERVERS)}")
            results = []
            for i, server in enumerate(ALL_SERVERS, 1):
                print(f"\n{'='*60}")
                print(f"[{i}/{len(ALL_SERVERS)}] Backing up {server}")
                print(f"{'='*60}\n")
                try:
                    backup_path = backup(server, args.user)
                    results.append((server, "OK", backup_path))

                    # Verify the server is healthy before proceeding
                    status(f"Verifying {server} is healthy after backup...")
                    verify_server_health(server, args.user)

                    # Wait 2 minutes between servers to ensure stability
                    if i < len(ALL_SERVERS):
                        status(f"Waiting 2 minutes before next backup...")
                        time.sleep(120)
                except Exception as e:
                    print(f"ERROR: Backup failed for {server}: {e}", file=sys.stderr)
                    results.append((server, "FAILED", str(e)))

            # Summary
            print(f"\n{'='*60}")
            print("Backup Summary")
            print(f"{'='*60}")
            for server, status_str, path_or_error in results:
                if status_str == "OK":
                    size_gb = path_or_error.stat().st_size / (1024**3)
                    print(f"  {server}: OK ({size_gb:.2f} GB)")
                else:
                    print(f"  {server}: FAILED - {path_or_error}")

            failed = [r for r in results if r[1] == "FAILED"]
            if failed:
                print(f"\n{len(failed)} backup(s) failed!")
                sys.exit(1)
        else:
            backup(args.source, args.user)
    elif args.command == "restore":
        # --migrate requires --file (you must specify which server's backup to use)
        if args.migrate and args.latest:
            print("ERROR: --migrate requires --file (specify which server's backup to use)", file=sys.stderr)
            sys.exit(1)

        # Determine backup file
        if args.latest:
            # Same-server restore: find latest backup in target's folder
            backup_file = find_latest_backup(args.target)
            status(f"Using latest backup: {backup_file}")
        else:
            backup_file = args.file

        restore(args.target, backup_file, args.user, args.force, args.debug_skip, args.migrate, args.image)
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
