package iavl

import (
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

func TestConsensusFatalHaltExitsProcess(t *testing.T) {
	if os.Getenv("MIRAGE_TEST_IAVL_FATAL_EXIT") == "1" {
		consensusFatalHalt("CONSENSUS_FATAL:test exit")
		return
	}

	cmd := exec.Command(os.Args[0], "-test.run=^TestConsensusFatalHaltExitsProcess$")
	cmd.Env = append(os.Environ(), "MIRAGE_TEST_IAVL_FATAL_EXIT=1")
	cmd.Env = append(cmd.Env, "MIRAGE_CONSENSUS_FATAL_FILE="+filepath.Join(t.TempDir(), ".consensus_fatal"))
	output, err := cmd.CombinedOutput()
	exitErr, ok := err.(*exec.ExitError)
	if !ok {
		t.Fatalf("subprocess did not exit non-zero: err=%v output=%s", err, output)
	}
	if exitErr.ExitCode() != 1 {
		t.Fatalf("subprocess exit code=%d, want 1; output=%s", exitErr.ExitCode(), output)
	}
	if !strings.Contains(string(output), "FATAL: CONSENSUS_FATAL:test exit") {
		t.Fatalf("fatal output missing tag: %s", output)
	}
}

// TestConsensusFatalHaltLeavesBreadcrumb pins the hook into recover.sh's
// forensic-snapshot chokepoint. The prune-hole guard fires from the background
// pruning goroutine, so without this file a halt that happened unattended is
// indistinguishable from an ordinary crash, and the operator's first action is
// the wipe that destroys the diverged DB.
func TestConsensusFatalHaltLeavesBreadcrumb(t *testing.T) {
	path := filepath.Join(t.TempDir(), "nested", ".consensus_fatal")
	t.Setenv("MIRAGE_CONSENSUS_FATAL_FILE", path)

	prev := exitProcess
	exited := -1
	exitProcess = func(code int) { exited = code }
	defer func() {
		exitProcess = prev
		if r := recover(); r == nil {
			t.Fatal("consensusFatalHalt must not fall through when exitProcess returns")
		}
	}()

	defer func() {
		if exited != 1 {
			t.Errorf("exit code=%d, want 1", exited)
		}
		body, err := os.ReadFile(path)
		if err != nil {
			t.Fatalf("breadcrumb not written: %v", err)
		}
		if !strings.Contains(string(body), "CONSENSUS_FATAL:PRUNE_HOLE version=7") {
			t.Errorf("breadcrumb missing the reason: %s", body)
		}
		if !strings.Contains(string(body), "pid=") || !strings.Contains(string(body), "utc=") {
			t.Errorf("breadcrumb missing pid/utc: %s", body)
		}
	}()

	consensusFatalHalt("CONSENSUS_FATAL:PRUNE_HOLE version=%d missing above existing history", 7)
}

// TestBreadcrumbPathResolutionOrder keeps the fork's copy in lockstep with
// consensusfatal.BreadcrumbPath, which recover.sh reads.
func TestBreadcrumbPathResolutionOrder(t *testing.T) {
	t.Setenv("MIRAGE_CONSENSUS_FATAL_FILE", "/explicit/path")
	t.Setenv("MIRAGE_NODE_HOME", "/node/home")
	if got := breadcrumbPath(); got != "/explicit/path" {
		t.Fatalf("explicit override ignored: %s", got)
	}

	t.Setenv("MIRAGE_CONSENSUS_FATAL_FILE", "")
	if got := breadcrumbPath(); got != "/node/home/.consensus_fatal" {
		t.Fatalf("node home not honoured: %s", got)
	}

	t.Setenv("MIRAGE_NODE_HOME", "")
	t.Setenv("HOME", "/root")
	if got := breadcrumbPath(); got != "/root/.mirage/.consensus_fatal" {
		t.Fatalf("default path wrong: %s", got)
	}
}
