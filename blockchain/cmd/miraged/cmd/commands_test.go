package cmd

import (
	"testing"

	dbm "github.com/cosmos/cosmos-db"
)

// closeSpyDB mimics a PebbleDB handle: the first Close() succeeds, a second
// Close() panics "pebble: closed" — exactly the cosmos-sdk v0.54 double-close
// behavior that crashes miraged on every graceful shutdown (postmortem AI#13).
// Only Close() is exercised; the embedded nil dbm.DB satisfies the interface.
type closeSpyDB struct {
	dbm.DB
	closes int
}

func (s *closeSpyDB) Close() error {
	s.closes++
	if s.closes > 1 {
		panic("pebble: closed")
	}
	return nil
}

// TestIdempotentCloseDBAbsorbsDoubleClose pins the contract: the wrapper forwards
// the first Close() to the underlying handle and turns every subsequent Close()
// into a no-op, so the upstream double-close cannot panic the process.
func TestIdempotentCloseDBAbsorbsDoubleClose(t *testing.T) {
	spy := &closeSpyDB{}
	d := &idempotentCloseDB{DB: spy}

	if err := d.Close(); err != nil {
		t.Fatalf("first Close: unexpected error: %v", err)
	}

	defer func() {
		if r := recover(); r != nil {
			t.Fatalf("second Close panicked (shim failed to absorb double-close): %v", r)
		}
	}()
	if err := d.Close(); err != nil {
		t.Fatalf("second Close: unexpected error: %v", err)
	}

	if spy.closes != 1 {
		t.Fatalf("underlying Close called %d times, want exactly 1", spy.closes)
	}
}
