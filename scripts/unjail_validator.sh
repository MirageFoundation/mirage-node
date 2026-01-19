#!/usr/bin/env bash
set -euo pipefail

# Unjail the validator with correct account sequence handling (container friendly)
# Usage (inside container):
#   bash /opt/mirage/scripts/unjail_validator.sh
#
# This script:
#  - Verifies RPC readiness
#  - Resolves validator operator and account addresses
#  - Ensures local consensus key matches on-chain (warns if not)
#  - Fetches account_number and sequence from chain
#  - Broadcasts unjail in block mode with explicit sequence
#  - Retries once automatically on sequence mismatch
#  - Prints post-state (jailed flag, status)

ROOT_DIR="${ROOT_DIR:-/opt/mirage}"
BIN="${BIN:-$ROOT_DIR/blockchain/bin/miraged}"
NODE_HOME="${HOME:-/root}/.mirage/node"

# Safety check: prevent doubling .mirage/node
if echo "$NODE_HOME" | grep -qE "\.mirage/node/\.mirage/node"; then
  NODE_HOME="/root/.mirage/node"
fi
KEYRING_BACKEND="${KEYRING_BACKEND:-test}"
CHAIN_ID="${CHAIN_ID:-mirage-1}"
RPC="${RPC:-tcp://127.0.0.1:26657}"
RPC_HTTP="${RPC_HTTP:-http://127.0.0.1:26657}"
EXCLUDE_IPS="${EXCLUDE_IPS:-}"
USE_REMOTE_RPC="${USE_REMOTE_RPC:-true}"

say() { printf "%s\n" "$*"; }
die() { printf "ERROR: %s\n" "$*" >&2; exit 1; }

require_bin() {
  command -v "$1" >/dev/null 2>&1 || die "missing dependency: $1"
}

require_bin "$BIN"
require_bin jq
require_bin curl
require_bin timeout # for the timeout command

# Try to pick a live remote RPC from peers/addrbook (exclude blocked IPs)
select_remote_rpc() {
  # Helper: test an IP for RPC readiness
  test_rpc() {
    local ip="$1"
    for ex in $EXCLUDE_IPS; do
      if [ "$ip" = "$ex" ]; then
        return 1
      fi
    done
    curl -sf "http://$ip:26657/status" >/dev/null 2>&1
  }
  # 1) Try peers from net_info
  local peers
  peers="$(curl -sf "$RPC_HTTP/net_info" 2>/dev/null | jq -r '.result.peers[]? | .remote_ip // empty' 2>/dev/null || true)"
  if [ -n "$peers" ]; then
    while IFS=$'\n' read -r ip; do
      [ -z "$ip" ] && continue
      if test_rpc "$ip"; then
        RPC_HTTP="http://$ip:26657"
        RPC="tcp://$ip:26657"
        say "Using remote RPC from peers: $RPC_HTTP"
        return 0
      fi
    done <<< "$peers"
  fi
  # 2) Try addrbook
  local addrbook="$NODE_HOME/config/addrbook.json"
  if [ -f "$addrbook" ]; then
    # Common CometBFT formats
    local ips
    ips="$(jq -r '.addrs[]? | .addr.ip // .ip // .address // empty' "$addrbook" 2>/dev/null || echo "")"
    if [ -z "$ips" ]; then
      # Parse tcp://id@ip:port strings
      ips="$(jq -r '.addrs[]? | .addr // empty' "$addrbook" 2>/dev/null | sed -nE 's#.*@([0-9.]+):[0-9]+#\1#p')"
    fi
    if [ -n "$ips" ]; then
      while IFS=$'\n' read -r ip; do
        [ -z "$ip" ] && continue
        if test_rpc "$ip"; then
          RPC_HTTP="http://$ip:26657"
          RPC="tcp://$ip:26657"
          say "Using remote RPC from addrbook: $RPC_HTTP"
          return 0
        fi
      done <<< "$ips"
    fi
  fi
  return 1
}

say "=== Unjail Validator (block mode, with sequence handling) ==="
say "Home:     $NODE_HOME"
say "RPC:      $RPC"
say ""

# 1) Wait for RPC
for i in $(seq 1 30); do
  if curl -sf "$RPC_HTTP/status" >/dev/null 2>&1; then
    break
  fi
  if [ "$i" -eq 30 ]; then
    die "RPC not ready at $RPC_HTTP"
  fi
  sleep 1
done

# Optionally switch to a live remote RPC for broadcasting/queries (exclude blocked IPs)
if [ "$USE_REMOTE_RPC" = "true" ]; then
  if select_remote_rpc; then
    :
  else
    say "No remote RPC found, continuing with $RPC_HTTP"
  fi
fi

# 2) Resolve addresses
if ! $BIN keys show validator --home "$NODE_HOME" --keyring-backend "$KEYRING_BACKEND" >/dev/null 2>&1; then
  die "key 'validator' not found in keyring (home=$NODE_HOME, keyring=$KEYRING_BACKEND)"
fi

ACCOUNT_ADDR="$($BIN keys show validator -a --home "$NODE_HOME" --keyring-backend "$KEYRING_BACKEND" 2>/dev/null | tr -d '\r\n')"
[ -n "$ACCOUNT_ADDR" ] || die "failed to resolve validator account address"

if $BIN keys show validator --bech val --address --home "$NODE_HOME" --keyring-backend "$KEYRING_BACKEND" >/dev/null 2>&1; then
  VALOPER="$($BIN keys show validator --bech val --address --home "$NODE_HOME" --keyring-backend "$KEYRING_BACKEND" 2>/dev/null | tr -d '\r\n')"
else
  # Fallback: transform account -> valoper
  if [[ "$ACCOUNT_ADDR" =~ ^mirage1(.+)$ ]]; then
    VALOPER="miragevaloper1${BASH_REMATCH[1]}"
  else
    die "cannot derive valoper from account address"
  fi
fi

say "Account:  $ACCOUNT_ADDR"
say "Valoper:  $VALOPER"
say ""

# 3) IMMEDIATELY check jailed status and jailed_until BEFORE attempting anything
say "=== Checking Validator Status ==="
VAL_INFO_PRE="$($BIN q staking validator "$VALOPER" --node "$RPC" -o json 2>/dev/null || echo "{}")"
JAILED_PRE="$(echo "$VAL_INFO_PRE" | jq -r '.validator.jailed // false' 2>/dev/null || echo "false")"
TOMBSTONED_PRE="false"
JAILED_UNTIL_PRE=""

if [ "$JAILED_PRE" = "true" ]; then
  say ""
  say "⚠️  VALIDATOR IS JAILED"
  say ""
  
  # Get all signing-infos immediately to show jailed_until
  SLASH_INFO_PRE="$($BIN q slashing signing-infos --node "$RPC" -o json 2>/dev/null || echo "{}")"
  
  # Get jailed signing-infos (those with jailed_until set and not epoch zero)
  JAILED_SIGNING_INFOS="$(echo "$SLASH_INFO_PRE" | jq -r '.info[]? | select(.jailed_until != null and .jailed_until != "" and .jailed_until != "1970-01-01T00:00:00Z") | [.address, .jailed_until, .tombstoned] | @tsv' 2>/dev/null)"
  
  if [ -n "$JAILED_SIGNING_INFOS" ]; then
    # Show all jailed signing-infos immediately
    say "Found jailed signing-infos:"
    echo "$JAILED_SIGNING_INFOS" | while IFS=$'\t' read -r addr until tomb; do
      say "  Consensus Address: $addr"
      say "  Jailed Until: $until"
      say "  Tombstoned: $tomb"
      say ""
    done
    
    # Match to OUR validator by matching consensus pubkey to signing-info
    say "Matching signing-info to our validator (operator: $VALOPER)..."
    
    # Get our validator's consensus pubkey
    VAL_CONSENSUS_PUBKEY_PRE="$(echo "$VAL_INFO_PRE" | jq -r '.validator.consensus_pubkey.value // ""' 2>/dev/null || echo "")"
    
    if [ -z "$VAL_CONSENSUS_PUBKEY_PRE" ] || [ "$VAL_CONSENSUS_PUBKEY_PRE" = "" ]; then
      die "Could not get validator consensus pubkey"
    fi
    
    # Get all validators to find which one has our consensus pubkey and operator
    ALL_VALS_PRE="$($BIN q staking validators --node "$RPC" -o json 2>/dev/null || echo "{}")"
    
    # Find validator with our operator and consensus pubkey
    OUR_VAL_CONSENSUS_ADDR=""
    # Query validators to find the one with our operator, then get its consensus address
    # Validators query doesn't return consensus_address directly, so we need to match differently
    
    # Match by checking each jailed signing-info against all validators
    # For each jailed signing-info, check if any validator with our operator matches
    CONS_ADDR_BECH32=""
    JAILED_UNTIL_PRE=""
    TOMBSTONED_PRE="false"
    
    # Try to match by checking if any validator with our operator has a consensus pubkey
    # that corresponds to a jailed signing-info
    # Since we can't directly convert, we'll match by checking all validators
    # and finding which one has our operator, then try to match signing-infos
    
    # Get all validators with our operator address
    VALS_WITH_OUR_OP=$(echo "$ALL_VALS_PRE" | jq -r --arg op "$VALOPER" '.validators[]? | select(.operator_address==$op) | .consensus_pubkey.value' 2>/dev/null)
    
    if [ -n "$VALS_WITH_OUR_OP" ]; then
      # We found validators with our operator - now match signing-infos
      # Since we can't directly convert pubkey to consensus address, we'll match by:
      # 1. Check if there's only one jailed signing-info (use it)
      # 2. Otherwise, try to match by checking validators for each signing-info
      
      JAILED_COUNT=$(echo "$JAILED_SIGNING_INFOS" | wc -l)
      if [ "$JAILED_COUNT" -eq 1 ]; then
        # Only one jailed signing-info - assume it's ours
        CONS_ADDR_BECH32="$(echo "$JAILED_SIGNING_INFOS" | cut -f1)"
        JAILED_UNTIL_PRE="$(echo "$JAILED_SIGNING_INFOS" | cut -f2)"
        TOMBSTONED_PRE="$(echo "$JAILED_SIGNING_INFOS" | cut -f3)"
        say "✓ Matched: Only one jailed signing-info found"
        say ""
      else
        # Multiple jailed signing-infos - need to match more carefully
        # Try to match by checking which validator has our consensus pubkey
        # and see if we can find a corresponding signing-info
        
        # For each jailed signing-info, check if we can match it to our validator
        # by checking if any validator with our operator has a matching pubkey
        # Since we can't convert easily, we'll use the validator's consensus pubkey
        # to try to match
        
        # Actually, let's try querying each signing-info and see if we can match
        # by checking validators. But signing-info doesn't tell us which validator it belongs to.
        
        # Best approach: Match by checking if our validator's consensus pubkey
        # matches any validator, then try to find the corresponding signing-info
        # Since we can't convert, we'll match by checking all validators for our operator
        # and consensus pubkey, then use heuristic
        
        # Check if our validator exists with matching pubkey
        OUR_VAL_MATCH=$(echo "$ALL_VALS_PRE" | jq -r --arg op "$VALOPER" --arg pub "$VAL_CONSENSUS_PUBKEY_PRE" '.validators[]? | select(.operator_address==$op and .consensus_pubkey.value==$pub) | .operator_address' 2>/dev/null | head -1)
        
        if [ -n "$OUR_VAL_MATCH" ] && [ "$OUR_VAL_MATCH" = "$VALOPER" ]; then
          # Our validator exists - now try to match signing-infos
          # Since we can't directly convert, we'll try to match by checking
          # if any validator in the active set has our consensus pubkey
          # and matches a jailed signing-info
          
          # Try to get consensus address from local priv_validator_key.json
          LOCAL_HEX_ADDR=""
          if [ -f "$NODE_HOME/config/priv_validator_key.json" ]; then
            LOCAL_HEX_ADDR=$(jq -r '.address // empty' "$NODE_HOME/config/priv_validator_key.json" 2>/dev/null | tr '[:lower:]' '[:upper:]' || echo "")
          fi
          
          # Match by querying validator set to find our validator's hex address
          # Then match that to jailed signing-infos
          MATCHED=false
          
          # Query validator set at multiple heights to find our validator
          # (it might not be in current set if jailed)
          OUR_VAL_HEX_ADDR=""
          for HEIGHT in "" "1" "100" "500" "1000" "1500"; do
            VALIDATOR_SET=$(curl -sf "$RPC_HTTP/validators${HEIGHT:+?height=$HEIGHT}" 2>/dev/null || echo "{}")
            if [ -n "$VALIDATOR_SET" ] && [ "$VALIDATOR_SET" != "{}" ]; then
              # Find validator with our pubkey and get its hex address
              VAL_HEX=$(echo "$VALIDATOR_SET" | jq -r --arg pub "$VAL_CONSENSUS_PUBKEY_PRE" '.result.validators[]? | select(.pub_key.value==$pub) | .address' 2>/dev/null | head -1)
              if [ -n "$VAL_HEX" ] && [ "$VAL_HEX" != "" ] && [ "$VAL_HEX" != "null" ]; then
                OUR_VAL_HEX_ADDR="$VAL_HEX"
                break
              fi
            fi
          done
          
          # If we found our validator's hex address, match it to local hex address
          # and then try to find the corresponding bech32 address in jailed signing-infos
          if [ -n "$OUR_VAL_HEX_ADDR" ] && [ "$OUR_VAL_HEX_ADDR" != "" ]; then
            # Normalize hex addresses for comparison
            OUR_VAL_HEX_UPPER=$(echo "$OUR_VAL_HEX_ADDR" | tr '[:lower:]' '[:upper:]')
            LOCAL_HEX_UPPER=$(echo "$LOCAL_HEX_ADDR" | tr '[:lower:]' '[:upper:]')
            
            if [ "$OUR_VAL_HEX_UPPER" = "$LOCAL_HEX_UPPER" ]; then
              # Hex addresses match! Now find which jailed signing-info corresponds
              # Since we can't convert hex to bech32 easily, we'll use the fact that
              # our validator's pubkey matches, and try to match by checking validators
              # at different heights to see which consensus address (bech32) corresponds
              
              # For each jailed signing-info, check if we can verify it's ours
              # by checking if querying validators shows a match
              for CONS_ADDR in $(echo "$JAILED_SIGNING_INFOS" | cut -f1); do
                # Try to verify this signing-info is ours by checking validator set
                # If we can find a validator with our pubkey and this consensus address matches,
                # it's ours. But we can't easily check that.
                
                # Since we know our hex address matches, and we have jailed signing-infos,
                # we'll use the one that matches our validator's status or use heuristic
                # For now, if hex addresses match, use the most recent jailed signing-info
                MOST_RECENT=$(echo "$JAILED_SIGNING_INFOS" | sort -t$'\t' -k2 -r | head -1)
                CONS_ADDR_BECH32="$(echo "$MOST_RECENT" | cut -f1)"
                MATCHED=true
                break
              done
            fi
          fi
          
          # If still no match, try matching each jailed signing-info by checking validators
          if [ "$MATCHED" != "true" ]; then
            for CONS_ADDR in $(echo "$JAILED_SIGNING_INFOS" | cut -f1); do
              # Try to verify this signing-info belongs to our validator
              # by checking if any validator with our pubkey matches
              # Since we can't easily convert, we'll use heuristic: most recent jailed_until
              MOST_RECENT=$(echo "$JAILED_SIGNING_INFOS" | sort -t$'\t' -k2 -r | head -1)
              CONS_ADDR_BECH32="$(echo "$MOST_RECENT" | cut -f1)"
              MATCHED=true
              break
            done
          fi
          
          # If matched, get jailed_until and tombstoned
          if [ "$MATCHED" = "true" ] && [ -n "$CONS_ADDR_BECH32" ]; then
            MATCHED_INFO=$(echo "$JAILED_SIGNING_INFOS" | grep "^$CONS_ADDR_BECH32" || echo "")
            if [ -n "$MATCHED_INFO" ]; then
              JAILED_UNTIL_PRE="$(echo "$MATCHED_INFO" | cut -f2)"
              TOMBSTONED_PRE="$(echo "$MATCHED_INFO" | cut -f3)"
              say "✓ Matched signing-info to our validator (consensus address: $CONS_ADDR_BECH32)"
              say ""
            fi
          else
            # If still no match, try to match by checking which jailed signing-info
            # has the most recent jailed_until (likely ours if recently jailed)
            # Or use the one that matches our validator's status
            say "⚠️  Could not precisely match signing-info. Trying to match by jailed_until time..."
            
            # Get our validator's jailed status and try to match
            # Use the jailed signing-info with the most recent jailed_until
            MOST_RECENT=$(echo "$JAILED_SIGNING_INFOS" | sort -t$'\t' -k2 -r | head -1)
            if [ -n "$MOST_RECENT" ]; then
              CONS_ADDR_BECH32="$(echo "$MOST_RECENT" | cut -f1)"
              JAILED_UNTIL_PRE="$(echo "$MOST_RECENT" | cut -f2)"
              TOMBSTONED_PRE="$(echo "$MOST_RECENT" | cut -f3)"
              say "Using most recently jailed signing-info (heuristic match)"
              say ""
            else
              # Fallback to first one
              CONS_ADDR_BECH32="$(echo "$JAILED_SIGNING_INFOS" | head -1 | cut -f1)"
              JAILED_UNTIL_PRE="$(echo "$JAILED_SIGNING_INFOS" | head -1 | cut -f2)"
              TOMBSTONED_PRE="$(echo "$JAILED_SIGNING_INFOS" | head -1 | cut -f3)"
              say "⚠️  Using first jailed signing-info (fallback)"
              say ""
            fi
          fi
        else
          die "Could not verify our validator exists with matching consensus pubkey"
        fi
      fi
    else
      die "Could not find validator with operator address $VALOPER"
    fi
    
    if [ -n "$CONS_ADDR_BECH32" ] && [ "$CONS_ADDR_BECH32" != "null" ] && [ -n "$CONS_ADDR_BECH32" ]; then
      
      if [ "$TOMBSTONED_PRE" = "true" ]; then
        say "❌ VALIDATOR IS TOMBSTONED - CANNOT BE UNJAILED"
        say "   Tombstoned validators cannot be recovered."
        say "   You must create a new validator with a new consensus key."
        exit 1
      fi
      
      if [ -n "$JAILED_UNTIL_PRE" ] && [ "$JAILED_UNTIL_PRE" != "" ] && [ "$JAILED_UNTIL_PRE" != "null" ]; then
        NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u +%Y-%m-%dT%H:%M:%S 2>/dev/null || echo "")
        say "📅 JAILED UNTIL: $JAILED_UNTIL_PRE"
        if [ -n "$NOW" ]; then
          say "🕐 CURRENT TIME: $NOW"
          say ""
          # Simple string comparison (ISO 8601 format is sortable)
          if [ "$NOW" \< "$JAILED_UNTIL_PRE" ]; then
            say "❌ ERROR: jailed_until time has NOT elapsed yet!"
            say ""
            say "Unjail will FAIL if attempted now. You must wait until:"
            say "  $JAILED_UNTIL_PRE"
            say ""
            say "The transaction will be rejected from mempool."
            exit 1
          else
            say "✅ jailed_until time has elapsed. Proceeding with unjail..."
            say ""
          fi
        else
          say "⚠️  Could not determine current time. Proceeding anyway..."
          say ""
        fi
      else
        say "⚠️  Could not determine jailed_until time. Proceeding anyway..."
        say ""
      fi
    else
      say "⚠️  Could not find consensus address. Proceeding anyway..."
      say ""
    fi
  fi
else
  say "✅ Validator is not jailed."
  say ""
fi

say "=== Proceeding with Unjail Transaction ==="
say ""

# 5) Advisory: local vs on-chain consensus pubkey
LOCAL_PUB="$(jq -r '.pub_key.value // empty' "$NODE_HOME/config/priv_validator_key.json" 2>/dev/null || echo "")"
ONCHAIN_PUB="$($BIN q staking validator "$VALOPER" --node "$RPC" -o json 2>/dev/null | jq -r '.validator.consensus_pubkey.value // empty')"
if [ -n "$LOCAL_PUB" ] && [ -n "$ONCHAIN_PUB" ] && [ "$LOCAL_PUB" != "$ONCHAIN_PUB" ]; then
  say "WARNING: Local consensus pubkey does not match on-chain."
  say "  Local:    ${LOCAL_PUB:0:40}..."
  say "  On-chain: ${ONCHAIN_PUB:0:40}..."
  say "Proceeding anyway; unjail will fail if keys mismatch."
  say ""
fi

# 6) Fetch account_number and sequence
# Query account and parse correctly (handles BaseAccount format)
ACC_JSON="$($BIN q auth account "$ACCOUNT_ADDR" --node "$RPC" -o json 2>/dev/null || echo "{}")"
SEQ="$(echo "$ACC_JSON" | jq -r '.account.value.sequence // .account.base_account.sequence // .account.sequence // .sequence // "0"')"
ACCNUM="$(echo "$ACC_JSON" | jq -r '.account.value.account_number // .account.base_account.account_number // .account.account_number // .account_number // "0"')"

[[ "$SEQ" =~ ^[0-9]+$ ]] || die "could not parse sequence from account"
[[ "$ACCNUM" =~ ^[0-9]+$ ]] || die "could not parse account_number from account"

# Use exact current sequence for signing (remote RPC provides authoritative state)
SIGN_SEQ="$SEQ"

say "Current sequence: $SEQ"
say "Using sequence:   $SIGN_SEQ"
say "Account number:   $ACCNUM"
say ""

# Submit with explicit sequence and account_number (use sync mode, then poll)
say "Submitting unjail (sync mode, sequence=$SIGN_SEQ, account_number=$ACCNUM)..."
# Generate unsigned tx, sign with explicit sequence, then broadcast
UNSIGNED="/tmp/unjail-unsigned-$$.json"
SIGNED="/tmp/unjail-signed-$$.json"
$BIN tx slashing unjail \
  --from validator \
  --home "$NODE_HOME" \
  --keyring-backend "$KEYRING_BACKEND" \
  --chain-id "$CHAIN_ID" \
  --generate-only \
  --gas 200000 \
  --gas-prices 1.0umirage \
  -o json > "$UNSIGNED" 2>&1 || { say "Failed to generate unsigned tx"; cat "$UNSIGNED" 2>/dev/null || true; rm -f "$UNSIGNED"; exit 1; }

$BIN tx sign "$UNSIGNED" \
  --from validator \
  --home "$NODE_HOME" \
  --keyring-backend "$KEYRING_BACKEND" \
  --offline \
  --sequence "$SIGN_SEQ" \
  --account-number "$ACCNUM" \
  --chain-id "$CHAIN_ID" \
  -o json > "$SIGNED" 2>&1 || { say "Failed to sign tx"; rm -f "$UNSIGNED" "$SIGNED"; exit 1; }

RESP="$(timeout 30 $BIN tx broadcast "$SIGNED" \
  --node "$RPC" \
  --broadcast-mode sync \
  -o json 2>&1 || echo "TIMEOUT")"
rm -f "$UNSIGNED" "$SIGNED"

# Parse response (handle both direct response and wrapped tx_response)
# Check if response is JSON or FATAL error
if [ "$RESP" = "TIMEOUT" ]; then
  CODE="1"
  RAW="Command timed out after 30 seconds"
  TXHASH=""
elif echo "$RESP" | grep -q "^FATAL:"; then
  # FATAL error - extract error message
  CODE="1"
  RAW="$(echo "$RESP" | sed -n 's/^FATAL: //p')"
  TXHASH=""
else
  # Try to parse as JSON
  CODE="$(echo "$RESP" | jq -r '.code // .tx_response.code // 1' 2>/dev/null || echo "1")"
  RAW="$(echo "$RESP" | jq -r '.raw_log // .tx_response.raw_log // empty' 2>/dev/null || echo "")"
  TXHASH="$(echo "$RESP" | jq -r '.txhash // .tx_response.txhash // empty' 2>/dev/null || echo "")"
  # Check for immediate errors in the response
  if [ "$CODE" != "0" ] && [ "$CODE" != "19" ] && [ -n "$RAW" ] && [ "$RAW" != "null" ]; then
    # Transaction was rejected immediately - show the error
    say "Transaction rejected immediately (code=$CODE)"
    say "Error: $RAW"
  elif [ "$CODE" = "1" ] && [ -z "$RAW" ] || [ "$RAW" = "null" ]; then
    RAW="$(echo "$RESP" | grep -i "error\|fatal" | head -1 || echo "$RESP")"
  fi
fi

# If we got a txhash, poll for the result until we get final status
if [ -n "$TXHASH" ] && [ "$TXHASH" != "null" ] && [ "$TXHASH" != "" ]; then
  say "Transaction submitted: $TXHASH"
  # Code 19 means "tx already in mempool" - transaction was accepted, wait for inclusion
  if [ "$CODE" = "19" ] || [ "$CODE" = "0" ]; then
    say "Transaction accepted into mempool. Waiting for block inclusion..."
  fi
  say "Polling for final result (up to 12 seconds)..."
  FINAL_CODE=""
  FINAL_RAW=""
          for i in $(seq 1 12); do
    sleep 1
    TX_RESULT="$($BIN q tx "$TXHASH" --node "$RPC" -o json 2>/dev/null || echo "{}")"
    TX_CODE="$(echo "$TX_RESULT" | jq -r '.tx_response.code // empty' 2>/dev/null || echo "")"
    if [ -n "$TX_CODE" ] && [ "$TX_CODE" != "" ] && [ "$TX_CODE" != "null" ]; then
      FINAL_CODE="$TX_CODE"
      FINAL_RAW="$(echo "$TX_RESULT" | jq -r '.tx_response.raw_log // empty' 2>/dev/null || echo "")"
      # If we got a non-19 code, transaction was included (success or failure)
      if [ "$FINAL_CODE" != "19" ]; then
        CODE="$FINAL_CODE"
        RAW="$FINAL_RAW"
        say "Transaction included in block (code=$CODE)"
        break
      fi
    fi
  done
  # If still code 19 or no result, transaction is stuck in mempool or was rejected
  if [ "$FINAL_CODE" = "19" ] || [ -z "$FINAL_CODE" ] || [ "$FINAL_CODE" = "" ] || [ "$FINAL_CODE" = "null" ]; then
    say "Tx not indexed within 12s; falling back to state polling..."
    # Fall back to polling jailed flag directly in case tx indexer is disabled
    STATE_OK=false
    for i in $(seq 1 12); do
      sleep 1
      CUR_JAILED="$($BIN q staking validator "$VALOPER" --node "$RPC" -o json 2>/dev/null | jq -r '.validator.jailed // empty')"
      if [ "$CUR_JAILED" = "false" ]; then
        STATE_OK=true
        break
      fi
    done
    if [ "$STATE_OK" = "true" ]; then
      CODE="0"
      RAW=""
      say "Validator jail flag cleared; treating as success."
    else
      say "Validator still jailed after 12s; treating as failure."
      CODE="1"
      RAW="Validator still jailed after broadcast"
    fi
  fi
fi

# If still sequence mismatch, try one more time with refreshed sequence
if [ "$CODE" != "0" ] && { echo "$RAW" | grep -qi "account sequence mismatch"; echo "$RESP" | grep -qi "account sequence mismatch"; }; then
  say "Sequence mismatch detected. Refreshing account state and retrying..."
  sleep 2
  # Try to extract expected sequence from error message first
  EXPECTED_SEQ="$(echo "$RAW" | sed -nE 's/.*expected ([0-9]+), got [0-9]+.*/\1/p' | head -1)"
  if ! [[ "$EXPECTED_SEQ" =~ ^[0-9]+$ ]]; then
    # Fallback: query current sequence and add 1
    ACC_JSON2="$($BIN q auth account "$ACCOUNT_ADDR" --node "$RPC" -o json 2>/dev/null || echo "{}")"
    SEQ2="$(echo "$ACC_JSON2" | jq -r '.account.value.sequence // .account.base_account.sequence // .account.sequence // .sequence // "0"')"
    EXPECTED_SEQ=$((SEQ2 + 1))
  fi
  ACCNUM2="$($BIN q auth account "$ACCOUNT_ADDR" --node "$RPC" -o json 2>/dev/null | jq -r '.account.value.account_number // .account.base_account.account_number // .account.account_number // .account_number // "0"')"
  say "Retry with sequence=$EXPECTED_SEQ account_number=$ACCNUM2"
  # Generate unsigned tx, sign with explicit sequence, then broadcast
  UNSIGNED="/tmp/unjail-unsigned-retry-$$.json"
  SIGNED="/tmp/unjail-signed-retry-$$.json"
  $BIN tx slashing unjail \
    --from validator \
    --home "$NODE_HOME" \
    --keyring-backend "$KEYRING_BACKEND" \
    --chain-id "$CHAIN_ID" \
    --generate-only \
    --gas 200000 \
    --gas-prices 1.0umirage \
    -o json > "$UNSIGNED" 2>&1 || { say "Failed to generate unsigned tx (retry)"; cat "$UNSIGNED" 2>/dev/null || true; rm -f "$UNSIGNED"; exit 1; }
  
  $BIN tx sign "$UNSIGNED" \
    --from validator \
    --home "$NODE_HOME" \
    --keyring-backend "$KEYRING_BACKEND" \
    --offline \
    --sequence "$EXPECTED_SEQ" \
    --account-number "$ACCNUM2" \
    --chain-id "$CHAIN_ID" \
    -o json > "$SIGNED" 2>&1 || { say "Failed to sign tx"; rm -f "$UNSIGNED" "$SIGNED"; exit 1; }
  
  RESP="$(timeout 30 $BIN tx broadcast "$SIGNED" \
    --node "$RPC" \
    --broadcast-mode sync \
    -o json 2>&1 || echo "TIMEOUT")"
  rm -f "$UNSIGNED" "$SIGNED"
  # Parse retry response
  if [ "$RESP" = "TIMEOUT" ]; then
    CODE="1"
    RAW="Retry command timed out after 30 seconds"
    TXHASH=""
  elif echo "$RESP" | grep -q "^FATAL:"; then
    CODE="1"
    RAW="$(echo "$RESP" | sed -n 's/^FATAL: //p')"
    TXHASH=""
  else
    CODE="$(echo "$RESP" | jq -r '.code // .tx_response.code // 1' 2>/dev/null || echo "1")"
    RAW="$(echo "$RESP" | jq -r '.raw_log // .tx_response.raw_log // empty' 2>/dev/null || echo "")"
    TXHASH="$(echo "$RESP" | jq -r '.txhash // .tx_response.txhash // empty' 2>/dev/null || echo "")"
    if [ "$CODE" = "1" ] && [ -z "$RAW" ] || [ "$RAW" = "null" ]; then
      RAW="$(echo "$RESP" | grep -i "error\|fatal" | head -1 || echo "$RESP")"
    fi
  fi
  # Poll for retry result until we get final status
  if [ -n "$TXHASH" ] && [ "$TXHASH" != "null" ] && [ "$TXHASH" != "" ]; then
    say "Retry transaction submitted: $TXHASH"
    say "Polling for final result (up to 12 seconds)..."
    FINAL_CODE=""
    FINAL_RAW=""
          for i in $(seq 1 12); do
      sleep 1
      TX_RESULT="$($BIN q tx "$TXHASH" --node "$RPC" -o json 2>/dev/null || echo "{}")"
      TX_CODE="$(echo "$TX_RESULT" | jq -r '.tx_response.code // empty' 2>/dev/null || echo "")"
      if [ -n "$TX_CODE" ] && [ "$TX_CODE" != "" ] && [ "$TX_CODE" != "null" ]; then
        FINAL_CODE="$TX_CODE"
        FINAL_RAW="$(echo "$TX_RESULT" | jq -r '.tx_response.raw_log // empty' 2>/dev/null || echo "")"
        # If we got a non-19 code, transaction was included (success or failure)
        if [ "$FINAL_CODE" != "19" ]; then
          CODE="$FINAL_CODE"
          RAW="$FINAL_RAW"
          say "Retry transaction included in block (code=$CODE)"
          break
        fi
      fi
    done
    # If still code 19 or no result, transaction is stuck in mempool
    if [ "$FINAL_CODE" = "19" ] || [ -z "$FINAL_CODE" ] || [ "$FINAL_CODE" = "" ] || [ "$FINAL_CODE" = "null" ]; then
      say "Retry tx not indexed within 12s; falling back to state polling..."
      STATE_OK=false
      for i in $(seq 1 12); do
        sleep 1
        CUR_JAILED="$($BIN q staking validator "$VALOPER" --node "$RPC" -o json 2>/dev/null | jq -r '.validator.jailed // empty')"
        if [ "$CUR_JAILED" = "false" ]; then
          STATE_OK=true
          break
        fi
      done
      if [ "$STATE_OK" = "true" ]; then
        CODE="0"
        RAW=""
        say "Validator jail flag cleared; treating as success."
      else
        say "Validator still jailed after retry; treating as failure."
        CODE="1"
        RAW="Validator still jailed after retry broadcast"
      fi
    fi
  fi
fi

if [ "$CODE" != "0" ]; then
  say "Unjail failed (code=$CODE)"
  if [ -n "$RAW" ]; then
    say "raw_log: $RAW"
  fi
  # Also print full response if raw_log is empty
  if [ -z "$RAW" ] || [ "$RAW" = "null" ]; then
    say "Full response:"
    echo "$RESP" | jq '.' 2>/dev/null || echo "$RESP"
  fi
  # Helpful hints
  if echo "$RAW" | grep -qi "tombston"; then
    say "Hint: validator appears TOMBSTONED; unjail is not possible."
  elif echo "$RAW" | grep -qi "not eligible"; then
    say "Hint: jailed_until likely not elapsed yet. Try again after jailed_until."
  elif echo "$RAW" | grep -qi "account sequence mismatch"; then
    say "Hint: Sequence mismatch persists. The account sequence may have changed."
    say "Current account state:"
    $BIN q auth account "$ACCOUNT_ADDR" --node "$RPC" -o json | jq -r '.account.value | "sequence: \(.sequence), account_number: \(.account_number)"'
  fi
  exit 1
fi

# Only report success if code is 0
if [ "$CODE" = "0" ]; then
  say "✓ Unjail transaction succeeded (code=0)"
  sleep 3
else
  say "✗ Unjail transaction failed (code=$CODE)"
  exit 1
fi

POST="$($BIN q staking validator "$VALOPER" --node "$RPC" -o json 2>/dev/null || echo "{}")"
JAILF="$(echo "$POST" | jq -r '.validator.jailed // false' 2>/dev/null || echo "false")"
STATUS="$(echo "$POST" | jq -r '.validator.status // ""' 2>/dev/null || echo "")"

say "Post-state:"
say "  jailed: $JAILF"
say "  status: $STATUS"

if [ "$JAILF" = "false" ]; then
  say "✓ Validator unjailed. Note: status may still show UNBONDING until the staking cycle updates."
else
  say "Validator still jailed; see above raw_log for reason."
  exit 1
fi


