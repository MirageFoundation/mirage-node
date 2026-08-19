#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${ROOT_DIR:-/opt/mirage}"
LOGS_DIR="${LOGS_DIR:-/root/.mirage/logs}"

if [ -z "${ALERT_WEBHOOK_URL:-}" ]; then
  echo "ERROR: ALERT_WEBHOOK_URL is unset; stuck-alert must not be scheduled" >&2
  exit 1
fi

mkdir -p "$LOGS_DIR/deploy"
exec env PYTHONPATH="$ROOT_DIR" python3 "$ROOT_DIR/scripts/stuck_node_alert.py" \
  2>&1 | tee >(cronolog "$LOGS_DIR/deploy/stuck_node_alert-%Y-%m-%d.log")
