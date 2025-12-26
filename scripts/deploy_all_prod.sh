#!/usr/bin/env bash
set -euo pipefail

# Hard-coded wrapper: deploy a pre-built tarball to all production servers.
#
# Usage:
#   scripts/deploy_all_prod.sh [--file <tarball>] [--init|--update|--update-init]
#
# Arguments:
#   --file <tarball>  Optional. Path to the Docker image tarball to deploy.
#                     If not provided, REBUILDS deploy/mirage-docker-dev.tar.gz automatically.
#
# Default mode: --update-init
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
DEFAULT_DEV_TARBALL="${REPO_ROOT}/deploy/mirage-docker-dev.tar.gz"
PROD_TARBALL_PATH="${REPO_ROOT}/deploy/mirage-docker-prod.tar.gz"

trash_file() {
  local file="$1"
  if [[ ! -e "$file" ]]; then
    return 0
  fi

  local backup_dir="${REPO_ROOT}/.trash"
  mkdir -p "${backup_dir}"
  local ts
  ts="$(date +%Y%m%d-%H%M%S)"
  local base
  base="$(basename "$file")"
  mv "$file" "${backup_dir}/${base}.${ts}"
}

# Parse arguments
MODE=""
TARBALL=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --init|--update|--update-init)
      MODE="$1"
      shift
      ;;
    --file)
      if [[ -z "${2-}" ]]; then
        echo "ERROR: --file requires a path argument" >&2
        exit 1
      fi
      TARBALL="$2"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1" >&2
      echo "Usage: $0 [--file <tarball>] [--init|--update|--update-init]" >&2
      exit 1
      ;;
  esac
done

if [[ -z "${MODE}" ]]; then
  MODE="--update-init"
fi

# Determine which tarball will be used and whether to rebuild
WILL_REBUILD=false
if [[ -z "${TARBALL}" ]]; then
  TARBALL="${DEFAULT_DEV_TARBALL}"
  WILL_REBUILD=true
fi

# Hard-coded production hosts
SSH_USER="${SSH_USER:-root}"
HOSTS=(
  "mirage.talk"
  "mirage.vote"
  "146.190.108.140"
  "139.59.9.96"  
)

# Show deployment info and get confirmation BEFORE building
echo "=============================================================="
echo "Mirage Production Deploy"
echo "Mode: ${MODE}"
if [[ "${WILL_REBUILD}" == "true" ]]; then
  echo "Tarball: ${TARBALL} (will be rebuilt)"
else
  echo "Tarball: ${TARBALL}"
fi
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

# Build tarball if needed (after confirmation)
if [[ "${WILL_REBUILD}" == "true" ]]; then
  echo "No --file provided, rebuilding dev tarball: ${TARBALL}"
  if [[ -f "${TARBALL}" ]]; then
    echo "Removing existing tarball before rebuild..."
    rm -f "${TARBALL}"
  fi
  echo "==> Building Docker image..."
  "${DEPLOY_SH}" --build-only --file "${TARBALL}"
fi

# Validate tarball
if [[ ! -f "${TARBALL}" ]]; then
  echo "ERROR: Tarball not found: ${TARBALL}" >&2
  exit 1
fi

if [[ ! -x "${DEPLOY_SH}" ]]; then
  echo "ERROR: Not found or not executable: ${DEPLOY_SH}" >&2
  exit 1
fi

# Deploy to all hosts using provided tarball
for HOST in "${HOSTS[@]}"; do
  echo "---- Deploying to ${SSH_USER}@${HOST}"
  "${DEPLOY_SH}" "${SSH_USER}@${HOST}" "${MODE}" --file "${TARBALL}"
done

# Always rotate tarballs: remove prod and rename dev to prod
echo "Rotating tarballs: dev -> prod"
if [[ -f "${PROD_TARBALL_PATH}" ]]; then
  echo "Removing existing prod tarball: ${PROD_TARBALL_PATH}"
  rm -f "${PROD_TARBALL_PATH}"
fi
if [[ -f "${DEFAULT_DEV_TARBALL}" ]]; then
  echo "Renaming dev tarball to prod: ${DEFAULT_DEV_TARBALL} -> ${PROD_TARBALL_PATH}"
  mv "${DEFAULT_DEV_TARBALL}" "${PROD_TARBALL_PATH}"
fi

echo "=============================================================="
echo "Deploy complete."
echo "If HTTPS is not working on mirage.vote or mirage.talk, run on each host:"
echo "  docker exec mirage bash /opt/mirage/deploy/letsencrypt_register.sh --domain <domain>"
echo "=============================================================="


