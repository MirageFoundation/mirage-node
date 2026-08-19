#!/usr/bin/env bash
# Wait for local RPC, then run Gunicorn in the foreground.
set -euo pipefail

ROOT_DIR="${ROOT_DIR:-/opt/mirage}"
BACKEND_HOST="${BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${BACKEND_PORT:-5000}"

echo "==> backend: waiting for node RPC..."
RPC_READY=0
for _ in $(seq 1 1800); do
  if curl -sf --max-time 2 http://127.0.0.1:26657/status >/dev/null 2>&1; then
    RPC_READY=1
    break
  fi
  sleep 1
done
if [ "$RPC_READY" -eq 0 ]; then
  echo "ERROR: node RPC not ready after 1800s; not starting backend" >&2
  exit 1
fi

cd "$ROOT_DIR/web/backend"
exec env BACKEND_HOST="$BACKEND_HOST" BACKEND_PORT="$BACKEND_PORT" PYTHONPATH="$ROOT_DIR" \
  python3 -m gunicorn -c gunicorn_config.py 'factory:app'
