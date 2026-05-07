package core

import (
	"errors"
	"testing"

	"github.com/stretchr/testify/require"

	"mirage/x/core/types"
)

// CONSENSUS DETERMINISM CONTRACT for BeginBlock / EndBlock / GetParams /
// MintIfNeeded:
//
// The previous "NEVER HALT THE CHAIN" invariant has been replaced by a
// FAIL-FAST contract for consensus-critical decode failures. Silently
// substituting defaults on one node while peers used the stored bytes
// produced single-node app-hash divergence — the very class of bug that
// jailed mirage.talk in production. The new contract:
//
//   * Consensus-critical reads (params, profile lookups for paid users,
//     recent-block-hashes window) MUST panic on store/decode/validate
//     failure. The chain halts cleanly; the auto-recovery watchdog
//     state-syncs from healthy peers.
//
//   * Non-consensus-critical writes (PruneExpiredNonces,
//     SetCurrentDifficulty, SetConsecutiveLowUsage, etc.) STILL log and
//     continue. Those failures affect ALL nodes equally — same operation,
//     same in-memory inputs, same outcome — and so do not cause divergence.
//
// Tests in this file pin both contracts.

// --- EndBlock: writes still log-and-continue --------------------------------

// TestEndBlockNeverReturnsError_EmptyState verifies the baseline: on a fresh
// store with default params (seeded by newMockKeeper) and no PoW messages /
// expired nonces / subscriptions, the calm-increment path is taken and
// EndBlock returns nil without panicking.
func TestEndBlockNeverReturnsError_EmptyState(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()
	am := newTestModule(mk)

	require.NotPanics(t, func() {
		require.NoError(t, am.EndBlock(ctx))
	})

	// The calm-increment path should have advanced the sequence to 1.
	require.Equal(t, uint64(1), mk.GetConsecutiveLowUsage(ctx),
		"EndBlock should advance the calm sequence on a zero-message block")
}

// TestEndBlockNeverReturnsError_OnSetConsecutiveLowUsageFailure forces the
// calm-increment write to fail. Set failures are non-consensus-critical
// (they fail equally on all nodes; the sequence simply does not advance
// this block on any node). EndBlock logs and returns nil.
func TestEndBlockNeverReturnsError_OnSetConsecutiveLowUsageFailure(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()
	am := newTestModule(mk)

	mk.storeService.setErrors = map[string]error{
		"consecutive_low_usage": errors.New("simulated SetConsecutiveLowUsage failure"),
	}

	require.NotPanics(t, func() {
		require.NoError(t, am.EndBlock(ctx))
	})

	// Sequence must NOT have advanced because the Set failed.
	require.Equal(t, uint64(0), mk.GetConsecutiveLowUsage(ctx),
		"SetConsecutiveLowUsage failure must not be masked by a silent write")
}

// TestEndBlockNeverReturnsError_OnSetCurrentDifficultyFailureCalmDecrease
// forces the calm-decrease branch: start at difficulty 3, seed a calm
// sequence >= threshold, and inject a Set failure on "current_difficulty".
// EndBlock must still return nil — Set failures are non-divergent.
func TestEndBlockNeverReturnsError_OnSetCurrentDifficultyFailureCalmDecrease(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()
	am := newTestModule(mk)

	require.NoError(t, mk.SetCurrentDifficulty(ctx, 3))

	params := types.DefaultParams()
	require.NoError(t, mk.SetConsecutiveLowUsage(ctx, params.PowCalmSequenceThreshold))

	mk.storeService.setErrors = map[string]error{
		"current_difficulty": errors.New("simulated SetCurrentDifficulty failure on calm decrease"),
	}

	require.NotPanics(t, func() {
		require.NoError(t, am.EndBlock(ctx))
	})

	require.Equal(t, uint64(3), mk.GetCurrentDifficulty(ctx),
		"failed SetCurrentDifficulty must leave the difficulty unchanged")
}

// TestEndBlockPropagatesIteratorFailureFromGetExpiredSubscriptions: an
// iterator-open failure on the subscriptions prefix is itself evidence of
// per-node store divergence (deterministic data should iterate identically
// on all nodes). processSubscriptions returns the error and EndBlock now
// halts the chain rather than silently skipping renewals/expiries on this
// node only — the previous "log and continue" let one node skip mutations
// that peers performed, producing app-hash divergence on the next round.
//
// PruneExpiredNonces and GetPoWMessageCount also iterate from EndBlock but
// are non-consensus-critical (their failure paths log and continue without
// state mutation). The blocking case is the subscriptions iterator.
func TestEndBlockPropagatesIteratorFailureFromGetExpiredSubscriptions(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()
	am := newTestModule(mk)

	mk.storeService.iterError = errors.New("simulated iterator failure")

	require.NotPanics(t, func() {
		err := am.EndBlock(ctx)
		require.Error(t, err, "iterator failure must propagate so the chain halts (auto-recovery state-syncs)")
	})
}

// --- EndBlock / BeginBlock: consensus-critical decode failures fail fast ---

// TestEndBlockPanicsOnCorruptParams: corrupt stored params bytes MUST halt
// the chain. The prior behavior (silently fall back to DefaultParams) caused
// per-node app-hash divergence whenever one node's params bytes diverged
// from peers'.
func TestEndBlockPanicsOnCorruptParams(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()
	am := newTestModule(mk)

	mk.storeService.store["params"] = []byte{0xff, 0xff, 0xff, 0xff, 0xff}

	require.Panics(t, func() {
		_ = am.EndBlock(ctx)
	}, "EndBlock must panic on corrupt params (no silent fallback to defaults)")
}

// TestEndBlockPanicsOnParamsStoreGetFailure: a raw store.Get failure on the
// "params" key MUST halt the chain. Silently returning defaults on the
// affected node only would diverge it from peers.
func TestEndBlockPanicsOnParamsStoreGetFailure(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()
	am := newTestModule(mk)

	mk.storeService.getErrors = map[string]error{
		"params": errors.New("simulated store.Get failure on params"),
	}

	require.Panics(t, func() {
		_ = am.EndBlock(ctx)
	}, "EndBlock must panic on store.Get failure for params")
}

// TestRecordRecentBlockHashPanicsOnReadFailure (proxy for BeginBlock fail-fast
// on recent-block-hashes read): when the on-chain window cannot be read, the
// keeper helper MUST surface the error so BeginBlock can halt rather than
// silently writing an empty window. A divergent window across nodes flips
// PoW tx acceptance per-node and produces app-hash divergence.
//
// We test the keeper helper directly because BeginBlock's first call is
// BurnAllFromModuleName(fee_collector) which dereferences the bank keeper
// (nil in this mock setup) before reaching the recent-hashes write — so a
// full BeginBlock path would panic on the bank dereference, not on the
// behavior we want to pin.
func TestRecordRecentBlockHashFailsOnReadFailure(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()

	mk.storeService.getErrors = map[string]error{
		types.RecentBlockHashesKey: errors.New("simulated store.Get failure on recent_block_hashes"),
	}

	err := mk.RecordRecentBlockHash(ctx, "deadbeef", 10)
	require.Error(t, err, "RecordRecentBlockHash must propagate read failures")
	require.Contains(t, err.Error(), "CONSENSUS_FATAL:RECENT_HASHES_GET",
		"error must be tagged for incident triage")
}

// --- MintIfNeeded: consensus-critical reads fail fast ----------------------

// TestMintIfNeededNeverReturnsError_BelowInterval exercises the
// height < MintInterval short-circuit. With seeded default params
// (MintInterval = 200) at height 100, MintIfNeeded returns nil without
// touching bank or staking. (newMockKeeper now seeds default params, so
// this test no longer depends on the old "fall back to defaults" path.)
func TestMintIfNeededNeverReturnsError_BelowInterval(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext().WithBlockHeight(100)

	require.NotPanics(t, func() {
		require.NoError(t, mk.MintIfNeeded(ctx))
	})
}

// TestMintIfNeededNeverReturnsError_NonIntervalBoundary exercises the
// current%MintInterval != 0 short-circuit at a height past the first
// mint boundary (height 250, default interval 200 → 250%200 = 50).
func TestMintIfNeededNeverReturnsError_NonIntervalBoundary(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext().WithBlockHeight(250)

	require.NotPanics(t, func() {
		require.NoError(t, mk.MintIfNeeded(ctx))
	})
}

// TestMintIfNeededPanicsOnCorruptParams: corrupt params now halt MintIfNeeded
// (via GetParams panic). Previously this test asserted the chain stayed up
// on defaults — which is exactly the silent-divergence vector being closed.
func TestMintIfNeededPanicsOnCorruptParams(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext().WithBlockHeight(100)

	mk.storeService.store["params"] = []byte{0x00, 0xff, 0x13, 0x37}

	require.Panics(t, func() {
		_ = mk.MintIfNeeded(ctx)
	}, "MintIfNeeded must panic on corrupt params (no silent fallback)")
}

// TestMintIfNeededPanicsOnParamsStoreGetFailure: store.Get failure on the
// params key now halts MintIfNeeded.
func TestMintIfNeededPanicsOnParamsStoreGetFailure(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext().WithBlockHeight(100)

	mk.storeService.getErrors = map[string]error{
		"params": errors.New("simulated params store.Get failure"),
	}

	require.Panics(t, func() {
		_ = mk.MintIfNeeded(ctx)
	}, "MintIfNeeded must panic on store.Get failure for params")
}
