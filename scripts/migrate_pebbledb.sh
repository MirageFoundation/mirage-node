#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BLOCKCHAIN_DIR="$REPO_ROOT/blockchain"

DATA_DIR="\$HOME/.mirage/node/data"
ENV_FILE="\$HOME/.mirage/env/node.env"
CONTAINER="mirage"
HEALTH_TIMEOUT=120

usage() {
  cat <<EOF
Usage: $0 <server>

Converts application.db from GoLevelDB to PebbleDB on the target server.

Arguments:
  server    SSH target (e.g. root@64.23.136.132)

Steps performed:
  1. Cross-compile convert-db for linux/amd64
  2. Show before sizes
  3. scp convert-db to target:/tmp/
  4. Stop container
  5. Run converter on host
  6. Set APP_DB_BACKEND=pebbledb in node.env
  7. Start container
  8. Wait for node health + validate bond_denom
  9. Show after sizes
  10. Clean up

Example:
  $0 root@64.23.136.132
EOF
  exit 1
}

if [ $# -ne 1 ]; then
  usage
fi

SERVER="$1"

run() {
  ssh "$SERVER" "$@"
}

log() {
  echo "==> $*"
}

die() {
  echo "ERROR: $*" >&2
  exit 1
}

current_backend=$(run "grep '^APP_DB_BACKEND=' $ENV_FILE | cut -d= -f2-") || die "Failed to read APP_DB_BACKEND"
if [ "$current_backend" = "pebbledb" ]; then
  die "Already running PebbleDB on $SERVER"
fi

log "Step 1/10: Cross-compiling convert-db for linux/amd64"
cd "$BLOCKCHAIN_DIR"
GOOS=linux GOARCH=amd64 make build-convert-db
CONVERT_BIN="$BLOCKCHAIN_DIR/bin/convert-db"
[ -f "$CONVERT_BIN" ] || die "convert-db binary not found at $CONVERT_BIN"

log "Step 2/10: Before sizes on $SERVER"
run "du -sh $DATA_DIR/application.db 2>/dev/null || echo 'application.db not found'"
run "df -h $DATA_DIR | tail -1"

log "Step 3/10: Uploading convert-db to $SERVER:/tmp/"
scp "$CONVERT_BIN" "$SERVER:/tmp/convert-db"
run "chmod +x /tmp/convert-db"

log "Step 4/10: Stopping container '$CONTAINER'"
run "docker stop --timeout=30 $CONTAINER" || die "Failed to stop container"
echo "    Container stopped."

log "Step 5/10: Running converter"
if ! run "/tmp/convert-db $DATA_DIR"; then
  echo "    CONVERTER FAILED — restarting container with original DB"
  run "docker start $CONTAINER" || true
  die "Conversion failed. Node restarted with GoLevelDB."
fi

log "Step 6/10: Setting APP_DB_BACKEND=pebbledb"
run "sed -i 's/^APP_DB_BACKEND=.*/APP_DB_BACKEND=pebbledb/' $ENV_FILE"
verify=$(run "grep '^APP_DB_BACKEND=' $ENV_FILE | cut -d= -f2-")
[ "$verify" = "pebbledb" ] || die "Failed to update APP_DB_BACKEND (got: $verify)"
echo "    node.env updated."

log "Step 7/10: Starting container '$CONTAINER'"
run "docker start $CONTAINER" || die "Failed to start container"
echo "    Container started."

log "Step 8/10: Waiting for node health (timeout: ${HEALTH_TIMEOUT}s)"
elapsed=0
while [ $elapsed -lt $HEALTH_TIMEOUT ]; do
  sleep 5
  elapsed=$((elapsed + 5))

  status=$(run "curl -sf http://localhost:26657/status 2>/dev/null" || echo "")
  if [ -z "$status" ]; then
    echo "    [$elapsed/${HEALTH_TIMEOUT}s] RPC not ready..."
    continue
  fi

  catching_up=$(echo "$status" | jq -r '.result.sync_info.catching_up // empty')
  latest_height=$(echo "$status" | jq -r '.result.sync_info.latest_block_height // "0"')

  if [ "$catching_up" = "false" ] && [ "$latest_height" != "0" ]; then
    echo "    Node synced at height $latest_height"
    break
  fi

  echo "    [$elapsed/${HEALTH_TIMEOUT}s] height=$latest_height catching_up=$catching_up"
done

if [ $elapsed -ge $HEALTH_TIMEOUT ]; then
  echo "    WARNING: Health check timed out. Node may still be catching up."
  echo "    Check manually: ssh $SERVER 'curl -s http://localhost:26657/status | jq .result.sync_info'"
fi

log "Step 9/10: Validating bond_denom"
bond_denom=$(run "curl -sf 'http://localhost:1317/cosmos/staking/v1beta1/params' 2>/dev/null" | jq -r '.params.bond_denom // empty' || echo "")
if [ "$bond_denom" = "umirage" ]; then
  echo "    bond_denom=umirage OK"
elif [ -z "$bond_denom" ]; then
  echo "    WARNING: Could not query bond_denom (API may not be ready yet)"
  echo "    Verify manually: curl -s http://$SERVER:1317/cosmos/staking/v1beta1/params | jq .params.bond_denom"
else
  echo "    CRITICAL: bond_denom='$bond_denom' — expected 'umirage'"
  echo "    Consider rolling back: set APP_DB_BACKEND=goleveldb, restore application.db.bak"
fi

log "Step 10/10: After sizes on $SERVER"
run "du -sh $DATA_DIR/application.db 2>/dev/null || echo 'application.db not found'"
run "du -sh $DATA_DIR/application.db.bak 2>/dev/null || echo 'no backup (already cleaned?)'"
run "df -h $DATA_DIR | tail -1"

log "Cleaning up"
run "rm -f /tmp/convert-db"
run "rm -rf $DATA_DIR/application.db.bak"
echo "    Cleanup done."

echo ""
echo "Migration complete on $SERVER"
echo "PebbleDB is now active with continuous background compaction."
