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
	unjoinedTeam, found, err := mk.GetCurationTeam(ctx, lonelySlug, unjoinedTeamID)
	require.NoError(t, err)
	require.True(t, found)
	require.Equal(t, uint64(1), unjoinedTeam.SubscriberCount, "founder counts as the first subscriber")
	joined, _, _, _, _, err := mk.ResolveEffectivePreference(ctx, unjoined, lonelySlug)
	require.NoError(t, err)
	require.True(t, joined, "create auto-joins the founder")
	t.Logf("[debug] unjoined create community=%s team_id=%d subs=%d", lonelySlug, unjoinedTeamID, unjoinedTeam.SubscriberCount)

	teamID, err := mk.CreateCurationTeam(ctx, leader, slug, "Signal", "Team description")
	require.NoError(t, err)
	require.Equal(t, uint64(1), teamID)
	team, found, err := mk.GetCurationTeam(ctx, slug, teamID)
	require.NoError(t, err)
	require.True(t, found)
	require.Equal(t, uint64(1), team.SubscriberCount, "founder is subscriber 1")
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
	team, found, err = mk.GetCurationTeam(ctx, slug, teamID)
	require.NoError(t, err)
	require.True(t, found)
	require.Equal(t, "Team description", team.Description)
	require.Equal(t, uint64(2), team.SubscriberCount, "founder + curator")
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
	require.Equal(t, uint64(2), team.SubscriberCount)
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
	require.Equal(t, uint64(1), team.SubscriberCount, "founder remains after curator leaves pin")

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
	require.Equal(t, uint64(1), team.SubscriberCount, "unpaid pin does not increment")

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
	require.Equal(t, uint64(1), team.SubscriberCount, "founder remains after watcher leaves")
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
	// Founder auto-pin at create + explicit subscriber pin → 2 after recount.
	require.Equal(t, uint64(2), team.SubscriberCount)
	hasCommunity, err := mk.StoreService().OpenKVStore(ctx).Has(types.KeyCommunity(slug))
	require.NoError(t, err)
	require.False(t, hasCommunity)
	require.NoError(t, mk.MigrateV139(ctx))
}

func TestAcceptCuratorInviteAutoJoins(t *testing.T) {
	mk, ctx, _ := setupModule(t)
	leader := genAddr(81)
	invitee := genAddr(82)
	slug := "auto-join-on-accept"
	setPaidProfile(t, mk, ctx, leader)
	setPaidProfile(t, mk, ctx, invitee)
	joinOpenCommunity(t, mk, ctx, leader, slug)

	teamID, err := mk.CreateCurationTeam(ctx, leader, slug, "AutoJoin", "")
	require.NoError(t, err)
	_, joined, err := mk.GetPreference(ctx, invitee, slug)
	require.NoError(t, err)
	require.False(t, joined, "invitee starts unjoined")

	require.NoError(t, mk.InviteCurator(ctx, leader, slug, teamID, invitee))
	acceptCtx := ctx.WithEventManager(sdk.NewEventManager())
	require.NoError(t, mk.AcceptCuratorInvite(acceptCtx, invitee, slug, teamID))
	// The indexer projects membership from community_joined, so the auto-join is
	// only visible to the API if accept emits it.
	var joinEvent bool
	for _, ev := range acceptCtx.EventManager().Events() {
		if ev.Type != "community_joined" {
			continue
		}
		var addr, community string
		for _, attr := range ev.Attributes {
			switch attr.Key {
			case "address":
				addr = attr.Value
			case "community":
				community = attr.Value
			}
		}
		if addr == invitee && community == slug {
			joinEvent = true
		}
	}
	require.True(t, joinEvent, "accept must emit community_joined for the invitee")
	_, joined, err = mk.GetPreference(ctx, invitee, slug)
	require.NoError(t, err)
	require.True(t, joined, "accept auto-joins the invitee")
	members, _, err := mk.GetCurationTeamMembersPaginated(
		ctx,
		types.KeyCurationTeamMemberPrefix(slug, teamID),
		nil,
		10,
	)
	require.NoError(t, err)
	var foundInvitee bool
	for _, m := range members {
		if m.GetAddress() == invitee {
			foundInvitee = true
			break
		}
	}
	require.True(t, foundInvitee, "invitee must be a team member after accept")
	t.Logf("[debug] accept auto-join community=%s team_id=%d invitee=%s members=%d", slug, teamID, invitee[:12], len(members))
}

func TestSetCurationTeamTagStoresOnTeam(t *testing.T) {
	mk, ctx, _ := setupModule(t)
	leader := genAddr(83)
	slug := "community-tag"
	setPaidProfile(t, mk, ctx, leader)
	joinOpenCommunity(t, mk, ctx, leader, slug)
	teamID, err := mk.CreateCurationTeam(ctx, leader, slug, "Tagged", "")
	require.NoError(t, err)

	team, found, err := mk.GetCurationTeam(ctx, slug, teamID)
	require.NoError(t, err)
	require.True(t, found)
	require.Equal(t, "", team.GetTag(), "a new team carries no community tag")

	require.NoError(t, mk.SetCurationTeamTag(ctx, slug, teamID, "adult"))
	team, found, err = mk.GetCurationTeam(ctx, slug, teamID)
	require.NoError(t, err)
	require.True(t, found)
	require.Equal(t, "adult", team.GetTag())

	require.NoError(t, mk.SetCurationTeamTag(ctx, slug, teamID, ""))
	team, _, err = mk.GetCurationTeam(ctx, slug, teamID)
	require.NoError(t, err)
	require.Equal(t, "", team.GetTag(), "clearing the community tag is allowed")
	t.Logf("[debug] community tag round-trip community=%s team_id=%d", slug, teamID)
}

// The empty tag and the absent record are different states, and the whole
// precedence chain depends on telling them apart.
func TestSetCurationPostTagDistinguishesEmptyFromCleared(t *testing.T) {
	mk, ctx, _ := setupModule(t)
	leader := genAddr(84)
	slug := "post-tag"
	post := strings.Repeat("ab", 32)
	setPaidProfile(t, mk, ctx, leader)
	joinOpenCommunity(t, mk, ctx, leader, slug)
	teamID, err := mk.CreateCurationTeam(ctx, leader, slug, "Tagger", "")
	require.NoError(t, err)

	_, found, err := mk.GetCurationPostTag(ctx, slug, teamID, post)
	require.NoError(t, err)
	require.False(t, found, "no record means the team has no opinion")

	require.NoError(t, mk.SetCurationPostTag(ctx, slug, teamID, post, "gore", leader, false))
	record, found, err := mk.GetCurationPostTag(ctx, slug, teamID, post)
	require.NoError(t, err)
	require.True(t, found)
	require.Equal(t, "gore", record.GetTag())
	require.Equal(t, leader, record.GetActor())

	require.NoError(t, mk.SetCurationPostTag(ctx, slug, teamID, post, "", leader, false))
	record, found, err = mk.GetCurationPostTag(ctx, slug, teamID, post)
	require.NoError(t, err)
	require.True(t, found, "an empty tag is still a decision")
	require.Equal(t, "", record.GetTag())

	require.NoError(t, mk.SetCurationPostTag(ctx, slug, teamID, post, "", leader, true))
	_, found, err = mk.GetCurationPostTag(ctx, slug, teamID, post)
	require.NoError(t, err)
	require.False(t, found, "clear removes the team's opinion entirely")
	t.Logf("[debug] post tag states community=%s team_id=%d post=%s", slug, teamID, post[:12])
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
	require.Equal(t, uint64(10000), adminTier.MaxDailyRelays)
	require.NoError(t, mk.JoinCommunity(ctx, admin, slug, uint32(adminTier.MaxJoinedCommunities)))

	teamID, err := mk.CreateCurationTeam(ctx, admin, slug, "AdminTeam", "admin without paid flag")
	require.NoError(t, err, "admin without EffectivePaid must be able to create a curator team")
	require.Equal(t, uint64(1), teamID)
	team, found, err := mk.GetCurationTeam(ctx, slug, teamID)
	require.NoError(t, err)
	require.True(t, found)
	require.Equal(t, uint64(1), team.SubscriberCount, "admin founder counts as a subscriber")
	t.Logf("[debug] admin curated team_id=%d without effective_paid subs=%d", teamID, team.SubscriberCount)
}

func TestCurationTeamProfileValidationAndNoPolicy(t *testing.T) {
	mk, ctx, _ := setupModule(t)
	leader := genAddr(41)
	otherLeader := genAddr(43)
	slug := "desc-limit"
	setPaidProfile(t, mk, ctx, leader)
	setPaidProfile(t, mk, ctx, otherLeader)
	joinOpenCommunity(t, mk, ctx, leader, slug)

	params := mk.GetParams(ctx)
	require.Equal(t, uint64(30), params.MaxCurationTeamNameLength)
	require.Equal(t, uint64(800), params.MaxCurationTeamDescriptionLength)
	require.NotContains(t, params.String(), "max_curation_team_policy_length")

	invalidNames := []string{
		"",
		"   ",
		" leading",
		"trailing ",
		strings.Repeat("n", int(params.MaxCurationTeamNameLength)+1),
		"bad!",
		"tëam",
	}
	for _, name := range invalidNames {
		_, err := mk.CreateCurationTeam(ctx, leader, slug, name, "")
		require.Error(t, err, "name %q must be rejected", name)
	}

	over := strings.Repeat("🙂", int(params.MaxCurationTeamDescriptionLength)+1)
	_, err := mk.CreateCurationTeam(ctx, leader, slug, "Long", over)
	require.ErrorContains(t, err, "description exceeds")

	exactName := strings.Repeat("N", int(params.MaxCurationTeamNameLength))
	exactDescription := strings.Repeat("🙂", int(params.MaxCurationTeamDescriptionLength))
	// Padded going in: the chain trims, so a description already at the limit
	// still fits and comes back stored without the padding.
	teamID, err := mk.CreateCurationTeam(ctx, leader, slug, exactName, "  "+exactDescription+"\n")
	require.NoError(t, err)
	team, found, err := mk.GetCurationTeam(ctx, slug, teamID)
	require.NoError(t, err)
	require.True(t, found)
	require.Equal(t, exactName, team.Name)
	require.Equal(t, exactDescription, team.Description)

	_, err = mk.CreateCurationTeam(ctx, otherLeader, slug, strings.ToLower(exactName), "")
	require.ErrorContains(t, err, "team name already used")
	otherTeamID, err := mk.CreateCurationTeam(ctx, otherLeader, slug, "Other", "")
	require.NoError(t, err)
	require.ErrorContains(
		t,
		mk.UpdateCurationTeamProfile(ctx, otherLeader, slug, otherTeamID, strings.ToLower(exactName), ""),
		"team name already used",
	)

	require.Error(t, mk.UpdateCurationTeamProfile(ctx, leader, slug, teamID, "bad!", "updated guidance"))
	require.ErrorContains(
		t,
		mk.UpdateCurationTeamProfile(ctx, leader, slug, teamID, exactName, strings.Repeat("x", 801)),
		"description exceeds",
	)
	team, found, err = mk.GetCurationTeam(ctx, slug, teamID)
	require.NoError(t, err)
	require.True(t, found)
	require.Equal(t, exactDescription, team.Description, "rejected updates must not mutate the profile")

	// Trimmed on update as well, and the trimmed text is what is stored.
	require.NoError(t, mk.UpdateCurationTeamProfile(ctx, leader, slug, teamID, exactName, "  updated guidance\n"))
	team, found, err = mk.GetCurationTeam(ctx, slug, teamID)
	require.NoError(t, err)
	require.True(t, found)
	require.Equal(t, "updated guidance", team.Description)

	require.NoError(t, mk.UpdateCurationTeamProfile(ctx, leader, slug, teamID, exactName, ""))
	team, found, err = mk.GetCurationTeam(ctx, slug, teamID)
	require.NoError(t, err)
	require.True(t, found)
	require.Empty(t, team.Description, "description remains optional")
}

// joinWithLens is the user-facing join path: whatever lens the joiner was
// shown is what gets stored.
func joinWithLens(t *testing.T, mk *mockKeeper, ctx sdk.Context, owner, slug string, mode types.CurationPreferenceMode, teamID uint64, paid bool) error {
	t.Helper()
	tier := mk.GetParams(ctx).GetTierConfig(types.LevelSubscriber)
	require.NotNil(t, tier)
	return mk.JoinCommunityWithLens(ctx, owner, slug, uint32(tier.MaxJoinedCommunities), mode, teamID, paid)
}

func requireStoredPreference(t *testing.T, mk *mockKeeper, ctx sdk.Context, owner, slug string, mode types.CurationPreferenceMode, teamID uint64) {
	t.Helper()
	pref, found, err := mk.GetPreference(ctx, owner, slug)
	require.NoError(t, err)
	require.True(t, found, "%s must be joined to %s", owner, slug)
	require.Equal(t, mode, pref.Mode)
	require.Equal(t, teamID, pref.PinnedTeamId)
}

func TestJoinLocksInSelectedTeamLens(t *testing.T) {
	mk, ctx, _ := setupModule(t)
	leader := genAddr(60)
	joiner := genAddr(61)
	slug := "lens-lock"
	setPaidProfile(t, mk, ctx, leader)
	setPaidProfile(t, mk, ctx, joiner)

	teamID, err := mk.CreateCurationTeam(ctx, leader, slug, "Signal", "")
	require.NoError(t, err)

	require.NoError(t, joinWithLens(t, mk, ctx, joiner, slug,
		types.CurationPreferenceMode_CURATION_PREFERENCE_MODE_PINNED, teamID, true))
	requireStoredPreference(t, mk, ctx, joiner, slug,
		types.CurationPreferenceMode_CURATION_PREFERENCE_MODE_PINNED, teamID)

	team, found, err := mk.GetCurationTeam(ctx, slug, teamID)
	require.NoError(t, err)
	require.True(t, found)
	require.Equal(t, uint64(2), team.SubscriberCount, "founder + the joiner who picked this team")
}

func TestJoinLocksInRawLens(t *testing.T) {
	mk, ctx, _ := setupModule(t)
	leader := genAddr(62)
	joiner := genAddr(63)
	slug := "lens-raw"
	setPaidProfile(t, mk, ctx, leader)
	setPaidProfile(t, mk, ctx, joiner)
	teamID, err := mk.CreateCurationTeam(ctx, leader, slug, "Signal", "")
	require.NoError(t, err)

	require.NoError(t, joinWithLens(t, mk, ctx, joiner, slug,
		types.CurationPreferenceMode_CURATION_PREFERENCE_MODE_RAW, 0, true))
	requireStoredPreference(t, mk, ctx, joiner, slug,
		types.CurationPreferenceMode_CURATION_PREFERENCE_MODE_RAW, 0)

	team, _, err := mk.GetCurationTeam(ctx, slug, teamID)
	require.NoError(t, err)
	require.Equal(t, uint64(1), team.SubscriberCount, "an uncensored joiner backs no team")
}

// The whole point of the lock-in: a member recorded against the team they saw
// does not migrate when a rival team later buys the top of the subscriber
// ranking, so the default audience cannot be captured wholesale.
func TestJoinSnapshotsDefaultTeamAndSurvivesRankingFlip(t *testing.T) {
	mk, ctx, _ := setupModule(t)
	incumbentOwner := genAddr(64)
	rivalOwner := genAddr(65)
	joiner := genAddr(66)
	backer := genAddr(67)
	secondBacker := genAddr(79)
	slug := "lens-snapshot"
	for _, addr := range []string{incumbentOwner, rivalOwner, joiner, backer, secondBacker} {
		setPaidProfile(t, mk, ctx, addr)
	}

	incumbent, err := mk.CreateCurationTeam(ctx, incumbentOwner, slug, "Incumbent", "")
	require.NoError(t, err)
	rival, err := mk.CreateCurationTeam(ctx, rivalOwner, slug, "Rival", "")
	require.NoError(t, err)

	// Tie on subscriber_count (one founder each) breaks to the older team.
	require.NoError(t, joinWithLens(t, mk, ctx, joiner, slug,
		types.CurationPreferenceMode_CURATION_PREFERENCE_MODE_LIVE_DEFAULT, 0, true))
	requireStoredPreference(t, mk, ctx, joiner, slug,
		types.CurationPreferenceMode_CURATION_PREFERENCE_MODE_PINNED, incumbent)
	t.Logf("[debug] default lens snapshot pinned team_id=%d", incumbent)

	// Rival overtakes the incumbent on subscriber_count.
	require.NoError(t, joinWithLens(t, mk, ctx, backer, slug,
		types.CurationPreferenceMode_CURATION_PREFERENCE_MODE_PINNED, rival, true))
	require.NoError(t, joinWithLens(t, mk, ctx, secondBacker, slug,
		types.CurationPreferenceMode_CURATION_PREFERENCE_MODE_PINNED, rival, true))
	rivalTeam, _, err := mk.GetCurationTeam(ctx, slug, rival)
	require.NoError(t, err)
	incumbentTeam, _, err := mk.GetCurationTeam(ctx, slug, incumbent)
	require.NoError(t, err)
	require.Greater(t, rivalTeam.SubscriberCount, incumbentTeam.SubscriberCount, "rival now leads the ranking")

	// The earlier joiner is unmoved — no floating audience to capture.
	requireStoredPreference(t, mk, ctx, joiner, slug,
		types.CurationPreferenceMode_CURATION_PREFERENCE_MODE_PINNED, incumbent)
	_, _, effective, _, effectiveTeam, err := mk.ResolveEffectivePreference(ctx, joiner, slug)
	require.NoError(t, err)
	require.Equal(t, types.CurationPreferenceMode_CURATION_PREFERENCE_MODE_PINNED, effective)
	require.Equal(t, incumbent, effectiveTeam)
}

// Nothing to pin in an uncurated community, and RAW is what the picker shows
// there, so that is what gets locked in.
func TestJoinWithoutLiveTeamLocksRaw(t *testing.T) {
	mk, ctx, _ := setupModule(t)
	joiner := genAddr(68)
	slug := "lens-uncurated"
	setPaidProfile(t, mk, ctx, joiner)

	require.NoError(t, joinWithLens(t, mk, ctx, joiner, slug,
		types.CurationPreferenceMode_CURATION_PREFERENCE_MODE_LIVE_DEFAULT, 0, true))
	requireStoredPreference(t, mk, ctx, joiner, slug,
		types.CurationPreferenceMode_CURATION_PREFERENCE_MODE_RAW, 0)
}

func TestJoinDefaultLensSkipsTeamThatBannedTheJoiner(t *testing.T) {
	mk, ctx, _ := setupModule(t)
	leadOwner := genAddr(69)
	secondOwner := genAddr(70)
	joiner := genAddr(71)
	backer := genAddr(72)
	slug := "lens-banned"
	for _, addr := range []string{leadOwner, secondOwner, joiner, backer} {
		setPaidProfile(t, mk, ctx, addr)
	}
	lead, err := mk.CreateCurationTeam(ctx, leadOwner, slug, "Lead", "")
	require.NoError(t, err)
	second, err := mk.CreateCurationTeam(ctx, secondOwner, slug, "Second", "")
	require.NoError(t, err)
	require.NoError(t, joinWithLens(t, mk, ctx, backer, slug,
		types.CurationPreferenceMode_CURATION_PREFERENCE_MODE_PINNED, lead, true))

	require.NoError(t, mk.SetCurationActionHiddenUser(ctx, slug, lead, joiner, leadOwner, true))
	require.NoError(t, joinWithLens(t, mk, ctx, joiner, slug,
		types.CurationPreferenceMode_CURATION_PREFERENCE_MODE_LIVE_DEFAULT, 0, true))
	requireStoredPreference(t, mk, ctx, joiner, slug,
		types.CurationPreferenceMode_CURATION_PREFERENCE_MODE_PINNED, second)
}

func TestJoinLensValidationRejectsInconsistentRequests(t *testing.T) {
	mk, ctx, _ := setupModule(t)
	leader := genAddr(73)
	slug := "lens-validation"
	setPaidProfile(t, mk, ctx, leader)
	teamID, err := mk.CreateCurationTeam(ctx, leader, slug, "Signal", "")
	require.NoError(t, err)

	cases := []struct {
		name    string
		addr    string
		mode    types.CurationPreferenceMode
		teamID  uint64
		wantErr string
	}{
		{"pinned without team", genAddr(74), types.CurationPreferenceMode_CURATION_PREFERENCE_MODE_PINNED, 0, "requires a team_id"},
		{"raw with team", genAddr(75), types.CurationPreferenceMode_CURATION_PREFERENCE_MODE_RAW, teamID, "requires team_id 0"},
		{"default with team", genAddr(76), types.CurationPreferenceMode_CURATION_PREFERENCE_MODE_LIVE_DEFAULT, teamID, "requires team_id 0"},
		{"unknown mode", genAddr(77), types.CurationPreferenceMode(9), 0, "invalid join lens mode"},
		{"unknown team", genAddr(78), types.CurationPreferenceMode_CURATION_PREFERENCE_MODE_PINNED, 999, "deleted or unknown team"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			setPaidProfile(t, mk, ctx, tc.addr)
			err := joinWithLens(t, mk, ctx, tc.addr, slug, tc.mode, tc.teamID, true)
			require.ErrorContains(t, err, tc.wantErr)
			_, found, err := mk.GetPreference(ctx, tc.addr, slug)
			require.NoError(t, err)
			require.False(t, found, "a rejected join must not leave a membership behind")
		})
	}
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
