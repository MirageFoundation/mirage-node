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
export PYTHONPATH="/opt/mirage"

# Prefer IPv4 in name resolution. These nodes have no working IPv6 egress, but
# public hostnames in front of the node (e.g. the Bunny edge) return AAAA records
# intermittently. glibc defaults to trying IPv6 first, which then hangs until
# timeout on a v6-less host — silently breaking the node's own outbound calls and
# self-probes (status dashboard chain/rpc/rest/api, edge IP refresh, etc.). This
# makes getaddrinfo return IPv4 first so connections succeed immediately; IPv6 is
# still attempted as a fallback if v6 connectivity ever exists. Idempotent.
if [ -f /etc/gai.conf ] && ! grep -qE '^[[:space:]]*precedence[[:space:]]+::ffff:0:0/96' /etc/gai.conf; then
  echo 'precedence ::ffff:0:0/96  100' >> /etc/gai.conf
  echo "==> gai.conf: set IPv4 precedence (host has no IPv6 egress)"
fi

# Load persistent env files if present
ENV_DIR="${HOME}/.mirage/env"
export ENV_DIR
load_env_files() {
  # Values are literals. Do not bash-source: a spaced moniker or `$()` in
  # node.env would otherwise run as root with the keyring mounted.
  local loader="$ROOT_DIR/deploy/load_env_exports.py"
  local envfile exports
  for envfile in "${ENV_DIR}/backend.env" "${ENV_DIR}/node.env" "${ENV_DIR}/indexer.env" "${ENV_DIR}/frontend.env" "${ENV_DIR}/secrets.env"; do
    if [ -f "$envfile" ]; then
      exports="$(python3 "$loader" "$envfile")" || exit 1
      eval "$exports"
    fi
  done
}
# Ensure config directory exists
mkdir -p "$ENV_DIR"

# Sync env files with templates before requiring any values
echo "==> Syncing env files with templates (pre-migrations)..."
python3 - <<'PY'
import os
from pathlib import Path

from deploy.migrations._helpers import sync_all

config_dir = Path(os.environ["ENV_DIR"])
templates_root = Path("/opt/mirage/deploy/templates")
templates_dir = templates_root / "env" if (templates_root / "env").exists() else templates_root
sync_all(templates_dir, config_dir)
PY

# Load persistent env files after sync
load_env_files

# DB URLs must be set BEFORE migrations run (no fallbacks).
for var in INDEXER_DB_URL INDEXER_DB_RO_URL BACKEND_DB_URL; do
  if [ -z "${!var:-}" ]; then
    echo "ERROR: $var is required but missing (check env files in $ENV_DIR)" >&2
    exit 1
  fi
done

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

# Defaults if not provided
: "${BACKEND_HOST:=127.0.0.1}"
: "${BACKEND_PORT:=5000}"

DATA_DIR="${HOME}/.mirage"
NODE_HOME="$DATA_DIR/node"
LOGS_DIR="$DATA_DIR/logs"
BIN="$ROOT_DIR/blockchain/bin/miraged"
COMPACT_BIN="$ROOT_DIR/blockchain/bin/compact-db"
CHAIN_ID="mirage-1"
MONIKER="${MONIKER:-validator}"

# Log retention (from node.env, hard fail if missing/invalid)
if [ -z "${LOG_RETENTION_DAYS:-}" ]; then
  echo "ERROR: LOG_RETENTION_DAYS not set in node.env" >&2
  exit 1
fi
if ! [[ "$LOG_RETENTION_DAYS" =~ ^[0-9]+$ ]] || [ "$LOG_RETENTION_DAYS" -le 0 ]; then
  echo "ERROR: LOG_RETENTION_DAYS must be a positive integer" >&2
  exit 1
fi

# Create centralized log directory structure
mkdir -p "$LOGS_DIR"/{node,indexer,backend,postgres,caddy,referrals,deploy,supervisor}

# Clean up old log files on startup
find "$LOGS_DIR" -name "*.log" -type f -mtime +"$LOG_RETENTION_DAYS" -delete 2>/dev/null || true

# Export variables needed by init.sh and render_template.py
export MONIKER CHAIN_ID LOGS_DIR

# Start logging entrypoint to deploy log (date-based). Keep the original
# stdout/stderr so they can be restored before exec supervisord; otherwise the
# process-substitution tee remains a child of PID 1.
DEPLOY_LOG="$LOGS_DIR/deploy/entrypoint-$(date -u +%Y-%m-%d).log"
exec 3>&1 4>&2
exec > >(tee -a "$DEPLOY_LOG") 2>&1

echo "=== Mirage Startup $(date -Iseconds) ==="
echo "Node home: $NODE_HOME"
echo "Logs dir:  $LOGS_DIR"
echo "Moniker:   $MONIKER"

# Run initialization (idempotent - safe to run every startup)
echo "==> Running initialization..."
bash "$ROOT_DIR/deploy/init.sh"

# Always re-render from the template so Caddyfile changes reach already-HTTPS
# nodes. The www redirect block is re-appended when DOMAIN is set.
mkdir -p /etc/caddy
CADDYFILE="/etc/caddy/Caddyfile"

# Mirror the installer and the manifests this node verified, so an operator who
# cannot reach GitHub can install from any running node. Availability only, not
# integrity: the signature is what makes a copy trustworthy. A failure here must
# never keep a validator from starting.
publish_well_known() {
  local src dest
  src="$1"
  dest="/root/.mirage/well-known/$2"
  if [ ! -f "$src" ]; then
    rm -f "$dest"
    return 0
  fi
  if ! install -m 0644 "$src" "$dest"; then
    echo "WARNING: could not publish $dest" >&2
  fi
}
mkdir -p /root/.mirage/well-known
publish_well_known /opt/mirage/deploy/install.sh install.sh
publish_well_known /opt/mirage/deploy/harden_server.sh harden_server.sh
publish_well_known /opt/mirage/deploy/release_verify.py release_verify.py
# Only the release manifest this node verified and stored gets mirrored. A
# release manifest is signed after its image digest exists, so the copy baked
# into the image necessarily describes an older release, and mirroring that
# would hand out stale bootstrap metadata. When the file is absent — a node
# deployed by deploy.sh rather than the installer — publish_well_known clears
# the path and the mirror omits it rather than serving something wrong.
publish_well_known /root/.mirage/env/release-manifest.json manifest.json
publish_well_known /root/.mirage/env/release-manifest.json.sig manifest.json.sig
if [ -f /root/.mirage/env/network-manifest.json ]; then
  publish_well_known /root/.mirage/env/network-manifest.json network.json
  publish_well_known /root/.mirage/env/network-manifest.json.sig network.json.sig
else
  publish_well_known /opt/mirage/release/network.json network.json
  publish_well_known /opt/mirage/release/network.json.sig network.json.sig
fi

echo "==> Rendering Caddyfile..."
if ! python3 "$ROOT_DIR/deploy/render_template.py" "$ROOT_DIR/deploy/templates/caddy/Caddyfile" "$CADDYFILE"; then
  echo "ERROR: Failed to render Caddyfile" >&2
  exit 1
fi
if [ -n "${DOMAIN:-}" ]; then
  printf '\nwww.%s {\n\tredir https://%s{uri} permanent\n}\n' "$DOMAIN" "$DOMAIN" >> "$CADDYFILE"
fi

# Verify Caddyfile contains expected content (API proxy)
if ! grep -q "reverse_proxy.*127.0.0.1:5000" "$CADDYFILE"; then
  echo "ERROR: Caddyfile missing API proxy configuration" >&2
  echo "Caddyfile contents:" >&2
  cat "$CADDYFILE" >&2
  exit 1
fi
echo "✓ Caddyfile verified"

# Generate /etc/caddy/trusted-proxies.caddy BEFORE Caddy starts. The Caddyfile
# imports it inside the global servers{} block, so the file must exist or Caddy
# fails to parse. Driven by EDGE_PROVIDER (default cloudflare = prior behavior).
# Non-fatal: in cloudflare mode this is a local write; in bunny/both it keeps the
# last-known file on a transient fetch failure.
echo "==> Generating Caddy trusted-proxy config (EDGE_PROVIDER=${EDGE_PROVIDER:-cloudflare})..."
python3 "$ROOT_DIR/deploy/refresh_edge_ips.py" || echo "WARN: refresh_edge_ips.py failed; using existing trusted-proxies.caddy if present"

# Local IP-to-network-class dataset for network tags. Lives on the persistent
# volume, never in the image, so a refresh survives redeploys instead of being
# reverted to whatever was baked at build time. Non-fatal: a failed fetch keeps
# the previous dataset, and with no dataset at all the relay simply omits the
# class from the tag rather than blocking the posting path.
echo "==> Refreshing IP-to-network-class dataset..."
python3 "$ROOT_DIR/deploy/refresh_asn_db.py" || echo "WARN: refresh_asn_db.py failed; network class may be stale or absent"

# Enable maintenance mode while services start up
touch /etc/caddy/.maintenance

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

echo "==> Starting PostgreSQL for bootstrap migrations..."
pg_ctlcluster 16 main start

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

# Parse a PostgreSQL URL into components
_parse_pg_url() {
  local url="$1"
  PG_USER="$(echo "$url" | sed -E 's#^postgresql://([^:@/]+)(:([^@/]*))?@([^:/]+)(:([0-9]+))?/([^?]+).*$#\1#')"
  PG_PASS="$(echo "$url" | sed -E 's#^postgresql://([^:@/]+)(:([^@/]*))?@([^:/]+)(:([0-9]+))?/([^?]+).*$#\3#')"
  PG_HOST="$(echo "$url" | sed -E 's#^postgresql://([^:@/]+)(:([^@/]*))?@([^:/]+)(:([0-9]+))?/([^?]+).*$#\4#')"
  PG_PORT="$(echo "$url" | sed -E 's#^postgresql://([^:@/]+)(:([^@/]*))?@([^:/]+)(:([0-9]+))?/([^?]+).*$#\6#')"
  PG_DB="$(echo "$url" | sed -E 's#^postgresql://([^:@/]+)(:([^@/]*))?@([^:/]+)(:([0-9]+))?/([^?]+).*$#\7#')"
  PG_PORT="${PG_PORT:-5432}"
}

_ensure_role_and_db() {
  local user="$1" pass="$2" db="$3"
  if ! su - postgres -c "psql -tAc \"SELECT 1 FROM pg_roles WHERE rolname='${user}'\"" | grep -q 1; then
    if [ -n "$pass" ]; then
      su - postgres -c "psql -c \"CREATE ROLE ${user} WITH LOGIN PASSWORD '${pass//\'/''}';\""
    else
      su - postgres -c "psql -c \"CREATE ROLE ${user} WITH LOGIN;\""
    fi
  fi
  if ! su - postgres -c "psql -tAc \"SELECT 1 FROM pg_database WHERE datname='${db}'\"" | grep -q 1; then
    su - postgres -c "psql -c \"CREATE DATABASE ${db} OWNER ${user};\""
  fi
}

ensure_local_postgres_dbs() {
  _parse_pg_url "${INDEXER_DB_URL}"
  if [ "$PG_HOST" != "127.0.0.1" ] && [ "$PG_HOST" != "localhost" ]; then
    echo "PostgreSQL URL points to non-local host ($PG_HOST); skipping local DB provisioning."
    return 0
  fi
  if [ -z "$PG_USER" ] || [ -z "$PG_DB" ]; then
    echo "Invalid INDEXER_DB_URL, missing user or db" >&2
    exit 1
  fi

  echo "==> Provisioning indexer DB (${PG_DB})..."
  _ensure_role_and_db "$PG_USER" "$PG_PASS" "$PG_DB"

  _parse_pg_url "${BACKEND_DB_URL}"
  echo "==> Provisioning backend DB (${PG_DB})..."
  _ensure_role_and_db "$PG_USER" "$PG_PASS" "$PG_DB"

  _parse_pg_url "${INDEXER_DB_RO_URL}"
  PG_RO_USER="$PG_USER"
  echo "==> Provisioning read-only role (${PG_USER})..."
  if ! su - postgres -c "psql -tAc \"SELECT 1 FROM pg_roles WHERE rolname='${PG_USER}'\"" | grep -q 1; then
    if [ -n "$PG_PASS" ]; then
      su - postgres -c "psql -c \"CREATE ROLE ${PG_USER} WITH LOGIN PASSWORD '${PG_PASS//\'/''}';\""
    else
      su - postgres -c "psql -c \"CREATE ROLE ${PG_USER} WITH LOGIN;\""
    fi
  fi
  _parse_pg_url "${INDEXER_DB_URL}"
  su - postgres -c "psql -d ${PG_DB} -c \"GRANT CONNECT ON DATABASE ${PG_DB} TO ${PG_RO_USER};\""
  su - postgres -c "psql -d ${PG_DB} -c \"GRANT USAGE ON SCHEMA public TO ${PG_RO_USER};\""
  su - postgres -c "psql -d ${PG_DB} -c \"GRANT SELECT ON ALL TABLES IN SCHEMA public TO ${PG_RO_USER};\""
  su - postgres -c "psql -d ${PG_DB} -c \"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO ${PG_RO_USER};\""

  echo "✓ All Postgres databases and roles ensured."
}

# ── One-time: migrate DB & role names (mirage → mirage_indexer, etc.) ────────
# Requires superuser (su - postgres), so this lives in entrypoint, not Python.
migrate_local_postgres_names() {
  _parse_pg_url "${INDEXER_DB_URL:-}"
  if [ "$PG_HOST" != "127.0.0.1" ] && [ "$PG_HOST" != "localhost" ]; then
    return 0
  fi

  local changed=0

  # 1. Rename DB: mirage → mirage_indexer
  local old_db new_db
  old_db=$(su - postgres -c "psql -tAc \"SELECT 1 FROM pg_database WHERE datname='mirage'\"" 2>/dev/null | tr -d ' ')
  new_db=$(su - postgres -c "psql -tAc \"SELECT 1 FROM pg_database WHERE datname='mirage_indexer'\"" 2>/dev/null | tr -d ' ')
  if [ "$old_db" = "1" ] && [ "$new_db" != "1" ]; then
    echo "==> Renaming database: mirage → mirage_indexer..."
    su - postgres -c "psql -c \"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='mirage' AND pid <> pg_backend_pid();\"" >/dev/null 2>&1 || true
    su - postgres -c "psql -c \"ALTER DATABASE mirage RENAME TO mirage_indexer;\""
    echo "  ✓ DB renamed"
    changed=1
  fi

  # 2. Rename role: mirage → mirage_indexer
  local old_role new_role
  old_role=$(su - postgres -c "psql -tAc \"SELECT 1 FROM pg_roles WHERE rolname='mirage'\"" 2>/dev/null | tr -d ' ')
  new_role=$(su - postgres -c "psql -tAc \"SELECT 1 FROM pg_roles WHERE rolname='mirage_indexer'\"" 2>/dev/null | tr -d ' ')
  if [ "$old_role" = "1" ] && [ "$new_role" != "1" ]; then
    su - postgres -c "psql -c \"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE usename='mirage' AND pid <> pg_backend_pid();\"" >/dev/null 2>&1 || true
    su - postgres -c "psql -c \"ALTER ROLE mirage RENAME TO mirage_indexer;\""
    su - postgres -c "psql -c \"ALTER ROLE mirage_indexer WITH PASSWORD 'mirage_indexer';\""
    echo "  ✓ Role renamed: mirage → mirage_indexer"
    changed=1
  fi

  # 3. Rename role: mirage_ro → mirage_indexer_ro
  local old_ro new_ro
  old_ro=$(su - postgres -c "psql -tAc \"SELECT 1 FROM pg_roles WHERE rolname='mirage_ro'\"" 2>/dev/null | tr -d ' ')
  new_ro=$(su - postgres -c "psql -tAc \"SELECT 1 FROM pg_roles WHERE rolname='mirage_indexer_ro'\"" 2>/dev/null | tr -d ' ')
  if [ "$old_ro" = "1" ] && [ "$new_ro" != "1" ]; then
    su - postgres -c "psql -c \"ALTER ROLE mirage_ro RENAME TO mirage_indexer_ro;\""
    su - postgres -c "psql -c \"ALTER ROLE mirage_indexer_ro WITH PASSWORD 'mirage_indexer_ro';\""
    echo "  ✓ Role renamed: mirage_ro → mirage_indexer_ro"
    changed=1
  fi

  # 4. Create mirage_backend role if needed
  local backend_role
  backend_role=$(su - postgres -c "psql -tAc \"SELECT 1 FROM pg_roles WHERE rolname='mirage_backend'\"" 2>/dev/null | tr -d ' ')
  if [ "$backend_role" != "1" ]; then
    su - postgres -c "psql -c \"CREATE ROLE mirage_backend WITH LOGIN PASSWORD 'mirage_backend';\""
    echo "  ✓ Created role: mirage_backend"
    changed=1
  fi

  # 5. Transfer mirage_backend DB ownership
  local backend_db_owner
  backend_db_owner=$(su - postgres -c "psql -tAc \"SELECT pg_catalog.pg_get_userbyid(datdba) FROM pg_database WHERE datname='mirage_backend'\"" 2>/dev/null | tr -d ' ')
  if [ -n "$backend_db_owner" ] && [ "$backend_db_owner" != "mirage_backend" ]; then
    su - postgres -c "psql -c \"ALTER DATABASE mirage_backend OWNER TO mirage_backend;\""
    su - postgres -c "psql -d mirage_backend -c \"REASSIGN OWNED BY ${backend_db_owner} TO mirage_backend;\"" 2>/dev/null || true
    echo "  ✓ mirage_backend DB ownership transferred"
    changed=1
  fi

  # 6. Grant schema privileges to renamed roles, re-grant RO, update env files
  if [ "$changed" = "1" ]; then
    # Ensure RW roles can create/own objects in their respective DBs
    su - postgres -c "psql -d mirage_indexer -c \"GRANT ALL ON SCHEMA public TO mirage_indexer;\"" 2>/dev/null || true
    su - postgres -c "psql -d mirage_indexer -c \"GRANT ALL ON ALL TABLES IN SCHEMA public TO mirage_indexer;\"" 2>/dev/null || true
    su - postgres -c "psql -d mirage_indexer -c \"GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO mirage_indexer;\"" 2>/dev/null || true
    su - postgres -c "psql -d mirage_backend -c \"GRANT ALL ON SCHEMA public TO mirage_backend;\"" 2>/dev/null || true
    su - postgres -c "psql -d mirage_backend -c \"GRANT ALL ON ALL TABLES IN SCHEMA public TO mirage_backend;\"" 2>/dev/null || true
    su - postgres -c "psql -d mirage_backend -c \"GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO mirage_backend;\"" 2>/dev/null || true
    # RO role for indexer
    su - postgres -c "psql -d mirage_indexer -c \"GRANT CONNECT ON DATABASE mirage_indexer TO mirage_indexer_ro;\"" 2>/dev/null || true
    su - postgres -c "psql -d mirage_indexer -c \"GRANT USAGE ON SCHEMA public TO mirage_indexer_ro;\"" 2>/dev/null || true
    su - postgres -c "psql -d mirage_indexer -c \"GRANT SELECT ON ALL TABLES IN SCHEMA public TO mirage_indexer_ro;\"" 2>/dev/null || true
    su - postgres -c "psql -d mirage_indexer -c \"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO mirage_indexer_ro;\"" 2>/dev/null || true

    python3 - <<'PYUPDATE'
import os
env_dir = os.environ.get("ENV_DIR", "")
for fname in ("backend.env", "indexer.env"):
    path = os.path.join(env_dir, fname)
    if not os.path.isfile(path):
        continue
    lines = []
    with open(path) as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith("#") or "=" not in s:
                lines.append(line)
                continue
            key, _, val = s.partition("=")
            key, val = key.strip(), val.strip()
            if key == "INDEXER_DB_URL":
                val = val.replace("mirage:mirage@", "mirage_indexer:mirage_indexer@")
                if val.rstrip("/").endswith("/mirage"):
                    val = val.rstrip("/").rsplit("/mirage", 1)[0] + "/mirage_indexer"
            elif key == "INDEXER_DB_RO_URL":
                val = val.replace("mirage_ro:mirage_ro@", "mirage_indexer_ro:mirage_indexer_ro@")
                if val.rstrip("/").endswith("/mirage"):
                    val = val.rstrip("/").rsplit("/mirage", 1)[0] + "/mirage_indexer"
            elif key == "BACKEND_DB_URL":
                val = val.replace("mirage:mirage@", "mirage_backend:mirage_backend@")
                val = val.replace("mirage_indexer:mirage_indexer@", "mirage_backend:mirage_backend@")
            lines.append(f"{key}={val}\n")
    with open(path, "w") as f:
        f.writelines(lines)
PYUPDATE

    load_env_files
    echo "  ✓ Env files updated with new DB/role names"
  fi
}
migrate_local_postgres_names
ensure_local_postgres_dbs

# Ensure backend schema exists before data migrations run
echo "==> Initializing backend schema (pre-migrations)..."
python3 - <<'PY'
from web.backend.db import init_backend_schema

init_backend_schema()
PY

# Same for the indexer schema. Data migrations query indexer tables, and until
# this ran here the indexer only created them once it started — which is after
# migrations — so any migration touching e.g. posts aborted the whole startup on
# a host that had never indexed a block.
echo "==> Initializing indexer schema (pre-migrations)..."
python3 - <<'PY'
import os

from indexer.database import DatabaseManager

DatabaseManager(os.environ["INDEXER_DB_URL"])
PY

# Run deploy migrations (one-time migrations + env sync with templates)
echo "==> Running deploy migrations..."
python3 -m deploy.migrations --config-dir "$ENV_DIR"

# Reload env files after migrations
load_env_files

# Local testnet: override peer config so re-render doesn't reintroduce real peers
# (init.sh does this too, but in a subprocess whose exports don't propagate back)
if [ "${SKIP_PEERS:-0}" = "1" ]; then
  export PERSISTENT_PEERS=""
  export PEX_ENABLED="false"
  export MAX_INBOUND_PEERS="0"
  export MAX_OUTBOUND_PEERS="0"
fi

# Re-run initialization so post-migration env values are rendered without
# discarding dynamically derived state-sync trust on a joining node.
echo "==> Re-rendering node config from updated env..."
bash "$ROOT_DIR/deploy/init.sh"

# Post-migration env is already exported in this process. Supervisor children
# inherit it when we exec, so there is no separate environment-sync step.

# Auto-configure HTTPS if domain is set (from node.env)
# Skip if Caddyfile already has HTTPS configured (www redirect indicates full HTTPS setup)
if [ -n "${DOMAIN:-}" ]; then
  if grep -q "^www\.${DOMAIN}" "$CADDYFILE" 2>/dev/null; then
    echo "==> HTTPS already configured for $DOMAIN (www redirect present)"
  else
    echo "==> Domain configured: $DOMAIN"
    echo "==> Configuring HTTPS automatically..."
    HTTPS_ARGS="--domain=$DOMAIN"
    if [ "${SKIP_HTTPS_IP_CHECK:-}" = "true" ]; then
      HTTPS_ARGS="$HTTPS_ARGS --skip-ip-check"
      echo "    (SKIP_HTTPS_IP_CHECK=1, skipping DNS-to-IP validation)"
    fi
    if ! python3 "$ROOT_DIR/deploy/setup_letsencrypt.py" $HTTPS_ARGS; then
      echo "WARNING: HTTPS setup failed (non-fatal). Caddy continues with existing config." >&2
      echo "         To retry: python3 $ROOT_DIR/deploy/setup_letsencrypt.py $HTTPS_ARGS" >&2
    fi
  fi
fi

# PebbleDB startup compaction (reclaim disk from pruning tombstones)
if [ -x "$COMPACT_BIN" ] && [ -d "$NODE_HOME/data" ]; then
  echo "==> Compacting PebbleDB databases (startup)..."
  if "$COMPACT_BIN" "$NODE_HOME/data" application blockstore state evidence; then
    echo "✓ PebbleDB compaction complete"
  else
    echo "WARNING: PebbleDB compaction failed (non-fatal)" >&2
  fi
fi


# Bootstrap PostgreSQL must release 5432 before Supervisor starts it in the
# foreground. Fast shutdown is enough: migrations already committed.
echo "==> Stopping bootstrap PostgreSQL so Supervisor can take it over..."
pg_ctlcluster 16 main stop -m fast
for _ in $(seq 1 30); do
  if ! pg_isready -h 127.0.0.1 -p 5432 -U postgres -t 1 >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
if pg_isready -h 127.0.0.1 -p 5432 -U postgres -t 1 >/dev/null 2>&1; then
  echo "ERROR: PostgreSQL still accepting connections after bootstrap stop" >&2
  exit 1
fi
echo "✓ Bootstrap PostgreSQL stopped"

mkdir -p /etc/supervisor/conf.d "$LOGS_DIR/supervisor"
install -m 0644 "$ROOT_DIR/deploy/templates/supervisor/supervisord.conf" /etc/supervisor/supervisord.conf
# Services are launched by supervisord using:
#   $ROOT_DIR/deploy/run_miraged_supervised.sh
#   $ROOT_DIR/deploy/run_indexer_supervised.sh
echo "==> Writing Supervisor program configuration..."
bash "$ROOT_DIR/deploy/write_supervisor_programs.sh"
if [ -n "${SKIP_UPGRADES:-}" ]; then
  echo "==> Skipping upgrades: $SKIP_UPGRADES"
fi

echo "✓ Bootstrap complete; handing off to supervisord as PID 1"
echo "  Watch live status from the host: mirage-status"
trap - SIGTERM SIGINT
# Close the bootstrap tee so it is not inherited as a child of PID 1.
exec 1>&3 2>&4
exec 3>&- 4>&-
exec supervisord -n -c /etc/supervisor/supervisord.conf
