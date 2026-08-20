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

UNJAIL_POLL_SECONDS="${UNJAIL_POLL_SECONDS:-60}"
[[ "$UNJAIL_POLL_SECONDS" =~ ^[1-9][0-9]*$ ]] || die "UNJAIL_POLL_SECONDS must be a positive integer"

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

# 3) Check whether we are jailed, and if so on what terms
say "=== Checking Validator Status ==="
VAL_INFO_PRE="$($BIN q staking validator "$VALOPER" --node "$RPC" -o json 2>/dev/null || echo "{}")"
JAILED_PRE="$(echo "$VAL_INFO_PRE" | jq -r '.validator.jailed // false')"

if [ "$JAILED_PRE" != "true" ]; then
  say "Validator is not jailed. Nothing to do."
  exit 0
fi

say ""
say "Validator is JAILED."
say ""

# Look the signing info up by this validator's own consensus pubkey, which the
# slashing query accepts in place of an address. What was here before listed
# every jailed signing-info on the chain and guessed which one was ours (the
# most recent jailed_until, else the first), so with more than one validator
# jailed it could read another operator's jail time and refuse an unjail that
# was in fact due -- exactly when a fleet-wide outage makes this script needed.
CONS_TYPE="$(echo "$VAL_INFO_PRE" | jq -r '.validator.consensus_pubkey.type // empty')"
CONS_KEY="$(echo "$VAL_INFO_PRE" | jq -r '.validator.consensus_pubkey.value // empty')"
if [ -z "$CONS_TYPE" ] || [ -z "$CONS_KEY" ]; then
  die "could not read the consensus pubkey of $VALOPER"
fi
CONS_PUB_JSON="$(jq -cn --arg t "$CONS_TYPE" --arg k "$CONS_KEY" '{"@type":$t,key:$k}')"

SIGN_INFO="$($BIN q slashing signing-info "$CONS_PUB_JSON" --node "$RPC" -o json 2>/dev/null || echo "{}")"
CONS_ADDR_BECH32="$(echo "$SIGN_INFO" | jq -r '.val_signing_info.address // empty')"
if [ -z "$CONS_ADDR_BECH32" ]; then
  die "no signing info for $VALOPER on $RPC; cannot tell whether unjail is allowed"
fi
# Both are omitted from the response when unset, being proto3 defaults.
TOMBSTONED_PRE="$(echo "$SIGN_INFO" | jq -r '.val_signing_info.tombstoned // false')"
JAILED_UNTIL_PRE="$(echo "$SIGN_INFO" | jq -r '.val_signing_info.jailed_until // empty')"

say "Consensus address: $CONS_ADDR_BECH32"
say "Jailed until:      ${JAILED_UNTIL_PRE:-<unset>}"
say "Tombstoned:        $TOMBSTONED_PRE"
say ""

if [ "$TOMBSTONED_PRE" = "true" ]; then
  say "Validator is TOMBSTONED and cannot be unjailed."
  say "Tombstoning is permanent: recovery needs a new validator with a new consensus key."
  exit 1
fi

if [ -n "$JAILED_UNTIL_PRE" ]; then
  NOW="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  # Both timestamps are ISO 8601 in UTC, which orders lexicographically.
  if [ "$NOW" \< "$JAILED_UNTIL_PRE" ]; then
    say "The jail period has not elapsed yet, so unjail would be rejected."
    say "  now:          $NOW"
    say "  jailed until: $JAILED_UNTIL_PRE"
    exit 1
  fi
  say "Jail period elapsed at $JAILED_UNTIL_PRE."
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
# Generate unsigned tx, sign with explicit sequence, then broadcast.
# Keep stderr separate (miraged emits "core/types: registered msg interfaces" on stderr
# at startup, which contaminates the JSON output file if merged via 2>&1).
UNSIGNED="/tmp/unjail-unsigned-$$.json"
SIGNED="/tmp/unjail-signed-$$.json"
GEN_ERR="/tmp/unjail-gen-err-$$.log"
SIGN_ERR="/tmp/unjail-sign-err-$$.log"
$BIN tx slashing unjail \
  --from validator \
  --home "$NODE_HOME" \
  --keyring-backend "$KEYRING_BACKEND" \
  --chain-id "$CHAIN_ID" \
  --generate-only \
  --gas 200000 \
  --fees 1000000000umirage \
  -o json > "$UNSIGNED" 2>"$GEN_ERR" || { say "Failed to generate unsigned tx"; cat "$GEN_ERR" 2>/dev/null || true; rm -f "$UNSIGNED" "$GEN_ERR"; exit 1; }
rm -f "$GEN_ERR"

$BIN tx sign "$UNSIGNED" \
  --from validator \
  --home "$NODE_HOME" \
  --keyring-backend "$KEYRING_BACKEND" \
  --offline \
  --sequence "$SIGN_SEQ" \
  --account-number "$ACCNUM" \
  --chain-id "$CHAIN_ID" \
  -o json > "$SIGNED" 2>"$SIGN_ERR" || { say "Failed to sign tx"; cat "$SIGN_ERR" 2>/dev/null || true; rm -f "$UNSIGNED" "$SIGNED" "$SIGN_ERR"; exit 1; }
rm -f "$SIGN_ERR"

RESP="$(timeout 30 $BIN tx broadcast "$SIGNED" \
  --node "$RPC" \
  --broadcast-mode sync \
  -o json 2>/dev/null || echo "TIMEOUT")"
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

# Poll jailed flag directly (no tx index dependency).
# UNJAIL_POLL_SECONDS controls the budget. 60s = 10 blocks at 6s each, enough
# for normal mempool-to-block propagation on this chain.
if { [ "$CODE" = "0" ] || [ "$CODE" = "19" ]; } && [ -n "$TXHASH" ] && [ "$TXHASH" != "null" ] && [ "$TXHASH" != "" ]; then
  say "Transaction submitted: $TXHASH"
  say "Transaction accepted into mempool. Waiting for block inclusion (up to ${UNJAIL_POLL_SECONDS}s)..."
  POLL_OUTCOME="pending"
  for i in $(seq 1 "$UNJAIL_POLL_SECONDS"); do
    sleep 1
    CUR_JAILED="$($BIN q staking validator "$VALOPER" --node "$RPC" -o json 2>/dev/null | jq -r '.validator.jailed // empty')"
    if [ "$CUR_JAILED" = "false" ]; then
      POLL_OUTCOME="success"
      break
    fi
  done
  case "$POLL_OUTCOME" in
    success)
      CODE="0"
      RAW=""
      say "Validator jail flag cleared; treating as success."
      ;;
    pending)
      say ""
      say "Transaction $TXHASH was accepted into the mempool but jail flag has not cleared after ${UNJAIL_POLL_SECONDS}s."
      say "Possible causes: block inclusion is still pending, the mempool dropped the tx, or this RPC has not observed the post-unjail state yet."
      say "Verify manually after a few more blocks:"
      say "  $BIN q staking validator $VALOPER --node $RPC -o json | jq .validator.jailed"
      say ""
      say "Exiting 0 (tx was accepted; on-chain confirmation may still be propagating)."
      exit 0
      ;;
  esac
fi

# If still sequence mismatch, try one more time with refreshed sequence
if [ "$CODE" != "0" ] && { echo "$RAW" | grep -qi "account sequence mismatch" || echo "$RESP" | grep -qi "account sequence mismatch"; }; then
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
  # Generate unsigned tx, sign with explicit sequence, then broadcast.
  # Keep stderr separate (see above).
  UNSIGNED="/tmp/unjail-unsigned-retry-$$.json"
  SIGNED="/tmp/unjail-signed-retry-$$.json"
  GEN_ERR="/tmp/unjail-gen-err-retry-$$.log"
  SIGN_ERR="/tmp/unjail-sign-err-retry-$$.log"
  $BIN tx slashing unjail \
    --from validator \
    --home "$NODE_HOME" \
    --keyring-backend "$KEYRING_BACKEND" \
    --chain-id "$CHAIN_ID" \
    --generate-only \
    --gas 200000 \
    --fees 1000000000umirage \
    -o json > "$UNSIGNED" 2>"$GEN_ERR" || { say "Failed to generate unsigned tx (retry)"; cat "$GEN_ERR" 2>/dev/null || true; rm -f "$UNSIGNED" "$GEN_ERR"; exit 1; }
  rm -f "$GEN_ERR"

  $BIN tx sign "$UNSIGNED" \
    --from validator \
    --home "$NODE_HOME" \
    --keyring-backend "$KEYRING_BACKEND" \
    --offline \
    --sequence "$EXPECTED_SEQ" \
    --account-number "$ACCNUM2" \
    --chain-id "$CHAIN_ID" \
    -o json > "$SIGNED" 2>"$SIGN_ERR" || { say "Failed to sign tx"; cat "$SIGN_ERR" 2>/dev/null || true; rm -f "$UNSIGNED" "$SIGNED" "$SIGN_ERR"; exit 1; }
  rm -f "$SIGN_ERR"

  RESP="$(timeout 30 $BIN tx broadcast "$SIGNED" \
    --node "$RPC" \
    --broadcast-mode sync \
    -o json 2>/dev/null || echo "TIMEOUT")"
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
  # Same validator-state polling logic as the initial broadcast.
  if { [ "$CODE" = "0" ] || [ "$CODE" = "19" ]; } && [ -n "$TXHASH" ] && [ "$TXHASH" != "null" ] && [ "$TXHASH" != "" ]; then
    say "Retry transaction submitted: $TXHASH"
    say "Polling validator state (up to ${UNJAIL_POLL_SECONDS}s)..."
    POLL_OUTCOME="pending"
    for i in $(seq 1 "$UNJAIL_POLL_SECONDS"); do
      sleep 1
      CUR_JAILED="$($BIN q staking validator "$VALOPER" --node "$RPC" -o json 2>/dev/null | jq -r '.validator.jailed // empty')"
      if [ "$CUR_JAILED" = "false" ]; then
        POLL_OUTCOME="success"
        break
      fi
    done
    case "$POLL_OUTCOME" in
      success)
        CODE="0"
        RAW=""
        say "Validator jail flag cleared; treating as success."
        ;;
      pending)
        say ""
        say "Retry transaction $TXHASH was accepted into the mempool but jail flag has not cleared after ${UNJAIL_POLL_SECONDS}s."
        say "Possible causes: block inclusion is still pending, the mempool dropped the tx, or this RPC has not observed the post-unjail state yet."
        say "Verify manually after a few more blocks:"
        say "  $BIN q staking validator $VALOPER --node $RPC -o json | jq .validator.jailed"
        say ""
        say "Exiting 0 (tx was accepted; on-chain confirmation may still be propagating)."
        exit 0
        ;;
    esac
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


