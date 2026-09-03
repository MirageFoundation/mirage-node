#!/usr/bin/env bash
set -euo pipefail

# Deployment script for Mirage
# Usage: deploy/deploy.sh user@host [--init|--update] [--file TARBALL] [--moniker VALUE] [--proxyjump HOST]
#        deploy/deploy.sh --local [--init|--update] [--file TARBALL]
#
# Notes:
# - Moniker defaults to "mirage-node" and can be overridden with --moniker
# - Domain/TLS: Configure HTTPS inside the container using setup_letsencrypt.py (domain is persisted automatically)
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
  user@host            SSH connection string (e.g., root@<val1>)
  --local              Deploy to local Docker container (no SSH)

Modes (exactly one required, except for --build-only):
  --init               First-time setup: build, upload, start container.
                       Prompts for mnemonic and imports it before startup.
                       REQUIRES --moniker to be explicitly provided.
  --update             Update image and restart container. Preserves data.
                       Re-renders configs on startup (idempotent).
  --build-only         Build Docker image only (default: pushes to registry; use --file to save tarball).

Options:
  --image IMAGE        Use a pre-built image (skip dirty check and build). Used by deploy_all_prod.sh.
  --file TARBALL       Use tarball flow (legacy fallback). If omitted, deploy uses GHCR by default.
  --moniker VALUE      Set CometBFT node moniker (default: mirage-node, REQUIRED for --init)
  --proxyjump HOST     Route traffic through a jump host (for high-latency servers).
                       Example: --proxyjump mirage.vote
  --no-cache           Disable Docker build cache (enabled by default).

Local deployment:
  deploy/deploy.sh --local --update

Remote access:
  ssh user@host 'docker logs -f mirage'
  ssh user@host mirage-status
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
PRE_BUILT_IMAGE=""
MONIKER_VALUE="mirage-node"
PROXYJUMP=""
NO_CACHE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --build-only) BUILD_ONLY=1 ; shift ;;
    --init) MODE="init" ; shift ;;
    --update) MODE="update" ; shift ;;
    --no-cache) NO_CACHE=1 ; shift ;;
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
    --image=*)
      PRE_BUILT_IMAGE="${1#*=}"
      shift
      ;;
    --image)
      if [ $# -lt 2 ]; then
        echo "ERROR: --image requires an image reference" >&2
        exit 1
      fi
      PRE_BUILT_IMAGE="$2"
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

# Fail fast if there are uncommitted changes (skip when using a pre-built image)
if [ -z "$PRE_BUILT_IMAGE" ]; then
  dirty_files="$(git -C "$REPO_ROOT" diff --name-only 2>/dev/null; git -C "$REPO_ROOT" diff --cached --name-only 2>/dev/null)"
  if [ -n "$dirty_files" ]; then
    echo "ERROR: You have uncommitted changes. Commit or stash them before deploying." >&2
    git -C "$REPO_ROOT" status --short >&2
    exit 1
  fi
fi

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
  # pipefail + SIGPIPE (find/xargs closing a pipe) would otherwise abort the
  # caller with exit 141; hashing is advisory so keep going.
  local tmp hash
  tmp="$(mktemp)"
  set +o pipefail
  for p in "$@"; do
    if [ -e "$p" ]; then
      find "$p" -type f -print0
    fi
  done | sort -z | xargs -0 sha256sum > "$tmp" 2>/dev/null || true
  hash="$(sha256sum "$tmp")"
  set -o pipefail
  printf '%s\n' "${hash%% *}"
  rm -f "$tmp"
}

maybe_proto_gen_and_go_build() {
  local cdir
  cdir="$(cache_dir)"

  local proto_hash_file="$cdir/proto.${GIT_BRANCH}.sha256"
  local go_hash_file="$cdir/go.${GIT_BRANCH}.sha256"

  # Step 1: Check if proto sources changed BEFORE running proto-gen
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

  # Only run proto-gen if proto sources changed
  if [ -z "$old_proto_hash" ] || [ "$old_proto_hash" != "$new_proto_hash" ]; then
    echo "==> Proto sources changed, regenerating protobuf files..."
    ( cd "$REPO_ROOT/blockchain" && make proto-gen )
    echo "$new_proto_hash" > "$proto_hash_file"
  else
    echo "==> Proto sources unchanged; skipping proto-gen."
  fi

  # Step 2: Compute Go hash AFTER proto-gen (so it includes fresh .pb.go files)
  # This is critical: if proto-gen updated any .pb.go files, the hash will change
  # The hash is STRICTLY based on source file contents — tags, commit hashes,
  # and other git metadata are NOT included. The version string baked into the
  # binary via ldflags is cosmetic and not worth triggering a full rebuild for.
  local new_go_hash
  new_go_hash="$(hash_tree \
    "$REPO_ROOT/blockchain/go.mod" \
    "$REPO_ROOT/blockchain/go.sum" \
    "$REPO_ROOT/blockchain/app" \
    "$REPO_ROOT/blockchain/cmd" \
    "$REPO_ROOT/blockchain/x" \
  )"

  local miraged_bin="$REPO_ROOT/blockchain/bin/miraged"
  local need_build=0

  # Check if binaries exist
  if [ ! -f "$miraged_bin" ]; then
    echo "==> miraged binary not found; rebuild needed"
    need_build=1
  fi

  # Check if any source file is newer than binaries (catches proto-gen updates)
  if [ "$need_build" -eq 0 ]; then
    local newest_source
    newest_source="$(find \
      "$REPO_ROOT/blockchain/go.mod" \
      "$REPO_ROOT/blockchain/go.sum" \
      "$REPO_ROOT/blockchain/app" \
      "$REPO_ROOT/blockchain/cmd" \
      "$REPO_ROOT/blockchain/x" \
      -type f -newer "$miraged_bin" -print -quit 2>/dev/null || true)"
    if [ -n "$newest_source" ]; then
      echo "==> Source newer than miraged: $newest_source"
      need_build=1
    fi
  fi

  # Embedded version comes from the root VERSION file (Makefile ldflags), not
  # git describe. A moved tag must not change what the binary reports.
  if [ "$need_build" -eq 0 ]; then
    local want_version have_version
    want_version="$(tr -d '[:space:]' < "$REPO_ROOT/VERSION" 2>/dev/null || echo "")"
    have_version="$("$miraged_bin" version 2>/dev/null || true)"
    have_version="${have_version##*$'\n'}"
    have_version="${have_version//[$' \t\r\n']/}"
    have_version="${have_version%-dirty}"
    if [ -n "$want_version" ] && [ "$want_version" != "$have_version" ]; then
      echo "==> miraged reports '$have_version' but VERSION is '$want_version'; rebuild needed"
      need_build=1
    fi
  fi

  # Check hash for content changes
  if [ "$need_build" -eq 0 ]; then
    local old_go_hash=""
    if [ -f "$go_hash_file" ]; then
      old_go_hash="$(cat "$go_hash_file" 2>/dev/null || echo "")"
    fi
    if [ -z "$old_go_hash" ] || [ "$old_go_hash" != "$new_go_hash" ]; then
      echo "==> Go source hash changed"
      need_build=1
    fi
  fi

  if [ "$need_build" -eq 1 ]; then
    echo "==> Building miraged..."
    # Delete old binaries to force Go to rebuild
    rm -f "$miraged_bin"
    ( cd "$REPO_ROOT/blockchain" && make build-all )
    echo "$new_go_hash" > "$go_hash_file"
  else
    echo "==> Go binaries up to date; skipping build."
  fi
}

docker_build() {
  # docker_build <load_or_push>
  local mode="$1"

  # Local loads use plain docker build to avoid buildx gRPC stream timeout
  # on large images. Buildx is only needed for --push (registry).
  if [ "$mode" = "load" ]; then
    local cache_arg=""
    if [ "$NO_CACHE" -eq 1 ]; then
      echo "==> Building WITHOUT cache (use default to enable)"
      cache_arg="--no-cache"
    fi
    DOCKER_BUILDKIT=1 docker build \
      -t "mirage:local" \
      $cache_arg \
      --build-arg GIT_BRANCH="$GIT_BRANCH" \
      --build-arg GIT_HASH="$GIT_HASH" \
      -f "$REPO_ROOT/deploy/Dockerfile" \
      "$REPO_ROOT"
    return
  fi

  # Push mode: use buildx for registry push + explicit cache dirs
  local cache_base
  cache_base="$(cache_dir)/buildx-cache"
  mkdir -p "$cache_base"

  local tags=(-t "$IMAGE_SHA_TAG")
  if [ -n "$IMAGE_MOVING_TAG" ]; then
    tags+=(-t "$IMAGE_MOVING_TAG")
  fi

  local cache_args=()
  if [ "$NO_CACHE" -eq 1 ]; then
    echo "==> Building WITHOUT cache (use default to enable)"
    cache_args+=(--no-cache)
  else
    cache_args+=(--cache-from "type=local,src=$cache_base")
    cache_args+=(--cache-to "type=local,dest=$cache_base,mode=max")
  fi

  # amd64 only: the Dockerfile copies the miraged binary built on this machine,
  # so a second platform would ship an image whose chain binary cannot run.
  # Arm64 needs the binary built inside the image first.
  docker buildx build \
    --platform linux/amd64 \
    --push \
    "${tags[@]}" \
    "${cache_args[@]}" \
    --build-arg GIT_BRANCH="$GIT_BRANCH" \
    --build-arg GIT_HASH="$GIT_HASH" \
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

# Docker CE is required (harden_server.sh / install.sh). No docker.io fallback.
if [ "$LOCAL_MODE" -eq 0 ]; then
  echo "==> Checking Docker on remote..."
  if ! run_ssh 'command -v docker >/dev/null 2>&1'; then
    echo "ERROR: docker is not installed on the remote host." >&2
    echo "       Run deploy/harden_server.sh (or deploy/install.sh) first so Docker CE is present." >&2
    close_ssh_socket
    exit 1
  fi
fi

# No seed file verification required
DEPLOY_IMAGE="mirage:local"
USE_TARBALL=0

if [ -n "$PRE_BUILT_IMAGE" ]; then
  echo "==> Using pre-built image: $PRE_BUILT_IMAGE"
  DEPLOY_IMAGE="$PRE_BUILT_IMAGE"
elif [ -n "$TARBALL_FILE" ]; then
  USE_TARBALL=1
  TARBALL="$TARBALL_FILE"
  echo "==> Using provided tarball: $TARBALL"
else
  echo "==> Default deploy: registry image ($IMAGE_SHA_TAG)"
  if [ -n "$IMAGE_MOVING_TAG" ]; then
    echo "==> Moving tag will be updated: $IMAGE_MOVING_TAG"
  fi

  if [ "$LOCAL_MODE" -eq 1 ]; then
    # Local mode: always build locally
    maybe_proto_gen_and_go_build
    echo "==> Building image locally..."
    docker_build load
  else
    # Remote mode: check if image already exists in registry before building
    echo "==> Checking if image exists in registry: $IMAGE_SHA_TAG"
    if docker manifest inspect "$IMAGE_SHA_TAG" >/dev/null 2>&1; then
      echo "==> Image already exists in registry, skipping build"
      DEPLOY_IMAGE="$IMAGE_SHA_TAG"
    else
      echo "==> Image not found in registry, building and pushing..."
      maybe_proto_gen_and_go_build
      docker_build push
      DEPLOY_IMAGE="$IMAGE_SHA_TAG"
    fi
  fi
fi

# Reclaim disk BEFORE the image lands, not after. The prune below used to run
# only once the new container was already up, which is too late to matter: the
# transfer is what consumes the space. On 2026-08-20 a 2.2 GiB pull filled val1's
# disk to 100% mid-pull, CometBFT could not write its consensus WAL ("no space
# left on device"), and the validator stopped signing at the block it was on
# while the rest of the chain carried on without it.
if [ "$LOCAL_MODE" -eq 0 ]; then
  echo "==> Reclaiming disk before transferring image..."
  # Ship the pruner rather than hoping it is installed. deploy.sh provisions
  # hosts but never installed the host tools, and the old call was guarded on
  # the tool being executable — so on every host deployed this way the prune was
  # a silent no-op. val1 had an empty /usr/local/bin and 10 GiB of dead images.
  run_scp "$REPO_ROOT/deploy/hosttools/prune_mirage_images.sh" "$REMOTE:/usr/local/bin/prune_mirage_images.sh"
  run_ssh 'chmod 0755 /usr/local/bin/prune_mirage_images.sh && /usr/local/bin/prune_mirage_images.sh'
  # Refuse to deploy onto a disk that cannot take the image. Filling it does not
  # fail the deploy, it stops the validator, so this has to be checked up front
  # rather than discovered from a stalled node.
  run_ssh 'set -eu
    free_mb=$(df -BM --output=avail / | tail -1 | tr -dc "0-9")
    if [ "$free_mb" -lt 6144 ]; then
      echo "ERROR: only ${free_mb} MiB free on / after pruning" >&2
      echo "       The image needs ~2.2 GiB and the node needs headroom to write its" >&2
      echo "       consensus WAL. Deploying onto a full disk halts the validator." >&2
      exit 1
    fi
    echo "    ${free_mb} MiB free on /"
  '
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

# Pull/load image BEFORE stopping container to minimize downtime
if [ "$LOCAL_MODE" -eq 1 ]; then
  if [ "$USE_TARBALL" -eq 1 ]; then
    echo "==> Loading image locally..."
    gunzip -c "$TARBALL" | docker load
  fi
else
  if [ "$USE_TARBALL" -eq 1 ]; then
    echo "==> Loading image on remote..."
    run_ssh 'gunzip < /tmp/mirage-docker.tar.gz | docker load'
  else
    echo "==> Pulling image on remote (container still running): $DEPLOY_IMAGE"
    pull_image() {
      ssh -t $SSH_OPTS "$REMOTE" "docker pull '$DEPLOY_IMAGE'"
    }

    if ! pull_image; then
      echo "==> Initial pull failed; retrying in case registry manifest is still propagating..."
      PULL_READY=0
      for attempt in {1..12}; do
        sleep 5
        echo "    Pull retry ${attempt}/12..."
        if pull_image; then
          PULL_READY=1
          break
        fi
      done
      if [ "$PULL_READY" -ne 1 ]; then
        echo "ERROR: Failed to pull image after retries: $DEPLOY_IMAGE" >&2
        close_ssh_socket
        exit 1
      fi
    fi
  fi
fi

echo "==> Stopping old container..."
if [ "$LOCAL_MODE" -eq 1 ]; then
  # Local: run docker commands directly on host
  if docker ps -a --format "{{.Names}}" | grep -qx mirage; then
    docker stop --timeout=60 mirage || true
    docker rm mirage || true
  fi
else
  # Remote: stop and remove old container
  run_ssh '
    set -euo pipefail
    if docker ps -a --format "{{.Names}}" | grep -qx mirage; then
      docker stop --timeout=60 mirage
      docker rm mirage
    fi
  '
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
  # Double-check consensus key doesn't exist on remote (sanity check before deriving)
  if run_ssh "test -f ~/.mirage/node/config/priv_validator_key.json"; then
    echo "ERROR: Consensus key already exists on remote. Aborting to avoid overwrite." >&2
    exit 1
  fi
  # Derive consensus key on remote using Docker. Index is fixed at 0.
  echo "==> Deriving consensus key on remote..."
  if ! echo "$MNEMONIC" | run_ssh "docker run --rm -i \
    --entrypoint python3 \
    -v ~/.mirage:/root/.mirage \
      '$DEPLOY_IMAGE' /opt/mirage/deploy/derive_consensus_key.py --index 0"; then
  echo "ERROR: Failed to derive consensus key." >&2
  exit 1
  fi
  # Set correct permissions on remote
  run_ssh 'chmod 600 ~/.mirage/node/config/priv_validator_key.json'
  echo "✓ Consensus key derived (index 0)."
  # Import using a one-shot container into the mounted volume to avoid storing the mnemonic as an env var
  if ! echo "$MNEMONIC" | run_ssh "docker run --rm -i \
    --entrypoint /bin/sh \
    -v ~/.mirage:/root/.mirage \
      '$DEPLOY_IMAGE' -lc '/opt/mirage/blockchain/bin/miraged keys add validator --recover --home /root/.mirage/node --keyring-backend test >/dev/null 2>&1'"; then
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
else
  run_ssh 'mkdir -p ~/.caddy ~/.mirage'
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
  # A joining node needs the peer list and bootstrap RPCs, and neither is in
  # this repo. They live in the operator's .env, which only exists here on the
  # workstation, so seed them into the remote node.env now.
  ENV_FILE="$(dirname "$0")/../.env"
  if [ ! -f "$ENV_FILE" ]; then
    echo "ERROR: .env not found at $ENV_FILE. --init needs MIRAGE_REMOTE_RPC and MIRAGE_PERSISTENT_PEERS." >&2
    exit 1
  fi
  for key in MIRAGE_REMOTE_RPC MIRAGE_PERSISTENT_PEERS; do
    value="$(grep -E "^${key}=" "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'")"
    if [ -z "$value" ]; then
      echo "ERROR: $key is empty in $ENV_FILE; a joining node cannot reach the network without it." >&2
      exit 1
    fi
    case "$key" in
      MIRAGE_REMOTE_RPC) remote_key="BOOTSTRAP_RPC" ;;
      MIRAGE_PERSISTENT_PEERS) remote_key="PERSISTENT_PEERS" ;;
    esac
    run_ssh "bash -lc 'set -euo pipefail; FILE=\$HOME/.mirage/env/node.env; touch \"\$FILE\"; if grep -q \"^${remote_key}=\" \"\$FILE\"; then sed -i \"s|^${remote_key}=.*|${remote_key}=${value}|\" \"\$FILE\"; else echo ${remote_key}=${value} >> \"\$FILE\"; fi'"
    echo "==> Seeded $remote_key on remote from $key"
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

# Same derivation init.sh performs for the p2p moniker, so the on-chain one does
# not stay behind. Without it the update below is skipped by its own "not the
# default" guard on exactly the nodes that need it: one that has a domain but
# never had a name chosen for it.
if [ -n "$DOMAIN_VALUE" ] && { [ -z "$MONIKER_VALUE" ] || [ "$MONIKER_VALUE" = "mirage-node" ]; }; then
  MONIKER_VALUE="https://$DOMAIN_VALUE"
  echo "==> Moniker derived from DOMAIN: $MONIKER_VALUE"
fi

# Set hostname: prefer DOMAIN, fallback to MONIKER
# Replace dots with dashes for container hostname compatibility
if [ -n "$DOMAIN_VALUE" ]; then
  CLEAN_HOSTNAME=$(echo "$DOMAIN_VALUE" | tr '.' '-')
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
  # Force --hostname testnet so test_backend.py can verify it's a local testnet
  # --shm-size=2g: Postgres parallel workers allocate 8MB shared-memory segments;
  # Docker's default 64MB /dev/shm is exhausted under normal indexer-read load.
  # --ulimit nofile: containers inherit the Docker daemon's 1024 soft limit and
  # never see /etc/security/limits.d/99-mirage.conf, which harden_server.sh
  # writes for host logins only. 1024 descriptors is shared by the node's WAL and
  # per-substore IAVL files, peer sockets, the RPC surface, Postgres and
  # gunicorn. Since v1.34.0 a node-local store failure halts the validator
  # deliberately, so descriptor exhaustion now stops a node instead of producing
  # a stray error. The value matches what harden_server.sh already intends.
  docker run -d $PORTS $ENV_ARGS --name mirage --hostname testnet --restart unless-stopped --shm-size=2g --ulimit nofile=131072:131072 $MONIKER_ARG -e SKIP_VALIDATOR_CHECK=1 -e SKIP_PEERS=1 -v "$HOME/.mirage:/root/.mirage" -v "$HOME/.caddy:/root/.local/share/caddy" "$DEPLOY_IMAGE"
else
  if run_ssh 'command -v mirage-launch >/dev/null 2>&1'; then
    echo "==> Starting remote container via mirage-launch..."
    if [ "$MONIKER_VALUE" != "mirage-node" ]; then
      run_ssh "mirage-launch --image '$DEPLOY_IMAGE' --moniker '$MONIKER_VALUE'"
    else
      run_ssh "mirage-launch --image '$DEPLOY_IMAGE'"
    fi
  else
    run_ssh "ENV_ARGS=\"\"; for f in backend node indexer frontend secrets; do if [ -f \$HOME/.mirage/env/\$f.env ]; then ENV_ARGS=\"\$ENV_ARGS --env-file \$HOME/.mirage/env/\$f.env\"; fi; done; docker run -d $PORTS \$ENV_ARGS --name mirage --restart unless-stopped --shm-size=2g --ulimit nofile=131072:131072 $HOSTNAME_ARG $MONIKER_ARG -v \$HOME/.mirage:/root/.mirage -v \$HOME/.caddy:/root/.local/share/caddy '$DEPLOY_IMAGE'"
  fi
fi

echo "==> Waiting briefly for container to become healthy..."
sleep 2

# Drop the image this deploy just superseded. Never `docker image prune -af`.
# The pruner is installed unconditionally before the pull, so this no longer
# depends on the host happening to have it.
if [ "$LOCAL_MODE" -eq 0 ]; then
  echo "==> Pruning superseded Mirage images..."
  run_ssh '/usr/local/bin/prune_mirage_images.sh; rm -f /tmp/mirage-docker.tar.gz'
fi

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
        echo "  -> Docker exec successful (need 5 consecutive)"
        if [ "$consec" -ge 5 ]; then
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
      echo "  -> Docker exec successful (need 5 consecutive)"
      if [ "$consec" -ge 5 ]; then
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
    if [ "$LOCAL_MODE" -eq 1 ]; then
      # For local mode, run docker exec directly (run_ssh would wrap it in another docker exec)
      docker exec -e NEW_MONIKER="$MONIKER_VALUE" -i mirage bash /opt/mirage/deploy/update_moniker.sh
    else
      run_ssh "docker exec -e NEW_MONIKER=\"$MONIKER_VALUE\" -i mirage bash /opt/mirage/deploy/update_moniker.sh"
    fi
  fi
fi

# Run host-side security setup - remote only
if [ "$LOCAL_MODE" -eq 0 ]; then
  echo "==> Running host rate limiting setup..."
  run_scp "$SCRIPT_DIR/enable_rate_limiting.sh" "$REMOTE:/tmp/enable_rate_limiting.sh"
  run_ssh "chmod +x /tmp/enable_rate_limiting.sh && /tmp/enable_rate_limiting.sh && rm /tmp/enable_rate_limiting.sh"
  
  echo "==> Running host fail2ban setup..."
  run_scp "$SCRIPT_DIR/enable_fail2ban.sh" "$REMOTE:/tmp/enable_fail2ban.sh"
  run_ssh "chmod +x /tmp/enable_fail2ban.sh && /tmp/enable_fail2ban.sh && rm /tmp/enable_fail2ban.sh"

  echo "==> Running host journald cap..."
  run_scp "$SCRIPT_DIR/cap_journald.sh" "$REMOTE:/tmp/cap_journald.sh"
  run_ssh "chmod +x /tmp/cap_journald.sh && /tmp/cap_journald.sh && rm /tmp/cap_journald.sh"
fi

# Health check: best-effort only. Log status but never block the deploy.
# Poll for up to ~15s — long enough for a normal deploy to flip healthy, short
# enough that an upgrade-halt rollout doesn't add minutes per node (chain stays
# halted until 2/3+ validators restart, so the first nodes will always look
# unhealthy here and we don't want to wait for them).
echo "==> Running post-deploy health check (non-blocking, up to ~15s)..."
if [ "$LOCAL_MODE" -eq 1 ]; then
  HEALTH_JSON=""
  for _ in $(seq 1 3); do
    HEALTH_JSON=$(docker exec mirage python3 /opt/mirage/scripts/status_dashboard.py --json 2>/dev/null) || true
    if echo "$HEALTH_JSON" | python3 -c "import sys, json
try:
    sys.exit(0 if json.load(sys.stdin).get('healthy') else 1)
except Exception:
    sys.exit(1)" 2>/dev/null; then
      break
    fi
    sleep 5
  done
  echo "$HEALTH_JSON" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    for name, info in d.get('services', {}).items():
        status = info.get('status', 'unknown').upper()
        msg = info.get('message', '')
        symbol = '✓' if info.get('healthy') else '✗'
        print(f'    {symbol} {name}: {status} - {msg}')
    if not d.get('healthy'):
        print()
        print('    Note: still unhealthy after ~15s — may be an upgrade halt (resumes once 2/3+ validators restart)')
except Exception:
    print('    (health check not available yet)')
"
else
  run_ssh '
    HEALTH_JSON=""
    for _ in $(seq 1 3); do
      HEALTH_JSON=$(docker exec mirage python3 /opt/mirage/scripts/status_dashboard.py --json 2>/dev/null) || true
      if echo "$HEALTH_JSON" | python3 -c "import sys, json
try:
    sys.exit(0 if json.load(sys.stdin).get(\"healthy\") else 1)
except Exception:
    sys.exit(1)" 2>/dev/null; then
        break
      fi
      sleep 5
    done
    echo "$HEALTH_JSON" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    for name, info in d.get(\"services\", {}).items():
        status = info.get(\"status\", \"unknown\").upper()
        msg = info.get(\"message\", \"\")
        symbol = \"✓\" if info.get(\"healthy\") else \"✗\"
        print(f\"    {symbol} {name}: {status} - {msg}\")
    if not d.get(\"healthy\"):
        print()
        print(\"    Note: still unhealthy after ~15s — may be an upgrade halt (resumes once 2/3+ validators restart)\")
except Exception:
    print(\"    (health check not available yet)\")
"
  '
fi

if [ "$LOCAL_MODE" -eq 1 ]; then
  echo "==> Done. Container 'mirage' is running locally."
  echo ""
  echo "Container access:"
  echo "  Status:       mirage-status"
  echo "  Shell:        docker exec -it mirage bash"
  echo "  Logs:         docker logs -f mirage"
else
  echo "==> Done. Container 'mirage' is running on $REMOTE_HOST."
  echo "    To configure HTTPS (domain will persist for future deployments):"
  echo "      ssh $REMOTE 'docker exec mirage python3 /opt/mirage/deploy/setup_letsencrypt.py --domain=yourdomain.com'"
  echo ""
  echo "Remote container access:"
  echo "  Live status:"
  echo "    ssh $REMOTE mirage-status"
  echo "  Shell into container:"
  echo "    ssh -t $REMOTE 'docker exec -it mirage bash'"
  echo "  Follow logs:"
  echo "    ssh $REMOTE 'docker logs -f mirage'"
fi

close_ssh_socket
