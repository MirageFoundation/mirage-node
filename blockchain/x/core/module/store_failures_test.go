package core

import (
	"encoding/binary"
	"errors"
	"fmt"
	"strings"
	"testing"

	sdk "github.com/cosmos/cosmos-sdk/types"
	"github.com/stretchr/testify/require"

	"mirage/x/core/types"
)

// Injected store-failure coverage for the consensus-write fail-fast contract
// (review M-5, M-6, L-2, L-3). Every test here proves that a node-local
// Get/Set/Delete failure on state that a later block reads produces an error
// instead of a committed divergence.

const powCleanupMarkerKey = "pow_cleanup_marker"

func powCounterKey(height int64) string {
	return fmt.Sprintf("pow_msg_count:%d", height)
}

func seedPowCounter(mk *mockKeeper, height int64, count uint64) {
	bz := make([]byte, 8)
	binary.BigEndian.PutUint64(bz, count)
	mk.storeService.store[powCounterKey(height)] = bz
}

func seedCleanupMarker(mk *mockKeeper, marker uint64) {
	bz := make([]byte, 8)
	binary.BigEndian.PutUint64(bz, marker)
	mk.storeService.store[powCleanupMarkerKey] = bz
}

// --- M-6: cleanup cursor -----------------------------------------------------

// TestCleanupOldCountersFailsOnMarkerGetFailure pins the M-6 fix. A read
// failure on the marker used to be indistinguishable from "no marker", which
// restarted this node's sweep at height 1 while peers continued from the
// stored cursor — different committed keysets, different app hash.
func TestCleanupOldCountersFailsOnMarkerGetFailure(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()
	params := types.DefaultParams()

	seedCleanupMarker(mk, 50)
	seedPowCounter(mk, 1, 7)
	mk.storeService.getErrors = map[string]error{
		powCleanupMarkerKey: errors.New("simulated cleanup marker Get failure"),
	}

	err := mk.CleanupOldCounters(ctx, params)
	require.Error(t, err, "marker Get failure must not be read as an absent marker")
	require.Contains(t, err.Error(), "CONSENSUS_FATAL:POW_CLEANUP_MARKER_GET")
	require.Contains(t, mk.storeService.store, powCounterKey(1),
		"no counter may be deleted when the cursor could not be read")
}

// TestCleanupOldCountersFailsOnMalformedMarker rejects a marker that is present
// but not eight bytes, rather than silently restarting the sweep at height 1.
func TestCleanupOldCountersFailsOnMalformedMarker(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()

	mk.storeService.store[powCleanupMarkerKey] = []byte{0x01, 0x02}
	seedPowCounter(mk, 1, 7)

	err := mk.CleanupOldCounters(ctx, types.DefaultParams())
	require.Error(t, err)
	require.Contains(t, err.Error(), "CONSENSUS_FATAL:POW_CLEANUP_MARKER_LEN")
	require.Contains(t, mk.storeService.store, powCounterKey(1))
}

// TestCleanupOldCountersFailsOnOutOfRangeMarker rejects a decodable marker that
// cannot be a real cursor: zero, or a height above the current block.
func TestCleanupOldCountersFailsOnOutOfRangeMarker(t *testing.T) {
	for name, marker := range map[string]uint64{
		"zero":         0,
		"above_height": 101,
		"wrapped":      ^uint64(0),
	} {
		t.Run(name, func(t *testing.T) {
			mk := newMockKeeper()
			ctx := newMockContext()

			seedCleanupMarker(mk, marker)
			seedPowCounter(mk, 1, 7)

			err := mk.CleanupOldCounters(ctx, types.DefaultParams())
			require.Error(t, err)
			require.Contains(t, err.Error(), "CONSENSUS_FATAL:POW_CLEANUP_MARKER_RANGE")
			require.Contains(t, mk.storeService.store, powCounterKey(1))
		})
	}
}

// TestCleanupOldCountersAbsentMarkerStartsAtGenesis keeps the happy path: with
// no marker the sweep starts at height 1, deletes up to the cutoff, and records
// the cursor for the next sweep.
func TestCleanupOldCountersAbsentMarkerStartsAtGenesis(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()
	params := types.DefaultParams()

	// Default window is 20 blocks, so at height 100 the cutoff is 60.
	seedPowCounter(mk, 1, 7)
	seedPowCounter(mk, 59, 7)
	seedPowCounter(mk, 90, 7)

	require.NoError(t, mk.CleanupOldCounters(ctx, params))
	require.NotContains(t, mk.storeService.store, powCounterKey(1))
	require.NotContains(t, mk.storeService.store, powCounterKey(59))
	require.Contains(t, mk.storeService.store, powCounterKey(90),
		"counters inside the retained range must survive the sweep")

	marker, ok := mk.storeService.store[powCleanupMarkerKey]
	require.True(t, ok, "a completed sweep must record its cursor")
	require.Len(t, marker, 8)
	require.Greater(t, binary.BigEndian.Uint64(marker), uint64(1))
}

// TestCleanupOldCountersFailsOnCounterDeleteFailure proves a partial sweep is
// never committed as a successful one.
func TestCleanupOldCountersFailsOnCounterDeleteFailure(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()

	seedPowCounter(mk, 1, 7)
	mk.storeService.deleteErrors = map[string]error{
		powCounterKey(1): errors.New("simulated counter delete failure"),
	}

	err := mk.CleanupOldCounters(ctx, types.DefaultParams())
	require.Error(t, err)
	require.NotContains(t, mk.storeService.store, powCleanupMarkerKey,
		"a failed sweep must not advance the cursor")
}

// --- M-5 / M-6: BeginBlock propagation --------------------------------------

// TestBeginBlockFailsClosedOnCleanupMarkerGetFailure pins the caller half of
// M-6. Returning an error from the keeper is not enough on its own: BeginBlock
// used to log cleanup failures and continue, which committed the block anyway.
func TestBeginBlockFailsClosedOnCleanupMarkerGetFailure(t *testing.T) {
	mk := newMockKeeper()
	am := newTestModule(mk)
	ctx := newMockContext() // height 100 → the every-100-blocks sweep runs

	seedCleanupMarker(mk, 50)
	seedPowCounter(mk, 1, 7)
	mk.storeService.getErrors = map[string]error{
		powCleanupMarkerKey: errors.New("simulated cleanup marker Get failure"),
	}

	err := am.BeginBlock(ctx)
	require.Error(t, err, "BeginBlock must not commit a block after a failed cleanup sweep")
	require.Contains(t, mk.storeService.store, powCounterKey(1),
		"no counter may be deleted when the cursor could not be read")
}

// TestBeginBlockFailsClosedOnDifficultyInitFailure covers the base-difficulty
// initialization write, which the PoW ante reads on every transaction.
func TestBeginBlockFailsClosedOnDifficultyInitFailure(t *testing.T) {
	mk := newMockKeeper()
	am := newTestModule(mk)
	ctx := newMockContext()

	mk.storeService.setErrors = map[string]error{
		"current_difficulty": errors.New("simulated difficulty init failure"),
	}

	require.Error(t, am.BeginBlock(ctx),
		"a node that cannot initialize difficulty would admit work at a different cost than its peers")
}

// TestBeginBlockReservedProfileBootstrapIsIdempotent is the carryover gap from
// the review's test-coverage table: the one-shot bootstrap must not re-run once
// the sentinel is set. Injecting write failures on the second pass proves no
// claim or profile write is attempted.
func TestBeginBlockReservedProfileBootstrapIsIdempotent(t *testing.T) {
	mk := newMockKeeper()
	am := newTestModule(mk)
	ctx := newMockContext()

	require.NoError(t, am.BeginBlock(ctx))

	bootstrapped, err := mk.HasReservedProfilesBootstrapped(ctx)
	require.NoError(t, err)
	require.True(t, bootstrapped, "first BeginBlock must set the bootstrap sentinel")

	// Any profile or username write on the second pass now fails; BeginBlock
	// must still succeed, proving the bootstrap was skipped entirely. Ordinary
	// per-block writes such as the supply baseline are left working.
	failProfileWrites := map[string]error{}
	for key := range mk.storeService.store {
		if strings.HasPrefix(key, types.ProfilesPrefix) || strings.HasPrefix(key, types.UsernamesPrefix) {
			failProfileWrites[key] = errors.New("second-pass write must not happen: " + key)
		}
	}
	require.NotEmpty(t, failProfileWrites,
		"first BeginBlock should have written at least one reserved profile")
	mk.storeService.setErrors = failProfileWrites

	require.NoError(t, am.BeginBlock(ctx),
		"a second BeginBlock must not rewrite reserved profiles")
}

// --- L-2: PoW window clear ---------------------------------------------------

// TestClearPoWWindowFailsOnDeleteFailure pins L-2: a partially cleared window
// feeds a different sliding-window count into the next difficulty decision.
func TestClearPoWWindowFailsOnDeleteFailure(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()

	seedPowCounter(mk, 90, 3)
	mk.storeService.deleteErrors = map[string]error{
		powCounterKey(90): errors.New("simulated window delete failure"),
	}

	err := mk.ClearPoWWindow(ctx, types.DefaultParams())
	require.Error(t, err)
	require.Contains(t, err.Error(), "CONSENSUS_FATAL:POW_WINDOW_CLEAR")
}

// --- L-3: difficulty secondary writes ---------------------------------------

// TestSetCurrentDifficultyFailsOnSecondaryWriteFailure pins L-3: previous
// difficulty and change height are read by the ante grace window, so all three
// writes are one state transition.
func TestSetCurrentDifficultyFailsOnSecondaryWriteFailure(t *testing.T) {
	for name, key := range map[string]string{
		"previous_difficulty": "prev_difficulty",
		"change_height":       "last_diff_change_height",
	} {
		t.Run(name, func(t *testing.T) {
			mk := newMockKeeper()
			ctx := newMockContext()

			mk.storeService.setErrors = map[string]error{
				key: errors.New("simulated secondary difficulty write failure"),
			}

			err := mk.SetCurrentDifficulty(ctx, 4)
			require.Error(t, err,
				"a secondary difficulty write failure must not report success")
		})
	}
}

// --- M-5: EndBlock propagation ----------------------------------------------

// busyContext seeds enough PoW messages in the window to cross PowMessageLimit
// so EndBlock takes the busy-increase branch.
func busyContext(t *testing.T, mk *mockKeeper) sdk.Context {
	t.Helper()
	ctx := newMockContext()
	params := types.DefaultParams()
	seedPowCounter(mk, ctx.BlockHeight(), params.PowMessageLimit)
	return ctx
}

// TestEndBlockFailsClosedOnWindowClearFailureBusyPath proves the busy-increase
// branch no longer commits a difficulty bump alongside a half-cleared window.
func TestEndBlockFailsClosedOnWindowClearFailureBusyPath(t *testing.T) {
	mk := newMockKeeper()
	am := newTestModule(mk)
	ctx := busyContext(t, mk)

	mk.storeService.deleteErrors = map[string]error{
		powCounterKey(ctx.BlockHeight()): errors.New("simulated window delete failure"),
	}

	err := am.EndBlock(ctx)
	require.Error(t, err,
		"window clear failure must propagate so the difficulty bump is not committed")
}

// TestEndBlockFailsClosedOnDifficultyWriteFailureBusyPath covers the busy-path
// difficulty write, which the previous contract logged and continued.
func TestEndBlockFailsClosedOnDifficultyWriteFailureBusyPath(t *testing.T) {
	mk := newMockKeeper()
	am := newTestModule(mk)
	ctx := busyContext(t, mk)

	mk.storeService.setErrors = map[string]error{
		"current_difficulty": errors.New("simulated busy difficulty write failure"),
	}

	require.Error(t, am.EndBlock(ctx))
}

// TestEndBlockFailsClosedOnNeutralCalmReset covers the branch that previously
// discarded its error entirely: a window that is neither busy nor calm resets
// the calm sequence, and that reset decides when difficulty next drops.
func TestEndBlockFailsClosedOnNeutralCalmReset(t *testing.T) {
	mk := newMockKeeper()
	am := newTestModule(mk)
	ctx := newMockContext()
	params := types.DefaultParams()

	// Between PowCalmPeriodDefinition and PowMessageLimit → neutral window.
	seedPowCounter(mk, ctx.BlockHeight(), params.PowCalmPeriodDefinition+1)
	require.NoError(t, mk.SetConsecutiveLowUsage(ctx, 5))

	mk.storeService.setErrors = map[string]error{
		"consecutive_low_usage": errors.New("simulated neutral calm reset failure"),
	}

	require.Error(t, am.EndBlock(ctx),
		"the neutral-window calm reset must not discard its error")
}
