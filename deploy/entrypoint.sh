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
ENV_DIR="${HOME}/.mirage/env"
load_env_files() {
  for envfile in "${ENV_DIR}/backend.env" "${ENV_DIR}/node.env" "${ENV_DIR}/indexer.env" "${ENV_DIR}/frontend.env" "${ENV_DIR}/secrets.env"; do
    if [ -f "$envfile" ]; then
      set -a
      . "$envfile"
      set +a
    fi
  done
}
load_env_files

# Ensure config directory exists
mkdir -p "$ENV_DIR"

# Run deploy migrations (one-time migrations + env sync with templates)
echo "==> Running deploy migrations..."
python3 -m deploy.migrations --config-dir "$ENV_DIR" || true

# Reload env files after migrations
load_env_files

# Set container hostname (instead of random container ID)
# Priority: DOMAIN > MONIKER > external IP
# Note: Replace dots/colons/slashes with dashes (invalid in hostnames). Fails silently if no permissions.
if [ -n "${DOMAIN:-}" ]; then
  hostname "${DOMAIN//./-}" 2>/dev/null || true
elif [ -n "${MONIKER:-}" ] && [ "${MONIKER}" != "validator" ]; then
  # Strip protocol and replace invalid chars
  CLEAN_MONIKER=$(echo "$MONIKER" | sed 's|https\?://||' | tr './:' '-')
  hostname "$CLEAN_MONIKER" 2>/dev/null || true
else
  EXTERNAL_IP=$(curl -s --max-time 5 ifconfig.me 2>/dev/null || echo "")
  if [ -n "$EXTERNAL_IP" ]; then
    hostname "${EXTERNAL_IP//./-}" 2>/dev/null || true
  fi
fi

# Safety fallback for DB URL (should already be set in indexer.env template)
if [ -z "${MIRAGE_INDEXER_DB_URL:-}" ]; then
  export MIRAGE_INDEXER_DB_URL="postgresql://mirage:mirage@127.0.0.1:5432/mirage"
fi

# Defaults if not provided
: "${BACKEND_HOST:=127.0.0.1}"
: "${BACKEND_PORT:=5000}"

DATA_DIR="${HOME}/.mirage"
NODE_HOME="$DATA_DIR/node"
LOGS_DIR="$DATA_DIR/logs"
BIN="$ROOT_DIR/blockchain/miraged"
CHAIN_ID="mirage-1"
MONIKER="${MONIKER:-validator}"

# Create centralized log directory structure
mkdir -p "$LOGS_DIR"/{node,indexer,backend,postgres,hermes,caddy,referrals,deploy}

# Clean up old log files (older than 30 days)
find "$LOGS_DIR" -name "*.log" -type f -mtime +30 -delete 2>/dev/null || true

# Export variables needed by init.sh and render_template.py
export MONIKER CHAIN_ID LOGS_DIR

# Start logging entrypoint to deploy log (date-based)
DEPLOY_LOG="$LOGS_DIR/deploy/entrypoint-$(date -u +%Y-%m-%d).log"
exec > >(tee -a "$DEPLOY_LOG") 2>&1

echo "=== Mirage Startup $(date -Iseconds) ==="
echo "Node home: $NODE_HOME"
echo "Logs dir:  $LOGS_DIR"
echo "Moniker:   $MONIKER"

# Run initialization (idempotent - safe to run every startup)
echo "==> Running initialization..."
bash "$ROOT_DIR/deploy/init.sh"

# Ensure Caddyfile exists and is correct
# If DOMAIN is set and Caddyfile already has HTTPS config for that domain, don't overwrite
mkdir -p /etc/caddy
CADDYFILE="/etc/caddy/Caddyfile"
SHOULD_RENDER=1

if [ -n "${DOMAIN:-}" ] && [ -f "$CADDYFILE" ]; then
  # Check if existing Caddyfile already has HTTPS for this domain (not just :80)
  if grep -q "^${DOMAIN}" "$CADDYFILE" 2>/dev/null; then
    echo "==> Caddyfile already configured for $DOMAIN (HTTPS), keeping existing config"
    SHOULD_RENDER=0
  fi
fi

if [ "$SHOULD_RENDER" = "1" ]; then
  echo "==> Rendering Caddyfile..."
  if ! python3 "$ROOT_DIR/deploy/render_template.py" "$ROOT_DIR/deploy/templates/caddy/Caddyfile" "$CADDYFILE"; then
    echo "ERROR: Failed to render Caddyfile" >&2
    exit 1
  fi
fi

# Verify Caddyfile contains expected content (API proxy)
if ! grep -q "reverse_proxy.*127.0.0.1:5000" "$CADDYFILE"; then
  echo "ERROR: Caddyfile missing API proxy configuration" >&2
  echo "Caddyfile contents:" >&2
  cat "$CADDYFILE" >&2
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
TMUX_TEMPLATE="$ROOT_DIR/deploy/templates/tmux/tmux.conf"
if [ -f "$TMUX_TEMPLATE" ]; then
  cp "$TMUX_TEMPLATE" /etc/tmux.conf
  tmux source-file /etc/tmux.conf 2>/dev/null
fi

# Caddy (first) - start with HTTP-only config, will be upgraded to HTTPS if domain exists
tmux send-keys -t "$SESSION:caddy" "caddy run --config /etc/caddy/Caddyfile --adapter caddyfile 2>&1 | tee >(cronolog \"$LOGS_DIR/caddy/caddy-%Y-%m-%d.log\")" C-m

# PostgreSQL (start early)
# Data lives directly on persistent volume at ~/.mirage/postgres
PG_DATA_DIR="$DATA_DIR/postgres"
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
  chmod o+x "$HOME" "$DATA_DIR" 2>/dev/null || true
  chown postgres:postgres "$PG_DATA_DIR"
  chmod 700 "$PG_DATA_DIR"
  pg_createcluster 16 main --datadir="$PG_DATA_DIR" --locale=C.UTF-8
  echo "✓ PostgreSQL cluster created"
else
  # Cluster data exists at new location - ensure cluster points to it (not old /var/lib location)
  CURRENT_DATADIR=$(pg_lsclusters -h 2>/dev/null | awk '/^16 *main/ {print $6}')
  if [ "$CURRENT_DATADIR" != "$PG_DATA_DIR" ]; then
    echo "==> Pointing PostgreSQL cluster to $PG_DATA_DIR..."
    chmod o+x "$HOME" "$DATA_DIR" "$LOGS_DIR" 2>/dev/null || true
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
# Skip if Caddyfile already has HTTPS configured (www redirect indicates full HTTPS setup)
if [ -n "${DOMAIN:-}" ]; then
  if grep -q "^www\.${DOMAIN}" "$CADDYFILE" 2>/dev/null; then
    echo "==> HTTPS already configured for $DOMAIN (www redirect present)"
  else
    echo "==> Domain configured: $DOMAIN"
    echo "==> Configuring HTTPS automatically..."
    sleep 2  # Give Caddy a moment to start
    bash "$ROOT_DIR/deploy/letsencrypt_register.sh" --domain="$DOMAIN"
  fi
fi

# Node (second)
tmux new-window -t "$SESSION" -n node -c "$ROOT_DIR"
# Node home is always ~/.mirage/node (hardcoded)
tmux send-keys -t "$SESSION:node" "$BIN start --home \"$NODE_HOME\" 2>&1 | tee >(cronolog \"$LOGS_DIR/node/miraged-%Y-%m-%d.log\")" C-m

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
  bash "$ROOT_DIR/deploy/enable_validator_mode.sh"
fi

# Indexer (third) - uses wrapper script that waits for RPC
tmux new-window -t "$SESSION" -n indexer -c "$ROOT_DIR"
tmux send-keys -t "$SESSION:indexer" "PYTHONPATH=$ROOT_DIR python3 indexer/main.py" C-m

# Backend (fourth)
tmux new-window -t "$SESSION" -n backend -c "$ROOT_DIR/web/backend"
tmux send-keys -t "$SESSION:backend" "BACKEND_HOST=127.0.0.1 BACKEND_PORT=5000 PYTHONPATH=$ROOT_DIR python3 -m gunicorn -c gunicorn_config.py 'factory:app'" C-m

# Referral accrual daemon (fifth)
tmux new-window -t "$SESSION" -n referrals -c "$ROOT_DIR"
tmux send-keys -t "$SESSION:referrals" "PYTHONPATH=$ROOT_DIR python3 referrals/referral_accrue.py" C-m

# IBC Relayer (sixth) - only if Hermes is configured
# NOTE: This hermes startup code is duplicated in deploy/setup_hermes_relayer.sh
#       If you change this, update the other file too!
HERMES_HOME="$DATA_DIR/hermes"
if [ -f "$HERMES_HOME/config.toml" ]; then
  # Install or upgrade hermes if needed
  HERMES_VERSION="v1.13.3"
  INSTALLED_VERSION=$(hermes version 2>&1 | grep -oE 'v[0-9]+\.[0-9]+\.[0-9]+' | head -1 || echo "")
  if [ "$INSTALLED_VERSION" != "$HERMES_VERSION" ]; then
    echo "==> Installing Hermes ${HERMES_VERSION} (was: ${INSTALLED_VERSION:-not installed})..."
    curl -sL "https://github.com/informalsystems/hermes/releases/download/${HERMES_VERSION}/hermes-${HERMES_VERSION}-x86_64-unknown-linux-gnu.tar.gz" -o /tmp/hermes.tar.gz
    tar -xzf /tmp/hermes.tar.gz -C /usr/local/bin/
    chmod +x /usr/local/bin/hermes
    rm /tmp/hermes.tar.gz
  fi
  echo "==> Starting Hermes IBC relayer..."
  tmux new-window -t "$SESSION" -n hermes -c "$ROOT_DIR"
  tmux send-keys -t "$SESSION:hermes" "hermes --config \"$HERMES_HOME/config.toml\" start 2>&1 | tee >(cronolog \"$LOGS_DIR/hermes/hermes-%Y-%m-%d.log\")" C-m
fi

# Unified Status Dashboard (last window)
tmux new-window -t "$SESSION" -n status -c "$ROOT_DIR"
tmux send-keys -t "$SESSION:status" "PYTHONPATH=$ROOT_DIR python3 $ROOT_DIR/scripts/check_status.py" C-m

echo "✓ Started. Attach via: tmux attach -t $SESSION"

# Keep container alive
while true; do sleep 1; done


