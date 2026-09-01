package keeper

import (
	"encoding/binary"
	"fmt"

	sdk "github.com/cosmos/cosmos-sdk/types"

	"mirage/x/core/types"
)

func (k Keeper) CreateCurationTeam(ctx sdk.Context, owner, slug, name, description string) (uint64, error) {
	params := k.GetParams(ctx)
	if _, err := types.CanonicalAccBytes(owner); err != nil {
		return 0, err
	}
	if err := types.ValidateCommunitySlug(slug, params.MinCommunitySize, params.MaxCommunitySize); err != nil {
		return 0, err
	}
	if err := types.ValidateCurationTeamName(name, params.MaxCurationTeamNameLength); err != nil {
		return 0, err
	}
	description, err := types.NormalizeCurationTeamDescription(description, params.MaxCurationTeamDescriptionLength)
	if err != nil {
		return 0, err
	}
	core, found, err := k.loadProfile(ctx, owner)
	if err != nil {
		return 0, err
	}
	if !found || !types.CanCurate(core) {
		return 0, fmt.Errorf("creating a curation team requires an active subscriber or admin")
	}
	// Creating a team does not require joining the community first; accept
	// auto-joins the invitee the same way.
	if _, occupied, err := k.getU64Key(ctx, types.KeyCurationTeamUser(owner, slug)); err != nil {
		return 0, err
	} else if occupied {
		return 0, fmt.Errorf("already a curator in this community")
	}
	norm := types.NormalizeTeamNameKey(name)
	if taken, err := k.storeHas(ctx, types.KeyCurationTeamName(slug, norm)); err != nil {
		return 0, err
	} else if taken {
		return 0, fmt.Errorf("team name already used in this community")
	}
	tier := params.GetTierConfig(int(core.Level))
	if tier == nil {
		return 0, fmt.Errorf("tier config not found")
	}
	cur, _, err := k.getU32Key(ctx, types.KeyCurationTeamUserCount(owner))
	if err != nil {
		return 0, err
	}
	if uint64(cur) >= tier.MaxCurationMemberships {
		return 0, fmt.Errorf("curation membership cap reached")
	}
	next, _, err := k.getU64Key(ctx, types.KeyCurationTeamNext(slug))
	if err != nil {
		return 0, err
	}
	if next == 0 {
		next = 1
	}
	nextID, err := types.CheckedAddUint64(next, 1)
	if err != nil {
		return 0, err
	}
	if err := k.setU64Key(ctx, types.KeyCurationTeamNext(slug), nextID); err != nil {
		return 0, err
	}
	team := &types.CurationTeam{
		Community:       slug,
		TeamId:          next,
		Owner:           owner,
		Name:            name,
		Description:     description,
		CreatedHeight:   ctx.BlockHeight(),
		CreatedOrder:    next,
		NextMemberOrder: 2,
	}
	if err := k.SetCurationTeam(ctx, team); err != nil {
		return 0, err
	}
	member := &types.CurationTeamMember{Address: owner, AcceptedOrder: 1}
	if err := k.setProto(ctx, types.KeyCurationTeamMember(slug, next, owner), member); err != nil {
		return 0, err
	}
	if err := k.setU64Key(ctx, types.KeyCurationTeamUser(owner, slug), next); err != nil {
		return 0, err
	}
	if _, err := k.addCheckedU32(ctx, types.KeyCurationTeamUserCount(owner), 1); err != nil {
		return 0, err
	}
	if err := k.storeSet(ctx, types.KeyCurationTeamName(slug, norm), putU64(next)); err != nil {
		return 0, err
	}
	// Founder is the first subscriber: join (if needed) and pin this team.
	// Counts via CanCurate so paid founders and admins both register as 1 sub.
	if err := k.JoinCommunity(ctx, owner, slug, uint32(tier.MaxJoinedCommunities)); err != nil {
		return 0, err
	}
	if err := k.SetCurationPreference(
		ctx,
		owner,
		slug,
		types.CurationPreferenceMode_CURATION_PREFERENCE_MODE_PINNED,
		next,
		types.CanCurate(core),
	); err != nil {
		return 0, err
	}
	ctx.EventManager().EmitEvent(sdk.NewEvent("curation_team_created",
		sdk.NewAttribute("community", slug),
		sdk.NewAttribute("team_id", fmt.Sprintf("%d", next)),
		sdk.NewAttribute("owner", owner),
		sdk.NewAttribute("name", name),
		sdk.NewAttribute("description", description),
		sdk.NewAttribute("created_height", fmt.Sprintf("%d", team.CreatedHeight)),
		sdk.NewAttribute("created_order", fmt.Sprintf("%d", team.CreatedOrder)),
		sdk.NewAttribute("subscriber_count", "1"),
	))
	return next, nil
}

func (k Keeper) InviteCurator(ctx sdk.Context, actor, slug string, teamID uint64, target string) error {
	team, ok, err := k.GetCurationTeam(ctx, slug, teamID)
	if err != nil {
		return err
	}
	if !ok || !k.teamLive(team) {
		return fmt.Errorf("team not found")
	}
	if team.Owner != actor {
		return fmt.Errorf("only the team owner may invite")
	}
	if target == actor {
		return fmt.Errorf("team owner is already a curator")
	}
	if _, err := types.CanonicalAccBytes(target); err != nil {
		return err
	}
	params := k.GetParams(ctx)
	core, found, err := k.loadProfile(ctx, target)
	if err != nil {
		return err
	}
	if !found || !types.CanCurate(core) {
		return fmt.Errorf("invitee must be an active subscriber or admin")
	}
	// Invitee need not be joined yet — AcceptCuratorInvite auto-joins them.
	if _, occupied, err := k.getU64Key(ctx, types.KeyCurationTeamUser(target, slug)); err != nil {
		return err
	} else if occupied {
		return fmt.Errorf("invitee already curates in this community")
	}
	if has, err := k.storeHas(ctx, types.KeyCurationInvite(slug, teamID, target)); err != nil {
		return err
	} else if has {
		return fmt.Errorf("invitation already pending")
	}
	members, err := k.countTeamMembers(ctx, slug, teamID, params.MaxCuratorsPerTeam)
	if err != nil {
		return err
	}
	if members >= params.MaxCuratorsPerTeam {
		return fmt.Errorf("team is full")
	}
	pendingTeam, err := k.countTeamInvites(ctx, slug, teamID, params.MaxCuratorsPerTeam)
	if err != nil {
		return err
	}
	if pendingTeam >= params.MaxPendingCuratorInvitesPerTeam {
		return fmt.Errorf("too many pending invites for this team")
	}
	if members+pendingTeam >= params.MaxCuratorsPerTeam {
		return fmt.Errorf("accepted curators plus pending invitations reached team capacity")
	}
	pc, _, err := k.getU32Key(ctx, types.KeyCurationInviteCount(target))
	if err != nil {
		return err
	}
	if uint64(pc) >= params.MaxPendingCuratorInvitesPerUser {
		return fmt.Errorf("too many pending invites for this user")
	}
	if err := k.storeSet(ctx, types.KeyCurationInvite(slug, teamID, target), []byte(actor)); err != nil {
		return err
	}
	if err := k.storeSet(ctx, types.KeyCurationInviteRev(target, slug, teamID), []byte{1}); err != nil {
		return err
	}
	if _, err := k.addCheckedU32(ctx, types.KeyCurationInviteCount(target), 1); err != nil {
		return err
	}
	ctx.EventManager().EmitEvent(sdk.NewEvent("curator_invited",
		sdk.NewAttribute("community", slug),
		sdk.NewAttribute("team_id", fmt.Sprintf("%d", teamID)),
		sdk.NewAttribute("target", target),
		sdk.NewAttribute("inviter", actor),
		sdk.NewAttribute("status", "pending"),
	))
	return nil
}

func (k Keeper) countTeamMembers(ctx sdk.Context, slug string, teamID, max uint64) (uint64, error) {
	var count uint64
	err := k.iterPrefixKeys(ctx, types.KeyCurationTeamMemberPrefix(slug, teamID), int(max)+1, func(_, _ []byte) error {
		count++
		if count > max {
			return fmt.Errorf("team member count exceeds configured maximum")
		}
		return nil
	})
	return count, err
}

func (k Keeper) countTeamInvites(ctx sdk.Context, slug string, teamID, max uint64) (uint64, error) {
	var count uint64
	err := k.iterPrefixKeys(ctx, types.KeyCurationInvitePrefix(slug, teamID), int(max)+1, func(_, _ []byte) error {
		count++
		if count > max {
			return fmt.Errorf("team invitation count exceeds configured maximum")
		}
		return nil
	})
	return count, err
}

func (k Keeper) ClearInvite(ctx sdk.Context, slug string, teamID uint64, target string) error {
	if _, err := types.CanonicalAccBytes(target); err != nil {
		return err
	}
	has, err := k.storeHas(ctx, types.KeyCurationInvite(slug, teamID, target))
	if err != nil {
		return err
	}
	if !has {
		return fmt.Errorf("no pending invitation")
	}
	return k.clearInvite(ctx, slug, teamID, target)
}

// ClearPendingInvitationsForTarget must clear all of them, so the enumeration is
// not bounded by the current per-user cap: a cap lowered after the invitations
// were accepted into the store would otherwise abort this mid-way, and it runs on
// the subscription-expiry path where that means a halt.
func (k Keeper) ClearPendingInvitationsForTarget(ctx sdk.Context, target string) error {
	type invitation struct {
		slug   string
		teamID uint64
	}
	var pending []invitation
	pfx := types.KeyCurationInviteRevPrefix(target)
	if err := k.iterPrefixKeys(ctx, pfx, 0, func(key, _ []byte) error {
		rest := key[len(pfx):]
		if len(rest) < 2 {
			return fmt.Errorf("malformed reverse invitation key")
		}
		n := int(binary.BigEndian.Uint16(rest[:2]))
		if len(rest) != 2+n+8 {
			return fmt.Errorf("malformed reverse invitation key")
		}
		pending = append(pending, invitation{
			slug:   string(rest[2 : 2+n]),
			teamID: binary.BigEndian.Uint64(rest[2+n:]),
		})
		return nil
	}); err != nil {
		return err
	}
	for _, inv := range pending {
		if err := k.clearInvite(ctx, inv.slug, inv.teamID, target); err != nil {
			return err
		}
	}
	return nil
}

func (k Keeper) RequireTeamOwner(ctx sdk.Context, actor, slug string, teamID uint64) (*types.CurationTeam, error) {
	return k.requireTeamActor(ctx, actor, slug, teamID, true)
}

func (k Keeper) RequireTeamCurator(ctx sdk.Context, actor, slug string, teamID uint64) (*types.CurationTeam, error) {
	return k.requireTeamActor(ctx, actor, slug, teamID, false)
}

func (k Keeper) IsCommunityCurator(ctx sdk.Context, actor, slug string) (bool, error) {
	if _, err := types.CanonicalAccBytes(actor); err != nil {
		return false, err
	}
	teamID, found, err := k.getU64Key(ctx, types.KeyCurationTeamUser(actor, slug))
	if err != nil || !found {
		return false, err
	}
	team, found, err := k.GetCurationTeam(ctx, slug, teamID)
	if err != nil {
		return false, err
	}
	if !found {
		return false, fmt.Errorf("curation membership points to missing team community=%s team=%d", slug, teamID)
	}
	return k.teamLive(team), nil
}

func (k Keeper) UpdateCurationTeamProfile(ctx sdk.Context, actor, slug string, teamID uint64, name, description string) error {
	team, err := k.RequireTeamOwner(ctx, actor, slug, teamID)
	if err != nil {
		return err
	}
	params := k.GetParams(ctx)
	if err := types.ValidateCurationTeamName(name, params.MaxCurationTeamNameLength); err != nil {
		return err
	}
	description, err = types.NormalizeCurationTeamDescription(description, params.MaxCurationTeamDescriptionLength)
	if err != nil {
		return err
	}
	oldNorm := types.NormalizeTeamNameKey(team.Name)
	newNorm := types.NormalizeTeamNameKey(name)
	if oldNorm != newNorm {
		nameKey := types.KeyCurationTeamName(slug, newNorm)
		if taken, err := k.storeHas(ctx, nameKey); err != nil {
			return err
		} else if taken {
			return fmt.Errorf("team name already used in this community")
		}
		if err := k.storeDelete(ctx, types.KeyCurationTeamName(slug, oldNorm)); err != nil {
			return err
		}
		if err := k.storeSet(ctx, nameKey, putU64(teamID)); err != nil {
			return err
		}
	}
	team.Name = name
	team.Description = description
	if err := k.SetCurationTeam(ctx, team); err != nil {
		return err
	}
	ctx.EventManager().EmitEvent(sdk.NewEvent("curation_team_profile_updated",
		sdk.NewAttribute("community", slug),
		sdk.NewAttribute("team_id", fmt.Sprintf("%d", teamID)),
		sdk.NewAttribute("owner", team.Owner),
		sdk.NewAttribute("name", team.Name),
		sdk.NewAttribute("description", team.Description),
	))
	return nil
}

func (k Keeper) TransferCurationTeamOwner(ctx sdk.Context, actor, slug string, teamID uint64, newOwner string) error {
	if _, err := k.RequireTeamOwner(ctx, actor, slug, teamID); err != nil {
		return err
	}
	return k.SetCurationTeamOwner(ctx, slug, teamID, newOwner)
}

func (k Keeper) SetCurationTeamOwner(ctx sdk.Context, slug string, teamID uint64, newOwner string) error {
	team, found, err := k.GetCurationTeam(ctx, slug, teamID)
	if err != nil {
		return err
	}
	if !found || !k.teamLive(team) {
		return fmt.Errorf("team not found")
	}
	if newOwner == team.Owner {
		return fmt.Errorf("new owner is already the team owner")
	}
	if _, err := types.CanonicalAccBytes(newOwner); err != nil {
		return err
	}
	core, found, err := k.loadProfile(ctx, newOwner)
	if err != nil {
		return err
	}
	if !found || !types.CanCurate(core) {
		return fmt.Errorf("new owner must be an active subscriber or admin")
	}
	member, err := k.storeHas(ctx, types.KeyCurationTeamMember(slug, teamID, newOwner))
	if err != nil {
		return err
	}
	if !member {
		return fmt.Errorf("new owner must be an accepted curator")
	}
	oldOwner := team.Owner
	team.Owner = newOwner
	if err := k.SetCurationTeam(ctx, team); err != nil {
		return err
	}
	ctx.EventManager().EmitEvent(sdk.NewEvent("curation_team_owner_changed",
		sdk.NewAttribute("community", slug),
		sdk.NewAttribute("team_id", fmt.Sprintf("%d", teamID)),
		sdk.NewAttribute("old_owner", oldOwner),
		sdk.NewAttribute("new_owner", newOwner),
	))
	return nil
}

func (k Keeper) clearInvite(ctx sdk.Context, slug string, teamID uint64, target string) error {
	has, err := k.storeHas(ctx, types.KeyCurationInvite(slug, teamID, target))
	if err != nil {
		return err
	}
	if !has {
		return nil
	}
	if err := k.storeDelete(ctx, types.KeyCurationInvite(slug, teamID, target)); err != nil {
		return err
	}
	if err := k.storeDelete(ctx, types.KeyCurationInviteRev(target, slug, teamID)); err != nil {
		return err
	}
	_, err = k.addCheckedU32(ctx, types.KeyCurationInviteCount(target), -1)
	return err
}

func (k Keeper) AcceptCuratorInvite(ctx sdk.Context, actor, slug string, teamID uint64) error {
	inviteKey := types.KeyCurationInvite(slug, teamID, actor)
	has, err := k.storeHas(ctx, inviteKey)
	if err != nil {
		return err
	}
	if !has {
		return fmt.Errorf("no pending invitation")
	}
	inviter, err := k.storeGet(ctx, inviteKey)
	if err != nil {
		return err
	}
	team, ok, err := k.GetCurationTeam(ctx, slug, teamID)
	if err != nil {
		return err
	}
	if !ok || !k.teamLive(team) {
		return fmt.Errorf("team not found")
	}
	core, found, err := k.loadProfile(ctx, actor)
	if err != nil {
		return err
	}
	if !found || !types.CanCurate(core) {
		return fmt.Errorf("must be an active subscriber or admin")
	}
	if _, occupied, err := k.getU64Key(ctx, types.KeyCurationTeamUser(actor, slug)); err != nil {
		return err
	} else if occupied {
		return fmt.Errorf("already a curator in this community")
	}
	params := k.GetParams(ctx)
	tier := params.GetTierConfig(int(core.Level))
	if tier == nil {
		return fmt.Errorf("tier config not found")
	}
	cur, _, err := k.getU32Key(ctx, types.KeyCurationTeamUserCount(actor))
	if err != nil {
		return err
	}
	if uint64(cur) >= tier.MaxCurationMemberships {
		return fmt.Errorf("curation membership cap reached")
	}
	members, err := k.countTeamMembers(ctx, slug, teamID, params.MaxCuratorsPerTeam)
	if err != nil {
		return err
	}
	if members >= params.MaxCuratorsPerTeam {
		return fmt.Errorf("team is full")
	}
	// Accepting a curator invite auto-joins the community (same as CreateCurationTeam).
	if err := k.JoinCommunity(ctx, actor, slug, uint32(tier.MaxJoinedCommunities)); err != nil {
		return err
	}
	order := team.NextMemberOrder
	if order == 0 {
		return fmt.Errorf("invalid next curator accepted order")
	}
	nextOrder, err := types.CheckedAddUint64(order, 1)
	if err != nil {
		return err
	}
	team.NextMemberOrder = nextOrder
	if err := k.SetCurationTeam(ctx, team); err != nil {
		return err
	}
	member := &types.CurationTeamMember{Address: actor, AcceptedOrder: order}
	if err := k.setProto(ctx, types.KeyCurationTeamMember(slug, teamID, actor), member); err != nil {
		return err
	}
	if err := k.setU64Key(ctx, types.KeyCurationTeamUser(actor, slug), teamID); err != nil {
		return err
	}
	if _, err := k.addCheckedU32(ctx, types.KeyCurationTeamUserCount(actor), 1); err != nil {
		return err
	}
	if err := k.clearInvite(ctx, slug, teamID, actor); err != nil {
		return err
	}
	ctx.EventManager().EmitEvent(sdk.NewEvent("curator_joined",
		sdk.NewAttribute("community", slug),
		sdk.NewAttribute("team_id", fmt.Sprintf("%d", teamID)),
		sdk.NewAttribute("address", actor),
		sdk.NewAttribute("accepted_order", fmt.Sprintf("%d", order)),
		sdk.NewAttribute("member_count", fmt.Sprintf("%d", members+1)),
	))
	ctx.EventManager().EmitEvent(sdk.NewEvent("curator_invitation_accepted",
		sdk.NewAttribute("community", slug),
		sdk.NewAttribute("team_id", fmt.Sprintf("%d", teamID)),
		sdk.NewAttribute("target", actor),
		sdk.NewAttribute("inviter", string(inviter)),
		sdk.NewAttribute("status", "accepted"),
	))
	return nil
}

func (k Keeper) RemoveCuratorFromTeam(ctx sdk.Context, slug string, teamID uint64, target string, emit string) error {
	if _, err := types.CanonicalAccBytes(target); err != nil {
		return err
	}
	var member types.CurationTeamMember
	found, err := k.getProto(ctx, types.KeyCurationTeamMember(slug, teamID, target), &member)
	if err != nil {
		return err
	}
	if !found {
		return fmt.Errorf("curator is not a member of this team")
	}
	if err := k.storeDelete(ctx, types.KeyCurationTeamMember(slug, teamID, target)); err != nil {
		return err
	}
	if err := k.storeDelete(ctx, types.KeyCurationTeamUser(target, slug)); err != nil {
		return err
	}
	if _, err := k.addCheckedU32(ctx, types.KeyCurationTeamUserCount(target), -1); err != nil {
		return err
	}
	params := k.GetParams(ctx)
	memberCount, err := k.countTeamMembers(ctx, slug, teamID, params.MaxCuratorsPerTeam)
	if err != nil {
		return err
	}
	if emit != "" {
		ctx.EventManager().EmitEvent(sdk.NewEvent(emit,
			sdk.NewAttribute("community", slug),
			sdk.NewAttribute("team_id", fmt.Sprintf("%d", teamID)),
			sdk.NewAttribute("address", target),
			sdk.NewAttribute("accepted_order", fmt.Sprintf("%d", member.AcceptedOrder)),
			sdk.NewAttribute("member_count", fmt.Sprintf("%d", memberCount)),
		))
	}
	return nil
}

func (k Keeper) DeleteCurationTeam(ctx sdk.Context, slug string, teamID uint64) error {
	team, ok, err := k.GetCurationTeam(ctx, slug, teamID)
	if err != nil {
		return err
	}
	if !ok || !k.teamLive(team) {
		return fmt.Errorf("team not found")
	}
	previousSubscriberCount := team.SubscriberCount
	// Deleting a team has to drain the whole roster and invite list. Stopping at
	// the current cap would leave orphaned members pointing at a deleted team if
	// governance ever lowered max_curators_per_team below an existing roster.
	var members []string
	if err := k.iterPrefixKeys(ctx, types.KeyCurationTeamMemberPrefix(slug, teamID), 0, func(key, _ []byte) error {
		addr := sdk.AccAddress(key[len(key)-20:]).String()
		members = append(members, addr)
		return nil
	}); err != nil {
		return err
	}
	for _, m := range members {
		if err := k.RemoveCuratorFromTeam(ctx, slug, teamID, m, "curator_removed"); err != nil {
			return err
		}
	}
	var invitees []string
	if err := k.iterPrefixKeys(ctx, types.KeyCurationInvitePrefix(slug, teamID), 0, func(key, _ []byte) error {
		addr := sdk.AccAddress(key[len(key)-20:]).String()
		invitees = append(invitees, addr)
		return nil
	}); err != nil {
		return err
	}
	for _, inv := range invitees {
		if err := k.clearInvite(ctx, slug, teamID, inv); err != nil {
			return err
		}
	}
	if err := k.storeDelete(ctx, types.KeyCurationTeamName(slug, types.NormalizeTeamNameKey(team.Name))); err != nil {
		return err
	}
	team.SubscriberCount = 0
	team.DeletedHeight = ctx.BlockHeight()
	if err := k.SetCurationTeam(ctx, team); err != nil {
		return err
	}
	ctx.EventManager().EmitEvent(sdk.NewEvent("curation_team_deleted",
		sdk.NewAttribute("community", slug),
		sdk.NewAttribute("team_id", fmt.Sprintf("%d", teamID)),
		sdk.NewAttribute("deleted_height", fmt.Sprintf("%d", team.DeletedHeight)),
		sdk.NewAttribute("previous_subscriber_count", fmt.Sprintf("%d", previousSubscriberCount)),
	))
	return nil
}

func (k Keeper) SetCurationActionHiddenPost(ctx sdk.Context, slug string, teamID uint64, hash, actor string, hidden bool) error {
	h, err := types.HashBytes(hash)
	if err != nil {
		return err
	}
	key := types.KeyHiddenPost(slug, teamID, h)
	if hidden {
		if err := k.storeSet(ctx, key, []byte(actor)); err != nil {
			return err
		}
	} else {
		if err := k.storeDelete(ctx, key); err != nil {
			return err
		}
	}
	ctx.EventManager().EmitEvent(sdk.NewEvent("curation_post_hidden",
		sdk.NewAttribute("community", slug),
		sdk.NewAttribute("team_id", fmt.Sprintf("%d", teamID)),
		sdk.NewAttribute("target", hash),
		sdk.NewAttribute("hidden", fmt.Sprintf("%t", hidden)),
		sdk.NewAttribute("actor", actor),
	))
	return nil
}

// SetCurationTeamTag sets the blanket community tag carried by every post read
// through this team. The caller validates the tag against the content-tag
// whitelist before calling.
func (k Keeper) SetCurationTeamTag(ctx sdk.Context, slug string, teamID uint64, tag string) error {
	team, found, err := k.GetCurationTeam(ctx, slug, teamID)
	if err != nil {
		return err
	}
	if !found || !k.teamLive(team) {
		return fmt.Errorf("team not found")
	}
	team.Tag = tag
	if err := k.SetCurationTeam(ctx, team); err != nil {
		return err
	}
	ctx.EventManager().EmitEvent(sdk.NewEvent("curation_tag_changed",
		sdk.NewAttribute("community", slug),
		sdk.NewAttribute("team_id", fmt.Sprintf("%d", teamID)),
		sdk.NewAttribute("tag", tag),
	))
	return nil
}

// SetCurationPostTag records this team's tag decision for one post. clear drops
// the record so the community tag and then the author's own tag apply again;
// storing an empty tag is the different, deliberate claim that the post carries
// no tag at all.
func (k Keeper) SetCurationPostTag(ctx sdk.Context, slug string, teamID uint64, hash, tag, actor string, clear bool) error {
	h, err := types.HashBytes(hash)
	if err != nil {
		return err
	}
	key := types.KeyCurationPostTag(slug, teamID, h)
	if clear {
		if err := k.storeDelete(ctx, key); err != nil {
			return err
		}
	} else {
		record := &types.CurationPostTag{Tag: tag, Actor: actor, UpdatedHeight: ctx.BlockHeight()}
		if err := k.setProto(ctx, key, record); err != nil {
			return err
		}
	}
	ctx.EventManager().EmitEvent(sdk.NewEvent("curation_post_tag_changed",
		sdk.NewAttribute("community", slug),
		sdk.NewAttribute("team_id", fmt.Sprintf("%d", teamID)),
		sdk.NewAttribute("target", hash),
		sdk.NewAttribute("tag", tag),
		sdk.NewAttribute("cleared", fmt.Sprintf("%t", clear)),
		sdk.NewAttribute("actor", actor),
	))
	return nil
}

// GetCurationPostTag reports this team's tag decision for a post. The bool
// distinguishes "no decision" from a decision of "no tag".
func (k Keeper) GetCurationPostTag(ctx sdk.Context, slug string, teamID uint64, hash string) (*types.CurationPostTag, bool, error) {
	h, err := types.HashBytes(hash)
	if err != nil {
		return nil, false, err
	}
	var record types.CurationPostTag
	found, err := k.getProto(ctx, types.KeyCurationPostTag(slug, teamID, h), &record)
	if err != nil || !found {
		return nil, found, err
	}
	return &record, true, nil
}

func (k Keeper) bestCurationTeamForUser(ctx sdk.Context, slug, target string, allowHiddenTeamID uint64) (*types.CurationTeam, bool, error) {
	if target != "" {
		if _, err := types.CanonicalAccBytes(target); err != nil {
			return nil, false, err
		}
	}
	var best *types.CurationTeam
	if err := k.iterPrefixKeys(ctx, types.KeyCurationTeamPrefix(slug), 0, func(_, value []byte) error {
		var team types.CurationTeam
		if err := k.cdc.Unmarshal(value, &team); err != nil {
			return err
		}
		if !k.teamLive(&team) {
			return nil
		}
		if target != "" && team.TeamId != allowHiddenTeamID {
			hidden, err := k.storeHas(ctx, types.KeyHiddenUser(slug, team.TeamId, target))
			if err != nil {
				return err
			}
			if hidden {
				return nil
			}
		}
		if best == nil ||
			team.SubscriberCount > best.SubscriberCount ||
			(team.SubscriberCount == best.SubscriberCount && team.CreatedOrder < best.CreatedOrder) ||
			(team.SubscriberCount == best.SubscriberCount && team.CreatedOrder == best.CreatedOrder && team.TeamId < best.TeamId) {
			copyTeam := team
			best = &copyTeam
		}
		return nil
	}); err != nil {
		return nil, false, err
	}
	return best, best != nil, nil
}

func (k Keeper) RerouteBannedUserPreference(ctx sdk.Context, slug string, bannedTeamID uint64, target string) error {
	pref, joined, err := k.GetPreference(ctx, target, slug)
	if err != nil || !joined {
		return err
	}
	if pref.Mode == types.CurationPreferenceMode_CURATION_PREFERENCE_MODE_RAW {
		return nil
	}

	var currentTeamID uint64
	if pref.Mode == types.CurationPreferenceMode_CURATION_PREFERENCE_MODE_PINNED {
		team, found, err := k.GetCurationTeam(ctx, slug, pref.PinnedTeamId)
		if err != nil {
			return err
		}
		if found && k.teamLive(team) {
			currentTeamID = pref.PinnedTeamId
		}
	}
	if currentTeamID == 0 {
		current, found, err := k.bestCurationTeamForUser(ctx, slug, target, bannedTeamID)
		if err != nil {
			return err
		}
		if found {
			currentTeamID = current.TeamId
		}
	}
	if currentTeamID != bannedTeamID {
		return nil
	}

	core, found, err := k.loadProfile(ctx, target)
	if err != nil {
		return err
	}
	if !found {
		return fmt.Errorf("profile not found for joined user %s", target)
	}
	next, found, err := k.bestCurationTeamForUser(ctx, slug, target, 0)
	if err != nil {
		return err
	}
	if !found {
		return k.SetCurationPreference(
			ctx,
			target,
			slug,
			types.CurationPreferenceMode_CURATION_PREFERENCE_MODE_RAW,
			0,
			types.CanCurate(core),
		)
	}
	return k.SetCurationPreference(
		ctx,
		target,
		slug,
		types.CurationPreferenceMode_CURATION_PREFERENCE_MODE_PINNED,
		next.TeamId,
		types.CanCurate(core),
	)
}

func (k Keeper) SetCurationActionHiddenUser(ctx sdk.Context, slug string, teamID uint64, target, actor string, hidden bool) error {
	if _, err := types.CanonicalAccBytes(target); err != nil {
		return err
	}
	key := types.KeyHiddenUser(slug, teamID, target)
	if hidden {
		if err := k.storeSet(ctx, key, []byte(actor)); err != nil {
			return err
		}
	} else {
		if err := k.storeDelete(ctx, key); err != nil {
			return err
		}
	}
	ctx.EventManager().EmitEvent(sdk.NewEvent("curation_user_hidden",
		sdk.NewAttribute("community", slug),
		sdk.NewAttribute("team_id", fmt.Sprintf("%d", teamID)),
		sdk.NewAttribute("target", target),
		sdk.NewAttribute("hidden", fmt.Sprintf("%t", hidden)),
		sdk.NewAttribute("actor", actor),
	))
	return nil
}

// SetCurationThreadLocked opens or closes this team's lock on one thread.
//
// The chain stores only the cut-off of the window that is currently open, which
// is all it needs to decide anything. Accumulating the history of past windows
// is the indexer's job: a thread can be locked and unlocked repeatedly, and the
// replies written during each locked stretch have to stay hidden after the
// thread reopens, so the event carries both ends of the window it closes.
//
// That list of windows has to be bounded, and it cannot be bounded after the
// fact without either republishing or over-hiding replies, so the bound is a
// hard cap here: window MaxThreadLockWindows+1 is rejected.
func (k Keeper) SetCurationThreadLocked(ctx sdk.Context, slug string, teamID uint64, root, actor string, locked bool) error {
	h, err := types.HashBytes(root)
	if err != nil {
		return err
	}
	key := types.KeyThreadLock(slug, teamID, h)
	stored, wasLocked, err := k.getU64Key(ctx, key)
	if err != nil {
		return err
	}
	seq, _, err := k.getU64Key(ctx, []byte(types.PfxPostSeq))
	if err != nil {
		return err
	}
	// lockSequence is where the window this event describes begins, and
	// unlockSequence where it ends; 0 means the window is still open. Both are
	// global post sequences, so a reply is inside the window exactly when
	// lockSequence < its sequence <= unlockSequence.
	var lockSequence, unlockSequence uint64
	switch {
	case locked && wasLocked:
		// Re-locking must not move the cut-off forward: that would un-hide
		// every reply written since the thread was originally locked.
		lockSequence = stored
	case locked:
		// Opening a window is what the cap counts, so the count is read here and
		// not on the redundant-lock or unlock paths. It survives the unlock that
		// deletes the lock key, which is the only reason it is a separate key.
		countKey := types.KeyThreadLockCount(slug, teamID, h)
		used, _, err := k.getU64Key(ctx, countKey)
		if err != nil {
			return err
		}
		if used >= types.MaxThreadLockWindows {
			return fmt.Errorf("thread lock limit reached: this team has locked this thread %d times", types.MaxThreadLockWindows)
		}
		if err := k.setU64Key(ctx, countKey, used+1); err != nil {
			return err
		}
		if err := k.storeSet(ctx, key, putU64(seq)); err != nil {
			return err
		}
		lockSequence = seq
	case wasLocked:
		if err := k.storeDelete(ctx, key); err != nil {
			return err
		}
		lockSequence = stored
		unlockSequence = seq
	}
	ctx.EventManager().EmitEvent(sdk.NewEvent("curation_thread_locked",
		sdk.NewAttribute("community", slug),
		sdk.NewAttribute("team_id", fmt.Sprintf("%d", teamID)),
		sdk.NewAttribute("target", root),
		sdk.NewAttribute("locked", fmt.Sprintf("%t", locked)),
		sdk.NewAttribute("lock_sequence", fmt.Sprintf("%d", lockSequence)),
		sdk.NewAttribute("unlock_sequence", fmt.Sprintf("%d", unlockSequence)),
		sdk.NewAttribute("actor", actor),
	))
	return nil
}

func (k Keeper) requireTeamActor(ctx sdk.Context, actor, slug string, teamID uint64, ownerOnly bool) (*types.CurationTeam, error) {
	team, ok, err := k.GetCurationTeam(ctx, slug, teamID)
	if err != nil {
		return nil, err
	}
	if !ok || !k.teamLive(team) {
		return nil, fmt.Errorf("team not found")
	}
	core, found, err := k.loadProfile(ctx, actor)
	if err != nil {
		return nil, err
	}
	if !found || !types.CanCurate(core) {
		return nil, fmt.Errorf("must be an active subscriber or admin")
	}
	if ownerOnly {
		if team.Owner != actor {
			return nil, fmt.Errorf("only the team owner may perform this action")
		}
		return team, nil
	}
	has, err := k.storeHas(ctx, types.KeyCurationTeamMember(slug, teamID, actor))
	if err != nil {
		return nil, err
	}
	if !has {
		return nil, fmt.Errorf("not a curator on this team")
	}
	return team, nil
}

func (k Keeper) AddBlockedCommunity(ctx sdk.Context, owner, pattern string, maxCap uint32) error {
	if has, err := k.storeHas(ctx, types.KeyBlockCommunityIdx(owner, pattern)); err != nil {
		return err
	} else if has {
		return nil
	}
	next, _, err := k.getU64Key(ctx, types.KeyBlockCommunityNext(owner))
	if err != nil {
		return err
	}
	seq := next
	if err := k.setU64Key(ctx, types.KeyBlockCommunityNext(owner), next+1); err != nil {
		return err
	}
	if err := k.storeSet(ctx, types.KeyBlockCommunity(owner, seq, pattern), []byte{1}); err != nil {
		return err
	}
	if err := k.setU64Key(ctx, types.KeyBlockCommunityIdx(owner, pattern), seq); err != nil {
		return err
	}
	cnt, err := k.addCheckedU32(ctx, types.KeyBlockCommunityCount(owner), 1)
	if err != nil {
		return err
	}
	if maxCap > 0 && cnt > maxCap {
		return k.evictOldestBlockedCommunity(ctx, owner)
	}
	return nil
}

func (k Keeper) RemoveBlockedCommunity(ctx sdk.Context, owner, pattern string) error {
	seq, found, err := k.getU64Key(ctx, types.KeyBlockCommunityIdx(owner, pattern))
	if err != nil {
		return err
	}
	if !found {
		return nil
	}
	if err := k.storeDelete(ctx, types.KeyBlockCommunity(owner, seq, pattern)); err != nil {
		return err
	}
	if err := k.storeDelete(ctx, types.KeyBlockCommunityIdx(owner, pattern)); err != nil {
		return err
	}
	_, err = k.addCheckedU32(ctx, types.KeyBlockCommunityCount(owner), -1)
	return err
}

func (k Keeper) evictOldestBlockedCommunity(ctx sdk.Context, owner string) error {
	pfx := types.KeyBlockCommunityPrefix(owner)
	var oldestSeq uint64
	var oldestPattern string
	first := true
	if err := k.iterPrefixKeys(ctx, pfx, 0, func(key, _ []byte) error {
		rest := key[len(pfx):]
		seq := binaryU64(rest[:8])
		lp := rest[8:]
		n := int(lp[0])<<8 | int(lp[1])
		pat := string(lp[2 : 2+n])
		if first || seq < oldestSeq {
			oldestSeq = seq
			oldestPattern = pat
			first = false
		}
		return nil
	}); err != nil {
		return err
	}
	if first {
		return nil
	}
	return k.RemoveBlockedCommunity(ctx, owner, oldestPattern)
}
