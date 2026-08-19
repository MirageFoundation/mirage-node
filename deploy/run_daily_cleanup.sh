#!/usr/bin/env bash
# Periodic WAL/log/edge/ASN cleanup. Lives under Supervisor, not PID 1.
set -euo pipefail

ROOT_DIR="${ROOT_DIR:-/opt/mirage}"
DATA_DIR="${HOME}/.mirage"
NODE_HOME="$DATA_DIR/node"
LOGS_DIR="$DATA_DIR/logs"

if [ -z "${LOG_RETENTION_DAYS:-}" ]; then
  echo "ERROR: LOG_RETENTION_DAYS not set" >&2
  exit 1
fi
if ! [[ "$LOG_RETENTION_DAYS" =~ ^[0-9]+$ ]] || [ "$LOG_RETENTION_DAYS" -le 0 ]; then
  echo "ERROR: LOG_RETENTION_DAYS must be a positive integer" >&2
  exit 1
fi

CLEANUP_INTERVAL=86400
SECONDS_SINCE_CLEANUP=$CLEANUP_INTERVAL
CLEANUP_JITTER=$((RANDOM % 21600))
CLEANUP_JITTER_APPLIED=0
echo "==> Daily cleanup offset: ${CLEANUP_JITTER}s after the first pass (anti-lockstep)"

while true; do
  sleep 1
  SECONDS_SINCE_CLEANUP=$((SECONDS_SINCE_CLEANUP + 1))
  if [ "$SECONDS_SINCE_CLEANUP" -ge "$CLEANUP_INTERVAL" ]; then
    SECONDS_SINCE_CLEANUP=0
    if [ "$CLEANUP_JITTER_APPLIED" -eq 0 ]; then
      CLEANUP_JITTER_APPLIED=1
      SECONDS_SINCE_CLEANUP=$((-CLEANUP_JITTER))
    fi
    find "$NODE_HOME/data/cs.wal" -name "wal.*" -type f -mtime +0 -delete 2>/dev/null || true
    find "$LOGS_DIR" -name "*.log" -type f -mtime +"$LOG_RETENTION_DAYS" -delete 2>/dev/null || true
    python3 "$ROOT_DIR/deploy/refresh_edge_ips.py" \
      2>&1 | tee -a "$LOGS_DIR/deploy/refresh-edge-ips-$(date -u +%Y-%m-%d).log" || true
    python3 "$ROOT_DIR/deploy/refresh_asn_db.py" \
      2>&1 | tee -a "$LOGS_DIR/deploy/refresh-asn-db-$(date -u +%Y-%m-%d).log" || true
    if [ "${IMAGE_GC_ENABLED:-false}" = "true" ]; then
      python3 "$ROOT_DIR/scripts/image_gc.py" --days 7 --limit 100 \
        2>&1 | tee -a "$LOGS_DIR/deploy/image-gc-$(date -u +%Y-%m-%d).log" || true
    fi
  fi
done
