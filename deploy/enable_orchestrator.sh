#!/usr/bin/env bash
# Enable the bridge orchestrator for validators
# Usage: ./enable_orchestrator.sh [--solana-rpc URL] [--solana-ws URL] [--solana-program-id ID]
#
# This script:
# 1. Creates the orchestrator config directory
# 2. Renders the config template with current environment
# 3. Validates the configuration
#
# Prerequisites:
# - Node must be initialized (priv_validator_key.json must exist)
# - For Solana bridge: set ORCHESTRATOR_SOLANA_* environment variables
#
# Environment variables (set in ~/.mirage/env/orchestrator.env):
#   ORCHESTRATOR_SOLANA_ENABLED=true
#   ORCHESTRATOR_SOLANA_RPC=https://api.mainnet-beta.solana.com
#   ORCHESTRATOR_SOLANA_WS=wss://api.mainnet-beta.solana.com
#   ORCHESTRATOR_SOLANA_PROGRAM_ID=<program_id>
#   ORCHESTRATOR_SOLANA_KEYPAIR=/path/to/keypair.json
#   ORCHESTRATOR_KEY_NAME=validator

set -euo pipefail

ROOT_DIR="${ROOT_DIR:-/opt/mirage}"
DATA_DIR="${HOME}/.mirage"
ORCHESTRATOR_DIR="$DATA_DIR/orchestrator"
ORCHESTRATOR_CONFIG="$ORCHESTRATOR_DIR/config.yaml"
ORCHESTRATOR_ENV="$DATA_DIR/env/orchestrator.env"
TEMPLATE="$ROOT_DIR/deploy/templates/orchestrator/config.yaml"

# Parse arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --solana-rpc)
      export ORCHESTRATOR_SOLANA_RPC="$2"
      shift 2
      ;;
    --solana-ws)
      export ORCHESTRATOR_SOLANA_WS="$2"
      shift 2
      ;;
    --solana-program-id)
      export ORCHESTRATOR_SOLANA_PROGRAM_ID="$2"
      shift 2
      ;;
    --enable-solana)
      export ORCHESTRATOR_SOLANA_ENABLED="true"
      shift
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 1
      ;;
  esac
done

# Load existing env files
for envfile in "$DATA_DIR/env/node.env" "$DATA_DIR/env/secrets.env" "$ORCHESTRATOR_ENV"; do
  if [ -f "$envfile" ]; then
    set -a
    # shellcheck source=/dev/null
    . "$envfile"
    set +a
  fi
done

# Check prerequisites
if [ ! -f "$DATA_DIR/node/config/priv_validator_key.json" ]; then
  echo "ERROR: Node not initialized. Run init.sh first." >&2
  exit 1
fi

if [ ! -f "$TEMPLATE" ]; then
  echo "ERROR: Template not found: $TEMPLATE" >&2
  exit 1
fi

# Create orchestrator directory
mkdir -p "$ORCHESTRATOR_DIR"
mkdir -p "$DATA_DIR/env"
mkdir -p "$DATA_DIR/logs/orchestrator"

echo "==> Enabling bridge orchestrator..."

# Save environment to orchestrator.env for persistence
if [ -n "${ORCHESTRATOR_SOLANA_ENABLED:-}" ]; then
  {
    echo "# Orchestrator configuration"
    echo "ORCHESTRATOR_SOLANA_ENABLED=${ORCHESTRATOR_SOLANA_ENABLED:-false}"
    echo "ORCHESTRATOR_SOLANA_RPC=${ORCHESTRATOR_SOLANA_RPC:-}"
    echo "ORCHESTRATOR_SOLANA_WS=${ORCHESTRATOR_SOLANA_WS:-}"
    echo "ORCHESTRATOR_SOLANA_PROGRAM_ID=${ORCHESTRATOR_SOLANA_PROGRAM_ID:-}"
    echo "ORCHESTRATOR_SOLANA_KEYPAIR=${ORCHESTRATOR_SOLANA_KEYPAIR:-$ORCHESTRATOR_DIR/solana-keypair.json}"
    echo "ORCHESTRATOR_KEY_NAME=${ORCHESTRATOR_KEY_NAME:-validator}"
  } > "$ORCHESTRATOR_ENV"
  echo "✓ Saved orchestrator environment to $ORCHESTRATOR_ENV"
fi

# Render config template
echo "==> Rendering orchestrator config..."
python3 "$ROOT_DIR/deploy/render_template.py" "$TEMPLATE" "$ORCHESTRATOR_CONFIG"

if [ ! -f "$ORCHESTRATOR_CONFIG" ]; then
  echo "ERROR: Failed to render orchestrator config" >&2
  exit 1
fi

echo "✓ Orchestrator config created: $ORCHESTRATOR_CONFIG"

# Check orchestrator binary exists
ORCHESTRATOR_BIN="$ROOT_DIR/blockchain/mirage-orchestrator"
if [ ! -f "$ORCHESTRATOR_BIN" ]; then
  echo "WARNING: Orchestrator binary not found at $ORCHESTRATOR_BIN" >&2
  echo "         The binary should be included in the Docker image." >&2
  echo "         If running locally, build with: cd blockchain && make build-orchestrator" >&2
fi

# Validate Solana setup if enabled
if [ "${ORCHESTRATOR_SOLANA_ENABLED:-false}" = "true" ]; then
  if [ -z "${ORCHESTRATOR_SOLANA_PROGRAM_ID:-}" ]; then
    echo "WARNING: ORCHESTRATOR_SOLANA_PROGRAM_ID not set - Solana bridge will fail" >&2
  fi
  KEYPAIR_PATH="${ORCHESTRATOR_SOLANA_KEYPAIR:-$ORCHESTRATOR_DIR/solana-keypair.json}"
  if [ ! -f "$KEYPAIR_PATH" ]; then
    echo "WARNING: Solana keypair not found at $KEYPAIR_PATH" >&2
    echo "         Create one with: solana-keygen new -o $KEYPAIR_PATH" >&2
  fi
fi

echo ""
echo "✓ Orchestrator enabled!"
echo ""
echo "The orchestrator will start automatically on next container restart."
echo "To start it now, run in tmux:"
echo "  $ORCHESTRATOR_BIN --config \"$ORCHESTRATOR_CONFIG\""
echo ""
if [ "${ORCHESTRATOR_SOLANA_ENABLED:-false}" = "true" ]; then
  echo "Solana bridge: ENABLED"
  echo "  Program ID: ${ORCHESTRATOR_SOLANA_PROGRAM_ID:-NOT SET}"
  echo "  RPC: ${ORCHESTRATOR_SOLANA_RPC:-default}"
else
  echo "Solana bridge: DISABLED (set ORCHESTRATOR_SOLANA_ENABLED=true to enable)"
fi
