package core

import (
	"errors"
	"testing"

	"github.com/stretchr/testify/require"

	"mirage/x/core/types"
)

// These tests codify the "NEVER HALT THE CHAIN" invariant for BeginBlock,
// EndBlock, and their critical helpers (GetParams, MintIfNeeded, etc.). Any
// change to those code paths that reintroduces a non-nil return or a panic
// from an ABCI handler MUST break a test in this file.
//
// Paths that require a real bank / staking keeper (e.g. BeginBlock's
// BurnAllFromModuleName → k.bank.GetBalance, MintIfNeeded's staking iterator
// and mint/burn/send calls on a mint-interval boundary) are not exercised
// here because the shared mock wires nil concrete keepers. mintAndDistribute
// (the extracted pure-logic core of MintIfNeeded) is covered independently
// under keeper/mint_distribute_test.go using a narrow mockMintBank that
// injects mint/send/burn failures. Together the two suites cover both the
// outer short-circuit paths here and the bank-failure fan-out there.

// --- EndBlock ---------------------------------------------------------------

// TestEndBlockNeverReturnsError_EmptyState verifies the baseline: on a fresh
// store with no PoW messages, no expired nonces, and no subscriptions, the
// calm-increment path is taken and EndBlock returns nil.
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

// TestEndBlockNeverReturnsError_CorruptParams ensures that even when stored
// params are unreadable, EndBlock still returns nil. GetParams falls back to
// DefaultParams and the rest of the function proceeds on defaults.
func TestEndBlockNeverReturnsError_CorruptParams(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()
	am := newTestModule(mk)

	mk.storeService.store["params"] = []byte{0xff, 0xff, 0xff, 0xff, 0xff}

	require.NotPanics(t, func() {
		require.NoError(t, am.EndBlock(ctx))
	})
}

// TestEndBlockNeverReturnsError_OnParamsStoreGetFailure forces a store.Get
// failure on the "params" key (GetParams returns DefaultParams) and asserts
// EndBlock still returns nil.
func TestEndBlockNeverReturnsError_OnParamsStoreGetFailure(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()
	am := newTestModule(mk)

	mk.storeService.getErrors = map[string]error{
		"params": errors.New("simulated store.Get failure on params"),
	}

	require.NotPanics(t, func() {
		require.NoError(t, am.EndBlock(ctx))
	})
}

// TestEndBlockNeverReturnsError_OnSetConsecutiveLowUsageFailure forces the
// calm-increment write to fail. EndBlock logs the failure and returns nil
// (the sequence simply does not advance this block).
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
// EndBlock must still return nil.
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

// TestEndBlockNeverReturnsError_OnParamsIteratorFailure forces iterator
// errors (used by PruneExpiredNonces, GetExpiredSubscriptions,
// GetPoWMessageCount). Any iterator open failure must be logged and the
// handler must still return nil.
func TestEndBlockNeverReturnsError_OnParamsIteratorFailure(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()
	am := newTestModule(mk)

	mk.storeService.iterError = errors.New("simulated iterator failure")

	require.NotPanics(t, func() {
		require.NoError(t, am.EndBlock(ctx))
	})
}

// --- MintIfNeeded -----------------------------------------------------------

// TestMintIfNeededNeverReturnsError_BelowInterval exercises the
// height < MintInterval short-circuit. With default params (MintInterval
// = 200) at height 100, MintIfNeeded returns nil before touching bank or
// staking. Any future refactor that moves bank / staking calls above this
// gate would fail this test (nil-panic on k.bank).
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

// TestMintIfNeededNeverReturnsError_CorruptParams ensures that corrupt
// stored params do not cause MintIfNeeded to panic or return an error.
// GetParams falls back to DefaultParams (interval 200), so at height 100
// we take the below-interval short-circuit. The explicit assertion is
// that no combination of corrupt-bytes + early-exit ever surfaces an error
// from MintIfNeeded.
func TestMintIfNeededNeverReturnsError_CorruptParams(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext().WithBlockHeight(100)

	mk.storeService.store["params"] = []byte{0x00, 0xff, 0x13, 0x37}

	require.NotPanics(t, func() {
		require.NoError(t, mk.MintIfNeeded(ctx))
	})
}

// TestMintIfNeededNeverReturnsError_ParamsStoreGetFailure forces GetParams
// to go through its store.Get-error fallback and verifies MintIfNeeded
// still returns nil without panicking.
func TestMintIfNeededNeverReturnsError_ParamsStoreGetFailure(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext().WithBlockHeight(100)

	mk.storeService.getErrors = map[string]error{
		"params": errors.New("simulated params store.Get failure"),
	}

	require.NotPanics(t, func() {
		require.NoError(t, mk.MintIfNeeded(ctx))
	})
}
