package core

import (
	"encoding/json"
	"strings"
	"testing"

	sdk "github.com/cosmos/cosmos-sdk/types"
	"github.com/stretchr/testify/require"

	"mirage/x/core/types"
)

func setPaidProfile(t *testing.T, mk *mockKeeper, ctx sdk.Context, owner string) {
	t.Helper()
	ensureUsername(t, mk, ctx, owner, "Anon-"+owner[len(owner)-6:])
	bz, found, err := mk.GetProfileCore(ctx, owner)
	require.NoError(t, err)
	require.True(t, found)
	var core types.ProfileCore
	require.NoError(t, json.Unmarshal(bz, &core))
	core.EffectivePaid = true
	core.Level = types.LevelSubscriber
	core.SubscriptionExpiry = ctx.BlockTime().Unix() + 86400
	out, err := json.Marshal(&core)
	require.NoError(t, err)
	require.NoError(t, mk.SetProfileCore(ctx, owner, out))
}

func joinOpenCommunity(t *testing.T, mk *mockKeeper, ctx sdk.Context, owner, slug string) {
	t.Helper()
	params := mk.GetParams(ctx)
	tier := params.GetTierConfig(types.LevelSubscriber)
	require.NotNil(t, tier)
	require.NoError(t, mk.JoinCommunity(ctx, owner, slug, uint32(tier.MaxJoinedCommunities)))
}

func TestOpenCommunityCurationLifecycle(t *testing.T) {
	mk, ctx, _ := setupModule(t)
	leader := genAddr(31)
	curator := genAddr(32)
	slug := "open-community"
	setPaidProfile(t, mk, ctx, leader)
	setPaidProfile(t, mk, ctx, curator)
	joinOpenCommunity(t, mk, ctx, leader, slug)
	joinOpenCommunity(t, mk, ctx, curator, slug)
	unjoined := genAddr(35)
	setPaidProfile(t, mk, ctx, unjoined)
	lonelySlug := "lonely-community"
	unjoinedTeamID, err := mk.CreateCurationTeam(ctx, unjoined, lonelySlug, "Unjoined", "")
	require.NoError(t, err, "paid user may create a curator team without joining first")
	require.Equal(t, uint64(1), unjoinedTeamID)
	t.Logf("[debug] unjoined create community=%s team_id=%d", lonelySlug, unjoinedTeamID)

	teamID, err := mk.CreateCurationTeam(ctx, leader, slug, "Signal", "Team description")
	require.NoError(t, err)
	require.Equal(t, uint64(1), teamID)
	require.NoError(t, mk.InviteCurator(ctx, leader, slug, teamID, curator))
	require.NoError(t, mk.AcceptCuratorInvite(ctx, curator, slug, teamID))
	members, nextKey, err := mk.GetCurationTeamMembersPaginated(
		ctx,
		types.KeyCurationTeamMemberPrefix(slug, teamID),
		nil,
		1,
	)
	require.NoError(t, err)
	require.Len(t, members, 1)
	require.NotEmpty(t, nextKey)
	members, finalKey, err := mk.GetCurationTeamMembersPaginated(
		ctx,
		types.KeyCurationTeamMemberPrefix(slug, teamID),
		nextKey,
		1,
	)
	require.NoError(t, err)
	require.Len(t, members, 1)
	require.Empty(t, finalKey)

	require.NoError(t, mk.SetCurationPreference(
		ctx,
		curator,
		slug,
		types.CurationPreferenceMode_CURATION_PREFERENCE_MODE_PINNED,
		teamID,
		true,
	))
	team, found, err := mk.GetCurationTeam(ctx, slug, teamID)
	require.NoError(t, err)
	require.True(t, found)
	require.Equal(t, "Team description", team.Description)
	require.Equal(t, uint64(1), team.SubscriberCount)
	require.NoError(t, mk.SetCurationPreference(
		ctx,
		curator,
		slug,
		types.CurationPreferenceMode_CURATION_PREFERENCE_MODE_PINNED,
		teamID,
		true,
	))
	team, _, err = mk.GetCurationTeam(ctx, slug, teamID)
	require.NoError(t, err)
	require.Equal(t, uint64(1), team.SubscriberCount)
	require.NoError(t, mk.SetCurationPreference(
		ctx,
		curator,
		slug,
		types.CurationPreferenceMode_CURATION_PREFERENCE_MODE_RAW,
		0,
		true,
	))
	team, _, err = mk.GetCurationTeam(ctx, slug, teamID)
	require.NoError(t, err)
	require.Zero(t, team.SubscriberCount)

	free := genAddr(33)
	ensureUsername(t, mk, ctx, free, "Anon-free")
	freeTier := mk.GetParams(ctx).GetTierConfig(types.LevelFree)
	require.NotNil(t, freeTier)
	require.NoError(t, mk.JoinCommunity(ctx, free, slug, uint32(freeTier.MaxJoinedCommunities)))
	_, err = mk.CreateCurationTeam(ctx, free, slug, "Free", "")
	require.ErrorContains(t, err, "active subscriber or admin")
	require.NoError(t, mk.SetCurationPreference(
		ctx,
		free,
		slug,
		types.CurationPreferenceMode_CURATION_PREFERENCE_MODE_PINNED,
		teamID,
		false,
	))
	team, _, err = mk.GetCurationTeam(ctx, slug, teamID)
	require.NoError(t, err)
	require.Zero(t, team.SubscriberCount)

	watcher := genAddr(34)
	setPaidProfile(t, mk, ctx, watcher)
	joinOpenCommunity(t, mk, ctx, watcher, slug)
	require.NoError(t, mk.SetCurationPreference(
		ctx,
		watcher,
		slug,
		types.CurationPreferenceMode_CURATION_PREFERENCE_MODE_PINNED,
		teamID,
		true,
	))
	require.NoError(t, mk.LeaveCommunity(ctx, watcher, slug, true))
	team, _, err = mk.GetCurationTeam(ctx, slug, teamID)
	require.NoError(t, err)
	require.Zero(t, team.SubscriberCount)
	require.NoError(t, mk.SetCurationPreference(
		ctx,
		curator,
		slug,
		types.CurationPreferenceMode_CURATION_PREFERENCE_MODE_PINNED,
		teamID,
		true,
	))

	require.NoError(t, mk.DeleteCurationTeam(ctx, slug, teamID))
	team, found, err = mk.GetCurationTeam(ctx, slug, teamID)
	require.NoError(t, err)
	require.True(t, found)
	require.NotZero(t, team.DeletedHeight)
	require.Zero(t, team.SubscriberCount)

	joined, stored, effective, storedTeam, effectiveTeam, err := mk.ResolveEffectivePreference(ctx, curator, slug)
	require.NoError(t, err)
	require.True(t, joined)
	require.Equal(t, types.CurationPreferenceMode_CURATION_PREFERENCE_MODE_PINNED, stored)
	require.Equal(t, types.CurationPreferenceMode_CURATION_PREFERENCE_MODE_LIVE_DEFAULT, effective)
	require.Equal(t, teamID, storedTeam)
	require.Zero(t, effectiveTeam)

	live, _, err := mk.GetCurationTeamsPaginated(ctx, types.KeyCurationTeamPrefix(slug), nil, 10, false)
	require.NoError(t, err)
	require.Empty(t, live)
	all, _, err := mk.GetCurationTeamsPaginated(ctx, types.KeyCurationTeamPrefix(slug), nil, 10, true)
	require.NoError(t, err)
	require.Len(t, all, 1)
}

func TestCurationTeamMemberAndPendingInviteCap(t *testing.T) {
	mk, ctx, _ := setupModule(t)
	leader := genAddr(61)
	slug := "ten-curators"
	setPaidProfile(t, mk, ctx, leader)
	joinOpenCommunity(t, mk, ctx, leader, slug)
	teamID, err := mk.CreateCurationTeam(ctx, leader, slug, "Ten", "")
	require.NoError(t, err)

	var curators []string
	for i := byte(62); i <= 71; i++ {
		curator := genAddr(i)
		setPaidProfile(t, mk, ctx, curator)
		joinOpenCommunity(t, mk, ctx, curator, slug)
		curators = append(curators, curator)
	}
	for _, curator := range curators[:8] {
		require.NoError(t, mk.InviteCurator(ctx, leader, slug, teamID, curator))
		require.NoError(t, mk.AcceptCuratorInvite(ctx, curator, slug, teamID))
	}
	require.ErrorContains(t, mk.InviteCurator(ctx, curators[0], slug, teamID, curators[9]), "only the team owner")
	require.NoError(t, mk.InviteCurator(ctx, leader, slug, teamID, curators[8]))
	require.ErrorContains(t, mk.InviteCurator(ctx, leader, slug, teamID, curators[9]), "team capacity")
	require.NoError(t, mk.AcceptCuratorInvite(ctx, curators[8], slug, teamID))

	otherLeader := genAddr(72)
	setPaidProfile(t, mk, ctx, otherLeader)
	joinOpenCommunity(t, mk, ctx, otherLeader, slug)
	otherTeamID, err := mk.CreateCurationTeam(ctx, otherLeader, slug, "Other", "")
	require.NoError(t, err)
	require.ErrorContains(t, mk.InviteCurator(ctx, otherLeader, slug, otherTeamID, curators[0]), "already curates")
}

func TestLeaderExpiryTransfersToEarliestPaidCurator(t *testing.T) {
	mk, ctx, _ := setupModule(t)
	leader := genAddr(41)
	first := genAddr(42)
	second := genAddr(43)
	slug := "expiry-transfer"
	for _, owner := range []string{leader, first, second} {
		setPaidProfile(t, mk, ctx, owner)
		joinOpenCommunity(t, mk, ctx, owner, slug)
	}
	teamID, err := mk.CreateCurationTeam(ctx, leader, slug, "Expiry", "")
	require.NoError(t, err)
	for _, curator := range []string{first, second} {
		require.NoError(t, mk.InviteCurator(ctx, leader, slug, teamID, curator))
		require.NoError(t, mk.AcceptCuratorInvite(ctx, curator, slug, teamID))
	}

	require.NoError(t, mk.TransitionPaidState(ctx, leader, false))
	team, found, err := mk.GetCurationTeam(ctx, slug, teamID)
	require.NoError(t, err)
	require.True(t, found)
	require.Equal(t, first, team.Owner)

	soloLeader := genAddr(44)
	watcher := genAddr(45)
	soloSlug := "expiry-delete"
	for _, owner := range []string{soloLeader, watcher} {
		setPaidProfile(t, mk, ctx, owner)
		joinOpenCommunity(t, mk, ctx, owner, soloSlug)
	}
	soloTeamID, err := mk.CreateCurationTeam(ctx, soloLeader, soloSlug, "Solo", "")
	require.NoError(t, err)
	require.NoError(t, mk.SetCurationPreference(
		ctx,
		watcher,
		soloSlug,
		types.CurationPreferenceMode_CURATION_PREFERENCE_MODE_PINNED,
		soloTeamID,
		true,
	))
	require.NoError(t, mk.TransitionPaidState(ctx, soloLeader, false))
	soloTeam, found, err := mk.GetCurationTeam(ctx, soloSlug, soloTeamID)
	require.NoError(t, err)
	require.True(t, found)
	require.NotZero(t, soloTeam.DeletedHeight)
	require.Zero(t, soloTeam.SubscriberCount)
}

func TestV139MigrationRecountsPinnedPaidSubscribersAndDropsCommunityState(t *testing.T) {
	mk, ctx, _ := setupModule(t)
	leader := genAddr(51)
	subscriber := genAddr(52)
	slug := "legacy-community"
	for _, owner := range []string{leader, subscriber} {
		setPaidProfile(t, mk, ctx, owner)
		require.NoError(t, mk.SetSubscription(ctx, owner, types.LevelSubscriber, ctx.BlockTime().Unix()+86400))
		joinOpenCommunity(t, mk, ctx, owner, slug)
	}
	teamID, err := mk.CreateCurationTeam(ctx, leader, slug, "Legacy", "Migrated")
	require.NoError(t, err)
	require.NoError(t, mk.SetCurationPreference(
		ctx,
		subscriber,
		slug,
		types.CurationPreferenceMode_CURATION_PREFERENCE_MODE_PINNED,
		teamID,
		true,
	))
	team, found, err := mk.GetCurationTeam(ctx, slug, teamID)
	require.NoError(t, err)
	require.True(t, found)
	team.SubscriberCount = 99
	require.NoError(t, mk.SetCurationTeam(ctx, team))

	legacy := &types.Community{Slug: slug, OriginalFounder: leader, CurrentFounder: leader}
	legacyBytes, err := mk.CDC().Marshal(legacy)
	require.NoError(t, err)
	require.NoError(t, mk.SetRawKVPair(ctx, types.KeyCommunity(slug), legacyBytes))

	require.NoError(t, mk.MigrateV139(ctx))
	team, found, err = mk.GetCurationTeam(ctx, slug, teamID)
	require.NoError(t, err)
	require.True(t, found)
	require.Equal(t, uint64(1), team.SubscriberCount)
	hasCommunity, err := mk.StoreService().OpenKVStore(ctx).Has(types.KeyCommunity(slug))
	require.NoError(t, err)
	require.False(t, hasCommunity)
	require.NoError(t, mk.MigrateV139(ctx))
}

func TestAdminCanCreateCurationTeamWithoutEffectivePaid(t *testing.T) {
	mk, ctx, _ := setupModule(t)
	admin := genAddr(42)
	slug := "admin-community"
	ensureUsername(t, mk, ctx, admin, "Anon-admin")
	bz, found, err := mk.GetProfileCore(ctx, admin)
	require.NoError(t, err)
	require.True(t, found)
	var core types.ProfileCore
	require.NoError(t, json.Unmarshal(bz, &core))
	core.Level = types.LevelAdminMin
	core.EffectivePaid = false
	out, err := json.Marshal(&core)
	require.NoError(t, err)
	require.NoError(t, mk.SetProfileCore(ctx, admin, out))

	adminTier := mk.GetParams(ctx).GetTierConfig(types.LevelAdminMin)
	require.NotNil(t, adminTier)
	require.Equal(t, uint64(1000), adminTier.MaxCurationMemberships)
	require.Equal(t, uint64(1000), adminTier.MaxDailyRelays)
	require.NoError(t, mk.JoinCommunity(ctx, admin, slug, uint32(adminTier.MaxJoinedCommunities)))

	teamID, err := mk.CreateCurationTeam(ctx, admin, slug, "AdminTeam", "admin without paid flag")
	require.NoError(t, err, "admin without EffectivePaid must be able to create a curator team")
	require.Equal(t, uint64(1), teamID)
	t.Logf("[debug] admin curated team_id=%d without effective_paid", teamID)
}

func TestCurationTeamDescriptionLimitAndNoPolicy(t *testing.T) {
	mk, ctx, _ := setupModule(t)
	leader := genAddr(41)
	slug := "desc-limit"
	setPaidProfile(t, mk, ctx, leader)
	joinOpenCommunity(t, mk, ctx, leader, slug)

	params := mk.GetParams(ctx)
	require.Equal(t, uint64(4000), params.MaxCurationTeamDescriptionLength)
	require.NotContains(t, params.String(), "max_curation_team_policy_length")

	over := strings.Repeat("x", int(params.MaxCurationTeamDescriptionLength)+1)
	_, err := mk.CreateCurationTeam(ctx, leader, slug, "Long", over)
	require.ErrorContains(t, err, "description exceeds")

	teamID, err := mk.CreateCurationTeam(ctx, leader, slug, "Ok", "guidance in description")
	require.NoError(t, err)
	team, found, err := mk.GetCurationTeam(ctx, slug, teamID)
	require.NoError(t, err)
	require.True(t, found)
	require.Equal(t, "guidance in description", team.Description)
	require.NoError(t, mk.UpdateCurationTeamProfile(ctx, leader, slug, teamID, "Ok", "updated guidance"))
	team, found, err = mk.GetCurationTeam(ctx, slug, teamID)
	require.NoError(t, err)
	require.True(t, found)
	require.Equal(t, "updated guidance", team.Description)
}

func TestRetiredCommunityOwnershipHandlersReject(t *testing.T) {
	_, ctx, am := setupModule(t)
	_, err := am.CreateCommunity(ctx, &types.MsgCreateCommunity{})
	require.ErrorContains(t, err, "retired message")
	_, err = am.SetCommunityMetadata(ctx, &types.MsgSetCommunityMetadata{})
	require.ErrorContains(t, err, "retired message")
	_, err = am.TransferCommunity(ctx, &types.MsgTransferCommunity{})
	require.ErrorContains(t, err, "retired message")
	_, err = am.GovCreateCommunity(ctx, &types.MsgGovCreateCommunity{})
	require.ErrorContains(t, err, "retired message")
	_, err = am.GovSetCommunityFounder(ctx, &types.MsgGovSetCommunityFounder{})
	require.ErrorContains(t, err, "retired message")
}
