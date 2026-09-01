package core

import (
	"bytes"
	"encoding/json"
	"fmt"
	"testing"

	"github.com/cosmos/cosmos-sdk/crypto/keys/secp256k1"
	sdk "github.com/cosmos/cosmos-sdk/types"
	"github.com/stretchr/testify/require"

	"mirage/x/core/types"
)

// The curation handlers derive the actor from envelope_pubkey, so authorization
// can only be exercised with real keypairs — a genAddr string cannot sign.
func curationSigner(seed byte) ([]byte, string) {
	priv := secp256k1.PrivKey{Key: bytes.Repeat([]byte{seed}, 32)}
	return priv.PubKey().Bytes(), sdk.AccAddress(priv.PubKey().Address()).String()
}

func setUnpaidProfile(t *testing.T, mk *mockKeeper, ctx sdk.Context, owner string) {
	t.Helper()
	bz, found, err := mk.GetProfileCore(ctx, owner)
	require.NoError(t, err)
	require.True(t, found)
	var core types.ProfileCore
	require.NoError(t, json.Unmarshal(bz, &core))
	core.EffectivePaid = false
	core.SubscriptionExpiry = 0
	out, err := json.Marshal(&core)
	require.NoError(t, err)
	require.NoError(t, mk.SetProfileCore(ctx, owner, out))
}

// curationTeam builds a live team in slug owned by ownerSeed's key with
// curatorSeed's key accepted onto the roster.
type curationFixture struct {
	ownerPub   []byte
	owner      string
	curatorPub []byte
	curator    string
	teamID     uint64
	slug       string
}

func newCurationFixture(t *testing.T, mk *mockKeeper, ctx sdk.Context, slug string, ownerSeed, curatorSeed byte) curationFixture {
	t.Helper()
	ownerPub, owner := curationSigner(ownerSeed)
	curatorPub, curator := curationSigner(curatorSeed)
	setPaidProfile(t, mk, ctx, owner)
	setPaidProfile(t, mk, ctx, curator)
	teamID, err := mk.CreateCurationTeam(ctx, owner, slug, "Team-"+slug, "")
	require.NoError(t, err)
	require.NoError(t, mk.InviteCurator(ctx, owner, slug, teamID, curator))
	require.NoError(t, mk.AcceptCuratorInvite(ctx, curator, slug, teamID))
	return curationFixture{
		ownerPub:   ownerPub,
		owner:      owner,
		curatorPub: curatorPub,
		curator:    curator,
		teamID:     teamID,
		slug:       slug,
	}
}

func teamMemberAddrs(t *testing.T, mk *mockKeeper, ctx sdk.Context, slug string, teamID uint64) []string {
	t.Helper()
	members, _, err := mk.GetCurationTeamMembersPaginated(
		ctx,
		types.KeyCurationTeamMemberPrefix(slug, teamID),
		nil,
		100,
	)
	require.NoError(t, err)
	addrs := make([]string, 0, len(members))
	for _, m := range members {
		addrs = append(addrs, m.GetAddress())
	}
	return addrs
}

func eventAttr(t *testing.T, ctx sdk.Context, evType, key string) (string, bool) {
	t.Helper()
	for _, ev := range ctx.EventManager().Events() {
		if ev.Type != evType {
			continue
		}
		for _, attr := range ev.Attributes {
			if attr.Key == key {
				return attr.Value, true
			}
		}
	}
	return "", false
}

// =========================================================================
// Roster changes: remove, leave, transfer
// =========================================================================

func TestRemoveCuratorIsOwnerOnly(t *testing.T) {
	mk, ctx, am := setupModule(t)
	f := newCurationFixture(t, mk, ctx, "remove-curator", 0x11, 0x12)
	outsiderPub, outsider := curationSigner(0x13)
	setPaidProfile(t, mk, ctx, outsider)

	_, err := am.RemoveCurator(ctx, &types.MsgRemoveCurator{
		EnvelopePubkey: f.curatorPub, Community: f.slug, TeamId: f.teamID, Target: f.owner,
	})
	require.ErrorContains(t, err, "only the team owner", "a curator must not be able to remove the owner")

	_, err = am.RemoveCurator(ctx, &types.MsgRemoveCurator{
		EnvelopePubkey: outsiderPub, Community: f.slug, TeamId: f.teamID, Target: f.curator,
	})
	require.ErrorContains(t, err, "only the team owner")

	_, err = am.RemoveCurator(ctx, &types.MsgRemoveCurator{
		EnvelopePubkey: f.ownerPub, Community: f.slug, TeamId: f.teamID, Target: f.owner,
	})
	require.ErrorContains(t, err, "owner cannot remove self")

	_, err = am.RemoveCurator(ctx, &types.MsgRemoveCurator{
		EnvelopePubkey: f.ownerPub, Community: f.slug, TeamId: f.teamID, Target: outsider,
	})
	require.ErrorContains(t, err, "not a member of this team")

	require.ElementsMatch(t, []string{f.owner, f.curator}, teamMemberAddrs(t, mk, ctx, f.slug, f.teamID))
	_, err = am.RemoveCurator(ctx, &types.MsgRemoveCurator{
		EnvelopePubkey: f.ownerPub, Community: f.slug, TeamId: f.teamID, Target: f.curator,
	})
	require.NoError(t, err)
	require.ElementsMatch(t, []string{f.owner}, teamMemberAddrs(t, mk, ctx, f.slug, f.teamID))

	// Removal must free the one-team-per-community slot, or the curator is
	// permanently locked out of every other team in the community.
	require.NoError(t, mk.InviteCurator(ctx, f.owner, f.slug, f.teamID, f.curator))
	t.Logf("[debug] remove curator community=%s team_id=%d members=%d", f.slug, f.teamID, len(teamMemberAddrs(t, mk, ctx, f.slug, f.teamID)))
}

func TestLeaveCurationTeamOwnerMustTransferOrDelete(t *testing.T) {
	mk, ctx, am := setupModule(t)
	f := newCurationFixture(t, mk, ctx, "leave-team", 0x14, 0x15)

	_, err := am.LeaveCurationTeam(ctx, &types.MsgLeaveCurationTeam{
		EnvelopePubkey: f.ownerPub, Community: f.slug, TeamId: f.teamID,
	})
	require.ErrorContains(t, err, "owner cannot leave", "an ownerless live team would be unmanageable")

	_, err = am.LeaveCurationTeam(ctx, &types.MsgLeaveCurationTeam{
		EnvelopePubkey: f.curatorPub, Community: f.slug, TeamId: f.teamID,
	})
	require.NoError(t, err)
	require.ElementsMatch(t, []string{f.owner}, teamMemberAddrs(t, mk, ctx, f.slug, f.teamID))

	_, err = am.LeaveCurationTeam(ctx, &types.MsgLeaveCurationTeam{
		EnvelopePubkey: f.curatorPub, Community: f.slug, TeamId: f.teamID,
	})
	require.ErrorContains(t, err, "not a member of this team", "leaving twice must not silently succeed")

	_, err = am.LeaveCurationTeam(ctx, &types.MsgLeaveCurationTeam{
		EnvelopePubkey: f.curatorPub, Community: f.slug, TeamId: f.teamID + 1,
	})
	require.ErrorContains(t, err, "team not found")
}

func TestLeaveCommunityAlsoLeavesOrDeletesCurationTeam(t *testing.T) {
	t.Run("non-owner curator leaves team", func(t *testing.T) {
		mk, ctx, am := setupModule(t)
		f := newCurationFixture(t, mk, ctx, "leave-community-member", 0x40, 0x41)

		_, err := am.LeaveCommunity(ctx, &types.MsgLeaveCommunity{
			EnvelopePubkey: f.curatorPub,
			Community:      f.slug,
		})
		require.NoError(t, err)
		require.ElementsMatch(t, []string{f.owner}, teamMemberAddrs(t, mk, ctx, f.slug, f.teamID))
		_, joined, err := mk.GetPreference(ctx, f.curator, f.slug)
		require.NoError(t, err)
		require.False(t, joined)
		team, found, err := mk.GetCurationTeam(ctx, f.slug, f.teamID)
		require.NoError(t, err)
		require.True(t, found)
		require.Zero(t, team.DeletedHeight)
		require.Equal(t, f.owner, team.Owner)
	})

	t.Run("owner promotes successor then last curator deletes team", func(t *testing.T) {
		mk, ctx, am := setupModule(t)
		f := newCurationFixture(t, mk, ctx, "leave-community-owner", 0x42, 0x43)

		_, err := am.LeaveCommunity(ctx, &types.MsgLeaveCommunity{
			EnvelopePubkey: f.ownerPub,
			Community:      f.slug,
		})
		require.NoError(t, err)
		team, found, err := mk.GetCurationTeam(ctx, f.slug, f.teamID)
		require.NoError(t, err)
		require.True(t, found)
		require.Zero(t, team.DeletedHeight)
		require.Equal(t, f.curator, team.Owner)
		require.ElementsMatch(t, []string{f.curator}, teamMemberAddrs(t, mk, ctx, f.slug, f.teamID))
		_, joined, err := mk.GetPreference(ctx, f.owner, f.slug)
		require.NoError(t, err)
		require.False(t, joined)

		_, err = am.LeaveCommunity(ctx, &types.MsgLeaveCommunity{
			EnvelopePubkey: f.curatorPub,
			Community:      f.slug,
		})
		require.NoError(t, err)
		team, found, err = mk.GetCurationTeam(ctx, f.slug, f.teamID)
		require.NoError(t, err)
		require.True(t, found)
		require.NotZero(t, team.DeletedHeight)
		require.Empty(t, teamMemberAddrs(t, mk, ctx, f.slug, f.teamID))
		_, joined, err = mk.GetPreference(ctx, f.curator, f.slug)
		require.NoError(t, err)
		require.False(t, joined)
	})
}

func TestTransferCurationTeamRequiresAcceptedCurator(t *testing.T) {
	mk, ctx, am := setupModule(t)
	f := newCurationFixture(t, mk, ctx, "transfer-team", 0x16, 0x17)
	outsiderPub, outsider := curationSigner(0x18)
	setPaidProfile(t, mk, ctx, outsider)

	_, err := am.TransferCurationTeam(ctx, &types.MsgTransferCurationTeam{
		EnvelopePubkey: f.curatorPub, Community: f.slug, TeamId: f.teamID, NewOwner: f.curator,
	})
	require.ErrorContains(t, err, "only the team owner")

	_, err = am.TransferCurationTeam(ctx, &types.MsgTransferCurationTeam{
		EnvelopePubkey: f.ownerPub, Community: f.slug, TeamId: f.teamID, NewOwner: outsider,
	})
	require.ErrorContains(t, err, "must be an accepted curator")

	_, err = am.TransferCurationTeam(ctx, &types.MsgTransferCurationTeam{
		EnvelopePubkey: f.ownerPub, Community: f.slug, TeamId: f.teamID, NewOwner: f.owner,
	})
	require.ErrorContains(t, err, "already the team owner")

	_, err = am.TransferCurationTeam(ctx, &types.MsgTransferCurationTeam{
		EnvelopePubkey: f.ownerPub, Community: f.slug, TeamId: f.teamID, NewOwner: f.curator,
	})
	require.NoError(t, err)
	team, found, err := mk.GetCurationTeam(ctx, f.slug, f.teamID)
	require.NoError(t, err)
	require.True(t, found)
	require.Equal(t, f.curator, team.Owner)

	// The old owner stays on the roster but loses owner-only powers.
	require.ElementsMatch(t, []string{f.owner, f.curator}, teamMemberAddrs(t, mk, ctx, f.slug, f.teamID))
	_, err = am.SetCurationSubscriberOnly(ctx, &types.MsgSetCurationSubscriberOnly{
		EnvelopePubkey: f.ownerPub, Community: f.slug, TeamId: f.teamID, Enabled: true,
	})
	require.ErrorContains(t, err, "only the team owner", "transfer must actually move the owner-only powers")

	outsiderTeam, err := mk.CreateCurationTeam(ctx, outsider, "transfer-other", "Other", "")
	require.NoError(t, err)
	_, err = am.TransferCurationTeam(ctx, &types.MsgTransferCurationTeam{
		EnvelopePubkey: outsiderPub, Community: "transfer-other", TeamId: outsiderTeam, NewOwner: f.owner,
	})
	require.ErrorContains(t, err, "must be an accepted curator")
}

// =========================================================================
// Invitations: revoke and decline
// =========================================================================

func TestRevokeCuratorInviteIsOwnerOnly(t *testing.T) {
	mk, ctx, am := setupModule(t)
	f := newCurationFixture(t, mk, ctx, "revoke-invite", 0x19, 0x1a)
	inviteePub, invitee := curationSigner(0x1b)
	setPaidProfile(t, mk, ctx, invitee)
	require.NoError(t, mk.InviteCurator(ctx, f.owner, f.slug, f.teamID, invitee))

	_, err := am.RevokeCuratorInvite(ctx, &types.MsgRevokeCuratorInvite{
		EnvelopePubkey: f.curatorPub, Community: f.slug, TeamId: f.teamID, Target: invitee,
	})
	require.ErrorContains(t, err, "only the team owner")

	revokeCtx := ctx.WithEventManager(sdk.NewEventManager())
	_, err = am.RevokeCuratorInvite(revokeCtx, &types.MsgRevokeCuratorInvite{
		EnvelopePubkey: f.ownerPub, Community: f.slug, TeamId: f.teamID, Target: invitee,
	})
	require.NoError(t, err)
	target, ok := eventAttr(t, revokeCtx, "curator_invitation_revoked", "target")
	require.True(t, ok, "the indexer projects invitation state from events")
	require.Equal(t, invitee, target)

	// The invitation is gone, so accepting it must fail and revoking again must
	// not report success.
	_, err = am.AcceptCuratorInvite(ctx, &types.MsgAcceptCuratorInvite{
		EnvelopePubkey: inviteePub, Community: f.slug, TeamId: f.teamID,
	})
	require.ErrorContains(t, err, "no pending invitation")
	_, err = am.RevokeCuratorInvite(ctx, &types.MsgRevokeCuratorInvite{
		EnvelopePubkey: f.ownerPub, Community: f.slug, TeamId: f.teamID, Target: invitee,
	})
	require.ErrorContains(t, err, "no pending invitation")

	// Revoking must release the pending-invite slot so the owner can re-invite.
	require.NoError(t, mk.InviteCurator(ctx, f.owner, f.slug, f.teamID, invitee))
}

func TestDeclineCuratorInviteClearsOwnInvitation(t *testing.T) {
	mk, ctx, am := setupModule(t)
	f := newCurationFixture(t, mk, ctx, "decline-invite", 0x1c, 0x1d)
	inviteePub, invitee := curationSigner(0x1e)
	setPaidProfile(t, mk, ctx, invitee)

	_, err := am.DeclineCuratorInvite(ctx, &types.MsgDeclineCuratorInvite{
		EnvelopePubkey: inviteePub, Community: f.slug, TeamId: f.teamID,
	})
	require.ErrorContains(t, err, "no pending invitation")

	require.NoError(t, mk.InviteCurator(ctx, f.owner, f.slug, f.teamID, invitee))
	declineCtx := ctx.WithEventManager(sdk.NewEventManager())
	_, err = am.DeclineCuratorInvite(declineCtx, &types.MsgDeclineCuratorInvite{
		EnvelopePubkey: inviteePub, Community: f.slug, TeamId: f.teamID,
	})
	require.NoError(t, err)
	inviter, ok := eventAttr(t, declineCtx, "curator_invitation_declined", "inviter")
	require.True(t, ok)
	require.Equal(t, f.owner, inviter, "declining must report who invited, not who declined")

	_, err = am.AcceptCuratorInvite(ctx, &types.MsgAcceptCuratorInvite{
		EnvelopePubkey: inviteePub, Community: f.slug, TeamId: f.teamID,
	})
	require.ErrorContains(t, err, "no pending invitation")
	require.ElementsMatch(t, []string{f.owner, f.curator}, teamMemberAddrs(t, mk, ctx, f.slug, f.teamID))
}

// =========================================================================
// Owner-only community controls: subscriber-only and community tag
// =========================================================================

func TestSetCurationSubscriberOnlyIsOwnerOnly(t *testing.T) {
	mk, ctx, am := setupModule(t)
	f := newCurationFixture(t, mk, ctx, "subs-only", 0x21, 0x22)

	_, err := am.SetCurationSubscriberOnly(ctx, &types.MsgSetCurationSubscriberOnly{
		EnvelopePubkey: f.curatorPub, Community: f.slug, TeamId: f.teamID, Enabled: true,
	})
	require.ErrorContains(t, err, "only the team owner")

	enableCtx := ctx.WithEventManager(sdk.NewEventManager())
	_, err = am.SetCurationSubscriberOnly(enableCtx, &types.MsgSetCurationSubscriberOnly{
		EnvelopePubkey: f.ownerPub, Community: f.slug, TeamId: f.teamID, Enabled: true,
	})
	require.NoError(t, err)
	team, found, err := mk.GetCurationTeam(ctx, f.slug, f.teamID)
	require.NoError(t, err)
	require.True(t, found)
	require.True(t, team.SubscriberOnly)
	enabled, ok := eventAttr(t, enableCtx, "curation_subscriber_only_changed", "enabled")
	require.True(t, ok)
	require.Equal(t, "true", enabled)

	_, err = am.SetCurationSubscriberOnly(ctx, &types.MsgSetCurationSubscriberOnly{
		EnvelopePubkey: f.ownerPub, Community: f.slug, TeamId: f.teamID, Enabled: false,
	})
	require.NoError(t, err)
	team, _, err = mk.GetCurationTeam(ctx, f.slug, f.teamID)
	require.NoError(t, err)
	require.False(t, team.SubscriberOnly, "subscriber-only must be reversible")
}

func TestSetCurationTagIsOwnerOnlyAndWhitelisted(t *testing.T) {
	mk, ctx, am := setupModule(t)
	f := newCurationFixture(t, mk, ctx, "community-tags", 0x23, 0x24)

	_, err := am.SetCurationTag(ctx, &types.MsgSetCurationTag{
		EnvelopePubkey: f.curatorPub, Community: f.slug, TeamId: f.teamID, Tag: "adult",
	})
	require.ErrorContains(t, err, "only the team owner")

	_, err = am.SetCurationTag(ctx, &types.MsgSetCurationTag{
		EnvelopePubkey: f.ownerPub, Community: f.slug, TeamId: f.teamID, Tag: "not-a-real-tag",
	})
	require.ErrorContains(t, err, "invalid tag")

	_, err = am.SetCurationTag(ctx, &types.MsgSetCurationTag{
		EnvelopePubkey: f.ownerPub, Community: f.slug, TeamId: f.teamID, Tag: "porn",
	})
	require.NoError(t, err)
	team, found, err := mk.GetCurationTeam(ctx, f.slug, f.teamID)
	require.NoError(t, err)
	require.True(t, found)
	require.Equal(t, "adult", team.GetTag(), "the deprecated alias must be stored in canonical form")
}

// =========================================================================
// Any-curator moderation actions
// =========================================================================

func TestCurationModerationActionsRequireTeamMembership(t *testing.T) {
	mk, ctx, am := setupModule(t)
	f := newCurationFixture(t, mk, ctx, "mod-actions", 0x25, 0x26)
	outsiderPub, outsider := curationSigner(0x27)
	setPaidProfile(t, mk, ctx, outsider)
	post := genTxHash(7)
	_, target := curationSigner(0x28)
	setPaidProfile(t, mk, ctx, target)
	require.NoError(t, mk.SetPostMetadata(ctx, post, &types.PostMetadata{
		Author:    target,
		Community: f.slug,
	}))

	// Every action rejects a paid non-member, so the failure is membership and
	// not eligibility.
	_, err := am.SetCurationPostHidden(ctx, &types.MsgSetCurationPostHidden{
		EnvelopePubkey: outsiderPub, Community: f.slug, TeamId: f.teamID, Target: post, Hidden: true,
	})
	require.ErrorContains(t, err, "not a curator on this team")
	_, err = am.SetCurationUserHidden(ctx, &types.MsgSetCurationUserHidden{
		EnvelopePubkey: outsiderPub, Community: f.slug, TeamId: f.teamID, Target: target, Hidden: true,
	})
	require.ErrorContains(t, err, "not a curator on this team")
	_, err = am.SetCurationThreadLocked(ctx, &types.MsgSetCurationThreadLocked{
		EnvelopePubkey: outsiderPub, Community: f.slug, TeamId: f.teamID, RootHash: post, Locked: true,
	})
	require.ErrorContains(t, err, "not a curator on this team")
	_, err = am.SetCurationPostTag(ctx, &types.MsgSetCurationPostTag{
		EnvelopePubkey: outsiderPub, Community: f.slug, TeamId: f.teamID, Target: post, Tag: "gore",
	})
	require.ErrorContains(t, err, "not a curator on this team")

	// A non-owner curator may perform all of them.
	_, err = am.SetCurationPostHidden(ctx, &types.MsgSetCurationPostHidden{
		EnvelopePubkey: f.curatorPub, Community: f.slug, TeamId: f.teamID, Target: post, Hidden: true,
	})
	require.NoError(t, err)
	_, err = am.SetCurationUserHidden(ctx, &types.MsgSetCurationUserHidden{
		EnvelopePubkey: f.curatorPub, Community: f.slug, TeamId: f.teamID, Target: target, Hidden: true,
	})
	require.NoError(t, err)
	_, err = am.SetCurationPostTag(ctx, &types.MsgSetCurationPostTag{
		EnvelopePubkey: f.curatorPub, Community: f.slug, TeamId: f.teamID, Target: post, Tag: "gore",
	})
	require.NoError(t, err)
	record, found, err := mk.GetCurationPostTag(ctx, f.slug, f.teamID, post)
	require.NoError(t, err)
	require.True(t, found)
	require.Equal(t, "gore", record.GetTag())
	require.Equal(t, f.curator, record.GetActor())

	// Losing paid status revokes the moderation powers even while the roster
	// row survives.
	setUnpaidProfile(t, mk, ctx, f.curator)
	_, err = am.SetCurationPostHidden(ctx, &types.MsgSetCurationPostHidden{
		EnvelopePubkey: f.curatorPub, Community: f.slug, TeamId: f.teamID, Target: post, Hidden: false,
	})
	require.ErrorContains(t, err, "must be an active subscriber or admin")
}

func TestCurationCannotBanCommunityCuratorsOrTheirPosts(t *testing.T) {
	mk, ctx, am := setupModule(t)
	f := newCurationFixture(t, mk, ctx, "protected-curators", 0x36, 0x37)
	_, otherCurator := curationSigner(0x38)
	setPaidProfile(t, mk, ctx, otherCurator)
	_, err := mk.CreateCurationTeam(ctx, otherCurator, f.slug, "OtherTeam", "")
	require.NoError(t, err)

	protected := []string{f.curator, f.owner, otherCurator}
	for i, target := range protected {
		_, err = am.SetCurationUserHidden(ctx, &types.MsgSetCurationUserHidden{
			EnvelopePubkey: f.curatorPub,
			Community:      f.slug,
			TeamId:         f.teamID,
			Target:         target,
			Hidden:         true,
		})
		require.ErrorContains(t, err, "cannot ban a curator in this community")

		post := genTxHash(20 + i)
		require.NoError(t, mk.SetPostMetadata(ctx, post, &types.PostMetadata{
			Author:    target,
			Community: f.slug,
		}))
		_, err = am.SetCurationPostHidden(ctx, &types.MsgSetCurationPostHidden{
			EnvelopePubkey: f.curatorPub,
			Community:      f.slug,
			TeamId:         f.teamID,
			Target:         post,
			Hidden:         true,
		})
		require.ErrorContains(t, err, "cannot ban a curator's post in this community")
	}

	_, ordinary := curationSigner(0x39)
	ordinaryPost := genTxHash(30)
	require.NoError(t, mk.SetPostMetadata(ctx, ordinaryPost, &types.PostMetadata{
		Author:    ordinary,
		Community: f.slug,
	}))
	_, err = am.SetCurationUserHidden(ctx, &types.MsgSetCurationUserHidden{
		EnvelopePubkey: f.curatorPub, Community: f.slug, TeamId: f.teamID, Target: ordinary, Hidden: true,
	})
	require.NoError(t, err)
	_, err = am.SetCurationPostHidden(ctx, &types.MsgSetCurationPostHidden{
		EnvelopePubkey: f.curatorPub, Community: f.slug, TeamId: f.teamID, Target: ordinaryPost, Hidden: true,
	})
	require.NoError(t, err)

	// A legacy post has no metadata to read, and nearly the whole history is
	// legacy. The curator has to be able to ban it rather than be told the
	// metadata is missing, which is a fact about the chain and not an answer.
	legacyPost := genTxHash(32)
	_, found, err := mk.GetPostMetadata(ctx, legacyPost)
	require.NoError(t, err)
	require.False(t, found, "the fixture post must have no metadata to be legacy")
	legacyCtx := ctx.WithEventManager(sdk.NewEventManager())
	_, err = am.SetCurationPostHidden(legacyCtx, &types.MsgSetCurationPostHidden{
		EnvelopePubkey: f.curatorPub, Community: f.slug, TeamId: f.teamID, Target: legacyPost, Hidden: true,
	})
	require.NoError(t, err, "a legacy post must be bannable")
	got, ok := eventAttr(t, legacyCtx, "curation_post_hidden", "hidden")
	require.True(t, ok, "the legacy ban must emit curation_post_hidden")
	require.Equal(t, "true", got)

	// Existing bans must remain removable after this protection activates.
	protectedPost := genTxHash(31)
	require.NoError(t, mk.SetPostMetadata(ctx, protectedPost, &types.PostMetadata{
		Author:    f.owner,
		Community: f.slug,
	}))
	require.NoError(t, mk.SetCurationActionHiddenUser(ctx, f.slug, f.teamID, f.owner, f.curator, true))
	require.NoError(t, mk.SetCurationActionHiddenPost(ctx, f.slug, f.teamID, protectedPost, f.curator, true))
	_, err = am.SetCurationUserHidden(ctx, &types.MsgSetCurationUserHidden{
		EnvelopePubkey: f.curatorPub, Community: f.slug, TeamId: f.teamID, Target: f.owner, Hidden: false,
	})
	require.NoError(t, err)
	_, err = am.SetCurationPostHidden(ctx, &types.MsgSetCurationPostHidden{
		EnvelopePubkey: f.curatorPub, Community: f.slug, TeamId: f.teamID, Target: protectedPost, Hidden: false,
	})
	require.NoError(t, err)
}

func TestBannedUserMovesToNextCurationTeamOrRaw(t *testing.T) {
	t.Run("default and pinned users move to next best team", func(t *testing.T) {
		for _, pinned := range []bool{false, true} {
			mk, ctx, am := setupModule(t)
			f := newCurationFixture(t, mk, ctx, fmt.Sprintf("ban-reroute-%t", pinned), 0x44, 0x45)
			_, secondOwner := curationSigner(0x46)
			setPaidProfile(t, mk, ctx, secondOwner)
			secondTeamID, err := mk.CreateCurationTeam(ctx, secondOwner, f.slug, "Second", "")
			require.NoError(t, err)

			_, target := curationSigner(0x47)
			setPaidProfile(t, mk, ctx, target)
			joinOpenCommunity(t, mk, ctx, target, f.slug)
			if pinned {
				require.NoError(t, mk.SetCurationPreference(
					ctx,
					target,
					f.slug,
					types.CurationPreferenceMode_CURATION_PREFERENCE_MODE_PINNED,
					f.teamID,
					true,
				))
			}

			_, err = am.SetCurationUserHidden(ctx, &types.MsgSetCurationUserHidden{
				EnvelopePubkey: f.curatorPub,
				Community:      f.slug,
				TeamId:         f.teamID,
				Target:         target,
				Hidden:         true,
			})
			require.NoError(t, err)
			pref, found, err := mk.GetPreference(ctx, target, f.slug)
			require.NoError(t, err)
			require.True(t, found)
			require.Equal(t, types.CurationPreferenceMode_CURATION_PREFERENCE_MODE_PINNED, pref.Mode)
			require.Equal(t, secondTeamID, pref.PinnedTeamId)
			bannedTeam, found, err := mk.GetCurationTeam(ctx, f.slug, f.teamID)
			require.NoError(t, err)
			require.True(t, found)
			require.Equal(t, uint64(1), bannedTeam.SubscriberCount)
			nextTeam, found, err := mk.GetCurationTeam(ctx, f.slug, secondTeamID)
			require.NoError(t, err)
			require.True(t, found)
			require.Equal(t, uint64(2), nextTeam.SubscriberCount)
			require.ErrorContains(
				t,
				mk.SetCurationPreference(
					ctx,
					target,
					f.slug,
					types.CurationPreferenceMode_CURATION_PREFERENCE_MODE_PINNED,
					f.teamID,
					true,
				),
				"cannot pin a team that banned this user",
			)
		}
	})

	t.Run("no eligible team falls back to uncensored", func(t *testing.T) {
		mk, ctx, am := setupModule(t)
		f := newCurationFixture(t, mk, ctx, "ban-reroute-raw", 0x48, 0x49)
		_, target := curationSigner(0x4a)
		setPaidProfile(t, mk, ctx, target)
		joinOpenCommunity(t, mk, ctx, target, f.slug)

		_, err := am.SetCurationUserHidden(ctx, &types.MsgSetCurationUserHidden{
			EnvelopePubkey: f.curatorPub,
			Community:      f.slug,
			TeamId:         f.teamID,
			Target:         target,
			Hidden:         true,
		})
		require.NoError(t, err)
		pref, found, err := mk.GetPreference(ctx, target, f.slug)
		require.NoError(t, err)
		require.True(t, found)
		require.Equal(t, types.CurationPreferenceMode_CURATION_PREFERENCE_MODE_RAW, pref.Mode)
		require.Zero(t, pref.PinnedTeamId)
	})
}

func TestSetCurationPostTagRejectsClearWithTag(t *testing.T) {
	mk, ctx, am := setupModule(t)
	f := newCurationFixture(t, mk, ctx, "post-tag-clear", 0x29, 0x2a)
	post := genTxHash(9)

	_, err := am.SetCurationPostTag(ctx, &types.MsgSetCurationPostTag{
		EnvelopePubkey: f.ownerPub, Community: f.slug, TeamId: f.teamID, Target: post, Tag: "gore", Clear: true,
	})
	require.ErrorContains(t, err, "clear cannot be combined with a tag")

	_, err = am.SetCurationPostTag(ctx, &types.MsgSetCurationPostTag{
		EnvelopePubkey: f.ownerPub, Community: f.slug, TeamId: f.teamID, Target: post, Tag: "made-up",
	})
	require.ErrorContains(t, err, "invalid tag")

	// An empty tag is a decision ("this post carries no tag"); clear withdraws
	// the decision entirely. The precedence chain depends on the difference.
	_, err = am.SetCurationPostTag(ctx, &types.MsgSetCurationPostTag{
		EnvelopePubkey: f.ownerPub, Community: f.slug, TeamId: f.teamID, Target: post, Tag: "",
	})
	require.NoError(t, err)
	_, found, err := mk.GetCurationPostTag(ctx, f.slug, f.teamID, post)
	require.NoError(t, err)
	require.True(t, found)

	_, err = am.SetCurationPostTag(ctx, &types.MsgSetCurationPostTag{
		EnvelopePubkey: f.ownerPub, Community: f.slug, TeamId: f.teamID, Target: post, Clear: true,
	})
	require.NoError(t, err)
	_, found, err = mk.GetCurationPostTag(ctx, f.slug, f.teamID, post)
	require.NoError(t, err)
	require.False(t, found)
}

func TestSetCurationThreadLockedCarriesLockSequence(t *testing.T) {
	mk, ctx, am := setupModule(t)
	f := newCurationFixture(t, mk, ctx, "thread-lock", 0x2b, 0x2c)
	root := genTxHash(11)

	// Three posts precede the lock so the cut-off is not trivially zero.
	for i := 0; i < 3; i++ {
		_, err := mk.NextPostSequence(ctx)
		require.NoError(t, err)
	}

	lockCtx := ctx.WithEventManager(sdk.NewEventManager())
	_, err := am.SetCurationThreadLocked(lockCtx, &types.MsgSetCurationThreadLocked{
		EnvelopePubkey: f.curatorPub, Community: f.slug, TeamId: f.teamID, RootHash: root, Locked: true,
	})
	require.NoError(t, err)
	locked, ok := eventAttr(t, lockCtx, "curation_thread_locked", "locked")
	require.True(t, ok)
	require.Equal(t, "true", locked)
	// The indexer applies a lock by comparing each reply's global sequence
	// against this cut-off, so the event is useless without it.
	start, ok := eventAttr(t, lockCtx, "curation_thread_locked", "lock_sequence")
	require.True(t, ok, "lock_sequence must travel with the event")
	require.Equal(t, "3", start)
	end, ok := eventAttr(t, lockCtx, "curation_thread_locked", "unlock_sequence")
	require.True(t, ok, "unlock_sequence must travel with the event")
	require.Equal(t, "0", end, "a lock leaves its window open")

	unlockCtx := ctx.WithEventManager(sdk.NewEventManager())
	_, err = am.SetCurationThreadLocked(unlockCtx, &types.MsgSetCurationThreadLocked{
		EnvelopePubkey: f.curatorPub, Community: f.slug, TeamId: f.teamID, RootHash: root, Locked: false,
	})
	require.NoError(t, err)
	locked, ok = eventAttr(t, unlockCtx, "curation_thread_locked", "locked")
	require.True(t, ok)
	require.Equal(t, "false", locked)

	_, err = am.SetCurationThreadLocked(ctx, &types.MsgSetCurationThreadLocked{
		EnvelopePubkey: f.curatorPub, Community: f.slug, TeamId: f.teamID, RootHash: "not-a-hash", Locked: true,
	})
	require.Error(t, err)
}

// TestThreadLockWindowsSurviveUnlock pins what the indexer needs in order to
// keep the replies written during a lock hidden after the thread reopens. The
// chain stores only the open cut-off, so every closed window has to reach the
// indexer as a pair of sequences on the unlock event, and a redundant lock must
// never move a cut-off that already exists.
func TestThreadLockWindowsSurviveUnlock(t *testing.T) {
	mk, ctx, am := setupModule(t)
	f := newCurationFixture(t, mk, ctx, "lock-windows", 0x3b, 0x3c)
	root := genTxHash(12)

	setLocked := func(locked bool) (string, string) {
		t.Helper()
		evCtx := ctx.WithEventManager(sdk.NewEventManager())
		_, err := am.SetCurationThreadLocked(evCtx, &types.MsgSetCurationThreadLocked{
			EnvelopePubkey: f.curatorPub, Community: f.slug, TeamId: f.teamID, RootHash: root, Locked: locked,
		})
		require.NoError(t, err)
		start, ok := eventAttr(t, evCtx, "curation_thread_locked", "lock_sequence")
		require.True(t, ok)
		end, ok := eventAttr(t, evCtx, "curation_thread_locked", "unlock_sequence")
		require.True(t, ok)
		return start, end
	}
	reply := func() {
		t.Helper()
		_, err := mk.NextPostSequence(ctx)
		require.NoError(t, err)
	}

	reply() // sequence 1, written before any lock
	start, end := setLocked(true)
	require.Equal(t, "1", start)
	require.Equal(t, "0", end)

	reply() // 2, inside the window
	reply() // 3, inside the window

	// A curator clicking lock twice must not republish 2 and 3.
	start, end = setLocked(true)
	require.Equal(t, "1", start, "a redundant lock moved the cut-off forward")
	require.Equal(t, "0", end)

	start, end = setLocked(false)
	require.Equal(t, "1", start)
	require.Equal(t, "3", end, "the closed window must carry both of its ends")

	reply() // 4, written while open, stays visible

	start, end = setLocked(true)
	require.Equal(t, "4", start, "a later lock opens a new window")
	require.Equal(t, "0", end)

	// Locking and unlocking with nothing posted in between describes no reply,
	// so both ends match and the indexer stores no window for it.
	start, end = setLocked(false)
	require.Equal(t, "4", start)
	require.Equal(t, "4", end)

	// Unlocking a thread that is not locked is a no-op rather than an error.
	start, end = setLocked(false)
	require.Equal(t, "0", start)
	require.Equal(t, "0", end)
}

// TestThreadLockWindowCap is the bound on the indexer's window list. It cannot
// be enforced there: dropping the oldest window republishes what a curator hid
// and merging two windows hides replies written while the thread was open, so
// the chain refuses the lock instead and nothing already hidden moves.
// The cap lives in the keeper, and the handler in front of it spends a quota
// unit per call, so driving a hundred cycles through the handler would test the
// daily relay quota instead of the cap. The handler path is covered above.
func TestThreadLockWindowCap(t *testing.T) {
	mk, ctx, _ := setupModule(t)
	f := newCurationFixture(t, mk, ctx, "lock-cap", 0x4b, 0x4c)
	root := genTxHash(13)

	// Every cycle opens one window, and the count has to outlive the unlock that
	// deletes the lock key, or the cap would reset on every unlock.
	for i := 0; i < types.MaxThreadLockWindows; i++ {
		require.NoError(t,
			mk.SetCurationThreadLocked(ctx, f.slug, f.teamID, root, f.curator, true),
			"lock %d of %d", i+1, types.MaxThreadLockWindows,
		)
		require.NoError(t,
			mk.SetCurationThreadLocked(ctx, f.slug, f.teamID, root, f.curator, false),
			"unlock %d", i+1,
		)
	}
	err := mk.SetCurationThreadLocked(ctx, f.slug, f.teamID, root, f.curator, true)
	require.ErrorContains(t, err, "thread lock limit reached")

	// A refused lock must leave the thread unlocked rather than half-applied, so
	// an unlock right after it describes no window at all.
	evCtx := ctx.WithEventManager(sdk.NewEventManager())
	require.NoError(t,
		mk.SetCurationThreadLocked(evCtx, f.slug, f.teamID, root, f.curator, false),
		"unlocking at the cap must still work",
	)
	start, ok := eventAttr(t, evCtx, "curation_thread_locked", "lock_sequence")
	require.True(t, ok)
	require.Equal(t, "0", start, "the rejected lock was applied anyway")

	// The cap is per thread and per team, so a different thread starts at zero.
	require.NoError(t,
		mk.SetCurationThreadLocked(ctx, f.slug, f.teamID, genTxHash(14), f.curator, true),
		"the cap leaked across threads",
	)
}

// =========================================================================
// Deleted teams accept no further curation
// =========================================================================

func TestDeletedTeamRejectsFurtherCuration(t *testing.T) {
	mk, ctx, am := setupModule(t)
	f := newCurationFixture(t, mk, ctx, "deleted-team", 0x2d, 0x2e)

	_, err := am.DeleteCurationTeam(ctx, &types.MsgDeleteCurationTeam{
		EnvelopePubkey: f.curatorPub, Community: f.slug, TeamId: f.teamID,
	})
	require.ErrorContains(t, err, "only the team owner")

	_, err = am.DeleteCurationTeam(ctx, &types.MsgDeleteCurationTeam{
		EnvelopePubkey: f.ownerPub, Community: f.slug, TeamId: f.teamID,
	})
	require.NoError(t, err)
	require.Empty(t, teamMemberAddrs(t, mk, ctx, f.slug, f.teamID), "delete must drain the roster")

	for name, call := range map[string]func() error{
		"hide_post": func() error {
			_, err := am.SetCurationPostHidden(ctx, &types.MsgSetCurationPostHidden{
				EnvelopePubkey: f.ownerPub, Community: f.slug, TeamId: f.teamID, Target: genTxHash(13), Hidden: true,
			})
			return err
		},
		"subscriber_only": func() error {
			_, err := am.SetCurationSubscriberOnly(ctx, &types.MsgSetCurationSubscriberOnly{
				EnvelopePubkey: f.ownerPub, Community: f.slug, TeamId: f.teamID, Enabled: true,
			})
			return err
		},
		"invite": func() error {
			_, err := am.InviteCurator(ctx, &types.MsgInviteCurator{
				EnvelopePubkey: f.ownerPub, Community: f.slug, TeamId: f.teamID, Target: f.curator,
			})
			return err
		},
		"transfer": func() error {
			_, err := am.TransferCurationTeam(ctx, &types.MsgTransferCurationTeam{
				EnvelopePubkey: f.ownerPub, Community: f.slug, TeamId: f.teamID, NewOwner: f.curator,
			})
			return err
		},
		"delete_again": func() error {
			_, err := am.DeleteCurationTeam(ctx, &types.MsgDeleteCurationTeam{
				EnvelopePubkey: f.ownerPub, Community: f.slug, TeamId: f.teamID,
			})
			return err
		},
	} {
		require.ErrorContains(t, call(), "team not found", "deleted team must reject %s", name)
	}
}

// =========================================================================
// max_curation_memberships
// =========================================================================

func TestCurationMembershipCapAppliesToCreateAndAccept(t *testing.T) {
	mk, ctx, am := setupModule(t)
	params := mk.GetParams(ctx)
	params.Tiers[types.LevelSubscriber].MaxCurationMemberships = 1
	require.NoError(t, mk.SetParams(ctx, params))

	founderPub, founder := curationSigner(0x31)
	joinerPub, joiner := curationSigner(0x32)
	setPaidProfile(t, mk, ctx, founder)
	setPaidProfile(t, mk, ctx, joiner)

	_, err := am.CreateCurationTeam(ctx, &types.MsgCreateCurationTeam{
		EnvelopePubkey: founderPub, Community: "cap-one", Name: "First", Description: "",
	})
	require.NoError(t, err)
	_, err = am.CreateCurationTeam(ctx, &types.MsgCreateCurationTeam{
		EnvelopePubkey: founderPub, Community: "cap-two", Name: "Second", Description: "",
	})
	require.ErrorContains(t, err, "curation membership cap reached")

	// The cap is enforced at both entry points, so accepting an invitation
	// cannot be used to exceed what creating a team refuses.
	_, err = am.CreateCurationTeam(ctx, &types.MsgCreateCurationTeam{
		EnvelopePubkey: joinerPub, Community: "cap-two", Name: "JoinerTeam", Description: "",
	})
	require.NoError(t, err)
	require.NoError(t, mk.InviteCurator(ctx, founder, "cap-one", 1, joiner))
	_, err = am.AcceptCuratorInvite(ctx, &types.MsgAcceptCuratorInvite{
		EnvelopePubkey: joinerPub, Community: "cap-one", TeamId: 1,
	})
	require.ErrorContains(t, err, "curation membership cap reached")

	params.Tiers[types.LevelSubscriber].MaxCurationMemberships = 2
	require.NoError(t, mk.SetParams(ctx, params))
	_, err = am.AcceptCuratorInvite(ctx, &types.MsgAcceptCuratorInvite{
		EnvelopePubkey: joinerPub, Community: "cap-one", TeamId: 1,
	})
	require.NoError(t, err)
	t.Logf("[debug] curation membership cap raised to 2, accept succeeded joiner=%s", joiner[:12])
}

func TestFreeTierCannotCurate(t *testing.T) {
	mk, ctx, am := setupModule(t)
	freePub, free := curationSigner(0x33)
	ensureUsername(t, mk, ctx, free, "Anon-freecurator")

	freeTier := mk.GetParams(ctx).GetTierConfig(types.LevelFree)
	require.NotNil(t, freeTier)
	require.Zero(t, freeTier.MaxCurationMemberships, "the free tier holds no curation memberships")

	_, err := am.CreateCurationTeam(ctx, &types.MsgCreateCurationTeam{
		EnvelopePubkey: freePub, Community: "free-curate", Name: "FreeTeam", Description: "",
	})
	require.ErrorContains(t, err, "active subscriber or admin")

	f := newCurationFixture(t, mk, ctx, "free-invite", 0x34, 0x35)
	require.ErrorContains(t,
		mk.InviteCurator(ctx, f.owner, f.slug, f.teamID, free),
		"active subscriber or admin",
		"a free user must not even be invitable")
}
