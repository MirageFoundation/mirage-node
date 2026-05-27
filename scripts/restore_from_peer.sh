#!/usr/bin/env bash
set -euo pipefail

# Restore blockchain data from a peer node WITHOUT copying keys or validator state.
# This prevents double-signing by preserving the target's priv_validator_state.json.
#
# Usage: scripts/restore_from_peer.sh --source=user@host --target=user@host
#
# What gets copied (blockchain data only):
#   - application.db/
#   - blockstore.db/
#   - cs.wal/
#   - evidence.db/
#   - snapshots/
#   - state.db/
#   - tx_index.db/
#
# What is NEVER copied (preserved on target):
#   - priv_validator_state.json (signing state - prevents double signing)
#   - config/ (keys, genesis, node identity)
#   - keyring-* (account keys)

show_help() {
  cat <<EOF
Restore blockchain data from a peer node

Usage: scripts/restore_from_peer.sh --source=user@host --target=user@host

Arguments:
  --source=user@host    SSH connection to healthy source node (e.g., root@146.190.108.140)
  --target=user@host    SSH connection to broken target node (e.g., root@64.23.136.132)

Safety:
  - NEVER copies private keys or config
  - Preserves target's priv_validator_state.json to prevent double signing
  - Only copies blockchain database files

Example:
  scripts/restore_from_peer.sh --source=root@146.190.108.140 --target=root@64.23.136.132
EOF
}

SOURCE=""
TARGET=""

while [ $# -gt 0 ]; do
  case "$1" in
    --source=*) SOURCE="${1#*=}"; shift ;;
    --source) SOURCE="$2"; shift 2 ;;
    --target=*) TARGET="${1#*=}"; shift ;;
    --target) TARGET="$2"; shift 2 ;;
    -h|--help) show_help; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; show_help; exit 1 ;;
  esac
done

if [ -z "$SOURCE" ] || [ -z "$TARGET" ]; then
  echo "ERROR: Both --source and --target are required" >&2
  show_help
  exit 1
fi

# Server-to-server transfer (step 6) needs SSH agent forwarding so the source
# can scp directly to the target without routing data through this workstation.
# Verify the agent has at least one key loaded BEFORE we start tearing things
# down; otherwise we'd stop both nodes and only discover the auth gap mid-flight.
if ! command -v ssh-add >/dev/null 2>&1; then
  echo "ERROR: ssh-add not found; cannot verify SSH agent state" >&2
  exit 1
fi
if ! ssh-add -l >/dev/null 2>&1; then
  echo "ERROR: SSH agent has no keys loaded (or is not running)." >&2
  echo "       This script needs agent forwarding (ssh -A) so $SOURCE can" >&2
  echo "       scp directly to $TARGET. Load the appropriate key with:" >&2
  echo "         ssh-add ~/.ssh/<your_key>" >&2
  exit 1
fi

echo "==> Restore blockchain data"
echo "    Source: $SOURCE"
echo "    Target: $TARGET"
echo ""
echo "WARNING: This will stop the target node and replace its blockchain data."
echo "         Keys and validator state will be preserved."
echo ""
read -p "Continue? [y/N] " confirm
if [ "$confirm" != "y" ] && [ "$confirm" != "Y" ]; then
  echo "Aborted."
  exit 0
fi

# Database directories to sync (relative to ~/.mirage/node/data/)
DB_DIRS="application.db blockstore.db cs.wal evidence.db snapshots state.db tx_index.db"

echo ""
echo "==> Step 1: Stop target node"
ssh "$TARGET" 'docker stop mirage || true'

echo ""
echo "==> Step 2: Backup target's priv_validator_state.json"
ssh "$TARGET" 'cp ~/.mirage/node/data/priv_validator_state.json /tmp/priv_validator_state.json.bak 2>/dev/null || echo "{\"height\":\"0\",\"round\":0,\"step\":0}" > /tmp/priv_validator_state.json.bak'

echo ""
echo "==> Step 3: Stop source node briefly for consistent snapshot"
ssh "$SOURCE" 'docker exec mirage pkill -TERM miraged 2>/dev/null || true; sleep 3'

echo ""
echo "==> Step 4: Create snapshot on source (databases only, excluding validator state)"
# --ignore-failed-read tolerates DB_DIRS entries that don't exist on this peer
# (e.g. tx_index.db is absent when CometBFT is configured with indexer="null").
ssh "$SOURCE" "cd ~/.mirage/node/data && tar --ignore-failed-read --exclude='priv_validator_state.json' -czf /tmp/blockchain_data.tar.gz $DB_DIRS"

echo ""
echo "==> Step 5: Restart source node"
ssh "$SOURCE" 'docker restart mirage'

echo ""
echo "==> Step 6: Transfer snapshot directly from source to target (server-to-server)"
# Uses SSH agent forwarding so source can authenticate to target with the key
# loaded in the operator's local agent. This bypasses the workstation entirely
# and saves ~5 min on a typical chain-DB transfer vs streaming through stdin.
ssh -A "$SOURCE" "scp -o StrictHostKeyChecking=accept-new /tmp/blockchain_data.tar.gz $TARGET:/tmp/blockchain_data.tar.gz"

echo ""
echo "==> Step 7: Clear target's old data (preserving priv_validator_state.json backup)"
ssh "$TARGET" "cd ~/.mirage/node/data && rm -rf $DB_DIRS"

echo ""
echo "==> Step 8: Extract snapshot on target"
ssh "$TARGET" 'cd ~/.mirage/node/data && tar -xzf /tmp/blockchain_data.tar.gz'

echo ""
echo "==> Step 9: Restore target's priv_validator_state.json"
ssh "$TARGET" 'cp /tmp/priv_validator_state.json.bak ~/.mirage/node/data/priv_validator_state.json'

echo ""
echo "==> Step 10: Cleanup temporary files"
ssh "$SOURCE" 'rm -f /tmp/blockchain_data.tar.gz'
ssh "$TARGET" 'rm -f /tmp/blockchain_data.tar.gz /tmp/priv_validator_state.json.bak'

echo ""
echo "==> Step 11: Start target node"
ssh "$TARGET" 'docker restart mirage'

echo ""
echo "==> Step 12: Verify node is starting"
sleep 3
ssh "$TARGET" 'docker logs --tail 20 mirage 2>&1' || true

echo ""
echo "==> Done! Target node should now sync from the restored state."
echo "    Monitor with: ssh $TARGET 'docker logs -f mirage'"

