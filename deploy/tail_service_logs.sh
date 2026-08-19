#!/usr/bin/env bash
# Follow persistent service logs from inside the container.
set -euo pipefail
SERVICE="${1:?service required}"
LINES="${2:?lines required}"
ONCE="${3:?once flag required}"

shopt -s nullglob
case "$SERVICE" in
  supervisor) files=(/root/.mirage/logs/supervisor/supervisord.log) ;;
  node) files=(/root/.mirage/logs/node/miraged-*.log /root/.mirage/logs/node/node-supervisor.log) ;;
  indexer) files=(/root/.mirage/logs/indexer/indexer-*.log /root/.mirage/logs/indexer/indexer-supervisor.log) ;;
  backend) files=(/root/.mirage/logs/backend/*.log /root/.mirage/logs/backend/backend-supervisor.log) ;;
  caddy) files=(/root/.mirage/logs/caddy/caddy-*.log /root/.mirage/logs/caddy/caddy-supervisor.log) ;;
  postgres) files=(/root/.mirage/logs/postgres/postgres-*.log /root/.mirage/logs/postgres/postgres-supervisor.log) ;;
  watchdog) files=(/root/.mirage/logs/deploy/divergence_watchdog-*.log /root/.mirage/logs/deploy/watchdog-supervisor.log) ;;
  stuck-alert) files=(/root/.mirage/logs/deploy/stuck_node_alert-*.log /root/.mirage/logs/deploy/stuck-alert-supervisor.log) ;;
  all) files=(
    /root/.mirage/logs/supervisor/supervisord.log
    /root/.mirage/logs/node/miraged-*.log
    /root/.mirage/logs/indexer/indexer-*.log
    /root/.mirage/logs/backend/*-supervisor.log
    /root/.mirage/logs/caddy/caddy-*.log
    /root/.mirage/logs/postgres/postgres-*.log
  ) ;;
  *) echo "ERROR: unknown service $SERVICE" >&2; exit 2 ;;
esac

if [[ ${#files[@]} -eq 0 ]]; then
  echo "ERROR: no log files yet for $SERVICE" >&2
  exit 1
fi

if [[ "$ONCE" == "1" ]]; then
  exec tail -n "$LINES" "${files[@]}"
fi
exec tail -n "$LINES" -F "${files[@]}"
