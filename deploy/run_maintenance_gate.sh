#!/usr/bin/env bash
# Hold Caddy maintenance until Gunicorn answers, then lift it once.
set -euo pipefail

# A node joining by state sync lands thousands of blocks behind head and the
# backend answers 503 for the whole catch-up, which can take hours. A wall
# clock budget gives up in the middle of a healthy sync and, with
# autorestart=false, leaves the maintenance page up forever. So the deadline
# follows block progress: a node that is still advancing keeps the page as long
# as it needs, a node that has genuinely stalled still fails here.
STALL_SECONDS="${CHAIN_STARTUP_GRACE_SECONDS:-1800}"

node_height() {
  curl -sf --max-time 2 http://127.0.0.1:26657/status 2>/dev/null |
    python3 -c 'import json,sys; print(json.load(sys.stdin)["result"]["sync_info"]["latest_block_height"])' 2>/dev/null ||
    true
}

echo "==> Waiting for backend to become available (stall limit ${STALL_SECONDS}s)..."
last_height=""
stalled_for=0
elapsed=0
while true; do
  if curl -sf --max-time 1 http://127.0.0.1:5000/api/get_node_config >/dev/null 2>&1; then
    echo "✓ Backend is ready after ${elapsed}s"
    break
  fi

  height="$(node_height)"
  if [ -n "$height" ] && [ "$height" != "$last_height" ]; then
    last_height="$height"
    stalled_for=0
  fi

  if [ "$stalled_for" -ge "$STALL_SECONDS" ]; then
    echo "ERROR: backend unavailable and the chain has not advanced for ${STALL_SECONDS}s (height ${last_height:-unknown})" >&2
    exit 1
  fi

  sleep 5
  stalled_for=$((stalled_for + 5))
  elapsed=$((elapsed + 5))
  if [ $((elapsed % 60)) -eq 0 ]; then
    echo "    backend still starting (${elapsed}s elapsed, height ${last_height:-unknown}; maintenance mode held)"
  fi
done

rm -f /etc/caddy/.maintenance
echo "✓ Maintenance mode disabled"
# Stay alive so Supervisor does not treat a one-shot success as a flap if
# autorestart is later changed. SIGTERM from Supervisor ends the wait.
exec sleep infinity
