#!/usr/bin/env bash
set -euo pipefail

# Create a lean snapshot of a remote mirage node
# Usage: scripts/create_snapshot.sh <ip>

if [ $# -lt 1 ]; then
    echo "Usage: $0 <ip> [ssh_user]"
    echo "Example: $0 64.23.136.132"
    exit 1
fi

IP="$1"
SSH_USER="${2:-root}"
CONN="${SSH_USER}@${IP}"

echo "==> Creating snapshot on ${CONN}..."

ssh -o StrictHostKeyChecking=accept-new "$CONN" bash -s <<'REMOTE_SCRIPT'
set -euo pipefail

MAIN_DIR="$HOME/.mirage/main"
BACKUP_DIR="$HOME/.mirage/backup"

if [ ! -d "$MAIN_DIR" ]; then
    echo "ERROR: $MAIN_DIR does not exist"
    exit 1
fi

echo "==> Stopping container..."
docker stop mirage --timeout 60 || true

echo "==> Cleaning up old backups and unnecessary files..."
rm -rf "$BACKUP_DIR"
rm -rf "$MAIN_DIR"/data.backup.* 2>/dev/null || true
rm -rf "$MAIN_DIR"/logs/*.log.* 2>/dev/null || true
rm -f "$MAIN_DIR"/miraged.log 2>/dev/null || true

echo "==> Creating lean backup..."
mkdir -p "$BACKUP_DIR/data"

# Essential: config and keys
cp -a "$MAIN_DIR/config" "$BACKUP_DIR/"
cp -a "$MAIN_DIR/keyring-test" "$BACKUP_DIR/" 2>/dev/null || true

# Essential: validator state (critical to avoid double signing)
cp "$MAIN_DIR/data/priv_validator_state.json" "$BACKUP_DIR/data/"

# Essential: chain state databases
cp -a "$MAIN_DIR/data/application.db" "$BACKUP_DIR/data/"
cp -a "$MAIN_DIR/data/state.db" "$BACKUP_DIR/data/"

# Optional: indexer data (small)
cp -a "$MAIN_DIR/data/indexer" "$BACKUP_DIR/data/" 2>/dev/null || true

echo "==> Restarting container..."
docker start mirage

echo "==> Snapshot complete:"
du -sh "$BACKUP_DIR"
echo ""
echo "Contents:"
du -sh "$BACKUP_DIR"/* 2>/dev/null || true
du -sh "$BACKUP_DIR/data"/* 2>/dev/null || true
echo ""
echo "Disk usage:"
df -h /
REMOTE_SCRIPT

echo "==> Done!"

