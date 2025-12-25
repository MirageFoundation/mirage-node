package core

import (
	corekeeper "mirage/x/core/keeper"
	"testing"
)

func TestReservedUsernameForModule(t *testing.T) {
	if got := reservedUsernameForModule("fee_collector"); got != "mirage-fee-collector" {
		t.Fatalf("unexpected reserved username: %s", got)
	}
}

func TestReservedModuleAccountNames_NotEmpty(t *testing.T) {
	names := reservedModuleAccountNames()
	if len(names) == 0 {
		t.Fatal("expected reserved module account names")
	}
	// spot-check a couple of expected entries
	want := map[string]bool{
		"fee_collector": true,
		"gov":           true,
		"core":          true,
	}
	have := map[string]bool{}
	for _, n := range names {
		have[n] = true
	}
	for k := range want {
		if !have[k] {
			t.Fatalf("missing reserved module name: %s", k)
		}
	}
}

func TestUtcJulianDayFromUnix(t *testing.T) {
	// 0 -> day 0
	if got := corekeeper.UTCJulianDayFromUnix(0); got != 0 {
		t.Fatalf("want 0, got %d", got)
	}
	// 86399 -> still day 0
	if got := corekeeper.UTCJulianDayFromUnix(86399); got != 0 {
		t.Fatalf("want 0, got %d", got)
	}
	// 86400 -> day 1
	if got := corekeeper.UTCJulianDayFromUnix(86400); got != 1 {
		t.Fatalf("want 1, got %d", got)
	}
}

// punish validator tests added in external test to avoid import cycles
