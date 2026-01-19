#!/usr/bin/env bash
set -euo pipefail

# Sync backend/shared/indexer/scripts/referrals code into the local Docker container
# and restart services in-place inside the tmux session (no frontend build/copy).
#
# Defaults:
#   CONTAINER_NAME=mirage
#   ROOT_DIR=/opt/mirage
#   BACKEND_PANE=mirage:backend
#   INDEXER_PANE=mirage:indexer
#   NODE_PANE=mirage:node
#   RELOAD_CADDY=1
#   RESTART_NODE=0
#
# Usage:
#   ./scripts/sync_local_docker_runtime.sh
#   CONTAINER_NAME=my-mirage ./scripts/sync_local_docker_runtime.sh
#   RESTART_NODE=1 ./scripts/sync_local_docker_runtime.sh

CONTAINER_NAME="${CONTAINER_NAME:-mirage}"
ROOT_DIR="${ROOT_DIR:-/opt/mirage}"

BACKEND_PANE="${BACKEND_PANE:-mirage:backend}"
INDEXER_PANE="${INDEXER_PANE:-mirage:indexer}"
NODE_PANE="${NODE_PANE:-mirage:node}"

RELOAD_CADDY="${RELOAD_CADDY:-1}"
RESTART_NODE="${RESTART_NODE:-0}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

NODE_HOME="/root/.mirage/node"

echo "==> Checking Docker container..."
if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
  echo "Error: Docker container '${CONTAINER_NAME}' is not running" >&2
  exit 1
fi
echo "✓ Container '${CONTAINER_NAME}' is running"

echo ""
echo "==> Stopping backend (tmux: ${BACKEND_PANE})..."
docker exec "${CONTAINER_NAME}" tmux send-keys -t "${BACKEND_PANE}" C-c 2>/dev/null || true
sleep 1
docker exec "${CONTAINER_NAME}" bash -lc "pkill -f gunicorn || pkill -f app.py || true" 2>/dev/null || true
sleep 1

echo ""
echo "==> Stopping indexer (tmux: ${INDEXER_PANE})..."
docker exec "${CONTAINER_NAME}" tmux send-keys -t "${INDEXER_PANE}" C-c 2>/dev/null || true
sleep 1
docker exec "${CONTAINER_NAME}" bash -lc "pkill -f 'indexer/main.py' || true" 2>/dev/null || true
sleep 1

if [[ "${RESTART_NODE}" == "1" ]]; then
  echo ""
  echo "==> Stopping node (tmux: ${NODE_PANE})..."
  docker exec "${CONTAINER_NAME}" tmux send-keys -t "${NODE_PANE}" C-c 2>/dev/null || true
  sleep 2
  docker exec "${CONTAINER_NAME}" bash -lc "pkill -f 'miraged start' || true" 2>/dev/null || true
  sleep 3
fi

# Copy all code directories
for dir in web/backend indexer shared scripts referrals; do
  local_path="${PROJECT_ROOT}/${dir}"
  remote_path="${ROOT_DIR}/${dir}"
  if [[ -d "${local_path}" ]]; then
    echo ""
    echo "==> Copying ${dir}..."
    docker exec "${CONTAINER_NAME}" mkdir -p "${remote_path}" 2>/dev/null || true
    docker exec "${CONTAINER_NAME}" bash -lc "rm -rf \"${remote_path:?}\"/*" 2>/dev/null || true
    docker cp "${local_path}/." "${CONTAINER_NAME}:${remote_path}/"
    echo "✓ ${dir} synced"
  fi
done

echo ""
echo "==> Restarting backend in tmux..."
docker exec "${CONTAINER_NAME}" bash -lc "
  tmux send-keys -t '${BACKEND_PANE}' \"cd ${ROOT_DIR}/web/backend && BACKEND_HOST=127.0.0.1 BACKEND_PORT=5000 PYTHONPATH='${ROOT_DIR}' python3 -m gunicorn -c gunicorn_config.py 'factory:app'\" C-m
" || {
  echo "Error: Failed to restart backend in tmux" >&2
  exit 1
}
echo "✓ Backend restarted"

echo ""
echo "==> Restarting indexer in tmux..."
docker exec "${CONTAINER_NAME}" bash -lc "
  tmux send-keys -t '${INDEXER_PANE}' \"PYTHONPATH='${ROOT_DIR}' python3 ${ROOT_DIR}/indexer/main.py\" C-m
" || {
  echo "Error: Failed to restart indexer in tmux" >&2
  exit 1
}
echo "✓ Indexer restarted"

if [[ "${RESTART_NODE}" == "1" ]]; then
  echo ""
  echo "==> Restarting node in tmux..."
  docker exec "${CONTAINER_NAME}" bash -lc "
    tmux send-keys -t '${NODE_PANE}' \"${ROOT_DIR}/blockchain/bin/miraged start 2>&1 | tee >(cronolog '/root/.mirage/logs/node/miraged-%Y-%m-%d.log')\" C-m
  " || {
    echo "Error: Failed to restart node in tmux" >&2
    exit 1
  }
  echo "✓ Node restarted"
fi

if [[ "${RELOAD_CADDY}" == "1" ]]; then
  echo ""
  echo "==> Reloading Caddy..."
  docker exec "${CONTAINER_NAME}" pkill -HUP caddy 2>/dev/null || true
  echo "✓ Caddy reloaded"
fi

echo ""
echo "==> Sync complete!"
echo "Container: ${CONTAINER_NAME}"
echo ""
echo "To view tmux:"
echo "  docker exec -it ${CONTAINER_NAME} tmux attach -t mirage"
echo ""
