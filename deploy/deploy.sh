#!/usr/bin/env bash
set -euo pipefail

# Remote deployment script for Mirage
# Usage: deploy/deploy.sh user@host [--init|--update] [--file TARBALL] [--moniker VALUE]
#
# Notes:
# - Moniker defaults to "mirage-node" and can be overridden with --moniker
# - Domain/TLS: Configure HTTPS inside the container using letsencrypt_register.sh (domain is persisted automatically)
# - For local testing, use scripts/reset_local_testnet.py instead
#

show_help() {
  cat <<EOF
Mirage Remote Deployment

Usage: deploy/deploy.sh user@host [--init|--update] [--file TARBALL] [--moniker VALUE]
       deploy/deploy.sh --build-only [--file TARBALL]

Arguments:
  user@host            SSH connection string (e.g., root@159.203.114.27)

Modes (exactly one required, except for --build-only):
  --init               First-time setup: build, upload, start container.
                       Prompts for mnemonic and imports it before startup.
                       REQUIRES --moniker to be explicitly provided.
  --update             Update image and restart container. Preserves data.
                       Re-renders configs on startup (idempotent).
  --build-only         Build Docker image and create tarball without deploying.

Options:
  --file TARBALL       For deploy modes: skip build and use the provided tarball.
                       For --build-only: specify output tarball path.
  --moniker VALUE      Set CometBFT node moniker (default: mirage-node, REQUIRED for --init)

Local testing:
  For local development with production data, use scripts/reset_local_testnet.py instead.

Remote access:
  ssh user@host 'docker logs mirage'
  ssh -t user@host 'docker exec -it mirage tmux attach -t mirage'
EOF
}

if [ "${1-}" = "" ] || [ "${1-}" = "--help" ] || [ "${1-}" = "-h" ]; then
  show_help
  exit 0
fi

# Check if first arg is --build-only (no remote required)
BUILD_ONLY=0
if [ "${1-}" = "--build-only" ]; then
  BUILD_ONLY=1
  shift
  REMOTE=""
else
  REMOTE="$1"; shift
fi

MODE=""
TARBALL_FILE=""
MONIKER_VALUE="mirage-node"
while [ $# -gt 0 ]; do
  case "$1" in
    --build-only) BUILD_ONLY=1 ; shift ;;
    --init) MODE="init" ; shift ;;
    --update) MODE="update" ; shift ;;
    --moniker=*)
      MONIKER_VALUE="${1#*=}"
      shift
      ;;
    --moniker)
      if [ $# -lt 2 ]; then
        echo "ERROR: --moniker requires a value" >&2
        exit 1
      fi
      MONIKER_VALUE="$2"
      shift 2
      ;;
    --file=*)
      TARBALL_FILE="${1#*=}"
      shift
      ;;
    --file)
      if [ $# -lt 2 ]; then
        echo "ERROR: --file requires a tarball path" >&2
        exit 1
      fi
      TARBALL_FILE="$2"
      shift 2
      ;;
    *) echo "Unknown argument: $1" >&2; echo "Run with --help for usage information." >&2; exit 1 ;;
  esac
done

# Handle --build-only mode
if [ "$BUILD_ONLY" -eq 1 ]; then
  echo "==> Build-only mode: building Docker image..."
  
  if [ -n "$TARBALL_FILE" ]; then
    TARBALL="$TARBALL_FILE"
  else
    TARBALL="deploy/mirage-docker-dev.tar.gz"
  fi
  
  echo "==> Generating protobuf files and building miraged binary..."
  (
    cd "$(dirname "$0")/.."
    cd blockchain && make proto-gen && make install && cd ..
  )

  echo "==> Building Docker image..."
  (
    cd "$(dirname "$0")/.."
    docker buildx build --load -t mirage:prod -f deploy/Dockerfile .
  )

  echo "==> Saving Docker image to tarball..."
  mkdir -p "$(dirname "$TARBALL")"
  docker save mirage:prod | gzip > "$TARBALL"
  
  echo "==> Build complete. Tarball saved to: $TARBALL"
  exit 0
fi

if [ -z "$MODE" ]; then
  echo "ERROR: one of --init or --update is required." >&2
  exit 1
fi

if [ -n "$TARBALL_FILE" ] && [ ! -f "$TARBALL_FILE" ]; then
  echo "ERROR: Tarball file not found: $TARBALL_FILE" >&2
  exit 1
fi

REMOTE_HOST="${REMOTE##*@}"

# Helper function to close SSH control socket
close_ssh_socket() {
  ssh -o ControlPath=/tmp/mirage-ssh-%r@%h:%p -O exit "$REMOTE" 2>/dev/null || true
}

# Establish SSH control socket for re-use
echo "==> Establishing SSH control socket..."
ssh -o PreferredAuthentications=publickey,password,keyboard-interactive -o StrictHostKeyChecking=accept-new -o ControlMaster=auto -o ControlPath=/tmp/mirage-ssh-%r@%h:%p -o ControlPersist=300 "$REMOTE" 'exit'

# Early sanity check for --init: consensus key must NOT already exist on remote
if [ "$MODE" = "init" ]; then
  echo "==> Sanity check: remote consensus key must not exist..."
  if ssh -o ControlPath=/tmp/mirage-ssh-%r@%h:%p "$REMOTE" "test -f ~/.mirage/main/config/priv_validator_key.json"; then
    echo "ERROR: Found existing ~/.mirage/main/config/priv_validator_key.json on remote. Aborting to avoid accidental overwrite." >&2
    echo "If this server was previously used, provision a fresh server or remove the file manually with extreme caution." >&2
    close_ssh_socket
    exit 1
  fi
fi

# Ensure docker on remote
echo "==> Ensuring Docker is installed on remote..."
ssh -o ControlPath=/tmp/mirage-ssh-%r@%h:%p "$REMOTE" '
  set -euo pipefail
  if ! command -v docker >/dev/null 2>&1; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -y
    apt-get install -y docker.io
    systemctl enable --now docker
  fi
'

# No seed file verification required
# Build binary and Docker image locally (unless --file is provided)
if [ -n "$TARBALL_FILE" ]; then
  TARBALL="$TARBALL_FILE"
  echo "==> Using provided tarball: $TARBALL"
else
  TARBALL="deploy/mirage-docker-dev.tar.gz"
  echo "==> Generating protobuf files and building miraged binary..."
  (
    cd "$(dirname "$0")/.."
    cd blockchain && make proto-gen && make install && cd ..
  )

  echo "==> Building Docker image..."
  (
    cd "$(dirname "$0")/.."
    docker buildx build --load -t mirage:prod -f deploy/Dockerfile .
  )

  echo "==> Saving Docker image to tarball..."
  mkdir -p "$(dirname "$TARBALL")"
  docker save mirage:prod | gzip > "$TARBALL"
fi

echo "==> Uploading image..."
ssh -o ControlPath=/tmp/mirage-ssh-%r@%h:%p "$REMOTE" 'rm -f /tmp/mirage-docker.tar.gz'
scp -o ControlPath=/tmp/mirage-ssh-%r@%h:%p "$TARBALL" "$REMOTE:/tmp/mirage-docker.tar.gz"

echo "==> Stopping old container..."
ssh -o ControlPath=/tmp/mirage-ssh-%r@%h:%p "$REMOTE" '
  set -euo pipefail
  if docker ps -a --format "{{.Names}}" | grep -qx mirage; then
    docker stop --timeout=60 mirage
    docker rm mirage
  fi
  if docker images --format "{{.Repository}}:{{.Tag}}" | grep -qx mirage:prod; then
    docker rmi mirage:prod
  fi
  docker system prune -f
'

echo "==> Loading image on remote..."
ssh -o ControlPath=/tmp/mirage-ssh-%r@%h:%p "$REMOTE" 'gunzip < /tmp/mirage-docker.tar.gz | docker load && rm -f /tmp/mirage-docker.tar.gz'

# For --init: enforce --moniker is provided
if [ "$MODE" = "init" ]; then
  if [ "$MONIKER_VALUE" = "mirage-node" ]; then
    echo "ERROR: --init requires --moniker to be explicitly provided" >&2
    echo "   Example: deploy/deploy.sh user@host --init --moniker 'my-validator-name'" >&2
    exit 1
  fi
  echo "==> Preparing validator keys (consensus + account)..."
  # shellcheck disable=SC2162
  read -s -p "Enter 12-word mnemonic for the funded account: " MNEMONIC
  echo ""
  if [ -z "${MNEMONIC:-}" ]; then
    echo "ERROR: Empty mnemonic entered." >&2
    exit 1
  fi
  # Validate mnemonic is exactly 12 words
  WORD_COUNT=$(echo "$MNEMONIC" | wc -w)
  if [ "$WORD_COUNT" -ne 12 ]; then
    echo "ERROR: Mnemonic must be exactly 12 words (got $WORD_COUNT words)." >&2
    exit 1
  fi
  # Ensure data dirs exist on remote
  ssh -o ControlPath=/tmp/mirage-ssh-%r@%h:%p "$REMOTE" 'mkdir -p ~/.mirage/main/config ~/.caddy'
  # Prompt for consensus derivation index (default 0)
  read -p "Consensus derivation index [0] (default 0; do not change unless rotating): " CONS_INDEX
  CONS_INDEX="${CONS_INDEX:-0}"
  if ! echo "$CONS_INDEX" | grep -Eq '^[0-9]+$'; then
    echo "ERROR: Derivation index must be a non-negative integer." >&2
    exit 1
  fi
  # Double-check consensus key doesn't exist on remote (sanity check before deriving)
  if ssh -o ControlPath=/tmp/mirage-ssh-%r@%h:%p "$REMOTE" "test -f ~/.mirage/main/config/priv_validator_key.json"; then
    echo "ERROR: Consensus key already exists on remote. Aborting to avoid overwrite." >&2
    exit 1
  fi
  # Derive consensus key on remote using Docker
  echo "==> Deriving consensus key on remote..."
  if ! echo "$MNEMONIC" | ssh -o ControlPath=/tmp/mirage-ssh-%r@%h:%p "$REMOTE" "MIRAGE_DERIVATION_INDEX='$CONS_INDEX' docker run --rm -i \
    --entrypoint python3 \
    -v ~/.mirage:/root/.mirage \
      mirage:prod /opt/mirage/deploy/derive_consensus_key.py --home /root/.mirage/main"; then
  echo "ERROR: Failed to derive consensus key." >&2
  exit 1
  fi
  # Set correct permissions on remote
  ssh -o ControlPath=/tmp/mirage-ssh-%r@%h:%p "$REMOTE" 'chmod 600 ~/.mirage/main/config/priv_validator_key.json'
  echo "✓ Consensus key derived (index $CONS_INDEX)."
  # Import using a one-shot container into the mounted volume to avoid storing the mnemonic as an env var
  if ! echo "$MNEMONIC" | ssh -o ControlPath=/tmp/mirage-ssh-%r@%h:%p "$REMOTE" "docker run --rm -i \
    --entrypoint /bin/sh \
    -v ~/.mirage:/root/.mirage \
      mirage:prod -lc '/opt/mirage/blockchain/miraged keys add validator --recover --home /root/.mirage/main --keyring-backend test >/dev/null 2>&1'"; then
  echo "ERROR: Failed to import mnemonic into keyring volume." >&2
  exit 1
  fi
  unset MNEMONIC || true
  echo "✓ Account key imported into keyring."
fi

echo "==> Starting container..."

# Persist caddy data for future TLS issuance; persist node data under ~/.mirage
ssh -o ControlPath=/tmp/mirage-ssh-%r@%h:%p "$REMOTE" 'mkdir -p ~/.caddy ~/.mirage'

# One-time migration: move ~/.hermes to ~/.mirage/hermes (old volume mount location)
ssh -o ControlPath=/tmp/mirage-ssh-%r@%h:%p "$REMOTE" '
  if [ -d ~/.hermes ] && [ ! -L ~/.hermes ] && [ ! -e ~/.mirage/hermes ]; then
    echo "==> Migrating ~/.hermes to ~/.mirage/hermes..."
    mv ~/.hermes ~/.mirage/hermes
  elif [ -d ~/.hermes ] && [ ! -L ~/.hermes ] && [ -d ~/.mirage/hermes ]; then
    echo "==> Merging ~/.hermes into ~/.mirage/hermes..."
    cp -a ~/.hermes/. ~/.mirage/hermes/
    rm -rf ~/.hermes
  fi
'

# Initialize persistent config directory and seed env files if missing (for --init)
if [ "$MODE" = "init" ]; then
  echo "==> Ensuring persistent config files exist on remote..."
  ssh -o ControlPath=/tmp/mirage-ssh-%r@%h:%p "$REMOTE" 'mkdir -p ~/.mirage/env'
  # Copy env templates if they don't exist on remote
  for f in "$(dirname "$0")/templates/env"/*.env; do
    if [ -f "$f" ]; then
      fname="$(basename "$f")"
      # Only copy if file doesn't exist on remote (preserve user customizations)
      ssh -o ControlPath=/tmp/mirage-ssh-%r@%h:%p "$REMOTE" "[ -f ~/.mirage/env/$fname ]" 2>/dev/null || scp -o ControlPath=/tmp/mirage-ssh-%r@%h:%p "$f" "$REMOTE:~/.mirage/env/$fname"
    fi
  done
  # Persist moniker during first-time init
  if [ -n "$MONIKER_VALUE" ]; then
    ssh -o ControlPath=/tmp/mirage-ssh-%r@%h:%p "$REMOTE" "bash -lc 'set -euo pipefail; FILE=\$HOME/.mirage/env/node.env; touch \"\$FILE\"; if grep -q \"^MONIKER=\" \"\$FILE\"; then sed -i \"s/^MONIKER=.*/MONIKER=\\\"$MONIKER_VALUE\\\"/\" \"\$FILE\"; else echo MONIKER=\\\"$MONIKER_VALUE\\\" >> \"\$FILE\"; fi'"
  fi
fi


# For --update modes, read MONIKER from existing node.env if not explicitly provided
if [ "$MODE" != "init" ] && [ "$MONIKER_VALUE" = "mirage-node" ]; then
  echo "==> Reading existing MONIKER from node.env..."
  EXISTING_MONIKER=$(ssh -o ControlPath=/tmp/mirage-ssh-%r@%h:%p "$REMOTE" "grep -E '^MONIKER=' ~/.mirage/env/node.env 2>/dev/null | cut -d= -f2 | tr -d '\"'" || echo "")
  if [ -n "$EXISTING_MONIKER" ] && [ "$EXISTING_MONIKER" != "mirage-node" ]; then
    MONIKER_VALUE="$EXISTING_MONIKER"
    echo "    Using existing moniker: $MONIKER_VALUE"
  fi
fi

PORTS="-p 80:80 -p 26656:26656 -p 26657:26657 -p 443:443"
MONIKER_ARG=""
HOSTNAME_ARG=""
if [ -n "$MONIKER_VALUE" ] && [ "$MONIKER_VALUE" != "mirage-node" ]; then
  MONIKER_ARG="-e MONIKER=\"$MONIKER_VALUE\""
  # Strip protocol and replace invalid chars for valid hostname
  CLEAN_HOSTNAME=$(echo "$MONIKER_VALUE" | sed 's|https\?://||' | tr './:' '-')
  HOSTNAME_ARG="--hostname $CLEAN_HOSTNAME"
fi
ssh -o ControlPath=/tmp/mirage-ssh-%r@%h:%p "$REMOTE" "ENV_ARGS=\"\"; for f in backend node indexer frontend secrets; do if [ -f \$HOME/.mirage/env/\$f.env ]; then ENV_ARGS=\"\$ENV_ARGS --env-file \$HOME/.mirage/env/\$f.env\"; fi; done; docker run -d $PORTS \$ENV_ARGS --name mirage --restart unless-stopped $HOSTNAME_ARG $MONIKER_ARG -v \$HOME/.mirage:/root/.mirage -v \$HOME/.caddy:/root/.local/share/caddy mirage:prod"

echo "==> Waiting briefly for container to become healthy..."
sleep 2

# Ensure container is running and stable (handle restart loop) before docker exec
echo "==> Waiting for container to be running and stable..."
STABILITY_CHECK='
set -euo pipefail
consec=0
for i in $(seq 1 60); do
  st=$(docker inspect -f "{{.State.Status}}" mirage 2>/dev/null || echo "notfound")
  echo "[$i/60] Container status: $st (consecutive stable checks: $consec)"
  if [ "$st" = "restarting" ]; then
    consec=0
    echo "  -> Waiting for restart to complete..."
    sleep 1
    continue
  elif [ "$st" = "running" ]; then
    if docker exec mirage echo ready >/dev/null 2>&1; then
      consec=$((consec+1))
      echo "  -> Docker exec successful (need 3 consecutive)"
      if [ "$consec" -ge 3 ]; then
        echo "  -> Container is stable!"
        exit 0
      fi
    else
      echo "  -> Docker exec failed, resetting counter"
      consec=0
    fi
  else
    if [ "$st" != "notfound" ]; then
      echo "  -> ERROR: Container status is $st (not running)"
      docker logs --tail 20 mirage 2>&1 | sed "s/^/    /" || true
    fi
    consec=0
  fi
  sleep 1
done
echo "ERROR: Container not stable after 60s (last status: $st)" >&2
docker logs --tail 100 mirage 2>&1 | tail -100 | sed "s/^/  /" >&2
exit 1
'
ssh -o ControlPath=/tmp/mirage-ssh-%r@%h:%p "$REMOTE" "bash -c '$STABILITY_CHECK'"

# On init only, create the validator if it doesn't exist yet (idempotent)
if [ "$MODE" = "init" ]; then
  echo "==> Ensuring validator exists on-chain..."
  echo "==> Running create_validator.sh inside container (remote) with moniker: $MONIKER_VALUE"
  ssh -o ControlPath=/tmp/mirage-ssh-%r@%h:%p "$REMOTE" "docker exec -i mirage bash -c \"MONIKER=\\\"$MONIKER_VALUE\\\" bash /opt/mirage/deploy/create_validator.sh\""
fi

# For --update: update validator moniker on-chain if it differs
if [ "$MODE" = "update" ]; then
  if [ -n "$MONIKER_VALUE" ] && [ "$MONIKER_VALUE" != "mirage-node" ]; then
    echo "==> Checking if validator moniker needs update..."
    MONIKER_UPDATE_SCRIPT=$'# Ensure strict mode in container\nset -euo pipefail\ncd /opt/mirage\nVALOPER=$(/opt/mirage/blockchain/miraged keys show validator --home /root/.mirage/main --keyring-backend test --bech val -a 2>/dev/null || echo \"\")\nif [ -z \"$VALOPER\" ]; then\n  echo \"Validator not found, skipping moniker update\"\n  exit 0\nfi\nCURRENT=$(/opt/mirage/blockchain/miraged q staking validator \"$VALOPER\" --home /root/.mirage/main --node tcp://127.0.0.1:26657 -o json 2>/dev/null | jq -r \".validator.description.moniker // \\\"\\\"\" || echo \"\")\nif [ \"$CURRENT\" = \"${NEW_MONIKER:-}\" ]; then\n  echo \"Validator moniker already set to \\\"${NEW_MONIKER:-}\\\"\"\n  exit 0\nfi\necho \"Updating validator moniker from \\\"$CURRENT\\\" to \\\"${NEW_MONIKER:-}\\\"\"\n/opt/mirage/blockchain/miraged tx staking edit-validator --new-moniker=\"${NEW_MONIKER:-}\" \\\n  --from validator --home /root/.mirage/main --keyring-backend test \\\n  --chain-id mirage-1 --node tcp://127.0.0.1:26657 --gas auto --gas-adjustment 1.5 -y >/dev/null 2>&1 || true\n'
    echo "$MONIKER_UPDATE_SCRIPT" | ssh -o ControlPath=/tmp/mirage-ssh-%r@%h:%p "$REMOTE" "docker exec -e NEW_MONIKER=\"$MONIKER_VALUE\" -i mirage bash -seuo pipefail"
  fi
fi

echo "==> Done. Container 'mirage' is running on $REMOTE_HOST."
echo "    To configure HTTPS (domain will persist for future deployments):"
echo "      ssh $REMOTE 'docker exec mirage bash /opt/mirage/deploy/letsencrypt_register.sh --domain=yourdomain.com'"
echo ""
echo "Remote container access:"
echo "  Attach tmux session:"
echo "    ssh -t $REMOTE 'docker exec -it mirage tmux attach -t mirage'"
echo "  Shell into container:"
echo "    ssh -t $REMOTE 'docker exec -it mirage bash'"
echo "  Follow logs:"
echo "    ssh $REMOTE 'docker logs -f mirage'"

close_ssh_socket
