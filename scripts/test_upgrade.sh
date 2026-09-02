#!/usr/bin/env bash
# Local release rehearsal: reset from the latest mirage.vote backup, deploy the
# current tree, confirm the suite PoW/relay limits, then launch test_blockchain,
# test_backend, and verify/postflight as detached docker exec jobs. Postflight
# waits for both suites, then runs extended coverage and the creator payout probe.
# When the release registers a
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
#     upgrade path completely unrehearsed while every job still reports passed.
#   * Passing the proposal for a release that registers NO handler halts the
#     chain at the plan height with nothing able to resume it, which looks like
#     a hung node rather than an operator error.
#
# Status files (host path, volume-mounted) so an LLM can poll without attaching
# while the jobs are running. --wait deletes the directory only after all jobs
# pass; failures and timeouts preserve every captured log for diagnosis.
#   ~/.mirage/upgrade_tests/pipeline.stage                         current pipeline step
#   ~/.mirage/upgrade_tests/{blockchain,backend,verify}.state      running|passed|failed
#   ~/.mirage/upgrade_tests/{blockchain,backend,verify}.exit       set when done
#   ~/.mirage/upgrade_tests/{blockchain,backend,verify}.out        full captured output
#   ~/.mirage/upgrade_tests/postflight.*.state                     postflight phase results
#   ~/.mirage/upgrade_tests/all.json                               written when all three finish
#
# Usage:
#   scripts/test_upgrade.sh                     # run the pipeline and launch the jobs
#   scripts/test_upgrade.sh --no-chain-upgrade  # same, for a release with no handler
#   scripts/test_upgrade.sh --wait              # block until the jobs finish, exit 0 iff all passed
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CONTAINER="${CONTAINER:-mirage}"
STATUS_HOST="${HOME}/.mirage/upgrade_tests"
STATUS_CTN="/root/.mirage/upgrade_tests"
PROPOSAL_UPGRADE="${ROOT}/scripts/proposals/proposal_upgrade.json"
PROPOSAL_POW="${ROOT}/scripts/proposals/proposal_set_pow_message_limit_9999999.json"
PROPOSAL_RELAY_LIMIT="${ROOT}/scripts/proposals/proposal_set_subscriber_daily_relay_limit_10000.json"
PROPOSAL_CREATOR_TEST="${ROOT}/scripts/proposals/proposal_test_creator_rewards.json"
UPGRADES_GO="${ROOT}/blockchain/app/upgrades.go"
JOBS=(blockchain backend verify)
BACKUP_TARBALL=""

# Set from --no-chain-upgrade; cross-checked against upgrades.go before use.
NO_CHAIN_UPGRADE=0

# Time budgets. Loops must terminate; these are the ceilings, not the expected wait.
HALT_BUDGET_SEC="${HALT_BUDGET_SEC:-600}"
RPC_BUDGET_SEC="${RPC_BUDGET_SEC:-240}"
APPLIED_BUDGET_SEC="${APPLIED_BUDGET_SEC:-180}"
POW_BUDGET_SEC="${POW_BUDGET_SEC:-90}"
WAIT_BUDGET_SEC="${WAIT_BUDGET_SEC:-14400}"
CORE_JOBS_BUDGET_SEC="${CORE_JOBS_BUDGET_SEC:-14400}"
CREATOR_PARAM_BUDGET_SEC="${CREATOR_PARAM_BUDGET_SEC:-180}"

log() { printf '[%s] %s\n' "$(date -u +%H:%M:%S)" "$*"; }
die() { printf '[%s] ERROR: %s\n' "$(date -u +%H:%M:%S)" "$*" >&2; exit 1; }

usage() {
  cat <<'EOF'
Local release rehearsal: reset from the latest mirage.vote backup, deploy the
current tree, confirm the suite PoW/relay limits, then launch test_blockchain,
test_backend, and verify/postflight as detached docker exec jobs. Postflight
runs extended coverage and the creator payout probe only after both suites pass.
A release that registers a chain
upgrade handler additionally passes the software-upgrade proposal and waits for
the halt and the plan to apply.

  scripts/test_upgrade.sh                     run the pipeline and launch the jobs
  scripts/test_upgrade.sh --no-chain-upgrade  same, for a release that ships no handler
  scripts/test_upgrade.sh --wait              block until the jobs finish; exit 0 iff all passed

--no-chain-upgrade is cross-checked against blockchain/app/upgrades.go. The run
aborts if the flag and the source disagree in either direction, because both
mistakes are silent: skipping the proposal leaves a real upgrade unrehearsed,
and passing it without a handler halts the local chain permanently.

Poll while jobs are running (the directory is removed when --wait finishes):
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

assert_backup_image_version() {
  local metadata="${STATUS_HOST}/backup-image.json"
  local version_out="${STATUS_HOST}/backup-image-version.out"
  local version_err="${STATUS_HOST}/backup-image-version.err"
  python3 - "$ROOT" "$metadata" <<'PY'
import json
import subprocess
import sys
import tarfile
from pathlib import Path, PurePosixPath

root = Path(sys.argv[1])
sys.path.insert(0, str(root / "scripts"))
import backup_restore

tarball = backup_restore.find_latest_backup("mirage.vote").resolve()
with tarfile.open(tarball, "r:gz") as archive:
    members = [
        member
        for member in archive.getmembers()
        if member.isfile() and PurePosixPath(member.name).parts[-2:] == (".mirage", "docker_image")
    ]
    if len(members) != 1:
        raise SystemExit(f"{tarball}: expected exactly one .mirage/docker_image, found {len(members)}")
    stream = archive.extractfile(members[0])
    if stream is None:
        raise SystemExit(f"{tarball}: cannot read {members[0].name}")
    image = stream.read().decode("utf-8").strip()
if not image:
    raise SystemExit(f"{tarball}: docker_image metadata is empty")
manifest = json.loads(
    subprocess.check_output(
        ["git", "-C", str(root), "show", "v1.38.11:release/manifest.json"],
        text=True,
    )
)
expected_image = manifest.get("image")
if not expected_image:
    raise SystemExit("v1.38.11:release/manifest.json is missing image")
if image != expected_image:
    raise SystemExit(
        f"{tarball}: docker_image is {image}; signed v1.38.11 image is {expected_image}"
    )
Path(sys.argv[2]).write_text(
    json.dumps(
        {
            "tarball": str(tarball),
            "image": image,
            "expected_image": expected_image,
        },
        indent=2,
    )
    + "\n",
    encoding="utf-8",
)
print(f"backup={tarball}")
print(f"image={image}")
PY
  BACKUP_TARBALL="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["tarball"])' "$metadata")"
  local image
  image="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["image"])' "$metadata")"
  log "backup image digest matches signed v1.38.11 manifest"
  set +e
  docker run --rm --network none --entrypoint /bin/bash "$image" -lc '
set -euo pipefail
if [[ -x /opt/mirage/blockchain/miraged ]]; then
  binary=/opt/mirage/blockchain/miraged
elif [[ -x /opt/mirage/blockchain/bin/miraged ]]; then
  binary=/opt/mirage/blockchain/bin/miraged
else
  echo "ERROR: miraged binary not found in backup image" >&2
  exit 1
fi
exec "$binary" version
' >"$version_out" 2>"$version_err"
  local docker_rc=$?
  set -e
  (( docker_rc == 0 )) || die "could not run the miraged binary from backup image ${image}"
  local reported
  reported="$(grep -E '^v[0-9]+\.[0-9]+\.[0-9]+$' "$version_out" | sed -n '$p')"
  [[ -n "$reported" ]] || die "backup image ${image} printed no vX.Y.Z version line"
  log "backup binary version string=${reported} (signed v1.38.11 image may be mislabeled)"
}

verify_proto_generation_parity() {
  local before after
  before="$(git -C "$ROOT" status --porcelain=v1 --untracked-files=all)"
  log "regenerating protobuf output and checking committed parity"
  make -C "${ROOT}/blockchain" proto-gen
  after="$(git -C "$ROOT" status --porcelain=v1 --untracked-files=all)"
  if [[ "$after" != "$before" ]]; then
    git -C "$ROOT" status --short
    die "protobuf generation changed the working tree; commit regenerated output before rehearsal"
  fi
  log "protobuf generation matches committed output"
}

capture_pre_upgrade_params() {
  python3 - "${STATUS_HOST}/pre_upgrade_params.json" <<'PY'
import json
import sys
import urllib.request
from pathlib import Path

url = "http://127.0.0.1:1317/mirage/core/v1/params"
with urllib.request.urlopen(url, timeout=10) as response:
    payload = json.load(response)
params = payload.get("params")
if not isinstance(params, dict):
    raise SystemExit(f"pre-upgrade params response is invalid: {payload!r}")
path = Path(sys.argv[1])
tmp = path.with_suffix(path.suffix + ".tmp")
tmp.write_text(json.dumps(params, indent=2, sort_keys=True) + "\n", encoding="utf-8")
tmp.replace(path)
print(f"captured {len(params)} pre-upgrade params in {path}")
PY
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

chain_param() {
  ctn_python "
import json, urllib.request, sys
url = 'http://127.0.0.1:1317/mirage/core/v1/params'
req = urllib.request.Request(url, headers={'Accept': 'application/json'})
try:
    with urllib.request.urlopen(req, timeout=5) as resp:
        data = json.load(resp)
except Exception as e:
    print(f'params query failed: {e}', file=sys.stderr)
    sys.exit(1)
print(int(data['params']['$1']))
"
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

supervisor_ready() {
  docker exec "$CONTAINER" test -S /var/run/supervisor.sock
}

backend_ready() {
  docker exec "$CONTAINER" python3 -c '
import urllib.request, sys
try:
    with urllib.request.urlopen("http://127.0.0.1:80/api/get_parameters", timeout=5) as resp:
        sys.exit(0 if resp.status == 200 else 1)
except Exception:
    sys.exit(1)
'
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
    phase_prefix = "postflight."
    summary["postflight"] = {
        path.name[len(phase_prefix) : -len(".state")]: path.read_text().strip()
        for path in sorted(status_dir.glob(f"{phase_prefix}*.state"))
    }
    stage_path = status_dir / "pipeline.stage"
    summary["pipeline_stage"] = stage_path.read_text().strip() if stage_path.exists() else "missing"
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

write_postflight() {
  cat > "${STATUS_HOST}/postflight.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
DIR="/root/.mirage/upgrade_tests"
CORE_JOBS_BUDGET_SEC="${CORE_JOBS_BUDGET_SEC:-14400}"
CREATOR_PARAM_BUDGET_SEC="${CREATOR_PARAM_BUDGET_SEC:-180}"
CURRENT_PHASE=""

atomic_write() {
  local path="$1" body="$2"
  printf '%s\n' "$body" > "${path}.tmp"
  mv "${path}.tmp" "$path"
}

set_stage() {
  atomic_write "${DIR}/pipeline.stage" "$1"
  printf '[postflight] stage=%s\n' "$1"
}

phase_state() {
  atomic_write "${DIR}/postflight.${1}.state" "$2"
}

on_exit() {
  local rc=$?
  if (( rc != 0 )) && [[ -n "$CURRENT_PHASE" ]]; then
    phase_state "$CURRENT_PHASE" failed
    set_stage "postflight_failed:${CURRENT_PHASE}"
  fi
}
trap on_exit EXIT

run_phase() {
  local phase="$1"
  shift
  CURRENT_PHASE="$phase"
  phase_state "$phase" running
  set_stage "postflight_${phase}"
  if "$@"; then
    phase_state "$phase" passed
    CURRENT_PHASE=""
    return 0
  else
    local rc=$?
    phase_state "$phase" failed
    return "$rc"
  fi
}

wait_for_core_jobs() {
  local start=$SECONDS blockchain backend state
  while (( SECONDS - start < CORE_JOBS_BUDGET_SEC )); do
    blockchain="$(cat "${DIR}/blockchain.state" 2>/dev/null || printf missing)"
    backend="$(cat "${DIR}/backend.state" 2>/dev/null || printf missing)"
    printf '[postflight] core jobs blockchain=%s backend=%s\n' "$blockchain" "$backend"
    for state in "$blockchain" "$backend"; do
      case "$state" in
        passed|running|missing) ;;
        failed) return 1 ;;
        *) printf '[postflight] invalid core job state: %s\n' "$state" >&2; return 1 ;;
      esac
    done
    if [[ "$blockchain" == passed && "$backend" == passed ]]; then
      return 0
    fi
    sleep 5
  done
  printf '[postflight] timed out after %ss waiting for blockchain and backend\n' \
    "$CORE_JOBS_BUDGET_SEC" >&2
  return 1
}

wait_creator_param() {
  python3 - "$CREATOR_PARAM_BUDGET_SEC" <<'PY'
import json
import sys
import time
import urllib.request

budget = int(sys.argv[1])
deadline = time.monotonic() + budget
last = None
while time.monotonic() < deadline:
    try:
        with urllib.request.urlopen(
            "http://127.0.0.1:1317/mirage/core/v1/params", timeout=5
        ) as response:
            params = json.load(response)["params"]
        last = int(params["creator_epoch_seconds"])
        print(f"[postflight] creator_epoch_seconds={last}", flush=True)
        if last == 300:
            raise SystemExit(0)
    except Exception as error:
        print(f"[postflight] params query not ready: {error}", flush=True)
    time.sleep(3)
raise SystemExit(
    f"timed out after {budget}s waiting for creator_epoch_seconds=300 (last={last!r})"
)
PY
}

run_phase upgrade python3 /opt/mirage/scripts/verify_upgrade.py
run_phase core_jobs wait_for_core_jobs
run_phase extended python3 tests/test_extended.py
run_phase creator_proposal \
  python3 scripts/submit_proposal.py local \
  scripts/proposals/proposal_test_creator_rewards.json --no-confirm
run_phase creator_activation wait_creator_param
run_phase creator_payout python3 /opt/mirage/scripts/verify_creator_payout.py
set_stage postflight_complete
EOF
  chmod +x "${STATUS_HOST}/postflight.sh"
}

clear_status() {
  log "clearing ${STATUS_HOST}"
  rm -rf "$STATUS_HOST"
  mkdir -p "$STATUS_HOST"
  write_run_job
  write_postflight
}

# Successful jobs need no leftover scratch. Failed runs preserve this directory
# because their captured output is the evidence needed to diagnose the failure.
remove_status_dir() {
  if [[ -d "$STATUS_HOST" ]]; then
    log "removing ${STATUS_HOST}"
    rm -rf "$STATUS_HOST"
  fi
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
      die "the pipeline died at stage '${stage}'; logs preserved at ${STATUS_HOST}"
    fi
    log "pipeline.stage=${stage}"
    print_job_states
    if [[ -f "${STATUS_HOST}/all.json" ]]; then
      echo
      log "all jobs finished"
      cat "${STATUS_HOST}/all.json"
      echo
      if [[ -f "${STATUS_HOST}/verify.out" ]]; then
        log "verify/postflight output:"
        cat "${STATUS_HOST}/verify.out"
      fi
      local name rc=0
      for name in "${JOBS[@]}"; do
        if [[ "$(job_state "$name")" != "passed" ]]; then
          rc=1
          echo
          log "${name} failure output:"
          if [[ -f "${STATUS_HOST}/${name}.out" ]]; then
            cat "${STATUS_HOST}/${name}.out"
          else
            printf 'missing captured output: %s\n' "${STATUS_HOST}/${name}.out"
          fi
        fi
      done
      if (( rc != 0 )); then
        log "rehearsal failed; logs preserved at ${STATUS_HOST}"
        exit "$rc"
      fi
      remove_status_dir
      exit 0
    fi
    sleep 5
  done
  echo
  print_job_states
  die "timed out after ${WAIT_BUDGET_SEC}s; logs preserved at ${STATUS_HOST}"
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

wait_param_limit() {
  local name="$1" want="$2"
  local start=$SECONDS limit
  log "waiting for ${name}=${want} (budget ${POW_BUDGET_SEC}s)"
  while (( SECONDS - start < POW_BUDGET_SEC )); do
    if limit=$(chain_param "$name"); then
      log "${name}=${limit}"
      if [[ "$limit" -eq "$want" ]]; then
        return 0
      fi
    else
      log "params query not ready"
    fi
    sleep 3
  done
  die "timed out waiting for ${name}=${want}"
}

# Raise a limit only when it is not already raised. MsgUpdateParams rejects an
# update whose mask selects a field it would not change ("update_mask does not
# change any selected field"), so re-proposing against an already-raised chain
# fails the proposal and, under set -e, would kill the pipeline for no reason.
ensure_param_limit() {
  local name="$1" want="$2" proposal="$3"
  local limit
  if limit=$(chain_param "$name") && [[ "$limit" -eq "$want" ]]; then
    log "${name} already ${want}; skipping the proposal"
    return 0
  fi
  log "raise ${name} for the test suites (currently ${limit:-unknown})"
  python3 "${ROOT}/scripts/submit_proposal.py" local "$proposal" --no-confirm
  wait_param_limit "$name" "$want"
}

# The transaction-heavy suites run as a handful of wallets, so a subscriber
# spends far more than a real user's share of the daily relay quota in one run.
# Left at the production default the suite starts failing partway through with
# subscriber_daily_limit_reached, which says nothing about the release.
ensure_test_limits() {
  ensure_param_limit pow_message_limit 9999999 "$PROPOSAL_POW"
  ensure_param_limit subscriber_daily_relay_limit 10000 "$PROPOSAL_RELAY_LIMIT"
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

launch_jobs() {
  write_run_job
  wait_until 60 "supervisord socket" supervisor_ready
  wait_until 90 "backend /api/get_parameters" backend_ready

  log "launching detached docker exec jobs: blockchain, backend, verify/postflight"
  docker exec -d "$CONTAINER" bash "${STATUS_CTN}/run_job.sh" blockchain python3 tests/test_blockchain.py
  docker exec -d "$CONTAINER" bash "${STATUS_CTN}/run_job.sh" backend python3 tests/test_backend.py
  docker exec -d "$CONTAINER" env \
    "CORE_JOBS_BUDGET_SEC=${CORE_JOBS_BUDGET_SEC}" \
    "CREATOR_PARAM_BUDGET_SEC=${CREATOR_PARAM_BUDGET_SEC}" \
    bash "${STATUS_CTN}/run_job.sh" verify bash "${STATUS_CTN}/postflight.sh"
}

print_monitor() {
  cat <<EOF

Jobs launched as detached docker exec processes.
Watch live status:  mirage-status

Poll while running (removed once --wait finishes):
  cat ${STATUS_HOST}/pipeline.stage
  cat ${STATUS_HOST}/blockchain.state ${STATUS_HOST}/backend.state ${STATUS_HOST}/verify.state
  cat ${STATUS_HOST}/all.json
  cat ${STATUS_HOST}/verify.out

Block until done (prints the summary, then deletes ${STATUS_HOST}):
  scripts/test_upgrade.sh --wait
EOF
}

run_pipeline() {
  [[ -f "$PROPOSAL_UPGRADE" ]] || die "missing ${PROPOSAL_UPGRADE}"
  [[ -f "$PROPOSAL_POW" ]] || die "missing ${PROPOSAL_POW}"
  [[ -f "$PROPOSAL_RELAY_LIMIT" ]] || die "missing ${PROPOSAL_RELAY_LIMIT}"
  [[ -f "$PROPOSAL_CREATOR_TEST" ]] || die "missing ${PROPOSAL_CREATOR_TEST}"
  [[ -f "${ROOT}/scripts/verify_creator_payout.py" ]] || die "missing creator payout verifier"
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
  set_stage backup_image
  assert_backup_image_version
  set_stage proto_parity
  verify_proto_generation_parity
  set_stage reset

  log "reset local testnet from latest mirage.vote backup"
  python3 "${ROOT}/scripts/reset_local_testnet.py" --file "$BACKUP_TARBALL"
  wait_until "$RPC_BUDGET_SEC" "RPC after reset" rpc_is_up
  capture_pre_upgrade_params

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
  ensure_test_limits

  launch_jobs
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
