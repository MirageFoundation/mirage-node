#!/bin/bash
# Fetches current node IDs from all servers and outputs updated PERSISTENT_PEERS line
# Usage: ./scripts/fetch_node_ids.sh

set -e

# Server definitions (IP:PORT)
SERVERS=(
    "159.203.114.27:26656"   # PROD (mirage.talk)
    "64.23.136.132:26656"    # UAT (mirage.vote)
    "146.190.108.140:26656"  # 3rd node
    "139.59.9.96:26656"      # 4th node
)

PEERS=()

echo "Fetching node IDs from servers..."
echo ""

for server in "${SERVERS[@]}"; do
    ip="${server%%:*}"
    port="${server##*:}"
    
    echo -n "  $ip ... "
    
    # Fetch node ID via SSH (extract from status JSON)
    node_id=$(ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no "root@$ip" \
        "docker exec mirage /opt/mirage/blockchain/bin/miraged status 2>/dev/null | jq -r '.node_info.id'")
    
    if [ -z "$node_id" ]; then
        echo "FAILED (could not fetch node ID)"
        exit 1
    fi
    
    echo "$node_id"
    PEERS+=("${node_id}@${server}")
done

echo ""
echo "=========================================="
echo "Updated PERSISTENT_PEERS value:"
echo "=========================================="
echo ""

# Join array with commas
IFS=','
echo "PERSISTENT_PEERS=${PEERS[*]}"