package consensusfatal

import (
	"fmt"
	"os"
	"path/filepath"
	"time"
)

// BreadcrumbPath returns the file a halt writes before exiting.
//
// recover.sh reads it, so a halt that happened while nobody was watching still
// reaches the forensic-snapshot chokepoint with its reason attached instead of
// being recovered as a generic "node is down". Without it, an operator's first
// action after a halt from a background goroutine is the wipe AGENTS.md forbids.
//
// Keep this resolution order identical to breadcrumbPath in
// patches/iavl/consensus_fatal.go, which cannot import this package.
func BreadcrumbPath() string {
	if p := os.Getenv("MIRAGE_CONSENSUS_FATAL_FILE"); p != "" {
		return p
	}
	if home := os.Getenv("MIRAGE_NODE_HOME"); home != "" {
		return filepath.Join(home, ".consensus_fatal")
	}
	return filepath.Join(os.Getenv("HOME"), ".mirage", ".consensus_fatal")
}

// writeBreadcrumb records why the process is about to die. Every failure is
// ignored on purpose: a breadcrumb that cannot be written must never stop or
// delay the halt itself.
func writeBreadcrumb(reason string) {
	path := BreadcrumbPath()
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return
	}
	body := fmt.Sprintf("utc=%s\npid=%d\nreason=%s\n",
		time.Now().UTC().Format(time.RFC3339), os.Getpid(), reason)
	_ = os.WriteFile(path, []byte(body), 0o644)
}

// haltWith terminates the process on a CONSENSUS_FATAL condition.
// Overridden in tests via SetHaltForTest so require.PanicsWithError still works.
var haltWith = func(err error) {
	fmt.Fprintf(os.Stderr, "FATAL: %v\n", err)
	writeBreadcrumb(err.Error())
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
