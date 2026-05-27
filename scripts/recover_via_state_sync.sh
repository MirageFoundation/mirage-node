#!/usr/bin/env bash
# scripts/recover_via_state_sync.sh
#
# Recover a forked / app-hash-diverged Mirage node by state-syncing from
# healthy peers. Designed to run INSIDE the mirage container, called either
# by hand (with --auto) or by scripts/divergence_watchdog.py.
#
# Safety:
#   - Refuses to run without --auto (or --dry-run).
#   - Preserves priv_validator_state.json (no double-sign).
#   - Only touches chain DBs under $NODE_HOME/data — never touches PostgreSQL,
#     the keyring, env files, or backend data. Honors the mirage.talk hard
#     rule from docs/troubleshooting/incident-recovery.md (no cross-node
#     restore on the prod app host; chain-state-only recovery).
#   - Cross-validates >=2 healthy peers agree on app_hash for a recent
#     height before wiping anything.
#   - Honors a 6h cool-down marker (~/.mirage/.divergence_recovery_lock) so
#     repeated triggers don't loop. --force overrides.
#
# Hard-won field notes (2026-05-04 mirage.talk incident):
#   * On under-provisioned / noisy droplets (high steal time) the CometBFT
#     light client's per-RPC deadline (~5s) blows up under bisection, so
#     ALWAYS pin trust_height to the snapshot height + 1 — that eliminates
#     the bisection ladder and reduces verification to one VerifyHeader call.
#   * The indexer + backend can hog enough CPU to push the light client
#     over its deadline. We pause them during state-sync and resume after.
#
# Usage:
#   docker exec mirage /opt/mirage/scripts/recover_via_state_sync.sh --auto
#   docker exec mirage /opt/mirage/scripts/recover_via_state_sync.sh --dry-run
#
# Env overrides:
#   NODE_HOME, ENV_FILE, LOCK, BIN, TMUX_SESSION, COOLDOWN_SECONDS,
#   SNAPSHOT_INTERVAL, STATESYNC_WAIT_SECONDS, RECOVERY_VERIFY_SECONDS,
#   RECOVERY_LOG

set -euo pipefail

NODE_HOME="${NODE_HOME:-/root/.mirage/node}"
ENV_FILE="${ENV_FILE:-/root/.mirage/env/node.env}"
LOCK="${LOCK:-/root/.mirage/.divergence_recovery_lock}"
DISABLE_MARKER="${DISABLE_MARKER:-/root/.mirage/.recovery_disabled}"
BIN="${BIN:-/opt/mirage/blockchain/bin/miraged}"
TMUX_SESSION="${TMUX_SESSION:-mirage}"
COOLDOWN_SECONDS="${COOLDOWN_SECONDS:-21600}"  # 6h
LOGS_DIR="${LOGS_DIR:-/root/.mirage/logs}"
RECOVERY_LOG="${RECOVERY_LOG:-$LOGS_DIR/deploy/divergence_recovery-$(date -u +%Y-%m-%d).log}"
ROOT_DIR="${ROOT_DIR:-/opt/mirage}"
STATESYNC_WAIT_SECONDS="${STATESYNC_WAIT_SECONDS:-300}"  # max 5 min for snapshot to apply
RECOVERY_VERIFY_SECONDS="${RECOVERY_VERIFY_SECONDS:-60}"

mkdir -p "$(dirname "$RECOVERY_LOG")"

log() {
  printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" | tee -a "$RECOVERY_LOG"
}

die() {
  log "ERROR: $*"
  exit 1
}

[[ "$STATESYNC_WAIT_SECONDS" =~ ^[1-9][0-9]*$ ]] || die "STATESYNC_WAIT_SECONDS must be a positive integer"
[[ "$RECOVERY_VERIFY_SECONDS" =~ ^[1-9][0-9]*$ ]] || die "RECOVERY_VERIFY_SECONDS must be a positive integer"

# ── Args ─────────────────────────────────────────────────────────────────
AUTO=0
DRY_RUN=0
FORCE=0
for a in "$@"; do
  case "$a" in
    --auto)    AUTO=1 ;;
    --dry-run) DRY_RUN=1 ;;
    --force)   FORCE=1 ;;
    -h|--help) sed -n '2,40p' "$0"; exit 0 ;;
    *)         die "unknown arg: $a" ;;
  esac
done

if [ "$AUTO" -ne 1 ] && [ "$DRY_RUN" -ne 1 ]; then
  die "refusing to run without --auto (destructive). Use --dry-run to preview."
fi

# ── Pre-flight: opt-out + cool-down ──────────────────────────────────────
if [ -e "$DISABLE_MARKER" ]; then
  die "recovery disabled by marker $DISABLE_MARKER (delete to re-enable)"
fi

if [ "$FORCE" -ne 1 ] && [ -e "$LOCK" ]; then
  lock_age=$(( $(date +%s) - $(stat -c %Y "$LOCK" 2>/dev/null || echo 0) ))
  if [ "$lock_age" -lt "$COOLDOWN_SECONDS" ]; then
    die "cool-down active: last recovery ${lock_age}s ago (< ${COOLDOWN_SECONDS}s). Use --force to override."
  fi
fi

# ── Read SNAPSHOT_INTERVAL from env (fallback 14400) ─────────────────────
# shellcheck disable=SC1090
SNAPSHOT_INTERVAL="${SNAPSHOT_INTERVAL:-$(grep -E '^SNAPSHOT_INTERVAL=' "$ENV_FILE" 2>/dev/null | cut -d= -f2 | head -1)}"
SNAPSHOT_INTERVAL="${SNAPSHOT_INTERVAL:-14400}"
[[ "$SNAPSHOT_INTERVAL" =~ ^[1-9][0-9]*$ ]] || die "SNAPSHOT_INTERVAL must be a positive integer"
log "snapshot interval: $SNAPSHOT_INTERVAL blocks"

# ── Discover healthy peers ───────────────────────────────────────────────
log "discovering healthy peers from persistent_peers..."

LOCAL_NODE_ID=$(curl -fsS --max-time 3 http://127.0.0.1:26657/status 2>/dev/null \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["result"]["node_info"]["id"])' 2>/dev/null \
  || echo "")
log "local node_id: ${LOCAL_NODE_ID:-(unknown)}"

PEERS_LINE=$(grep -E '^persistent_peers' "$NODE_HOME/config/config.toml" \
  | head -1 | sed -E 's/^persistent_peers *= *"([^"]*)".*/\1/' || true)
[ -n "$PEERS_LINE" ] || die "no persistent_peers configured"

declare -a HEALTHY_RPC=()
declare -a HEALTHY_HEIGHT=()

for spec in ${PEERS_LINE//,/ }; do
  peer_id="${spec%@*}"
  ip_port="${spec#*@}"
  ip="${ip_port%:*}"
  [ -z "$ip" ] && continue

  if [ -n "$LOCAL_NODE_ID" ] && [ "$peer_id" = "$LOCAL_NODE_ID" ]; then
    log "  skip $ip (self by node_id)"
    continue
  fi

  st=$(curl -fsS --max-time 5 "http://$ip:26657/status" 2>/dev/null || echo "")
  if [ -z "$st" ]; then
    log "  $ip unreachable"
    continue
  fi

  remote_id=$(echo "$st" | python3 -c 'import sys,json; print(json.load(sys.stdin)["result"]["node_info"]["id"])' 2>/dev/null || echo "")
  if [ -n "$LOCAL_NODE_ID" ] && [ "$remote_id" = "$LOCAL_NODE_ID" ]; then
    log "  skip $ip (self by remote node_id)"
    continue
  fi

  catch=$(echo "$st" | python3 -c 'import sys,json; print(json.load(sys.stdin)["result"]["sync_info"]["catching_up"])' 2>/dev/null || echo "true")
  hgt=$(echo   "$st" | python3 -c 'import sys,json; print(json.load(sys.stdin)["result"]["sync_info"]["latest_block_height"])' 2>/dev/null || echo "0")

  if [ "$catch" = "False" ] && [ "$hgt" != "0" ]; then
    HEALTHY_RPC+=("http://$ip:26657")
    HEALTHY_HEIGHT+=("$hgt")
    log "  healthy: $ip @ $hgt"
  else
    log "  $ip catching_up=$catch height=$hgt (unhealthy)"
  fi
done

if [ "${#HEALTHY_RPC[@]}" -lt 2 ]; then
  die "need >=2 healthy peers, found ${#HEALTHY_RPC[@]}. Aborting (avoid blind recovery)."
fi

# ── Cross-validate: peers agree on app_hash for some recent height ───────
MIN_H="${HEALTHY_HEIGHT[0]}"
for h in "${HEALTHY_HEIGHT[@]}"; do
  [ "$h" -lt "$MIN_H" ] && MIN_H="$h"
done
CHECK_H=$((MIN_H - 100))

declare -A SEEN_AHASH=()
for r in "${HEALTHY_RPC[@]}"; do
  ah=$(curl -fsS --max-time 5 "$r/block?height=$CHECK_H" \
    | python3 -c 'import sys,json; print(json.load(sys.stdin)["result"]["block"]["header"]["app_hash"])' 2>/dev/null || echo "")
  [ -n "$ah" ] || die "peer $r failed to return block $CHECK_H"
  SEEN_AHASH["$ah"]=1
  log "  $r app_hash@$CHECK_H = ${ah:0:16}..."
done

if [ "${#SEEN_AHASH[@]}" -ne 1 ]; then
  die "peers DISAGREE on app_hash @ $CHECK_H (count=${#SEEN_AHASH[@]}). Refusing to recover from inconsistent peers."
fi
log "peers agree on app_hash @ $CHECK_H"

# ── Compute trust block: snapshot height + 1 (no bisection) ──────────────
# Latest snapshot is at floor(tip / SNAPSHOT_INTERVAL) * SNAPSHOT_INTERVAL.
# Pick one snapshot back to ensure peers actually have it created & served.
# (peers create the snapshot a few seconds after committing block N.)
LATEST_SNAP=$((MIN_H / SNAPSHOT_INTERVAL * SNAPSHOT_INTERVAL))
# If tip is within 60s of the latest snapshot height, the snapshot may not be
# fully committed on all peers yet — back off one interval.
if [ $((MIN_H - LATEST_SNAP)) -lt 20 ]; then
  LATEST_SNAP=$((LATEST_SNAP - SNAPSHOT_INTERVAL))
fi
TRUST_HEIGHT=$((LATEST_SNAP + 1))

# Sanity bound: trust height must be > 0 and <= MIN_H
if [ "$TRUST_HEIGHT" -le 0 ] || [ "$TRUST_HEIGHT" -gt "$MIN_H" ]; then
  die "computed nonsensical trust_height=$TRUST_HEIGHT (snap=$LATEST_SNAP, tip=$MIN_H)"
fi

TRUST_HASH=$(curl -fsS --max-time 5 "${HEALTHY_RPC[0]}/block?height=$TRUST_HEIGHT" \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["result"]["block_id"]["hash"])' 2>/dev/null || echo "")
[ -n "$TRUST_HASH" ] || die "could not fetch trust hash @ $TRUST_HEIGHT"
log "trust block: height=$TRUST_HEIGHT (snapshot+1, snapshot=$LATEST_SNAP) hash=$TRUST_HASH"

# Use up to first 3 healthy peers for rpc_servers (CometBFT requires >=2)
RPC_CSV="${HEALTHY_RPC[0]},${HEALTHY_RPC[1]}"
if [ "${#HEALTHY_RPC[@]}" -ge 3 ]; then
  RPC_CSV="$RPC_CSV,${HEALTHY_RPC[2]}"
fi
log "rpc_servers: $RPC_CSV"

if [ "$DRY_RUN" -eq 1 ]; then
  log "DRY RUN — would now: pause indexer+backend+status, stop miraged, wipe chain DBs,"
  log "DRY RUN — set STATESYNC_* in $ENV_FILE, restart miraged, wait for snapshot,"
  log "DRY RUN — restore STATESYNC_ENABLE=false, restart paused services."
  log "DRY RUN — exiting without changes."
  exit 0
fi

# ── Pause CPU-heavy services to free deadline budget for state-sync ──────
log "pausing indexer/backend/status windows to free CPU for state-sync..."
for w in indexer backend status; do
  tmux send-keys -t "$TMUX_SESSION:$w" C-c 2>/dev/null || true
done
sleep 3

# ── Stop miraged via tmux ────────────────────────────────────────────────
log "stopping miraged (tmux $TMUX_SESSION:node)..."
if tmux has-session -t "$TMUX_SESSION" 2>/dev/null; then
  tmux send-keys -t "$TMUX_SESSION:node" C-c 2>/dev/null || true
fi
for i in $(seq 1 30); do
  if ! pgrep -f "miraged start" >/dev/null 2>&1 && ! pgrep -f "run_miraged_supervised.sh" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
if pgrep -f "miraged start" >/dev/null 2>&1 || pgrep -f "run_miraged_supervised.sh" >/dev/null 2>&1; then
  log "miraged supervisor didn't exit gracefully, sending SIGTERM"
  pkill -TERM -f "run_miraged_supervised.sh" 2>/dev/null || true
  pkill -TERM -f "miraged start" 2>/dev/null || true
  sleep 5
fi
if pgrep -f "miraged start" >/dev/null 2>&1 || pgrep -f "run_miraged_supervised.sh" >/dev/null 2>&1; then
  log "miraged supervisor still running, sending SIGKILL"
  pkill -KILL -f "run_miraged_supervised.sh" 2>/dev/null || true
  pkill -KILL -f "miraged start" 2>/dev/null || true
  sleep 2
fi
if pgrep -f "miraged start" >/dev/null 2>&1 || pgrep -f "run_miraged_supervised.sh" >/dev/null 2>&1; then
  die "miraged or its supervisor is still running after SIGKILL"
fi
log "miraged stopped"

# ── Backup priv_validator_state.json ─────────────────────────────────────
BACKUP_DIR="/root/.mirage/.recovery_backup"
mkdir -p "$BACKUP_DIR"
PV_STATE="$NODE_HOME/data/priv_validator_state.json"
if [ -f "$PV_STATE" ]; then
  TS_BACKUP="$BACKUP_DIR/priv_validator_state.json.$(date -u +%Y%m%dT%H%M%SZ)"
  cp -v "$PV_STATE" "$TS_BACKUP" | tee -a "$RECOVERY_LOG"
  cp "$PV_STATE" "$BACKUP_DIR/priv_validator_state.json.bak"
else
  log "WARNING: $PV_STATE not present (will be created fresh)"
fi

# ── Wipe chain DBs ───────────────────────────────────────────────────────
log "wiping chain DBs in $NODE_HOME/data ..."
cd "$NODE_HOME/data"
rm -rf application.db blockstore.db cs.wal evidence.db snapshots state.db tx_index.db
log "chain DBs wiped. Remaining files:"
ls -la "$NODE_HOME/data" | tee -a "$RECOVERY_LOG"

# ── Restore priv_validator_state.json ────────────────────────────────────
if [ -f "$BACKUP_DIR/priv_validator_state.json.bak" ]; then
  cp "$BACKUP_DIR/priv_validator_state.json.bak" "$PV_STATE"
  log "restored priv_validator_state.json (height-watermark preserved)"
fi

# ── Update STATESYNC_* in node.env ───────────────────────────────────────
log "updating $ENV_FILE STATESYNC_* ..."
python3 - "$ENV_FILE" "$RPC_CSV" "$TRUST_HEIGHT" "$TRUST_HASH" <<'PY'
import sys, pathlib, re
env_path, rpc_csv, trust_h, trust_hash = sys.argv[1:5]
p = pathlib.Path(env_path)
t = p.read_text()
def patch(s, k, v):
    return re.sub(rf"^{k}=.*", f"{k}={v}", s, count=1, flags=re.M)
t = patch(t, "STATESYNC_ENABLE", "true")
t = patch(t, "STATESYNC_RPC_SERVERS", rpc_csv)
t = patch(t, "STATESYNC_TRUST_HEIGHT", trust_h)
t = patch(t, "STATESYNC_TRUST_HASH", trust_hash)
p.write_text(t)
print("[updated]")
PY

log "re-rendering $NODE_HOME/config/config.toml from template ..."
# shellcheck disable=SC1090
( set -a; . "$ENV_FILE"; set +a; \
  python3 "$ROOT_DIR/deploy/render_template.py" \
    "$ROOT_DIR/deploy/templates/node/config.toml" \
    "$NODE_HOME/config/config.toml" )

# ── Restart miraged in the existing tmux node window ─────────────────────
log "restarting miraged in tmux $TMUX_SESSION:node ..."
NODE_START_CMD="BIN=\"$BIN\" NODE_HOME=\"$NODE_HOME\" LOGS_DIR=\"$LOGS_DIR\" bash \"$ROOT_DIR/deploy/run_miraged_supervised.sh\""
TODAYS_LOG="$LOGS_DIR/node/miraged-$(date -u +%Y-%m-%d).log"
SNAPSHOT_SEARCH_START=1
if [ -f "$TODAYS_LOG" ]; then
  SNAPSHOT_SEARCH_START=$(( $(wc -l < "$TODAYS_LOG") + 1 ))
fi
if tmux has-session -t "$TMUX_SESSION" 2>/dev/null; then
  tmux send-keys -t "$TMUX_SESSION:node" "$NODE_START_CMD" C-m
else
  log "WARNING: tmux session $TMUX_SESSION missing; container restart will pick this up"
fi

# ── Wait for snapshot to be applied ──────────────────────────────────────
log "waiting up to ${STATESYNC_WAIT_SECONDS}s for snapshot to be restored..."
SNAPSHOT_OK=0
SNAPSHOT_LOG_LINE=1
DEADLINE=$(( $(date +%s) + STATESYNC_WAIT_SECONDS ))
while [ "$(date +%s)" -lt "$DEADLINE" ]; do
  if [ -f "$TODAYS_LOG" ] && tail -n +"$SNAPSHOT_SEARCH_START" "$TODAYS_LOG" | grep -q "Snapshot restored" 2>/dev/null; then
    SNAPSHOT_OK=1
    SNAPSHOT_LOG_LINE=$(wc -l < "$TODAYS_LOG")
    break
  fi
  sleep 5
done
if [ "$SNAPSHOT_OK" = "1" ]; then
  log "snapshot restored. now blocksyncing forward..."
else
  log "WARNING: no 'Snapshot restored' line within ${STATESYNC_WAIT_SECONDS}s — state-sync may have failed"
  log "WARNING: check tmux mirage:node and $TODAYS_LOG"
fi

# ── Reset STATESYNC_ENABLE so future restarts don't re-trigger sync ──────
log "resetting STATESYNC_ENABLE=false in $ENV_FILE for future restarts..."
sed -i 's|^STATESYNC_ENABLE=.*|STATESYNC_ENABLE=false|' "$ENV_FILE"

# ── Resume paused services ───────────────────────────────────────────────
log "resuming indexer/backend/status ..."
if tmux has-session -t "$TMUX_SESSION" 2>/dev/null; then
  if tmux list-windows -t "$TMUX_SESSION" -F '#W' 2>/dev/null | grep -qx "indexer"; then
    tmux send-keys -t "$TMUX_SESSION:indexer" "PYTHONPATH=$ROOT_DIR python3 $ROOT_DIR/indexer/main.py" C-m
  fi
  if tmux list-windows -t "$TMUX_SESSION" -F '#W' 2>/dev/null | grep -qx "backend"; then
    tmux send-keys -t "$TMUX_SESSION:backend" "BACKEND_HOST=127.0.0.1 BACKEND_PORT=5000 PYTHONPATH=$ROOT_DIR python3 -m gunicorn -c gunicorn_config.py 'factory:app'" C-m
  fi
  if tmux list-windows -t "$TMUX_SESSION" -F '#W' 2>/dev/null | grep -qx "status"; then
    tmux send-keys -t "$TMUX_SESSION:status" "PYTHONPATH=$ROOT_DIR python3 $ROOT_DIR/scripts/status_dashboard.py" C-m
  fi
fi

# ── Verify miraged survived snapshot restore before writing cool-down ─────
RECOVERY_VERIFIED=0
if [ "$SNAPSHOT_OK" = "1" ]; then
  log "verifying miraged health for ${RECOVERY_VERIFY_SECONDS}s after snapshot restore..."
  VERIFY_DEADLINE=$(( $(date +%s) + RECOVERY_VERIFY_SECONDS ))
  while [ "$(date +%s)" -lt "$VERIFY_DEADLINE" ]; do
    if [ -f "$TODAYS_LOG" ] && tail -n +"$SNAPSHOT_LOG_LINE" "$TODAYS_LOG" | grep -q "panic:" 2>/dev/null; then
      log "ERROR: panic detected in miraged log after snapshot restore"
      break
    fi

    cur_h=$(curl -fsS --max-time 3 http://127.0.0.1:26657/status 2>/dev/null \
      | python3 -c 'import sys,json; print(json.load(sys.stdin)["result"]["sync_info"]["latest_block_height"])' 2>/dev/null \
      || echo 0)

    if [[ "$cur_h" =~ ^[0-9]+$ ]] && [ "$cur_h" -gt "$TRUST_HEIGHT" ]; then
      RECOVERY_VERIFIED=1
      log "verified: miraged height $cur_h is past trust height $TRUST_HEIGHT"
      break
    fi

    sleep 5
  done
fi

# ── Mark cool-down ───────────────────────────────────────────────────────
log "monitor: tmux attach -t $TMUX_SESSION  (window 'node')"
log "logs:    $LOGS_DIR/node/miraged-$(date -u +%Y-%m-%d).log"
log "this script's log: $RECOVERY_LOG"

# ── After-state hint: reminder to unjail ─────────────────────────────────
log "NOTE: after blocksync catches up, run: docker exec mirage bash $ROOT_DIR/scripts/unjail_validator.sh"

if [ "$RECOVERY_VERIFIED" = "1" ]; then
  date -u +%Y-%m-%dT%H:%M:%SZ > "$LOCK"
  log "recovery verified. Cool-down lock written: $LOCK"
  exit 0
fi

if [ "$SNAPSHOT_OK" != "1" ]; then
  exit 4
fi

log "ERROR: recovery was not verified; cool-down lock was not written"
exit 5
