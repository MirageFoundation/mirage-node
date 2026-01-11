#!/usr/bin/env bash
set -euo pipefail

# Create validator on-chain if it doesn't exist yet (idempotent)
# Usage: deploy/create_validator.sh

ROOT_DIR="${ROOT_DIR:-/opt/mirage}"
NODE_HOME="/root/.mirage/node"
BIN="${BIN:-$ROOT_DIR/blockchain/miraged}"
MONIKER="${MONIKER:-validator}"
RPC_URL="${RPC_URL:-http://127.0.0.1:26657}"
CHAIN_ID="${CHAIN_ID:-mirage-1}"
KEYRING_BACKEND="${KEYRING_BACKEND:-test}"

echo "==> Ensuring validator exists on-chain..."
echo "   Node home: $NODE_HOME"
echo "   Moniker: $MONIKER"
echo "   RPC: $RPC_URL"

# Wait for RPC to be available
echo "==> Waiting for RPC to be available..."
for i in $(seq 1 120); do
  if curl -sf "$RPC_URL/status" >/dev/null 2>&1; then
    echo "✓ RPC is ready"
    break
  fi
  if [ $i -eq 120 ]; then
    echo "ERROR: RPC not available after 120s" >&2
    exit 1
  fi
  sleep 1
done

# Check if node is synced
echo "==> Checking sync status..."
STATUS=$(curl -sf "$RPC_URL/status" || echo "")
CATCHING_UP=$(echo "$STATUS" | jq -r 'if .result.sync_info.catching_up == null then "true" else (.result.sync_info.catching_up | tostring) end' 2>/dev/null || echo "true")
if [ "$CATCHING_UP" != "false" ]; then
  LATEST_HEIGHT=$(echo "$STATUS" | jq -r '.result.sync_info.latest_block_height // "unknown"' 2>/dev/null || echo "unknown")
  echo "ERROR: Node is still catching up (height: $LATEST_HEIGHT)" >&2
  echo "   Wait for sync to complete before creating validator" >&2
  exit 1
fi
echo "✓ Node is synced"

# Verify priv_validator_key.json exists
if [ ! -f "$NODE_HOME/config/priv_validator_key.json" ]; then
  echo "ERROR: Consensus key file not found: $NODE_HOME/config/priv_validator_key.json" >&2
  exit 1
fi

# Obtain consensus pubkey directly from priv_validator_key.json
echo "==> Getting consensus pubkey..."
PUB_KEY_VALUE=$(jq -r '.pub_key.value' "$NODE_HOME/config/priv_validator_key.json" 2>/dev/null || echo "")
if [ -z "$PUB_KEY_VALUE" ] || [ "$PUB_KEY_VALUE" = "null" ]; then
  echo "ERROR: Failed to read pubkey from priv_validator_key.json" >&2
  echo "   File: $NODE_HOME/config/priv_validator_key.json" >&2
  exit 1
fi

# Convert to Cosmos SDK format: {"@type":"/cosmos.crypto.ed25519.PubKey","key":"..."}
PUB_JSON=$(jq -n --arg key "$PUB_KEY_VALUE" '{"@type":"/cosmos.crypto.ed25519.PubKey","key":$key}')
PUB="$PUB_KEY_VALUE"
echo "✓ Consensus pubkey: ${PUB:0:20}..."

# Check if validator with this pubkey already exists
echo "==> Checking if validator already exists..."
ALL="$($BIN q staking validators --home "$NODE_HOME" --node tcp://127.0.0.1:26657 -o json 2>/dev/null || echo "{}")"
MATCH=$(echo "$ALL" | jq -r --arg pub "$PUB" ".validators[]? | select(((.consensus_pubkey.value // .consensus_pubkey.key // \"\") == \$pub)) | .operator_address" 2>/dev/null | head -1)

if [ -n "$MATCH" ] && [ "$MATCH" != "null" ] && [ "$MATCH" != "" ]; then
  echo "✓ Validator already exists: $MATCH"
  exit 0
fi

# Check if validator account key exists
if ! $BIN keys show validator --home "$NODE_HOME" --keyring-backend "$KEYRING_BACKEND" >/dev/null 2>&1; then
  echo "ERROR: Validator account key not found in keyring" >&2
  echo "   Import the key first with: $BIN keys add validator --recover --home $NODE_HOME --keyring-backend $KEYRING_BACKEND" >&2
  exit 1
fi

# Create validator
echo "==> Creating validator (self-delegating 1 MIRAGE)..."
VAL_JSON="/tmp/validator.json"
cat > "$VAL_JSON" <<EOF
{
  "pubkey": $PUB_JSON,
  "amount": "1000000umirage",
  "moniker": "$MONIKER",
  "identity": "",
  "website": "",
  "security": "",
  "details": "",
  "commission-rate": "1.0",
  "commission-max-rate": "1.0",
  "commission-max-change-rate": "0.0",
  "min-self-delegation": "1000000"
}
EOF

echo "==> Submitting create-validator transaction..."
$BIN tx staking create-validator "$VAL_JSON" \
  --from validator \
  --keyring-backend "$KEYRING_BACKEND" \
  --chain-id "$CHAIN_ID" \
  --home "$NODE_HOME" \
  --node tcp://127.0.0.1:26657 \
  --gas auto --gas-adjustment 1.3 --gas-prices 0.025umirage \
  -y >/tmp/create_validator.out 2>&1
RC=$?

# Always show the transaction output
echo ""
echo "---- Transaction Output ----"
cat /tmp/create_validator.out
echo "----------------------------"
echo ""

if [ "$RC" -ne 0 ]; then
  echo "ERROR: create-validator tx failed (exit $RC)" >&2
  rm -f "$VAL_JSON"
  exit "$RC"
fi

# Extract txhash from output to check status
TXHASH=$(grep -oE '[A-F0-9]{64}' /tmp/create_validator.out | head -1 || echo "")
if [ -n "$TXHASH" ]; then
  echo "✓ Transaction submitted (txhash: ${TXHASH:0:16}...)"
else
  echo "✓ Transaction submitted (could not extract txhash)"
fi

rm -f "$VAL_JSON"

# Verify validator registration - wait up to 60 seconds, checking every second
echo "==> Verifying validator registration (checking every second for up to 60 seconds)..."
MATCH=""
for i in $(seq 1 60); do
  ALL="$($BIN q staking validators --home "$NODE_HOME" --node tcp://127.0.0.1:26657 -o json 2>/dev/null || echo "{}")"
  MATCH=$(echo "$ALL" | jq -r --arg pub "$PUB" ".validators[]? | select(((.consensus_pubkey.value // .consensus_pubkey.key // \"\") == \$pub)) | .operator_address" 2>/dev/null | head -1)
  if [ -n "$MATCH" ] && [ "$MATCH" != "null" ] && [ "$MATCH" != "" ]; then
    echo "✓ Validator registered: $MATCH"
    break
  fi
  if [ $((i % 5)) -eq 0 ]; then
    echo "   Still waiting... (${i}/60 seconds)"
  fi
  sleep 1
done

if [ -z "$MATCH" ] || [ "$MATCH" = "null" ] || [ "$MATCH" = "" ]; then
  echo ""
  echo "ERROR: Validator not visible in validator set after 60 seconds" >&2
  if [ -n "$TXHASH" ]; then
    echo "   Checking transaction status..." >&2
    TX_STATUS=$($BIN q tx "$TXHASH" --home "$NODE_HOME" --node tcp://127.0.0.1:26657 -o json 2>/dev/null || echo "{}")
    TX_CODE=$(echo "$TX_STATUS" | jq -r '.code // "unknown"' 2>/dev/null || echo "unknown")
    if [ "$TX_CODE" != "unknown" ] && [ "$TX_CODE" != "null" ]; then
      if [ "$TX_CODE" = "0" ]; then
        echo "   Transaction succeeded but validator not yet visible (may need more time)" >&2
      else
        TX_LOG=$(echo "$TX_STATUS" | jq -r '.raw_log // .logs[0].log // "No log available"' 2>/dev/null || echo "No log available")
        echo "   Transaction failed with code $TX_CODE" >&2
        echo "   Error: $TX_LOG" >&2
      fi
    else
      echo "   Transaction may still be pending or not found" >&2
    fi
  fi
  echo "---- Full transaction output ----" >&2
  cat /tmp/create_validator.out >&2 || true
  echo "----------------------------------" >&2
  exit 1
fi

echo "✓ Validator creation complete"

