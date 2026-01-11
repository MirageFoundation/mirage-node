#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="/opt/mirage"
DATA_DIR="${HOME}/.mirage"
NODE_HOME="$DATA_DIR/main"
BIN="$ROOT_DIR/blockchain/miraged"
CHAIN_ID="mirage-1"
MARKER="$DATA_DIR/.initialized"
MIGRATE="${MIGRATE_CONFIG:-0}"

echo "==> Init: NODE_HOME=$NODE_HOME MIGRATE=$MIGRATE"

mkdir -p "$NODE_HOME" "$NODE_HOME/config" "$NODE_HOME/data" "$NODE_HOME/data/indexer"

# Import validator key from seed on first init (idempotent)
KEYRING_BACKEND="test"
if [ "$MIGRATE" != "1" ]; then
  if ! $BIN keys show validator --home "$NODE_HOME" --keyring-backend "$KEYRING_BACKEND" >/dev/null 2>&1; then
    echo "ERROR: validator account key not found in keyring. Import it before startup." >&2
    echo "Hint: The deploy script imports the mnemonic into the node volume during --init." >&2
    exit 1
  else
    echo "==> Validator key already present in keyring"
  fi
fi

# Require consensus key to exist and never generate automatically
if [ ! -f "$NODE_HOME/config/priv_validator_key.json" ]; then
  echo "ERROR: Consensus key missing: $NODE_HOME/config/priv_validator_key.json" >&2
  echo "Hint: On --init, the deploy script derives this from your mnemonic (index default 0) before start." >&2
  exit 1
fi
echo "==> Consensus key present"

# Ensure priv_validator_state.json exists BEFORE miraged init (it needs this file)
if [ ! -f "$NODE_HOME/data/priv_validator_state.json" ]; then
  echo '{"height":"0","round":0,"step":0}' > "$NODE_HOME/data/priv_validator_state.json"
fi

# Initialize default config state once (genesis and client.toml), but we will replace config files with templates below
if [ "$MIGRATE" != "1" ] && [ ! -f "$NODE_HOME/config/genesis.json" ]; then
  echo "==> Running miraged init to create base config (genesis)..."
  $BIN init "validator" --chain-id "$CHAIN_ID" --home "$NODE_HOME"
fi

# Peer configuration (from node.env)
# For local deployment, skip external peers to avoid validator set mismatches
R="$ROOT_DIR/deploy/templates"
if [ "${MIRAGE_MODE:-}" = "local" ] || [ "${SKIP_PEERS:-0}" = "1" ]; then
  echo "==> Local deployment detected, disabling peer connections"
  PERSISTENT_PEERS=""
  PEX_ENABLED="false"
  MAX_INBOUND_PEERS="0"
  MAX_OUTBOUND_PEERS="0"
else
  # Use env values (from node.env), with sensible defaults
  PERSISTENT_PEERS="${PERSISTENT_PEERS:-}"
  PEX_ENABLED="${PEX_ENABLED:-true}"
  MAX_INBOUND_PEERS="${MAX_INBOUND_PEERS:-40}"
  MAX_OUTBOUND_PEERS="${MAX_OUTBOUND_PEERS:-10}"
fi

export MONIKER CHAIN_ID PERSISTENT_PEERS PEX_ENABLED MAX_INBOUND_PEERS MAX_OUTBOUND_PEERS

# Render templates atomically
OUT="$NODE_HOME/config"
mkdir -p "$OUT"

python3 "$ROOT_DIR/deploy/render_template.py" "$R/config.toml" "$OUT/config.toml"
python3 "$ROOT_DIR/deploy/render_template.py" "$R/app.toml" "$OUT/app.toml"
python3 "$ROOT_DIR/deploy/render_template.py" "$R/client.toml" "$OUT/client.toml"

# Caddyfile (HTTP only by default)
mkdir -p /etc/caddy
if ! python3 "$ROOT_DIR/deploy/render_template.py" "$R/Caddyfile" "/etc/caddy/Caddyfile"; then
  echo "ERROR: Failed to render Caddyfile" >&2
  exit 1
fi
# Verify Caddyfile was rendered correctly
if ! grep -q "reverse_proxy.*127.0.0.1:5000" /etc/caddy/Caddyfile; then
  echo "ERROR: Caddyfile missing API proxy configuration" >&2
  echo "Caddyfile contents:" >&2
  cat /etc/caddy/Caddyfile >&2
  exit 1
fi
echo "==> Caddyfile rendered and verified"

touch "$MARKER"
echo "==> Init complete."


