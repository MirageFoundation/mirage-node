#!/usr/bin/env bash
# Hold Caddy maintenance until Gunicorn answers, then lift it once.
set -euo pipefail

BACKEND_WAIT_SECONDS="${CHAIN_STARTUP_GRACE_SECONDS:-1800}"
echo "==> Waiting for backend to become available (up to ${BACKEND_WAIT_SECONDS}s)..."
BACKEND_READY=0
BACKEND_WAITED=0
while [ "$BACKEND_WAITED" -lt "$BACKEND_WAIT_SECONDS" ]; do
  if curl -sf --max-time 1 http://127.0.0.1:5000/api/get_node_config >/dev/null 2>&1; then
    BACKEND_READY=1
    echo "✓ Backend is ready after ${BACKEND_WAITED}s"
    break
  fi
  sleep 5
  BACKEND_WAITED=$((BACKEND_WAITED + 5))
  if [ $((BACKEND_WAITED % 60)) -eq 0 ]; then
    echo "    backend still starting (${BACKEND_WAITED}s elapsed; maintenance mode held)"
  fi
done

if [ "$BACKEND_READY" -eq 0 ]; then
  echo "ERROR: Backend not ready after ${BACKEND_WAIT_SECONDS}s" >&2
  exit 1
fi

rm -f /etc/caddy/.maintenance
echo "✓ Maintenance mode disabled"
# Stay alive so Supervisor does not treat a one-shot success as a flap if
# autorestart is later changed. SIGTERM from Supervisor ends the wait.
exec sleep infinity
