#!/bin/bash
# Update Solana program ID on all UAT/test servers
# Usage: ./scripts/update_program_id.sh <new_program_id>
#
# Does NOT touch production (mirage.talk) - run manually if needed

set -e

NEW_PROGRAM_ID="$1"

if [ -z "$NEW_PROGRAM_ID" ]; then
    echo "Usage: $0 <new_program_id>"
    echo "Example: $0 4taEm2D4skz4sPCMJEnLhF9XSDoULtgnn85M1bxbWA2c"
    exit 1
fi

# Validate it looks like a Solana pubkey (base58, ~44 chars)
if [[ ! "$NEW_PROGRAM_ID" =~ ^[1-9A-HJ-NP-Za-km-z]{32,44}$ ]]; then
    echo "Error: Invalid program ID format"
    exit 1
fi

# UAT and test servers (NOT production)
SERVERS=(
    "root@mirage.vote"      # UAT - 64.23.136.132
    "root@146.190.108.140"  # Node 3
    "root@139.59.9.96"      # Node 4
    "root@mirage.talk"      # Prod
)

echo "=== Updating Solana Program ID ==="
echo "New ID: $NEW_PROGRAM_ID"
echo ""

for SERVER in "${SERVERS[@]}"; do
    echo "--- $SERVER ---"
    
    # Update orchestrator.env inside the container
    ssh "$SERVER" "docker exec mirage sed -i 's|^ORCHESTRATOR_SOLANA_PROGRAM_ID=.*|ORCHESTRATOR_SOLANA_PROGRAM_ID=$NEW_PROGRAM_ID|' /root/.mirage/env/orchestrator.env" || {
        echo "  [FAIL] Could not update orchestrator.env"
        continue
    }
    echo "  [OK] Updated orchestrator.env"
    
    # Restart orchestrator (with env sourced)
    ssh "$SERVER" "docker exec mirage pkill -TERM -f 'blockchain/bin/orchestrator' 2>/dev/null || true"
    sleep 2
    ssh "$SERVER" "docker exec mirage tmux send-keys -t mirage:orchestrator 'source /root/.mirage/env/orchestrator.env && /opt/mirage/blockchain/bin/orchestrator' C-m 2>/dev/null || true"
    echo "  [OK] Restarted orchestrator"
    
    echo ""
done

echo "=== Done ==="
echo ""
echo "NOTE: Production (mirage.talk) was NOT updated."
echo "To update production manually:"
echo "  ssh root@mirage.talk"
echo "  docker exec mirage sed -i 's|^ORCHESTRATOR_SOLANA_PROGRAM_ID=.*|ORCHESTRATOR_SOLANA_PROGRAM_ID=$NEW_PROGRAM_ID|' /root/.mirage/env/orchestrator.env"
echo "  docker exec mirage pkill -TERM -f 'blockchain/bin/orchestrator'"
