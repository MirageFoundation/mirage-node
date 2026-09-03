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

QUERY_ERR=$(mktemp)
trap 'rm -f "$QUERY_ERR"' EXIT

# Prints the on-chain moniker, or fails when the query could not answer at all.
# Those are different outcomes and only the caller knows which one is fatal: a
# query that cannot reach the node must never be read as "the moniker differs".
current_moniker() {
  local out
  out=$("$MIRAGED" q staking validator "$VALOPER" --home "$NODE_HOME" --node "$NODE_RPC" -o json 2>"$QUERY_ERR") || return 1
  printf '%s' "$out" | jq -r '.validator.description.moniker // ""'
}

# The container accepts `docker exec` several seconds before the node's RPC
# starts serving, so this runs against a closed port on every deploy that
# restarts the node. That used to end the deploy in silence: the query's stderr
# went to /dev/null and `set -e` killed the script from inside the command
# substitution, so deploy.sh exited 1 printing nothing and the fleet loop
# abandoned every host after this one, production included. Exhaustion is
# checked after the loop rather than in it, because an unanswered query leaves
# CURRENT empty, which is indistinguishable from a moniker that differs, and
# broadcasting on that would edit the validator off a reading we never got.
CURRENT=""
ANSWERED=0
for _ in $(seq 1 30); do
  if CURRENT=$(current_moniker); then
    ANSWERED=1
    break
  fi
  sleep 2
done

if [ "$ANSWERED" -ne 1 ]; then
  echo "ERROR: validator query on $NODE_RPC still failing 60s after container start:" >&2
  cat "$QUERY_ERR" >&2
  exit 1
fi

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
  if [ "$(current_moniker || true)" = "$WANTED" ]; then
    echo "Validator moniker now \"$WANTED\""
    exit 0
  fi
done

echo "ERROR: moniker still \"$(current_moniker || echo '?')\" 30s after broadcasting $(printf '%s' "$JSON" | jq -r '.txhash')" >&2
exit 1
