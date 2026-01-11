#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<EOF
Usage: list_validators.sh [--rpc=tcp://127.0.0.1:26657] [--bonded|--unbonding|--unbonded|--all]

Shows validators and their stake (tokens) in MIRAGE.
Defaults to bonded (active) validators.
EOF
}

# Defaults
ROOT_DIR="/opt/mirage"
BIN_DEFAULT="$ROOT_DIR/blockchain/miraged"
BIN="${BIN:-}"
if [ -z "${BIN:-}" ]; then
  if [ -x "$BIN_DEFAULT" ]; then
    BIN="$BIN_DEFAULT"
  elif command -v miraged >/dev/null 2>&1; then
    BIN="miraged"
  else
    echo "ERROR: miraged binary not found" >&2
    exit 1
  fi
fi

NODE_HOME="$HOME/.mirage/node"
RPC="${RPC:-tcp://127.0.0.1:26657}"
STATUS="BOND_STATUS_BONDED"  # BOND_STATUS_BONDED | BOND_STATUS_UNBONDING | BOND_STATUS_UNBONDED | (empty => all)

for arg in "$@"; do
  case "$arg" in
    --rpc=*) RPC="${arg#--rpc=}" ;;
    --bonded) STATUS="BOND_STATUS_BONDED" ;;
    --unbonding) STATUS="BOND_STATUS_UNBONDING" ;;
    --unbonded) STATUS="BOND_STATUS_UNBONDED" ;;
    --all) STATUS="" ;;
    --help|-h) usage; exit 0 ;;
    *) echo "Unknown argument: $arg" >&2; usage; exit 1 ;;
  esac
done

CMD=("$BIN" q staking validators --home "$NODE_HOME" --node "$RPC" -o json)
if [ -n "$STATUS" ]; then
  CMD+=(--status "$STATUS")
fi

JSON="$(${CMD[@]} 2>/dev/null || echo '{}')"
if ! echo "$JSON" | jq -e '.validators' >/dev/null 2>&1; then
  echo "ERROR: unable to query validators from $RPC" >&2
  exit 1
fi

# Extract to TSV: operator\tmoniker\ttokens\tjailed\tstatus
TSV=$(echo "$JSON" | jq -r '.validators[]? | [(.operator_address // ""), (.description.moniker // ""), (.tokens // "0"), (.jailed // false), (.status // "")] | @tsv')

if [ -z "$TSV" ]; then
  echo "No validators found."
  exit 0
fi

# Sort by tokens desc and print formatted table
printf "%-60s | %-24s | %14s | %-6s | %-20s\n" "Operator" "Moniker" "Stake (MIRAGE)" "Jailed" "Status"
printf "%-60s-+-%-24s-+-%14s-+-%-6s-+-%-20s\n" "------------------------------------------------------------" "------------------------" "--------------" "------" "--------------------"

echo "$TSV" | sort -t $'\t' -k3,3nr | awk -F '\t' '
  BEGIN { OFS=" | " }
  {
    operator=$1; moniker=$2; tokens=$3; jailed=$4; status=$5;
    mirage=tokens/1000000.0;
    printf "%-60s | %-24s | %14.6f | %-6s | %-20s\n", operator, moniker, mirage, jailed, status;
  }
'
