#!/usr/bin/env bash
# Write Supervisor program files from the current (post-migration) environment.
set -euo pipefail

ROOT_DIR="${ROOT_DIR:-/opt/mirage}"
CONF_DIR="${SUPERVISOR_PROGRAM_DIR:-/etc/supervisor/conf.d}"
LOGS_DIR="${LOGS_DIR:-/root/.mirage/logs}"

mkdir -p "$CONF_DIR" "$LOGS_DIR/supervisor"

write_program() {
  local name="$1"
  cat > "$CONF_DIR/${name}.conf"
}

write_program postgres <<EOF
[program:postgres]
command=bash ${ROOT_DIR}/deploy/run_postgres.sh
directory=${ROOT_DIR}
autostart=true
autorestart=true
startsecs=5
startretries=10
stopwaitsecs=30
stopsignal=INT
stopasgroup=true
killasgroup=true
stdout_logfile=${LOGS_DIR}/postgres/postgres-supervisor.log
stdout_logfile_maxbytes=20MB
stderr_logfile=${LOGS_DIR}/postgres/postgres-supervisor.err
stderr_logfile_maxbytes=20MB
priority=10
EOF

write_program caddy <<EOF
[program:caddy]
command=bash ${ROOT_DIR}/deploy/run_caddy.sh
directory=${ROOT_DIR}
autostart=true
autorestart=true
startsecs=2
startretries=10
stopasgroup=true
killasgroup=true
stdout_logfile=${LOGS_DIR}/caddy/caddy-supervisor.log
stderr_logfile=${LOGS_DIR}/caddy/caddy-supervisor.err
priority=20
EOF

write_program node <<EOF
[program:node]
command=bash ${ROOT_DIR}/deploy/run_miraged_supervised.sh
directory=${ROOT_DIR}
autostart=true
autorestart=unexpected
startsecs=5
startretries=20
stopwaitsecs=60
stopsignal=TERM
stopasgroup=true
killasgroup=true
stdout_logfile=${LOGS_DIR}/node/node-supervisor.log
stderr_logfile=${LOGS_DIR}/node/node-supervisor.err
priority=40
EOF

write_program indexer <<EOF
[program:indexer]
command=bash ${ROOT_DIR}/deploy/run_indexer_supervised.sh
directory=${ROOT_DIR}
autostart=true
autorestart=unexpected
startsecs=3
startretries=20
stopwaitsecs=30
stopsignal=TERM
stopasgroup=true
killasgroup=true
stdout_logfile=${LOGS_DIR}/indexer/indexer-supervisor.log
stderr_logfile=${LOGS_DIR}/indexer/indexer-supervisor.err
priority=50
EOF

write_program backend <<EOF
[program:backend]
command=bash ${ROOT_DIR}/deploy/run_backend.sh
directory=${ROOT_DIR}/web/backend
autostart=true
autorestart=true
startsecs=5
startretries=20
stopwaitsecs=30
stopsignal=TERM
stopasgroup=true
killasgroup=true
stdout_logfile=${LOGS_DIR}/backend/backend-supervisor.log
stderr_logfile=${LOGS_DIR}/backend/backend-supervisor.err
priority=60
EOF

write_program enable-validator <<EOF
[program:enable-validator]
command=bash ${ROOT_DIR}/deploy/run_enable_validator.sh
directory=${ROOT_DIR}
autostart=true
autorestart=false
startsecs=0
startretries=1
priority=45
stdout_logfile=${LOGS_DIR}/deploy/enable-validator.log
stderr_logfile=${LOGS_DIR}/deploy/enable-validator.err
EOF

write_program state-sync-marker <<EOF
[program:state-sync-marker]
command=bash ${ROOT_DIR}/deploy/run_state_sync_marker.sh
directory=${ROOT_DIR}
autostart=true
autorestart=false
startsecs=0
startretries=1
priority=46
stdout_logfile=${LOGS_DIR}/deploy/state-sync-marker.log
stderr_logfile=${LOGS_DIR}/deploy/state-sync-marker.err
EOF

write_program maintenance-gate <<EOF
[program:maintenance-gate]
command=bash ${ROOT_DIR}/deploy/run_maintenance_gate.sh
directory=${ROOT_DIR}
autostart=true
autorestart=false
startsecs=0
startretries=3
stopasgroup=true
killasgroup=true
priority=70
stdout_logfile=${LOGS_DIR}/deploy/maintenance-gate.log
stderr_logfile=${LOGS_DIR}/deploy/maintenance-gate.err
EOF

write_program cleanup <<EOF
[program:cleanup]
command=bash ${ROOT_DIR}/deploy/run_daily_cleanup.sh
directory=${ROOT_DIR}
autostart=true
autorestart=true
startsecs=1
priority=100
stdout_logfile=${LOGS_DIR}/deploy/cleanup.log
stderr_logfile=${LOGS_DIR}/deploy/cleanup.err
EOF

if [ "${AUTO_DIVERGENCE_RECOVERY:-false}" = "true" ]; then
  write_program watchdog <<EOF
[program:watchdog]
command=bash ${ROOT_DIR}/deploy/run_watchdog.sh
directory=${ROOT_DIR}
autostart=true
autorestart=true
startsecs=3
stopasgroup=true
killasgroup=true
priority=80
stdout_logfile=${LOGS_DIR}/deploy/watchdog-supervisor.log
stderr_logfile=${LOGS_DIR}/deploy/watchdog-supervisor.err
EOF
  echo "==> Divergence watchdog scheduled (autorecover=${WATCHDOG_AUTORECOVER:-false})"
else
  rm -f "$CONF_DIR/watchdog.conf"
  echo "==> Divergence watchdog disabled (AUTO_DIVERGENCE_RECOVERY=false on this host)"
fi

if [ -n "${ALERT_WEBHOOK_URL:-}" ]; then
  write_program stuck-alert <<EOF
[program:stuck-alert]
command=bash ${ROOT_DIR}/deploy/run_stuck_alert.sh
directory=${ROOT_DIR}
autostart=true
autorestart=true
startsecs=3
stopasgroup=true
killasgroup=true
priority=81
stdout_logfile=${LOGS_DIR}/deploy/stuck-alert-supervisor.log
stderr_logfile=${LOGS_DIR}/deploy/stuck-alert-supervisor.err
EOF
  echo "==> Stuck-node alert pager scheduled"
else
  rm -f "$CONF_DIR/stuck-alert.conf"
  echo "==> Stuck-node alert pager disabled (ALERT_WEBHOOK_URL unset)"
fi
