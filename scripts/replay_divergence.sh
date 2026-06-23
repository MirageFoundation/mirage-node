#!/usr/bin/env bash
#
# replay_divergence.sh — LOCAL-ONLY forensic harness to test the IAVL pruning
# divergence hypothesis. See docs/troubleshooting/divergence-recovery.md §0.1/§0.2.
#
# ──────────────────────────────────────────────────────────────────────────────
# WHAT THIS IS
#   You copy a *diverged* chain-DB snapshot (from a forensic capture under
#   /root/.mirage/.divergence_forensics/<utc>-h<height>/ or an old data.preheal-*
#   backup) — and, ideally, a *healthy* peer's snapshot at the same height — to
#   THIS dev box. The script then drives the read-only `cmd/analyze-db` tool over
#   each application.db and looks for the pruning fingerprint:
#     - a blown-out commit-info span (pruning not actually deleting),
#     - a stale `pruneSnapshotHeights` (the 2026-04-02 bug),
#     - per-store IAVL version ranges that disagree between diverged vs healthy.
#
# WHAT IT PROVES / DOES NOT PROVE
#   - A pruning anomaly in the diverged DB SUPPORTS the prune-race hypothesis.
#   - A clean pruning state — with the diverging key in a fast-node-only read
#     path — points BACK at the read-path surface (fast-node), not pruning.
#   - This is a STATIC scan. It does NOT re-execute the block. The faithful
#     behavioral A/B (pruning active vs disabled, *with* the concurrent query
#     load that actually triggers the race) is operator-run; print it with
#     `--procedure`. The locked-down miraged binary has no `rollback`, so there
#     is no push-button single-block re-exec.
#
# SAFETY (RULES.md): NEVER point this at a production host or a live data dir.
#   It only reads local snapshot copies. It does not SSH, curl, or write to any
#   chain DB.
# ──────────────────────────────────────────────────────────────────────────────

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
BLOCKCHAIN_DIR="$REPO_ROOT/blockchain"
ANALYZE_BIN="$BLOCKCHAIN_DIR/bin/analyze-db"

DIVERGED=""
HEALTHY=""
HEIGHT=""
OUT_DIR=""
FORCE_BUILD=0

die() { echo "ERROR: $*" >&2; exit 1; }
log() { echo "[$(date -u +%H:%M:%SZ)] $*"; }

usage() {
	cat <<'EOF'
Usage: replay_divergence.sh --diverged <snapshot> [--healthy <snapshot>] [options]

  --diverged <path>   Diverged chain-DB snapshot. Accepts the snapshot dir, its
                      data/ dir, or the application.db dir directly. REQUIRED.
  --healthy  <path>   Healthy peer snapshot at the same height (for comparison).
  --height   <N>      Divergence height, for the report header (optional).
  --out      <dir>    Where to write reports (default: /tmp/replay_divergence-<ts>).
  --build             Force-rebuild the analyze-db tool.
  --procedure         Print the manual behavioral A/B replay procedure and exit.
  -h | --help         This help.

LOCAL-ONLY. Copy snapshots to this box first; never point at a prod host.
EOF
}

print_procedure() {
	cat <<'EOF'
================ Behavioral A/B replay (operator-run, isolated box) ================
Goal: confirm whether ACTIVE pruning is what flips the app hash at the divergence
height. The trigger is concurrency-driven, so the load matters.

Preconditions (all LOCAL — never prod):
  1. A diverged snapshot at height H AND a matching config/ for an isolated node.
  2. The canonical blocks H..H+2 reachable from a LOCAL block source (a peer's
     blockstore copy, or a local archive node), so the node can apply block H.

Run TWICE, identical except pruning, comparing the app hash the node computes at
H against the canonical app hash (a "wrong Block.Header.AppHash" panic == repro):
  A. pruning = "custom"   (PRUNING_KEEP_RECENT=1000, PRUNING_INTERVAL=100)
  B. pruning = "nothing"  (no pruning at all)

While the node applies H, drive the prod-only concurrent read load against its
RPC/gRPC (mimic the indexer + backend `simulate` + reward distributor): a tight
parallel query loop over balances/params/blocks. The race only fires under it.

Verdict:
  - A diverges (wrong app hash) and B does not  -> pruning race CONFIRMED.
  - Both diverge, or neither                    -> pruning is NOT the trigger;
                                                   look at the read path (fast-node).

Isolation: P2P off (no persistent_peers, pex=false), no validator key in the
keyring, RPC bound to 127.0.0.1 only. This node must never join the real network.
====================================================================================
EOF
}

while [[ $# -gt 0 ]]; do
	case "$1" in
		--diverged) DIVERGED="${2:-}"; shift 2 ;;
		--healthy)  HEALTHY="${2:-}"; shift 2 ;;
		--height)   HEIGHT="${2:-}"; shift 2 ;;
		--out)      OUT_DIR="${2:-}"; shift 2 ;;
		--build)    FORCE_BUILD=1; shift ;;
		--procedure) print_procedure; exit 0 ;;
		-h|--help)  usage; exit 0 ;;
		*) usage; die "unknown argument: $1" ;;
	esac
done

[[ -n "$DIVERGED" ]] || { usage; die "--diverged is required"; }
[[ -z "$OUT_DIR" ]] && OUT_DIR="/tmp/replay_divergence-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$OUT_DIR"

# Resolve an application.db dir from a snapshot/data/db path.
resolve_app_db() {
	local p="$1"
	[[ -e "$p" ]] || die "path does not exist: $p"
	if [[ "$(basename "$p")" == "application.db" && -d "$p" ]]; then echo "$p"; return; fi
	if [[ -d "$p/application.db" ]]; then echo "$p/application.db"; return; fi
	if [[ -d "$p/data/application.db" ]]; then echo "$p/data/application.db"; return; fi
	die "could not find application.db under: $p (expected <snap>/application.db or <snap>/data/application.db)"
}

ensure_tool() {
	if [[ "$FORCE_BUILD" -eq 1 || ! -x "$ANALYZE_BIN" ]]; then
		log "building analyze-db ..."
		( cd "$BLOCKCHAIN_DIR" && go build -o ./bin/analyze-db ./cmd/analyze-db ) \
			|| die "failed to build analyze-db"
	fi
	[[ -x "$ANALYZE_BIN" ]] || die "analyze-db missing after build: $ANALYZE_BIN"
}

# Run analyze-db and write the report; print the verdict-bearing lines.
scan() {
	local label="$1" app_db="$2" report="$3"
	log "scanning $label: $app_db"
	"$ANALYZE_BIN" "$app_db" >"$report" 2>&1 || die "analyze-db failed on $label (see $report)"
	echo "  --- $label: pruning signals ---"
	grep -E '^(Count|Version range|First height|If snapshot-interval|Current height|>>>)' "$report" \
		| sed 's/^/    /' || true
	echo "  --- $label: per-store IAVL version ranges ---"
	grep -E 's/k:[^ ]+/(roots|nodes)' "$report" | sed 's/^/    /' || true
}

ensure_tool

DIV_DB="$(resolve_app_db "$DIVERGED")"
DIV_REPORT="$OUT_DIR/diverged.analyze.txt"

echo "============================================================"
echo "replay_divergence — IAVL pruning forensic scan (LOCAL-ONLY)"
[[ -n "$HEIGHT" ]] && echo "divergence height: $HEIGHT"
echo "reports: $OUT_DIR"
echo "============================================================"

scan "DIVERGED" "$DIV_DB" "$DIV_REPORT"

if [[ -n "$HEALTHY" ]]; then
	HEAL_DB="$(resolve_app_db "$HEALTHY")"
	HEAL_REPORT="$OUT_DIR/healthy.analyze.txt"
	scan "HEALTHY" "$HEAL_DB" "$HEAL_REPORT"
	echo "------------------------------------------------------------"
	echo "DIVERGED vs HEALTHY — commit-info + pruning verdicts:"
	diff -u \
		<(grep -E '^(Count|Version range|>>>)' "$HEAL_REPORT" || true) \
		<(grep -E '^(Count|Version range|>>>)' "$DIV_REPORT" || true) \
		&& echo "  (commit-info/pruning verdicts identical)" || true
fi

echo "------------------------------------------------------------"
# IMPORTANT (2026-06-22): analyze-db's ">>> PRUNING APPEARS BROKEN" line counts
# the cosmos-sdk commit-info store (s/<version>) and fires whenever that store
# holds far more than ~1000 records. We confirmed on real snapshots that a
# HEALTHY mirage-1 peer carries the SAME bloat (2.39M commit-info records from
# version floor 3146400) as a DIVERGED node (2.13M, same floor). So that line
# alone is NOT diagnostic of divergence — it reflects a fleet-wide commit-info
# pruning bug, present on nodes that never diverged. Only a DIVERGED-vs-HEALTHY
# DELTA is suggestive, and even then this static scan cannot see the
# load-triggered IAVL node-level prune race that the §0.1 hypothesis is about
# (that needs the behavioral A/B under concurrent read load, --procedure).
div_commit="$(grep -E '^Count:' "$DIV_REPORT" | head -1 | grep -oE '[0-9]+' | head -1 || echo '?')"
div_floor="$(grep -E '^Version range:' "$DIV_REPORT" | head -1 | grep -oE '[0-9]+' | head -1 || echo '?')"
echo "commit-info store (s/<version>) — diverged: count=${div_commit} floor=${div_floor}"
if [[ -n "$HEALTHY" ]]; then
	heal_commit="$(grep -E '^Count:' "$HEAL_REPORT" | head -1 | grep -oE '[0-9]+' | head -1 || echo '?')"
	heal_floor="$(grep -E '^Version range:' "$HEAL_REPORT" | head -1 | grep -oE '[0-9]+' | head -1 || echo '?')"
	echo "commit-info store (s/<version>) — healthy:  count=${heal_commit} floor=${heal_floor}"
	if [[ "$div_floor" == "$heal_floor" ]]; then
		echo "VERDICT: diverged and healthy share the SAME commit-info floor (${div_floor})."
		echo "         The commit-info bloat is FLEET-WIDE, not divergence-specific, and does"
		echo "         NOT implicate pruning in this divergence. Investigate the read path and"
		echo "         the load-triggered IAVL node race via the behavioral A/B (--procedure)."
	else
		echo "VERDICT: commit-info floors DIFFER (diverged=${div_floor} healthy=${heal_floor})."
		echo "         A real divergence-specific pruning delta — pin the diverging store/key,"
		echo "         then run the behavioral A/B (--procedure)."
	fi
else
	echo "VERDICT: inconclusive without a --healthy baseline. The raw commit-info count is"
	echo "         NOT diagnostic on its own (a healthy peer shows the same bloat). Re-run"
	echo "         with --healthy <peer-snapshot> to get a meaningful diverged-vs-healthy"
	echo "         delta, and run the behavioral A/B (--procedure) for the load-triggered race."
fi
echo "Reports written to: $OUT_DIR"
