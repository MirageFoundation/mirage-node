package iavl

import (
	"fmt"
	"os"
	"path/filepath"
	"time"
)

// exitProcess is a seam so the halt path can be tested. The guard fires from the
// background pruning goroutine, where an untestable os.Exit meant the only way
// to exercise it was to kill a real node.
var exitProcess = os.Exit

// breadcrumbPath mirrors consensusfatal.BreadcrumbPath. Duplicated rather than
// imported because this vendored package cannot depend on mirage/; keep the two
// resolution orders identical.
func breadcrumbPath() string {
	if p := os.Getenv("MIRAGE_CONSENSUS_FATAL_FILE"); p != "" {
		return p
	}
	if home := os.Getenv("MIRAGE_NODE_HOME"); home != "" {
		return filepath.Join(home, ".consensus_fatal")
	}
	return filepath.Join(os.Getenv("HOME"), ".mirage", ".consensus_fatal")
}

// writeBreadcrumb records why the process is about to die, so recover.sh reaches
// its forensic-snapshot chokepoint knowing this was a consensus halt rather than
// an ordinary crash. Failures are ignored: a breadcrumb must never delay a halt.
func writeBreadcrumb(reason string) {
	path := breadcrumbPath()
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return
	}
	body := fmt.Sprintf("utc=%s\npid=%d\nreason=%s\n",
		time.Now().UTC().Format(time.RFC3339), os.Getpid(), reason)
	_ = os.WriteFile(path, []byte(body), 0o644)
}

// consensusFatalHalt terminates the process on a CONSENSUS_FATAL condition.
// Stdlib-only: this vendored package cannot import mirage/.
func consensusFatalHalt(format string, args ...any) {
	msg := fmt.Sprintf(format, args...)
	fmt.Fprintf(os.Stderr, "FATAL: %s\n", msg)
	writeBreadcrumb(msg)
	exitProcess(1)
	panic(msg)
}
