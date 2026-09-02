package core

import (
	"encoding/json"
	"math"
	"testing"
	"time"

	sdk "github.com/cosmos/cosmos-sdk/types"
	authtypes "github.com/cosmos/cosmos-sdk/x/auth/types"
	govtypes "github.com/cosmos/cosmos-sdk/x/gov/types"
	"github.com/stretchr/testify/require"

	"mirage/x/core/types"
)

func saveTestProfile(t *testing.T, mk *mockKeeper, ctx sdk.Context, core types.ProfileCore) {
	t.Helper()
	bz, err := json.Marshal(&core)
	require.NoError(t, err)
	require.NoError(t, mk.SetProfileCore(ctx, core.Owner, bz))
}

func TestGiftedAdminSubscriptionPreservesCurationEligibility(t *testing.T) {
	mk, ctx, _ := setupModule(t)
	payer := genAddr(101)
	admin := genAddr(102)
	ensureUsername(t, mk, ctx, payer, "gift-payer")
	ensureUsername(t, mk, ctx, admin, "gift-admin")
	adminCore := loadCore(t, mk, ctx, admin)
	adminCore.Level = types.LevelAdminMin
	saveTestProfile(t, mk, ctx, adminCore)

	teamID, err := mk.CreateCurationTeam(ctx, admin, "gift-admin-team", "Admin", "")
	require.NoError(t, err)
	tier := mk.GetParams(ctx).GetTierConfig(types.LevelSubscriber)
	require.NotNil(t, tier)
	fundAccount(mk, payer, tier.PeriodFee*2)

	require.NoError(t, mk.CreateTranche(ctx, payer, admin,
		types.SubscriptionTrancheSource_SUBSCRIPTION_TRANCHE_SOURCE_GIFT, 1, genTxHash(901)))
	require.NoError(t, mk.CreateTranche(ctx, payer, admin,
		types.SubscriptionTrancheSource_SUBSCRIPTION_TRANCHE_SOURCE_GIFT, 1, genTxHash(902)))
	team, found, err := mk.GetCurationTeam(ctx, "gift-admin-team", teamID)
	require.NoError(t, err)
	require.True(t, found)
	require.Equal(t, uint64(1), team.SubscriberCount)
	require.Equal(t, int32(types.LevelAdminMin), loadCore(t, mk, ctx, admin).Level)

	require.NoError(t, mk.TransitionPaidState(ctx, admin, false))
	team, found, err = mk.GetCurationTeam(ctx, "gift-admin-team", teamID)
	require.NoError(t, err)
	require.True(t, found)
	require.Zero(t, team.DeletedHeight)
	require.Equal(t, admin, team.Owner)
	require.Equal(t, uint64(1), team.SubscriberCount)
	core := loadCore(t, mk, ctx, admin)
	require.Equal(t, int32(types.LevelAdminMin), core.Level)
	require.False(t, core.EffectivePaid)
}

func TestSubscriptionEligibilityTransitionsExactlyOnce(t *testing.T) {
	mk, ctx, _ := setupModule(t)
	payer := genAddr(103)
	subscriber := genAddr(104)
	owner := genAddr(105)
	for addr, name := range map[string]string{
		payer: "transition-payer", subscriber: "transition-subscriber", owner: "transition-owner",
	} {
		ensureUsername(t, mk, ctx, addr, name)
	}
	ownerCore := loadCore(t, mk, ctx, owner)
	ownerCore.Level = types.LevelAdminMin
	saveTestProfile(t, mk, ctx, ownerCore)
	teamID, err := mk.CreateCurationTeam(ctx, owner, "transition-team", "Owner", "")
	require.NoError(t, err)
	freeTier := mk.GetParams(ctx).GetTierConfig(types.LevelFree)
	require.NotNil(t, freeTier)
	require.NoError(t, mk.JoinCommunity(ctx, subscriber, "transition-team", uint32(freeTier.MaxJoinedCommunities)))
	require.NoError(t, mk.SetCurationPreference(ctx, subscriber, "transition-team",
		types.CurationPreferenceMode_CURATION_PREFERENCE_MODE_PINNED, teamID, false))

	tier := mk.GetParams(ctx).GetTierConfig(types.LevelSubscriber)
	require.NotNil(t, tier)
	fundAccount(mk, payer, tier.PeriodFee*2)
	require.NoError(t, mk.CreateTranche(ctx, payer, subscriber,
		types.SubscriptionTrancheSource_SUBSCRIPTION_TRANCHE_SOURCE_GIFT, 1, genTxHash(903)))
	require.NoError(t, mk.CreateTranche(ctx, payer, subscriber,
		types.SubscriptionTrancheSource_SUBSCRIPTION_TRANCHE_SOURCE_GIFT, 1, genTxHash(904)))
	team, _, err := mk.GetCurationTeam(ctx, "transition-team", teamID)
	require.NoError(t, err)
	require.Equal(t, uint64(2), team.SubscriberCount)
	core := loadCore(t, mk, ctx, subscriber)
	require.Equal(t, int32(types.LevelSubscriber), core.Level)
	require.True(t, core.EffectivePaid)

	core.EffectivePaid = false
	core.Level = types.LevelSubscriber
	saveTestProfile(t, mk, ctx, core)
	require.NoError(t, mk.TransitionPaidState(ctx, subscriber, false))
	require.Equal(t, int32(types.LevelFree), loadCore(t, mk, ctx, subscriber).Level)
}

func TestSetLevelTransitionsCurationAndRejectsSubscriptionLevels(t *testing.T) {
	mk, ctx, am := setupModule(t)
	gov := authtypes.NewModuleAddress(govtypes.ModuleName).String()
	owner := genAddr(106)
	target := genAddr(107)
	secondOwner := genAddr(108)
	for addr, name := range map[string]string{owner: "level-owner", target: "level-target", secondOwner: "level-second"} {
		ensureUsername(t, mk, ctx, addr, name)
		if addr != target {
			core := loadCore(t, mk, ctx, addr)
			core.Level = types.LevelAdminMin
			saveTestProfile(t, mk, ctx, core)
		}
	}
	teamID, err := mk.CreateCurationTeam(ctx, owner, "level-team", "Primary", "")
	require.NoError(t, err)
	secondTeamID, err := mk.CreateCurationTeam(ctx, secondOwner, "level-second", "Secondary", "")
	require.NoError(t, err)
	freeTier := mk.GetParams(ctx).GetTierConfig(types.LevelFree)
	require.NoError(t, mk.JoinCommunity(ctx, target, "level-team", uint32(freeTier.MaxJoinedCommunities)))
	require.NoError(t, mk.SetCurationPreference(ctx, target, "level-team",
		types.CurationPreferenceMode_CURATION_PREFERENCE_MODE_PINNED, teamID, false))

	_, err = am.SetLevel(ctx, &types.MsgSetLevel{Authority: gov, Target: target, Level: types.LevelAdminMin})
	require.NoError(t, err)
	team, _, err := mk.GetCurationTeam(ctx, "level-team", teamID)
	require.NoError(t, err)
	require.Equal(t, uint64(2), team.SubscriberCount)
	require.NoError(t, mk.InviteCurator(ctx, owner, "level-team", teamID, target))
	require.NoError(t, mk.AcceptCuratorInvite(ctx, target, "level-team", teamID))
	require.NoError(t, mk.InviteCurator(ctx, secondOwner, "level-second", secondTeamID, target))

	for _, level := range []int32{types.LevelSubscriber, types.LevelAgent} {
		_, err := am.SetLevel(ctx, &types.MsgSetLevel{Authority: gov, Target: target, Level: level})
		require.ErrorContains(t, err, "must be 0 or >= 100")
		require.Equal(t, int32(types.LevelAdminMin), loadCore(t, mk, ctx, target).Level)
	}
	_, err = am.SetLevel(ctx, &types.MsgSetLevel{Authority: genAddr(109), Target: target, Level: 0})
	require.ErrorContains(t, err, "only governance")

	_, err = am.SetLevel(ctx, &types.MsgSetLevel{Authority: gov, Target: target, Level: types.LevelFree})
	require.NoError(t, err)
	team, _, err = mk.GetCurationTeam(ctx, "level-team", teamID)
	require.NoError(t, err)
	require.Equal(t, uint64(1), team.SubscriberCount)
	memberValue, err := mk.GetRaw(ctx, types.KeyCurationTeamUser(target, "level-team"))
	require.NoError(t, err)
	require.Empty(t, memberValue)
	invitations, _, err := mk.GetPendingCuratorInvitationsPaginated(ctx, target, nil, 10)
	require.NoError(t, err)
	require.Empty(t, invitations)
}

func TestSetLevelRemovesAdminRoleWithoutDestroyingActiveSubscription(t *testing.T) {
	mk, ctx, am := setupModule(t)
	target := genAddr(126)
	ensureUsername(t, mk, ctx, target, "paid-admin")
	core := loadCore(t, mk, ctx, target)
	core.Level = types.LevelAdminMin
	core.EffectivePaid = true
	core.SubscriptionExpiry = ctx.BlockTime().Unix() + 3600
	saveTestProfile(t, mk, ctx, core)

	_, err := am.SetLevel(ctx, &types.MsgSetLevel{
		Authority: authtypes.NewModuleAddress(govtypes.ModuleName).String(),
		Target:    target, Level: types.LevelFree,
	})
	require.NoError(t, err)
	core = loadCore(t, mk, ctx, target)
	require.Equal(t, int32(types.LevelSubscriber), core.Level)
	require.True(t, core.EffectivePaid)
	require.NotZero(t, core.SubscriptionExpiry)
}

func TestMigrateV139NormalizesExpiryAndPreservesGovernedParams(t *testing.T) {
	mk, baseCtx, _ := setupModule(t)
	ctx := baseCtx.WithBlockTime(time.Unix(2_000_000_000, 0))
	expiries := []int64{ctx.BlockTime().Unix() - 1, ctx.BlockTime().Unix(), ctx.BlockTime().Unix() + 1}
	owners := []string{genAddr(110), genAddr(111), genAddr(112)}
	for i, owner := range owners {
		saveTestProfile(t, mk, ctx, types.ProfileCore{
			Owner: owner, Username: "migration-user", Level: types.LevelSubscriber,
			EffectivePaid: true, SubscriptionExpiry: expiries[i],
		})
		require.NoError(t, mk.SetSubscription(ctx, owner, types.LevelSubscriber, expiries[i]))
	}

	stored := types.DefaultParams()
	stored.MinDifficulty = 11
	stored.PowMessageWindow = 30
	stored.PowMessageLimit = 50
	stored.PowCalmPeriodDefinition = 20
	stored.PowCalmSequenceThreshold = 101
	stored.MintInterval = 201
	stored.MintQuantity = 124_000_000_000
	stored.BlockHashWindow = 70
	stored.PowDifficultyAllowance = 3
	stored.MinUsernameSize = 4
	stored.MaxUsernameSize = 40
	stored.MinCommunitySize = 3
	stored.MaxCommunitySize = 40
	stored.MintDynamicCreditCap = 31
	stored.MintDynamicSplit = 0.11
	stored.MintFloorSplit = 0.21
	stored.SubscriptionPeriod = 40_000
	stored.RelayMinGasPrice = 2_000
	stored.RelayMaxGasFee = 600_000_000
	stored.MaxEnvelopeAge = 120
	stored.PowDifficultyStep = 0.30
	stored.AwardConfigs = []*types.AwardConfig{{Name: "migration-award", Cost: 123}}
	stored.SubscriptionReserveBps = 9_500
	stored.SubscriptionCreatorBps = 0
	require.NoError(t, mk.SetParams(ctx, stored))

	require.NoError(t, mk.MigrateV139(ctx))
	for i, owner := range owners {
		core := loadCore(t, mk, ctx, owner)
		if i < 2 {
			require.Equal(t, int32(types.LevelFree), core.Level)
			require.False(t, core.EffectivePaid)
		} else {
			require.Equal(t, int32(types.LevelSubscriber), core.Level)
			require.True(t, core.EffectivePaid)
		}
	}

	expected := stored
	defaults := types.DefaultParams()
	expected.Tiers = defaults.Tiers
	expected.SubscriptionReserveBps = 0
	expected.SubscriptionCreatorBps = defaults.SubscriptionCreatorBps
	expected.MaxCuratorsPerTeam = defaults.MaxCuratorsPerTeam
	expected.MaxPendingCuratorInvitesPerTeam = defaults.MaxPendingCuratorInvitesPerTeam
	expected.MaxPendingCuratorInvitesPerUser = defaults.MaxPendingCuratorInvitesPerUser
	expected.MaxCurationTeamNameLength = defaults.MaxCurationTeamNameLength
	expected.MaxCurationTeamDescriptionLength = defaults.MaxCurationTeamDescriptionLength
	expected.SubscriptionTransitionsPerBlock = defaults.SubscriptionTransitionsPerBlock
	expected.CurationPruneKeysPerBlock = defaults.CurationPruneKeysPerBlock
	expected.CreatorEpochClosuresPerBlock = defaults.CreatorEpochClosuresPerBlock
	expected.CreatorSettlementRecordsPerBlock = defaults.CreatorSettlementRecordsPerBlock
	expected.CreatorPruneKeysPerBlock = defaults.CreatorPruneKeysPerBlock
	expected.CreatorClaimWindowDays = defaults.CreatorClaimWindowDays
	expected.MaxCreatorClaimEpochs = defaults.MaxCreatorClaimEpochs
	expected.MaxCreatorEngagementsPerEpoch = defaults.MaxCreatorEngagementsPerEpoch
	expected.CreatorEpochExpiriesPerBlock = defaults.CreatorEpochExpiriesPerBlock
	expected.SubscriptionEarlyRenewalDays = defaults.SubscriptionEarlyRenewalDays
	expected.SubscriptionRenewalAttemptsPerBlock = defaults.SubscriptionRenewalAttemptsPerBlock
	expected.SubscriberDailyRelayLimit = defaults.SubscriberDailyRelayLimit
	expected.MaxSubscriptionPeriodsPerPurchase = defaults.MaxSubscriptionPeriodsPerPurchase
	expected.CreatorEpochSeconds = defaults.CreatorEpochSeconds
	require.Equal(t, expected, mk.GetParams(ctx))
}

func TestZeroCapsDisablePublicAndGovernanceAdds(t *testing.T) {
	mk, ctx, am := setupModule(t)
	pub, owner := testPubkeyOwner()
	params := mk.GetParams(ctx)
	params.Tiers[0].MaxJoinedCommunities = 0
	params.Tiers[0].MaxBlockedCommunities = 0
	require.NoError(t, mk.SetParams(ctx, params))

	_, err := am.JoinCommunity(ctx, &types.MsgJoinCommunity{EnvelopePubkey: pub, Community: "disabled-join"})
	require.ErrorContains(t, err, "cap is zero")
	_, joined, err := mk.GetPreference(ctx, owner, "disabled-join")
	require.NoError(t, err)
	require.False(t, joined)

	_, err = am.GovSetCommunityBlock(ctx, &types.MsgGovSetCommunityBlock{
		Authority: authtypes.NewModuleAddress(govtypes.ModuleName).String(),
		Owner:     owner, Community: "disabled-block", Blocked: true,
	})
	require.ErrorContains(t, err, "cap is zero")
	blocked, err := mk.ListBlockedCommunities(ctx, owner)
	require.NoError(t, err)
	require.Empty(t, blocked)
}

func TestV139SequencesRejectUint64OverflowBeforeWrites(t *testing.T) {
	mk, ctx, _ := setupModule(t)
	owner := genAddr(124)
	require.NoError(t, mk.SetRawKVPair(ctx, types.KeyBlockCommunityNext(owner), u64Test(math.MaxUint64)))
	require.ErrorContains(t, mk.AddBlockedCommunity(ctx, owner, "overflow-block", 10), "overflow")
	blocked, err := mk.ListBlockedCommunities(ctx, owner)
	require.NoError(t, err)
	require.Empty(t, blocked)

	require.NoError(t, mk.SetRawKVPair(ctx, []byte(types.PfxTrancheSeq), u64Test(math.MaxUint64)))
	require.ErrorContains(t, mk.CreateTranche(ctx, owner, owner,
		types.SubscriptionTrancheSource_SUBSCRIPTION_TRANCHE_SOURCE_GIFT, 1, ""), "overflow")
	found, err := mk.GetProto(ctx, types.KeyTranche(math.MaxUint64), &types.SubscriptionTranche{})
	require.NoError(t, err)
	require.False(t, found)
}
