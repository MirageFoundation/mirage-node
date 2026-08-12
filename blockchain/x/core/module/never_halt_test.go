package core

import (
	"errors"
	"fmt"
	"testing"

	sdk "github.com/cosmos/cosmos-sdk/types"
	"github.com/stretchr/testify/require"

	"mirage/consensusfatal"
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
//   * Consensus-critical writes (SetCurrentDifficulty, ClearPoWWindow,
//     SetConsecutiveLowUsage, CleanupOldCounters) MUST propagate their
//     failure so the block is not committed. A store failure is node-local,
//     not fleet-wide: the node that fails the write reads different
//     difficulty inputs on the next block than its peers do. This replaces
//     the earlier log-and-continue treatment of these writes (review M-5,
//     M-6, L-2, L-3).
//
//   * Expired nonce deletes also propagate. Nonce admission checks key
//     presence, so a stale key on one node changes transaction acceptance.
//
// Tests in this file pin these contracts.

// --- EndBlock: consensus-critical writes fail closed -----------------------

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

// TestEndBlockFailsClosedOnSetConsecutiveLowUsageFailure forces the
// calm-increment write to fail. The calm sequence decides when difficulty
// drops, so a node that silently skips the increment reaches the threshold on
// a different block than its peers. EndBlock must return the error.
func TestEndBlockFailsClosedOnSetConsecutiveLowUsageFailure(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()
	am := newTestModule(mk)

	mk.storeService.setErrors = map[string]error{
		"consecutive_low_usage": errors.New("simulated SetConsecutiveLowUsage failure"),
	}

	var err error
	require.NotPanics(t, func() {
		err = am.EndBlock(ctx)
	})
	require.Error(t, err,
		"calm-sequence write failure must propagate so the block is not committed")

	// Sequence must NOT have advanced because the Set failed.
	require.Equal(t, uint64(0), mk.GetConsecutiveLowUsage(ctx),
		"SetConsecutiveLowUsage failure must not be masked by a silent write")
}

// TestEndBlockFailsClosedOnSetCurrentDifficultyFailureCalmDecrease forces the
// calm-decrease branch: start at difficulty 3, seed a calm sequence >=
// threshold, and inject a Set failure on "current_difficulty". Difficulty is
// read by the PoW ante on every transaction, so the failure must propagate
// rather than leave this node admitting work at a stale difficulty.
func TestEndBlockFailsClosedOnSetCurrentDifficultyFailureCalmDecrease(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()
	am := newTestModule(mk)

	require.NoError(t, mk.SetCurrentDifficulty(ctx, 3))

	params := types.DefaultParams()
	require.NoError(t, mk.SetConsecutiveLowUsage(ctx, params.PowCalmSequenceThreshold))

	mk.storeService.setErrors = map[string]error{
		"current_difficulty": errors.New("simulated SetCurrentDifficulty failure on calm decrease"),
	}

	var err error
	require.NotPanics(t, func() {
		err = am.EndBlock(ctx)
	})
	require.Error(t, err,
		"difficulty write failure must propagate so the block is not committed")

	require.Equal(t, uint64(3), mk.GetCurrentDifficulty(ctx),
		"failed SetCurrentDifficulty must leave the difficulty unchanged")
}

// TestProcessSubscriptionsPropagatesIteratorFailure: an
// iterator-open failure on the subscriptions prefix is itself evidence of
// per-node store divergence (deterministic data should iterate identically
// on all nodes). The error must propagate rather than silently skipping
// renewals and expiries on this node only.
func TestProcessSubscriptionsPropagatesIteratorFailure(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()
	am := newTestModule(mk)

	mk.storeService.iterError = errors.New("simulated iterator failure")

	require.NotPanics(t, func() {
		err := am.processSubscriptions(ctx, types.DefaultParams())
		require.Error(t, err, "iterator failure must propagate so the chain halts (auto-recovery state-syncs)")
	})
}

// --- EndBlock / BeginBlock: consensus-critical decode failures fail fast ---

// TestEndBlockPanicsOnCorruptParams: corrupt stored params bytes MUST halt
// the chain. The prior behavior (silently fall back to DefaultParams) caused
// per-node app-hash divergence whenever one node's params bytes diverged
// from peers'.
func TestEndBlockPanicsOnCorruptParams(t *testing.T) {
	defer consensusfatal.SetHaltForTest(func(err error) { panic(err) })()

	mk := newMockKeeper()
	ctx := newMockContext()
	am := newTestModule(mk)

	mk.storeService.store["params"] = []byte{0xff, 0xff, 0xff, 0xff, 0xff}

	require.Panics(t, func() {
		_ = am.EndBlock(ctx)
	}, "EndBlock must halt on corrupt params (no silent fallback to defaults)")
}

// TestEndBlockPanicsOnParamsStoreGetFailure: a raw store.Get failure on the
// "params" key MUST halt the chain. Silently returning defaults on the
// affected node only would diverge it from peers.
func TestEndBlockPanicsOnParamsStoreGetFailure(t *testing.T) {
	defer consensusfatal.SetHaltForTest(func(err error) { panic(err) })()

	mk := newMockKeeper()
	ctx := newMockContext()
	am := newTestModule(mk)

	mk.storeService.getErrors = map[string]error{
		"params": errors.New("simulated store.Get failure on params"),
	}

	require.Panics(t, func() {
		_ = am.EndBlock(ctx)
	}, "EndBlock must halt on store.Get failure for params")
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
	defer consensusfatal.SetHaltForTest(func(err error) { panic(err) })()

	mk := newMockKeeper()
	ctx := newMockContext().WithBlockHeight(100)

	mk.storeService.store["params"] = []byte{0x00, 0xff, 0x13, 0x37}

	require.Panics(t, func() {
		_ = mk.MintIfNeeded(ctx)
	}, "MintIfNeeded must halt on corrupt params (no silent fallback)")
}

// TestMintIfNeededPanicsOnParamsStoreGetFailure: store.Get failure on the
// params key now halts MintIfNeeded.
func TestMintIfNeededPanicsOnParamsStoreGetFailure(t *testing.T) {
	defer consensusfatal.SetHaltForTest(func(err error) { panic(err) })()

	mk := newMockKeeper()
	ctx := newMockContext().WithBlockHeight(100)

	mk.storeService.getErrors = map[string]error{
		"params": errors.New("simulated params store.Get failure"),
	}

	require.Panics(t, func() {
		_ = mk.MintIfNeeded(ctx)
	}, "MintIfNeeded must halt on store.Get failure for params")
}

// --- Difficulty / PoW-count / nonce reads: fail fast on store.Get error ----

// requirePanicContains asserts fn panics and the recovered value's string form
// contains substr. We can't use require.PanicsWithError because the tagged
// messages embed runtime context (height, wrapped err) that we don't want to
// pin verbatim — a substring match on the CONSENSUS_FATAL tag is the stable
// contract.
func requirePanicContains(t *testing.T, substr string, fn func()) {
	t.Helper()
	defer consensusfatal.SetHaltForTest(func(err error) { panic(err) })()
	defer func() {
		r := recover()
		require.NotNil(t, r, "expected panic containing %q, got none", substr)
		require.Contains(t, fmt.Sprint(r), substr)
	}()
	fn()
}

// TestConsensusReadsPanicOnStoreGetFailure pins the fail-fast contract for the
// difficulty / PoW-count / envelope-nonce read family. Each of these reads
// feeds a consensus decision — the PoW tx-acceptance threshold (ante) or the
// difficulty the chain writes in EndBlock — so a swallowed store.Get error that
// returns a default/false on ONE node silently forks its app hash from peers'.
// That is the mirage.talk divergence class. A raw store.Get failure must now
// halt loudly (recoverable via the divergence watchdog) instead.
//
// These panics fire ONLY on a store.Get *error*, never on a legitimately absent
// key: the "absent key -> default" behavior is unchanged and is exercised by the
// rest of the suite (newMockKeeper seeds no difficulty/nonce, yet those reads
// resolve to their defaults without panicking).
func TestConsensusReadsPanicOnStoreGetFailure(t *testing.T) {
	defer consensusfatal.SetHaltForTest(func(err error) { panic(err) })()

	// ctx height is 100; powMessageCountKey(100) is the last (always in-window)
	// iteration of the sliding-window sum, so failing it always triggers.
	const powKey = "pow_msg_count:100"
	// Matches keeper: fmt.Sprintf("%s%x/%d", EnvelopeNoncePrefix, []byte{0xab,0xcd}, 7).
	const nonceKey = "envelope_nonce/abcd/7"

	cases := []struct {
		name    string
		failKey string
		tag     string
		invoke  func(mk *mockKeeper, ctx sdk.Context)
	}{
		{"GetCurrentDifficulty", "current_difficulty", "CONSENSUS_FATAL:DIFFICULTY_STORE_GET",
			func(mk *mockKeeper, ctx sdk.Context) { _ = mk.GetCurrentDifficulty(ctx) }},
		{"HasCurrentDifficulty", "current_difficulty", "CONSENSUS_FATAL:DIFFICULTY_STORE_GET",
			func(mk *mockKeeper, ctx sdk.Context) { _ = mk.HasCurrentDifficulty(ctx) }},
		{"GetPreviousDifficulty", "prev_difficulty", "CONSENSUS_FATAL:PREV_DIFFICULTY_STORE_GET",
			func(mk *mockKeeper, ctx sdk.Context) { _ = mk.GetPreviousDifficulty(ctx) }},
		{"GetLastDifficultyChangeHeight", "last_diff_change_height", "CONSENSUS_FATAL:LAST_DIFF_CHANGE_STORE_GET",
			func(mk *mockKeeper, ctx sdk.Context) { _ = mk.GetLastDifficultyChangeHeight(ctx) }},
		{"GetConsecutiveLowUsage", "consecutive_low_usage", "CONSENSUS_FATAL:CONSECUTIVE_LOW_USAGE_STORE_GET",
			func(mk *mockKeeper, ctx sdk.Context) { _ = mk.GetConsecutiveLowUsage(ctx) }},
		{"GetPoWMessageCount", powKey, "CONSENSUS_FATAL:POW_COUNT_STORE_GET",
			func(mk *mockKeeper, ctx sdk.Context) { _ = mk.GetPoWMessageCount(ctx, types.DefaultParams()) }},
		{"RecordPoWMessage", powKey, "CONSENSUS_FATAL:POW_COUNT_STORE_GET",
			func(mk *mockKeeper, ctx sdk.Context) { _ = mk.RecordPoWMessage(ctx) }},
		{"HasEnvelopeNonce", nonceKey, "CONSENSUS_FATAL:ENVELOPE_NONCE_STORE_HAS",
			func(mk *mockKeeper, ctx sdk.Context) { _ = mk.HasEnvelopeNonce(ctx, []byte{0xab, 0xcd}, 7) }},
		{"GetRelayCredit", "relay_credits/miragevaloper1test", "CONSENSUS_FATAL:RELAY_CREDIT_STORE_GET",
			func(mk *mockKeeper, ctx sdk.Context) { _ = mk.GetRelayCredit(ctx, "miragevaloper1test") }},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			mk := newMockKeeper()
			ctx := newMockContext()
			mk.storeService.getErrors = map[string]error{
				tc.failKey: errors.New("simulated store.Get failure"),
			}
			requirePanicContains(t, tc.tag, func() { tc.invoke(mk, ctx) })
		})
	}
}

// TestGetRelayCreditPanicsOnDecodeFailure pins M-3: corrupt credit bytes must
// halt with RELAY_CREDIT_DECODE rather than silently returning zero.
func TestGetRelayCreditPanicsOnDecodeFailure(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()
	mk.storeService.store["relay_credits/miragevaloper1test"] = []byte{0x01, 0x02, 0x03} // not 8 bytes
	requirePanicContains(t, "CONSENSUS_FATAL:RELAY_CREDIT_DECODE", func() {
		_ = mk.GetRelayCredit(ctx, "miragevaloper1test")
	})
}

func TestPoWMessageCountPanicsOnDecodeFailure(t *testing.T) {
	for _, bz := range [][]byte{{0x01}, make([]byte, 9)} {
		t.Run(fmt.Sprintf("bytes_%d", len(bz)), func(t *testing.T) {
			mk := newMockKeeper()
			ctx := newMockContext()
			mk.storeService.store["pow_msg_count:100"] = bz

			requirePanicContains(t, "CONSENSUS_FATAL:POW_COUNT_DECODE", func() {
				_ = mk.GetPoWMessageCount(ctx, types.DefaultParams())
			})
			requirePanicContains(t, "CONSENSUS_FATAL:POW_COUNT_DECODE", func() {
				_ = mk.RecordPoWMessage(ctx)
			})
		})
	}
}

func TestDifficultyStatePanicsOnDecodeFailure(t *testing.T) {
	cases := []struct {
		key    string
		tag    string
		invoke func(*mockKeeper, sdk.Context)
	}{
		{"current_difficulty", "CONSENSUS_FATAL:DIFFICULTY_DECODE",
			func(mk *mockKeeper, ctx sdk.Context) { _ = mk.GetCurrentDifficulty(ctx) }},
		{"prev_difficulty", "CONSENSUS_FATAL:PREV_DIFFICULTY_DECODE",
			func(mk *mockKeeper, ctx sdk.Context) { _ = mk.GetPreviousDifficulty(ctx) }},
		{"last_diff_change_height", "CONSENSUS_FATAL:LAST_DIFF_CHANGE_DECODE",
			func(mk *mockKeeper, ctx sdk.Context) { _ = mk.GetLastDifficultyChangeHeight(ctx) }},
		{"consecutive_low_usage", "CONSENSUS_FATAL:CONSECUTIVE_LOW_USAGE_DECODE",
			func(mk *mockKeeper, ctx sdk.Context) { _ = mk.GetConsecutiveLowUsage(ctx) }},
	}

	for _, tc := range cases {
		t.Run(tc.key, func(t *testing.T) {
			mk := newMockKeeper()
			ctx := newMockContext()
			mk.storeService.store[tc.key] = []byte{1}
			requirePanicContains(t, tc.tag, func() { tc.invoke(mk, ctx) })
		})
	}
}

// TestConsensusReadsReturnDefaultsOnAbsentKey is the companion guard: with NO
// store errors injected and the keys simply absent, the same reads must NOT
// panic and must return their documented defaults. This pins that the fail-fast
// change is narrowly scoped to store.Get *errors* and did not regress the
// legitimate empty-store path.
func TestConsensusReadsReturnDefaultsOnAbsentKey(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()

	require.NotPanics(t, func() {
		require.Equal(t, uint64(0), mk.GetCurrentDifficulty(ctx), "absent difficulty -> base (0)")
		require.False(t, mk.HasCurrentDifficulty(ctx), "absent difficulty -> Has=false")
		require.Equal(t, uint64(0), mk.GetPreviousDifficulty(ctx), "absent prev -> current (base 0)")
		require.Equal(t, int64(0), mk.GetLastDifficultyChangeHeight(ctx), "absent change height -> 0")
		require.Equal(t, uint64(0), mk.GetConsecutiveLowUsage(ctx), "absent calm seq -> 0")
		require.Equal(t, uint64(0), mk.GetPoWMessageCount(ctx, types.DefaultParams()), "no messages -> 0")
		require.False(t, mk.HasEnvelopeNonce(ctx, []byte{0xab, 0xcd}, 7), "absent nonce -> not seen")
		require.True(t, mk.GetRelayCredit(ctx, "miragevaloper1absent").IsZero(), "absent relay credit -> 0")
	})
}
