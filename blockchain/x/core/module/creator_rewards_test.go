package core

import (
	"strings"
	"testing"
	"time"

	sdkmath "cosmossdk.io/math"
	sdk "github.com/cosmos/cosmos-sdk/types"
	authtypes "github.com/cosmos/cosmos-sdk/x/auth/types"
	govtypes "github.com/cosmos/cosmos-sdk/x/gov/types"
	"github.com/stretchr/testify/require"

	"mirage/x/core/types"
)

type settledCreatorReward struct {
	mk         *mockKeeper
	am         AppModule
	ctx        sdk.Context
	payer      string
	subscriber string
	creator    string
	target     string
	epoch      int64
	earned     sdkmath.Int
	deadline   int64
}

func settleCreatorReward(t *testing.T, directReply bool, epochSeconds uint64, deleteInEpoch bool) settledCreatorReward {
	t.Helper()
	mk, ctx, am := setupModule(t)
	_, payer := curationSigner(0x61)
	_, subscriber := curationSigner(0x62)
	_, creator := curationSigner(0x63)
	ensureUsername(t, mk, ctx, payer, "reward-payer")
	ensureUsername(t, mk, ctx, subscriber, "reward-subscriber")
	ensureUsername(t, mk, ctx, creator, "reward-creator")

	params := mk.GetParams(ctx)
	// Subscription length is deliberately left at the 30-day default even for
	// five-minute epochs. Shortening it used to be mandatory, because a tranche
	// pre-split its creator share into one record per epoch spanned.
	params.CreatorEpochSeconds = epochSeconds
	require.NoError(t, mk.SetParams(ctx, params))
	tier := params.GetTierConfig(types.LevelSubscriber)
	require.NotNil(t, tier)
	fundAccount(mk, payer, tier.PeriodFee)

	epoch, err := types.CreatorEpochFromUnix(ctx.BlockTime().Unix(), epochSeconds)
	require.NoError(t, err)
	require.NoError(t, mk.SetCreatorClock(ctx, epoch))
	require.NoError(t, mk.CreateTranche(
		ctx,
		payer,
		subscriber,
		types.SubscriptionTrancheSource_SUBSCRIPTION_TRANCHE_SOURCE_GIFT,
		1,
		genTxHash(200),
	))

	target := genTxHash(201)
	require.NoError(t, mk.SetPostMetadata(ctx, target, &types.PostMetadata{
		Author:    creator,
		Community: "creator-rewards",
	}))
	if directReply {
		source := genTxHash(202)
		require.NoError(t, mk.SetPostMetadata(ctx, source, &types.PostMetadata{
			Author:     subscriber,
			Community:  "creator-rewards",
			ParentHash: target,
		}))
		require.NoError(t, mk.RecordDirectReplyEngagement(ctx, subscriber, target, source))
	} else {
		require.NoError(t, mk.RecordUpvoteEngagement(ctx, subscriber, target, 1))
	}
	if deleteInEpoch {
		meta, found, err := mk.GetPostMetadata(ctx, target)
		require.NoError(t, err)
		require.True(t, found)
		meta.DeletedEpoch = epoch
		require.NoError(t, mk.SetPostMetadata(ctx, target, meta))
	}

	mk.storeService.store[types.UpgradeV139CompleteKey] = []byte{1}
	settlementTime, err := types.CreatorEpochEnd(epoch, epochSeconds)
	require.NoError(t, err)
	settledCtx := ctx.
		WithBlockHeight(ctx.BlockHeight() + 1).
		WithBlockTime(time.Unix(settlementTime+1, 0)).
		WithEventManager(sdk.NewEventManager())
	require.NoError(t, mk.ProcessBeginBlockV139(settledCtx))

	epochResponse, err := am.CreatorEpoch(settledCtx, &types.QueryCreatorEpochRequest{EpochId: epoch})
	require.NoError(t, err)
	if deleteInEpoch {
		require.Equal(t, types.CreatorEpochStatus_CREATOR_EPOCH_STATUS_EXPIRED, epochResponse.Epoch.Status)
		require.Equal(t, "0", epochResponse.Epoch.AllocatedTotal)
		accruals, err := am.CreatorAccruals(
			settledCtx,
			&types.QueryCreatorAccrualsRequest{Creator: creator},
		)
		require.NoError(t, err)
		require.Empty(t, accruals.Accruals)
		return settledCreatorReward{mk: mk, am: am, ctx: settledCtx, payer: payer, subscriber: subscriber, creator: creator, target: target, epoch: epoch}
	}
	require.Equal(t, types.CreatorEpochStatus_CREATOR_EPOCH_STATUS_CLAIMABLE, epochResponse.Epoch.Status)
	require.Equal(t, epochResponse.Epoch.Pool, epochResponse.Epoch.AllocatedTotal)

	accruals, err := am.CreatorAccruals(settledCtx, &types.QueryCreatorAccrualsRequest{Creator: creator})
	require.NoError(t, err)
	require.Len(t, accruals.Accruals, 1)
	accrual := accruals.Accruals[0]
	require.Equal(t, epoch, accrual.Epoch)
	require.False(t, accrual.Claimed)
	earned, ok := sdkmath.NewIntFromString(accrual.Amount)
	require.True(t, ok)
	require.True(t, earned.IsPositive())
	require.Equal(t, epochResponse.Epoch.Pool, earned.String())

	epochAccruals, err := am.CreatorEpochAccruals(
		settledCtx,
		&types.QueryCreatorEpochAccrualsRequest{EpochId: epoch},
	)
	require.NoError(t, err)
	require.Len(t, epochAccruals.Accruals, 1)
	require.Equal(t, creator, epochAccruals.Accruals[0].Creator)
	require.Equal(t, earned.String(), epochAccruals.Accruals[0].Amount)

	targetResponse, err := am.TargetEarnings(settledCtx, &types.QueryTargetEarningsRequest{Target: target})
	require.NoError(t, err)
	require.Len(t, targetResponse.Earnings, 1)
	require.Equal(t, earned.String(), targetResponse.Earnings[0].Amount)

	return settledCreatorReward{
		mk:         mk,
		am:         am,
		ctx:        settledCtx,
		payer:      payer,
		subscriber: subscriber,
		creator:    creator,
		target:     target,
		epoch:      epoch,
		earned:     earned,
		deadline:   epochResponse.Epoch.ClaimDeadlineUnix,
	}
}

func TestCreatorRewardDailySettlementAndClaim(t *testing.T) {
	reward := settleCreatorReward(t, false, types.SecondsPerUTCDay, false)
	liabilityBefore, err := reward.mk.GetCreatorLiability(reward.ctx)
	require.NoError(t, err)

	require.NoError(t, reward.mk.ClaimCreatorRewards(reward.ctx, reward.creator, []int64{reward.epoch}))
	require.Equal(
		t,
		reward.earned,
		reward.mk.bank.sentModuleToAccount.AmountOf(types.MintDenom),
	)
	liabilityAfter, err := reward.mk.GetCreatorLiability(reward.ctx)
	require.NoError(t, err)
	require.Equal(t, reward.earned, liabilityBefore.Sub(liabilityAfter))

	accruals, err := reward.am.CreatorAccruals(
		reward.ctx,
		&types.QueryCreatorAccrualsRequest{Creator: reward.creator},
	)
	require.NoError(t, err)
	require.Len(t, accruals.Accruals, 1)
	require.True(t, accruals.Accruals[0].Claimed)
	require.Equal(t, reward.earned.String(), accruals.Accruals[0].ClaimedAmount)
	require.ErrorContains(
		t,
		reward.mk.ClaimCreatorRewards(reward.ctx, reward.creator, []int64{reward.epoch}),
		"already claimed",
	)
}

func TestCreatorRewardFiveMinuteSettlementAndClaim(t *testing.T) {
	reward := settleCreatorReward(t, false, 300, false)
	require.NoError(t, reward.mk.ClaimCreatorRewards(reward.ctx, reward.creator, []int64{reward.epoch}))
	require.Equal(
		t,
		reward.earned,
		reward.mk.bank.sentModuleToAccount.AmountOf(types.MintDenom),
	)
}

func countPrefix(mk *mockKeeper, prefix string) int {
	n := 0
	for key := range mk.storeService.store {
		if strings.HasPrefix(key, prefix) {
			n++
		}
	}
	return n
}

// advanceCreatorClockTo runs BeginBlock at the given wall time until the
// creator clock stops moving, which is how a real chain catches up after the
// clock falls behind block time. Bounded so a stalled clock fails the test
// instead of hanging it.
func advanceCreatorClockTo(t *testing.T, mk *mockKeeper, base sdk.Context, at int64) sdk.Context {
	t.Helper()
	const maxBlocks = 10_000
	ctx := base
	last := int64(-1)
	for i := 0; i < maxBlocks; i++ {
		ctx = ctx.
			WithBlockHeight(ctx.BlockHeight() + 1).
			WithBlockTime(time.Unix(at, 0)).
			WithEventManager(sdk.NewEventManager())
		require.NoError(t, mk.ProcessBeginBlockV139(ctx))
		clock, err := mk.GetCreatorClock(ctx)
		require.NoError(t, err)
		if clock == last {
			return ctx
		}
		last = clock
	}
	t.Fatalf("creator clock did not settle within %d blocks", maxBlocks)
	return ctx
}

func TestCreatorRewardDirectReplyExpiresAfterClaimWindow(t *testing.T) {
	reward := settleCreatorReward(t, true, 300, false)
	// The window is thirty wall-clock days from settlement, not a count of
	// epochs, so it means the same span on any interval.
	require.Equal(t, reward.ctx.BlockTime().Unix()+30*types.SecondsPerUTCDay, reward.deadline)
	expiryTime := reward.deadline
	// The clock walks epoch boundaries rather than jumping, because each
	// boundary is where a streaming tranche hands its slice to an epoch.
	// Skipping to the deadline in one block would skip that money, so drive
	// blocks until the clock actually arrives. At creator_epoch_closures_per_block
	// this is ~2160 blocks for a 30-day window on 5-minute epochs; a real chain
	// covers the same span in real time with ~400x headroom.
	expiryCtx := advanceCreatorClockTo(t, reward.mk, reward.ctx, expiryTime)

	epochResponse, err := reward.am.CreatorEpoch(
		expiryCtx,
		&types.QueryCreatorEpochRequest{EpochId: reward.epoch},
	)
	require.NoError(t, err)
	require.Equal(t, types.CreatorEpochStatus_CREATOR_EPOCH_STATUS_EXPIRED, epochResponse.Epoch.Status)
	require.ErrorContains(
		t,
		reward.mk.ClaimCreatorRewards(expiryCtx, reward.creator, []int64{reward.epoch}),
		"is not claimable",
	)
	require.True(t, reward.mk.bank.sentModuleToAccount.Empty())
}

// TestCreatorStreamPaysOutExactlyTheCreatorShare is the conservation check the
// whole streaming design rests on. addCreatorLiability books the full creator
// share the moment a subscription is bought, so the accumulator must eventually
// hand epochs that exact number: short by any amount and the pool holds tokens
// nobody can ever claim, over by any amount and the pool is insolvent.
//
// Rounding is where this would break. A per-second rate cannot divide most
// amounts evenly, so each epoch takes a difference of floors and each tranche
// carries its own leftover on its end breakpoint.
func TestCreatorStreamPaysOutExactlyTheCreatorShare(t *testing.T) {
	mk, ctx, _ := setupModule(t)
	_, payer := curationSigner(0x71)
	_, subscriber := curationSigner(0x72)
	ensureUsername(t, mk, ctx, payer, "stream-payer")
	ensureUsername(t, mk, ctx, subscriber, "stream-subscriber")

	const epochSeconds = 300
	params := mk.GetParams(ctx)
	params.CreatorEpochSeconds = epochSeconds
	require.NoError(t, mk.SetParams(ctx, params))
	require.Equal(t, uint64(43_200), params.SubscriptionPeriod, "30-day subscriptions must survive 5-minute epochs")

	tier := params.GetTierConfig(types.LevelSubscriber)
	require.NotNil(t, tier)
	fundAccount(mk, payer, tier.PeriodFee)
	_, creatorAmt, err := types.SplitCreatorFee(tier.PeriodFee, params.SubscriptionCreatorBps)
	require.NoError(t, err)
	require.Positive(t, creatorAmt)

	mk.storeService.store[types.UpgradeV139CompleteKey] = []byte{1}
	start := ctx.BlockTime().Unix()
	epoch, err := types.CreatorEpochFromUnix(start, epochSeconds)
	require.NoError(t, err)
	require.NoError(t, mk.SetCreatorClock(ctx, epoch))
	require.NoError(t, mk.AnchorCreatorStream(ctx, start))
	require.NoError(t, mk.CreateTranche(
		ctx,
		payer,
		subscriber,
		types.SubscriptionTrancheSource_SUBSCRIPTION_TRANCHE_SOURCE_GIFT,
		1,
		genTxHash(210),
	))

	// A 30-day subscription spans 8640 five-minute epochs. Buying it must not
	// have materialized a record per epoch.
	require.Equal(t, 0, countPrefix(mk, types.PfxCreatorEpoch), "purchase must not pre-split into epoch records")

	// Run past the end of the subscription so the final breakpoint, and with it
	// the tranche's rounding leftover, has been applied.
	trancheEnd := start + int64(params.SubscriptionPeriod)*60
	advanceCreatorClockTo(t, mk, ctx, trancheEnd+2*epochSeconds)

	paid, err := mk.CreatorStreamPaid(ctx)
	require.NoError(t, err)
	require.Equal(t, sdkmath.NewIntFromUint64(creatorAmt).String(), paid.String(),
		"streamed total must equal the creator share exactly")

	rate, err := mk.CreatorStreamRate(ctx)
	require.NoError(t, err)
	require.True(t, rate.IsZero(), "nothing may still be streaming after the tranche ends, got %s", rate)
	require.Equal(t, 0, countPrefix(mk, types.PfxCreatorStreamEnd), "every breakpoint must have been consumed")
}

// TestCreatorStreamConservesAcrossIntervalChange is what lets the payout
// interval be governable without burning anything. Re-gridding mid-tranche
// inserts an extra draw boundary at the switchover instant, so the epoch pools
// are cut differently, but draws are differences of one monotone accumulator
// and the tranche's rounding leftover still lands on its end breakpoint. The
// creator share therefore pays out to the base unit either way.
func TestCreatorStreamConservesAcrossIntervalChange(t *testing.T) {
	mk, ctx, am := setupModule(t)
	_, payer := curationSigner(0x91)
	_, subscriber := curationSigner(0x92)
	ensureUsername(t, mk, ctx, payer, "regrid-payer")
	ensureUsername(t, mk, ctx, subscriber, "regrid-subscriber")

	params := mk.GetParams(ctx)
	require.Equal(t, uint64(types.SecondsPerUTCDay), params.CreatorEpochSeconds)
	tier := params.GetTierConfig(types.LevelSubscriber)
	require.NotNil(t, tier)
	fundAccount(mk, payer, tier.PeriodFee)
	_, creatorAmt, err := types.SplitCreatorFee(tier.PeriodFee, params.SubscriptionCreatorBps)
	require.NoError(t, err)
	require.Positive(t, creatorAmt)

	mk.storeService.store[types.UpgradeV139CompleteKey] = []byte{1}
	start := ctx.BlockTime().Unix()
	epoch, err := types.CreatorEpochFromUnix(start, params.CreatorEpochSeconds)
	require.NoError(t, err)
	require.NoError(t, mk.SetCreatorClock(ctx, epoch))
	require.NoError(t, mk.AnchorCreatorStream(ctx, start))
	require.NoError(t, mk.CreateTranche(
		ctx,
		payer,
		subscriber,
		types.SubscriptionTrancheSource_SUBSCRIPTION_TRANCHE_SOURCE_GIFT,
		1,
		genTxHash(220),
	))

	// Run a few days on daily epochs, then switch to five minutes partway
	// through the subscription.
	trancheEnd := start + int64(params.SubscriptionPeriod)*60
	midway := advanceCreatorClockTo(t, mk, ctx, start+3*types.SecondsPerUTCDay)
	paidBeforeChange, err := mk.CreatorStreamPaid(midway)
	require.NoError(t, err)
	require.True(t, paidBeforeChange.IsPositive(), "the stream must already have paid out")

	submitCreatorEpochProposal(t, am, midway, 300)

	paidAcrossChange, err := mk.CreatorStreamPaid(midway)
	require.NoError(t, err)
	require.True(t, paidAcrossChange.GTE(paidBeforeChange), "re-gridding may not un-pay anything")

	after := advanceCreatorClockTo(t, mk, midway, trancheEnd+600)
	paid, err := mk.CreatorStreamPaid(after)
	require.NoError(t, err)
	require.Equal(t, sdkmath.NewIntFromUint64(creatorAmt).String(), paid.String(),
		"the creator share must be paid out exactly, despite the grid changing mid-tranche")

	rate, err := mk.CreatorStreamRate(after)
	require.NoError(t, err)
	require.True(t, rate.IsZero(), "nothing may still be streaming after the tranche ends, got %s", rate)
	require.Equal(t, 0, countPrefix(mk, types.PfxCreatorStreamEnd), "every breakpoint must have been consumed")
}

// TestCreatorStreamConservesAcrossStackedRenewal covers the awkward case: a
// renewal's tranche begins at the previous expiry, so it starts in the future
// and its rate must switch on at a scheduled instant rather than immediately.
// Getting that wrong pays the second subscription out over the wrong window
// while the liability still expects every token.
func TestCreatorStreamConservesAcrossStackedRenewal(t *testing.T) {
	mk, ctx, _ := setupModule(t)
	_, payer := curationSigner(0x81)
	_, subscriber := curationSigner(0x82)
	ensureUsername(t, mk, ctx, payer, "renew-payer")
	ensureUsername(t, mk, ctx, subscriber, "renew-subscriber")

	const epochSeconds = 300
	params := mk.GetParams(ctx)
	params.CreatorEpochSeconds = epochSeconds
	require.NoError(t, mk.SetParams(ctx, params))
	tier := params.GetTierConfig(types.LevelSubscriber)
	require.NotNil(t, tier)
	_, creatorAmt, err := types.SplitCreatorFee(tier.PeriodFee, params.SubscriptionCreatorBps)
	require.NoError(t, err)

	mk.storeService.store[types.UpgradeV139CompleteKey] = []byte{1}
	start := ctx.BlockTime().Unix()
	epoch, err := types.CreatorEpochFromUnix(start, epochSeconds)
	require.NoError(t, err)
	require.NoError(t, mk.SetCreatorClock(ctx, epoch))
	require.NoError(t, mk.AnchorCreatorStream(ctx, start))

	fundAccount(mk, payer, tier.PeriodFee*2)
	require.NoError(t, mk.CreateTranche(ctx, payer, subscriber,
		types.SubscriptionTrancheSource_SUBSCRIPTION_TRANCHE_SOURCE_GIFT, 1, genTxHash(220)))
	// Second purchase stacks on top: it starts when the first one expires.
	require.NoError(t, mk.CreateTranche(ctx, payer, subscriber,
		types.SubscriptionTrancheSource_SUBSCRIPTION_TRANCHE_SOURCE_GIFT, 1, genTxHash(221)))

	period := int64(params.SubscriptionPeriod) * 60
	advanceCreatorClockTo(t, mk, ctx, start+2*period+2*epochSeconds)

	paid, err := mk.CreatorStreamPaid(ctx)
	require.NoError(t, err)
	expected := sdkmath.NewIntFromUint64(creatorAmt).MulRaw(2)
	require.Equal(t, expected.String(), paid.String(),
		"both subscriptions must stream out in full across a stacked renewal")

	rate, err := mk.CreatorStreamRate(ctx)
	require.NoError(t, err)
	require.True(t, rate.IsZero(), "got %s", rate)
}

func TestFiveMinuteCreatorRewardExcludesContentDeletedInEngagementEpoch(t *testing.T) {
	settleCreatorReward(t, false, 300, true)
}

func submitCreatorEpochProposal(t *testing.T, am AppModule, ctx sdk.Context, epochSeconds uint64) {
	t.Helper()
	_, err := am.UpdateParams(ctx, &types.MsgUpdateParams{
		Authority:  authtypes.NewModuleAddress(govtypes.ModuleName).String(),
		Params:     types.Params{CreatorEpochSeconds: epochSeconds},
		UpdateMask: mask("creator_epoch_seconds"),
	})
	require.NoError(t, err)
}

// TestCreatorEpochIntervalChangeKeepsEarnedRewards pins that re-gridding epochs
// is not destructive. Changing the interval used to burn the outstanding pool
// and wipe every engagement, accrual, claim and tranche, because pools were
// pre-computed per epoch id and a new interval made those ids meaningless.
// Money is now tracked in wall-clock terms, so a change costs nobody anything.
func TestCreatorEpochIntervalChangeKeepsEarnedRewards(t *testing.T) {
	reward := settleCreatorReward(t, false, types.SecondsPerUTCDay, false)
	savedClock, err := reward.mk.GetCreatorClock(reward.ctx)
	require.NoError(t, err)
	liabilityBefore, err := reward.mk.GetCreatorLiability(reward.ctx)
	require.NoError(t, err)
	require.True(t, liabilityBefore.IsPositive())
	burnedBefore := reward.mk.bank.sentModuleToModule.AmountOf(types.MintDenom)

	submitCreatorEpochProposal(t, reward.am, reward.ctx, 300)

	liabilityAfter, err := reward.mk.GetCreatorLiability(reward.ctx)
	require.NoError(t, err)
	require.Equal(t, liabilityBefore.String(), liabilityAfter.String(), "liability must not be zeroed")
	require.Equal(t, burnedBefore, reward.mk.bank.sentModuleToModule.AmountOf(types.MintDenom),
		"the creator pool must not be burned")

	epochResponse, err := reward.am.CreatorEpoch(reward.ctx, &types.QueryCreatorEpochRequest{EpochId: reward.epoch})
	require.NoError(t, err)
	require.Equal(t, types.CreatorEpochStatus_CREATOR_EPOCH_STATUS_CLAIMABLE, epochResponse.Epoch.Status,
		"a settled epoch must survive the interval change")
	require.Equal(t, reward.deadline, epochResponse.Epoch.ClaimDeadlineUnix, "the claim window must not move")

	require.NoError(t, reward.mk.ClaimCreatorRewards(reward.ctx, reward.creator, []int64{reward.epoch}))
	require.Equal(t, reward.earned, reward.mk.bank.sentModuleToAccount.AmountOf(types.MintDenom))

	// The epoch cut short by the change reports when it actually stopped
	// accruing, not the boundary it was born with, so its payout period does
	// not appear to still be running after it settled.
	inFlight, err := reward.am.CreatorEpoch(reward.ctx, &types.QueryCreatorEpochRequest{EpochId: savedClock})
	require.NoError(t, err)
	require.Equal(t, reward.ctx.BlockTime().Unix(), inFlight.Epoch.EndUnix)
	require.Less(t, inFlight.Epoch.StartUnix, inFlight.Epoch.EndUnix)

	// Epoch ids never repeat: the new grid opens after the one in flight.
	clock, err := reward.mk.GetCreatorClock(reward.ctx)
	require.NoError(t, err)
	require.Equal(t, savedClock+1, clock)
	sched, err := reward.am.CreatorSchedule(reward.ctx, &types.QueryCreatorScheduleRequest{})
	require.NoError(t, err)
	require.Equal(t, savedClock+1, sched.OriginEpoch)
	require.Equal(t, uint64(300), sched.EpochSeconds)
}

// TestCreatorClaimWindowSurvivesIntervalShortening covers the specific hazard
// that made the destructive reset look unavoidable. Deadlines used to be epoch
// numbers, so going from daily to five-minute epochs turned "thirty days from
// now" into about two and a half hours and would have silently expired every
// outstanding claim.
func TestCreatorClaimWindowSurvivesIntervalShortening(t *testing.T) {
	reward := settleCreatorReward(t, false, types.SecondsPerUTCDay, false)
	submitCreatorEpochProposal(t, reward.am, reward.ctx, 300)

	almostExpired := reward.ctx.WithBlockTime(time.Unix(reward.deadline-1, 0))
	require.NoError(t, reward.mk.ClaimCreatorRewards(almostExpired, reward.creator, []int64{reward.epoch}),
		"the full wall-clock window must still be open after shortening the interval")
}

// TestCreatorEpochIntervalLengthensMonotonically keeps ids increasing when the
// interval grows, where a naive rebase onto unix/seconds would move them
// backwards and collide with epochs that already settled.
func TestCreatorEpochIntervalLengthensMonotonically(t *testing.T) {
	reward := settleCreatorReward(t, false, 300, false)
	savedClock, err := reward.mk.GetCreatorClock(reward.ctx)
	require.NoError(t, err)

	submitCreatorEpochProposal(t, reward.am, reward.ctx, types.SecondsPerUTCDay)

	clock, err := reward.mk.GetCreatorClock(reward.ctx)
	require.NoError(t, err)
	require.Equal(t, savedClock+1, clock)
	unixRebase, err := types.CreatorEpochFromUnix(reward.ctx.BlockTime().Unix(), types.SecondsPerUTCDay)
	require.NoError(t, err)
	require.Greater(t, clock, unixRebase)
}
