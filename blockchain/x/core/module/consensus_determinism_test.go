package core

import (
	"encoding/json"
	"testing"
	"time"

	storetypes "github.com/cosmos/cosmos-sdk/store/v2/types"
	sdk "github.com/cosmos/cosmos-sdk/types"
	"github.com/stretchr/testify/require"

	"mirage/x/core/types"
)

// CONSENSUS DETERMINISM HARDENING regression tests.
//
// Each test pins a behavior that, if regressed, would re-introduce a
// silent-divergence vector. The original mirage.talk incident (jailed at
// height 4,349,996) was caused by exactly this class of bug: one node
// silently routed a paid-tier user through the free-tier path because it
// could not decode their profile bytes, while peers (with intact bytes)
// charged the gas fee correctly. The resulting state divergence flipped
// the app-hash on the next consensus round.

// --- deductRelayGasFee fail-fast on profile decode ------------------------

// TestDeductRelayGasFeeFailsFastOnCorruptProfile: a paid user (level >= 1)
// whose stored ProfileCore bytes do not unmarshal MUST cause
// deductRelayGasFee to return a tagged CONSENSUS_FATAL error. The previous
// behavior — log and return nil — silently skipped the fee deduction on
// the affected node only, leaving its reserve and supply state diverged
// from peers.
func TestDeductRelayGasFeeFailsFastOnCorruptProfile(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()
	am := newTestModule(mk)

	owner := testAccAddressString()
	require.NoError(t, mk.SetProfileCore(ctx, owner, []byte{0xff, 0x00, 0xff, 0x00}),
		"seed corrupt profile bytes")

	err := am.deductRelayGasFee(ctx, owner, 1, 100, "regression-test")
	require.Error(t, err, "corrupt profile must surface error, not silently skip fee")
	require.Contains(t, err.Error(), "CONSENSUS_FATAL:PROFILE_DECODE",
		"error must be tagged for incident triage")
}

// TestDeductRelayGasFeeFailsFastOnMissingProfile: a paid user with no
// profile in the store at all is a state inconsistency (the level argument
// claims paid tier; the store says no such user). Returning nil silently
// would let this node skip a fee that peers correctly charge — divergence.
func TestDeductRelayGasFeeFailsFastOnMissingProfile(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()
	am := newTestModule(mk)

	owner := testAccAddressString()

	err := am.deductRelayGasFee(ctx, owner, 1, 100, "regression-test")
	require.Error(t, err, "missing profile for paid user must surface error")
	require.Contains(t, err.Error(), "CONSENSUS_FATAL:PROFILE_MISSING",
		"error must be tagged for incident triage")
}

// TestDeductRelayGasFeeNoOpForFreeTier: free-tier users (level 0) bypass the
// fee path entirely; this remains a no-op even with corrupt/missing profile
// because the function returns early before touching ProfileCore.
func TestDeductRelayGasFeeNoOpForFreeTier(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()
	am := newTestModule(mk)

	owner := testAccAddressString()
	require.NoError(t, mk.SetProfileCore(ctx, owner, []byte{0xff, 0x00, 0xff}))

	require.NoError(t, am.deductRelayGasFee(ctx, owner, 0, 100, "regression-test"),
		"free-tier short-circuit must not exercise the profile-decode path")
}

// --- processSubscriptions fail-fast on profile decode ---------------------

// TestProcessSubscriptionsFailsFastOnCorruptProfile: an expired
// subscription whose ProfileCore bytes do not unmarshal MUST cause
// processSubscriptions to return a tagged error. Silently `continue`-ing on
// this node while peers process the renewal/expiry diverges burn amounts,
// reserve balances, and emitted events.
func TestProcessSubscriptionsFailsFastOnCorruptProfile(t *testing.T) {
	mk := newMockKeeper()
	// BlockTime > expiry so GetExpiredSubscriptions returns this entry.
	ctx := newMockContext().WithBlockTime(time.Unix(2_000_000_000, 0))
	am := newTestModule(mk)

	owner := testAccAddressString()
	expiry := int64(1_000_000_000)

	require.NoError(t, mk.SetSubscription(ctx, owner, 1, expiry))
	require.NoError(t, mk.SetProfileCore(ctx, owner, []byte{0xff, 0x00, 0xff, 0x00}),
		"seed corrupt profile bytes")

	err := am.processSubscriptions(ctx, types.DefaultParams())
	require.Error(t, err, "corrupt profile during expiry must surface error, not silently continue")
	require.Contains(t, err.Error(), "CONSENSUS_FATAL:PROFILE_DECODE",
		"error must be tagged for incident triage")
}

// TestProcessSubscriptionsFailsFastOnCorruptProfileOneTimePayment: even when
// SubscriptionPeriod==0 (one-time payment, no renewal), a corrupt ProfileCore
// on an expired subscription MUST still return CONSENSUS_FATAL:PROFILE_DECODE.
// Regression for review M-7 (decode used to sit below the period==0 continue).
func TestProcessSubscriptionsFailsFastOnCorruptProfileOneTimePayment(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext().WithBlockTime(time.Unix(2_000_000_000, 0))
	am := newTestModule(mk)

	owner := testAccAddressString()
	expiry := int64(1_000_000_000)

	require.NoError(t, mk.SetSubscription(ctx, owner, 1, expiry))
	require.NoError(t, mk.SetProfileCore(ctx, owner, []byte{0xff, 0x00, 0xff, 0x00}),
		"seed corrupt profile bytes")

	params := types.DefaultParams()
	params.SubscriptionPeriod = 0

	err := am.processSubscriptions(ctx, params)
	require.Error(t, err, "corrupt profile must fail-fast even for one-time payments")
	require.Contains(t, err.Error(), "CONSENSUS_FATAL:PROFILE_DECODE",
		"error must be tagged for incident triage")
}

// TestProcessSubscriptionsFailsFastOnMissingProfile: an expired subscription
// pointing to a missing profile is a state inconsistency. Skipping the
// renewal/expiry on this node only would leave its subscription index and
// supply state diverged from peers.
func TestProcessSubscriptionsFailsFastOnMissingProfile(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext().WithBlockTime(time.Unix(2_000_000_000, 0))
	am := newTestModule(mk)

	owner := testAccAddressString()
	expiry := int64(1_000_000_000)

	require.NoError(t, mk.SetSubscription(ctx, owner, 1, expiry))

	err := am.processSubscriptions(ctx, types.DefaultParams())
	require.Error(t, err, "missing profile during expiry must surface error")
	require.Contains(t, err.Error(), "CONSENSUS_FATAL:PROFILE_MISSING",
		"error must be tagged for incident triage")
}

// TestProcessSubscriptionsNoOpWhenNoExpired: with no entries in the
// subscription index, processSubscriptions returns nil without touching
// ProfileCore. Pins the GetExpiredSubscriptions short-circuit.
func TestProcessSubscriptionsNoOpWhenNoExpired(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()
	am := newTestModule(mk)

	require.NoError(t, am.processSubscriptions(ctx, types.DefaultParams()))
}

// --- Recent-block-hashes window: deterministic, restart-equivalent --------

// TestRecordRecentBlockHashRestartEquivalence: writing N hashes then
// "restarting" by constructing a fresh keeper handle over the same store
// MUST yield an identical window. This is the regression test for the
// previous PowDecorator.recent in-memory cache, which would silently empty
// on restart and reject envelopes referencing block hashes inside the
// window — divergence vs warm peers.
func TestRecordRecentBlockHashRestartEquivalence(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()
	const window = uint32(10)

	hashes := []string{
		"aa11", "bb22", "cc33", "dd44", "ee55",
		"ff66", "0077", "1188", "2299", "33aa",
	}
	for _, h := range hashes {
		require.NoError(t, mk.RecordRecentBlockHash(ctx, h, window))
	}

	got, err := mk.GetRecentBlockHashes(ctx)
	require.NoError(t, err)
	require.Len(t, got, len(hashes), "all hashes must fit within the window")

	// Simulate process restart: same KV store, but a fresh keeper struct
	// with no in-memory caches. The window must round-trip identically.
	restartedMk := &mockKeeper{
		Keeper:          mk.Keeper,
		storeService:    mk.storeService,
		bondedValidator: mk.bondedValidator,
	}
	gotAfterRestart, err := restartedMk.GetRecentBlockHashes(ctx)
	require.NoError(t, err)
	require.Equal(t, got, gotAfterRestart,
		"window MUST be byte-identical across restarts (no in-memory cache divergence)")
}

// TestRecordRecentBlockHashTrimsToWindow: pushing N+k hashes with window=N
// MUST keep only the N most-recent entries (most-recent-first ordering).
// All peers and restarts share the same trimmed window.
func TestRecordRecentBlockHashTrimsToWindow(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()
	const window = uint32(3)

	require.NoError(t, mk.RecordRecentBlockHash(ctx, "h1", window))
	require.NoError(t, mk.RecordRecentBlockHash(ctx, "h2", window))
	require.NoError(t, mk.RecordRecentBlockHash(ctx, "h3", window))
	require.NoError(t, mk.RecordRecentBlockHash(ctx, "h4", window))
	require.NoError(t, mk.RecordRecentBlockHash(ctx, "h5", window))

	got, err := mk.GetRecentBlockHashes(ctx)
	require.NoError(t, err)
	require.Equal(t, []string{"h5", "h4", "h3"}, got,
		"only the 3 most-recent hashes are retained; ordering is most-recent-first")
}

// TestRecordRecentBlockHashIgnoresDuplicateOfNewest: pushing the same hash
// twice in a row is a no-op. This handles the case where the same context
// (e.g., during a re-sync replay) calls BeginBlock multiple times for the
// same height; the window must remain monotonic.
func TestRecordRecentBlockHashIgnoresDuplicateOfNewest(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()

	require.NoError(t, mk.RecordRecentBlockHash(ctx, "h1", 10))
	require.NoError(t, mk.RecordRecentBlockHash(ctx, "h1", 10))
	require.NoError(t, mk.RecordRecentBlockHash(ctx, "h1", 10))

	got, err := mk.GetRecentBlockHashes(ctx)
	require.NoError(t, err)
	require.Equal(t, []string{"h1"}, got, "duplicate-of-newest is a no-op")
}

// TestRecordRecentBlockHashIgnoresEmpty: at genesis there is no previous
// block; LastBlockId.Hash is empty. The recorder must skip empty inputs so
// the genesis-write path does not corrupt the window.
func TestRecordRecentBlockHashIgnoresEmpty(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()

	require.NoError(t, mk.RecordRecentBlockHash(ctx, "", 10))

	got, err := mk.GetRecentBlockHashes(ctx)
	require.NoError(t, err)
	require.Empty(t, got, "empty hash must not be recorded")
}

// TestGetRecentBlockHashesFailsFastOnCorruptBytes: bytes that fail to
// unmarshal MUST surface the error so callers can halt rather than treating
// it as an empty window (which would silently flip PoW tx acceptance on
// this node only).
func TestGetRecentBlockHashesFailsFastOnCorruptBytes(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()

	// Inject corrupt bytes for the recent-hashes key.
	mk.storeService.store[types.RecentBlockHashesKey] = []byte("not-valid-json[]]")

	got, err := mk.GetRecentBlockHashes(ctx)
	require.Error(t, err, "corrupt window bytes must surface, not be silently treated as empty")
	require.Contains(t, err.Error(), "CONSENSUS_FATAL:RECENT_HASHES_DECODE")
	require.Nil(t, got)
}

// --- Subscription expiry: well-formed profile path stays deterministic ----

// TestProcessSubscriptionsHandlesValidExpiredSubscription: the happy path
// of an expired subscription with a valid (level=0) profile remains a no-op
// for the renewal logic — tier 0 is not renewed. This pins the
// upstream-of-decode logic so changes to the fail-fast contract do not
// accidentally regress the well-formed path.
func TestProcessSubscriptionsHandlesValidExpiredSubscription(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext().WithBlockTime(time.Unix(2_000_000_000, 0)).
		WithGasMeter(storetypes.NewInfiniteGasMeter())
	am := newTestModule(mk)

	owner := testAccAddressString()
	expiry := int64(1_000_000_000)

	require.NoError(t, mk.SetSubscription(ctx, owner, 0, expiry))
	bz, err := json.Marshal(types.ProfileCore{Owner: owner, Level: 0})
	require.NoError(t, err)
	require.NoError(t, mk.SetProfileCore(ctx, owner, bz))

	require.NoError(t, am.processSubscriptions(ctx, types.DefaultParams()),
		"valid free-tier expired subscription path must be a no-op")
}

// Compile-time guard: keeps sdk imported even if a future test refactor
// removes its only direct use here.
var _ = sdk.AccAddress(nil)
