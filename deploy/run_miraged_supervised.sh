#!/usr/bin/env bash
set -uo pipefail

NODE_HOME="${NODE_HOME:-/root/.mirage/node}"
LOGS_DIR="${LOGS_DIR:-/root/.mirage/logs}"
BIN="${BIN:-/opt/mirage/blockchain/bin/miraged}"
MAX_RESTARTS_PER_HOUR="${MAX_RESTARTS_PER_HOUR:-12}"
RESTART_BACKOFF_SECONDS="${RESTART_BACKOFF_SECONDS:-5}"
# Pre-flight: how many blocks before an on-chain upgrade plan height we
# consider it "imminent" and refuse to start without a registered handler.
# 500 blocks ~= 7 minutes at this chain's typical block time, which is more
# than enough margin to swap a binary without halting consensus, but won't
# spam the operator about plans that are still days away.
UPGRADE_PREFLIGHT_SAFETY_BLOCKS="${UPGRADE_PREFLIGHT_SAFETY_BLOCKS:-500}"
UPGRADE_PREFLIGHT_PROBE_TIMEOUT="${UPGRADE_PREFLIGHT_PROBE_TIMEOUT:-5}"

[[ "$MAX_RESTARTS_PER_HOUR" =~ ^[1-9][0-9]*$ ]] || { echo "ERROR: MAX_RESTARTS_PER_HOUR must be a positive integer" >&2; exit 1; }
[[ "$RESTART_BACKOFF_SECONDS" =~ ^[1-9][0-9]*$ ]] || { echo "ERROR: RESTART_BACKOFF_SECONDS must be a positive integer" >&2; exit 1; }
[[ "$UPGRADE_PREFLIGHT_SAFETY_BLOCKS" =~ ^[1-9][0-9]*$ ]] || { echo "ERROR: UPGRADE_PREFLIGHT_SAFETY_BLOCKS must be a positive integer" >&2; exit 1; }
[ -x "$BIN" ] || { echo "ERROR: miraged binary not executable: $BIN" >&2; exit 1; }

mkdir -p "$LOGS_DIR/node"

STOP_REQUESTED=0

log_supervisor() {
  printf '[%s] [miraged-supervisor] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" \
    | tee -a "$LOGS_DIR/node/miraged-$(date -u +%Y-%m-%d).log"
}

stop_supervisor() {
  STOP_REQUESTED=1
  pkill -TERM -P $$ 2>/dev/null || true
}

trap stop_supervisor INT TERM

# upgrade_preflight: refuse to start miraged when an on-chain upgrade plan is
# imminent and this binary lacks a registered handler for it. This is the
# direct fix for the 2026-05-27 prod incident: a v1.26.0 plan reached height
# while every validator still ran a pre-v1.26.0 binary; each binary panicked
# with the cosmos-sdk upgrade-needed halt; the divergence watchdog mistook
# those halts for divergence and wiped 3 of 4 validators' chain DBs.
#
# Algorithm: probe persistent_peers for highest healthy peer, fetch its
# /cosmos/upgrade/v1beta1/current_plan, and if a plan is set within
# UPGRADE_PREFLIGHT_SAFETY_BLOCKS of the peer's tip, grep this binary for the
# "Starting upgrade to <plan.name>..." literal that every handler in
# blockchain/app/upgrades.go logs. Missing handler → exit 1 (supervisor stops).
#
# Escape hatch: UPGRADE_PREFLIGHT_SKIP=1 bypasses the check entirely. The
# operator must set it explicitly; we never default to skipping.
upgrade_preflight() {
  if [ "${UPGRADE_PREFLIGHT_SKIP:-}" = "1" ] || [ "${UPGRADE_PREFLIGHT_SKIP:-}" = "true" ]; then
    log_supervisor "upgrade-preflight: UPGRADE_PREFLIGHT_SKIP=1, bypassing"
    return 0
  fi
  local cfg="$NODE_HOME/config/config.toml"
  if [ ! -f "$cfg" ]; then
    log_supervisor "upgrade-preflight: $cfg missing; cannot probe peers — proceeding (fresh provisioning)"
    return 0
  fi
  local peers_line
  peers_line=$(grep -E '^persistent_peers' "$cfg" \
    | head -1 | sed -E 's/^persistent_peers *= *"([^"]*)".*/\1/' || true)
  if [ -z "$peers_line" ]; then
    log_supervisor "upgrade-preflight: persistent_peers empty in $cfg — proceeding (fresh provisioning)"
    return 0
  fi

  # Pick the highest-height healthy peer. We trust ANY peer's view of the
  # on-chain plan because the upgrade module's plan is consensus-replicated;
  # if one healthy peer thinks a plan is set, every honest peer agrees.
  local best_ip="" best_h=0 spec ip st h catch
  for spec in ${peers_line//,/ }; do
    [ -n "$spec" ] || continue
    [[ "$spec" == *"@"* ]] || continue
    ip="${spec#*@}"; ip="${ip%:*}"
    [ -n "$ip" ] || continue
    st=$(curl -fsS --max-time "$UPGRADE_PREFLIGHT_PROBE_TIMEOUT" "http://$ip:26657/status" 2>/dev/null || echo "")
    [ -n "$st" ] || continue
    h=$(printf '%s' "$st" | python3 -c 'import sys,json; print(json.load(sys.stdin)["result"]["sync_info"]["latest_block_height"])' 2>/dev/null || echo 0)
    catch=$(printf '%s' "$st" | python3 -c 'import sys,json; print(json.load(sys.stdin)["result"]["sync_info"]["catching_up"])' 2>/dev/null || echo true)
    [ "$catch" = "False" ] || continue
    [ "$h" -gt 0 ] || continue
    if [ "$h" -gt "$best_h" ]; then
      best_h="$h"; best_ip="$ip"
    fi
  done

  if [ -z "$best_ip" ]; then
    log_supervisor "upgrade-preflight: no healthy peers reachable — proceeding (cannot determine plan)"
    return 0
  fi
  log_supervisor "upgrade-preflight: canonical peer $best_ip @ height $best_h"

  local plan_json plan_name plan_h
  plan_json=$(curl -fsS --max-time "$UPGRADE_PREFLIGHT_PROBE_TIMEOUT" "http://$best_ip:1317/cosmos/upgrade/v1beta1/current_plan" 2>/dev/null || echo "")
  if [ -z "$plan_json" ]; then
    log_supervisor "upgrade-preflight: peer $best_ip:1317 unreachable — proceeding (cannot fetch plan)"
    return 0
  fi
  plan_name=$(printf '%s' "$plan_json" | python3 -c 'import sys,json; p=json.load(sys.stdin).get("plan") or {}; print(p.get("name") or "")' 2>/dev/null || echo "")
  plan_h=$(printf '%s' "$plan_json"   | python3 -c 'import sys,json; p=json.load(sys.stdin).get("plan") or {}; print(p.get("height") or 0)'   2>/dev/null || echo 0)
  if [ -z "$plan_name" ] || [ "$plan_h" -le 0 ]; then
    log_supervisor "upgrade-preflight: no on-chain upgrade plan set — safe to start"
    return 0
  fi
  local blocks_until=$((plan_h - best_h))
  log_supervisor "upgrade-preflight: on-chain plan name=${plan_name} height=${plan_h} (peer at ${best_h}, ${blocks_until} blocks away)"
  if [ "$blocks_until" -gt "$UPGRADE_PREFLIGHT_SAFETY_BLOCKS" ]; then
    log_supervisor "upgrade-preflight: plan is ${blocks_until} blocks out (> ${UPGRADE_PREFLIGHT_SAFETY_BLOCKS}); not yet imminent — proceeding"
    log_supervisor "upgrade-preflight: ACTION ITEM ensure this binary registers a handler for ${plan_name} before height ${plan_h}"
    return 0
  fi

  # Imminent. Every handler in blockchain/app/upgrades.go logs
  # "Starting upgrade to <name>..." (39 handlers as of v1.26.0); grep -F is
  # safe because plan.Name is a chain-supplied opaque string that we never
  # interpret as a regex.
  if grep -aFq "Starting upgrade to ${plan_name}..." "$BIN"; then
    log_supervisor "upgrade-preflight: binary registers handler for ${plan_name}; safe to cross upgrade height"
    return 0
  fi

  log_supervisor "============================================================"
  log_supervisor "FATAL: upgrade-preflight check FAILED"
  log_supervisor "  on-chain upgrade plan ${plan_name} activates at height ${plan_h}"
  log_supervisor "  canonical peer ${best_ip} is at height ${best_h} (${blocks_until} blocks away)"
  log_supervisor "  this binary (${BIN}) has NO registered handler for ${plan_name}"
  log_supervisor "  starting miraged would halt the chain at the upgrade height,"
  log_supervisor "  exactly the failure mode that destroyed 3 of 4 validators on 2026-05-27."
  log_supervisor "  REMEDIATION: pull a newer miraged image that includes the handler,"
  log_supervisor "               then restart the container."
  log_supervisor "  ESCAPE HATCH: set UPGRADE_PREFLIGHT_SKIP=1 in node.env to bypass."
  log_supervisor "============================================================"
  return 1
}

# Run the pre-flight once before entering the restart loop. We do NOT re-run
# it on every restart inside the loop because (a) once miraged is in steady
# state, the on-chain plan view is already consistent with this binary or
# isn't, and (b) repeatedly hammering peers from a crash-loop is rude.
if ! upgrade_preflight; then
  log_supervisor "supervisor exiting due to failed upgrade-preflight check"
  exit 1
fi

SKIP_ARGS=()
if [ -n "${SKIP_UPGRADES:-}" ]; then
  log_supervisor "SKIP_UPGRADES=${SKIP_UPGRADES}"
  for upgrade in $(echo "$SKIP_UPGRADES" | tr ',' ' '); do
    [ -n "$upgrade" ] || continue
    SKIP_ARGS+=(--unsafe-skip-upgrades "$upgrade")
  done
fi

upgrade_halt_detected() {
  local log="$LOGS_DIR/node/miraged-$(date -u +%Y-%m-%d).log"
  [ -f "$log" ] || return 1
  grep -aE 'UPGRADE ".+" NEEDED at height:' "$log" | tail -1
}

hold_for_governed_upgrade() {
  local line="$1"
  local halt_dir="/root/.mirage/upgrade"
  mkdir -p "$halt_dir"
  printf '%s\n' "$line" > "$halt_dir/halt-detected.txt"
  log_supervisor "governed upgrade halt detected: $line"
  if [ ! -f "$halt_dir/prepared.json" ]; then
    log_supervisor "no prepared.json staged; remaining halted so the old binary cannot cross the upgrade height"
  else
    log_supervisor "prepared upgrade is staged; remaining halted until the host activator recreates the container"
  fi
  while [ "$STOP_REQUESTED" -eq 0 ]; do
    sleep 5
  done
  exit 0
}

declare -a RESTART_TIMES=()

while true; do
  log_supervisor "starting miraged (restarts_last_hour=${#RESTART_TIMES[@]}/${MAX_RESTARTS_PER_HOUR})"

  "$BIN" start --home "$NODE_HOME" "${SKIP_ARGS[@]}" "$@" 2>&1 | tee >(cronolog "$LOGS_DIR/node/miraged-%Y-%m-%d.log")
  exit_code="${PIPESTATUS[0]}"
  now_epoch="$(date +%s)"

  log_supervisor "miraged exited code=${exit_code}"
  if [ "$STOP_REQUESTED" -eq 1 ]; then
    log_supervisor "stop requested; exiting"
    exit 0
  fi

  halt_line="$(upgrade_halt_detected || true)"
  if [ -n "$halt_line" ]; then
    hold_for_governed_upgrade "$halt_line"
  fi

  RESTART_TIMES+=("$now_epoch")
  hour_ago=$((now_epoch - 3600))
  kept=()
  for restart_time in "${RESTART_TIMES[@]}"; do
    if [ "$restart_time" -gt "$hour_ago" ]; then
      kept+=("$restart_time")
    fi
  done
  RESTART_TIMES=("${kept[@]}")

  if [ "${#RESTART_TIMES[@]}" -gt "$MAX_RESTARTS_PER_HOUR" ]; then
    log_supervisor "restart limit exceeded; exiting"
    # Exit 0 so Supervisor autorestart=unexpected does not relaunch this
    # wrapper with a fresh hourly budget.
    exit 0
  fi

  sleep "$RESTART_BACKOFF_SECONDS"
done
