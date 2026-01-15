#!/usr/bin/env bash
set -euo pipefail

# Deployment script for Mirage
# Usage: deploy/deploy.sh user@host [--init|--update] [--file TARBALL] [--moniker VALUE] [--proxyjump HOST]
#        deploy/deploy.sh --local [--init|--update] [--file TARBALL]
#
# Notes:
# - Moniker defaults to "mirage-node" and can be overridden with --moniker
# - Domain/TLS: Configure HTTPS inside the container using letsencrypt_register.sh (domain is persisted automatically)
# - Use --local for local Docker deployment (no SSH)
# - Use --proxyjump for slow/high-latency servers (routes traffic through a jump host)
#

show_help() {
  cat <<EOF
Mirage Remote Deployment

Usage: deploy/deploy.sh user@host [--init|--update] [--file TARBALL] [--moniker VALUE] [--proxyjump HOST]
       deploy/deploy.sh --local [--init|--update] [--file TARBALL]
       deploy/deploy.sh --build-only [--file TARBALL]

Arguments:
  user@host            SSH connection string (e.g., root@159.203.114.27)
  --local              Deploy to local Docker container (no SSH)

Modes (exactly one required, except for --build-only):
  --init               First-time setup: build, upload, start container.
                       Prompts for mnemonic and imports it before startup.
                       REQUIRES --moniker to be explicitly provided.
  --update             Update image and restart container. Preserves data.
                       Re-renders configs on startup (idempotent).
  --build-only         Build Docker image only (default: pushes to registry; use --file to save tarball).

Options:
  --file TARBALL       Use tarball flow (legacy fallback). If omitted, deploy uses GHCR by default.
  --moniker VALUE      Set CometBFT node moniker (default: mirage-node, REQUIRED for --init)
  --proxyjump HOST     Route traffic through a jump host (for high-latency servers).
                       Example: --proxyjump mirage.vote
  --prune              Run docker system prune during update (slow; not recommended).

Local deployment:
  deploy/deploy.sh --local --update

Remote access:
  ssh user@host 'docker logs mirage'
  ssh -t user@host 'docker exec -it mirage tmux attach -t mirage'
EOF
}

if [ "${1-}" = "" ] || [ "${1-}" = "--help" ] || [ "${1-}" = "-h" ]; then
  show_help
  exit 0
fi

# Check if first arg is --build-only or --local (no remote required)
BUILD_ONLY=0
LOCAL_MODE=0
if [ "${1-}" = "--build-only" ]; then
  BUILD_ONLY=1
  shift
  REMOTE=""
elif [ "${1-}" = "--local" ]; then
  LOCAL_MODE=1
  shift
  REMOTE=""
else
  REMOTE="$1"; shift
fi

MODE=""
TARBALL_FILE=""
MONIKER_VALUE="mirage-node"
PROXYJUMP=""
PRUNE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --build-only) BUILD_ONLY=1 ; shift ;;
    --init) MODE="init" ; shift ;;
    --update) MODE="update" ; shift ;;
    --prune) PRUNE=1 ; shift ;;
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
    --proxyjump=*)
      PROXYJUMP="${1#*=}"
      shift
      ;;
    --proxyjump|-J)
      if [ $# -lt 2 ]; then
        echo "ERROR: --proxyjump requires a jump host" >&2
        exit 1
      fi
      PROXYJUMP="$2"
      shift 2
      ;;
    *) echo "Unknown argument: $1" >&2; echo "Run with --help for usage information." >&2; exit 1 ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

GIT_BRANCH="$(git -C "$REPO_ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")"
GIT_HASH="$(git -C "$REPO_ROOT" rev-parse --short HEAD 2>/dev/null || date +%Y%m%d%H%M%S)"

REGISTRY_HOST="ghcr.io"
REGISTRY_IMAGE="miragefoundation/mirage-node"
IMAGE_REF="$REGISTRY_HOST/$REGISTRY_IMAGE"
IMAGE_SHA_TAG="$IMAGE_REF:$GIT_HASH"
IMAGE_MOVING_TAG=""
if [ "$GIT_BRANCH" = "dev" ] || [ "$GIT_BRANCH" = "prod" ]; then
  IMAGE_MOVING_TAG="$IMAGE_REF:$GIT_BRANCH"
fi

cache_dir() {
  local base="${XDG_CACHE_HOME:-$HOME/.cache}/mirage/deploy"
  mkdir -p "$base"
  echo "$base"
}

hash_tree() {
  # hash_tree <abs_path_1> [<abs_path_2> ...]
  # Computes a stable hash of file contents under the provided paths.
  local tmp
  tmp="$(mktemp)"
  for p in "$@"; do
    if [ -e "$p" ]; then
      find "$p" -type f -print0
    fi
  done | sort -z | xargs -0 sha256sum 2>/dev/null > "$tmp" || true
  sha256sum "$tmp" | awk '{print $1}'
  rm -f "$tmp"
}

maybe_proto_gen_and_go_build() {
  echo "==> Checking whether proto/go rebuild is needed..."
  local cdir
  cdir="$(cache_dir)"

  local proto_hash_file="$cdir/proto.${GIT_BRANCH}.sha256"
  local go_hash_file="$cdir/go.${GIT_BRANCH}.sha256"

  local new_proto_hash
  new_proto_hash="$(hash_tree \
    "$REPO_ROOT/blockchain/proto" \
    "$REPO_ROOT/blockchain/buf.yaml" \
    "$REPO_ROOT/blockchain/buf.lock" \
    "$REPO_ROOT/blockchain/proto/buf.gen.gogo.yaml" \
    "$REPO_ROOT/blockchain/proto/buf.gen.sta.yaml" \
    "$REPO_ROOT/blockchain/proto/buf.gen.swagger.yaml" \
    "$REPO_ROOT/blockchain/proto/buf.gen.ts.yaml" \
    "$REPO_ROOT/blockchain/Makefile" \
  )"

  local old_proto_hash=""
  if [ -f "$proto_hash_file" ]; then
    old_proto_hash="$(cat "$proto_hash_file" 2>/dev/null || echo "")"
  fi
  if [ -z "$old_proto_hash" ] || [ "$old_proto_hash" != "$new_proto_hash" ]; then
    echo "==> Protobuf inputs changed; running proto-gen..."
    ( cd "$REPO_ROOT/blockchain" && make proto-gen )
    echo "$new_proto_hash" > "$proto_hash_file"
  else
    echo "==> Protobuf inputs unchanged; skipping proto-gen."
  fi

  local new_go_hash
  new_go_hash="$(hash_tree \
    "$REPO_ROOT/blockchain/go.mod" \
    "$REPO_ROOT/blockchain/go.sum" \
    "$REPO_ROOT/blockchain/app" \
    "$REPO_ROOT/blockchain/cmd" \
    "$REPO_ROOT/blockchain/x" \
  )"

  local old_go_hash=""
  if [ -f "$go_hash_file" ]; then
    old_go_hash="$(cat "$go_hash_file" 2>/dev/null || echo "")"
  fi
  if [ -z "$old_go_hash" ] || [ "$old_go_hash" != "$new_go_hash" ]; then
    echo "==> Go inputs changed; building miraged..."
    ( cd "$REPO_ROOT/blockchain" && make install )
    echo "$new_go_hash" > "$go_hash_file"
  else
    echo "==> Go inputs unchanged; skipping go build."
  fi
}

docker_build() {
  # docker_build <load_or_push>
  local mode="$1"
  local cache_base
  cache_base="$(cache_dir)/buildx-cache"
  mkdir -p "$cache_base"

  local tags=()
  local out_args=()
  if [ "$mode" = "push" ]; then
    out_args+=(--push)
    tags+=(-t "$IMAGE_SHA_TAG")
    if [ -n "$IMAGE_MOVING_TAG" ]; then
      tags+=(-t "$IMAGE_MOVING_TAG")
    fi
  else
    out_args+=(--load)
    tags+=(-t "mirage:local")
  fi

  docker buildx build \
    "${out_args[@]}" \
    "${tags[@]}" \
    --build-arg GIT_BRANCH="$GIT_BRANCH" \
    --build-arg GIT_HASH="$GIT_HASH" \
    --cache-from "type=local,src=$cache_base" \
    --cache-to "type=local,dest=$cache_base,mode=max" \
    -f "$REPO_ROOT/deploy/Dockerfile" \
    "$REPO_ROOT"
}

# Handle --build-only mode
if [ "$BUILD_ONLY" -eq 1 ]; then
  echo "==> Build-only mode"

  if [ -n "$TARBALL_FILE" ]; then
    # Explicit tarball build (fallback path).
    TARBALL="$TARBALL_FILE"
    echo "==> Building image locally and saving tarball to: $TARBALL"
    maybe_proto_gen_and_go_build
    docker_build load
    mkdir -p "$(dirname "$TARBALL")"
    docker save mirage:local | gzip > "$TARBALL"
    echo "==> Build complete. Tarball saved to: $TARBALL"
  else
    # Default: push to registry (fast remote deploys).
    echo "==> Building and pushing image to registry: $IMAGE_SHA_TAG"
    if [ -n "$IMAGE_MOVING_TAG" ]; then
      echo "==> Also updating moving tag: $IMAGE_MOVING_TAG"
    fi
    maybe_proto_gen_and_go_build
    docker_build push
    echo "==> Build complete. Image pushed:"
    echo "    $IMAGE_SHA_TAG"
    if [ -n "$IMAGE_MOVING_TAG" ]; then
      echo "    $IMAGE_MOVING_TAG"
    fi
  fi
  exit 0
fi

if [ -z "$MODE" ]; then
  echo "ERROR: one of --init or --update is required." >&2
  exit 1
fi

if [ "$LOCAL_MODE" -eq 1 ] && [ "$MODE" = "init" ]; then
  echo "ERROR: --init is not supported with --local" >&2
  echo "For local development, use: scripts/reset_local_testnet.py" >&2
  exit 1
fi

if [ -n "$TARBALL_FILE" ] && [ ! -f "$TARBALL_FILE" ]; then
  echo "ERROR: Tarball file not found: $TARBALL_FILE" >&2
  exit 1
fi

REMOTE_HOST="${REMOTE##*@}"
LOCAL_CONTAINER="mirage"
LOCAL_DATA_DIR="$HOME/.mirage"

# Set up execution mode based on --local or remote SSH
if [ "$LOCAL_MODE" -eq 1 ]; then
  echo "==> Local deployment mode"
  
  close_ssh_socket() { :; }  # No-op for local
  
  # Helper functions for local Docker deployment
  run_ssh() {
    docker exec "$LOCAL_CONTAINER" bash -lc "$*"
  }
  run_scp() {
    # run_scp source dest - for local, dest is container path
    local src="$1"
    local dest="$2"
    # Extract path from dest (format: ignored:/path or just /path)
    local container_path="${dest#*:}"
    docker cp "$src" "$LOCAL_CONTAINER:$container_path"
  }
elif [ -n "$PROXYJUMP" ]; then
  echo "==> Using ProxyJump through $PROXYJUMP"
  SSH_OPTS="-J $PROXYJUMP -o StrictHostKeyChecking=accept-new"
  SCP_OPTS="-J $PROXYJUMP -o StrictHostKeyChecking=accept-new"
  
  # Add jump host's key to known_hosts if needed
  ssh-keyscan -H "$PROXYJUMP" >> ~/.ssh/known_hosts 2>/dev/null || true
  # Add target host's key via jump host
  ssh -J "$PROXYJUMP" -o StrictHostKeyChecking=accept-new "$REMOTE" 'exit' 2>/dev/null || true
  
  close_ssh_socket() { :; }  # No-op when using ProxyJump
  
  # Helper functions using the configured SSH options
  run_ssh() {
    ssh $SSH_OPTS "$REMOTE" "$@"
  }
  run_scp() {
    scp $SCP_OPTS "$@"
  }
else
  SSH_OPTS="-o ControlPath=/tmp/mirage-ssh-%r@%h:%p"
  SCP_OPTS="-o ControlPath=/tmp/mirage-ssh-%r@%h:%p"
  
  # Helper function to close SSH control socket
  close_ssh_socket() {
    ssh -o ControlPath=/tmp/mirage-ssh-%r@%h:%p -O exit "$REMOTE" 2>/dev/null || true
  }

  # Establish SSH control socket for re-use
  echo "==> Establishing SSH control socket..."
  ssh -o PreferredAuthentications=publickey,password,keyboard-interactive -o StrictHostKeyChecking=accept-new -o ControlMaster=auto -o ControlPath=/tmp/mirage-ssh-%r@%h:%p -o ControlPersist=300 "$REMOTE" 'exit'
  
  # Helper functions using the configured SSH options
  run_ssh() {
    ssh $SSH_OPTS "$REMOTE" "$@"
  }
  run_scp() {
    scp $SCP_OPTS "$@"
  }
fi

# Early sanity check for --init: consensus key must NOT already exist on remote
if [ "$MODE" = "init" ]; then
  echo "==> Sanity check: remote consensus key must not exist..."
  if run_ssh "test -f ~/.mirage/node/config/priv_validator_key.json"; then
    echo "ERROR: Found existing ~/.mirage/node/config/priv_validator_key.json on remote. Aborting to avoid accidental overwrite." >&2
    echo "If this server was previously used, provision a fresh server or remove the file manually with extreme caution." >&2
    close_ssh_socket
    exit 1
  fi
fi

# Ensure docker on remote (skip for local - docker is already running)
if [ "$LOCAL_MODE" -eq 0 ]; then
  echo "==> Ensuring Docker is installed on remote..."
  run_ssh '
    set -euo pipefail
    if ! command -v docker >/dev/null 2>&1; then
      export DEBIAN_FRONTEND=noninteractive
      apt-get update -y
      apt-get install -y docker.io
      systemctl enable --now docker
    fi
  '
fi

# No seed file verification required
DEPLOY_IMAGE="mirage:local"
USE_TARBALL=0

if [ -n "$TARBALL_FILE" ]; then
  USE_TARBALL=1
  TARBALL="$TARBALL_FILE"
  echo "==> Using provided tarball: $TARBALL"
else
  echo "==> Default deploy: registry image ($IMAGE_SHA_TAG)"
  if [ -n "$IMAGE_MOVING_TAG" ]; then
    echo "==> Moving tag will be updated: $IMAGE_MOVING_TAG"
  fi

  maybe_proto_gen_and_go_build

  if [ "$LOCAL_MODE" -eq 1 ]; then
    echo "==> Building image locally..."
    docker_build load
  else
    echo "==> Building and pushing image to registry..."
    docker_build push
    DEPLOY_IMAGE="$IMAGE_SHA_TAG"
  fi
fi

if [ "$USE_TARBALL" -eq 1 ] && [ "$LOCAL_MODE" -eq 0 ]; then
  echo "==> Transferring image tarball..."
  # Optimization: avoid re-uploading the tarball if possible.
  # Priority: 1) Target has it, 2) Jump host has it (copy internally), 3) Upload from local
  LOCAL_SHA="$(sha256sum "$TARBALL" | awk '{print $1}')"
  REMOTE_SHA="$(run_ssh 'test -f /tmp/mirage-docker.tar.gz && sha256sum /tmp/mirage-docker.tar.gz | awk '\''{print $1}'\'' || echo ""')"

  if [ -n "$REMOTE_SHA" ] && [ "$REMOTE_SHA" = "$LOCAL_SHA" ]; then
    echo "    Hash match: target already has identical tarball (SHA256: ${LOCAL_SHA:0:16}...), skipping transfer"
  elif [ -n "$PROXYJUMP" ]; then
    # Check if jump host has the tarball (can copy internally, much faster)
    JUMP_SHA="$(ssh "$PROXYJUMP" 'test -f /tmp/mirage-docker.tar.gz && sha256sum /tmp/mirage-docker.tar.gz | awk '\''{print $1}'\'' || echo ""' 2>/dev/null || echo "")"
    if [ -n "$JUMP_SHA" ] && [ "$JUMP_SHA" = "$LOCAL_SHA" ]; then
      # Extract target host from REMOTE (user@host format)
      TARGET_HOST="${REMOTE#*@}"
      echo "    Hash match: jump host has identical tarball (SHA256: ${LOCAL_SHA:0:16}...)"
      echo "    Copying via jump host: $PROXYJUMP -> $TARGET_HOST (internal network)..."
      # Use -A for agent forwarding so jump host can use our local SSH key
      ssh -A "$PROXYJUMP" "scp -o StrictHostKeyChecking=no /tmp/mirage-docker.tar.gz root@${TARGET_HOST}:/tmp/mirage-docker.tar.gz" && echo "    Done."
    else
      echo "    Hash mismatch or missing: uploading from local (SHA256: ${LOCAL_SHA:0:16}...)..."
      run_scp "$TARBALL" "$REMOTE:/tmp/mirage-docker.tar.gz"
    fi
  else
    echo "    Uploading from local (SHA256: ${LOCAL_SHA:0:16}...)..."
    run_scp "$TARBALL" "$REMOTE:/tmp/mirage-docker.tar.gz"
  fi
fi

echo "==> Stopping old container..."
if [ "$LOCAL_MODE" -eq 1 ]; then
  # Local: run docker commands directly on host
  if docker ps -a --format "{{.Names}}" | grep -qx mirage; then
    docker stop --timeout=60 mirage || true
    docker rm mirage || true
  fi
  if [ "$PRUNE" -eq 1 ]; then
    docker system prune -f
  fi
  if [ "$USE_TARBALL" -eq 1 ]; then
    echo "==> Loading image locally..."
    gunzip -c "$TARBALL" | docker load
  fi
else
  if [ "$USE_TARBALL" -eq 1 ]; then
    run_ssh '
      set -euo pipefail
      if docker ps -a --format "{{.Names}}" | grep -qx mirage; then
        docker stop --timeout=60 mirage
        docker rm mirage
      fi
    '
    if [ "$PRUNE" -eq 1 ]; then
      run_ssh 'docker system prune -f'
    fi
    echo "==> Loading image on remote..."
    run_ssh 'gunzip < /tmp/mirage-docker.tar.gz | docker load'
  else
    run_ssh '
      set -euo pipefail
      if docker ps -a --format "{{.Names}}" | grep -qx mirage; then
        docker stop --timeout=60 mirage
        docker rm mirage
      fi
    '
    if [ "$PRUNE" -eq 1 ]; then
      run_ssh 'docker system prune -f'
    fi
    echo "==> Pulling image on remote: $DEPLOY_IMAGE"
    run_ssh "docker pull '$DEPLOY_IMAGE'"
  fi
fi

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
  run_ssh 'mkdir -p ~/.mirage/node/config ~/.caddy'
  # Prompt for consensus derivation index (default 0)
  read -p "Consensus derivation index [0] (default 0; do not change unless rotating): " CONS_INDEX
  CONS_INDEX="${CONS_INDEX:-0}"
  if ! echo "$CONS_INDEX" | grep -Eq '^[0-9]+$'; then
    echo "ERROR: Derivation index must be a non-negative integer." >&2
    exit 1
  fi
  # Double-check consensus key doesn't exist on remote (sanity check before deriving)
  if run_ssh "test -f ~/.mirage/node/config/priv_validator_key.json"; then
    echo "ERROR: Consensus key already exists on remote. Aborting to avoid overwrite." >&2
    exit 1
  fi
  # Derive consensus key on remote using Docker
  echo "==> Deriving consensus key on remote..."
  if ! echo "$MNEMONIC" | run_ssh "MIRAGE_DERIVATION_INDEX='$CONS_INDEX' docker run --rm -i \
    --entrypoint python3 \
    -v ~/.mirage:/root/.mirage \
      '$DEPLOY_IMAGE' /opt/mirage/deploy/derive_consensus_key.py"; then
  echo "ERROR: Failed to derive consensus key." >&2
  exit 1
  fi
  # Set correct permissions on remote
  run_ssh 'chmod 600 ~/.mirage/node/config/priv_validator_key.json'
  echo "✓ Consensus key derived (index $CONS_INDEX)."
  # Import using a one-shot container into the mounted volume to avoid storing the mnemonic as an env var
  if ! echo "$MNEMONIC" | run_ssh "docker run --rm -i \
    --entrypoint /bin/sh \
    -v ~/.mirage:/root/.mirage \
      '$DEPLOY_IMAGE' -lc '/opt/mirage/blockchain/miraged keys add validator --recover --home /root/.mirage/node --keyring-backend test >/dev/null 2>&1'"; then
  echo "ERROR: Failed to import mnemonic into keyring volume." >&2
  exit 1
  fi
  unset MNEMONIC || true
  echo "✓ Account key imported into keyring."
fi

echo "==> Starting container..."

# Persist caddy data for future TLS issuance; persist node data under ~/.mirage
if [ "$LOCAL_MODE" -eq 1 ]; then
  mkdir -p "$HOME/.caddy" "$HOME/.mirage"
  # Skip hermes migration for local
else
  run_ssh 'mkdir -p ~/.caddy ~/.mirage'
  # One-time migration: move ~/.hermes to ~/.mirage/hermes (old volume mount location)
  run_ssh '
    if [ -d ~/.hermes ] && [ ! -L ~/.hermes ] && [ ! -e ~/.mirage/hermes ]; then
      echo "==> Migrating ~/.hermes to ~/.mirage/hermes..."
      mv ~/.hermes ~/.mirage/hermes
    elif [ -d ~/.hermes ] && [ ! -L ~/.hermes ] && [ -d ~/.mirage/hermes ]; then
      echo "==> Merging ~/.hermes into ~/.mirage/hermes..."
      cp -a ~/.hermes/. ~/.mirage/hermes/
      rm -rf ~/.hermes
    fi
  '
fi

# Initialize persistent config directory and seed env files if missing (for --init)
if [ "$MODE" = "init" ]; then
  echo "==> Ensuring persistent config files exist on remote..."
  run_ssh 'mkdir -p ~/.mirage/env'
  # Copy env templates if they don't exist on remote
  for f in "$(dirname "$0")/templates/env"/*.env; do
    if [ -f "$f" ]; then
      fname="$(basename "$f")"
      # Only copy if file doesn't exist on remote (preserve user customizations)
      run_ssh "[ -f ~/.mirage/env/$fname ]" 2>/dev/null || run_scp "$f" "$REMOTE:~/.mirage/env/$fname"
    fi
  done
  # Persist moniker during first-time init
  if [ -n "$MONIKER_VALUE" ]; then
    run_ssh "bash -lc 'set -euo pipefail; FILE=\$HOME/.mirage/env/node.env; touch \"\$FILE\"; if grep -q \"^MONIKER=\" \"\$FILE\"; then sed -i \"s/^MONIKER=.*/MONIKER=\\\"$MONIKER_VALUE\\\"/\" \"\$FILE\"; else echo MONIKER=\\\"$MONIKER_VALUE\\\" >> \"\$FILE\"; fi'"
  fi
fi


# For --update modes, read MONIKER from existing node.env if not explicitly provided
if [ "$MODE" != "init" ] && [ "$MONIKER_VALUE" = "mirage-node" ]; then
  echo "==> Reading existing MONIKER from node.env..."
  if [ "$LOCAL_MODE" -eq 1 ]; then
    EXISTING_MONIKER=$(grep -E '^MONIKER=' "$HOME/.mirage/env/node.env" 2>/dev/null | cut -d= -f2 | tr -d '"' || echo "")
  else
    EXISTING_MONIKER=$(run_ssh "grep -E '^MONIKER=' ~/.mirage/env/node.env 2>/dev/null | cut -d= -f2 | tr -d '\"'" || echo "")
  fi
  if [ -n "$EXISTING_MONIKER" ] && [ "$EXISTING_MONIKER" != "mirage-node" ]; then
    MONIKER_VALUE="$EXISTING_MONIKER"
    echo "    Using existing moniker: $MONIKER_VALUE"
  fi
fi

PORTS="-p 80:80 -p 26656:26656 -p 26657:26657 -p 443:443"
MONIKER_ARG=""
HOSTNAME_ARG=""

# Try to get DOMAIN from env file for hostname
DOMAIN_VALUE=""
if [ "$LOCAL_MODE" -eq 1 ]; then
  [ -f "$HOME/.mirage/env/node.env" ] && DOMAIN_VALUE=$(grep -E '^DOMAIN=' "$HOME/.mirage/env/node.env" 2>/dev/null | cut -d= -f2- | tr -d '"' | tr -d "'" || true)
else
  DOMAIN_VALUE=$(run_ssh "grep -E '^DOMAIN=' \$HOME/.mirage/env/node.env 2>/dev/null | cut -d= -f2- | tr -d '\"' | tr -d \"'\"" 2>/dev/null || true)
fi

# Set hostname: prefer DOMAIN, fallback to MONIKER
if [ -n "$DOMAIN_VALUE" ]; then
  CLEAN_HOSTNAME=$(echo "$DOMAIN_VALUE" | tr './:' '-')
  HOSTNAME_ARG="--hostname $CLEAN_HOSTNAME"
elif [ -n "$MONIKER_VALUE" ] && [ "$MONIKER_VALUE" != "mirage-node" ]; then
  MONIKER_ARG="-e MONIKER=\"$MONIKER_VALUE\""
  CLEAN_HOSTNAME=$(echo "$MONIKER_VALUE" | sed 's|https\?://||' | tr './:' '-')
  HOSTNAME_ARG="--hostname $CLEAN_HOSTNAME"
fi

if [ "$LOCAL_MODE" -eq 1 ]; then
  # Local: run docker directly on host
  ENV_ARGS=""
  for f in backend node indexer frontend secrets; do
    if [ -f "$HOME/.mirage/env/$f.env" ]; then
      ENV_ARGS="$ENV_ARGS --env-file $HOME/.mirage/env/$f.env"
    fi
  done
  # Add SKIP_VALIDATOR_CHECK and SKIP_PEERS for local testing
  docker run -d $PORTS $ENV_ARGS --name mirage --restart unless-stopped $HOSTNAME_ARG $MONIKER_ARG -e SKIP_VALIDATOR_CHECK=1 -e SKIP_PEERS=1 -v "$HOME/.mirage:/root/.mirage" -v "$HOME/.caddy:/root/.local/share/caddy" "$DEPLOY_IMAGE"
else
  run_ssh "ENV_ARGS=\"\"; for f in backend node indexer frontend secrets; do if [ -f \$HOME/.mirage/env/\$f.env ]; then ENV_ARGS=\"\$ENV_ARGS --env-file \$HOME/.mirage/env/\$f.env\"; fi; done; docker run -d $PORTS \$ENV_ARGS --name mirage --restart unless-stopped $HOSTNAME_ARG $MONIKER_ARG -v \$HOME/.mirage:/root/.mirage -v \$HOME/.caddy:/root/.local/share/caddy '$DEPLOY_IMAGE'"
fi

echo "==> Waiting briefly for container to become healthy..."
sleep 2

# Ensure container is running and stable (handle restart loop) before docker exec
echo "==> Waiting for container to be running and stable..."
stability_check() {
  local consec=0
  for i in $(seq 1 60); do
    local st=$(docker inspect -f "{{.State.Status}}" mirage 2>/dev/null || echo "notfound")
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
          return 0
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
  return 1
}

if [ "$LOCAL_MODE" -eq 1 ]; then
  stability_check
else
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
  run_ssh "bash -c '$STABILITY_CHECK'"
fi

# On init only, create the validator if it doesn't exist yet (idempotent)
if [ "$MODE" = "init" ]; then
  echo "==> Ensuring validator exists on-chain..."
  echo "==> Running create_validator.sh inside container (remote) with moniker: $MONIKER_VALUE"
  run_ssh "docker exec -i mirage bash -c \"MONIKER=\\\"$MONIKER_VALUE\\\" bash /opt/mirage/deploy/create_validator.sh\""
fi

# For --update: update validator moniker on-chain if it differs
if [ "$MODE" = "update" ]; then
  if [ -n "$MONIKER_VALUE" ] && [ "$MONIKER_VALUE" != "mirage-node" ]; then
    echo "==> Checking if validator moniker needs update..."
    MONIKER_UPDATE_SCRIPT=$'# Ensure strict mode in container\nset -euo pipefail\ncd /opt/mirage\nVALOPER=$(/opt/mirage/blockchain/miraged keys show validator --home /root/.mirage/node --keyring-backend test --bech val -a 2>/dev/null || echo \"\")\nif [ -z \"$VALOPER\" ]; then\n  echo \"Validator not found, skipping moniker update\"\n  exit 0\nfi\nCURRENT=$(/opt/mirage/blockchain/miraged q staking validator \"$VALOPER\" --home /root/.mirage/node --node tcp://127.0.0.1:26657 -o json 2>/dev/null | jq -r \".validator.description.moniker // \\\"\\\"\" || echo \"\")\nif [ \"$CURRENT\" = \"${NEW_MONIKER:-}\" ]; then\n  echo \"Validator moniker already set to \\\"${NEW_MONIKER:-}\\\"\"\n  exit 0\nfi\necho \"Updating validator moniker from \\\"$CURRENT\\\" to \\\"${NEW_MONIKER:-}\\\"\"\n/opt/mirage/blockchain/miraged tx staking edit-validator --new-moniker=\"${NEW_MONIKER:-}\" \\\n  --from validator --home /root/.mirage/node --keyring-backend test \\\n  --chain-id mirage-1 --node tcp://127.0.0.1:26657 --gas auto --gas-adjustment 1.5 -y >/dev/null 2>&1 || true\n'
    echo "$MONIKER_UPDATE_SCRIPT" | run_ssh "docker exec -e NEW_MONIKER=\"$MONIKER_VALUE\" -i mirage bash -seuo pipefail"
  fi
fi

if [ "$LOCAL_MODE" -eq 1 ]; then
  echo "==> Done. Container 'mirage' is running locally."
  echo ""
  echo "Container access:"
  echo "  Attach tmux:  docker exec -it mirage tmux attach -t mirage"
  echo "  Shell:        docker exec -it mirage bash"
  echo "  Logs:         docker logs -f mirage"
else
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
fi

close_ssh_socket
