package iavl

import (
	"os"
	"os/exec"
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
