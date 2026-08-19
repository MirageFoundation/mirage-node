#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${ROOT_DIR:-/opt/mirage}"
LOGS_DIR="${LOGS_DIR:-/root/.mirage/logs}"
WD_AUTOREC="${WATCHDOG_AUTORECOVER:-false}"
WD_DRY="${DIVERGENCE_DRY_RUN:-false}"

mkdir -p "$LOGS_DIR/deploy"
exec env WATCHDOG_AUTORECOVER="$WD_AUTOREC" DRY_RUN="$WD_DRY" PYTHONPATH="$ROOT_DIR" \
  python3 "$ROOT_DIR/scripts/divergence_watchdog.py" \
  2>&1 | tee >(cronolog "$LOGS_DIR/deploy/divergence_watchdog-%Y-%m-%d.log")
