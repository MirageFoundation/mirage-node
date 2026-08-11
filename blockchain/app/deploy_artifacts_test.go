package app

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/stretchr/testify/require"
)

// Static deploy-artifact regression tests.
//
// Why these live in blockchain/app: this is a Go test package that runs as
// part of `make test-fast`, which is the gate every CI/release build runs.
// The deploy-side bash scripts and Dockerfile have no test infrastructure of
// their own. Pinning the contract here makes sure a future change to the
// Dockerfile (e.g. reverting to selective COPYs) or harden_server.sh
// (e.g. accidentally removing the weekly-upgrade pre-flight) breaks the
// build before it ships.
//
// The tests are static-only — they read files from disk, parse them, and
// assert specific shape invariants tied to changes in this release window
// (since the v1.25.4 prod tag).

// repoRoot returns the absolute path of the repository root, derived from
// the location of this test file. blockchain/app/ → repo root is two levels
// up.
func repoRoot(t *testing.T) string {
	t.Helper()
	wd, err := os.Getwd()
	require.NoError(t, err)
	root, err := filepath.Abs(filepath.Join(wd, "..", ".."))
	require.NoError(t, err)
	return root
}

// readRepoFile reads a path relative to the repo root.
func readRepoFile(t *testing.T, rel string) string {
	t.Helper()
	abs := filepath.Join(repoRoot(t), rel)
	b, err := os.ReadFile(abs)
	require.NoError(t, err, "reading %s", abs)
	return string(b)
}

func dockerPathEq(got, want string) bool {
	return strings.TrimRight(got, "/") == strings.TrimRight(want, "/")
}

// TestDockerfileBulkCopiesDeploy pins the v1.25.4-cycle Dockerfile change:
// the final image stage must bulk-COPY the entire deploy/ tree, not
// cherry-pick individual files. The original failure mode (UAT broken on
// 2026-05-26) was entrypoint.sh referencing run_miraged_supervised.sh, which
// existed on disk but was never copied into the image because the Dockerfile
// only listed specific deploy/* files.
//
// We assert two things:
//
//  1. The final stage contains a `COPY --from=builder /opt/mirage/deploy
//     /opt/mirage/deploy` (or equivalent bulk copy of the deploy directory),
//     not `COPY ... deploy/<filename>`.
//  2. The intermediate `builder` stage stages the entire deploy/ tree
//     into /opt/mirage/deploy/.
//
// Together this guarantees: any new file added under deploy/ ships in the
// final image automatically. No cherry-pick step can silently drop it.
func TestDockerfileBulkCopiesDeploy(t *testing.T) {
	dockerfile := readRepoFile(t, "deploy/Dockerfile")

	// 1) Final stage bulk-copies deploy/.
	foundFinalBulkCopy := false
	wantFinalSrc := "/opt/mirage/deploy"
	wantFinalDst := "/opt/mirage/deploy"

	// 2) The Dockerfile must not silently re-introduce a selective per-file
	// copy from --from=builder for individual deploy/ files. Such a line
	// would be e.g. `COPY --from=builder /opt/mirage/deploy/foo.sh ...` —
	// detect any line that copies a single file under /opt/mirage/deploy/
	// from the builder stage.
	for _, line := range strings.Split(dockerfile, "\n") {
		trimmed := strings.TrimSpace(line)
		fields := strings.Fields(trimmed)
		if len(fields) < 4 || fields[0] != "COPY" || fields[1] != "--from=builder" {
			continue
		}
		src := fields[2]
		dst := fields[3]
		if dockerPathEq(src, wantFinalSrc) && dockerPathEq(dst, wantFinalDst) {
			foundFinalBulkCopy = true
			continue
		}
		if strings.HasPrefix(src, wantFinalSrc+"/") {
			require.Failf(t,
				"selective COPY of a single deploy/ file in the final stage",
				"found %q — use bulk COPY --from=builder %s %s instead",
				trimmed, wantFinalSrc, wantFinalDst)
		}
	}
	require.True(t, foundFinalBulkCopy,
		"final image stage must bulk-COPY the entire deploy/ tree (regression: "+
			"selective COPYs silently dropped run_miraged_supervised.sh on 2026-05-26)")

	// 3) The intermediate builder stage must stage the deploy/ tree so
	// the final-stage bulk copy has something to copy from.
	foundBuilderBulkCopy := false
	for _, line := range strings.Split(dockerfile, "\n") {
		fields := strings.Fields(strings.TrimSpace(line))
		if len(fields) >= 3 && fields[0] == "COPY" &&
			dockerPathEq(fields[1], "deploy") &&
			dockerPathEq(fields[2], "/opt/mirage/deploy") {
			foundBuilderBulkCopy = true
			break
		}
	}
	require.True(t, foundBuilderBulkCopy,
		"builder stage must stage deploy/ into /opt/mirage/deploy/ for the "+
			"final-stage bulk copy to pick up")
}

// TestRunMiragedSupervisedScriptPresent pins the run_miraged_supervised.sh
// inclusion change. entrypoint.sh execs this script directly; if the file
// is removed from the deploy/ tree, the container crashes on startup. We
// assert it exists, is non-empty, and is referenced by entrypoint.sh.
func TestRunMiragedSupervisedScriptPresent(t *testing.T) {
	root := repoRoot(t)

	supervised := filepath.Join(root, "deploy", "run_miraged_supervised.sh")
	stat, err := os.Stat(supervised)
	require.NoError(t, err, "deploy/run_miraged_supervised.sh must exist")
	require.False(t, stat.IsDir())
	require.Greater(t, stat.Size(), int64(0), "supervised wrapper must not be empty")

	entrypoint := readRepoFile(t, "deploy/entrypoint.sh")
	require.Contains(t, entrypoint, "run_miraged_supervised.sh",
		"deploy/entrypoint.sh must reference run_miraged_supervised.sh "+
			"(it is the supervisor wrapper that auto-restarts miraged on panic)")
}

// TestRunIndexerSupervisedScriptPresent pins the indexer supervisor the same
// way. Before 2026-08-11 the indexer ran as a bare `python3 indexer/main.py`
// in its tmux window, so one fatal exception (a post that broke urlsplit)
// stopped indexing on every node until an operator restarted it by hand.
// Reverting entrypoint.sh to the bare invocation restores that outage mode.
func TestRunIndexerSupervisedScriptPresent(t *testing.T) {
	root := repoRoot(t)

	supervised := filepath.Join(root, "deploy", "run_indexer_supervised.sh")
	stat, err := os.Stat(supervised)
	require.NoError(t, err, "deploy/run_indexer_supervised.sh must exist")
	require.False(t, stat.IsDir())
	require.Greater(t, stat.Size(), int64(0), "supervised wrapper must not be empty")

	entrypoint := readRepoFile(t, "deploy/entrypoint.sh")
	require.Contains(t, entrypoint, "run_indexer_supervised.sh",
		"deploy/entrypoint.sh must reference run_indexer_supervised.sh "+
			"(it is the supervisor wrapper that auto-restarts the indexer on crash)")
	require.NotContains(t, entrypoint, "python3 indexer/main.py",
		"deploy/entrypoint.sh must not launch the indexer unsupervised")
}

// TestHardenServerHasPerHostWeeklyUpgrade pins the v1.25.4-cycle
// harden_server.sh change: dropped the unattended-upgrades fleet-wide
// auto-reboot model and replaced it with a per-host mirage-weekly-upgrade
// systemd timer that runs ONLY after a pre-flight health check.
//
// The original failure mode this change prevents: every validator in the
// fleet hitting a daily auto-reboot at the same UTC hour and taking down
// consensus together. This test ensures we don't silently regress to that.
func TestHardenServerHasPerHostWeeklyUpgrade(t *testing.T) {
	harden := readRepoFile(t, "deploy/harden_server.sh")

	// Per-host weekly upgrade scaffolding: timer + service + script.
	required := []string{
		// CLI flags introduced for per-host scheduling
		"--upgrade-day=*",
		"--upgrade-hour=*",
		// Systemd unit names written by the script
		"mirage-weekly-upgrade.timer",
		"mirage-weekly-upgrade.service",
		"mirage-weekly-upgrade.sh",
		// Concrete pre-flight gates — without these the upgrade would
		// reboot a stopped/stale/catching-up validator and risk consensus
		// impact.
		"docker inspect mirage",
		"http://127.0.0.1:26657/status",
		".result.sync_info.catching_up",
		".result.sync_info.latest_block_time",
		"latest block is ${age}s old",
	}
	for _, want := range required {
		require.Contains(t, harden, want,
			"deploy/harden_server.sh must contain %q (per-host weekly "+
				"upgrade scaffolding); regression: fleet-wide auto-reboot",
			want)
	}

	// Negative assertion: the previous fleet-wide model used
	// `Unattended-Upgrade::Automatic-Reboot "true"` to force every host to
	// reboot daily after a kernel update. The replacement model does not
	// auto-reboot from unattended-upgrades; it defers to the per-host
	// weekly timer. If that string ever reappears we lost the protection.
	require.NotContains(t, harden, `Unattended-Upgrade::Automatic-Reboot "true"`,
		"deploy/harden_server.sh must not re-enable fleet-wide unattended "+
			"auto-reboot (replaced by per-host mirage-weekly-upgrade timer)")
}

// TestWeeklyRestartDayIsConfigurable pins the weekly container restart to a
// per-host schedule rather than a day baked into the script.
//
// Three jobs stop these containers: the off-site backup, the weekly restart
// timer, and the weekly OS upgrade. Voting power is split evenly across the
// validators, so quorum needs all but one — two down at the same time stalls
// the chain. Keeping them apart means the operator has to be able to place the
// restart on a day that is clear of the backup, which a hardcoded day
// prevents. The concrete slots live in the operator's .env, not in this repo.
func TestWeeklyRestartDayIsConfigurable(t *testing.T) {
	harden := readRepoFile(t, "deploy/harden_server.sh")

	require.Contains(t, harden, "--weekly-day=*",
		"deploy/harden_server.sh must expose --weekly-day so the restart day "+
			"is configurable per host")

	require.Contains(t, harden, "OnCalendar=${WEEKLY_DAY_NAME} ${WEEKLY_HOUR}:00",
		"the weekly-restart timer must template both day and hour; a "+
			"hardcoded day cannot be moved clear of the backup window")

	require.Regexp(t, `(?m)^WEEKLY_DAY="[1-7]"$`, harden,
		"--weekly-day needs a valid default (1=Mon .. 7=Sun)")

	// The backup stopping the container is why the separation is needed at
	// all. If that ever changes the constraint can be revisited, so assert the
	// coupling is real rather than assumed.
	backup := readRepoFile(t, "scripts/backup_restore.py")
	require.Contains(t, backup, "docker stop mirage",
		"backup_restore.py is expected to stop the container mid-backup; if "+
			"that changed, revisit the restart-day constraint")
}
