#!/usr/bin/env bash
set -euo pipefail

# Deploy to all production servers using GHCR registry.
#
# Usage:
#   scripts/deploy_all_prod.sh [--init|--update] [--proxyjump HOST]
#
# Default mode: --update
#
# Flow:
#   1. Build and push image to ghcr.io/miragefoundation/mirage-node
#   2. All servers pull from registry (fast, parallel-friendly)
#
# Notes:
# - This script is intentionally hard-coded to production hosts.
# - Requires SSH access to each host.
# - Will prompt for explicit confirmation before proceeding.
#
# IMPORTANT: Do not run this unless you intend to deploy to production.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
DEPLOY_SH="${REPO_ROOT}/deploy/deploy.sh"

# Parse arguments
MODE=""
PROXYJUMP=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --init|--update)
      MODE="$1"
      shift
      ;;
    --proxyjump|-J)
      if [[ -z "${2-}" ]]; then
        echo "ERROR: --proxyjump requires a host argument" >&2
        exit 1
      fi
      PROXYJUMP="$2"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1" >&2
      echo "Usage: $0 [--init|--update] [--proxyjump HOST]" >&2
      exit 1
      ;;
  esac
done

if [[ -z "${MODE}" ]]; then
  MODE="--update"
fi

PROXYJUMP_ARGS=()
if [[ -n "${PROXYJUMP}" ]]; then
  PROXYJUMP_ARGS=(--proxyjump "${PROXYJUMP}")
fi

# Hard-coded production hosts
SSH_USER="${SSH_USER:-root}"
HOSTS=(
#   "mirage.vote"
  "146.190.108.140"
  "139.59.9.96"
  "mirage.talk"
)

# Get image tag info
GIT_HASH="$(git -C "$REPO_ROOT" rev-parse --short HEAD 2>/dev/null || date +%Y%m%d%H%M%S)"
GIT_BRANCH="$(git -C "$REPO_ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")"
IMAGE_TAG="ghcr.io/miragefoundation/mirage-node:${GIT_HASH}"

# Show deployment info and get confirmation BEFORE building
echo "=============================================================="
echo "Mirage Production Deploy (Registry)"
echo "Mode: ${MODE}"
echo "Image: ${IMAGE_TAG}"
echo "Branch: ${GIT_BRANCH}"
echo ""
echo "Deploying to hosts:"
for h in "${HOSTS[@]}"; do
  echo "  - ${SSH_USER}@${h}"
done
echo "=============================================================="

read -p "Type 'confirm' to proceed with production deploy: " -r CONFIRM
if [[ "${CONFIRM}" != "confirm" ]]; then
  echo "Aborted: confirmation text did not match 'confirm'."
  exit 1
fi

# Build and push to registry (once)
echo "==> Building and pushing to registry..."
"${DEPLOY_SH}" --build-only

# Deploy to all hosts (each pulls from registry)
for HOST in "${HOSTS[@]}"; do
  echo ""
  echo "=============================================================="
  echo "Deploying to ${SSH_USER}@${HOST}"
  echo "=============================================================="
  "${DEPLOY_SH}" "${SSH_USER}@${HOST}" "${MODE}" "${PROXYJUMP_ARGS[@]}"
done

echo ""
echo "=============================================================="
echo "Deploy complete."
echo "If HTTPS is not working on mirage.vote or mirage.talk, run on each host:"
echo "  docker exec mirage python3 /opt/mirage/deploy/setup_letsencrypt.py --domain=<domain>"
echo "=============================================================="
