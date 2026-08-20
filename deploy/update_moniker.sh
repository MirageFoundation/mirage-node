#!/usr/bin/env bash
# Point this validator's on-chain moniker at the address it serves.
#
# The moniker is not decoration: /network builds its list of browsable nodes from
# the bonded validator set, so a node whose moniker is a label rather than an
# address has nowhere for a visitor to go and is left out of the list entirely.
#
# This used to be an escaped one-liner inside deploy.sh that sent the transaction
# with no fee and ended in `|| true`. Every run was rejected for insufficient fee
# and every rejection was discarded, so two nodes kept their install-time labels
# for months while the deploy reported success. Hence: the fee comes from the
# node's own configured minimum, a non-zero broadcast code is fatal, and the
# chain is polled until it actually shows the new moniker.
set -euo pipefail

MIRAGED=/opt/mirage/blockchain/bin/miraged
NODE_HOME=/root/.mirage/node
NODE_RPC=tcp://127.0.0.1:26657
WANTED="${NEW_MONIKER:-}"

if [ -z "$WANTED" ]; then
  echo "ERROR: NEW_MONIKER not set" >&2
  exit 1
fi

VALOPER=$("$MIRAGED" keys show validator --home "$NODE_HOME" --keyring-backend test --bech val -a 2>/dev/null || echo "")
if [ -z "$VALOPER" ]; then
  echo "Validator key not present, skipping moniker update"
  exit 0
fi

current_moniker() {
  "$MIRAGED" q staking validator "$VALOPER" --home "$NODE_HOME" --node "$NODE_RPC" -o json 2>/dev/null |
    jq -r '.validator.description.moniker // ""'
}

CURRENT=$(current_moniker)
if [ "$CURRENT" = "$WANTED" ]; then
  echo "Validator moniker already \"$WANTED\""
  exit 0
fi

GAS_PRICES=$(sed -n 's/^minimum-gas-prices = "\(.*\)"/\1/p' "$NODE_HOME/config/app.toml" | head -1)
if [ -z "$GAS_PRICES" ]; then
  echo "ERROR: minimum-gas-prices missing from $NODE_HOME/config/app.toml" >&2
  exit 1
fi

echo "Updating validator moniker from \"$CURRENT\" to \"$WANTED\" (gas price $GAS_PRICES)"
OUT=$("$MIRAGED" tx staking edit-validator \
  --new-moniker="$WANTED" \
  --from validator --home "$NODE_HOME" --keyring-backend test \
  --chain-id mirage-1 --node "$NODE_RPC" \
  --gas auto --gas-adjustment 1.5 --gas-prices "$GAS_PRICES" \
  --broadcast-mode sync -y -o json 2>&1)

JSON=$(printf '%s\n' "$OUT" | sed -n '/^{/{p;q;}')
if [ -z "$JSON" ]; then
  echo "ERROR: moniker update returned no transaction response:" >&2
  printf '%s\n' "$OUT" >&2
  exit 1
fi

CODE=$(printf '%s' "$JSON" | jq -r '.code // empty')
if [ "$CODE" != "0" ]; then
  echo "ERROR: moniker update rejected (code=$CODE): $JSON" >&2
  exit 1
fi

# Accepted into the mempool is not the same as committed, and the whole point of
# this script is that a moniker which silently failed to change looks identical
# to one that never needed changing. Confirm against the chain, on a budget.
for _ in $(seq 1 15); do
  sleep 2
  if [ "$(current_moniker)" = "$WANTED" ]; then
    echo "Validator moniker now \"$WANTED\""
    exit 0
  fi
done

echo "ERROR: moniker still \"$(current_moniker)\" 30s after broadcasting $(printf '%s' "$JSON" | jq -r '.txhash')" >&2
exit 1
