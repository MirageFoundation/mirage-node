#!/usr/bin/env bash
set -euo pipefail

cleanup() {
  echo "Received shutdown signal, gracefully stopping services..."
  
  # Stop node
  pkill -TERM -f "miraged start" 2>/dev/null || true
  for i in $(seq 1 30); do
    if ! pgrep -f "miraged start" >/dev/null 2>&1; then
      break
    fi
    sleep 1
  done
  if pgrep -f "miraged start" >/dev/null 2>&1; then
    pkill -KILL -f "miraged start" 2>/dev/null || true
  fi
  
  pg_ctlcluster 16 main stop -m fast 2>/dev/null || true
  sleep 2
  echo "✓ PostgreSQL stopped"
  
  exit 0
}
trap cleanup SIGTERM SIGINT

ROOT_DIR="/opt/mirage"
SESSION="mirage"
export PYTHONPATH="/opt/mirage"

# Load persistent env files if present
CONFIG_DIR="${HOME}/.mirage/config"
load_env_files() {
  for envfile in "${CONFIG_DIR}/backend.env" "${CONFIG_DIR}/node.env" "${CONFIG_DIR}/indexer.env" "${CONFIG_DIR}/frontend.env" "${CONFIG_DIR}/secrets.env"; do
    if [ -f "$envfile" ]; then
      set -a
      . "$envfile"
      set +a
    fi
  done
}
load_env_files

# Ensure config directory exists
mkdir -p "$CONFIG_DIR"

# Run deploy migrations (one-time migrations + env sync with templates)
echo "==> Running deploy migrations..."
python3 -m deploy.migrations --config-dir "$CONFIG_DIR" || true

# Reload env files after migrations
load_env_files

# Set container hostname to MONIKER or external IP (instead of random container ID)
# Note: Replace dots with dashes (dots not allowed in hostnames). Fails silently if no permissions.
if [ -n "${MONIKER:-}" ]; then
  hostname "${MONIKER//./-}" 2>/dev/null || true
else
  EXTERNAL_IP=$(curl -s --max-time 5 ifconfig.me 2>/dev/null || echo "")
  if [ -n "$EXTERNAL_IP" ]; then
    hostname "${EXTERNAL_IP//./-}" 2>/dev/null || true
  fi
fi

# Ensure a default local Postgres URL if not provided
if [ -z "${MIRAGE_INDEXER_DB_URL:-}" ]; then
  export MIRAGE_INDEXER_DB_URL="postgresql://mirage:mirage@127.0.0.1:5432/mirage"
fi

# Defaults if not provided
: "${MIRAGE_MODE:=main}"
: "${BACKEND_HOST:=127.0.0.1}"
: "${BACKEND_PORT:=5000}"

DATA_DIR="${HOME}/.mirage"
NODE_HOME="$DATA_DIR/main"
LOGS_DIR="$DATA_DIR/logs"
BIN="$ROOT_DIR/blockchain/miraged"
CHAIN_ID="mirage-1"
MONIKER="${MONIKER:-validator}"
MIGRATE_CONFIG="${MIGRATE_CONFIG:-0}"

# Create centralized log directory structure
mkdir -p "$LOGS_DIR"/{node,indexer,backend,postgres,hermes,caddy,referrals,deploy}

# Export variables needed by init.sh and render_template.py
export MONIKER CHAIN_ID LOGS_DIR

# Start logging entrypoint to deploy log (date-based)
DEPLOY_LOG="$LOGS_DIR/deploy/entrypoint-$(date -u +%Y-%m-%d).log"
exec > >(tee -a "$DEPLOY_LOG") 2>&1

echo "=== Mirage Startup $(date -Iseconds) ==="
echo "Node home: $NODE_HOME"
echo "Logs dir:  $LOGS_DIR"
echo "Moniker:   $MONIKER"

# Run initialization if needed
if [ ! -f "$DATA_DIR/.initialized" ] || [ "$MIGRATE_CONFIG" = "1" ]; then
  echo "==> Running initialization (MIGRATE_CONFIG=$MIGRATE_CONFIG)..."
  MIGRATE_CONFIG="$MIGRATE_CONFIG" bash "$ROOT_DIR/deploy/init.sh"
fi

# ALWAYS ensure Caddyfile is rendered correctly (even if init already ran)
# This prevents issues where the Caddyfile might be missing or incorrect
echo "==> Ensuring Caddyfile is correctly rendered..."
mkdir -p /etc/caddy
if ! python3 "$ROOT_DIR/deploy/render_template.py" "$ROOT_DIR/deploy/templates/Caddyfile" "/etc/caddy/Caddyfile"; then
  echo "ERROR: Failed to render Caddyfile" >&2
  exit 1
fi
# Verify Caddyfile contains expected content (API proxy)
if ! grep -q "reverse_proxy.*127.0.0.1:5000" /etc/caddy/Caddyfile; then
  echo "ERROR: Caddyfile missing API proxy configuration" >&2
  echo "Caddyfile contents:" >&2
  cat /etc/caddy/Caddyfile >&2
  exit 1
fi
echo "✓ Caddyfile verified"

# Kill any existing tmux session
if tmux has-session -t "$SESSION" 2>/dev/null; then
  tmux kill-session -t "$SESSION" 2>/dev/null
fi

echo "==> Starting tmux session '$SESSION'..."
tmux new-session -d -s "$SESSION" -c "$ROOT_DIR" -n caddy

# Apply bundled tmux config
TMUX_TEMPLATE="$ROOT_DIR/deploy/templates/tmux.conf"
if [ -f "$TMUX_TEMPLATE" ]; then
  cp "$TMUX_TEMPLATE" /etc/tmux.conf
  tmux source-file /etc/tmux.conf 2>/dev/null
fi

# Caddy (first) - start with HTTP-only config, will be upgraded to HTTPS if domain exists
tmux send-keys -t "$SESSION:caddy" "caddy run --config /etc/caddy/Caddyfile --adapter caddyfile 2>&1 | cronolog \"$LOGS_DIR/caddy/caddy-%Y-%m-%d.log\"" C-m

# PostgreSQL (start early)
# Data lives directly on persistent volume at ~/.mirage/main/data/postgres
PG_DATA_DIR="$DATA_DIR/main/data/postgres"
PG_LOG_DIR="$LOGS_DIR/postgres"

# Ensure postgres user can traverse to and write to log directory
chmod o+x "$DATA_DIR" "$LOGS_DIR" 2>/dev/null || true
chown postgres:postgres "$PG_LOG_DIR"
chmod 755 "$PG_LOG_DIR"

# Ensure PostgreSQL cluster exists with UTF-8 encoding
if [ ! -f "$PG_DATA_DIR/PG_VERSION" ]; then
  echo "==> Creating PostgreSQL cluster at $PG_DATA_DIR..."
  pg_dropcluster 16 main 2>/dev/null || true
  mkdir -p "$PG_DATA_DIR"
  # Ensure postgres user can traverse parent directories (including $HOME which is /root)
  chmod o+x "$HOME" "$DATA_DIR" "$DATA_DIR/main" "$DATA_DIR/main/data" 2>/dev/null || true
  chown postgres:postgres "$PG_DATA_DIR"
  chmod 700 "$PG_DATA_DIR"
  pg_createcluster 16 main --datadir="$PG_DATA_DIR" --locale=C.UTF-8
  echo "✓ PostgreSQL cluster created"
else
  # Cluster data exists at new location - ensure cluster points to it (not old /var/lib location)
  CURRENT_DATADIR=$(pg_lsclusters -h 2>/dev/null | awk '/^16 *main/ {print $6}')
  if [ "$CURRENT_DATADIR" != "$PG_DATA_DIR" ]; then
    echo "==> Pointing PostgreSQL cluster to $PG_DATA_DIR..."
    chmod o+x "$HOME" "$DATA_DIR" "$DATA_DIR/main" "$DATA_DIR/main/data" "$LOGS_DIR" 2>/dev/null || true
    pg_ctlcluster 16 main stop 2>/dev/null || true
    # Update postgresql.conf to point to new data and log directories
    sed -i "s|^data_directory = .*|data_directory = '$PG_DATA_DIR'|" /etc/postgresql/16/main/postgresql.conf
    echo "✓ PostgreSQL data directory updated"
  fi
fi

# Always ensure logging is enabled and log_directory points to persistent location
PG_CONF="/etc/postgresql/16/main/postgresql.conf"
# Uncomment and set log_directory
sed -i "s|^#*log_directory = .*|log_directory = '$PG_LOG_DIR'|" "$PG_CONF"
if ! grep -q "^log_directory" "$PG_CONF"; then
  echo "log_directory = '$PG_LOG_DIR'" >> "$PG_CONF"
fi
# Set log filename to match our convention (postgres-YYYY-MM-DD.log)
sed -i "s|^#*log_filename = .*|log_filename = 'postgres-%Y-%m-%d.log'|" "$PG_CONF"
if ! grep -q "^log_filename" "$PG_CONF"; then
  echo "log_filename = 'postgres-%Y-%m-%d.log'" >> "$PG_CONF"
fi
# Enable logging_collector so logs go to files
sed -i "s|^#*logging_collector = .*|logging_collector = on|" "$PG_CONF"
if ! grep -q "^logging_collector" "$PG_CONF"; then
  echo "logging_collector = on" >> "$PG_CONF"
fi

tmux new-window -t "$SESSION" -n postgres -c "$ROOT_DIR"
tmux send-keys -t "$SESSION:postgres" "pg_ctlcluster 16 main start && sleep 2 && tail -f $PG_LOG_DIR/postgres-\$(date -u +%Y-%m-%d).log" C-m

# Wait for PostgreSQL readiness (hard fail) using a valid role
echo '==> Waiting for PostgreSQL to become available...'
PG_READY=0
for i in $(seq 1 60); do
  if pg_isready -h 127.0.0.1 -p 5432 -U postgres -t 1 >/dev/null 2>&1; then
    PG_READY=1
    echo '✓ PostgreSQL is ready'
    break
  fi
  sleep 1
done
if [ "$PG_READY" -eq 0 ]; then
  echo 'ERROR: PostgreSQL not ready after 60s' >&2
  exit 1
fi

# Ensure local database and role exist if URL points to localhost
ensure_local_postgres_db() {
  local url="${MIRAGE_INDEXER_DB_URL:-}"
  # Extract components: user, pass, host, port, db
  # shellcheck disable=SC2001
  local user pass host port db
  user="$(echo "$url" | sed -E 's#^postgresql://([^:@/]+)(:([^@/]*))?@([^:/]+)(:([0-9]+))?/([^?]+).*$#\1#')"
  pass="$(echo "$url" | sed -E 's#^postgresql://([^:@/]+)(:([^@/]*))?@([^:/]+)(:([0-9]+))?/([^?]+).*$#\3#')"
  host="$(echo "$url" | sed -E 's#^postgresql://([^:@/]+)(:([^@/]*))?@([^:/]+)(:([0-9]+))?/([^?]+).*$#\4#')"
  port="$(echo "$url" | sed -E 's#^postgresql://([^:@/]+)(:([^@/]*))?@([^:/]+)(:([0-9]+))?/([^?]+).*$#\6#')"
  db="$(echo "$url" | sed -E 's#^postgresql://([^:@/]+)(:([^@/]*))?@([^:/]+)(:([0-9]+))?/([^?]+).*$#\7#')"
  port="${port:-5432}"
  if [ "$host" != "127.0.0.1" ] && [ "$host" != "localhost" ]; then
    echo "PostgreSQL URL points to non-local host ($host); skipping local DB provisioning."
    return 0
  fi
  if [ -z "$user" ] || [ -z "$db" ]; then
    echo "Invalid MIRAGE_INDEXER_DB_URL, missing user or db: $url" >&2
    exit 1
  fi
  echo "==> Ensuring Postgres role '$user' and database '$db' exist..."
  # Create role if missing
  if ! su - postgres -c "psql -tAc \"SELECT 1 FROM pg_roles WHERE rolname='${user}'\"" | grep -q 1; then
    if [ -n "$pass" ]; then
      su - postgres -c "psql -c \"CREATE ROLE ${user} WITH LOGIN PASSWORD '${pass//\'/''}';\""
    else
      su - postgres -c "psql -c \"CREATE ROLE ${user} WITH LOGIN;\""
    fi
  fi
  # Create database if missing
  if ! su - postgres -c "psql -tAc \"SELECT 1 FROM pg_database WHERE datname='${db}'\"" | grep -q 1; then
    su - postgres -c "psql -c \"CREATE DATABASE ${db} OWNER ${user};\""
  fi
  echo "✓ Postgres role and database ensured."
}
ensure_local_postgres_db

# Auto-configure HTTPS if domain is set (from node.env)
if [ -n "${DOMAIN:-}" ]; then
  echo "==> Domain configured: $DOMAIN"
  echo "==> Configuring HTTPS automatically..."
  sleep 2  # Give Caddy a moment to start
  bash "$ROOT_DIR/deploy/letsencrypt_register.sh" --domain="$DOMAIN"
fi

# Node (second)
tmux new-window -t "$SESSION" -n node -c "$ROOT_DIR"
tmux send-keys -t "$SESSION:node" "export MIRAGE_NODE_HOME=\"$NODE_HOME\"" C-m
tmux send-keys -t "$SESSION:node" "$BIN start --home \"$NODE_HOME\" 2>&1 | cronolog \"$LOGS_DIR/node/miraged-%Y-%m-%d.log\"" C-m

# Wait for node RPC to be ready before starting dependent services
echo "==> Waiting for node RPC to become available..."
RPC_READY=0
for i in $(seq 1 120); do
  if curl -sf http://127.0.0.1:26657/status >/dev/null 2>&1; then
    RPC_READY=1
    echo "✓ Node RPC is ready"
    break
  fi
  sleep 1
done

if [ "$RPC_READY" -eq 0 ]; then
  echo "ERROR: Node RPC not ready after 120s" >&2
  exit 1
fi

# Enable validator mode if priv_validator_key.json exists
if [ -f "$NODE_HOME/config/priv_validator_key.json" ]; then
  echo "==> Enabling validator mode..."
  MIRAGE_NODE_HOME="$NODE_HOME" bash "$ROOT_DIR/deploy/enable_validator_mode.sh"
fi

# Indexer (third) - uses wrapper script that waits for RPC
tmux new-window -t "$SESSION" -n indexer -c "$ROOT_DIR"
tmux send-keys -t "$SESSION:indexer" "PYTHONPATH=$ROOT_DIR python3 indexer/main.py" C-m

# Backend (fourth)
tmux new-window -t "$SESSION" -n backend -c "$ROOT_DIR/web/backend"
tmux send-keys -t "$SESSION:backend" "MIRAGE_NODE_HOME=\"$NODE_HOME\" BACKEND_HOST=127.0.0.1 BACKEND_PORT=5000 PYTHONPATH=$ROOT_DIR python3 -m gunicorn -c gunicorn_config.py 'factory:app'" C-m

# Validator status monitor (fifth)
tmux new-window -t "$SESSION" -n status -c "$ROOT_DIR"
tmux send-keys -t "$SESSION:status" "watch -n 10 bash $ROOT_DIR/scripts/check_validator_status.sh" C-m

# Referral accrual daemon (sixth)
tmux new-window -t "$SESSION" -n referral -c "$ROOT_DIR"
tmux send-keys -t "$SESSION:referral" "PYTHONPATH=$ROOT_DIR python3 referrals/referral_accrue.py" C-m

# IBC Relayer (seventh) - only if Hermes is configured
if [ -f "$HOME/.hermes/config.toml" ]; then
  # Install hermes if not present
  if ! command -v hermes >/dev/null 2>&1; then
    echo "==> Installing Hermes binary..."
    HERMES_VERSION="v1.10.4"
    curl -sL "https://github.com/informalsystems/hermes/releases/download/${HERMES_VERSION}/hermes-${HERMES_VERSION}-x86_64-unknown-linux-gnu.tar.gz" -o /tmp/hermes.tar.gz
    tar -xzf /tmp/hermes.tar.gz -C /usr/local/bin/
    chmod +x /usr/local/bin/hermes
    rm /tmp/hermes.tar.gz
  fi
  echo "==> Starting Hermes IBC relayer..."
  tmux new-window -t "$SESSION" -n hermes -c "$ROOT_DIR"
  tmux send-keys -t "$SESSION:hermes" "hermes start 2>&1 | cronolog \"$LOGS_DIR/hermes/hermes-%Y-%m-%d.log\"" C-m
  # Add status monitor pane (50% bottom)
  tmux split-window -t "$SESSION:hermes" -v -p 50 -c "$ROOT_DIR"
  tmux send-keys -t "$SESSION:hermes.1" "watch -n 60 /opt/mirage/scripts/check_hermes_status.sh" C-m
  # Focus back on hermes pane
  tmux select-pane -t "$SESSION:hermes.0"
fi

echo "✓ Started. Attach via: tmux attach -t $SESSION"

# Keep container alive
while true; do sleep 1; done


