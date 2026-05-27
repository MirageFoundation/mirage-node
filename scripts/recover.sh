#!/usr/bin/env bash
# scripts/recover.sh
#
# Single recovery + provisioning tool for Mirage.
#
# Read this first during an incident
# ----------------------------------
# This file is intentionally both code and runbook. The recovery path is too
# dangerous to hide behind five tiny scripts with tribal knowledge in Slack:
# every destructive action, double-signing guard, and peer-safety check should
# be visible here.
#
# The normal operator flow is:
#
#   1. Provision recovery access once per cluster:
#
#        ./scripts/recover.sh provision \
#          --cluster=mirage-1 \
#          --peer=root@146.190.108.140 \
#          --peer=root@139.59.9.96 \
#          --container-host=root@64.23.136.132
#
#      What this does:
#        - creates/reuses a local Ed25519 recovery keypair;
#        - copies this same recover.sh file to each source peer host;
#        - appends a restricted authorized_keys line on each source peer that
#          forces `recover.sh serve` and gives NO shell;
#        - installs the private key on each target container host at
#          ~/.mirage/.ssh/recovery_id (visible inside the container as
#          /root/.mirage/.ssh/recovery_id).
#
#      Important: this script never discovers or contacts production hosts by
#      itself. You must pass every host explicitly.
#
#   2. Dry-run a target recovery from inside the target container:
#
#        docker exec mirage bash /opt/mirage/scripts/recover.sh peer-pull --dry-run
#
#      Dry-run proves the target can:
#        - parse persistent_peers;
#        - find >=2 healthy peers;
#        - confirm peers agree on app_hash;
#        - choose the source peer it would pull from.
#
#   3. Run the recovery:
#
#        docker exec mirage bash /opt/mirage/scripts/recover.sh peer-pull --auto
#
#      `--force` bypasses the 6h cool-down marker and should only be used when
#      the previous recovery obviously failed (for example miraged is dead and
#      the watchdog is in process-dead mode).
#
# Why peer-pull is the default
# ----------------------------
# The May 25 2026 incident showed that cosmos-sdk v0.53 state-sync can restore
# a snapshot whose appHash verifies, but still leave staking.Params.bond_denom
# empty. The next block then panics in mint.BeginBlocker:
#
#   mint.BeginBlocker
#     -> DefaultMintFn
#       -> StakingTokenSupply
#         -> BondDenom(ctx) == ""
#         -> bank.GetSupply("")
#         -> sdk.NewCoin("", ...) panic: invalid denom
#
# Until Phase 4 fixes that root cause, the watchdog defaults to peer-pull:
# copy chain DBs from a healthy peer instead of asking CometBFT state-sync to
# rebuild state from snapshots.
#
# What this script NEVER touches
# ------------------------------
# Recovery only replaces chain data under $NODE_HOME/data:
#
#   application.db blockstore.db cs.wal evidence.db snapshots state.db tx_index.db
#
# It never copies or modifies:
#   - PostgreSQL data (mirage_backend / mirage_indexer);
#   - keyring files;
#   - validator private keys;
#   - config/ files;
#   - env files except in `state-sync` mode, where STATESYNC_* values must be
#     written temporarily and STATESYNC_ENABLE is reset to false afterwards.
#
# The crucial file is priv_validator_state.json. This is the validator signing
# watermark. If we copy another peer's watermark or wipe ours permanently, we
# can double-sign. Every destructive recovery mode backs it up before wiping DBs
# and restores the local copy afterwards.
#
# Modes
# -----
#   recover.sh peer-pull  [--auto|--dry-run|--force]
#       Runs INSIDE the target container. This is the watchdog default. It
#       validates peers, wipes local chain DBs, pulls a tar from a healthy peer,
#       restores local priv_validator_state.json, restarts miraged, and only
#       writes the cool-down lock after health verification.
#
#   recover.sh state-sync [--auto|--dry-run|--force]
#       Runs INSIDE the target container. Legacy fallback that uses CometBFT
#       state-sync. Kept so we can test/fallback, but not the default until the
#       BondDenom state-sync bug is fixed.
#
#   recover.sh serve
#       Runs on the SOURCE PEER HOST, not inside the source container. This is
#       not something an operator normally types. It is the forced authorized_keys
#       command installed by `provision`. It pauses source miraged, streams a tar
#       of chain DBs to stdout, and resumes miraged on exit.
#
#   recover.sh provision --cluster=NAME --peer=user@host[:port]
#                        [--peer=...] [--container-host=user@host[:port]]
#                        [--key-dir=PATH] [--regenerate] [--yes]
#       Runs on the OPERATOR WORKSTATION. Installs the recovery key + forced
#       command plumbing. Idempotent; safe to re-run for the same cluster.
#
# Exit codes worth knowing
# ------------------------
#   0  success
#   1  generic fail-fast validation/command failure
#   4  state-sync mode never saw "Snapshot restored"
#   5  recovery restarted miraged but health verification failed, so no
#      cool-down lock was written and the watchdog may retry later
#
# Layout
# ------
# Shared helpers live first so the mode functions are easy to scan:
#   - peer discovery and app_hash validation;
#   - miraged supervisor stop/start;
#   - priv_validator_state.json backup/restore;
#   - health verification and cool-down lock write.
set -euo pipefail

SCRIPT_PATH="$(readlink -f "${BASH_SOURCE[0]}" 2>/dev/null || echo "${BASH_SOURCE[0]}")"

# ── Shared logging ──────────────────────────────────────────────────────
# log() always writes to stderr (so `serve` mode's stdout stream stays clean
# for the tar payload). The in-container modes additionally tee to a daily
# log file via the LOG_FILE global, set inside each mode's setup().
LOG_FILE=""

log() {
  local line
  line="[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"
  if [ -n "$LOG_FILE" ]; then
    printf '%s\n' "$line" | tee -a "$LOG_FILE" >&2
  else
    printf '%s\n' "$line" >&2
  fi
}

die() {
  log "ERROR: $*"
  exit 1
}

require_positive_int() {
  # Usage: require_positive_int VARNAME
  local name="$1"
  local val="${!name:-}"
  [[ "$val" =~ ^[1-9][0-9]*$ ]] || die "$name must be a positive integer (got: '$val')"
}

# ── Shared peer discovery (in-container modes) ──────────────────────────
# Both recovery modes start the same way: ask the target node's config which
# peers it is supposed to trust, then independently probe those peers' RPC
# endpoints. This is deliberate:
#
#   - We do NOT take a peer address from the operator during automatic recovery.
#     The cluster config is the source of truth.
#   - We skip our own node by node_id so a broken node never recovers from
#     itself.
#   - A peer only counts as healthy if /status says catching_up=False and it
#     has a non-zero latest_block_height.
#   - We require at least two healthy peers and then verify they agree on the
#     app_hash at a recent height. This prevents recovering from a split-brain
#     minority or from a single bad peer with a locally consistent but wrong
#     database.
#
# Outputs used by the mode functions:
#   PEER_SPECS[]      raw persistent_peers entries from config.toml
#   HEALTHY_RPC[]     http://IP:26657 for peers that passed health checks
#   HEALTHY_HEIGHT[]  latest heights parallel to HEALTHY_RPC[]
#   HEALTHY_IP[]      bare IPs parallel to HEALTHY_RPC[]; used for SSH
peer_discover_local_node_id() {
  LOCAL_NODE_ID=$(curl -fsS --max-time 3 http://127.0.0.1:26657/status 2>/dev/null \
    | python3 -c 'import sys,json; print(json.load(sys.stdin)["result"]["node_info"]["id"])' 2>/dev/null \
    || echo "")
  log "local node_id: ${LOCAL_NODE_ID:-(unknown)}"
}

peer_discover_persistent_specs() {
  : "${NODE_HOME:?NODE_HOME must be set before calling peer_discover_persistent_specs}"
  local cfg="$NODE_HOME/config/config.toml"
  local peers_line
  peers_line=$(grep -E '^persistent_peers' "$cfg" \
    | head -1 | sed -E 's/^persistent_peers *= *"([^"]*)".*/\1/' || true)
  [ -n "$peers_line" ] || die "no persistent_peers configured in $cfg"
  PEER_SPECS=()
  local spec
  for spec in ${peers_line//,/ }; do
    [ -n "$spec" ] && PEER_SPECS+=("$spec")
  done
  [ "${#PEER_SPECS[@]}" -gt 0 ] || die "persistent_peers parsed empty"
}

peer_discover_healthy() {
  HEALTHY_RPC=()
  HEALTHY_HEIGHT=()
  HEALTHY_IP=()
  local spec peer_id ip_port ip st remote_id catch hgt
  for spec in "${PEER_SPECS[@]}"; do
    peer_id="${spec%@*}"
    ip_port="${spec#*@}"
    ip="${ip_port%:*}"
    [ -z "$ip" ] && continue
    if [ -n "${LOCAL_NODE_ID:-}" ] && [ "$peer_id" = "$LOCAL_NODE_ID" ]; then
      log "  skip $ip (self by node_id)"; continue
    fi
    st=$(curl -fsS --max-time 5 "http://$ip:26657/status" 2>/dev/null || echo "")
    if [ -z "$st" ]; then log "  $ip unreachable"; continue; fi
    remote_id=$(echo "$st" | python3 -c 'import sys,json; print(json.load(sys.stdin)["result"]["node_info"]["id"])' 2>/dev/null || echo "")
    if [ -n "${LOCAL_NODE_ID:-}" ] && [ "$remote_id" = "$LOCAL_NODE_ID" ]; then
      log "  skip $ip (self by remote node_id)"; continue
    fi
    catch=$(echo "$st" | python3 -c 'import sys,json; print(json.load(sys.stdin)["result"]["sync_info"]["catching_up"])' 2>/dev/null || echo "true")
    hgt=$(echo   "$st" | python3 -c 'import sys,json; print(json.load(sys.stdin)["result"]["sync_info"]["latest_block_height"])' 2>/dev/null || echo "0")
    if [ "$catch" = "False" ] && [ "$hgt" != "0" ]; then
      HEALTHY_RPC+=("http://$ip:26657"); HEALTHY_HEIGHT+=("$hgt"); HEALTHY_IP+=("$ip")
      log "  healthy: $ip @ $hgt"
    else
      log "  $ip catching_up=$catch height=$hgt (unhealthy)"
    fi
  done
}

peer_pick_min_height() {
  [ "${#HEALTHY_HEIGHT[@]}" -gt 0 ] || die "peer_pick_min_height: no healthy peers"
  MIN_HEIGHT="${HEALTHY_HEIGHT[0]}"
  local h
  for h in "${HEALTHY_HEIGHT[@]}"; do
    [ "$h" -lt "$MIN_HEIGHT" ] && MIN_HEIGHT="$h"
  done
}

peer_validate_app_hash() {
  : "${MIN_HEIGHT:?call peer_pick_min_height first}"
  # Use MIN_HEIGHT-100 rather than tip. Tip can differ by a few blocks between
  # honest peers due to normal propagation. One hundred blocks back is recent
  # enough to catch a bad fork but old enough that healthy peers should all
  # have the block locally.
  #
  # On young chains (devnet, fresh testnets) MIN_HEIGHT may be < 100. Refuse
  # below height 2 (genesis is meaningless to cross-validate); otherwise fall
  # back to MIN_HEIGHT-1 with a warning so the lookback is still meaningful.
  if [ "$MIN_HEIGHT" -lt 2 ]; then
    die "MIN_HEIGHT=$MIN_HEIGHT too low to cross-validate app_hash (need >=2)"
  fi
  if [ "$MIN_HEIGHT" -gt 100 ]; then
    CHECK_HEIGHT=$((MIN_HEIGHT - 100))
  else
    CHECK_HEIGHT=$((MIN_HEIGHT - 1))
    log "  WARNING: MIN_HEIGHT=$MIN_HEIGHT; using CHECK_HEIGHT=$CHECK_HEIGHT (chain too young for 100-block lookback)"
  fi
  declare -A _seen=()
  local r ah
  for r in "${HEALTHY_RPC[@]}"; do
    ah=$(curl -fsS --max-time 5 "$r/block?height=$CHECK_HEIGHT" \
      | python3 -c 'import sys,json; print(json.load(sys.stdin)["result"]["block"]["header"]["app_hash"])' 2>/dev/null || echo "")
    [ -n "$ah" ] || die "peer $r failed to return block $CHECK_HEIGHT"
    _seen["$ah"]=1
    log "  $r app_hash@$CHECK_HEIGHT = ${ah:0:16}..."
  done
  if [ "${#_seen[@]}" -ne 1 ]; then
    die "peers DISAGREE on app_hash @ $CHECK_HEIGHT (count=${#_seen[@]}). Refusing to recover from inconsistent peers."
  fi
  log "peers agree on app_hash @ $CHECK_HEIGHT"
}

# ── Shared in-container helpers (peer-pull and state-sync share these) ──
stop_miraged_supervised() {
  # The node tmux window no longer runs `miraged start` directly; it runs
  # deploy/run_miraged_supervised.sh, which restarts miraged on crash. During a
  # recovery we need an intentional stop, not a crash-loop. So the sequence is:
  #
  #   1. Send C-c to the tmux node window. The supervisor's signal trap should
  #      set STOP_REQUESTED=1, terminate its child miraged, and exit 0.
  #   2. Wait up to 30s for both `miraged start` and the supervisor process to
  #      disappear.
  #   3. Escalate to SIGTERM, then SIGKILL.
  #   4. If either process still exists, fail hard BEFORE wiping DBs.
  #
  # Failing before the wipe is important: a live miraged process can keep DB
  # files open while we remove directories underneath it, producing corruption
  # that looks like a recovery bug later.
  log "stopping miraged + supervisor (tmux $TMUX_SESSION:node)..."
  if tmux has-session -t "$TMUX_SESSION" 2>/dev/null; then
    tmux send-keys -t "$TMUX_SESSION:node" C-c 2>/dev/null || true
  fi
  for _ in $(seq 1 30); do
    if ! pgrep -f "miraged start" >/dev/null 2>&1 && ! pgrep -f "run_miraged_supervised.sh" >/dev/null 2>&1; then
      break
    fi
    sleep 1
  done
  if pgrep -f "miraged start" >/dev/null 2>&1 || pgrep -f "run_miraged_supervised.sh" >/dev/null 2>&1; then
    log "supervisor didn't exit gracefully, sending SIGTERM"
    pkill -TERM -f "run_miraged_supervised.sh" 2>/dev/null || true
    pkill -TERM -f "miraged start" 2>/dev/null || true
    sleep 5
  fi
  if pgrep -f "miraged start" >/dev/null 2>&1 || pgrep -f "run_miraged_supervised.sh" >/dev/null 2>&1; then
    log "supervisor still running, sending SIGKILL"
    pkill -KILL -f "run_miraged_supervised.sh" 2>/dev/null || true
    pkill -KILL -f "miraged start" 2>/dev/null || true
    sleep 2
  fi
  if pgrep -f "miraged start" >/dev/null 2>&1 || pgrep -f "run_miraged_supervised.sh" >/dev/null 2>&1; then
    die "miraged or its supervisor is still running after SIGKILL"
  fi
  log "miraged stopped"
}

backup_priv_validator_state() {
  # This is the double-signing guard. priv_validator_state.json records the
  # highest height/round/step the validator has signed. The chain DBs are safe
  # to replace, but this watermark must stay local to the validator. Never copy
  # it from the peer tar. Never generate a fresh one for a live validator unless
  # you are intentionally tombstoning/re-keying and know the consensus rules.
  BACKUP_DIR="/root/.mirage/.recovery_backup"
  mkdir -p "$BACKUP_DIR"
  PV_STATE="$NODE_HOME/data/priv_validator_state.json"
  if [ -f "$PV_STATE" ]; then
    local ts_backup="$BACKUP_DIR/priv_validator_state.json.$(date -u +%Y%m%dT%H%M%SZ)"
    cp "$PV_STATE" "$ts_backup"
    cp "$PV_STATE" "$BACKUP_DIR/priv_validator_state.json.bak"
    log "backed up priv_validator_state.json -> $ts_backup"
  else
    log "WARNING: $PV_STATE not present (will be created fresh)"
  fi
}

restore_priv_validator_state() {
  if [ -f "$BACKUP_DIR/priv_validator_state.json.bak" ]; then
    cp "$BACKUP_DIR/priv_validator_state.json.bak" "$PV_STATE"
    log "restored priv_validator_state.json (height watermark preserved)"
  fi
}

wipe_chain_dbs() {
  # The only destructive filesystem operation in normal recovery. Keep this
  # list narrow. It is chain data only; no config/, keyring, Postgres, logs, or
  # env files. tx_index.db is included even though this cluster usually runs
  # indexer="null"; rm -rf on a missing dir is fine.
  log "wiping chain DBs in $NODE_HOME/data ..."
  cd "$NODE_HOME/data"
  rm -rf application.db blockstore.db cs.wal evidence.db snapshots state.db tx_index.db
  log "chain DBs wiped"
}

# Captures TODAYS_LOG and SUPERVISOR_LOG_LINE_START so verify_recovery_health
# can scan only the post-restart slice for "panic:". MUST be called BEFORE
# tmux send-keys restarts miraged.
prepare_supervisor_log_marker() {
  TODAYS_LOG="$LOGS_DIR/node/miraged-$(date -u +%Y-%m-%d).log"
  SUPERVISOR_LOG_LINE_START=1
  if [ -f "$TODAYS_LOG" ]; then
    SUPERVISOR_LOG_LINE_START=$(( $(wc -l < "$TODAYS_LOG") + 1 ))
  fi
}

restart_miraged_via_supervisor() {
  # Always restart via the supervisor, never `miraged start` directly. If the
  # node panics again, the supervisor gives it bounded retries and writes
  # supervisor messages into the miraged daily log, which is exactly what the
  # watchdog and incident triage expect.
  log "restarting miraged in tmux $TMUX_SESSION:node ..."
  local cmd="BIN=\"$BIN\" NODE_HOME=\"$NODE_HOME\" LOGS_DIR=\"$LOGS_DIR\" bash \"$ROOT_DIR/deploy/run_miraged_supervised.sh\""
  if tmux has-session -t "$TMUX_SESSION" 2>/dev/null; then
    tmux send-keys -t "$TMUX_SESSION:node" "$cmd" C-m
  else
    log "WARNING: tmux session $TMUX_SESSION missing; container restart will pick this up"
  fi
}

# Verifies miraged came back healthy: no "panic:" in the log slice since
# restart, AND latest_block_height > TRUST_HEIGHT, both within
# RECOVERY_VERIFY_SECONDS. Sets RECOVERY_VERIFIED=1 on success.
verify_recovery_health() {
  # A recovery is NOT successful just because miraged started or because
  # state-sync logged "Snapshot restored". The May 25 failure happened after
  # "Snapshot restored": miraged panicked on the next BeginBlock. So success is:
  #
  #   - no new "panic:" in the miraged log after the restart marker; AND
  #   - /status height advances past TRUST_HEIGHT before the verification budget.
  #
  # If this fails, we deliberately do not write the cool-down lock. The watchdog
  # can then retry instead of sitting out for six hours after a fake success.
  : "${TRUST_HEIGHT:?TRUST_HEIGHT must be set before verify_recovery_health}"
  RECOVERY_VERIFIED=0
  log "verifying miraged health for ${RECOVERY_VERIFY_SECONDS}s after restart..."
  local deadline cur_h
  deadline=$(( $(date +%s) + RECOVERY_VERIFY_SECONDS ))
  while [ "$(date +%s)" -lt "$deadline" ]; do
    if [ -f "$TODAYS_LOG" ] && tail -n +"$SUPERVISOR_LOG_LINE_START" "$TODAYS_LOG" | grep -q "panic:" 2>/dev/null; then
      log "ERROR: panic detected in miraged log after restart"
      return 0
    fi
    cur_h=$(curl -fsS --max-time 3 http://127.0.0.1:26657/status 2>/dev/null \
      | python3 -c 'import sys,json; print(json.load(sys.stdin)["result"]["sync_info"]["latest_block_height"])' 2>/dev/null \
      || echo 0)
    if [[ "$cur_h" =~ ^[0-9]+$ ]] && [ "$cur_h" -gt "$TRUST_HEIGHT" ]; then
      RECOVERY_VERIFIED=1
      log "verified: miraged height $cur_h is past trust height $TRUST_HEIGHT"
      return 0
    fi
    sleep 5
  done
}

pause_tmux_services() {
  # These services depend on the local node and can burn CPU during recovery.
  # Pausing them reduces noise while the node restarts and avoids backend/indexer
  # loops hammering an RPC endpoint that we know is unavailable.
  log "pausing indexer/backend/status windows ..."
  for w in indexer backend status; do
    tmux send-keys -t "$TMUX_SESSION:$w" C-c 2>/dev/null || true
  done
  sleep 3
}

resume_tmux_services() {
  log "resuming indexer/backend/status ..."
  if ! tmux has-session -t "$TMUX_SESSION" 2>/dev/null; then return 0; fi
  if tmux list-windows -t "$TMUX_SESSION" -F '#W' 2>/dev/null | grep -qx "indexer"; then
    tmux send-keys -t "$TMUX_SESSION:indexer" "PYTHONPATH=$ROOT_DIR python3 $ROOT_DIR/indexer/main.py" C-m
  fi
  if tmux list-windows -t "$TMUX_SESSION" -F '#W' 2>/dev/null | grep -qx "backend"; then
    tmux send-keys -t "$TMUX_SESSION:backend" "BACKEND_HOST=127.0.0.1 BACKEND_PORT=5000 PYTHONPATH=$ROOT_DIR python3 -m gunicorn -c gunicorn_config.py 'factory:app'" C-m
  fi
  if tmux list-windows -t "$TMUX_SESSION" -F '#W' 2>/dev/null | grep -qx "status"; then
    tmux send-keys -t "$TMUX_SESSION:status" "PYTHONPATH=$ROOT_DIR python3 $ROOT_DIR/scripts/status_dashboard.py" C-m
  fi
}

write_cooldown_lock_if_verified() {
  # The cool-down lock is the watchdog's "we already acted" marker. It must be
  # written only after verification, never merely after launching recovery.
  # Otherwise a bad recovery can suppress the next real recovery attempt.
  log "monitor: tmux attach -t $TMUX_SESSION  (window 'node')"
  log "logs:    $LOGS_DIR/node/miraged-$(date -u +%Y-%m-%d).log"
  log "this run's log: $LOG_FILE"
  log "NOTE: after blocksync catches up, run: docker exec mirage bash $ROOT_DIR/scripts/unjail_validator.sh"
  if [ "$RECOVERY_VERIFIED" = "1" ]; then
    date -u +%Y-%m-%dT%H:%M:%SZ > "$LOCK"
    log "recovery verified. Cool-down lock written: $LOCK"
    return 0
  fi
  log "ERROR: recovery was not verified; cool-down lock was not written"
  return 5
}

# Best-effort rollback if a recovery mode aborts after pausing services or
# stopping miraged. Set as an EXIT/INT/TERM trap so partial recoveries do not
# leave the node down indefinitely (which is what bit us during the May 25
# incident: miraged stayed dead after a "successful" recovery).
#
# Each mode sets the global flags TMUX_PAUSED / LOCAL_STOPPED as it crosses
# those checkpoints, and clears them (well, sets SERVICES_RESTARTED=1) once
# services are healthy again. The cleanup function only acts when the script
# is exiting non-zero AND services have not yet been restarted; otherwise it
# is a no-op so a final `exit 0` (or a verification-only failure with code 5)
# does not double-restart anything.
peer_pull_cleanup_on_abort() {
  local rc=$?
  trap - EXIT INT TERM
  if [ "$rc" -eq 0 ]; then exit 0; fi
  if [ "${SERVICES_RESTARTED:-0}" -eq 0 ]; then
    if [ "${LOCAL_STOPPED:-0}" -eq 1 ]; then
      log "peer-pull aborted (rc=$rc); attempting best-effort miraged restart"
      restart_miraged_via_supervisor || true
    fi
    if [ "${TMUX_PAUSED:-0}" -eq 1 ]; then
      log "peer-pull aborted (rc=$rc); attempting best-effort service resume"
      resume_tmux_services || true
    fi
  fi
  exit "$rc"
}

# State-sync's rollback is more involved than peer-pull's: we may have already
# set STATESYNC_ENABLE=true in node.env and re-rendered config.toml, so the
# next miraged start would attempt state-sync again and re-trigger whatever
# we just failed on. Reset both before letting the supervisor restart.
state_sync_cleanup_on_abort() {
  local rc=$?
  trap - EXIT INT TERM
  if [ "$rc" -eq 0 ]; then exit 0; fi
  if [ "${SERVICES_RESTARTED:-0}" -eq 0 ]; then
    log "state-sync aborted (rc=$rc); rolling back env to STATESYNC_ENABLE=false"
    sed -i 's|^STATESYNC_ENABLE=.*|STATESYNC_ENABLE=false|' "$ENV_FILE" 2>/dev/null || true
    # shellcheck disable=SC1090
    ( set -a; . "$ENV_FILE" 2>/dev/null; set +a; \
      python3 "$ROOT_DIR/deploy/render_template.py" \
        "$ROOT_DIR/deploy/templates/node/config.toml" \
        "$NODE_HOME/config/config.toml" 2>/dev/null ) || true
    if [ "${LOCAL_STOPPED:-0}" -eq 1 ]; then
      log "  attempting best-effort miraged restart"
      restart_miraged_via_supervisor || true
    fi
    if [ "${TMUX_PAUSED:-0}" -eq 1 ]; then
      log "  attempting best-effort service resume"
      resume_tmux_services || true
    fi
  fi
  exit "$rc"
}

setup_in_container_mode() {
  # Common defaults + arg parsing for peer-pull and state-sync modes. Parse
  # first so `recover.sh peer-pull --help` and "missing --auto" do not try to
  # create /root/.mirage paths when run from a workstation checkout.
  #
  # The --auto flag is intentionally mandatory for destructive modes. A plain
  # `recover.sh peer-pull` should never wipe DBs because someone pasted the
  # command halfway through. --dry-run is the safe preview path. --force exists
  # only to bypass the cool-down lock when the previous recovery demonstrably
  # failed (for example process-dead detection after a panic).
  AUTO=0; DRY_RUN=0; FORCE=0
  for a in "$@"; do
    case "$a" in
      --auto)    AUTO=1 ;;
      --dry-run) DRY_RUN=1 ;;
      --force)   FORCE=1 ;;
      -h|--help) usage_in_container; exit 0 ;;
      *)         die "unknown arg: $a" ;;
    esac
  done
  if [ "$AUTO" -ne 1 ] && [ "$DRY_RUN" -ne 1 ]; then
    die "refusing to run without --auto (destructive). Use --dry-run to preview."
  fi

  NODE_HOME="${NODE_HOME:-/root/.mirage/node}"
  ENV_FILE="${ENV_FILE:-/root/.mirage/env/node.env}"
  LOCK="${LOCK:-/root/.mirage/.divergence_recovery_lock}"
  DISABLE_MARKER="${DISABLE_MARKER:-/root/.mirage/.recovery_disabled}"
  BIN="${BIN:-/opt/mirage/blockchain/bin/miraged}"
  TMUX_SESSION="${TMUX_SESSION:-mirage}"
  COOLDOWN_SECONDS="${COOLDOWN_SECONDS:-21600}"
  LOGS_DIR="${LOGS_DIR:-/root/.mirage/logs}"
  ROOT_DIR="${ROOT_DIR:-/opt/mirage}"
  RECOVERY_VERIFY_SECONDS="${RECOVERY_VERIFY_SECONDS:-60}"
  LOG_FILE="${RECOVERY_LOG:-$LOGS_DIR/deploy/divergence_recovery-$(date -u +%Y-%m-%d).log}"
  mkdir -p "$(dirname "$LOG_FILE")"
  require_positive_int RECOVERY_VERIFY_SECONDS
  require_positive_int COOLDOWN_SECONDS
  if [ -e "$DISABLE_MARKER" ]; then
    die "recovery disabled by marker $DISABLE_MARKER (delete to re-enable)"
  fi
  if [ "$FORCE" -ne 1 ] && [ -e "$LOCK" ]; then
    local lock_age=$(( $(date +%s) - $(stat -c %Y "$LOCK" 2>/dev/null || echo 0) ))
    if [ "$lock_age" -lt "$COOLDOWN_SECONDS" ]; then
      die "cool-down active: last recovery ${lock_age}s ago (< ${COOLDOWN_SECONDS}s). Use --force to override."
    fi
  fi
}

# ── Mode: peer-pull ─────────────────────────────────────────────────────
# In-container; default watchdog path. SSH-pulls a chain-DB tar from one
# healthy peer (forced-command on the peer side runs `recover.sh serve`),
# extracts it on top of our wiped data dir, restarts via the supervisor.
cmd_peer_pull() {
  # High-level peer-pull sequence (post-review ordering: pull BEFORE wipe so a
  # failed transfer never leaves the local node with no chain data):
  #
  #   target container                         source peer host
  #   ----------------                         ----------------
  #   validate peers                           (idle)
  #   pick source peer
  #   ssh -i recovery_id --------------------> forced command: recover.sh serve
  #   receive tar to /tmp                       SIGSTOP source miraged
  #                                             tar chain DBs to stdout
  #                                             SIGCONT source miraged on EXIT
  #   gzip -t the tar
  #   verify tar listing has required dirs
  #   --- destructive boundary ---
  #   pause tmux services       (TMUX_PAUSED=1, install cleanup trap)
  #   stop local miraged        (LOCAL_STOPPED=1)
  #   backup priv_validator_state.json
  #   wipe local chain DBs
  #   extract tar into local NODE_HOME/data
  #   restore priv_validator_state.json
  #   restart local miraged via supervisor (SERVICES_RESTARTED=1)
  #   resume tmux services
  #   verify height progress + no panic
  #   clear cleanup trap
  #   write cool-down lock
  #
  # This avoids the cosmos-sdk state-sync code path entirely. It is effectively
  # "copy a known-good chain DB from a healthy peer", but without copying keys,
  # config, Postgres, or the peer's validator signing watermark.
  setup_in_container_mode "$@"
  PEER_PULL_SECONDS="${PEER_PULL_SECONDS:-1800}"
  RECOVERY_KEY="${RECOVERY_KEY:-/root/.mirage/.ssh/recovery_id}"
  PEER_SSH_USER="${PEER_SSH_USER:-root}"
  PEER_SSH_PORT="${PEER_SSH_PORT:-22}"
  # PEER_PULL_MIN_HEALTHY=1 enables single-survivor recovery (e.g. the
  # 2026-05-27 incident: an upgrade halt + a buggy watchdog wiped 3 of 4
  # validators, leaving only one node with chain data). Default stays at 2 so
  # the watchdog never silently trusts a single peer; the operator must opt in
  # by setting the env var explicitly.
  PEER_PULL_MIN_HEALTHY="${PEER_PULL_MIN_HEALTHY:-2}"
  require_positive_int PEER_PULL_SECONDS
  require_positive_int PEER_SSH_PORT
  require_positive_int PEER_PULL_MIN_HEALTHY

  log "discovering healthy peers from persistent_peers..."
  peer_discover_local_node_id
  peer_discover_persistent_specs
  peer_discover_healthy
  [ "${#HEALTHY_RPC[@]}" -ge "$PEER_PULL_MIN_HEALTHY" ] \
    || die "need >=${PEER_PULL_MIN_HEALTHY} healthy peers, found ${#HEALTHY_RPC[@]}. Aborting (avoid blind recovery)."
  peer_pick_min_height
  if [ "${#HEALTHY_RPC[@]}" -ge 2 ]; then
    peer_validate_app_hash
  else
    log "  WARNING: only 1 healthy peer (${HEALTHY_IP[0]}); skipping cross-validation."
    log "  WARNING: trusting this peer's chain state without app_hash agreement check."
    log "  WARNING: this is single-survivor recovery; the operator is responsible for"
    log "  WARNING: confirming the source peer is the canonical chain (PEER_PULL_MIN_HEALTHY=${PEER_PULL_MIN_HEALTHY})."
  fi

  # Pick highest healthy peer as the source. If one healthy peer is ahead of
  # the rest, pulling from it reduces catch-up time after extraction. The
  # app_hash agreement check already proved it is on the same chain as the
  # other healthy peers at CHECK_HEIGHT.
  local source_ip="" source_height=0 i
  for i in "${!HEALTHY_HEIGHT[@]}"; do
    if [ "${HEALTHY_HEIGHT[$i]}" -gt "$source_height" ]; then
      source_height="${HEALTHY_HEIGHT[$i]}"
      source_ip="${HEALTHY_IP[$i]}"
    fi
  done
  [ -n "$source_ip" ] || die "could not pick a source peer"
  log "selected source peer: $source_ip @ height $source_height"
  TRUST_HEIGHT="$source_height"

  # Dry-run is intentionally permissive: it does not require RECOVERY_KEY to
  # exist so an operator can validate peer-discovery + app-hash agreement on a
  # workstation that has not yet been provisioned. We only flag the absence as
  # an informational note.
  if [ "$DRY_RUN" -eq 1 ]; then
    log "DRY RUN — would: pause services, stop miraged, wipe DBs,"
    log "DRY RUN — ssh -i $RECOVERY_KEY $PEER_SSH_USER@$source_ip, extract, restart,"
    log "DRY RUN — verify height > $TRUST_HEIGHT, write cool-down lock."
    if [ ! -f "$RECOVERY_KEY" ]; then
      log "DRY RUN — note: $RECOVERY_KEY not present; provisioning required before --auto"
    fi
    exit 0
  fi

  # --- AUTO path: from here on, real recovery work begins. ---
  # Recovery key check is deferred until after dry-run handling above.
  if [ ! -f "$RECOVERY_KEY" ]; then
    # Installed by `recover.sh provision` on the container host. Required for
    # --auto because peer-pull is run by the watchdog with no SSH agent.
    die "recovery key missing at $RECOVERY_KEY — run 'recover.sh provision' first"
  fi
  local key_perms
  key_perms=$(stat -c %a "$RECOVERY_KEY" 2>/dev/null || echo "")
  [ "$key_perms" = "600" ] || [ "$key_perms" = "400" ] \
    || die "recovery key $RECOVERY_KEY has insecure perms ($key_perms); must be 600 or 400"

  local tar_path="/tmp/mirage_peer_snapshot.tar.gz"
  rm -f "$tar_path"
  # Keep SSH state under /root/.mirage so it survives container restarts with
  # the node data volume. StrictHostKeyChecking=accept-new is intentional:
  # first recovery after provisioning should not hang on an interactive prompt,
  # but changed host keys still fail.
  mkdir -p /root/.mirage/.ssh
  chmod 700 /root/.mirage/.ssh
  log "pulling chain snapshot from $PEER_SSH_USER@$source_ip (timeout ${PEER_PULL_SECONDS}s)..."
  local ssh_opts=(
    -i "$RECOVERY_KEY"
    -p "$PEER_SSH_PORT"
    -o BatchMode=yes
    -o StrictHostKeyChecking=accept-new
    -o UserKnownHostsFile=/root/.mirage/.ssh/known_hosts
    -o ConnectTimeout=10
    -o ServerAliveInterval=30
    -o ServerAliveCountMax=4
  )
  # The remote side ignores any command we send because authorized_keys forces
  # `recover.sh serve`. We redirect stdout to a local tar file. All remote logs
  # go to stderr, so they do not corrupt the tar stream.
  if ! timeout "$PEER_PULL_SECONDS" ssh "${ssh_opts[@]}" "$PEER_SSH_USER@$source_ip" >"$tar_path"; then
    rm -f "$tar_path"
    die "ssh peer-pull from $source_ip failed or timed out after ${PEER_PULL_SECONDS}s"
  fi
  [ -s "$tar_path" ] || { rm -f "$tar_path"; die "peer-pull produced empty tar"; }
  local tar_bytes
  tar_bytes=$(stat -c %s "$tar_path" 2>/dev/null || echo 0)
  log "tar received: ${tar_bytes} bytes; verifying integrity..."

  # gzip -t catches transport corruption (truncation, bit flips) without
  # decompressing the whole stream. Cheap insurance against wiping local DBs
  # for a corrupt tar.
  if ! gzip -t "$tar_path" 2>/dev/null; then
    rm -f "$tar_path"
    die "received tar failed gzip integrity check"
  fi

  # Validate tar listing BEFORE wiping local DBs. If the source forgot to tar a
  # required directory (or the source's data dir was misconfigured), we want to
  # find out now, not after we have already deleted our copy.
  local listing d
  listing=$(tar -tzf "$tar_path" 2>/dev/null) || { rm -f "$tar_path"; die "tar listing failed"; }
  for d in application.db blockstore.db cs.wal evidence.db state.db; do
    if ! grep -q "^$d/" <<<"$listing"; then
      rm -f "$tar_path"
      die "tar listing missing required dir: $d (refusing to wipe local DBs)"
    fi
  done
  log "tar contents OK; required dirs present"

  # --- Destructive boundary. From here on, install the cleanup trap so an
  # abort restarts services instead of leaving the node down. ---
  pause_tmux_services
  TMUX_PAUSED=1
  trap peer_pull_cleanup_on_abort EXIT INT TERM
  stop_miraged_supervised
  LOCAL_STOPPED=1
  backup_priv_validator_state
  wipe_chain_dbs

  log "extracting tar into $NODE_HOME/data ..."
  if ! tar -xzf "$tar_path" -C "$NODE_HOME/data"; then
    rm -f "$tar_path"
    die "tar extract failed"
  fi
  # `tar --ignore-failed-read` on the source tolerates optional dirs like
  # tx_index.db, so the target must re-assert the core DB directories after
  # extraction. This catches truncated streams and source-side filesystem bugs.
  for d in application.db blockstore.db cs.wal evidence.db state.db; do
    [ -e "$NODE_HOME/data/$d" ] || die "extracted snapshot missing required dir: $d"
  done
  log "extracted snapshot has all required dirs"
  rm -f "$tar_path"

  restore_priv_validator_state
  prepare_supervisor_log_marker
  restart_miraged_via_supervisor
  SERVICES_RESTARTED=1
  resume_tmux_services
  verify_recovery_health
  # Verification done; cool-down lock writing has its own non-destructive exit
  # codes (5 = not verified). Disarm the cleanup trap so a 5 does not trigger
  # a redundant restart.
  trap - EXIT INT TERM
  write_cooldown_lock_if_verified || exit $?
  exit 0
}

# ── Mode: state-sync ────────────────────────────────────────────────────
# In-container; legacy CometBFT state-sync. Kept until Phase 4 fixes the
# v0.53 BondDenom panic. See docs/troubleshooting/incident-recovery.md.
cmd_state_sync() {
  # State-sync mode is kept because it is still useful for comparison/testing
  # and may become safe again after Phase 4. It is NOT the default watchdog
  # mode right now.
  #
  # The important hard-won details are:
  #
  #   - Choose trust_height = snapshot_height + 1. On our droplets, CometBFT's
  #     light client can blow its per-RPC deadline when it has to bisect across
  #     a long range. Pinning to snapshot+1 collapses verification to a short
  #     path.
  #   - Reset STATESYNC_ENABLE=false after the attempt. If we leave it true,
  #     any future container restart will accidentally state-sync again.
  #   - Do not write the cool-down lock until miraged survives past the trust
  #     height with no panic. This directly addresses the May 25 false-success
  #     failure mode.
  setup_in_container_mode "$@"
  STATESYNC_WAIT_SECONDS="${STATESYNC_WAIT_SECONDS:-300}"
  require_positive_int STATESYNC_WAIT_SECONDS

  # SNAPSHOT_INTERVAL: env override > node.env > default 14400. The default is
  # kept for emergency operation when node.env is damaged, but invalid values
  # still fail hard below.
  # shellcheck disable=SC1090
  SNAPSHOT_INTERVAL="${SNAPSHOT_INTERVAL:-$(grep -E '^SNAPSHOT_INTERVAL=' "$ENV_FILE" 2>/dev/null | cut -d= -f2 | head -1)}"
  SNAPSHOT_INTERVAL="${SNAPSHOT_INTERVAL:-14400}"
  require_positive_int SNAPSHOT_INTERVAL
  log "snapshot interval: $SNAPSHOT_INTERVAL blocks"

  log "discovering healthy peers from persistent_peers..."
  peer_discover_local_node_id
  peer_discover_persistent_specs
  peer_discover_healthy
  [ "${#HEALTHY_RPC[@]}" -ge 2 ] \
    || die "need >=2 healthy peers, found ${#HEALTHY_RPC[@]}. Aborting."
  peer_pick_min_height
  peer_validate_app_hash

  # Trust block = snapshot height + 1 (no light-client bisection).
  # Latest snapshot height is floor(tip / SNAPSHOT_INTERVAL) * SNAPSHOT_INTERVAL;
  # back off one interval if the tip is too close to it (peers may not have
  # finished creating that snapshot yet).
  local latest_snap=$((MIN_HEIGHT / SNAPSHOT_INTERVAL * SNAPSHOT_INTERVAL))
  if [ $((MIN_HEIGHT - latest_snap)) -lt 20 ]; then
    latest_snap=$((latest_snap - SNAPSHOT_INTERVAL))
  fi
  TRUST_HEIGHT=$((latest_snap + 1))
  if [ "$TRUST_HEIGHT" -le 0 ] || [ "$TRUST_HEIGHT" -gt "$MIN_HEIGHT" ]; then
    die "computed nonsensical trust_height=$TRUST_HEIGHT (snap=$latest_snap, tip=$MIN_HEIGHT)"
  fi
  local trust_hash
  trust_hash=$(curl -fsS --max-time 5 "${HEALTHY_RPC[0]}/block?height=$TRUST_HEIGHT" \
    | python3 -c 'import sys,json; print(json.load(sys.stdin)["result"]["block_id"]["hash"])' 2>/dev/null || echo "")
  [ -n "$trust_hash" ] || die "could not fetch trust hash @ $TRUST_HEIGHT"
  log "trust block: height=$TRUST_HEIGHT (snap+1, snap=$latest_snap) hash=$trust_hash"

  local rpc_csv="${HEALTHY_RPC[0]},${HEALTHY_RPC[1]}"
  if [ "${#HEALTHY_RPC[@]}" -ge 3 ]; then
    rpc_csv="$rpc_csv,${HEALTHY_RPC[2]}"
  fi
  log "rpc_servers: $rpc_csv"

  if [ "$DRY_RUN" -eq 1 ]; then
    log "DRY RUN — would set STATESYNC_* in $ENV_FILE, restart miraged via supervisor,"
    log "DRY RUN — wait for 'Snapshot restored', verify miraged health, write cool-down."
    exit 0
  fi

  # --- Destructive boundary. The cleanup trap also resets STATESYNC_ENABLE
  # on abort so a supervisor-driven restart does not re-trigger state-sync. ---
  pause_tmux_services
  TMUX_PAUSED=1
  trap state_sync_cleanup_on_abort EXIT INT TERM
  stop_miraged_supervised
  LOCAL_STOPPED=1
  backup_priv_validator_state
  wipe_chain_dbs
  restore_priv_validator_state

  log "updating $ENV_FILE STATESYNC_* ..."
  # Structured edit via Python instead of sed chains: all state-sync settings
  # are updated together. Each key MUST already exist in node.env; if any is
  # missing we fail hard rather than silently no-op (which would leave miraged
  # to start without state-sync configured and look "successful" while doing
  # the wrong thing). The deploy templates always include these keys.
  python3 - "$ENV_FILE" "$rpc_csv" "$TRUST_HEIGHT" "$trust_hash" <<'PY'
import sys, pathlib, re
env_path, rpc_csv, trust_h, trust_hash = sys.argv[1:5]
p = pathlib.Path(env_path)
t = p.read_text()
def patch(s, k, v):
    new, n = re.subn(rf"^{k}=.*", f"{k}={v}", s, count=1, flags=re.M)
    if n != 1:
        sys.stderr.write(f"ERROR: required key '{k}' not found in {env_path}\n")
        sys.exit(2)
    return new
t = patch(t, "STATESYNC_ENABLE", "true")
t = patch(t, "STATESYNC_RPC_SERVERS", rpc_csv)
t = patch(t, "STATESYNC_TRUST_HEIGHT", trust_h)
t = patch(t, "STATESYNC_TRUST_HASH", trust_hash)
p.write_text(t)
PY

  log "re-rendering $NODE_HOME/config/config.toml from template ..."
  # shellcheck disable=SC1090
  ( set -a; . "$ENV_FILE"; set +a; \
    python3 "$ROOT_DIR/deploy/render_template.py" \
      "$ROOT_DIR/deploy/templates/node/config.toml" \
      "$NODE_HOME/config/config.toml" )

  prepare_supervisor_log_marker
  restart_miraged_via_supervisor
  SERVICES_RESTARTED=1

  log "waiting up to ${STATESYNC_WAIT_SECONDS}s for snapshot to be restored..."
  local snapshot_ok=0 deadline
  deadline=$(( $(date +%s) + STATESYNC_WAIT_SECONDS ))
  while [ "$(date +%s)" -lt "$deadline" ]; do
    if [ -f "$TODAYS_LOG" ] && tail -n +"$SUPERVISOR_LOG_LINE_START" "$TODAYS_LOG" | grep -q "Snapshot restored" 2>/dev/null; then
      snapshot_ok=1
      # Bump the log-line marker forward so verify_recovery_health only
      # scans for "panic:" AFTER snapshot restore (avoids matching pre-restore noise).
      SUPERVISOR_LOG_LINE_START=$(wc -l < "$TODAYS_LOG")
      break
    fi
    sleep 5
  done
  if [ "$snapshot_ok" = "1" ]; then
    log "snapshot restored. now blocksyncing forward..."
  else
    log "WARNING: no 'Snapshot restored' line within ${STATESYNC_WAIT_SECONDS}s"
  fi

  log "resetting STATESYNC_ENABLE=false in $ENV_FILE for future restarts..."
  sed -i 's|^STATESYNC_ENABLE=.*|STATESYNC_ENABLE=false|' "$ENV_FILE"

  resume_tmux_services
  if [ "$snapshot_ok" = "1" ]; then
    verify_recovery_health
  fi
  # Recovery is past the destructive section; disarm the cleanup trap before
  # the cool-down write so a non-zero "not verified" exit (code 5) does not
  # trigger a redundant restart.
  trap - EXIT INT TERM
  write_cooldown_lock_if_verified || {
    rc=$?
    [ "$snapshot_ok" = "1" ] || rc=4
    exit $rc
  }
  exit 0
}

# ── Mode: serve ─────────────────────────────────────────────────────────
# Runs on a peer's docker host under a forced authorized_keys command.
# Streams a gzipped tar of chain DBs to stdout, pausing miraged with SIGSTOP
# (and ALWAYS resuming with SIGCONT on exit, even on failure).
cmd_serve() {
  # This mode is intentionally weird because it is an SSH forced command.
  #
  # The peer-pull client runs:
  #   ssh -i /root/.mirage/.ssh/recovery_id root@PEER > /tmp/mirage_peer_snapshot.tar.gz
  #
  # But the peer's authorized_keys line ignores the client command and forces:
  #   /opt/mirage/scripts/recover.sh serve
  #
  # That gives the recovery key exactly one capability: stream chain DBs. It
  # cannot open a shell, forward ports, allocate a TTY, or use agent forwarding.
  #
  # stdout contract:
  #   stdout MUST be only the gzipped tar stream. All logs from this mode go to
  #   stderr via log(), otherwise the receiver would save corrupted tar bytes.
  #
  # pause strategy:
  #   We SIGSTOP source miraged instead of stopping the container. The process
  #   remains alive, so the supervisor does not restart it. A trap SIGCONTs it
  #   on every exit path. This gives us a consistent on-disk snapshot window
  #   without leaving the source validator down if the SSH connection dies.
  # Forced command means $SSH_ORIGINAL_COMMAND is set to whatever the client
  # tried to run; deliberately discard it.
  unset SSH_ORIGINAL_COMMAND

  command -v docker >/dev/null 2>&1 || die "docker not found in PATH"
  command -v tar    >/dev/null 2>&1 || die "tar not found in PATH"
  command -v flock  >/dev/null 2>&1 || die "flock not found in PATH"

  local container="${MIRAGE_CONTAINER:-mirage}"
  local host_data_dir="${HOST_DATA_DIR:-$HOME/.mirage/node/data}"
  local lock_file="${PEER_SNAPSHOT_LOCK:-/run/mirage_peer_snapshot.lock}"

  [ -d "$host_data_dir" ] || die "chain data dir not present: $host_data_dir"
  if ! docker inspect -f '{{.State.Running}}' "$container" 2>/dev/null | grep -q true; then
    die "container '$container' is not running"
  fi
  if ! docker exec "$container" pgrep -f "miraged start" >/dev/null 2>&1; then
    die "miraged is not running inside container '$container'"
  fi

  # Single-instance guard: two concurrent SIGSTOPs would race and could
  # leave miraged frozen indefinitely.
  exec 9>"$lock_file" || die "could not open lock $lock_file"
  flock -n 9 || die "another serve is already running (lock $lock_file held)"

  local paused=0
  resume_serve() {
    if [ "$paused" -eq 1 ]; then
      log "resuming miraged (SIGCONT)..."
      docker exec "$container" pkill -CONT -f "miraged start" 2>/dev/null || true
      paused=0
    fi
  }
  trap resume_serve EXIT INT TERM

  log "pausing miraged in '$container' (SIGSTOP)..."
  docker exec "$container" pkill -STOP -f "miraged start" 2>/dev/null \
    || die "failed to send SIGSTOP to miraged"
  paused=1
  # Settle for any in-flight Pebble flush. SIGSTOP is delivered immediately
  # but write syscalls can be pending; 1s is more than enough on local disk.
  sleep 1

  local db_dirs="application.db blockstore.db cs.wal evidence.db snapshots state.db tx_index.db"
  log "tarring chain data ($db_dirs) from $host_data_dir ..."
  # --ignore-failed-read tolerates dirs missing on this peer (e.g. tx_index.db
  # when CometBFT runs with indexer="null"). priv_validator_state.json is
  # excluded so the receiver's signing watermark is never overwritten.
  # shellcheck disable=SC2086 # db_dirs is intentionally word-split into args
  if ! tar --ignore-failed-read \
      --exclude='priv_validator_state.json' \
      -czf - \
      -C "$host_data_dir" \
      $db_dirs; then
    die "tar failed while streaming chain data"
  fi
  log "tar stream complete"
  # trap fires here -> SIGCONT -> miraged resumes
}

# ── Mode: provision ─────────────────────────────────────────────────────
# Workstation-side; one-time. Generates an Ed25519 keypair and installs:
#   - this script + restricted authorized_keys line on each --peer
#   - the private key into each --container-host's ~/.mirage/.ssh/recovery_id
# Idempotent (skip-if-marker-present).
cmd_provision() {
  # This mode replaces the old separate provisioning script. It is intentionally
  # explicit: no discovery, no hidden production host list, no automatic fleet
  # mutation. It touches only the hosts supplied by --peer and --container-host.
  #
  # --peer hosts are source peers. They receive:
  #   - /opt/mirage/scripts/recover.sh
  #   - a restricted authorized_keys line for the recovery public key:
  #
  #       restrict,command="/opt/mirage/scripts/recover.sh serve",...
  #
  # --container-host hosts are recovery targets. They receive:
  #   - ~/.mirage/.ssh/recovery_id
  #
  # The target's Docker container sees that host path as:
  #   - /root/.mirage/.ssh/recovery_id
  #
  # Re-running is safe:
  #   - the keypair is reused unless --regenerate is passed;
  #   - recover.sh is copied only when sha256 differs;
  #   - authorized_keys is not appended twice if the cluster marker exists.
  local cluster=""
  local key_dir="$HOME/.mirage/recovery_keys"
  local regenerate=0
  local assume_yes=0
  local peers=()
  local container_hosts=()
  local a
  for a in "$@"; do
    case "$a" in
      --cluster=*)        cluster="${a#*=}" ;;
      --peer=*)           peers+=("${a#*=}") ;;
      --container-host=*) container_hosts+=("${a#*=}") ;;
      --key-dir=*)        key_dir="${a#*=}" ;;
      --regenerate)       regenerate=1 ;;
      --yes)              assume_yes=1 ;;
      -h|--help)          usage_provision; exit 0 ;;
      *) die "unknown arg: $a" ;;
    esac
  done
  [ -n "$cluster" ] || die "--cluster=NAME is required"
  [[ "$cluster" =~ ^[a-zA-Z0-9_.-]+$ ]] || die "--cluster must match [a-zA-Z0-9_.-]+"
  [ "${#peers[@]}" -gt 0 ] || [ "${#container_hosts[@]}" -gt 0 ] \
    || die "nothing to do: pass at least one --peer or --container-host"

  local ssh_dest_re='^[A-Za-z0-9_.-]+@[A-Za-z0-9_.-]+(:[1-9][0-9]*)?$'
  for a in "${peers[@]}" "${container_hosts[@]}"; do
    [[ "$a" =~ $ssh_dest_re ]] \
      || die "invalid SSH target: '$a' (expected user@host or user@host:port)"
  done

  mkdir -p "$key_dir"
  chmod 700 "$key_dir"
  local priv="$key_dir/recovery_id_${cluster}"
  local pub="$priv.pub"
  if { [ -f "$priv" ] || [ -f "$pub" ]; } && [ "$regenerate" -eq 1 ]; then
    log "regenerating: removing existing keypair at $priv"
    rm -f "$priv" "$pub"
  fi
  if [ ! -f "$priv" ] || [ ! -f "$pub" ]; then
    if [ -f "$priv" ] || [ -f "$pub" ]; then
      die "partial keypair at $key_dir; pass --regenerate to overwrite"
    fi
    log "generating Ed25519 keypair at $priv"
    ssh-keygen -t ed25519 -N "" -C "mirage-recovery-${cluster}" -f "$priv" >/dev/null
    chmod 600 "$priv"
    chmod 644 "$pub"
  else
    log "reusing existing keypair at $priv"
  fi

  # Build the authorized_keys line. The pubkey is appended to a fixed
  # restrictions prefix that forces `recover.sh serve`.
  local pubkey
  pubkey="$(<"$pub")"
  local auth_line='restrict,command="/opt/mirage/scripts/recover.sh serve",no-port-forwarding,no-X11-forwarding,no-agent-forwarding,no-pty '"$pubkey"

  local marker="mirage-recovery-${cluster}"
  local target user_host port_arg ssh_args scp_args
  for target in "${peers[@]}"; do
    user_host="${target%:*}"
    port_arg=()
    if [[ "$target" == *:* ]]; then
      port_arg=( -p "${target##*:}" )
    fi
    ssh_args=( "${port_arg[@]}" -o BatchMode=yes -o ConnectTimeout=10 )
    scp_args=()
    if [[ "$target" == *:* ]]; then
      scp_args=( -P "${target##*:}" )
    fi
    scp_args+=( -o BatchMode=yes -o ConnectTimeout=10 )

    log "=== peer: $target ==="
    if [ "$assume_yes" -ne 1 ]; then
      printf '[provision] deploy recover.sh + authorized_keys line to %s? [y/N] ' "$target" >&2
      local ans=""; read -r ans || true
      case "$ans" in y|Y|yes|YES) : ;; *) log "skipped (user)"; continue ;; esac
    fi

    ssh "${ssh_args[@]}" "$user_host" "mkdir -p /opt/mirage/scripts && chmod 0755 /opt/mirage/scripts"

    # SHA-skip the script copy if the peer already has the current version.
    # This matters because `provision` may be re-run during an incident to
    # repair only authorized_keys; needless writes to peers add risk/noise.
    local local_sha remote_sha
    local_sha="$(sha256sum "$SCRIPT_PATH" | awk '{print $1}')"
    remote_sha="$(ssh "${ssh_args[@]}" "$user_host" \
      "sha256sum /opt/mirage/scripts/recover.sh 2>/dev/null | awk '{print \$1}'" || echo "")"
    if [ -n "$remote_sha" ] && [ "$remote_sha" = "$local_sha" ]; then
      log "  recover.sh already current on $target (sha256 match)"
    else
      scp "${scp_args[@]}" "$SCRIPT_PATH" "$user_host:/opt/mirage/scripts/recover.sh"
      ssh "${ssh_args[@]}" "$user_host" "chmod 0755 /opt/mirage/scripts/recover.sh"
      log "  installed /opt/mirage/scripts/recover.sh on $target"
    fi

    # Idempotent authorized_keys handling, with stale-line replacement.
    #
    # The marker is the key comment generated by ssh-keygen
    # (mirage-recovery-$cluster). We do a single fetch of any existing
    # marker line(s) and pick one of three outcomes:
    #
    #   1. no marker found  -> append fresh
    #   2. exact match      -> already current, skip
    #   3. anything else    -> stale entry (e.g. forced command pointing to the
    #                          old peer_snapshot_server.sh, or a previous
    #                          recovery key that has since been rotated).
    #                          Atomically rewrite authorized_keys without any
    #                          marker lines, then append the fresh entry.
    #
    # Atomic rewrite uses awk + tmpfile + mv on the remote side so a partially-
    # written authorized_keys never leaves the peer un-loginable.
    ssh "${ssh_args[@]}" "$user_host" \
      "mkdir -p ~/.ssh && chmod 0700 ~/.ssh && touch ~/.ssh/authorized_keys && chmod 0600 ~/.ssh/authorized_keys"

    local existing
    existing="$(ssh "${ssh_args[@]}" "$user_host" \
      "grep -F '$marker' ~/.ssh/authorized_keys 2>/dev/null" || true)"

    if [ -z "$existing" ]; then
      printf '%s\n' "$auth_line" \
        | ssh "${ssh_args[@]}" "$user_host" "cat >> ~/.ssh/authorized_keys"
      log "  appended authorized_keys line for $marker"
    elif [ "$existing" = "$auth_line" ]; then
      log "  authorized_keys already current for marker '$marker'"
    else
      log "  authorized_keys has stale entry for '$marker'; replacing atomically"
      # shellcheck disable=SC2087
      ssh "${ssh_args[@]}" "$user_host" "
        set -e
        ak=\"\$HOME/.ssh/authorized_keys\"
        tmp=\"\$(mktemp \"\${ak}.XXXXXX\")\"
        awk -v m='$marker' 'index(\$0, m) == 0' \"\$ak\" > \"\$tmp\"
        chmod 0600 \"\$tmp\"
        mv \"\$tmp\" \"\$ak\"
      "
      printf '%s\n' "$auth_line" \
        | ssh "${ssh_args[@]}" "$user_host" "cat >> ~/.ssh/authorized_keys"
      log "  rewrote authorized_keys with current line for $marker"
    fi
  done

  for target in "${container_hosts[@]}"; do
    user_host="${target%:*}"
    port_arg=()
    if [[ "$target" == *:* ]]; then port_arg=( -p "${target##*:}" ); fi
    ssh_args=( "${port_arg[@]}" -o BatchMode=yes -o ConnectTimeout=10 )
    scp_args=()
    if [[ "$target" == *:* ]]; then scp_args=( -P "${target##*:}" ); fi
    scp_args+=( -o BatchMode=yes -o ConnectTimeout=10 )

    log "=== container-host: $target ==="
    if [ "$assume_yes" -ne 1 ]; then
      printf '[provision] install recovery private key into %s:~/.mirage/.ssh/recovery_id? [y/N] ' "$target" >&2
      local ans=""; read -r ans || true
      case "$ans" in y|Y|yes|YES) : ;; *) log "skipped (user)"; continue ;; esac
    fi
    ssh "${ssh_args[@]}" "$user_host" "mkdir -p ~/.mirage/.ssh && chmod 0700 ~/.mirage/.ssh"
    scp "${scp_args[@]}" "$priv" "$user_host:.mirage/.ssh/recovery_id"
    ssh "${ssh_args[@]}" "$user_host" "chmod 0600 ~/.mirage/.ssh/recovery_id"
    log "  installed private key at $target:~/.mirage/.ssh/recovery_id"
  done

  log "done"
}

# ── Usage / dispatch ────────────────────────────────────────────────────
usage() {
  cat >&2 <<EOF
Usage: recover.sh <mode> [args]

Incident quick start:
  # Preview default recovery from inside the target container:
  docker exec mirage bash /opt/mirage/scripts/recover.sh peer-pull --dry-run

  # Run default recovery from inside the target container:
  docker exec mirage bash /opt/mirage/scripts/recover.sh peer-pull --auto

  # Bypass cool-down after a failed previous recovery:
  docker exec mirage bash /opt/mirage/scripts/recover.sh peer-pull --auto --force

Modes:
  peer-pull  [--auto|--dry-run|--force]
      In-container; ssh-pulls a chain-data tar from a healthy peer.
      Default path used by scripts/divergence_watchdog.py.

  state-sync [--auto|--dry-run|--force]
      In-container; legacy CometBFT state-sync recovery. Kept as fallback;
      currently affected by a v0.53 BondDenom-after-restore panic (see
      docs/troubleshooting/incident-recovery.md).

  serve
      Peer-host-side; intended ONLY as the forced-command target of an
      authorized_keys entry. Streams a gzipped tar of chain DBs to stdout
      while pausing miraged with SIGSTOP (resumed on exit).

  provision --cluster=NAME
            --peer=user@host[:port] [--peer=...]
            [--container-host=user@host[:port]]
            [--key-dir=PATH] [--regenerate] [--yes]
      Workstation-side; one-time. Generates an Ed25519 keypair, scps this
      script + a restricted authorized_keys line to each --peer, and drops
      the private key into each --container-host's ~/.mirage/.ssh/recovery_id.
      Idempotent.

Safety summary:
  - peer-pull/state-sync refuse to wipe DBs without --auto or --dry-run.
  - priv_validator_state.json is backed up and restored locally.
  - peers must be healthy and agree on app_hash before recovery proceeds.
  - PostgreSQL, keyrings, validator keys, config/, and backend data are untouched.
  - cool-down is written only after post-restart health verification.
EOF
}

usage_in_container() {
  cat >&2 <<EOF
Usage: recover.sh <peer-pull|state-sync> [--auto|--dry-run|--force]

Env overrides (peer-pull):
  RECOVERY_KEY        default: /root/.mirage/.ssh/recovery_id
  PEER_SSH_USER       default: root
  PEER_SSH_PORT       default: 22
  PEER_PULL_SECONDS   default: 1800

Env overrides (both):
  NODE_HOME, ENV_FILE, LOCK, BIN, TMUX_SESSION, ROOT_DIR, LOGS_DIR,
  COOLDOWN_SECONDS, RECOVERY_VERIFY_SECONDS, RECOVERY_LOG

Env overrides (state-sync only):
  STATESYNC_WAIT_SECONDS  default: 300
  SNAPSHOT_INTERVAL       default: from ENV_FILE, fallback 14400
EOF
}

usage_provision() {
  cat >&2 <<EOF
Usage: recover.sh provision --cluster=NAME --peer=user@host[:port] [...]
                            [--container-host=user@host[:port]]
                            [--key-dir=PATH] [--regenerate] [--yes]

Example:
  ./scripts/recover.sh provision \\
    --cluster=mirage-1 \\
    --peer=root@146.190.108.140 \\
    --peer=root@139.59.9.96 \\
    --container-host=root@64.23.136.132

What --peer means:
  Install recover.sh plus a forced authorized_keys entry on this source peer.
  The key can only run: /opt/mirage/scripts/recover.sh serve

What --container-host means:
  Install the private recovery key into that host's ~/.mirage/.ssh/recovery_id,
  which is visible inside the mirage container as /root/.mirage/.ssh/recovery_id.
EOF
}

main() {
  case "${1:-}" in
    peer-pull)  shift; cmd_peer_pull  "$@" ;;
    state-sync) shift; cmd_state_sync "$@" ;;
    serve)      shift; cmd_serve      "$@" ;;
    provision)  shift; cmd_provision  "$@" ;;
    ""|-h|--help) usage; exit 0 ;;
    *) echo "unknown mode: $1" >&2; usage; exit 1 ;;
  esac
}

main "$@"
