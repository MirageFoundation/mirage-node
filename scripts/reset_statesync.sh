#!/usr/bin/env bash
#
# Reset a node via state-sync to reclaim disk space.
# Run this on the HOST (not inside Docker).
#
# Usage:
#   ./reset_statesync.sh [--yes]
#
# This script will:
#   1. Stop the node
#   2. Backup validator key
#   3. Wipe data directory
#   4. Configure state-sync with fresh trust height/hash
#   5. Restart node to sync from scratch
#
set -euo pipefail

# Parse args
AUTO_YES=false
for arg in "$@"; do
    case $arg in
        -y|--yes) AUTO_YES=true ;;
    esac
done

CONTAINER="mirage"
NODE_HOME="/root/.mirage/node"
DATA_DIR="$NODE_HOME/data"
CONFIG_DIR="$NODE_HOME/config"

# RPC servers for state-sync (use production validators)
RPC_SERVERS="http://159.203.114.27:26657,http://64.23.136.132:26657"

echo "=== State-Sync Reset ==="
echo ""
echo "This will WIPE the node data and state-sync from scratch."
echo "Disk space will be reclaimed after sync completes."
echo ""

if [ "$AUTO_YES" != "true" ]; then
    read -p "Continue? [y/N] " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Aborted."
        exit 1
    fi
fi

# Get trust height and hash from first RPC server
echo ""
echo "==> Fetching trust height and hash..."
RPC_SERVER=$(echo "$RPC_SERVERS" | cut -d',' -f1)
LATEST=$(curl -s "$RPC_SERVER/status" | jq -r '.result.sync_info.latest_block_height')
TRUST_HEIGHT=$((LATEST - 2000))
TRUST_HASH=$(curl -s "$RPC_SERVER/block?height=$TRUST_HEIGHT" | jq -r '.result.block_id.hash')

if [ -z "$TRUST_HASH" ] || [ "$TRUST_HASH" == "null" ]; then
    echo "ERROR: Could not fetch trust hash from $RPC_SERVER"
    exit 1
fi

echo "    Latest height:  $LATEST"
echo "    Trust height:   $TRUST_HEIGHT"
echo "    Trust hash:     $TRUST_HASH"

# Stop the node process (inside tmux)
echo ""
echo "==> Stopping node..."
docker exec "$CONTAINER" bash -c "tmux send-keys -t node C-c 2>/dev/null || true"
sleep 3

# Backup validator key if it exists
echo "==> Backing up validator key..."
docker exec "$CONTAINER" bash -c "
    if [ -f '$CONFIG_DIR/priv_validator_key.json' ]; then
        cp '$CONFIG_DIR/priv_validator_key.json' '/tmp/priv_validator_key.json.backup'
        echo '    Validator key backed up'
    else
        echo '    No validator key found (non-validator node)'
    fi
"

# Wipe data directory
echo "==> Wiping data directory..."
docker exec "$CONTAINER" bash -c "rm -rf '$DATA_DIR'/*"

# Reset priv_validator_state.json
echo "==> Resetting validator state..."
docker exec "$CONTAINER" bash -c "
    mkdir -p '$DATA_DIR'
    echo '{\"height\":\"0\",\"round\":0,\"step\":0}' > '$DATA_DIR/priv_validator_state.json'
"

# Enable state-sync in config.toml
echo "==> Configuring state-sync..."
docker exec "$CONTAINER" bash -c "
    CONFIG='$CONFIG_DIR/config.toml'
    
    # Update statesync section
    sed -i 's/^enable = false/enable = true/' \"\$CONFIG\"
    sed -i 's|^rpc_servers = \".*\"|rpc_servers = \"$RPC_SERVERS\"|' \"\$CONFIG\"
    sed -i 's/^trust_height = .*/trust_height = $TRUST_HEIGHT/' \"\$CONFIG\"
    sed -i 's/^trust_hash = \".*\"/trust_hash = \"$TRUST_HASH\"/' \"\$CONFIG\"
    
    echo '    State-sync enabled'
    echo '    RPC servers: $RPC_SERVERS'
"

# Restore validator key
echo "==> Restoring validator key..."
docker exec "$CONTAINER" bash -c "
    if [ -f '/tmp/priv_validator_key.json.backup' ]; then
        cp '/tmp/priv_validator_key.json.backup' '$CONFIG_DIR/priv_validator_key.json'
        rm '/tmp/priv_validator_key.json.backup'
        echo '    Validator key restored'
    fi
"

# Start the node
echo "==> Starting node with state-sync..."
docker exec "$CONTAINER" bash -c "
    tmux send-keys -t node '/opt/mirage/blockchain/bin/miraged start --home \"$NODE_HOME\" 2>&1 | tee >(cronolog \"/root/.mirage/logs/node/miraged-%Y-%m-%d.log\")' Enter
"

echo ""
echo "=== State-sync started ==="
echo ""
echo "Monitor progress with:"
echo "  docker exec $CONTAINER bash -c 'tail -f /root/.mirage/logs/node/miraged-\$(date +%Y-%m-%d).log'"
echo ""
echo "Or check status:"
echo "  curl -s http://localhost:26657/status | jq '.result.sync_info'"
echo ""
echo "Once sync completes, disable state-sync to prevent re-sync on restart:"
echo "  docker exec $CONTAINER sed -i 's/^enable = true/enable = false/' $CONFIG_DIR/config.toml"
