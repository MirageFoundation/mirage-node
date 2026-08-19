#!/usr/bin/env bash
# After RPC is up, restore validator key material without restarting miraged.
set -euo pipefail

ROOT_DIR="${ROOT_DIR:-/opt/mirage}"
NODE_HOME="${HOME}/.mirage/node"

if [ ! -f "$NODE_HOME/config/priv_validator_key.json" ]; then
  echo "==> No validator key; skipping validator-mode enable"
  exit 0
fi

echo "==> Waiting for node RPC before enabling validator mode..."
RPC_READY=0
for _ in $(seq 1 1800); do
  if curl -sf --max-time 2 http://127.0.0.1:26657/status >/dev/null 2>&1; then
    RPC_READY=1
    break
  fi
  sleep 1
done
if [ "$RPC_READY" -eq 0 ]; then
  echo "ERROR: node RPC not ready; cannot enable validator mode" >&2
  exit 1
fi

echo "==> Enabling validator mode..."
bash "$ROOT_DIR/deploy/enable_validator_mode.sh"
exit 0
