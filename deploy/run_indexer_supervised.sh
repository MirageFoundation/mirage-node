#!/usr/bin/env bash
set -uo pipefail

# Restart loop for the indexer, mirroring run_miraged_supervised.sh.
#
# The indexer used to run as a bare `python3 indexer/main.py` without a restart
# supervisor, so any fatal exception took indexing down until an operator noticed. On
# 2026-08-11 a single post whose content broke urlsplit killed the indexer on
# every node at height 6754167; the process never came back and the backend
# served 503 (node_catching_up) for 80 minutes because that check reads indexer
# lag. Crashes still need fixing at the source — this only bounds the blast
# radius while nobody is watching.
#
# No cronolog here: the indexer configures its own date-based log file via
# shared/logging_setup.py. Only the supervisor's own lines are appended.

ROOT_DIR="${ROOT_DIR:-/opt/mirage}"
LOGS_DIR="${LOGS_DIR:-/root/.mirage/logs}"
MAX_RESTARTS_PER_HOUR="${INDEXER_MAX_RESTARTS_PER_HOUR:-12}"
RESTART_BACKOFF_SECONDS="${INDEXER_RESTART_BACKOFF_SECONDS:-5}"

[[ "$MAX_RESTARTS_PER_HOUR" =~ ^[1-9][0-9]*$ ]] || { echo "ERROR: INDEXER_MAX_RESTARTS_PER_HOUR must be a positive integer" >&2; exit 1; }
[[ "$RESTART_BACKOFF_SECONDS" =~ ^[1-9][0-9]*$ ]] || { echo "ERROR: INDEXER_RESTART_BACKOFF_SECONDS must be a positive integer" >&2; exit 1; }
[ -f "$ROOT_DIR/indexer/main.py" ] || { echo "ERROR: indexer entry point missing: $ROOT_DIR/indexer/main.py" >&2; exit 1; }

mkdir -p "$LOGS_DIR/indexer"

# A disabled indexer is a configuration choice, not a crash. main.py raises on
# startup when INDEXER_ENABLED=false, and the loop below restarts on any exit, so
# without this the operator's own setting burns the entire restart budget and ends
# with a crash-loop ACTION ITEM. Only an explicit "false" skips: an absent or
# malformed value still falls through so shared/config.py can fail hard on it.
if [ "${INDEXER_ENABLED:-}" = "false" ]; then
  printf '[%s] [indexer-supervisor] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    "INDEXER_ENABLED=false; not starting the indexer" \
    | tee -a "$LOGS_DIR/indexer/indexer-$(date -u +%Y-%m-%d).log"
  exit 0
fi

STOP_REQUESTED=0

log_supervisor() {
  printf '[%s] [indexer-supervisor] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" \
    | tee -a "$LOGS_DIR/indexer/indexer-$(date -u +%Y-%m-%d).log"
}

stop_supervisor() {
  STOP_REQUESTED=1
  pkill -TERM -P $$ 2>/dev/null || true
}

trap stop_supervisor INT TERM

declare -a RESTART_TIMES=()

while true; do
  log_supervisor "starting indexer (restarts_last_hour=${#RESTART_TIMES[@]}/${MAX_RESTARTS_PER_HOUR})"

  PYTHONPATH="$ROOT_DIR" python3 "$ROOT_DIR/indexer/main.py" "$@"
  exit_code="$?"
  now_epoch="$(date +%s)"

  log_supervisor "indexer exited code=${exit_code}"
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

  # A poison block crashes the indexer identically on every attempt. Give up
  # rather than spin forever: the exit is loud and the log names the height.
  if [ "${#RESTART_TIMES[@]}" -gt "$MAX_RESTARTS_PER_HOUR" ]; then
    log_supervisor "restart limit exceeded (${#RESTART_TIMES[@]} in the last hour); exiting"
    log_supervisor "ACTION ITEM the indexer is crash-looping — check the traceback above for the failing height"
    # Exit 0 so Supervisor autorestart=unexpected does not relaunch this
    # wrapper with a fresh hourly budget.
    exit 0
  fi

  sleep "$RESTART_BACKOFF_SECONDS"
done
