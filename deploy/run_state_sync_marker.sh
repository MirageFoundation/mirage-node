#!/usr/bin/env bash
# Bounded watcher: once state sync installs a non-zero height, later restarts
# no longer derive remote trust.
set -euo pipefail

DATA_DIR="${HOME}/.mirage"

if [ "${SKIP_PEERS:-0}" = "1" ] || [ -f "$DATA_DIR/.state_sync_complete" ]; then
  exit 0
fi

for _ in $(seq 1 8640); do
  if STATUS_JSON="$(curl -fsS --max-time 3 http://127.0.0.1:26657/status)" &&
     HEIGHT="$(printf '%s' "$STATUS_JSON" | python3 -c 'import json, sys; print(int(json.load(sys.stdin)["result"]["sync_info"]["latest_block_height"]))')" &&
     [ "$HEIGHT" -gt 0 ]; then
    touch "$DATA_DIR/.state_sync_complete.tmp"
    mv "$DATA_DIR/.state_sync_complete.tmp" "$DATA_DIR/.state_sync_complete"
    echo "✓ State sync installed block height $HEIGHT"
    exit 0
  fi
  sleep 10
done
echo "ERROR: state sync did not install a non-zero height within 24 hours" >&2
exit 1
