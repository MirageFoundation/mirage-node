package core

import (
	"encoding/binary"
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"strings"
	"testing"
	"time"

	sdkmath "cosmossdk.io/math"
	sdk "github.com/cosmos/cosmos-sdk/types"
	sdkerrors "github.com/cosmos/cosmos-sdk/types/errors"
	authtypes "github.com/cosmos/cosmos-sdk/x/auth/types"
	"github.com/stretchr/testify/require"

	"mirage/consensusfatal"
	"mirage/x/core/keeper"
	"mirage/x/core/types"
)

// Injected store-failure coverage for the fail-fast contract on consensus
// writes and reads (review M-2, M-3, M-5, M-6, L-1, L-2, L-3, L-8, L-10). Every
// ordinary-mode tests pin error propagation and Finalize-mode tests pin process
// termination, so a faulty validator cannot reject a transaction that healthy
// peers commit.

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

func TestRecordPoWMessageFailsOnCounterOverflow(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext().WithBlockHeight(100)
	bz := make([]byte, 8)
	binary.BigEndian.PutUint64(bz, math.MaxUint64)
	mk.storeService.store[powCounterKey(100)] = bz

	requirePanicContains(t, "CONSENSUS_FATAL:POW_COUNT_OVERFLOW", func() {
		_ = mk.RecordPoWMessage(ctx)
	})
}

func TestGetPoWMessageCountFailsOnWindowSumOverflow(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext().WithBlockHeight(100)
	maxBz := make([]byte, 8)
	binary.BigEndian.PutUint64(maxBz, math.MaxUint64)
	oneBz := make([]byte, 8)
	binary.BigEndian.PutUint64(oneBz, 1)
	mk.storeService.store[powCounterKey(99)] = maxBz
	mk.storeService.store[powCounterKey(100)] = oneBz

	requirePanicContains(t, "CONSENSUS_FATAL:POW_COUNT_OVERFLOW", func() {
		_ = mk.GetPoWMessageCount(ctx, types.DefaultParams())
	})
}

// --- M-2: count and sequence reads ------------------------------------------

func listCountKey(prefix, owner string) string {
	return prefix + owner + types.SetCountSuffix
}

func listSeqKey(prefix, owner string) string {
	return prefix + owner + types.DequeSeqSuffix
}

func listCountBytes(v uint32) []byte {
	bz := make([]byte, 4)
	binary.BigEndian.PutUint32(bz, v)
	return bz
}

// TestListCountReadFailurePropagates covers every list family. A failed count
// read used to decode as zero, which rewrote a real counter from scratch and
// admitted entries past the tier cap on the failing node only (review M-2).
func TestListCountReadFailurePropagates(t *testing.T) {
	owner := testAccAddressString()

	cases := map[string]struct {
		prefix string
		add    func(mk *mockKeeper, ctx sdk.Context) error
	}{
		"followed_users": {types.FollowedUsersPrefix, func(mk *mockKeeper, ctx sdk.Context) error {
			_, err := mk.AddFollowedUser(ctx, owner, "target")
			return err
		}},
		"followed_topics": {types.FollowedTopicsPrefix, func(mk *mockKeeper, ctx sdk.Context) error {
			_, err := mk.AddFollowedTopic(ctx, owner, "topic")
			return err
		}},
		"enabled_agents": {types.EnabledAgentsPrefix, func(mk *mockKeeper, ctx sdk.Context) error {
			_, err := mk.AddEnabledAgent(ctx, owner, "agent")
			return err
		}},
		"blocked_users": {types.BlockedUsersPrefix, func(mk *mockKeeper, ctx sdk.Context) error {
			_, err := mk.AddBlockedUserDeque(ctx, owner, "target", 100)
			return err
		}},
		"blocked_posts": {types.BlockedPostsPrefix, func(mk *mockKeeper, ctx sdk.Context) error {
			_, err := mk.AddBlockedPostDeque(ctx, owner, "abcd", 100)
			return err
		}},
		"blocked_topics": {types.BlockedTopicsPrefix, func(mk *mockKeeper, ctx sdk.Context) error {
			_, err := mk.AddBlockedTopicDeque(ctx, owner, "topic", 100)
			return err
		}},
	}

	for name, tc := range cases {
		t.Run(name, func(t *testing.T) {
			mk := newMockKeeper()
			ctx := newMockContext()
			mk.storeService.getErrors = map[string]error{
				listCountKey(tc.prefix, owner): errors.New("simulated count read failure"),
			}

			require.Error(t, tc.add(mk, ctx),
				"a failed count read must not be decoded as zero")
		})
	}
}

// TestListSequenceReadFailurePropagates covers the ordered and deque families,
// where a failed sequence read would reuse positions and evict a different
// entry than peers do.
func TestListSequenceReadFailurePropagates(t *testing.T) {
	owner := testAccAddressString()

	cases := map[string]struct {
		prefix string
		add    func(mk *mockKeeper, ctx sdk.Context) error
	}{
		"enabled_agents": {types.EnabledAgentsPrefix, func(mk *mockKeeper, ctx sdk.Context) error {
			_, err := mk.AddEnabledAgent(ctx, owner, "agent")
			return err
		}},
		"blocked_users": {types.BlockedUsersPrefix, func(mk *mockKeeper, ctx sdk.Context) error {
			_, err := mk.AddBlockedUserDeque(ctx, owner, "target", 100)
			return err
		}},
		"blocked_posts": {types.BlockedPostsPrefix, func(mk *mockKeeper, ctx sdk.Context) error {
			_, err := mk.AddBlockedPostDeque(ctx, owner, "abcd", 100)
			return err
		}},
		"blocked_topics": {types.BlockedTopicsPrefix, func(mk *mockKeeper, ctx sdk.Context) error {
			_, err := mk.AddBlockedTopicDeque(ctx, owner, "topic", 100)
			return err
		}},
	}

	for name, tc := range cases {
		t.Run(name, func(t *testing.T) {
			mk := newMockKeeper()
			ctx := newMockContext()
			mk.storeService.getErrors = map[string]error{
				listSeqKey(tc.prefix, owner): errors.New("simulated sequence read failure"),
			}

			require.Error(t, tc.add(mk, ctx),
				"a failed sequence read must not restart positions at zero")
		})
	}
}

func TestListMetadataDecodeFailuresPropagate(t *testing.T) {
	owner := testAccAddressString()

	t.Run("count", func(t *testing.T) {
		mk := newMockKeeper()
		mk.storeService.store[listCountKey(types.FollowedUsersPrefix, owner)] = []byte{1}

		_, err := mk.CountFollowedUsers(newMockContext(), owner)
		require.ErrorContains(t, err, "count decode failed")
	})

	t.Run("sequence", func(t *testing.T) {
		mk := newMockKeeper()
		mk.storeService.store[listSeqKey(types.EnabledAgentsPrefix, owner)] = []byte{1}

		_, err := mk.AddEnabledAgent(newMockContext(), owner, "agent")
		require.ErrorContains(t, err, "sequence decode failed")
	})

	t.Run("position", func(t *testing.T) {
		mk := newMockKeeper()
		mk.storeService.store[types.EnabledAgentsPrefix+owner+"/agent"] = []byte{1}

		_, err := mk.ListEnabledAgentsOrdered(newMockContext(), owner)
		require.ErrorContains(t, err, "position decode failed")
	})
}

func TestListMetadataOverflowPropagates(t *testing.T) {
	owner := testAccAddressString()

	t.Run("count", func(t *testing.T) {
		mk := newMockKeeper()
		mk.storeService.store[listCountKey(types.FollowedUsersPrefix, owner)] = listCountBytes(math.MaxUint32)

		_, err := mk.AddFollowedUser(newMockContext(), owner, "target")
		require.ErrorContains(t, err, "count overflow")
	})

	t.Run("sequence", func(t *testing.T) {
		mk := newMockKeeper()
		bz := make([]byte, 8)
		binary.BigEndian.PutUint64(bz, math.MaxUint64)
		mk.storeService.store[listSeqKey(types.EnabledAgentsPrefix, owner)] = bz

		_, err := mk.AddEnabledAgent(newMockContext(), owner, "agent")
		require.ErrorContains(t, err, "sequence overflow")
	})
}

// TestListCountReadFailureOnRemovePropagates covers the decrement path, which
// discarded its read the same way the increment path did.
func TestListCountReadFailureOnRemovePropagates(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()
	owner := testAccAddressString()

	added, err := mk.AddFollowedUser(ctx, owner, "target")
	require.NoError(t, err)
	require.True(t, added)

	mk.storeService.getErrors = map[string]error{
		listCountKey(types.FollowedUsersPrefix, owner): errors.New("simulated count read failure"),
	}

	require.Error(t, mk.RemoveFollowedUser(ctx, owner, "target"))
}

// TestCountReadFailurePropagatesThroughPublicCounters proves the public
// accessors surface the error rather than reporting a plausible zero.
func TestCountReadFailurePropagatesThroughPublicCounters(t *testing.T) {
	owner := testAccAddressString()

	counters := map[string]struct {
		prefix string
		count  func(mk *mockKeeper, ctx sdk.Context) (uint32, error)
	}{
		"followed_users":  {types.FollowedUsersPrefix, func(mk *mockKeeper, ctx sdk.Context) (uint32, error) { return mk.CountFollowedUsers(ctx, owner) }},
		"followed_topics": {types.FollowedTopicsPrefix, func(mk *mockKeeper, ctx sdk.Context) (uint32, error) { return mk.CountFollowedTopics(ctx, owner) }},
		"enabled_agents":  {types.EnabledAgentsPrefix, func(mk *mockKeeper, ctx sdk.Context) (uint32, error) { return mk.CountEnabledAgents(ctx, owner) }},
		"blocked_users":   {types.BlockedUsersPrefix, func(mk *mockKeeper, ctx sdk.Context) (uint32, error) { return mk.CountBlockedUsers(ctx, owner) }},
		"blocked_posts":   {types.BlockedPostsPrefix, func(mk *mockKeeper, ctx sdk.Context) (uint32, error) { return mk.CountBlockedPosts(ctx, owner) }},
		"blocked_topics":  {types.BlockedTopicsPrefix, func(mk *mockKeeper, ctx sdk.Context) (uint32, error) { return mk.CountBlockedTopics(ctx, owner) }},
	}

	for name, tc := range counters {
		t.Run(name, func(t *testing.T) {
			mk := newMockKeeper()
			ctx := newMockContext()

			// Absent key is a legitimate zero.
			got, err := tc.count(mk, ctx)
			require.NoError(t, err)
			require.Equal(t, uint32(0), got)

			mk.storeService.getErrors = map[string]error{
				listCountKey(tc.prefix, owner): errors.New("simulated count read failure"),
			}
			_, err = tc.count(mk, ctx)
			require.Error(t, err, "a failed read must never be reported as a count of zero")
		})
	}
}

// TestListAddPropagatesCountReadFailure covers the keeper contract. The entry
// write happens before the count read, so the SDK transaction cache—not this
// direct mock store—rolls it back when the handler returns this error.
func TestListAddPropagatesCountReadFailure(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()
	owner := testAccAddressString()

	mk.storeService.getErrors = map[string]error{
		listCountKey(types.FollowedUsersPrefix, owner): errors.New("simulated count read failure"),
	}

	_, err := mk.AddFollowedUser(ctx, owner, "target")
	require.Error(t, err)

	// The count itself must still be unreadable rather than silently zeroed.
	_, cErr := mk.CountFollowedUsers(ctx, owner)
	require.Error(t, cErr)
}

func TestListStoreFailureHaltsDuringFinalize(t *testing.T) {
	restore := consensusfatal.SetHaltForTest(func(err error) { panic(err) })
	defer restore()

	mk := newMockKeeper()
	ctx := newMockContext().WithExecMode(sdk.ExecModeFinalize)
	owner := testAccAddressString()
	mk.storeService.getErrors = map[string]error{
		listCountKey(types.FollowedUsersPrefix, owner): errors.New("simulated finalize read failure"),
	}

	require.Panics(t, func() {
		_, _ = mk.CountFollowedUsers(ctx, owner)
	})
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

func TestBeginBlockFailsClosedOnFeeCollectorBurnFailure(t *testing.T) {
	t.Run("module_transfer", func(t *testing.T) {
		mk := newMockKeeper()
		am := newTestModule(mk)
		ctx := newMockContext()
		feeCollector := authtypes.NewModuleAddress(authtypes.FeeCollectorName).String()
		fundAccount(mk, feeCollector, 100)
		mk.bank.sendModuleToModuleErr = errors.New("simulated fee collector transfer failure")

		err := am.BeginBlock(ctx)
		require.ErrorContains(t, err, "simulated fee collector transfer failure")
	})

	t.Run("burn", func(t *testing.T) {
		mk := newMockKeeper()
		am := newTestModule(mk)
		ctx := newMockContext()
		feeCollector := authtypes.NewModuleAddress(authtypes.FeeCollectorName).String()
		fundAccount(mk, feeCollector, 100)
		mk.bank.burnCoinsErr = errors.New("simulated fee collector burn failure")

		err := am.BeginBlock(ctx)
		require.ErrorContains(t, err, "simulated fee collector burn failure")
	})
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

// --- M-1 / M-4: subscription atomicity and period-zero expiry ---------------

func TestExpiredSubscriptionIndexDecodeFailuresPropagate(t *testing.T) {
	owner := testAccAddressString()

	t.Run("malformed_key", func(t *testing.T) {
		mk := newMockKeeper()
		mk.storeService.store[types.SubscriptionsPrefix+"0000000000000001"] = listCountBytes(1)

		_, err := mk.GetExpiredSubscriptions(newMockContext(), 2_000_000_000)
		require.ErrorContains(t, err, "malformed subscription index key")
	})

	t.Run("malformed_value", func(t *testing.T) {
		mk := newMockKeeper()
		mk.storeService.store[subscriptionIndexKey(1, owner)] = []byte{1}

		_, err := mk.GetExpiredSubscriptions(newMockContext(), 2_000_000_000)
		require.ErrorContains(t, err, "malformed subscription level")
	})

	t.Run("timestamp_overflow", func(t *testing.T) {
		mk := newMockKeeper()

		_, err := mk.GetExpiredSubscriptions(newMockContext(), math.MaxInt64)
		require.ErrorContains(t, err, "subscription expiry scan end")
	})
}

// seedExpiredSubscription indexes a paid, auto-renewing profile whose expiry is
// already in the past for the contexts used below.
func seedExpiredSubscription(t *testing.T, mk *mockKeeper, ctx sdk.Context, owner string, expiry int64, reserve uint64) {
	t.Helper()
	if reserve > 0 {
		// Escrowed reserve is held by the module account; without the backing
		// balance the burn trips CONSENSUS_FATAL:CORE_MODULE_SHORT_BURN.
		if mk.bank.balances == nil {
			mk.bank.balances = map[string]sdkmath.Int{}
		}
		moduleAddr := authtypes.NewModuleAddress(types.ModuleName).String()
		existing, ok := mk.bank.balances[moduleAddr]
		if !ok {
			existing = sdkmath.ZeroInt()
		}
		mk.bank.balances[moduleAddr] = existing.Add(sdkmath.NewIntFromUint64(reserve))
	}
	core := types.ProfileCore{
		Owner:              owner,
		Username:           "subscriber",
		Level:              types.LevelSubscriber,
		SubscriptionExpiry: expiry,
		AutoRenew:          true,
		ReserveFunds:       reserve,
	}
	bz, err := json.Marshal(core)
	require.NoError(t, err)
	require.NoError(t, mk.SetProfileCore(ctx, owner, bz))
	require.NoError(t, mk.SetSubscription(ctx, owner, types.LevelSubscriber, expiry))
}

func fundAccount(mk *mockKeeper, addr string, amount uint64) {
	if mk.bank.balances == nil {
		mk.bank.balances = map[string]sdkmath.Int{}
	}
	existing, ok := mk.bank.balances[addr]
	if !ok {
		existing = sdkmath.ZeroInt()
	}
	mk.bank.balances[addr] = existing.Add(sdkmath.NewIntFromUint64(amount))
}

func loadCore(t *testing.T, mk *mockKeeper, ctx sdk.Context, owner string) types.ProfileCore {
	t.Helper()
	bz, found, err := mk.GetProfileCore(ctx, owner)
	require.NoError(t, err)
	require.True(t, found)
	var core types.ProfileCore
	require.NoError(t, json.Unmarshal(bz, &core))
	return core
}

// TestProcessSubscriptionsFailsOnProfileSaveFailure pins M-1. The reserve burn
// has already happened by the time the profile is written, so a skipped write
// commits bank state that contradicts the stored profile.
func TestProcessSubscriptionsFailsOnProfileSaveFailure(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext().WithBlockTime(time.Unix(2_000_000_000, 0))
	am := newTestModule(mk)
	owner := testAccAddressString()

	seedExpiredSubscription(t, mk, ctx, owner, 1_000_000_000, 500)

	params := types.DefaultParams()
	params.SubscriptionPeriod = 0
	mk.storeService.setErrors = map[string]error{
		types.ProfilesPrefix + owner: errors.New("simulated profile write failure"),
	}

	err := am.processSubscriptions(ctx, params)
	require.Error(t, err, "a lost profile write after a burn must not commit")
	require.Contains(t, err.Error(), "failed to save profile")
}

// TestSubscribeFailsOnStaleIndexDeleteFailure pins the M-1 gift/self index
// cleanup: the payer's tokens are already gone when the old index is removed.
func TestSubscribeFailsOnStaleIndexDeleteFailure(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext().WithBlockTime(time.Unix(2_000_000_000, 0))
	am := newTestModule(mk)
	pub, owner := testPubkeyOwner()
	const oldExpiry int64 = 1_000_000_000

	ensureUsername(t, mk, ctx, owner, "Anon-subscriber")
	tier := mk.GetParams(ctx).GetTierConfig(types.LevelSubscriber)
	require.NotNil(t, tier)
	fundAccount(mk, owner, tier.PeriodFee)

	core := loadCore(t, mk, ctx, owner)
	core.SubscriptionExpiry = oldExpiry
	bz, err := json.Marshal(core)
	require.NoError(t, err)
	require.NoError(t, mk.SetProfileCore(ctx, owner, bz))
	require.NoError(t, mk.SetSubscription(ctx, owner, types.LevelSubscriber, oldExpiry))

	mk.storeService.deleteErrors = map[string]error{
		subscriptionIndexKey(oldExpiry, owner): errors.New("simulated stale index delete failure"),
	}

	_, err = am.Subscribe(ctx, &types.MsgSubscribe{
		Authority:      testAccAddressString(),
		EnvelopePubkey: pub,
		Level:          types.LevelSubscriber,
	})
	require.Error(t, err, "a surviving stale index must reject the subscription")
	require.Contains(t, err.Error(), "remove old subscription index")
}

// TestSubscribeFailsOnNewIndexWriteFailure covers the other half: without the
// new index the paid subscription would never expire.
func TestSubscribeFailsOnNewIndexWriteFailure(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext().WithBlockTime(time.Unix(2_000_000_000, 0))
	am := newTestModule(mk)
	pub, owner := testPubkeyOwner()

	ensureUsername(t, mk, ctx, owner, "Anon-subscriber")

	params := mk.GetParams(ctx)
	tier := params.GetTierConfig(types.LevelSubscriber)
	require.NotNil(t, tier)
	fundAccount(mk, owner, tier.PeriodFee)

	newExpiry := ctx.BlockTime().Unix() + int64(params.SubscriptionPeriod)*60
	mk.storeService.setErrors = map[string]error{
		subscriptionIndexKey(newExpiry, owner): errors.New("simulated index write failure"),
	}

	_, err := am.Subscribe(ctx, &types.MsgSubscribe{
		Authority:      testAccAddressString(),
		EnvelopePubkey: pub,
		Level:          types.LevelSubscriber,
	})
	require.Error(t, err, "a paid subscription with no expiry index must not commit")
	require.Contains(t, err.Error(), "set subscription index")
}

func TestSubscribeGiftRejectsReserveOverflow(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext().WithBlockTime(time.Unix(2_000_000_000, 0))
	am := newTestModule(mk)
	pub, payer := testPubkeyOwner()
	recipient := testAccAddressString()

	ensureUsername(t, mk, ctx, recipient, "gift-recipient")
	params := mk.GetParams(ctx)
	params.SubscriptionReserveBps = types.BasisPointsDenominator
	require.NoError(t, mk.SetParams(ctx, params))
	tier := params.GetTierConfig(types.LevelSubscriber)
	require.NotNil(t, tier)
	fundAccount(mk, payer, tier.PeriodFee)

	core := loadCore(t, mk, ctx, recipient)
	core.ReserveFunds = math.MaxUint64 - tier.PeriodFee + 1
	bz, err := json.Marshal(core)
	require.NoError(t, err)
	require.NoError(t, mk.SetProfileCore(ctx, recipient, bz))

	_, err = am.Subscribe(ctx, &types.MsgSubscribe{
		Authority:      testAccAddressString(),
		EnvelopePubkey: pub,
		Target:         recipient,
		Level:          types.LevelSubscriber,
	})
	require.Error(t, err)
	require.Contains(t, err.Error(), "addition overflows uint64")
}

// TestProcessSubscriptionsPeriodZeroExpiresProfile pins M-4. One-time-payment
// mode used to remove the index and return, leaving a permanent paid level with
// stranded reserve.
func TestProcessSubscriptionsPeriodZeroExpiresProfile(t *testing.T) {
	for _, reserve := range []uint64{0, 1_500} {
		t.Run(fmt.Sprintf("reserve_%d", reserve), func(t *testing.T) {
			mk := newMockKeeper()
			ctx := newMockContext().WithBlockTime(time.Unix(2_000_000_000, 0))
			am := newTestModule(mk)
			owner := testAccAddressString()
			const expiry int64 = 1_000_000_000

			seedExpiredSubscription(t, mk, ctx, owner, expiry, reserve)

			params := types.DefaultParams()
			params.SubscriptionPeriod = 0
			require.NoError(t, am.processSubscriptions(ctx, params))

			core := loadCore(t, mk, ctx, owner)
			require.Equal(t, int32(0), core.Level, "one-time subscription must downgrade to free")
			require.Zero(t, core.SubscriptionExpiry)
			require.False(t, core.AutoRenew)
			require.Zero(t, core.ReserveFunds, "leftover reserve must be burned, not stranded")
			require.NotContains(t, mk.storeService.store, subscriptionIndexKey(expiry, owner))
		})
	}
}

func TestProcessSubscriptionsCleansStaleFreeProfile(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext().WithBlockTime(time.Unix(2_000_000_000, 0))
	am := newTestModule(mk)
	owner := testAccAddressString()
	const expiry int64 = 1_000_000_000

	core := types.ProfileCore{
		Owner:              owner,
		Username:           "freeuser",
		Level:              0,
		SubscriptionExpiry: expiry,
		AutoRenew:          true,
	}
	bz, err := json.Marshal(core)
	require.NoError(t, err)
	require.NoError(t, mk.SetProfileCore(ctx, owner, bz))
	require.NoError(t, mk.SetSubscription(ctx, owner, 0, expiry))

	params := types.DefaultParams()
	params.SubscriptionPeriod = 0
	require.NoError(t, am.processSubscriptions(ctx, params))

	core = loadCore(t, mk, ctx, owner)
	require.Zero(t, core.SubscriptionExpiry)
	require.False(t, core.AutoRenew)
	require.NotContains(t, mk.storeService.store, subscriptionIndexKey(expiry, owner))
}

func TestProcessSubscriptionsPersistsReserveBurnForFreeTier(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext().WithBlockTime(time.Unix(2_000_000_000, 0))
	am := newTestModule(mk)
	owner := testAccAddressString()
	const (
		expiry  int64  = 1_000_000_000
		reserve uint64 = 500
	)

	seedExpiredSubscription(t, mk, ctx, owner, expiry, reserve)
	core := loadCore(t, mk, ctx, owner)
	core.Level = 0
	bz, err := json.Marshal(core)
	require.NoError(t, err)
	require.NoError(t, mk.SetProfileCore(ctx, owner, bz))

	require.NoError(t, am.processSubscriptions(ctx, types.DefaultParams()))

	core = loadCore(t, mk, ctx, owner)
	require.Zero(t, core.ReserveFunds)
	require.NotContains(t, mk.storeService.store, subscriptionIndexKey(expiry, owner))
}

func TestProcessSubscriptionsDowngradesInvalidSubscriptionLevel(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext().WithBlockTime(time.Unix(2_000_000_000, 0))
	am := newTestModule(mk)
	owner := testAccAddressString()
	const expiry int64 = 1_000_000_000

	core := types.ProfileCore{
		Owner:              owner,
		Username:           "invalid-level",
		Level:              5,
		SubscriptionExpiry: expiry,
		AutoRenew:          true,
	}
	bz, err := json.Marshal(core)
	require.NoError(t, err)
	require.NoError(t, mk.SetProfileCore(ctx, owner, bz))
	require.NoError(t, mk.SetSubscription(ctx, owner, int(core.Level), expiry))

	require.NoError(t, am.processSubscriptions(ctx, types.DefaultParams()))

	core = loadCore(t, mk, ctx, owner)
	require.Zero(t, core.Level)
	require.Zero(t, core.SubscriptionExpiry)
	require.False(t, core.AutoRenew)
	require.NotContains(t, mk.storeService.store, subscriptionIndexKey(expiry, owner))
}

func TestProcessSubscriptionsFailsClosedOnRenewalBurnFailure(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext().WithBlockTime(time.Unix(2_000_000_000, 0))
	am := newTestModule(mk)
	owner := testAccAddressString()

	seedExpiredSubscription(t, mk, ctx, owner, 1_000_000_000, 0)
	params := types.DefaultParams()
	params.SubscriptionReserveBps = 0
	tier := params.GetTierConfig(types.LevelSubscriber)
	require.NotNil(t, tier)
	fundAccount(mk, owner, tier.PeriodFee)
	mk.bank.burnCoinsErr = errors.New("simulated renewal burn store failure")

	err := am.processSubscriptions(ctx, params)
	require.Error(t, err)
	require.Contains(t, err.Error(), "failed to burn renewal fee")
}

func TestProcessSubscriptionsFailsClosedOnRenewalEscrowFailure(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext().WithBlockTime(time.Unix(2_000_000_000, 0))
	am := newTestModule(mk)
	owner := testAccAddressString()

	seedExpiredSubscription(t, mk, ctx, owner, 1_000_000_000, 0)
	params := types.DefaultParams()
	params.SubscriptionReserveBps = types.BasisPointsDenominator
	tier := params.GetTierConfig(types.LevelSubscriber)
	require.NotNil(t, tier)
	fundAccount(mk, owner, tier.PeriodFee)
	mk.bank.sendToModuleErr = errors.New("simulated renewal escrow store failure")

	err := am.processSubscriptions(ctx, params)
	require.Error(t, err)
	require.Contains(t, err.Error(), "failed to escrow renewal reserve")
}

// --- M-3: delete-user cleanup -----------------------------------------------

func subscriptionIndexKey(expiry int64, addr string) string {
	return fmt.Sprintf("%s%016x:%s", types.SubscriptionsPrefix, expiry, addr)
}

func seedDeletableProfile(t *testing.T, mk *mockKeeper, ctx sdk.Context, owner, username string, expiry int64) {
	t.Helper()
	core := types.ProfileCore{Owner: owner, Username: username, SubscriptionExpiry: expiry}
	if expiry > 0 {
		core.Level = 1
	}
	bz, err := json.Marshal(core)
	require.NoError(t, err)
	require.NoError(t, mk.SetProfileCore(ctx, owner, bz))
	require.NoError(t, mk.ClaimUsername(ctx, username, owner))
	if expiry > 0 {
		require.NoError(t, mk.SetSubscription(ctx, owner, 1, expiry))
	}
}

// TestDeleteUserStateFailsOnSubscriptionIndexDeleteFailure pins the M-3 fix.
// Discarding this delete left a subscription index entry pointing at a deleted
// profile, which EndBlock later reports as CONSENSUS_FATAL:PROFILE_MISSING.
func TestDeleteUserStateFailsOnSubscriptionIndexDeleteFailure(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()
	owner := testAccAddressString()
	const expiry int64 = 1800000000

	seedDeletableProfile(t, mk, ctx, owner, "deleteme", expiry)

	mk.storeService.deleteErrors = map[string]error{
		subscriptionIndexKey(expiry, owner): errors.New("simulated subscription index delete failure"),
	}

	_, err := mk.DeleteUserState(ctx, owner, "deleteme", expiry)
	require.Error(t, err, "a surviving subscription index must fail the transaction")
	require.Contains(t, err.Error(), "subscription index")
}

// TestDeleteUserStateFailsOnUsernameReleaseFailure covers the other orphan: a
// username mapping that outlives the profile it points to.
func TestDeleteUserStateFailsOnUsernameReleaseFailure(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()
	owner := testAccAddressString()

	seedDeletableProfile(t, mk, ctx, owner, "deleteme", 0)

	mk.storeService.deleteErrors = map[string]error{
		types.UsernamesPrefix + "deleteme": errors.New("simulated username delete failure"),
	}

	_, err := mk.DeleteUserState(ctx, owner, "deleteme", 0)
	require.Error(t, err)
}

// TestDeleteUserStateRemovesEveryOwnedKey is the happy path: profile, username
// mapping, and subscription index all go together.
func TestDeleteUserStateRemovesEveryOwnedKey(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()
	owner := testAccAddressString()
	const expiry int64 = 1800000000

	seedDeletableProfile(t, mk, ctx, owner, "deleteme", expiry)
	_, err := mk.AddFollowedUser(ctx, owner, "someone")
	require.NoError(t, err)

	_, err = mk.DeleteUserState(ctx, owner, "deleteme", expiry)
	require.NoError(t, err)

	_, found, err := mk.GetProfileCore(ctx, owner)
	require.NoError(t, err)
	require.False(t, found)
	require.NotContains(t, mk.storeService.store, types.UsernamesPrefix+"deleteme")
	require.NotContains(t, mk.storeService.store, subscriptionIndexKey(expiry, owner))
	require.NotContains(t, mk.storeService.store, listCountKey(types.FollowedUsersPrefix, owner))
}

// --- L-1: profile mutation reads --------------------------------------------

// TestUpdateProfileCoreRefusesUnreadableProfile proves an unreadable profile is
// no longer overwritten with a freshly synthesized empty one.
func TestUpdateProfileCoreRefusesUnreadableProfile(t *testing.T) {
	mk := newMockKeeper()
	am := newTestModule(mk)
	ctx := newMockContext()
	owner := testAccAddressString()

	mk.storeService.getErrors = map[string]error{
		types.ProfilesPrefix + owner: errors.New("simulated profile Get failure"),
	}

	err := am.updateProfileCore(ctx, owner, func(c *types.ProfileCore) error { return nil })
	require.Error(t, err)
	require.Contains(t, err.Error(), "load profile")
}

// TestUpdateProfileCoreRefusesCorruptProfile covers the decode half: bytes that
// exist but are not a ProfileCore.
func TestUpdateProfileCoreRefusesCorruptProfile(t *testing.T) {
	mk := newMockKeeper()
	am := newTestModule(mk)
	ctx := newMockContext()
	owner := testAccAddressString()

	mk.storeService.store[types.ProfilesPrefix+owner] = []byte{0x00, 0xff, 0x13, 0x37}

	err := am.updateProfileCore(ctx, owner, func(c *types.ProfileCore) error { return nil })
	require.Error(t, err)
	require.Contains(t, err.Error(), "corrupt profile")

	require.Equal(t, []byte{0x00, 0xff, 0x13, 0x37}, mk.storeService.store[types.ProfilesPrefix+owner],
		"corrupt bytes must be left untouched, not replaced with an empty profile")
}

// TestUpdateProfileCoreRefusesUnreadableAgentList covers the list load that
// feeds tier validation.
func TestUpdateProfileCoreRefusesUnreadableAgentList(t *testing.T) {
	mk := newMockKeeper()
	am := newTestModule(mk)
	ctx := newMockContext()
	owner := testAccAddressString()

	mk.storeService.iterError = errors.New("simulated iterator failure")

	err := am.updateProfileCore(ctx, owner, func(c *types.ProfileCore) error { return nil })
	require.Error(t, err)
	require.Contains(t, err.Error(), "enabled_agents")
}

// --- L-8: mutual-exclusion cleanup ------------------------------------------

// TestBlockUserFailsWhenUnfollowFails proves the block is not committed while
// the contradictory follow entry survives.
func TestBlockUserFailsWhenUnfollowFails(t *testing.T) {
	mk := newMockKeeper()
	am := newTestModule(mk)
	ctx := newMockContext()
	pub, owner := testPubkeyOwner()
	target := testAccAddressString()

	ensureUsername(t, mk, ctx, owner, "Anon-blocker")
	added, err := mk.AddFollowedUser(ctx, owner, target)
	require.NoError(t, err)
	require.True(t, added)

	mk.storeService.deleteErrors = map[string]error{
		types.FollowedUsersPrefix + owner + "/" + target: errors.New("simulated unfollow delete failure"),
	}

	_, err = am.BlockUser(ctx, &types.MsgBlockUser{
		Authority:      testAccAddressString(),
		EnvelopePubkey: pub,
		Target:         target,
	})
	require.Error(t, err, "blocking must fail when the mutually exclusive follow cannot be removed")

	blocked, hErr := mk.HasBlockedUser(ctx, owner, target)
	require.NoError(t, hErr)
	require.False(t, blocked, "the block entry must not be written after cleanup failed")
}

// TestFollowTopicFailsWhenUnblockFails is the mirror case through the wildcard
// blocked-topic path.
func TestFollowTopicFailsWhenUnblockFails(t *testing.T) {
	mk := newMockKeeper()
	am := newTestModule(mk)
	ctx := newMockContext()
	pub, owner := testPubkeyOwner()

	ensureUsername(t, mk, ctx, owner, "Anon-follower")
	added, err := mk.AddBlockedTopicDeque(ctx, owner, "news*", 100)
	require.NoError(t, err)
	require.True(t, added)

	mk.storeService.deleteErrors = map[string]error{
		types.BlockedTopicsPrefix + owner + "/news*": errors.New("simulated unblock delete failure"),
	}

	_, err = am.FollowTopic(ctx, &types.MsgFollowTopic{
		Authority:      testAccAddressString(),
		EnvelopePubkey: pub,
		Topic:          "news",
	})
	require.Error(t, err, "following must fail when the matching block cannot be removed")
}

// --- L-10: admin fee waiver classification ----------------------------------

// TestAdminGasWaiverAppliesOnlyToInsufficientFunds pins L-10. The documented
// liveness waiver covers an empty admin balance; a node-local bank failure must
// reject instead, or one node skips a deduction its peers performed.
func TestAdminGasWaiverAppliesOnlyToInsufficientFunds(t *testing.T) {
	const adminLevel = 100
	const gasUsed = 100_000

	t.Run("insufficient_funds_is_waived", func(t *testing.T) {
		mk := newMockKeeper()
		am := newTestModule(mk)
		ctx := newMockContext()

		mk.bank.sendToModuleErr = sdkerrors.ErrInsufficientFunds

		require.NoError(t, am.deductRelayGasFee(ctx, testAccAddressString(), adminLevel, gasUsed, "test"),
			"an empty admin balance must not block the operation")
	})

	t.Run("storage_failure_is_rejected", func(t *testing.T) {
		mk := newMockKeeper()
		am := newTestModule(mk)
		ctx := newMockContext()

		fundAccount(mk, testAccAddressString(), gasUsed*types.DefaultParams().RelayMinGasPrice)
		mk.bank.sendToModuleErr = errors.New("simulated node-local bank failure")

		err := am.deductRelayGasFee(ctx, testAccAddressString(), adminLevel, gasUsed, "test")
		require.Error(t, err, "a bank/store failure must not be waived as insufficient funds")
		require.Contains(t, err.Error(), "deduct from")
	})

	t.Run("unexpected_insufficient_after_precheck_halts_finalize", func(t *testing.T) {
		restore := consensusfatal.SetHaltForTest(func(err error) { panic(err) })
		defer restore()

		mk := newMockKeeper()
		am := newTestModule(mk)
		ctx := newMockContext().WithExecMode(sdk.ExecModeFinalize)
		owner := testAccAddressString()
		fundAccount(mk, owner, gasUsed*types.DefaultParams().RelayMinGasPrice)
		mk.bank.sendToModuleErr = sdkerrors.ErrInsufficientFunds

		require.Panics(t, func() {
			_ = am.deductRelayGasFee(ctx, owner, adminLevel, gasUsed, "test")
		})
	})
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

func TestEndBlockFailsClosedOnExpiredNonceDeleteFailure(t *testing.T) {
	mk := newMockKeeper()
	am := newTestModule(mk)
	ctx := newMockContext()
	pubkeyHash := []byte{0xab, 0xcd}
	const nonce uint64 = 7
	expiry := ctx.BlockTime().Unix() - 1
	require.NoError(t, mk.SetEnvelopeNonce(ctx, pubkeyHash, nonce, expiry))

	nonceKey := fmt.Sprintf("%s%x/%d", types.EnvelopeNoncePrefix, pubkeyHash, nonce)
	mk.storeService.deleteErrors = map[string]error{
		nonceKey: errors.New("simulated expired nonce delete failure"),
	}

	err := am.EndBlock(ctx)
	require.ErrorContains(t, err, "simulated expired nonce delete failure")
}

func TestPruneExpiredNoncesRejectsTimeOverflow(t *testing.T) {
	mk := newMockKeeper()

	_, err := mk.PruneExpiredNonces(newMockContext(), math.MaxInt64)
	require.ErrorContains(t, err, "envelope nonce prune cutoff")
}

func TestPruneExpiredNoncesRejectsMalformedIndexKey(t *testing.T) {
	mk := newMockKeeper()
	key := types.EnvelopeNonceExpiryPrefix + "0000000000000000000x/abcd/7"
	mk.storeService.store[key] = []byte{}

	_, err := mk.PruneExpiredNonces(newMockContext(), 2_000_000_000)
	require.ErrorContains(t, err, "invalid envelope nonce expiry timestamp")
}

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

func TestDifficultyReadsFailClosedOnOutOfRangeState(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()
	bz := make([]byte, 8)
	binary.BigEndian.PutUint64(bz, keeper.MaxSafeDifficultySteps+1)
	mk.storeService.store["current_difficulty"] = bz

	requirePanicContains(t, "CONSENSUS_FATAL:DIFFICULTY_RANGE", func() {
		_ = mk.GetCurrentDifficulty(ctx)
	})
}

func TestCalmSequenceReadsFailClosedOnOutOfRangeState(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()
	bz := make([]byte, 8)
	binary.BigEndian.PutUint64(bz, types.MaxPowCalmSequenceThreshold+1)
	mk.storeService.store["consecutive_low_usage"] = bz

	requirePanicContains(t, "CONSENSUS_FATAL:CONSECUTIVE_LOW_USAGE_RANGE", func() {
		_ = mk.GetConsecutiveLowUsage(ctx)
	})
}

func TestPreviousDifficultyAndChangeHeightFailClosedOnOutOfRangeState(t *testing.T) {
	ctx := newMockContext()

	t.Run("previous_difficulty", func(t *testing.T) {
		mk := newMockKeeper()
		bz := make([]byte, 8)
		binary.BigEndian.PutUint64(bz, keeper.MaxSafeDifficultySteps+1)
		mk.storeService.store["prev_difficulty"] = bz
		requirePanicContains(t, "CONSENSUS_FATAL:PREV_DIFFICULTY_RANGE", func() {
			_ = mk.GetPreviousDifficulty(ctx)
		})
	})

	t.Run("change_height", func(t *testing.T) {
		mk := newMockKeeper()
		bz := make([]byte, 8)
		binary.BigEndian.PutUint64(bz, math.MaxUint64)
		mk.storeService.store["last_diff_change_height"] = bz
		requirePanicContains(t, "CONSENSUS_FATAL:LAST_DIFF_CHANGE_RANGE", func() {
			_ = mk.GetLastDifficultyChangeHeight(ctx)
		})
	})
}
