package consensusfatal

import (
	"fmt"
	"os"
)

// haltWith terminates the process on a CONSENSUS_FATAL condition.
// Overridden in tests via SetHaltForTest so require.PanicsWithError still works.
var haltWith = func(err error) {
	fmt.Fprintf(os.Stderr, "FATAL: %v\n", err)
	os.Exit(1)
}

// SetHaltForTest replaces the halt function. Restore with the returned func.
// Typical test usage: defer consensusfatal.SetHaltForTest(func(err error) { panic(err) })()
func SetHaltForTest(fn func(error)) (restore func()) {
	prev := haltWith
	haltWith = fn
	return func() { haltWith = prev }
}

// HaltErr logs and terminates (or panics in tests) for a CONSENSUS_FATAL error.
// Classification: call sites must have a comment `// CONSENSUS_FATAL class: node-local|deterministic`
//
// The trailing panic is intentional: os.Exit never returns, but if haltWith is
// a no-op or a buggy test mock that returns, fall-through would let GetParams
// return zero Params (or GetRelayCredit return ZeroInt) — the exact silent
// default class that caused past divergences. panic makes HaltErr noreturn.
func HaltErr(err error) {
	haltWith(err)
	panic(err)
}

// Haltf is convenience for HaltErr(fmt.Errorf(...))
func Haltf(format string, args ...any) {
	HaltErr(fmt.Errorf(format, args...))
}
