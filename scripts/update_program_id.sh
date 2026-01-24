#!/bin/bash
# Update Solana program ID and/or token address on all servers
# Usage: ./scripts/update_program_id.sh <new_program_id> [new_token_address]
#
# Examples:
#   ./scripts/update_program_id.sh 4taEm2D4skz4sPCMJEnLhF9XSDoULtgnn85M1bxbWA2c
#   ./scripts/update_program_id.sh 4taEm2D4skz4sPCMJEnLhF9XSDoULtgnn85M1bxbWA2c BfwtgUs98RkTTBRZK9UXTCnWv5B6Wqde3ZjSkX8KGSFc

set -e

NEW_PROGRAM_ID="$1"
NEW_TOKEN_ADDRESS="$2"

if [ -z "$NEW_PROGRAM_ID" ]; then
    echo "Usage: $0 <new_program_id> [new_token_address]"
    echo "Example: $0 4taEm2D4skz4sPCMJEnLhF9XSDoULtgnn85M1bxbWA2c BfwtgUs98RkTTBRZK9UXTCnWv5B6Wqde3ZjSkX8KGSFc"
    exit 1
fi

# Validate program ID looks like a Solana pubkey (base58, ~44 chars)
if [[ ! "$NEW_PROGRAM_ID" =~ ^[1-9A-HJ-NP-Za-km-z]{32,44}$ ]]; then
    echo "Error: Invalid program ID format"
    exit 1
fi

# Validate token address if provided
if [ -n "$NEW_TOKEN_ADDRESS" ]; then
    if [[ ! "$NEW_TOKEN_ADDRESS" =~ ^[1-9A-HJ-NP-Za-km-z]{32,44}$ ]]; then
        echo "Error: Invalid token address format"
        exit 1
    fi
fi

# All bridge servers
SERVERS=(
    "root@mirage.vote"      # Node 1 - 64.23.136.132
    "root@146.190.108.140"  # Node 2
    "root@139.59.9.96"      # Node 3
    "root@mirage.talk"      # Node 4
)

echo "=== Updating Solana Bridge Config ==="
echo "Program ID:    $NEW_PROGRAM_ID"
if [ -n "$NEW_TOKEN_ADDRESS" ]; then
    echo "Token Address: $NEW_TOKEN_ADDRESS"
fi
echo ""

for SERVER in "${SERVERS[@]}"; do
    echo "--- $SERVER ---"
    
    # Update program ID in orchestrator.env inside the container
    ssh "$SERVER" "docker exec mirage sed -i 's|^ORCHESTRATOR_SOLANA_PROGRAM_ID=.*|ORCHESTRATOR_SOLANA_PROGRAM_ID=$NEW_PROGRAM_ID|' /root/.mirage/env/orchestrator.env" || {
        echo "  [FAIL] Could not update program ID"
        continue
    }
    echo "  [OK] Updated program ID"
    
    # Update token address if provided
    if [ -n "$NEW_TOKEN_ADDRESS" ]; then
        ssh "$SERVER" "docker exec mirage sed -i 's|^ORCHESTRATOR_SOLANA_TOKEN_ADDRESS=.*|ORCHESTRATOR_SOLANA_TOKEN_ADDRESS=$NEW_TOKEN_ADDRESS|' /root/.mirage/env/orchestrator.env" || {
            echo "  [FAIL] Could not update token address"
            continue
        }
        echo "  [OK] Updated token address"
    fi
    
    # Restart orchestrator (with env sourced)
    ssh "$SERVER" "docker exec mirage pkill -TERM -f 'blockchain/bin/orchestrator' 2>/dev/null || true"
    sleep 2
    ssh "$SERVER" "docker exec mirage tmux send-keys -t mirage:orchestrator 'source /root/.mirage/env/orchestrator.env && /opt/mirage/blockchain/bin/orchestrator' C-m 2>/dev/null || true"
    echo "  [OK] Restarted orchestrator"
    
    echo ""
done

echo "=== Done ==="
echo ""
echo "To verify on any server:"
echo "  ssh root@<server> docker exec mirage grep ORCHESTRATOR_SOLANA /root/.mirage/env/orchestrator.env"
