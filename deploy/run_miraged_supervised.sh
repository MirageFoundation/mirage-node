#!/usr/bin/env bash
set -uo pipefail

NODE_HOME="${NODE_HOME:-/root/.mirage/node}"
LOGS_DIR="${LOGS_DIR:-/root/.mirage/logs}"
BIN="${BIN:-/opt/mirage/blockchain/bin/miraged}"
MAX_RESTARTS_PER_HOUR="${MAX_RESTARTS_PER_HOUR:-12}"
RESTART_BACKOFF_SECONDS="${RESTART_BACKOFF_SECONDS:-5}"

[[ "$MAX_RESTARTS_PER_HOUR" =~ ^[1-9][0-9]*$ ]] || { echo "ERROR: MAX_RESTARTS_PER_HOUR must be a positive integer" >&2; exit 1; }
[[ "$RESTART_BACKOFF_SECONDS" =~ ^[1-9][0-9]*$ ]] || { echo "ERROR: RESTART_BACKOFF_SECONDS must be a positive integer" >&2; exit 1; }
[ -x "$BIN" ] || { echo "ERROR: miraged binary not executable: $BIN" >&2; exit 1; }

mkdir -p "$LOGS_DIR/node"

STOP_REQUESTED=0

log_supervisor() {
  printf '[%s] [miraged-supervisor] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" \
    | tee -a "$LOGS_DIR/node/miraged-$(date -u +%Y-%m-%d).log"
}

stop_supervisor() {
  STOP_REQUESTED=1
  pkill -TERM -P $$ 2>/dev/null || true
}

trap stop_supervisor INT TERM

declare -a RESTART_TIMES=()

while true; do
  log_supervisor "starting miraged (restarts_last_hour=${#RESTART_TIMES[@]}/${MAX_RESTARTS_PER_HOUR})"

  "$BIN" start --home "$NODE_HOME" "$@" 2>&1 | tee >(cronolog "$LOGS_DIR/node/miraged-%Y-%m-%d.log")
  exit_code="${PIPESTATUS[0]}"
  now_epoch="$(date +%s)"

  log_supervisor "miraged exited code=${exit_code}"
  if [ "$STOP_REQUESTED" -eq 1 ]; then
    log_supervisor "stop requested; exiting"
    exit 0
  fi

  RESTART_TIMES+=("$now_epoch")
  hour_ago=$((now_epoch - 3600))
  kept=()
  for restart_time in "${RESTART_TIMES[@]}"; do
    if [ "$restart_time" -gt "$hour_ago" ]; then
      kept+=("$restart_time")
    fi
  done
  RESTART_TIMES=("${kept[@]}")

  if [ "${#RESTART_TIMES[@]}" -gt "$MAX_RESTARTS_PER_HOUR" ]; then
    log_supervisor "restart limit exceeded; exiting"
    exit 1
  fi

  sleep "$RESTART_BACKOFF_SECONDS"
done
