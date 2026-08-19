#!/usr/bin/env bash
# Thin supervisorctl wrapper used by recovery, host tools, and tests.
set -euo pipefail
CONF="${SUPERVISOR_CONF:-/etc/supervisor/supervisord.conf}"
exec supervisorctl -c "$CONF" "$@"
