#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="/opt/mirage"
DATA_DIR="${HOME}/.mirage"
NODE_HOME="$DATA_DIR/node"
BIN="$ROOT_DIR/blockchain/bin/miraged"
CHAIN_ID="mirage-1"
MARKER="$DATA_DIR/.initialized"
STATE_SYNC_COMPLETE="$DATA_DIR/.state_sync_complete"

echo "==> Init: NODE_HOME=$NODE_HOME"

mkdir -p "$NODE_HOME" "$NODE_HOME/config" "$NODE_HOME/data"

# SKIP_VALIDATOR_CHECK=1 skips key checks (used by reset_local_testnet.py)
if [ "${SKIP_VALIDATOR_CHECK:-0}" != "1" ]; then
  # Validator key must exist (imported by deploy.sh during --init)
  KEYRING_BACKEND="test"
  if ! $BIN keys show validator --home "$NODE_HOME" --keyring-backend "$KEYRING_BACKEND" >/dev/null 2>&1; then
    echo "ERROR: validator account key not found in keyring. Import it before startup." >&2
    echo "Hint: The deploy script imports the mnemonic into the node volume during --init." >&2
    exit 1
  fi
  echo "==> Validator key present"

  # Consensus key must exist (derived by deploy.sh during --init)
  if [ ! -f "$NODE_HOME/config/priv_validator_key.json" ]; then
    echo "ERROR: Consensus key missing: $NODE_HOME/config/priv_validator_key.json" >&2
    echo "Hint: On --init, the deploy script derives this from your mnemonic." >&2
    exit 1
  fi
  echo "==> Consensus key present"
else
  echo "==> Skipping validator/consensus key checks (SKIP_VALIDATOR_CHECK=1)"
fi

# Ensure priv_validator_state.json exists BEFORE miraged init (it needs this file)
if [ ! -f "$NODE_HOME/data/priv_validator_state.json" ]; then
  echo '{"height":"0","round":0,"step":0}' > "$NODE_HOME/data/priv_validator_state.json"
fi

# First run is detected before `miraged init`, which always writes a genesis.
FIRST_RUN=0
if [ ! -f "$NODE_HOME/config/genesis.json" ]; then
  FIRST_RUN=1
  echo "==> Running miraged init to create base config (node key, base config)..."
  $BIN init "validator" --chain-id "$CHAIN_ID" --home "$NODE_HOME"
fi

# A signed consensus height proves this is an existing validator, not a joining
# node. New nodes get a persistent completion marker as soon as state sync
# installs a non-zero height (entrypoint.sh owns that bounded watcher).
if [ -f "$NODE_HOME/data/priv_validator_state.json" ] && [ ! -f "$STATE_SYNC_COMPLETE" ]; then
  SIGNED_HEIGHT="$(python3 - "$NODE_HOME/data/priv_validator_state.json" <<'PY'
import json
import sys

height = json.load(open(sys.argv[1], encoding="utf-8"))["height"]
if not isinstance(height, str) or not height.isdigit():
    raise SystemExit("priv_validator_state.json height must be a decimal string")
print(height)
PY
)"
  if [ "$SIGNED_HEIGHT" -gt 0 ]; then
    touch "$STATE_SYNC_COMPLETE"
  fi
fi

# The genesis `miraged init` just wrote describes a new single-validator chain,
# never mirage-1. A joining node must replace it with the real one and derive
# fresh state-sync trust before every pre-sync restart. SKIP_PEERS=1 is the local
# testnet, which builds its own genesis and must not reach for the network.
BOOTSTRAP_STATESYNC=""
if [ "${SKIP_PEERS:-0}" != "1" ] && [ ! -f "$STATE_SYNC_COMPLETE" ]; then
  if [ "$FIRST_RUN" = "1" ]; then
    echo "==> Joining $CHAIN_ID: fetching network genesis and deriving state-sync trust..."
    BOOTSTRAP_ARGS=()
  else
    echo "==> Joining $CHAIN_ID: refreshing state-sync trust..."
    BOOTSTRAP_ARGS=(--trust-only)
  fi
  BOOTSTRAP_STATESYNC="$(NODE_HOME="$NODE_HOME" CHAIN_ID="$CHAIN_ID" \
    python3 "$ROOT_DIR/deploy/bootstrap_join.py" "${BOOTSTRAP_ARGS[@]}")"
fi

# Peer configuration (from node.env)
# For local testnet (SKIP_PEERS=1), disable peer connections to avoid validator set mismatches
R_ENV="$ROOT_DIR/deploy/templates/env"
R_NODE="$ROOT_DIR/deploy/templates/node"
R_CADDY="$ROOT_DIR/deploy/templates/caddy"
if [ "${SKIP_PEERS:-0}" = "1" ]; then
  echo "==> Local testnet mode, disabling peer connections"
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

# MONIKER names this node to its peers, and create_validator.sh records it
# on-chain at registration. The installer asks the operator for it, so a domain
# must not overwrite that answer. The site URL is only the default for a node
# that was never given a name, which is how the public nodes came to be called
# after their sites.
if [ -z "${MONIKER:-}" ] && [ -n "${DOMAIN:-}" ]; then
  MONIKER="https://${DOMAIN}"
fi
MONIKER="${MONIKER:-validator}"

if [ -z "${RETENTION_BLOCKS:-}" ]; then
  echo "ERROR: RETENTION_BLOCKS not set in node.env" >&2
  exit 1
fi
if ! [[ "$RETENTION_BLOCKS" =~ ^[0-9]+$ ]] || [ "$RETENTION_BLOCKS" -le 0 ]; then
  echo "ERROR: RETENTION_BLOCKS must be a positive integer" >&2
  exit 1
fi

if [ -z "${PRUNING_KEEP_RECENT:-}" ]; then
  echo "ERROR: PRUNING_KEEP_RECENT not set in node.env" >&2
  exit 1
fi
if ! [[ "$PRUNING_KEEP_RECENT" =~ ^[0-9]+$ ]] || [ "$PRUNING_KEEP_RECENT" -le 0 ]; then
  echo "ERROR: PRUNING_KEEP_RECENT must be a positive integer" >&2
  exit 1
fi

if [ -z "${PRUNING_INTERVAL:-}" ]; then
  echo "ERROR: PRUNING_INTERVAL not set in node.env" >&2
  exit 1
fi
if ! [[ "$PRUNING_INTERVAL" =~ ^[0-9]+$ ]] || [ "$PRUNING_INTERVAL" -le 0 ]; then
  echo "ERROR: PRUNING_INTERVAL must be a positive integer" >&2
  exit 1
fi

if [ -z "${SNAPSHOT_INTERVAL:-}" ]; then
  echo "ERROR: SNAPSHOT_INTERVAL not set in node.env" >&2
  exit 1
fi
if ! [[ "$SNAPSHOT_INTERVAL" =~ ^[0-9]+$ ]] || [ "$SNAPSHOT_INTERVAL" -le 0 ]; then
  echo "ERROR: SNAPSHOT_INTERVAL must be a positive integer" >&2
  exit 1
fi

if [ -z "${SNAPSHOT_KEEP_RECENT:-}" ]; then
  echo "ERROR: SNAPSHOT_KEEP_RECENT not set in node.env" >&2
  exit 1
fi
if ! [[ "$SNAPSHOT_KEEP_RECENT" =~ ^[0-9]+$ ]] || [ "$SNAPSHOT_KEEP_RECENT" -le 0 ]; then
  echo "ERROR: SNAPSHOT_KEEP_RECENT must be a positive integer" >&2
  exit 1
fi

# Derived state sync wins over the node.env defaults: those are static and
# cannot carry a trust height, which is only valid relative to the live head.
#
# Parsed, never eval'd. The trust hash and height originate from a remote node's
# RPC response, so shell metacharacters in either must not be executable — this
# runs as root, in the same window the operator's mnemonic is piped in. Only the
# four expected keys are accepted, and each value is validated before use.
if [ -n "$BOOTSTRAP_STATESYNC" ]; then
  while IFS='=' read -r ss_key ss_val; do
    [ -n "$ss_key" ] || continue
    case "$ss_key" in
      STATESYNC_ENABLE)
        if [ "$ss_val" != "true" ]; then
          echo "ERROR: bootstrap returned STATESYNC_ENABLE=$ss_val, expected 'true'" >&2
          exit 1
        fi
        STATESYNC_ENABLE="$ss_val"
        ;;
      STATESYNC_RPC_SERVERS)
        if [ -z "$ss_val" ]; then
          echo "ERROR: bootstrap returned an empty STATESYNC_RPC_SERVERS" >&2
          exit 1
        fi
        STATESYNC_RPC_SERVERS="$ss_val"
        ;;
      STATESYNC_TRUST_HEIGHT)
        if ! [[ "$ss_val" =~ ^[0-9]+$ ]] || [ "$ss_val" -le 0 ]; then
          echo "ERROR: bootstrap returned a non-numeric STATESYNC_TRUST_HEIGHT" >&2
          exit 1
        fi
        STATESYNC_TRUST_HEIGHT="$ss_val"
        ;;
      STATESYNC_TRUST_HASH)
        if ! [[ "$ss_val" =~ ^[0-9A-Fa-f]{64}$ ]]; then
          echo "ERROR: bootstrap returned a STATESYNC_TRUST_HASH that is not 64 hex chars" >&2
          exit 1
        fi
        STATESYNC_TRUST_HASH="$ss_val"
        ;;
      *)
        echo "ERROR: bootstrap returned an unexpected key: $ss_key" >&2
        exit 1
        ;;
    esac
  done <<< "$BOOTSTRAP_STATESYNC"
  echo "==> State sync enabled from trust height $STATESYNC_TRUST_HEIGHT"
fi

export MONIKER CHAIN_ID PERSISTENT_PEERS PEX_ENABLED MAX_INBOUND_PEERS MAX_OUTBOUND_PEERS RETENTION_BLOCKS PRUNING_KEEP_RECENT PRUNING_INTERVAL SNAPSHOT_INTERVAL SNAPSHOT_KEEP_RECENT APP_DB_BACKEND COMET_DB_BACKEND STATESYNC_ENABLE STATESYNC_RPC_SERVERS STATESYNC_TRUST_HEIGHT STATESYNC_TRUST_HASH

# Render templates atomically
OUT="$NODE_HOME/config"
mkdir -p "$OUT"

python3 "$ROOT_DIR/deploy/render_template.py" "$R_NODE/config.toml" "$OUT/config.toml"
python3 "$ROOT_DIR/deploy/render_template.py" "$R_NODE/app.toml" "$OUT/app.toml"
python3 "$ROOT_DIR/deploy/render_template.py" "$R_NODE/client.toml" "$OUT/client.toml"

# Caddyfile (HTTP only by default)
mkdir -p /etc/caddy
if ! python3 "$ROOT_DIR/deploy/render_template.py" "$R_CADDY/Caddyfile" "/etc/caddy/Caddyfile"; then
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
# Copy maintenance page (shown when backends are down during upgrades)
cp "$R_CADDY/maintenance.html" /etc/caddy/maintenance.html
echo "==> Caddyfile rendered and verified"

touch "$MARKER"
echo "==> Init complete."


