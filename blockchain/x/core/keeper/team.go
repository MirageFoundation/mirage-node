package keeper

import (
	"fmt"
	"unicode/utf8"

	sdk "github.com/cosmos/cosmos-sdk/types"

	"mirage/x/core/types"
)

func (k Keeper) CreateAlternativeTeam(ctx sdk.Context, owner, slug, name, bio, policy string) (uint64, error) {
	params := k.GetParams(ctx)
	if err := types.ValidateCurationTeamName(name, params.MaxCurationTeamNameLength); err != nil {
		return 0, err
	}
	if uint64(utf8.RuneCountInString(bio)) > params.MaxCurationTeamBioLength {
		return 0, fmt.Errorf("bio exceeds max_curation_team_bio_length")
	}
	if uint64(utf8.RuneCountInString(policy)) > params.MaxCurationTeamPolicyLength {
		return 0, fmt.Errorf("policy exceeds max_curation_team_policy_length")
	}
	if _, found, err := k.GetCommunity(ctx, slug); err != nil {
		return 0, err
	} else if !found {
		return 0, fmt.Errorf("community not claimed: %s", slug)
	}
	core, found, err := k.loadProfile(ctx, owner)
	if err != nil {
		return 0, err
	}
	if !found || !core.EffectivePaid {
		return 0, fmt.Errorf("creating a curation team requires an active subscriber")
	}
	if _, joined, err := k.GetPreference(ctx, owner, slug); err != nil {
		return 0, err
	} else if !joined {
		return 0, fmt.Errorf("must join community before creating a team")
	}
	if _, occupied, err := k.getU64Key(ctx, types.KeyCurationTeamUser(owner, slug)); err != nil {
		return 0, err
	} else if occupied {
		return 0, fmt.Errorf("already a curator in this community")
	}
	hasMarker, err := k.storeHas(ctx, types.KeyCurationCreated(slug, owner))
	if err != nil {
		return 0, err
	}
	if hasMarker {
		return 0, fmt.Errorf("already created an alternative team in this community")
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
	order, _, err := k.getU64Key(ctx, []byte(types.PfxCommunitySeq))
	if err != nil {
		return 0, err
	}
	order++
	if err := k.setU64Key(ctx, []byte(types.PfxCommunitySeq), order); err != nil {
		return 0, err
	}
	if err := k.setU64Key(ctx, types.KeyCurationTeamNext(slug), next+1); err != nil {
		return 0, err
	}
	team := &types.CurationTeam{
		Community:       slug,
		TeamId:          next,
		Owner:           owner,
		Name:            name,
		Bio:             bio,
		Policy:          policy,
		CreatedHeight:   ctx.BlockHeight(),
		CreatedOrder:    order,
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
	if err := k.storeSet(ctx, types.KeyCurationCreated(slug, owner), []byte{1}); err != nil {
		return 0, err
	}
	if err := k.writeEligibleIndex(ctx, team); err != nil {
		return 0, err
	}
	if err := k.writeSupportIndex(ctx, team); err != nil {
		return 0, err
	}
	if err := k.recomputeCrown(ctx, slug); err != nil {
		return 0, err
	}
	ctx.EventManager().EmitEvent(sdk.NewEvent("curation_team_created",
		sdk.NewAttribute("community", slug),
		sdk.NewAttribute("team_id", fmt.Sprintf("%d", next)),
		sdk.NewAttribute("owner", owner),
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
	params := k.GetParams(ctx)
	core, found, err := k.loadProfile(ctx, target)
	if err != nil {
		return err
	}
	if !found || !core.EffectivePaid {
		return fmt.Errorf("invitee must be an active subscriber")
	}
	if _, joined, err := k.GetPreference(ctx, target, slug); err != nil {
		return err
	} else if !joined {
		return fmt.Errorf("invitee must join the community first")
	}
	if _, occupied, err := k.getU64Key(ctx, types.KeyCurationTeamUser(target, slug)); err != nil {
		return err
	} else if occupied {
		return fmt.Errorf("invitee already curates in this community")
	}
	members := 0
	if err := k.iterPrefixKeys(ctx, types.KeyCurationTeamMemberPrefix(slug, teamID), 0, func(_, _ []byte) error {
		members++
		return nil
	}); err != nil {
		return err
	}
	if uint64(members) >= params.MaxCuratorsPerTeam {
		return fmt.Errorf("team is full")
	}
	pendingTeam := 0
	if err := k.iterPrefixKeys(ctx, types.KeyCurationInvitePrefix(slug, teamID), 0, func(_, _ []byte) error {
		pendingTeam++
		return nil
	}); err != nil {
		return err
	}
	if uint64(pendingTeam) >= params.MaxPendingCuratorInvitesPerTeam {
		return fmt.Errorf("too many pending invites for this team")
	}
	pc, _, err := k.getU32Key(ctx, types.KeyCurationInviteCount(target))
	if err != nil {
		return err
	}
	if uint64(pc) >= params.MaxPendingCuratorInvitesPerUser {
		return fmt.Errorf("too many pending invites for this user")
	}
	if has, err := k.storeHas(ctx, types.KeyCurationInvite(slug, teamID, target)); err != nil {
		return err
	} else if has {
		return nil
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
	))
	return nil
}

func (k Keeper) ClearInvite(ctx sdk.Context, slug string, teamID uint64, target string) error {
	return k.clearInvite(ctx, slug, teamID, target)
}

func (k Keeper) RequireTeamOwner(ctx sdk.Context, actor, slug string, teamID uint64) (*types.CurationTeam, error) {
	return k.requireTeamActor(ctx, actor, slug, teamID, true)
}

func (k Keeper) RequireTeamCurator(ctx sdk.Context, actor, slug string, teamID uint64) (*types.CurationTeam, error) {
	return k.requireTeamActor(ctx, actor, slug, teamID, false)
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
	has, err := k.storeHas(ctx, types.KeyCurationInvite(slug, teamID, actor))
	if err != nil {
		return err
	}
	if !has {
		return fmt.Errorf("no pending invitation")
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
	if !found || !core.EffectivePaid {
		return fmt.Errorf("must be an active subscriber")
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
	order := team.NextMemberOrder
	team.NextMemberOrder++
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
	))
	return nil
}

func (k Keeper) RemoveCuratorFromTeam(ctx sdk.Context, slug string, teamID uint64, target string, emit string) error {
	if err := k.storeDelete(ctx, types.KeyCurationTeamMember(slug, teamID, target)); err != nil {
		return err
	}
	if err := k.storeDelete(ctx, types.KeyCurationTeamUser(target, slug)); err != nil {
		return err
	}
	if _, err := k.addCheckedU32(ctx, types.KeyCurationTeamUserCount(target), -1); err != nil {
		return err
	}
	if emit != "" {
		ctx.EventManager().EmitEvent(sdk.NewEvent(emit,
			sdk.NewAttribute("community", slug),
			sdk.NewAttribute("team_id", fmt.Sprintf("%d", teamID)),
			sdk.NewAttribute("address", target),
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
	if err := k.removeSupportIndex(ctx, team); err != nil {
		return err
	}
	if err := k.deleteEligibleIndex(ctx, team); err != nil {
		return err
	}
	if team.SupporterCount > 0 {
		if _, err := k.addCheckedU64(ctx, types.KeyCommunitySupport(slug), int64(team.SupporterCount)); err != nil {
			return err
		}
		team.SupporterCount = 0
	}
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
	team.DeletedHeight = ctx.BlockHeight()
	if err := k.SetCurationTeam(ctx, team); err != nil {
		return err
	}
	if err := k.recomputeCrown(ctx, slug); err != nil {
		return err
	}
	ctx.EventManager().EmitEvent(sdk.NewEvent("curation_team_deleted",
		sdk.NewAttribute("community", slug),
		sdk.NewAttribute("team_id", fmt.Sprintf("%d", teamID)),
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

func (k Keeper) SetCurationActionHiddenUser(ctx sdk.Context, slug string, teamID uint64, target, actor string, hidden bool) error {
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

func (k Keeper) SetCurationThreadLocked(ctx sdk.Context, slug string, teamID uint64, root, actor string, locked bool) error {
	h, err := types.HashBytes(root)
	if err != nil {
		return err
	}
	key := types.KeyThreadLock(slug, teamID, h)
	if locked {
		seq, _, err := k.getU64Key(ctx, []byte(types.PfxPostSeq))
		if err != nil {
			return err
		}
		if err := k.storeSet(ctx, key, putU64(seq)); err != nil {
			return err
		}
	} else {
		if err := k.storeDelete(ctx, key); err != nil {
			return err
		}
	}
	ctx.EventManager().EmitEvent(sdk.NewEvent("curation_thread_locked",
		sdk.NewAttribute("community", slug),
		sdk.NewAttribute("team_id", fmt.Sprintf("%d", teamID)),
		sdk.NewAttribute("target", root),
		sdk.NewAttribute("locked", fmt.Sprintf("%t", locked)),
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
	if !found || !core.EffectivePaid {
		return nil, fmt.Errorf("must be an active subscriber")
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
