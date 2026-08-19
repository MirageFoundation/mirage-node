#!/usr/bin/env bash
# Foreground PostgreSQL for Supervisor. Cluster files are prepared by entrypoint.sh.
set -euo pipefail

PG_DATA_DIR="${HOME}/.mirage/postgres"
PG_CONF="/etc/postgresql/16/main/postgresql.conf"
BIN="/usr/lib/postgresql/16/bin/postgres"

if [ ! -f "$PG_DATA_DIR/PG_VERSION" ]; then
  echo "ERROR: PostgreSQL data directory is missing: $PG_DATA_DIR" >&2
  exit 1
fi
if [ ! -x "$BIN" ]; then
  echo "ERROR: postgres binary missing: $BIN" >&2
  exit 1
fi
if [ ! -f "$PG_CONF" ]; then
  echo "ERROR: PostgreSQL config missing: $PG_CONF" >&2
  exit 1
fi

exec su -s /bin/bash postgres -c "exec $(printf '%q' "$BIN") -D $(printf '%q' "$PG_DATA_DIR") --config-file=$(printf '%q' "$PG_CONF")"
