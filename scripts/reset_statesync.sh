#!/usr/bin/env bash
#
# Reset a node via state-sync to reclaim disk space.
# Run this on the HOST (not inside Docker).
#
# Usage:
#   ./reset_statesync.sh [--yes] [--wait]
#
# Options:
#   --yes   Skip confirmation prompt
#   --wait  Wait for sync to complete and auto-disable state-sync
#
# This script will:
#   1. Stop the node
#   2. Backup validator key
#   3. Wipe data directory
#   4. Configure state-sync with fresh trust height/hash
#   5. Restart node to sync from scratch
#   6. (with --wait) Monitor until synced, then disable state-sync
#
set -euo pipefail

# Parse args
AUTO_YES=false
WAIT_FOR_SYNC=false
for arg in "$@"; do
    case $arg in
        -y|--yes) AUTO_YES=true ;;
        -w|--wait) WAIT_FOR_SYNC=true ;;
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

if [ "$WAIT_FOR_SYNC" = "true" ]; then
    echo ""
    echo "Waiting for state-sync to complete..."
    echo ""
    
    # Wait for node to start responding
    sleep 15
    
    while true; do
        # Query status through docker exec for reliability
        STATUS=$(docker exec "$CONTAINER" curl -s http://127.0.0.1:26657/status 2>/dev/null || echo '{}')
        CATCHING_UP=$(echo "$STATUS" | jq -r '.result.sync_info.catching_up // "true"')
        LATEST=$(echo "$STATUS" | jq -r '.result.sync_info.latest_block_height // "0"')
        
        if [ "$CATCHING_UP" = "false" ] && [ "$LATEST" != "0" ] && [ "$LATEST" != "null" ]; then
            echo ""
            echo "==> Sync complete at height $LATEST"
            break
        fi
        
        # Show progress
        if [ "$LATEST" != "0" ] && [ "$LATEST" != "null" ]; then
            printf "\r    Syncing... height: %-10s" "$LATEST"
        else
            printf "\r    Waiting for state-sync snapshot...        "
        fi
        sleep 10
    done
    
    # Disable state-sync after successful sync.
    # Note: This is a safety convention, not strictly required.
    # - CometBFT won't re-sync if data already exists (even with enable=true)
    # - But trust_height/trust_hash become stale after trust_period (7 days)
    # - Disabling keeps config clean and avoids confusion
    echo "==> Disabling state-sync in config..."
    docker exec "$CONTAINER" sed -i 's/^enable = true/enable = false/' "$CONFIG_DIR/config.toml"
    
    # Reset indexer to start from earliest available block.
    # After state-sync, old blocks are gone - indexer needs to skip them.
    echo "==> Resetting indexer position..."
    EARLIEST=$(docker exec "$CONTAINER" curl -s http://127.0.0.1:26657/status | jq -r '.result.sync_info.earliest_block_height')
    if [ -n "$EARLIEST" ] && [ "$EARLIEST" != "null" ]; then
        # Set indexer to one block before earliest so it starts fresh
        INDEXER_START=$((EARLIEST - 1))
        docker exec "$CONTAINER" su - postgres -c "psql -d mirage -c \"UPDATE meta SET value = '$INDEXER_START' WHERE key = 'last_height';\"" 2>/dev/null || true
        echo "    Indexer will resume from block $EARLIEST"
        
        # Restart indexer
        docker exec "$CONTAINER" tmux send-keys -t mirage:indexer C-c 2>/dev/null || true
        sleep 2
        docker exec "$CONTAINER" tmux send-keys -t mirage:indexer "cd /opt/mirage/indexer && python3 main.py 2>&1 | tee -a /root/.mirage/logs/indexer/indexer.log" Enter
        echo "    Indexer restarted"
    else
        echo "    Warning: Could not determine earliest block, indexer may need manual reset"
    fi
    
    echo ""
    echo "=== State-sync complete ==="
    echo "Node is synced and state-sync is disabled."
    echo "Data directory size:"
    docker exec "$CONTAINER" du -sh "$DATA_DIR"
else
    echo ""
    echo "Monitor progress with:"
    echo "  docker exec $CONTAINER bash -c 'tail -f /root/.mirage/logs/node/miraged-\$(date +%Y-%m-%d).log'"
    echo ""
    echo "Or check status:"
    echo "  curl -s http://localhost:26657/status | jq '.result.sync_info'"
    echo ""
    echo "Once sync completes, optionally disable state-sync for cleanliness:"
    echo "  docker exec $CONTAINER sed -i 's/^enable = true/enable = false/' $CONFIG_DIR/config.toml"
    echo ""
    echo "(Not strictly required - CometBFT won't re-sync if data exists."
    echo " But trust params go stale after 7 days, so disabling is cleaner.)"
    echo ""
    echo "Or re-run with --wait to auto-disable when sync completes."
fi
