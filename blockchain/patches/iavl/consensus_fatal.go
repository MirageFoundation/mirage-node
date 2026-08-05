package iavl

import (
	"fmt"
	"os"
)

// consensusFatalHalt terminates the process on a CONSENSUS_FATAL condition.
// Stdlib-only: this vendored package cannot import mirage/.
func consensusFatalHalt(format string, args ...any) {
	msg := fmt.Sprintf(format, args...)
	fmt.Fprintf(os.Stderr, "FATAL: %s\n", msg)
	os.Exit(1)
	panic(msg)
}
