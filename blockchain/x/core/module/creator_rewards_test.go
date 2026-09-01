package core

import (
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
	params.CreatorEpochSeconds = epochSeconds
	if epochSeconds < types.SecondsPerUTCDay {
		params.SubscriptionPeriod = 60
		params.SubscriptionEarlyRenewalDays = 0
		params.MaxSubscriptionPeriodsPerPurchase = 1
	}
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
		deadline:   epochResponse.Epoch.ClaimDeadlineEpoch,
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

func TestCreatorRewardDirectReplyExpiresAfterClaimWindow(t *testing.T) {
	reward := settleCreatorReward(t, true, 300, false)
	require.Equal(t, reward.epoch+2+(30*288), reward.deadline)
	expiryTime, err := types.CreatorEpochStart(reward.deadline, 300)
	require.NoError(t, err)
	expiryCtx := reward.ctx.
		WithBlockHeight(reward.ctx.BlockHeight() + 1).
		WithBlockTime(time.Unix(expiryTime, 0)).
		WithEventManager(sdk.NewEventManager())
	require.NoError(t, reward.mk.ProcessBeginBlockV139(expiryCtx))

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

func TestFiveMinuteCreatorRewardExcludesContentDeletedInEngagementEpoch(t *testing.T) {
	settleCreatorReward(t, false, 300, true)
}

func submitCreatorEpochProposal(t *testing.T, am AppModule, ctx sdk.Context, epochSeconds, prunePerBlock uint64) {
	t.Helper()
	updates := types.Params{
		CreatorEpochSeconds:               epochSeconds,
		SubscriptionPeriod:                60,
		SubscriptionEarlyRenewalDays:      0,
		MaxSubscriptionPeriodsPerPurchase: 1,
		CreatorPruneKeysPerBlock:          prunePerBlock,
	}
	paths := []string{
		"creator_epoch_seconds",
		"subscription_period",
		"subscription_early_renewal_days",
		"max_subscription_periods_per_purchase",
	}
	if prunePerBlock != 0 {
		paths = append(paths, "creator_prune_keys_per_block")
	}
	_, err := am.UpdateParams(ctx, &types.MsgUpdateParams{
		Authority:  authtypes.NewModuleAddress(govtypes.ModuleName).String(),
		Params:     updates,
		UpdateMask: mask(paths...),
	})
	require.NoError(t, err)
}

func drainCreatorReset(t *testing.T, mk *mockKeeper, ctx sdk.Context) sdk.Context {
	t.Helper()
	for i := 0; i < 10_000; i++ {
		ctx = ctx.WithBlockHeight(ctx.BlockHeight() + 1).WithEventManager(sdk.NewEventManager())
		require.NoError(t, mk.ProcessBeginBlockV139(ctx))
		inProgress, err := mk.CreatorResetInProgress(ctx)
		require.NoError(t, err)
		if !inProgress {
			return ctx
		}
	}
	t.Fatal("creator reset did not finish within 10000 blocks")
	return ctx
}

func TestCreatorEpochResetWipesStateAndKeepsIDsMonotonic(t *testing.T) {
	reward := settleCreatorReward(t, false, types.SecondsPerUTCDay, false)
	savedClock, err := reward.mk.GetCreatorClock(reward.ctx)
	require.NoError(t, err)
	liability, err := reward.mk.GetCreatorLiability(reward.ctx)
	require.NoError(t, err)
	require.True(t, liability.IsPositive())
	pool := authtypes.NewModuleAddress(types.CreatorPoolName).String()
	if reward.mk.bank.balances == nil {
		reward.mk.bank.balances = map[string]sdkmath.Int{}
	}
	reward.mk.bank.balances[pool] = liability

	submitCreatorEpochProposal(t, reward.am, reward.ctx, 300, 1)
	inProgress, err := reward.mk.CreatorResetInProgress(reward.ctx)
	require.NoError(t, err)
	require.True(t, inProgress)
	require.ErrorContains(
		t,
		reward.mk.ClaimCreatorRewards(reward.ctx, reward.creator, []int64{reward.epoch}),
		"creator reward reset in progress",
	)
	fundAccount(reward.mk, reward.payer, 1)
	require.ErrorContains(
		t,
		reward.mk.CreateTranche(
			reward.ctx,
			reward.payer,
			reward.subscriber,
			types.SubscriptionTrancheSource_SUBSCRIPTION_TRANCHE_SOURCE_GIFT,
			1,
			genTxHash(301),
		),
		"creator reward reset in progress",
	)
	require.NoError(t, reward.mk.RecordUpvoteEngagement(reward.ctx, reward.subscriber, reward.target, 1))

	first := reward.ctx.WithBlockHeight(reward.ctx.BlockHeight() + 1).WithEventManager(sdk.NewEventManager())
	require.NoError(t, reward.mk.ProcessBeginBlockV139(first))
	inProgress, err = reward.mk.CreatorResetInProgress(first)
	require.NoError(t, err)
	require.True(t, inProgress, "a 1-key budget must leave the reset unfinished")

	ctx := drainCreatorReset(t, reward.mk, first)
	require.Greater(t, ctx.BlockHeight(), first.BlockHeight())
	hasState, err := reward.mk.HasCreatorRewardState(ctx)
	require.NoError(t, err)
	require.False(t, hasState)
	liability, err = reward.mk.GetCreatorLiability(ctx)
	require.NoError(t, err)
	require.True(t, liability.IsZero())
	require.True(t, reward.mk.bank.sentModuleToModule.AmountOf(types.MintDenom).IsPositive())

	clock, err := reward.mk.GetCreatorClock(ctx)
	require.NoError(t, err)
	require.Equal(t, savedClock+1, clock)
	unixRebase, err := types.CreatorEpochFromUnix(ctx.BlockTime().Unix(), 300)
	require.NoError(t, err)
	require.NotEqual(t, unixRebase, clock)

	sched, err := reward.am.CreatorSchedule(ctx, &types.QueryCreatorScheduleRequest{})
	require.NoError(t, err)
	require.Equal(t, savedClock+1, sched.OriginEpoch)
	require.Equal(t, uint64(300), sched.EpochSeconds)
	require.False(t, sched.ResetInProgress)

	_, err = reward.am.CreatorEpoch(ctx, &types.QueryCreatorEpochRequest{EpochId: reward.epoch})
	require.Error(t, err)

	_, subscriber2 := curationSigner(0x64)
	ensureUsername(t, reward.mk, ctx, subscriber2, "reward-subscriber-2")
	tier := reward.mk.GetParams(ctx).GetTierConfig(types.LevelSubscriber)
	fundAccount(reward.mk, reward.payer, tier.PeriodFee)
	require.NoError(t, reward.mk.CreateTranche(
		ctx,
		reward.payer,
		subscriber2,
		types.SubscriptionTrancheSource_SUBSCRIPTION_TRANCHE_SOURCE_GIFT,
		1,
		genTxHash(302),
	))
	require.NoError(t, reward.mk.RecordUpvoteEngagement(ctx, subscriber2, reward.target, 1))
	settlementTime, err := types.CreatorSchedule{
		OriginEpoch:  sched.OriginEpoch,
		OriginUnix:   sched.OriginUnix,
		EpochSeconds: sched.EpochSeconds,
	}.EpochEnd(clock)
	require.NoError(t, err)
	settledCtx := ctx.
		WithBlockHeight(ctx.BlockHeight() + 1).
		WithBlockTime(time.Unix(settlementTime+1, 0)).
		WithEventManager(sdk.NewEventManager())
	require.NoError(t, reward.mk.ProcessBeginBlockV139(settledCtx))
	epochResponse, err := reward.am.CreatorEpoch(settledCtx, &types.QueryCreatorEpochRequest{EpochId: clock})
	require.NoError(t, err)
	require.Equal(t, types.CreatorEpochStatus_CREATOR_EPOCH_STATUS_CLAIMABLE, epochResponse.Epoch.Status)
	require.NoError(t, reward.mk.ClaimCreatorRewards(settledCtx, reward.creator, []int64{clock}))
}

func TestCreatorEpochResetLengthensIntervalMonotonically(t *testing.T) {
	reward := settleCreatorReward(t, false, 300, false)
	savedClock, err := reward.mk.GetCreatorClock(reward.ctx)
	require.NoError(t, err)
	submitCreatorEpochProposal(t, reward.am, reward.ctx, types.SecondsPerUTCDay, 1000)
	ctx := drainCreatorReset(t, reward.mk, reward.ctx)
	clock, err := reward.mk.GetCreatorClock(ctx)
	require.NoError(t, err)
	require.Equal(t, savedClock+1, clock)
	unixRebase, err := types.CreatorEpochFromUnix(ctx.BlockTime().Unix(), types.SecondsPerUTCDay)
	require.NoError(t, err)
	require.Greater(t, clock, unixRebase)
	hasState, err := reward.mk.HasCreatorRewardState(ctx)
	require.NoError(t, err)
	require.False(t, hasState)
}
