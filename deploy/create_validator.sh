#!/usr/bin/env bash
set -euo pipefail

# Create validator on-chain if it doesn't exist yet (idempotent).
# The last STATE= line is the outcome; callers read that. Catching-up is
# STATE=syncing / exit 0 so a systemd timer can retry without looking crashed.

ROOT_DIR="${ROOT_DIR:-/opt/mirage}"
NODE_HOME="${NODE_HOME:-/root/.mirage/node}"
BIN="${BIN:-$ROOT_DIR/blockchain/bin/miraged}"
RPC_URL="${RPC_URL:-http://127.0.0.1:26657}"
CHAIN_ID="${CHAIN_ID:-mirage-1}"
KEYRING_BACKEND="${KEYRING_BACKEND:-test}"
NETWORK_MANIFEST="${NETWORK_MANIFEST:-}"

emit() {
  echo "STATE=$1"
}

# Every failure path has to reach the caller as a STATE= line on stdout, so
# helpers report to stderr and return non-zero: a die_state inside $( ) would
# have its STATE line captured by the substitution and never printed.
die_state() {
  echo "$*" >&2
  emit error
  exit 1
}

find_manifest() {
  local f
  for f in \
    "$NETWORK_MANIFEST" \
    /root/.mirage/env/network-manifest.json \
    /opt/mirage/release/network.json
  do
    if [[ -n "$f" && -f "$f" ]]; then
      echo "$f"
      return 0
    fi
  done
  echo "ERROR: network manifest not found (installer must drop ~/.mirage/env/network-manifest.json)" >&2
  return 1
}

load_min_gas_price() {
  local path="$NODE_HOME/config/app.toml"
  if [[ ! -f "$path" ]]; then
    echo "ERROR: app.toml not found: $path" >&2
    return 1
  fi
  local raw line value part number
  local -a parts
  while IFS= read -r raw; do
    line=${raw%%#*}
    line=${line#"${line%%[![:space:]]*}"}
    [[ "$line" == minimum-gas-prices* ]] || continue
    value=${line#*=}
    value=${value//\"/}
    value=${value//\'/}
    value=${value// /}
    IFS=',' read -ra parts <<<"$value"
    for part in "${parts[@]}"; do
      if [[ "$part" == *umirage ]]; then
        number=${part%umirage}
        if [[ ! "$number" =~ ^[0-9]*\.?[0-9]+$ ]]; then
          echo "ERROR: invalid umirage minimum-gas-prices in $path: $part" >&2
          return 1
        fi
        echo "$number"
        return 0
      fi
    done
  done < "$path"
  echo "ERROR: minimum-gas-prices missing umirage in $path" >&2
  return 1
}

MANIFEST=$(find_manifest) || die_state "ERROR: cannot read the network manifest"
SELF_DELEGATION=$(jq -r '.self_delegation_umirage' "$MANIFEST")
if [[ -z "$SELF_DELEGATION" || "$SELF_DELEGATION" == "null" ]]; then
  die_state "ERROR: self_delegation_umirage missing from $MANIFEST"
fi
# A min-self-delegation equal to the initial stake would unbond the validator
# permanently on the first slash of any size. The floor is a token amount; the
# real economic requirement is enforced by the installer and stake.py.
MIN_SELF="1000000"

MONIKER="${MONIKER:-}"
if [[ -z "$MONIKER" && -f /root/.mirage/env/node.env ]]; then
  MONIKER=$(grep -E '^MONIKER=' /root/.mirage/env/node.env | cut -d= -f2- | tr -d '"' | tr -d "'" || true)
fi
MONIKER="${MONIKER:-validator}"

echo "==> Ensuring validator exists on-chain..."
echo "   Node home: $NODE_HOME"
echo "   Moniker: $MONIKER"
echo "   RPC: $RPC_URL"
echo "   Self-delegation: ${SELF_DELEGATION}umirage"

if ! curl -sf --max-time 5 "$RPC_URL/status" >/dev/null 2>&1; then
  echo "==> RPC not ready"
  emit waiting_for_rpc
  exit 0
fi

STATUS=$(curl -sf --max-time 5 "$RPC_URL/status" || echo "")
CATCHING_UP=$(echo "$STATUS" | jq -r 'if .result.sync_info.catching_up == null then "true" else (.result.sync_info.catching_up | tostring) end' 2>/dev/null || echo "true")
if [[ "$CATCHING_UP" != "false" ]]; then
  LATEST_HEIGHT=$(echo "$STATUS" | jq -r '.result.sync_info.latest_block_height // "unknown"' 2>/dev/null || echo "unknown")
  echo "==> Node is still catching up (height: $LATEST_HEIGHT)"
  emit syncing
  exit 0
fi
echo "✓ Node is synced"

if [[ ! -f "$NODE_HOME/config/priv_validator_key.json" ]]; then
  die_state "ERROR: Consensus key file not found: $NODE_HOME/config/priv_validator_key.json"
fi

if ! PUB_KEY_VALUE=$(jq -er '.pub_key.value | select(type == "string" and length > 0)' "$NODE_HOME/config/priv_validator_key.json"); then
  die_state "ERROR: Failed to read pubkey from priv_validator_key.json"
fi
PUB_JSON=$(jq -n --arg key "$PUB_KEY_VALUE" '{"@type":"/cosmos.crypto.ed25519.PubKey","key":$key}')
PUB="$PUB_KEY_VALUE"

if ! $BIN keys show validator --home "$NODE_HOME" --keyring-backend "$KEYRING_BACKEND" >/dev/null 2>&1; then
  die_state "ERROR: Validator account key not found in keyring"
fi

# Ask about this operator address specifically. Scanning `q staking validators`
# only sees the first page, so on a network with more validators than one page
# an already-registered node would try to register again.
if ! VALOPER=$($BIN keys show validator --home "$NODE_HOME" --keyring-backend "$KEYRING_BACKEND" --bech val -a); then
  die_state "ERROR: could not derive the operator address from the validator key"
fi
if [[ -z "$VALOPER" ]]; then
  die_state "ERROR: could not derive the operator address from the validator key"
fi

# Empty output means "no such validator". A query that fails for any other
# reason returns non-zero rather than reporting the node unregistered, which
# would submit a create-validator that the chain charges gas to reject.
registered_pubkey() {
  local out rc=0
  out=$($BIN q staking validator "$VALOPER" --home "$NODE_HOME" --node tcp://127.0.0.1:26657 -o json 2>&1) || rc=$?
  if (( rc != 0 )); then
    if echo "$out" | grep -qiE 'not found|does not exist'; then
      return 0
    fi
    echo "ERROR: validator query failed: $out" >&2
    return 1
  fi
  echo "$out" | jq -r '((.validator // .).consensus_pubkey // {}) | (.value // .key // "")'
}

ONCHAIN_PUB=$(registered_pubkey) || die_state "ERROR: cannot determine whether $VALOPER is already registered"
if [[ -n "$ONCHAIN_PUB" ]]; then
  if [[ "$ONCHAIN_PUB" == "$PUB" ]]; then
    echo "✓ Validator already exists: $VALOPER"
    emit registered
    exit 0
  fi
  die_state "ERROR: $VALOPER is already a validator with a different consensus key; migrate the existing node instead of registering a second one"
fi

GAS_PRICE=$(load_min_gas_price) || die_state "ERROR: cannot determine the node gas price"

VAL_JSON=$(mktemp)
TX_OUT=$(mktemp)
trap 'rm -f "$VAL_JSON" "$TX_OUT"' EXIT
jq -n \
  --argjson pubkey "$PUB_JSON" \
  --arg amount "${SELF_DELEGATION}umirage" \
  --arg moniker "$MONIKER" \
  --arg min_self "$MIN_SELF" \
  '{
    pubkey: $pubkey,
    amount: $amount,
    moniker: $moniker,
    identity: "",
    website: "",
    security: "",
    details: "",
    "commission-rate": "1.0",
    "commission-max-rate": "1.0",
    "commission-max-change-rate": "0.0",
    "min-self-delegation": $min_self
  }' >"$VAL_JSON"

echo "==> Submitting create-validator transaction..."
emit submitting
set +e
$BIN tx staking create-validator "$VAL_JSON" \
  --from validator \
  --keyring-backend "$KEYRING_BACKEND" \
  --chain-id "$CHAIN_ID" \
  --home "$NODE_HOME" \
  --node tcp://127.0.0.1:26657 \
  --unordered --timeout-duration 2m \
  --broadcast-mode sync \
  --gas auto --gas-adjustment 1.3 --gas-prices "${GAS_PRICE}umirage" \
  -o json -y >"$TX_OUT" 2>&1
RC=$?
set -e

echo ""
echo "---- Transaction Output ----"
cat "$TX_OUT"
echo "----------------------------"
echo ""

if [[ "$RC" -ne 0 ]]; then
  die_state "ERROR: create-validator tx failed (exit $RC)"
fi
TX_CODE=$(jq -r '.code // 0' "$TX_OUT")
if [[ "$TX_CODE" != "0" ]]; then
  TX_LOG=$(jq -r '.raw_log // .log // "unknown CheckTx error"' "$TX_OUT")
  die_state "ERROR: create-validator CheckTx rejected code=$TX_CODE: $TX_LOG"
fi

TXHASH=$(jq -r '.txhash // ""' "$TX_OUT")

for i in $(seq 1 60); do
  if ! ONCHAIN_PUB=$(registered_pubkey); then
    die_state "ERROR: validator query failed while waiting for registration"
  fi
  if [[ "$ONCHAIN_PUB" == "$PUB" ]]; then
    echo "✓ Validator registered: $VALOPER"
    emit registered
    exit 0
  fi
  sleep 1
done

die_state "ERROR: Validator not visible in validator set after 60 seconds (txhash=${TXHASH:-unknown})"
