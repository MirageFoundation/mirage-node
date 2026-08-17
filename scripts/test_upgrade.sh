#!/usr/bin/env bash
# Local release rehearsal: reset from the latest mirage.vote backup, deploy the
# current tree, raise the PoW limit, then launch test_blockchain / test_backend
# / verify_upgrade in the container tmux session. When the release registers a
# chain upgrade handler it also passes the software-upgrade proposal and waits
# for the halt and the plan to apply.
#
# CHAIN-UPGRADE MODE IS DETECTED, NOT DECLARED. The script reads the plan name
# out of proposal_upgrade.json and looks for a matching SetUpgradeHandler in
# blockchain/app/upgrades.go, then requires --no-chain-upgrade to agree with
# what it found. Both ways of getting it wrong are things this script exists to
# catch, and both are silent:
#
#   * Skipping the proposal for a release that DOES change chain code leaves the
#     upgrade path completely unrehearsed while every pane still reports passed.
#   * Passing the proposal for a release that registers NO handler halts the
#     chain at the plan height with nothing able to resume it, which looks like
#     a hung node rather than an operator error.
#
# Status files (host path, volume-mounted) so an LLM can poll without attaching:
#   ~/.mirage/upgrade_tests/pipeline.stage                         current pipeline step
#   ~/.mirage/upgrade_tests/{blockchain,backend,verify}.state      running|passed|failed
#   ~/.mirage/upgrade_tests/{blockchain,backend,verify}.exit       set when done
#   ~/.mirage/upgrade_tests/{blockchain,backend,verify}.out        full captured output
#   ~/.mirage/upgrade_tests/all.json                               written when all three finish
#
# Usage:
#   scripts/test_upgrade.sh                     # run the pipeline and launch the panes
#   scripts/test_upgrade.sh --no-chain-upgrade  # same, for a release with no handler
#   scripts/test_upgrade.sh --wait              # block until the panes finish, exit 0 iff all passed
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CONTAINER="${CONTAINER:-mirage}"
SESSION="${SESSION:-mirage}"
STATUS_HOST="${HOME}/.mirage/upgrade_tests"
STATUS_CTN="/root/.mirage/upgrade_tests"
PROPOSAL_UPGRADE="${ROOT}/scripts/proposals/proposal_upgrade.json"
PROPOSAL_POW="${ROOT}/scripts/proposals/proposal_set_pow_message_limit_9999999.json"
UPGRADES_GO="${ROOT}/blockchain/app/upgrades.go"
JOBS=(blockchain backend verify)

# Set from --no-chain-upgrade; cross-checked against upgrades.go before use.
NO_CHAIN_UPGRADE=0

# Time budgets. Loops must terminate; these are the ceilings, not the expected wait.
HALT_BUDGET_SEC="${HALT_BUDGET_SEC:-600}"
RPC_BUDGET_SEC="${RPC_BUDGET_SEC:-240}"
APPLIED_BUDGET_SEC="${APPLIED_BUDGET_SEC:-180}"
POW_BUDGET_SEC="${POW_BUDGET_SEC:-90}"
WAIT_BUDGET_SEC="${WAIT_BUDGET_SEC:-14400}"

log() { printf '[%s] %s\n' "$(date -u +%H:%M:%S)" "$*"; }
die() { printf '[%s] ERROR: %s\n' "$(date -u +%H:%M:%S)" "$*" >&2; exit 1; }

usage() {
  cat <<'EOF'
Local release rehearsal: reset from the latest mirage.vote backup, deploy the
current tree, raise the PoW limit, then launch test_blockchain / test_backend /
verify_upgrade in the container tmux session. A release that registers a chain
upgrade handler additionally passes the software-upgrade proposal and waits for
the halt and the plan to apply.

  scripts/test_upgrade.sh                     run the pipeline and launch the panes
  scripts/test_upgrade.sh --no-chain-upgrade  same, for a release that ships no handler
  scripts/test_upgrade.sh --wait              block until the panes finish; exit 0 iff all passed

--no-chain-upgrade is cross-checked against blockchain/app/upgrades.go. The run
aborts if the flag and the source disagree in either direction, because both
mistakes are silent: skipping the proposal leaves a real upgrade unrehearsed,
and passing it without a handler halts the local chain permanently.

Poll:
  cat ~/.mirage/upgrade_tests/pipeline.stage
  cat ~/.mirage/upgrade_tests/{blockchain,backend,verify}.state
  cat ~/.mirage/upgrade_tests/all.json
  cat ~/.mirage/upgrade_tests/verify.out
EOF
}

atomic_write() {
  local path="$1" body="$2"
  printf '%s\n' "$body" > "${path}.tmp"
  mv "${path}.tmp" "$path"
}

set_stage() {
  mkdir -p "$STATUS_HOST"
  atomic_write "${STATUS_HOST}/pipeline.stage" "$1"
  log "pipeline stage: $1"
}

# Records that the pipeline died before it could launch the panes. Without this
# the only evidence was a pipeline.stage frozen at whatever step failed, which
# --wait cannot distinguish from a step still in progress.
#
# On EXIT rather than ERR: most steps fail through die, which is an explicit
# exit and never fires an ERR trap, and an ERR trap would not fire inside the
# wait_* functions at all without errtrace. EXIT catches every path.
record_pipeline_failure() {
  local rc=$?
  local stage
  (( rc == 0 )) && return 0
  stage="$(cat "${STATUS_HOST}/pipeline.stage" 2>/dev/null || echo unknown)"
  [[ "$stage" == "launched" ]] && return 0
  mkdir -p "$STATUS_HOST"
  atomic_write "${STATUS_HOST}/pipeline.failed" \
    "stage=${stage} exit=${rc} utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf '[%s] ERROR: pipeline failed at stage %s (exit %d); panes were never launched\n' \
    "$(date -u +%H:%M:%S)" "$stage" "$rc" >&2
}

# deploy.sh --local --update refuses to deploy a dirty tree, and the pipeline
# calls it four minutes in — after resetting the testnet, passing the upgrade
# proposal and halting the chain at the upgrade height. So a condition knowable
# in the first second instead left the local chain halted on the old binary with
# nothing to deploy, and --wait then sat for its full budget waiting for jobs
# that could never launch. Check it before touching anything.
#
# This mirrors deploy.sh's check exactly — tracked modifications, staged or not.
# Do not extend it to untracked files: deploy.sh deploys with those present, and
# a stricter gate here would block runs that would have worked.
preflight_clean_tree() {
  local dirty
  dirty="$( { git -C "$ROOT" diff --name-only; git -C "$ROOT" diff --cached --name-only; } 2>/dev/null | sort -u)"
  [[ -z "$dirty" ]] && return 0
  printf '[%s] ERROR: uncommitted changes; deploy.sh would refuse this tree.\n' "$(date -u +%H:%M:%S)" >&2
  printf '%s\n' "$dirty" | sed 's/^/  /' >&2
  die "commit or stash the above, then re-run. Nothing was changed; the local chain is untouched."
}

activate_conda() {
  if [[ "${CONDA_DEFAULT_ENV:-}" == "mirage-node" ]]; then
    return 0
  fi
  if ! command -v conda >/dev/null; then
    die "conda not found; run: conda activate mirage-node"
  fi
  eval "$(conda shell.bash hook)"
  conda activate mirage-node
}

rpc_height() {
  python3 - <<'PY'
import json, urllib.request, sys
try:
    with urllib.request.urlopen("http://127.0.0.1:26657/status", timeout=5) as resp:
        data = json.load(resp)
    print(int(data["result"]["sync_info"]["latest_block_height"]))
except Exception as e:
    print(f"rpc_height failed: {e}", file=sys.stderr)
    sys.exit(1)
PY
}

ctn_python() {
  docker exec "$CONTAINER" python3 -c "$1"
}

upgrade_name() {
  python3 - <<PY
import json
from pathlib import Path
data = json.loads(Path("${PROPOSAL_UPGRADE}").read_text())
print(data["messages"][0]["plan"]["name"])
PY
}

# True when upgrades.go registers a SetUpgradeHandler for the plan name. Matched
# on the quoted name so a mention in a comment cannot satisfy it.
handler_is_registered() {
  local name="$1"
  [[ -f "$UPGRADES_GO" ]] || die "missing ${UPGRADES_GO}"
  # The name must be the first argument on the line following the call, so a
  # version string mentioned in a comment or a log message cannot satisfy this.
  grep -A1 -E '^[[:space:]]*app\.UpgradeKeeper\.SetUpgradeHandler\($' "$UPGRADES_GO" \
    | grep -qE "^[[:space:]]*\"${name}\",[[:space:]]*$"
}

# Refuse to run when the flag and the source disagree. Fail-closed both ways.
resolve_upgrade_mode() {
  local name="$1"
  if handler_is_registered "$name"; then
    if (( NO_CHAIN_UPGRADE )); then
      die "--no-chain-upgrade was passed, but ${UPGRADES_GO} registers a handler for \"${name}\".
  Skipping the proposal would leave this release's upgrade path completely unrehearsed
  while all three panes still reported passed. Drop the flag, or remove the handler."
    fi
    log "chain upgrade mode: handler \"${name}\" is registered"
    return 0
  fi
  if (( ! NO_CHAIN_UPGRADE )); then
    die "no SetUpgradeHandler for \"${name}\" in ${UPGRADES_GO}.
  Submitting the proposal would halt the local chain at the plan height with nothing
  able to resume it. Either register the handler, or re-run with --no-chain-upgrade
  if this release genuinely ships no chain change."
  fi
  log "no-chain-upgrade mode: no handler for \"${name}\", and none expected"
}

# A plan inherited from the restored backup halts the chain mid-run. In upgrade
# mode our own proposal supplies the plan, so this only guards the other path.
#
# "no plan" and "could not ask" must not collapse into the same answer. Treating
# an unreachable API as an all-clear would disarm the one check standing between
# an inherited plan and a chain that halts mid-suite, so an indeterminate result
# is fatal here rather than reassuring.
assert_no_pending_plan() {
  local plan_line rc=0
  plan_line="$(current_plan_height)" || rc=$?
  case "$rc" in
    0)
      die "the restored backup carries a pending upgrade plan (${plan_line}), and this release
  registers no handler for it. The chain would halt at that height mid-test. Restore a
  backup taken after that upgrade applied, or register the handler."
      ;;
    "$PLAN_EMPTY_RC")
      log "no pending upgrade plan on the restored chain"
      ;;
    *)
      die "could not determine whether the restored chain has a pending upgrade plan (rc=${rc}).
  See the current_plan error above. Refusing to continue: if a plan is pending, the chain
  halts mid-suite and every pane fails for a reason that has nothing to do with the release."
      ;;
  esac
}

# Exit 0 with "<height> <name>" when a plan is pending, PLAN_EMPTY_RC when the
# chain answered and has none, 1 when the query itself failed. Callers must be
# able to tell the last two apart.
PLAN_EMPTY_RC=3

current_plan_height() {
  ctn_python '
import json, urllib.request, sys
url = "http://127.0.0.1:1317/cosmos/upgrade/v1beta1/current_plan"
req = urllib.request.Request(url, headers={"Accept": "application/json"})
try:
    with urllib.request.urlopen(req, timeout=5) as resp:
        data = json.load(resp)
except Exception as e:
    print(f"current_plan failed: {e}", file=sys.stderr)
    sys.exit(1)
plan = data.get("plan") or {}
height = int(plan.get("height") or 0)
name = plan.get("name") or ""
if height <= 0:
    print("current_plan is empty", file=sys.stderr)
    sys.exit('"$PLAN_EMPTY_RC"')
print(f"{height} {name}")
'
}

applied_height() {
  local name="$1"
  ctn_python "
import json, urllib.request, sys
url = 'http://127.0.0.1:1317/cosmos/upgrade/v1beta1/applied_plan/${name}'
req = urllib.request.Request(url, headers={'Accept': 'application/json'})
try:
    with urllib.request.urlopen(req, timeout=5) as resp:
        data = json.load(resp)
except Exception as e:
    print(f'applied_plan failed: {e}', file=sys.stderr)
    sys.exit(1)
print(int(data.get('height') or data.get('Height') or 0))
"
}

pow_message_limit() {
  ctn_python '
import json, urllib.request, sys
url = "http://127.0.0.1:1317/mirage/core/v1/params"
req = urllib.request.Request(url, headers={"Accept": "application/json"})
try:
    with urllib.request.urlopen(req, timeout=5) as resp:
        data = json.load(resp)
except Exception as e:
    print(f"params query failed: {e}", file=sys.stderr)
    sys.exit(1)
print(int(data["params"]["pow_message_limit"]))
'
}

wait_until() {
  local budget="$1" desc="$2"
  shift 2
  local start=$SECONDS
  while (( SECONDS - start < budget )); do
    if "$@"; then
      return 0
    fi
    sleep 3
  done
  die "timed out after ${budget}s waiting for ${desc}"
}

rpc_is_up() {
  local h
  if h=$(rpc_height); then
    log "rpc height=${h}"
    [[ "$h" -gt 0 ]]
  else
    return 1
  fi
}

backend_is_up() {
  python3 - <<'PY'
import json, urllib.request, sys
try:
    with urllib.request.urlopen("http://127.0.0.1/api/get_parameters", timeout=5) as resp:
        json.load(resp)
except Exception as e:
    print(f"backend not ready: {e}", file=sys.stderr)
    sys.exit(1)
PY
}

tmux_has_session() {
  docker exec "$CONTAINER" tmux has-session -t "$SESSION"
}

kill_window_if_present() {
  local name="$1"
  local windows
  windows="$(docker exec "$CONTAINER" tmux list-windows -t "$SESSION" -F '#W')"
  if grep -qx "$name" <<<"$windows"; then
    log "killing existing tmux window ${SESSION}:${name}"
    docker exec "$CONTAINER" tmux kill-window -t "${SESSION}:${name}"
  fi
}

write_run_job() {
  mkdir -p "$STATUS_HOST"
  cat > "${STATUS_HOST}/run_job.sh" <<'EOF'
#!/usr/bin/env bash
# Runs one named job, tees output, writes atomic status files an LLM can poll.
set -uo pipefail
NAME="$1"
shift
DIR="/root/.mirage/upgrade_tests"

atomic_write() {
  local path="$1" body="$2"
  printf '%s\n' "$body" > "${path}.tmp"
  mv "${path}.tmp" "$path"
}

mkdir -p "$DIR"
atomic_write "${DIR}/${NAME}.state" "running"
date -u +%Y-%m-%dT%H:%M:%SZ > "${DIR}/${NAME}.started.tmp"
mv "${DIR}/${NAME}.started.tmp" "${DIR}/${NAME}.started"
rm -f "${DIR}/${NAME}.exit" "${DIR}/${NAME}.finished" "${DIR}/${NAME}.out"

cd /opt/mirage
set -a
for f in /root/.mirage/env/*.env; do
  # shellcheck disable=SC1090
  . "$f"
done
set +a
export PYTHONPATH=/opt/mirage

set +e
"$@" 2>&1 | tee "${DIR}/${NAME}.out"
rc=${PIPESTATUS[0]}
set -e

atomic_write "${DIR}/${NAME}.exit" "$rc"
date -u +%Y-%m-%dT%H:%M:%SZ > "${DIR}/${NAME}.finished.tmp"
mv "${DIR}/${NAME}.finished.tmp" "${DIR}/${NAME}.finished"
if [[ "$rc" -eq 0 ]]; then
  atomic_write "${DIR}/${NAME}.state" "passed"
else
  atomic_write "${DIR}/${NAME}.state" "failed"
fi

python3 - "$DIR" <<'PY'
import json, pathlib, sys
status_dir = pathlib.Path(sys.argv[1])
jobs = ("blockchain", "backend", "verify")
summary = {}
for job in jobs:
    state_path = status_dir / f"{job}.state"
    item = {"state": state_path.read_text().strip() if state_path.exists() else "missing"}
    for key in ("exit", "started", "finished"):
        path = status_dir / f"{job}.{key}"
        if not path.exists():
            continue
        text = path.read_text().strip()
        item[key] = int(text) if key == "exit" else text
    summary[job] = item
if all("exit" in summary[job] for job in jobs):
    tmp = status_dir / "all.json.tmp"
    tmp.write_text(json.dumps(summary, indent=2) + "\n")
    tmp.replace(status_dir / "all.json")
    lines = [f"{job}={summary[job]['state']} exit={summary[job]['exit']}" for job in jobs]
    all_tmp = status_dir / "all.state.tmp"
    all_tmp.write_text("\n".join(lines) + "\n")
    all_tmp.replace(status_dir / "all.state")
PY

exit "$rc"
EOF
  chmod +x "${STATUS_HOST}/run_job.sh"
}

clear_status() {
  log "clearing ${STATUS_HOST}"
  rm -rf "$STATUS_HOST"
  mkdir -p "$STATUS_HOST"
  write_run_job
}

job_state() {
  local name="$1"
  local path="${STATUS_HOST}/${name}.state"
  if [[ -f "$path" ]]; then
    cat "$path"
  else
    printf 'missing'
  fi
}

print_job_states() {
  local name state
  for name in "${JOBS[@]}"; do
    state="$(job_state "$name")"
    printf '  %-12s %s\n' "$name" "$state"
  done
}

wait_for_jobs() {
  [[ -d "$STATUS_HOST" ]] || die "no status dir at ${STATUS_HOST}; run scripts/test_upgrade.sh first"
  [[ -f "${STATUS_HOST}/pipeline.stage" ]] || die "no pipeline.stage at ${STATUS_HOST}; run scripts/test_upgrade.sh first"
  local start=$SECONDS stage
  log "waiting up to ${WAIT_BUDGET_SEC}s for blockchain + backend + verify"
  while (( SECONDS - start < WAIT_BUDGET_SEC )); do
    stage="$(cat "${STATUS_HOST}/pipeline.stage")"
    # A dead pipeline never launches panes, so waiting the remaining budget for
    # its results is waiting for something that cannot happen. The budget alone
    # is not enough here: at four hours it is an indefinite wait in practice,
    # which is how a dirty tree turned into a silent stall.
    if [[ -f "${STATUS_HOST}/pipeline.failed" ]]; then
      echo
      log "pipeline.failed: $(cat "${STATUS_HOST}/pipeline.failed")"
      print_job_states
      die "the pipeline died at stage '${stage}' before launching the panes; fix the cause and re-run scripts/test_upgrade.sh"
    fi
    log "pipeline.stage=${stage}"
    print_job_states
    if [[ -f "${STATUS_HOST}/all.json" ]]; then
      echo
      log "all jobs finished"
      cat "${STATUS_HOST}/all.json"
      echo
      log "verify_upgrade output: ${STATUS_HOST}/verify.out"
      local name rc=0
      for name in "${JOBS[@]}"; do
        if [[ "$(job_state "$name")" != "passed" ]]; then
          rc=1
        fi
      done
      exit "$rc"
    fi
    sleep 5
  done
  echo
  print_job_states
  die "timed out after ${WAIT_BUDGET_SEC}s waiting for jobs (see ${STATUS_HOST})"
}

wait_for_halt() {
  local plan_line plan_h plan_n head rc=0
  log "waiting for upgrade halt (budget ${HALT_BUDGET_SEC}s)"
  plan_line="$(current_plan_height)" || rc=$?
  if (( rc != 0 )); then
    die "no upgrade plan on chain after submitting the proposal (rc=${rc}).
  The proposal did not pass, or it passed with a height already behind the head."
  fi
  plan_h="${plan_line%% *}"
  plan_n="${plan_line#* }"
  log "on-chain plan name=${plan_n} height=${plan_h}"
  local start=$SECONDS
  while (( SECONDS - start < HALT_BUDGET_SEC )); do
    if head=$(rpc_height); then
      log "height=${head} plan=${plan_h} remaining=$((plan_h - head))"
      if (( head >= plan_h - 1 )); then
        log "at upgrade boundary; giving the node a few seconds to halt"
        sleep 5
        return 0
      fi
    else
      log "RPC unreachable — treating as upgrade halt"
      return 0
    fi
    sleep 3
  done
  die "timed out waiting for upgrade height ${plan_h}"
}

wait_applied_and_live() {
  local name="$1"
  local start=$SECONDS applied head
  log "waiting for ${name} to apply and produce 5 blocks (budget ${APPLIED_BUDGET_SEC}s)"
  while (( SECONDS - start < APPLIED_BUDGET_SEC )); do
    if applied=$(applied_height "$name") && [[ "$applied" -gt 0 ]]; then
      if head=$(rpc_height); then
        log "applied_plan height=${applied} head=${head}"
        if (( head - applied >= 5 )); then
          return 0
        fi
      else
        log "upgrade applied but RPC not up yet"
      fi
    else
      log "upgrade ${name} not applied yet"
    fi
    sleep 3
  done
  die "timed out waiting for ${name} to apply and produce blocks"
}

wait_pow_limit() {
  local start=$SECONDS limit
  log "waiting for pow_message_limit=9999999 (budget ${POW_BUDGET_SEC}s)"
  while (( SECONDS - start < POW_BUDGET_SEC )); do
    if limit=$(pow_message_limit); then
      log "pow_message_limit=${limit}"
      if [[ "$limit" -eq 9999999 ]]; then
        return 0
      fi
    else
      log "params query not ready"
    fi
    sleep 3
  done
  die "timed out waiting for pow_message_limit=9999999"
}

# Raise the limit only when it is not already raised. MsgUpdateParams rejects an
# update whose mask selects a field it would not change ("update_mask does not
# change any selected field"), so re-proposing against an already-raised chain
# fails the proposal and, under set -e, would kill the pipeline for no reason.
ensure_pow_limit() {
  local limit
  if limit=$(pow_message_limit) && [[ "$limit" -eq 9999999 ]]; then
    log "pow_message_limit already 9999999; skipping the proposal"
    return 0
  fi
  log "raise PoW message limit for the test suites (currently ${limit:-unknown})"
  python3 "${ROOT}/scripts/submit_proposal.py" local "$PROPOSAL_POW" --no-confirm
  wait_pow_limit
}

# Liveness for a release with no plan to apply: the chain must gain height on
# the binary that was just deployed.
wait_chain_advancing() {
  local first second
  first=$(rpc_height) || die "RPC unreachable after deploy"
  log "chain at height ${first}; confirming it advances"
  local start=$SECONDS
  while (( SECONDS - start < APPLIED_BUDGET_SEC )); do
    sleep 3
    if second=$(rpc_height) && (( second > first + 2 )); then
      log "chain advancing: ${first} -> ${second}"
      return 0
    fi
  done
  die "chain did not advance past ${first} within ${APPLIED_BUDGET_SEC}s after deploy"
}

launch_panes() {
  write_run_job
  wait_until 60 "tmux session ${SESSION}" tmux_has_session
  kill_window_if_present tests
  kill_window_if_present verify

  log "creating tmux window tests (upper=blockchain, lower=backend)"
  docker exec "$CONTAINER" tmux new-window -t "$SESSION" -n tests -c /opt/mirage
  docker exec "$CONTAINER" tmux split-window -t "${SESSION}:tests" -v -c /opt/mirage
  docker exec "$CONTAINER" tmux select-layout -t "${SESSION}:tests" even-vertical
  docker exec "$CONTAINER" tmux send-keys -t "${SESSION}:tests.0" \
    "bash ${STATUS_CTN}/run_job.sh blockchain python3 tests/test_blockchain.py" C-m
  docker exec "$CONTAINER" tmux send-keys -t "${SESSION}:tests.1" \
    "bash ${STATUS_CTN}/run_job.sh backend python3 tests/test_backend.py" C-m

  log "creating tmux window verify"
  docker exec "$CONTAINER" tmux new-window -t "$SESSION" -n verify -c /opt/mirage
  docker exec "$CONTAINER" tmux send-keys -t "${SESSION}:verify" \
    "bash ${STATUS_CTN}/run_job.sh verify python3 /opt/mirage/scripts/verify_upgrade.py" C-m

  docker exec "$CONTAINER" tmux select-window -t "${SESSION}:tests"
}

print_monitor() {
  cat <<EOF

Jobs launched in tmux session '${SESSION}' (windows: tests, verify).
Attach:  docker exec -it ${CONTAINER} tmux attach -t ${SESSION}

Poll (host, volume-mounted):
  cat ${STATUS_HOST}/pipeline.stage
  cat ${STATUS_HOST}/blockchain.state ${STATUS_HOST}/backend.state ${STATUS_HOST}/verify.state
  cat ${STATUS_HOST}/all.json
  cat ${STATUS_HOST}/verify.out

Block until done:
  scripts/test_upgrade.sh --wait
EOF
}

run_pipeline() {
  [[ -f "$PROPOSAL_UPGRADE" ]] || die "missing ${PROPOSAL_UPGRADE}"
  [[ -f "$PROPOSAL_POW" ]] || die "missing ${PROPOSAL_POW}"
  preflight_clean_tree
  activate_conda

  # Any death after this point leaves a marker, so --wait fails immediately
  # instead of polling for an all.json that is never coming.
  trap record_pipeline_failure EXIT

  local name
  name="$(upgrade_name)"
  log "upgrade name from proposal: ${name}"
  resolve_upgrade_mode "$name"

  clear_status
  set_stage reset

  log "reset local testnet from latest mirage.vote backup"
  python3 "${ROOT}/scripts/reset_local_testnet.py" --latest
  wait_until "$RPC_BUDGET_SEC" "RPC after reset" rpc_is_up

  if (( NO_CHAIN_UPGRADE )); then
    assert_no_pending_plan
  else
    set_stage upgrade_proposal
    log "submit software-upgrade proposal"
    python3 "${ROOT}/scripts/submit_proposal.py" local "$PROPOSAL_UPGRADE" --no-confirm
    set_stage halt
    wait_for_halt
  fi

  set_stage deploy
  log "deploy current tree into local container"
  "${ROOT}/deploy/deploy.sh" --local --update
  wait_until "$RPC_BUDGET_SEC" "RPC after deploy" rpc_is_up
  wait_until 120 "backend after deploy" backend_is_up
  if (( NO_CHAIN_UPGRADE )); then
    # No plan to apply, so liveness is measured directly: the chain must still
    # be producing blocks on the newly deployed binary.
    wait_chain_advancing
  else
    wait_applied_and_live "$name"
  fi

  set_stage pow
  ensure_pow_limit

  launch_panes
  set_stage launched
  print_monitor
}

case "${1:-}" in
  -h|--help) usage; exit 0 ;;
  --wait) wait_for_jobs ;;
  --no-chain-upgrade) NO_CHAIN_UPGRADE=1; run_pipeline ;;
  "") run_pipeline ;;
  *) die "unknown argument: $1 (try --help)" ;;
esac
