#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${ROOT_DIR:-/opt/mirage}"
LOGS_DIR="${LOGS_DIR:-/root/.mirage/logs}"
CADDYFILE="${CADDYFILE:-/etc/caddy/Caddyfile}"

mkdir -p "$LOGS_DIR/caddy"
exec caddy run --config "$CADDYFILE" --adapter caddyfile 2>&1 | tee >(cronolog "$LOGS_DIR/caddy/caddy-%Y-%m-%d.log")
