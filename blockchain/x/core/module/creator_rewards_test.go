package core

import (
	"testing"
	"time"

	sdkmath "cosmossdk.io/math"
	sdk "github.com/cosmos/cosmos-sdk/types"
	"github.com/stretchr/testify/require"

	"mirage/x/core/types"
)

type settledCreatorReward struct {
	mk       *mockKeeper
	am       AppModule
	ctx      sdk.Context
	creator  string
	target   string
	epoch    int64
	earned   sdkmath.Int
	deadline int64
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
		return settledCreatorReward{mk: mk, am: am, ctx: settledCtx, creator: creator, target: target, epoch: epoch}
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
		mk:       mk,
		am:       am,
		ctx:      settledCtx,
		creator:  creator,
		target:   target,
		epoch:    epoch,
		earned:   earned,
		deadline: epochResponse.Epoch.ClaimDeadlineEpoch,
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
