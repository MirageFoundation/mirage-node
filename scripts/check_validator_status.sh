#!/usr/bin/env bash
set -euo pipefail

# Validator status checker - shows key validator information

# Trap to show error location on failure
trap 'echo "ERROR: Script failed at line $LINENO. Command: $BASH_COMMAND" >&2' ERR

ROOT_DIR="${ROOT_DIR:-/opt/mirage}"
NODE_HOME="$HOME/.mirage/node"
BIN="${BIN:-$ROOT_DIR/blockchain/miraged}"
RPC_URL="${RPC_URL:-http://127.0.0.1:26657}"
CHAIN_ID="${CHAIN_ID:-mirage-1}"
KEYRING_BACKEND="${KEYRING_BACKEND:-test}"

PRIV_VAL_KEY="$NODE_HOME/config/priv_validator_key.json"

clear
echo "=== Validator Status ==="
echo "Time: $(date '+%Y-%m-%d %H:%M:%S')"

# Get node version
NODE_VERSION=$($BIN version 2>/dev/null || echo "unknown")
echo "Version: $NODE_VERSION"
echo ""

# Check if RPC is available
if ! curl -sf "$RPC_URL/status" >/dev/null 2>&1; then
    echo "ERROR: Node RPC not available at $RPC_URL"
    exit 1
fi

# Get node status
STATUS=$(curl -sf "$RPC_URL/status" || echo "")
if [ -z "$STATUS" ]; then
    echo "ERROR: Failed to get node status from $RPC_URL/status"
    exit 1
fi

if ! echo "$STATUS" | jq -e '.result.sync_info' >/dev/null 2>&1; then
    echo "ERROR: Invalid status response from node"
    echo "Response: $STATUS"
    exit 1
fi

LATEST_HEIGHT=$(echo "$STATUS" | jq -r '.result.sync_info.latest_block_height // "unknown"')
# jq's // operator treats false as falsy, so we need to check for null explicitly
# Use ifnull to only default when the value is actually null/missing
CATCHING_UP=$(echo "$STATUS" | jq -r 'if .result.sync_info.catching_up == null then "true" else (.result.sync_info.catching_up | tostring) end')

# Only proceed if catching_up is explicitly false
if [ "$CATCHING_UP" != "false" ]; then
    if [ "$CATCHING_UP" = "true" ]; then
        echo "WAIT: Node is catching up (height: $LATEST_HEIGHT)"
    else
        echo "WARNING: Unexpected sync status value: $CATCHING_UP (assuming catching up)"
    fi
    echo "   Validator status check will be available after sync completes"
    exit 0
fi

# Check if priv_validator_key.json exists
if [ ! -f "$PRIV_VAL_KEY" ]; then
    echo "ERROR: Consensus key file not found: $PRIV_VAL_KEY"
    echo "   This file should exist if the validator is configured."
    exit 1
fi

# Get local consensus pubkey
LOCAL_PUB=$(jq -r '.pub_key.value // empty' "$PRIV_VAL_KEY" 2>/dev/null || echo "")
LOCAL_ADDR=$(jq -r '.address // empty' "$PRIV_VAL_KEY" 2>/dev/null || echo "")

if [ -z "$LOCAL_PUB" ] || [ -z "$LOCAL_ADDR" ]; then
    echo "ERROR: Invalid priv_validator_key.json format"
    echo "   File: $PRIV_VAL_KEY"
    echo "   Could not extract pub_key.value or address"
    echo "   This may indicate the file is corrupted or in an unexpected format."
    exit 1
fi

# Find validator operator address by matching local consensus pubkey
ALL_VALS=$($BIN query staking validators --home "$NODE_HOME" --node tcp://127.0.0.1:26657 -o json 2>/dev/null)
if [ $? -ne 0 ] || [ -z "$ALL_VALS" ]; then
    echo "ERROR: Failed to query validators"
    echo "   Command: $BIN query staking validators --home $NODE_HOME --node tcp://127.0.0.1:26657 -o json"
    echo "   Check if the node is running and RPC is accessible."
    exit 1
fi

if ! echo "$ALL_VALS" | jq -e '.validators' >/dev/null 2>&1; then
    echo "ERROR: Invalid validators query response"
    echo "Response: $ALL_VALS"
    exit 1
fi

VALOPER=$(echo "$ALL_VALS" | jq -r --arg pub "$LOCAL_PUB" '.validators[]? | select(.consensus_pubkey.value==$pub) | .operator_address' 2>/dev/null | head -1 | tr -d '\n\r ')

if [ -z "$VALOPER" ] || [ "$VALOPER" = "null" ] || [ "$VALOPER" = "" ]; then
    echo "ERROR: Validator not found on-chain"
    echo ""
    echo "   Local Consensus Address: $LOCAL_ADDR"
    echo "   Local Consensus Pubkey: $LOCAL_PUB"
    echo ""
    echo "   The validator may not exist yet or the consensus key doesn't match."
    echo ""
    echo "   To create the validator, run:"
    echo "   $ROOT_DIR/deploy/create_validator.sh"
    echo ""
    echo "   Or from outside the container:"
    echo "   docker exec mirage bash $ROOT_DIR/deploy/create_validator.sh"
    exit 1
fi

# Validate VALOPER is a bech32 address (should start with miragevaloper)
if ! echo "$VALOPER" | grep -qE '^miragevaloper'; then
    echo "ERROR: Invalid operator address format: $VALOPER"
    exit 1
fi

# Query validator info
VAL_INFO=$($BIN query staking validator "$VALOPER" --home "$NODE_HOME" --node tcp://127.0.0.1:26657 -o json 2>/dev/null)
if [ $? -ne 0 ] || [ -z "$VAL_INFO" ]; then
    echo "ERROR: Failed to query validator info for $VALOPER"
    exit 1
fi

if ! echo "$VAL_INFO" | jq -e '.validator' >/dev/null 2>&1; then
    echo "ERROR: Invalid validator info response"
    exit 1
fi

# Extract validator fields
MONIKER=$(echo "$VAL_INFO" | jq -r '.validator.description.moniker')
VAL_STAKE=$(echo "$VAL_INFO" | jq -r '.validator.tokens')
JAILED=$(echo "$VAL_INFO" | jq -r '.validator.jailed')
VAL_STATUS=$(echo "$VAL_INFO" | jq -r '.validator.status')
UNBONDING_TIME=$(echo "$VAL_INFO" | jq -r '.validator.unbonding_time')

# Convert stake to MIRAGE
STAKE_MIRAGE=$(awk "BEGIN {printf \"%.6f\", $VAL_STAKE / 1000000}")

# Check if in active validator set and get signatures (do this early for signing-info lookup)
VALIDATORS=$(curl -sf "$RPC_URL/validators?per_page=1000")

# Get jailed_until and tombstoned status (optional - basic jailed status already available from validator info)
# Note: query slashing signing-info needs bech32 consensus address, which is complex to derive from hex
# For now, we'll skip this detailed info - jailed status is sufficient from validator query
JAILED_UNTIL=""
TOMBSTONED="false"
IN_SET=$(echo "$VALIDATORS" | jq -r --arg addr "$LOCAL_ADDR" '.result.validators[]? | select(.address==$addr) | .voting_power' 2>/dev/null | head -1 || echo "")

# Check recent signatures
SIGNED=0
if [ -n "$IN_SET" ] && [ "$IN_SET" != "0" ] && [ "$IN_SET" != "null" ] && [ "$IN_SET" != "" ] && [ "$((IN_SET))" -gt 0 ]; then
    for i in $(seq 1 10); do
        HEIGHT=$((LATEST_HEIGHT - i + 1))
        if [ "$HEIGHT" -lt 1 ]; then
            break
        fi
        BLOCK=$(curl -sf "$RPC_URL/block?height=$HEIGHT" 2>/dev/null || echo "{}")
        SIG=$(echo "$BLOCK" | jq -r --arg addr "$LOCAL_ADDR" '.result.block.last_commit.signatures[]? | select(.validator_address==$addr) | .signature // empty' 2>/dev/null || echo "")
        if [ -n "$SIG" ] && [ "$SIG" != "null" ] && [ "$SIG" != "" ]; then
            SIGNED=$((SIGNED + 1))
        fi
    done
fi

# Format status display
STATUS_DISPLAY="$VAL_STATUS"
if [ "$VAL_STATUS" = "BOND_STATUS_UNBONDING" ] && [ -n "$UNBONDING_TIME" ] && [ "$UNBONDING_TIME" != "null" ] && [ "$UNBONDING_TIME" != "" ]; then
    STATUS_DISPLAY="${VAL_STATUS} (until $UNBONDING_TIME)"
fi

JAILED_DISPLAY="No"
if [ "$JAILED" = "true" ]; then
    JAILED_DISPLAY="Yes"
    if [ -n "$JAILED_UNTIL" ] && [ "$JAILED_UNTIL" != "null" ] && [ "$JAILED_UNTIL" != "" ]; then
        JAILED_DISPLAY="Yes (until $JAILED_UNTIL)"
    fi
fi

# Get account address and liquid balance
ACCOUNT_ADDR="mirage1${VALOPER#miragevaloper}"
BALANCE_JSON=$($BIN query bank balances "$ACCOUNT_ADDR" --node tcp://127.0.0.1:26657 -o json 2>/dev/null || echo '{"balances":[]}')
LIQUID_UMIRAGE=$(echo "$BALANCE_JSON" | jq -r '.balances[]? | select(.denom=="umirage") | .amount // "0"' 2>/dev/null | head -1)
[ -z "$LIQUID_UMIRAGE" ] && LIQUID_UMIRAGE="0"
LIQUID_MIRAGE=$(awk "BEGIN {printf \"%.6f\", $LIQUID_UMIRAGE / 1000000}")

# Display validator information
printf "%-12s %s\n" "Moniker:" "$MONIKER"
printf "%-12s %s\n" "Address:" "$VALOPER"
printf "%-12s %s\n" "Stake:" "$STAKE_MIRAGE MIRAGE"
printf "%-12s %s\n" "Liquid:" "$LIQUID_MIRAGE MIRAGE"
printf "%-12s %s\n" "Jailed:" "$JAILED_DISPLAY"
printf "%-12s %s\n" "Status:" "$STATUS_DISPLAY"
if [ -n "$IN_SET" ] && [ "$IN_SET" != "0" ] && [ "$IN_SET" != "null" ] && [ "$IN_SET" != "" ] && [ "$((IN_SET))" -gt 0 ]; then
    printf "%-12s %s\n" "Signatures:" "${SIGNED}/10"
fi
echo ""

if [ -n "$IN_SET" ] && [ "$IN_SET" != "0" ] && [ "$IN_SET" != "null" ] && [ "$IN_SET" != "" ] && [ "$((IN_SET))" -gt 0 ]; then
    echo "SUCCESS: IN ACTIVE VALIDATOR SET"
else
    echo "ERROR: NOT IN ACTIVE VALIDATOR SET"
    echo ""
    
    if [ "$JAILED" = "true" ]; then
        echo "   Validator is jailed. To unjail:"
        if $BIN keys show validator --home "$NODE_HOME" --keyring-backend "$KEYRING_BACKEND" -a >/dev/null 2>&1; then
            echo "   $BIN tx slashing unjail --from validator --home $NODE_HOME --keyring-backend $KEYRING_BACKEND --chain-id $CHAIN_ID --node tcp://127.0.0.1:26657 --fees 5000umirage -y"
        fi
    elif [ "$VAL_STATUS" = "BOND_STATUS_UNBONDING" ]; then
        echo "   Validator is unbonding and cannot join active set until unbonding completes."
    else
        echo "   Validator exists but is not in the active set."
        echo "   Possible reasons: insufficient stake, validator set is full, or recent status change."
    fi
fi

echo ""
echo "=== Connected Validators ==="

# Get net_info to find connected peers
NET_INFO=$(curl -sf "$RPC_URL/net_info" 2>/dev/null || echo "{}")
if ! echo "$NET_INFO" | jq -e '.result.peers' >/dev/null 2>&1; then
    echo "Unable to query peer information"
    exit 0
fi

# Get validator set with node IDs (from status or validators endpoint)
# The validators endpoint includes node_id in some cases, but we'll match by consensus address
# First, get all validators from the active set
ACTIVE_VALIDATORS=$(echo "$VALIDATORS" | jq -r '.result.validators[]? | {address: .address, voting_power: .voting_power, pub_key: .pub_key.value}' 2>/dev/null || echo "[]")

# Get peers count
PEER_COUNT=$(echo "$NET_INFO" | jq -r '.result.peers | length' 2>/dev/null || echo "0")

if [ "$PEER_COUNT" -eq 0 ]; then
    echo "No connected peers found"
    exit 0
fi

# Build a map of consensus addresses to validator info from ALL_VALS
# We'll match peers by trying to query their status and matching consensus pubkeys
CONNECTED_VALIDATORS=0

# For each peer, try to identify if they're a validator
# We'll query their status endpoint to get their node ID and try to match with validator set
PEER_INDEX=0
while [ "$PEER_INDEX" -lt "$PEER_COUNT" ]; do
    PEER_JSON=$(echo "$NET_INFO" | jq -c --argjson idx "$PEER_INDEX" '.result.peers[$idx]' 2>/dev/null)
    
    if [ -z "$PEER_JSON" ] || [ "$PEER_JSON" = "null" ]; then
        PEER_INDEX=$((PEER_INDEX + 1))
        continue
    fi
    
    PEER_NODE_ID=$(echo "$PEER_JSON" | jq -r '.node_info.id // empty')
    PEER_IP=$(echo "$PEER_JSON" | jq -r '.remote_ip // empty')
    PEER_LISTEN=$(echo "$PEER_JSON" | jq -r '.listen_addr // empty')
    
    [ -z "$PEER_IP" ] && PEER_INDEX=$((PEER_INDEX + 1)) && continue
    
    # Try to query peer's status to get their validator info
    # Note: This may fail if peer doesn't allow RPC access, so we'll skip those
    PEER_RPC="http://${PEER_IP}:26657"
    PEER_STATUS=$(curl -sf --max-time 2 "$PEER_RPC/status" 2>/dev/null || echo "{}")
    
    if ! echo "$PEER_STATUS" | jq -e '.result.validator_info' >/dev/null 2>&1; then
        PEER_INDEX=$((PEER_INDEX + 1))
        continue
    fi
    
    # Get peer's consensus address
    PEER_CONSENSUS_ADDR=$(echo "$PEER_STATUS" | jq -r '.result.validator_info.address // empty')
    PEER_PUBKEY=$(echo "$PEER_STATUS" | jq -r '.result.validator_info.pub_key.value // empty')
    
    if [ -z "$PEER_CONSENSUS_ADDR" ] || [ "$PEER_CONSENSUS_ADDR" = "null" ]; then
        PEER_INDEX=$((PEER_INDEX + 1))
        continue
    fi
    
    # Check if this consensus address is in the active validator set
    VAL_INFO=$(echo "$ACTIVE_VALIDATORS" | jq -r --arg addr "$PEER_CONSENSUS_ADDR" 'select(.address==$addr)' 2>/dev/null)
    
    if [ -z "$VAL_INFO" ] || [ "$VAL_INFO" = "null" ] || [ "$VAL_INFO" = "" ]; then
        # Not in active set, but might still be a validator (unbonding/unbonded)
        # Try to find in ALL_VALS by matching consensus pubkey
        VAL_OPERATOR=$(echo "$ALL_VALS" | jq -r --arg pub "$PEER_PUBKEY" '.validators[]? | select(.consensus_pubkey.value==$pub) | .operator_address' 2>/dev/null | head -1)
        
        if [ -n "$VAL_OPERATOR" ] && [ "$VAL_OPERATOR" != "null" ] && [ "$VAL_OPERATOR" != "" ]; then
            # Found validator but not in active set
            VAL_DETAILS=$(echo "$ALL_VALS" | jq -r --arg op "$VAL_OPERATOR" '.validators[]? | select(.operator_address==$op)' 2>/dev/null)
            VAL_MONIKER=$(echo "$VAL_DETAILS" | jq -r '.description.moniker // "Unknown"' 2>/dev/null)
            VAL_STATUS=$(echo "$VAL_DETAILS" | jq -r '.status // "Unknown"' 2>/dev/null)
            VAL_STAKE=$(echo "$VAL_DETAILS" | jq -r '.tokens // "0"' 2>/dev/null)
            VAL_STAKE_MIRAGE=$(awk "BEGIN {printf \"%.6f\", $VAL_STAKE / 1000000}" 2>/dev/null || echo "0")
            
            CONNECTED_VALIDATORS=$((CONNECTED_VALIDATORS + 1))
            if [ "$CONNECTED_VALIDATORS" -eq 1 ]; then
                printf "%-24s | %-15s | %-20s | %14s | %-20s\n" "Moniker" "IP Address" "Status" "Stake (MIRAGE)" "Validator Status"
                printf "%-24s-+-%-15s-+-%-20s-+-%14s-+-%-20s\n" "------------------------" "---------------" "--------------------" "--------------" "--------------------"
            fi
            printf "%-24s | %-15s | %-20s | %14s | %-20s\n" "$VAL_MONIKER" "$PEER_IP" "Connected" "$VAL_STAKE_MIRAGE" "$VAL_STATUS"
        fi
    else
        # In active validator set
        VAL_VOTING_POWER=$(echo "$VAL_INFO" | jq -r '.voting_power // "0"' 2>/dev/null)
        
        # Find moniker and stake from ALL_VALS
        VAL_OPERATOR=$(echo "$ALL_VALS" | jq -r --arg pub "$PEER_PUBKEY" '.validators[]? | select(.consensus_pubkey.value==$pub) | .operator_address' 2>/dev/null | head -1)
        
        if [ -n "$VAL_OPERATOR" ] && [ "$VAL_OPERATOR" != "null" ] && [ "$VAL_OPERATOR" != "" ]; then
            VAL_DETAILS=$(echo "$ALL_VALS" | jq -r --arg op "$VAL_OPERATOR" '.validators[]? | select(.operator_address==$op)' 2>/dev/null)
            VAL_MONIKER=$(echo "$VAL_DETAILS" | jq -r '.description.moniker // "Unknown"' 2>/dev/null)
            VAL_STAKE=$(echo "$VAL_DETAILS" | jq -r '.tokens // "0"' 2>/dev/null)
            VAL_STAKE_MIRAGE=$(awk "BEGIN {printf \"%.6f\", $VAL_STAKE / 1000000}" 2>/dev/null || echo "0")
            
            CONNECTED_VALIDATORS=$((CONNECTED_VALIDATORS + 1))
            if [ "$CONNECTED_VALIDATORS" -eq 1 ]; then
                printf "%-24s | %-15s | %-20s | %14s | %-20s\n" "Moniker" "IP Address" "Status" "Stake (MIRAGE)" "Validator Status"
                printf "%-24s-+-%-15s-+-%-20s-+-%14s-+-%-20s\n" "------------------------" "---------------" "--------------------" "--------------" "--------------------"
            fi
            printf "%-24s | %-15s | %-20s | %14s | %-20s\n" "$VAL_MONIKER" "$PEER_IP" "Active (VP: $VAL_VOTING_POWER)" "$VAL_STAKE_MIRAGE" "BOND_STATUS_BONDED"
        fi
    fi
    
    PEER_INDEX=$((PEER_INDEX + 1))
done

if [ "$CONNECTED_VALIDATORS" -eq 0 ]; then
    echo "No validators found among connected peers"
    echo "(Peers may not allow RPC access or may not be validators)"
fi

echo ""


