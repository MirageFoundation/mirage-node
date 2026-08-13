package app

import (
	"bytes"
	"encoding/hex"
	"fmt"
	"math/big"
	"testing"

	cosmoslog "cosmossdk.io/log/v2"
	sdkmath "cosmossdk.io/math"
	"github.com/stretchr/testify/require"

	sdk "github.com/cosmos/cosmos-sdk/types"
	stakingtypes "github.com/cosmos/cosmos-sdk/x/staking/types"
	protov2 "google.golang.org/protobuf/proto"

	coretypes "mirage/x/core/types"
	// "golang.org/x/crypto/argon2"
)

// mockHashLookup mimics the on-chain recent-block-hashes window for ante
// tests. The new validatePoWBytesArgon2 signature takes a callback
// (deterministic, state-derived); this fixture lets tests pre-seed the
// "seen" set without needing a real KV store.
type mockHashLookup struct {
	seenHashes map[string]bool
	err        error // when non-nil, simulates a state-read failure
}

func (m *mockHashLookup) lookup(hash string) (bool, error) {
	if m.err != nil {
		return false, m.err
	}
	return m.seenHashes[hash], nil
}

// TestValidatePoWBytesArgon2_RestartEquivalence pins the consensus
// determinism contract for the recent-block-hash acceptance branch:
// acceptance MUST be a pure function of (canonical bytes, header,
// on-chain window). Specifically, a "warm" node and a "freshly-restarted"
// node MUST produce the same accept/reject decision when the on-chain
// window contents are identical.
//
// Regression target: the previous PowDecorator.recent in-memory cache.
// After a process restart it was empty; envelopes referencing block hashes
// that were still inside the warm peers' window were rejected on the
// restarted node only — a per-node tx-acceptance flip and therefore an
// app-hash divergence.
func TestValidatePoWBytesArgon2_RestartEquivalence(t *testing.T) {
	canonical := []byte("canonical_bytes_for_restart_equivalence_test")
	envelopeHash, _ := hex.DecodeString("0011223344556677889900112233445566778899001122334455667788990011")
	envelopeHashHex := hex.EncodeToString(envelopeHash)
	currentLastID := "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"

	const minDiff = uint64(8)
	const step = 0.25

	findValidNonce := func(seenSet map[string]bool) uint64 {
		ring := &mockHashLookup{seenHashes: seenSet}
		var n uint64
		for n = 0; n < 100_000; n++ {
			if err := validatePoWBytesArgon2(canonical, envelopeHash, 0, n, currentLastID, ring.lookup, false, 0, 0, 0, 0, 0, minDiff, step); err == nil {
				return n
			}
		}
		t.Fatal("could not find valid PoW within 100k nonces; raise minDiff sanity")
		return 0
	}

	// Warm node: window contains the envelope's block hash.
	warm := &mockHashLookup{seenHashes: map[string]bool{envelopeHashHex: true}}
	nonce := findValidNonce(warm.seenHashes)

	// Acceptance on a warm node.
	require.NoError(t,
		validatePoWBytesArgon2(canonical, envelopeHash, 0, nonce, currentLastID, warm.lookup, false, 0, 0, 0, 0, 0, minDiff, step),
		"warm node accepts envelope referencing in-window hash")

	// Restarted node viewing the SAME on-chain window: same accept.
	restarted := &mockHashLookup{seenHashes: map[string]bool{envelopeHashHex: true}}
	require.NoError(t,
		validatePoWBytesArgon2(canonical, envelopeHash, 0, nonce, currentLastID, restarted.lookup, false, 0, 0, 0, 0, 0, minDiff, step),
		"restarted node sees same on-chain window -> same acceptance")

	// Node whose on-chain window does NOT contain the hash: same reject on
	// EVERY node (no in-memory cache to silently rescue it).
	missing := &mockHashLookup{seenHashes: map[string]bool{}}
	err := validatePoWBytesArgon2(canonical, envelopeHash, 0, nonce, currentLastID, missing.lookup, false, 0, 0, 0, 0, 0, minDiff, step)
	require.Error(t, err, "node whose on-chain window omits the hash MUST reject (no silent in-memory rescue)")
	require.Contains(t, err.Error(), "invalid last_block_hash")
}

// TestValidatePoWBytesArgon2_PropagatesLookupError: when the on-chain window
// read itself fails, validate must return a wrapped error rather than
// treating the missing window as "not seen" (which would leak a state-read
// failure as a tx-rejection on this node only -> divergence).
//
// M-1: the hash-window lookup runs BEFORE Argon2, so any nonce works here —
// we never reach the difficulty check when lookup fails.
func TestValidatePoWBytesArgon2_PropagatesLookupError(t *testing.T) {
	canonical := []byte("canonical_bytes_for_lookup_error")
	envelopeHash, _ := hex.DecodeString("0011223344556677889900112233445566778899001122334455667788990011")
	currentLastID := "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"

	const minDiff = uint64(8)
	const step = 0.25

	failing := &mockHashLookup{err: fmt.Errorf("simulated state-read failure")}
	err := validatePoWBytesArgon2(canonical, envelopeHash, 0, 0, currentLastID, failing.lookup, false, 0, 0, 0, 0, 0, minDiff, step)
	require.Error(t, err)
	require.Contains(t, err.Error(), "recent-block-hash window read failed",
		"lookup errors must be wrapped, not silently treated as 'not seen'")
}

// TestValidatePoWBytesArgon2_RejectsBadHashBeforeArgon2 documents M-1: a
// fabricated last_block_hash is rejected before Argon2id runs, so spam
// envelopes never pay the memory-hard cost.
func TestValidatePoWBytesArgon2_RejectsBadHashBeforeArgon2(t *testing.T) {
	canonical := []byte("canonical_bytes_bad_hash")
	badHash, _ := hex.DecodeString("deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef")
	currentLastID := "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
	missing := &mockHashLookup{seenHashes: map[string]bool{}}

	err := validatePoWBytesArgon2(canonical, badHash, 0, 0, currentLastID, missing.lookup, false, 0, 0, 0, 0, 0, 8, 0.25)
	require.Error(t, err)
	require.Contains(t, err.Error(), "invalid last_block_hash")
}

func TestComputeDifficultyFactor(t *testing.T) {
	// Test cases for difficulty factor calculation
	// factor = 1000 * (1 + step)^difficulty
	tests := []struct {
		name       string
		step       float64
		difficulty uint64
		want       uint64
		wantErr    bool
	}{
		{"Base difficulty (0)", 0.25, 0, 1000, false},
		{"Step 1 (0.25)", 0.25, 1, 1250, false},
		{"Step 2 (0.25)", 0.25, 2, 1563, false}, // 1000 * 1.25^2 = 1562.5 -> 1563 (round half up)
		{"Step 3 (0.25)", 0.25, 3, 1953, false}, // 1000 * 1.25^3 = 1953.125 -> 1953
		{"Step 10 (0.25)", 0.25, 10, 9313, false},
		{"Step 1 (0.10)", 0.10, 1, 1100, false},
		{"Step 1 (0.50)", 0.50, 1, 1500, false},
		{"Invalid step (0)", 0, 1, 0, true},
		{"Invalid step (negative)", -0.1, 1, 0, true},
		{"Invalid step (>1)", 1.1, 1, 0, true},
		{"Max safe difficulty", 0.25, 1000, 9007199254740991, false}, // Should cap at max safe
		{"Sparse huge exponent caps without rational growth", 0.25, 1 << 52, 9007199254740991, false},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got, err := computeDifficultyFactor(tt.step, tt.difficulty)
			if tt.wantErr {
				require.Error(t, err)
			} else {
				require.NoError(t, err)
				require.Equal(t, tt.want, got)
			}
		})
	}
}

// TestComputeDifficultyFactorDeterminismTable pins exact-rational outputs for a
// stable input table so architecture-specific float Pow cannot drift factors
// (review L-1).
func TestComputeDifficultyFactorDeterminismTable(t *testing.T) {
	table := []struct {
		step  float64
		steps uint64
		want  uint64
	}{
		{0.25, 0, 1000},
		{0.25, 1, 1250},
		{0.25, 2, 1563},
		{0.25, 3, 1953},
		{0.25, 4, 2441},
		{0.25, 5, 3052},
		{0.25, 10, 9313},
		{0.25, 20, 86736},
		{0.10, 1, 1100},
		{0.10, 2, 1210},
		{0.10, 5, 1611},
		{0.50, 1, 1500},
		{0.50, 2, 2250},
		{0.50, 3, 3375},
		{1.0, 1, 2000},
		{1.0, 2, 4000},
		{1.0, 10, 1024000},
	}
	for _, row := range table {
		got, err := computeDifficultyFactor(row.step, row.steps)
		require.NoError(t, err, "step=%v steps=%d", row.step, row.steps)
		require.Equal(t, row.want, got, "step=%v steps=%d", row.step, row.steps)
	}
}

func TestComputeTarget(t *testing.T) {
	// Test target calculation
	// target = 2^(256-minDiff) * 1000 / factor
	minDiff := uint64(10)
	step := 0.25

	// Base target for minDiff 10
	baseTarget := new(big.Int).Lsh(big.NewInt(1), 256-10)

	tests := []struct {
		name       string
		difficulty uint64
		wantFactor uint64
	}{
		{"Diff 0", 0, 1000},
		{"Diff 1", 1, 1250},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			target, err := computeTarget(minDiff, tt.difficulty, step)
			require.NoError(t, err)

			// Manually calculate expected
			expected := new(big.Int).Mul(baseTarget, big.NewInt(1000))
			expected.Div(expected, new(big.Int).SetUint64(tt.wantFactor))

			require.Equal(t, 0, target.Cmp(expected), "Target mismatch")
		})
	}
}

func TestValidatePoW(t *testing.T) {
	// Setup
	minDiff := uint64(8) // Low difficulty for testing
	step := 0.25
	lastBlockHash, _ := hex.DecodeString("0000000000000000000000000000000000000000000000000000000000000000")
	canonical := []byte("test_canonical_bytes")
	ring := &mockHashLookup{seenHashes: make(map[string]bool)}

	// Helper to find a valid nonce
	findNonce := func(diff uint64) uint64 {
		_, _ = computeTarget(minDiff, diff, step)
		var nonce uint64
		for {
			// Construct Argon2 input: canonical || ":" || uvarint(nonce)
			// This mimics the logic in validatePoWBytesArgon2
			// Note: We need to replicate the exact byte construction
			// But for this test, we can just use the validation function to check
			// Wait, to find a nonce we need to hash.
			// Let's just try a few nonces until one passes or use a known one if we can.
			// Since minDiff is small (8), it should be fast.
			if nonce > 10000 {
				t.Fatal("Could not find nonce quickly")
			}

			// We can't easily replicate the exact byte construction here without duplicating code
			// So we will rely on the fact that we are testing validatePoWBytesArgon2
			// We'll just pass nonces to it until one works? No, that's testing the test.

			// Let's use the actual hashing to find a nonce
			// Replicate byte construction from ante_pow.go
			// ...
			// Actually, let's just test the validation logic with a mocked hash check?
			// No, validatePoWBytesArgon2 does the hashing.
			// We need to generate a valid input.

			// Let's just try to find one.
			err := validatePoWBytesArgon2(canonical, lastBlockHash, diff, nonce, "", ring.lookup, true, diff, 0, 0, 0, 0, minDiff, step)
			if err == nil {
				return nonce
			}
			nonce++
		}
	}

	// 1. Valid PoW at Diff 0
	nonce0 := findNonce(0)
	err := validatePoWBytesArgon2(canonical, lastBlockHash, 0, nonce0, "", ring.lookup, true, 0, 0, 0, 0, 0, minDiff, step)
	require.NoError(t, err, "Should accept valid PoW at diff 0")

	// 2. Valid PoW at Diff 1
	nonce1 := findNonce(1)
	err = validatePoWBytesArgon2(canonical, lastBlockHash, 1, nonce1, "", ring.lookup, true, 1, 0, 0, 0, 0, minDiff, step)
	require.NoError(t, err, "Should accept valid PoW at diff 1")

	// 3. Invalid PoW (wrong nonce)
	err = validatePoWBytesArgon2(canonical, lastBlockHash, 0, nonce0+1, "", ring.lookup, true, 0, 0, 0, 0, 0, minDiff+10, step) // High minDiff to ensure failure
	require.Error(t, err, "Should reject invalid PoW")

	// 4. Replay Attack (same nonce, same block hash)
	// The ring buffer check is only done if skipHashCheck is false
	// And currentLastID matches or is in ring.
	// currentLastID := "0000000000000000000000000000000000000000000000000000000000000000"

	// Note: validatePoWBytesArgon2 doesn't update the ring, the caller does.
	// It just checks against it.
	// So we can't test "stateful" replay here, only that it checks the ring.

	// If we set the ring to have seen the hash, it should pass?
	// No, the ring stores BLOCK HASHES, not PoW nonces.
	// The replay protection for PoW is actually based on the *block hash* being recent.
	// If you reuse a PoW, you must use the same block hash.
	// If that block hash is old, it fails.
	// If it's new, it passes?
	// Wait, does the system prevent reusing the same nonce for the same block hash?
	// ante_pow.go:280: if err := d.Keeper.RecordPoWMessage(ctx); ...
	// It records the message count, but does it record the nonce?
	// Looking at ante_pow.go, there is no explicit nonce-deduplication storage.
	// The protection is:
	// 1. Salt = block hash.
	// 2. Block hash must be recent (Window).
	// 3. If you reuse nonce + block hash -> you get same hash.
	// 4. Transaction replay protection (sequence number) prevents replaying the *exact same tx*.
	// 5. If you change the tx (e.g. nonce/timestamp), the canonical bytes change -> hash changes -> PoW invalid.
	// So you can't reuse a PoW for a different message.
	// And you can't replay the same message due to account sequence.
	// So explicit nonce tracking isn't needed!

	// Test: Change canonical bytes -> PoW should fail
	canonical2 := []byte("test_canonical_bytes_2")
	err = validatePoWBytesArgon2(canonical2, lastBlockHash, 0, nonce0, "", ring.lookup, true, 0, 0, 0, 0, 0, minDiff, step)
	require.Error(t, err, "Should reject PoW if canonical bytes change")
}

// TestStalenessEnforcedFromWindowNotHeader covers the L-7 contract. Under ABCI
// 2.0 the header never carries LastBlockId, so currentLastID is empty on every
// path and acceptance has to come from the on-chain window instead. These cases
// fix the two failure modes that matter: an envelope referencing a hash outside
// the window must be refused even though the header hash is empty (the gap that
// left staleness unenforced), and an empty envelope hash must not slip through by
// comparing equal to the empty header hash.
func TestStalenessEnforcedFromWindowNotHeader(t *testing.T) {
	const minDiff, step = uint64(8), 0.25
	canonical := []byte("window_enforced_envelope")
	inWindow, err := hex.DecodeString("0011223344556677889900112233445566778899001122334455667788990011")
	require.NoError(t, err)
	outOfWindow, err := hex.DecodeString("ffee0011223344556677889900112233445566778899001122334455667788ff")
	require.NoError(t, err)

	ring := &mockHashLookup{seenHashes: map[string]bool{hex.EncodeToString(inWindow): true}}

	// Mine against the skip path so the nonce is valid for the salt, then reuse
	// it while enforcing: only the hash check differs between the assertions.
	var nonce uint64
	for ; nonce <= 10000; nonce++ {
		if validatePoWBytesArgon2(canonical, inWindow, 0, nonce, "", ring.lookup, true, 0, 0, 0, 0, 2, minDiff, step) == nil {
			break
		}
	}
	require.LessOrEqual(t, nonce, uint64(10000), "could not mine a nonce at minimum difficulty")

	require.NoError(t, validatePoWBytesArgon2(
		canonical, inWindow, 0, nonce, "", ring.lookup, false, 0, 0, 0, 0, 2, minDiff, step,
	), "a hash present in the window must be accepted with an empty header hash")

	require.ErrorContains(t, validatePoWBytesArgon2(
		canonical, outOfWindow, 0, nonce, "", ring.lookup, false, 0, 0, 0, 0, 2, minDiff, step,
	), "invalid last_block_hash", "a hash absent from the window must be refused")

	require.ErrorContains(t, validatePoWBytesArgon2(
		canonical, nil, 0, nonce, "", ring.lookup, false, 0, 0, 0, 0, 2, minDiff, step,
	), "empty", "an empty envelope hash must not match the empty header hash")
}

// TestEmptyWindowSkipsStalenessCheck pins the one case where enforcement is off:
// a window with no real hash in it, which happens on a chain's first block and on
// the v1.34.0 upgrade block that clears the stale all-empty window. Enforcing
// there would reject every transaction, which is how the first attempt at this
// guard broke the local testnet.
func TestEmptyWindowSkipsStalenessCheck(t *testing.T) {
	const minDiff, step = uint64(8), 0.25
	canonical := []byte("bootstrap_window_envelope")
	lastBlockHash, err := hex.DecodeString("0011223344556677889900112233445566778899001122334455667788990011")
	require.NoError(t, err)

	lookup := func(string) (bool, error) {
		t.Fatal("window lookup ran while the window was empty")
		return false, nil
	}

	var nonce uint64
	for ; nonce <= 10000; nonce++ {
		if validatePoWBytesArgon2(canonical, lastBlockHash, 0, nonce, "", lookup, true, 0, 0, 0, 0, 2, minDiff, step) == nil {
			break
		}
	}
	require.LessOrEqual(t, nonce, uint64(10000), "could not mine a nonce at minimum difficulty")

	require.NoError(t, validatePoWBytesArgon2(
		canonical, lastBlockHash, 0, nonce, "", lookup, true, 0, 0, 0, 0, 2, minDiff, step,
	), "an empty window must skip the staleness check, not reject the envelope")
}

// BenchmarkValidatePoWBytesArgon2 records the per-envelope cost of the
// memory-hard verification every PoW-routed relay message pays in both CheckTx
// and DeliverTx (MsgSubscribe and MsgSetAutoRenewal pay tokens/reserve instead). Report allocations and compare against the baseline recorded in
// the release retest rather than asserting a wall-clock threshold here: CI
// machines vary too much for a time assertion to mean anything.
func BenchmarkValidatePoWBytesArgon2(b *testing.B) {
	canonical := bytes.Repeat([]byte("canonical_envelope_bytes"), 8)
	lastBlockHash, err := hex.DecodeString("0011223344556677889900112233445566778899001122334455667788990011")
	require.NoError(b, err)
	lastID := hex.EncodeToString(lastBlockHash)
	ring := &mockHashLookup{seenHashes: map[string]bool{lastID: true}}

	b.ReportAllocs()
	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		// Difficulty 0 with a fixed nonce: the benchmark measures one Argon2id
		// verification, not the search for a passing nonce.
		_ = validatePoWBytesArgon2(canonical, lastBlockHash, 0, uint64(i), lastID, ring.lookup, false, 0, 0, 0, 0, 0, 8, 0.25)
	}
}

type mockTx struct {
	msgs []sdk.Msg
}

func (m mockTx) GetMsgs() []sdk.Msg                    { return m.msgs }
func (m mockTx) GetMsgsV2() ([]protov2.Message, error) { return nil, nil }
func (m mockTx) ValidateBasic() error                  { return nil }

func TestDisableDelegatorStakingDecorator(t *testing.T) {
	decorator := DisableDelegatorStakingDecorator{}
	next := func(ctx sdk.Context, tx sdk.Tx, simulate bool) (sdk.Context, error) {
		return ctx, nil
	}

	addr := sdk.AccAddress(bytes.Repeat([]byte{0x1}, 20))
	valAddr := sdk.ValAddress(addr)

	selfDelegate := &stakingtypes.MsgDelegate{
		DelegatorAddress: addr.String(),
		ValidatorAddress: valAddr.String(),
		Amount:           sdk.NewCoin("umirage", sdkmath.NewInt(1)),
	}
	_, err := decorator.AnteHandle(sdk.Context{}, mockTx{msgs: []sdk.Msg{selfDelegate}}, false, next)
	require.NoError(t, err)

	otherAddr := sdk.AccAddress(bytes.Repeat([]byte{0x2}, 20))
	thirdParty := &stakingtypes.MsgDelegate{
		DelegatorAddress: otherAddr.String(),
		ValidatorAddress: valAddr.String(),
		Amount:           sdk.NewCoin("umirage", sdkmath.NewInt(1)),
	}
	_, err = decorator.AnteHandle(sdk.Context{}, mockTx{msgs: []sdk.Msg{thirdParty}}, false, next)
	require.ErrorIs(t, err, ErrDelegationDisabled)

	redelegate := &stakingtypes.MsgBeginRedelegate{
		DelegatorAddress:    addr.String(),
		ValidatorSrcAddress: valAddr.String(),
		ValidatorDstAddress: valAddr.String(),
		Amount:              sdk.NewCoin("umirage", sdkmath.NewInt(1)),
	}
	_, err = decorator.AnteHandle(sdk.Context{}, mockTx{msgs: []sdk.Msg{redelegate}}, false, next)
	require.ErrorIs(t, err, ErrDelegationDisabled)

	// Self-cancel of an unbond by the validator's own account: allowed.
	selfCancelUnbond := &stakingtypes.MsgCancelUnbondingDelegation{
		DelegatorAddress: addr.String(),
		ValidatorAddress: valAddr.String(),
		Amount:           sdk.NewCoin("umirage", sdkmath.NewInt(1)),
		CreationHeight:   1,
	}
	_, err = decorator.AnteHandle(sdk.Context{}, mockTx{msgs: []sdk.Msg{selfCancelUnbond}}, false, next)
	require.NoError(t, err)

	// Third-party cancel of an unbond: rejected. Without this case the
	// decorator would previously let a non-self delegator cancel an unbond
	// despite delegation being disabled.
	thirdPartyCancelUnbond := &stakingtypes.MsgCancelUnbondingDelegation{
		DelegatorAddress: otherAddr.String(),
		ValidatorAddress: valAddr.String(),
		Amount:           sdk.NewCoin("umirage", sdkmath.NewInt(1)),
		CreationHeight:   1,
	}
	_, err = decorator.AnteHandle(sdk.Context{}, mockTx{msgs: []sdk.Msg{thirdPartyCancelUnbond}}, false, next)
	require.ErrorIs(t, err, ErrDelegationDisabled)

	// The shared rejection helper is used by the app's global ante router and
	// must enforce the same policy even outside this decorator.
	require.NoError(t, rejectDelegatorStakingMsgs(mockTx{msgs: []sdk.Msg{selfCancelUnbond}}))
	require.ErrorIs(t, rejectDelegatorStakingMsgs(mockTx{msgs: []sdk.Msg{thirdPartyCancelUnbond}}), ErrDelegationDisabled)
}

// TestMirageAnteRouterRejectsThirdPartyStakingBeforeRouting verifies that the
// top-level ante router installed on baseapp applies the staking-disable
// policy to BOTH the stdAnte and relayAnte paths. The historical bug this
// test pins: a pure non-relay MsgCancelUnbondingDelegation was classified as
// non-relay and routed to stdAnte, which did NOT include
// DisableDelegatorStakingDecorator, so a third-party cancel bypassed the rule
// entirely. The fix moves rejectDelegatorStakingMsgs to the front of the
// router so neither downstream ante chain is reached.
func TestMirageAnteRouterRejectsThirdPartyStakingBeforeRouting(t *testing.T) {
	ctx := sdk.Context{}.
		WithExecMode(sdk.ExecModeCheck).
		WithLogger(cosmoslog.NewNopLogger())

	addr := sdk.AccAddress(bytes.Repeat([]byte{0x1}, 20))
	otherAddr := sdk.AccAddress(bytes.Repeat([]byte{0x2}, 20))
	valAddr := sdk.ValAddress(addr)

	// Instrumented downstream handlers. If either is invoked, the ordering
	// guarantee of the router is broken.
	var stdCalled, relayCalled bool
	stdAnte := func(c sdk.Context, _ sdk.Tx, _ bool) (sdk.Context, error) {
		stdCalled = true
		return c, nil
	}
	relayAnte := func(c sdk.Context, _ sdk.Tx, _ bool) (sdk.Context, error) {
		relayCalled = true
		return c, nil
	}
	govDec := GovAuthorityDecorator{}

	thirdPartyCancelUnbond := &stakingtypes.MsgCancelUnbondingDelegation{
		DelegatorAddress: otherAddr.String(),
		ValidatorAddress: valAddr.String(),
		Amount:           sdk.NewCoin("umirage", sdkmath.NewInt(1)),
		CreationHeight:   1,
	}

	_, err := mirageAnteRouter(
		ctx,
		mockTx{msgs: []sdk.Msg{thirdPartyCancelUnbond}},
		false,
		govDec,
		stdAnte,
		relayAnte,
	)
	require.ErrorIs(t, err, ErrDelegationDisabled,
		"third-party MsgCancelUnbondingDelegation must be rejected at the top-level router")
	require.False(t, stdCalled, "stdAnte must NOT be reached when staking-disable rejects the tx")
	require.False(t, relayCalled, "relayAnte must NOT be reached when staking-disable rejects the tx")

	// Sanity check: a self-cancel (validator's own address) passes the staking
	// filter and reaches the downstream chain (stdAnte for non-relay msgs).
	stdCalled, relayCalled = false, false
	selfCancelUnbond := &stakingtypes.MsgCancelUnbondingDelegation{
		DelegatorAddress: addr.String(),
		ValidatorAddress: valAddr.String(),
		Amount:           sdk.NewCoin("umirage", sdkmath.NewInt(1)),
		CreationHeight:   1,
	}
	_, err = mirageAnteRouter(
		ctx,
		mockTx{msgs: []sdk.Msg{selfCancelUnbond}},
		false,
		govDec,
		stdAnte,
		relayAnte,
	)
	require.NoError(t, err, "self-cancel must not be rejected by staking-disable")
	require.True(t, stdCalled, "self-cancel (non-relay) must route to stdAnte")
	require.False(t, relayCalled, "self-cancel must not hit relayAnte")

	// Symmetric check for the three pre-existing staking messages: verifying
	// the router now catches them too even when submitted as pure non-relay
	// CLI txs.
	for _, tc := range []struct {
		name string
		msg  sdk.Msg
	}{
		{"MsgDelegate third-party", &stakingtypes.MsgDelegate{
			DelegatorAddress: otherAddr.String(),
			ValidatorAddress: valAddr.String(),
			Amount:           sdk.NewCoin("umirage", sdkmath.NewInt(1)),
		}},
		{"MsgUndelegate third-party", &stakingtypes.MsgUndelegate{
			DelegatorAddress: otherAddr.String(),
			ValidatorAddress: valAddr.String(),
			Amount:           sdk.NewCoin("umirage", sdkmath.NewInt(1)),
		}},
		{"MsgBeginRedelegate any", &stakingtypes.MsgBeginRedelegate{
			DelegatorAddress:    addr.String(),
			ValidatorSrcAddress: valAddr.String(),
			ValidatorDstAddress: valAddr.String(),
			Amount:              sdk.NewCoin("umirage", sdkmath.NewInt(1)),
		}},
	} {
		t.Run(tc.name, func(t *testing.T) {
			stdCalled, relayCalled = false, false
			_, err := mirageAnteRouter(
				ctx,
				mockTx{msgs: []sdk.Msg{tc.msg}},
				false,
				govDec,
				stdAnte,
				relayAnte,
			)
			require.ErrorIs(t, err, ErrDelegationDisabled)
			require.False(t, stdCalled)
			require.False(t, relayCalled)
		})
	}
}

func TestBuildCanonForBlockTopic(t *testing.T) {
	pub := bytes.Repeat([]byte{0x01}, 33)
	blockHash := []byte("blockhash")
	difficulty := uint64(7)
	timestamp := uint64(1710005556667)
	target := ""
	topic := "topicx"

	msg := &coretypes.MsgBlockTopic{
		EnvelopePubkey:     pub,
		EnvelopeBlockHash:  blockHash,
		EnvelopeDifficulty: difficulty,
		EnvelopeTimestamp:  timestamp,
		Target:             target,
		Topic:              topic,
	}

	expected := newCanonWriter("MsgBlockTopic")
	expected.writeBytes(2, pub)
	expected.writeBytes(3, blockHash)
	expected.writeUvarint(4, difficulty)
	expected.writeUvarint(6, timestamp)
	expected.writeUvarint(7, msg.EnvelopeNonce)
	expected.writeString(100, target)
	expected.writeString(101, topic)

	got := buildCanonForBlockTopic(msg)
	t.Logf("[debug] block_topic canon len=%d", len(got))
	require.Equal(t, expected.buf, got)
}

func TestBuildCanonForAward(t *testing.T) {
	pub := bytes.Repeat([]byte{0x03}, 33)
	blockHash := []byte("blockhash3")
	difficulty := uint64(5)
	timestamp := uint64(1710009990001)
	target := "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
	awardType := "quality_post"

	msg := &coretypes.MsgAward{
		EnvelopePubkey:     pub,
		EnvelopeBlockHash:  blockHash,
		EnvelopeDifficulty: difficulty,
		EnvelopeTimestamp:  timestamp,
		Target:             target,
		AwardType:          awardType,
	}

	expected := newCanonWriter("MsgAward")
	expected.writeBytes(2, pub)
	expected.writeBytes(3, blockHash)
	expected.writeUvarint(4, difficulty)
	expected.writeUvarint(6, timestamp)
	expected.writeUvarint(7, msg.EnvelopeNonce)
	expected.writeString(100, target)
	expected.writeString(101, awardType)

	got := buildCanonForAward(msg)
	t.Logf("[debug] award canon len=%d type=%s", len(got), awardType)
	require.Equal(t, expected.buf, got)
}

func TestBuildCanonForUnblockTopic(t *testing.T) {
	pub := bytes.Repeat([]byte{0x02}, 33)
	blockHash := []byte("blockhash2")
	difficulty := uint64(4)
	timestamp := uint64(1710007778889)
	target := ""
	topic := "topicy"

	msg := &coretypes.MsgUnblockTopic{
		EnvelopePubkey:     pub,
		EnvelopeBlockHash:  blockHash,
		EnvelopeDifficulty: difficulty,
		EnvelopeTimestamp:  timestamp,
		Target:             target,
		Topic:              topic,
	}

	expected := newCanonWriter("MsgUnblockTopic")
	expected.writeBytes(2, pub)
	expected.writeBytes(3, blockHash)
	expected.writeUvarint(4, difficulty)
	expected.writeUvarint(6, timestamp)
	expected.writeUvarint(7, msg.EnvelopeNonce)
	expected.writeString(100, target)
	expected.writeString(101, topic)

	got := buildCanonForUnblockTopic(msg)
	t.Logf("[debug] unblock_topic canon len=%d", len(got))
	require.Equal(t, expected.buf, got)
}
