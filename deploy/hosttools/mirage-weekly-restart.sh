#!/usr/bin/env bash
# Weekly container restart that no-ops if an upgrade plan is within 500 blocks.
set -euo pipefail
SAFETY_BLOCKS="${UPGRADE_PREFLIGHT_SAFETY_BLOCKS:-500}"

if ! docker inspect mirage --format '{{.State.Status}}' 2>/dev/null | grep -qx running; then
  echo "ERROR: mirage container is not running; weekly restart cannot proceed" >&2
  exit 1
fi

status=$(curl -fsS --max-time 5 http://127.0.0.1:26657/status)
catching=$(echo "$status" | python3 -c 'import json,sys; print(json.load(sys.stdin)["result"]["sync_info"]["catching_up"])')
if [[ "$catching" != "True" && "$catching" != "true" && "$catching" != "False" && "$catching" != "false" ]]; then
  echo "ERROR: unexpected catching_up from RPC: $catching" >&2
  exit 1
fi
if [[ "$catching" == "True" || "$catching" == "true" ]]; then
  echo "node is catching up; skipping weekly restart"
  exit 0
fi

plan=$(curl -fsS --max-time 5 http://127.0.0.1:1317/cosmos/upgrade/v1beta1/current_plan)
plan_name=$(echo "$plan" | python3 -c 'import json,sys; p=json.load(sys.stdin).get("plan") or {}; print(p.get("name") or "")')
if [[ -n "$plan_name" ]]; then
  plan_h=$(echo "$plan" | python3 -c 'import json,sys; p=json.load(sys.stdin).get("plan") or {}; print(int(p.get("height") or 0))')
  height=$(echo "$status" | python3 -c 'import json,sys; print(int(json.load(sys.stdin)["result"]["sync_info"]["latest_block_height"]))')
  remaining=$((plan_h - height))
  if (( remaining >= 0 && remaining <= SAFETY_BLOCKS )); then
    echo "upgrade plan $plan_name in $remaining blocks; skipping weekly restart"
    exit 0
  fi
fi

exec /usr/bin/docker restart mirage
