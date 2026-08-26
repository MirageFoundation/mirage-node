package keeper

import (
	"fmt"
	"unicode/utf8"

	sdk "github.com/cosmos/cosmos-sdk/types"

	"mirage/x/core/types"
)

func (k Keeper) GetCommunity(ctx sdk.Context, slug string) (*types.Community, bool, error) {
	var c types.Community
	found, err := k.getProto(ctx, types.KeyCommunity(slug), &c)
	if err != nil || !found {
		return nil, found, err
	}
	return &c, true, nil
}

func (k Keeper) SetCommunity(ctx sdk.Context, c *types.Community) error {
	return k.setProto(ctx, types.KeyCommunity(c.Slug), c)
}

func (k Keeper) GetCurationTeam(ctx sdk.Context, slug string, teamID uint64) (*types.CurationTeam, bool, error) {
	var t types.CurationTeam
	found, err := k.getProto(ctx, types.KeyCurationTeam(slug, teamID), &t)
	if err != nil || !found {
		return nil, found, err
	}
	return &t, true, nil
}

func (k Keeper) SetCurationTeam(ctx sdk.Context, t *types.CurationTeam) error {
	return k.setProto(ctx, types.KeyCurationTeam(t.Community, t.TeamId), t)
}

func (k Keeper) GetPreference(ctx sdk.Context, owner, slug string) (*types.CommunityPreference, bool, error) {
	key := types.KeyJoin(owner, slug)
	has, err := k.storeHas(ctx, key)
	if err != nil || !has {
		return nil, has, err
	}
	bz, err := k.storeGet(ctx, key)
	if err != nil {
		return nil, false, err
	}
	var p types.CommunityPreference
	if len(bz) > 0 {
		if err := k.cdc.Unmarshal(bz, &p); err != nil {
			return nil, false, err
		}
	}
	return &p, true, nil
}

func (k Keeper) GetPostMetadata(ctx sdk.Context, hashHex string) (*types.PostMetadata, bool, error) {
	h, err := types.HashBytes(hashHex)
	if err != nil {
		return nil, false, err
	}
	var m types.PostMetadata
	found, err := k.getProto(ctx, types.KeyPostMeta(h), &m)
	if err != nil || !found {
		return nil, found, err
	}
	return &m, true, nil
}

func (k Keeper) SetPostMetadata(ctx sdk.Context, hashHex string, m *types.PostMetadata) error {
	h, err := types.HashBytes(hashHex)
	if err != nil {
		return err
	}
	return k.setProto(ctx, types.KeyPostMeta(h), m)
}

func (k Keeper) NextPostSequence(ctx sdk.Context) (uint64, error) {
	cur, _, err := k.getU64Key(ctx, []byte(types.PfxPostSeq))
	if err != nil {
		return 0, err
	}
	next, err := types.CheckedAddUint64(cur, 1)
	if err != nil {
		return 0, err
	}
	if err := k.setU64Key(ctx, []byte(types.PfxPostSeq), next); err != nil {
		return 0, err
	}
	return next, nil
}

func (k Keeper) GetDefaultCount(ctx sdk.Context, slug string) (uint64, error) {
	v, _, err := k.getU64Key(ctx, types.KeyCommunitySupport(slug))
	return v, err
}

func (k Keeper) teamLive(t *types.CurationTeam) bool {
	return t != nil && t.DeletedHeight == 0
}

func (k Keeper) teamEligible(ctx sdk.Context, t *types.CurationTeam) (bool, error) {
	if !k.teamLive(t) {
		return false, nil
	}
	owner, found, err := k.loadProfile(ctx, t.Owner)
	if err != nil {
		return false, err
	}
	return found && owner.EffectivePaid, nil
}

func (k Keeper) ListJoinedCommunities(ctx sdk.Context, owner string) ([]string, error) {
	var slugs []string
	pfx := types.KeyJoinPrefix(owner)
	err := k.iterPrefixKeys(ctx, pfx, 0, func(key, _ []byte) error {
		if len(key) < len(pfx)+2 {
			return fmt.Errorf("join key too short for %s", owner)
		}
		rest := key[len(pfx):]
		n := int(rest[0])<<8 | int(rest[1])
		if len(rest) < 2+n {
			return fmt.Errorf("join key truncated for %s", owner)
		}
		slugs = append(slugs, string(rest[2:2+n]))
		return nil
	})
	return slugs, err
}

func (k Keeper) CountJoinedCommunities(ctx sdk.Context, owner string) (uint32, error) {
	v, _, err := k.getU32Key(ctx, types.KeyJoinCount(owner))
	return v, err
}

func (k Keeper) ListBlockedCommunities(ctx sdk.Context, owner string) ([]string, error) {
	type item struct {
		seq     uint64
		pattern string
	}
	var items []item
	pfx := types.KeyBlockCommunityPrefix(owner)
	err := k.iterPrefixKeys(ctx, pfx, 0, func(key, _ []byte) error {
		if len(key) < len(pfx)+8+2 {
			return fmt.Errorf("blocked-community key too short for %s", owner)
		}
		rest := key[len(pfx):]
		seq := uint64(rest[0])<<56 | uint64(rest[1])<<48 | uint64(rest[2])<<40 | uint64(rest[3])<<32 |
			uint64(rest[4])<<24 | uint64(rest[5])<<16 | uint64(rest[6])<<8 | uint64(rest[7])
		lp := rest[8:]
		n := int(lp[0])<<8 | int(lp[1])
		if len(lp) < 2+n {
			return fmt.Errorf("blocked-community pattern truncated for %s", owner)
		}
		items = append(items, item{seq: seq, pattern: string(lp[2 : 2+n])})
		return nil
	})
	if err != nil {
		return nil, err
	}
	out := make([]string, len(items))
	for i, it := range items {
		out[i] = it.pattern
	}
	return out, nil
}

func (k Keeper) storedContribution(pref *types.CommunityPreference) (mode types.CurationPreferenceMode, teamID uint64) {
	if pref == nil {
		return types.CurationPreferenceMode_CURATION_PREFERENCE_MODE_LIVE_DEFAULT, 0
	}
	return pref.Mode, pref.PinnedTeamId
}

func (k Keeper) ResolveEffectivePreference(ctx sdk.Context, owner, slug string) (joined bool, stored, effective types.CurationPreferenceMode, storedTeam, effectiveTeam uint64, err error) {
	pref, found, err := k.GetPreference(ctx, owner, slug)
	if err != nil {
		return false, 0, 0, 0, 0, err
	}
	if !found {
		return false, 0, 0, 0, 0, nil
	}
	stored = pref.Mode
	storedTeam = pref.PinnedTeamId
	comm, claimed, err := k.GetCommunity(ctx, slug)
	if err != nil {
		return true, stored, stored, storedTeam, 0, err
	}
	defaultTeam := uint64(0)
	if claimed {
		defaultTeam = comm.CurrentDefaultTeamId
	}
	switch pref.Mode {
	case types.CurationPreferenceMode_CURATION_PREFERENCE_MODE_RAW:
		return true, stored, stored, storedTeam, 0, nil
	case types.CurationPreferenceMode_CURATION_PREFERENCE_MODE_PINNED:
		team, ok, err := k.GetCurationTeam(ctx, slug, pref.PinnedTeamId)
		if err != nil {
			return true, stored, stored, storedTeam, 0, err
		}
		eligible := false
		if ok {
			eligible, err = k.teamEligible(ctx, team)
			if err != nil {
				return true, stored, stored, storedTeam, 0, err
			}
		}
		if eligible {
			return true, stored, stored, storedTeam, pref.PinnedTeamId, nil
		}
		fallthrough
	default:
		if defaultTeam == 0 {
			return true, stored, types.CurationPreferenceMode_CURATION_PREFERENCE_MODE_LIVE_DEFAULT, storedTeam, 0, nil
		}
		return true, stored, types.CurationPreferenceMode_CURATION_PREFERENCE_MODE_LIVE_DEFAULT, storedTeam, defaultTeam, nil
	}
}

func (k Keeper) JoinCommunity(ctx sdk.Context, owner, slug string, paid bool, cap uint32, requireClaimed bool) error {
	if _, found, err := k.GetPreference(ctx, owner, slug); err != nil {
		return err
	} else if found {
		return nil
	}
	comm, claimed, err := k.GetCommunity(ctx, slug)
	if err != nil {
		return err
	}
	if requireClaimed && !claimed {
		return fmt.Errorf("cannot join unclaimed community %s", slug)
	}
	_ = comm
	cnt, err := k.CountJoinedCommunities(ctx, owner)
	if err != nil {
		return err
	}
	if cap > 0 && cnt >= cap {
		return fmt.Errorf("joined communities cap reached: %d", cap)
	}
	pref := &types.CommunityPreference{Mode: types.CurationPreferenceMode_CURATION_PREFERENCE_MODE_LIVE_DEFAULT}
	if err := k.setProto(ctx, types.KeyJoin(owner, slug), pref); err != nil {
		return err
	}
	if err := k.storeSet(ctx, types.KeyJoinRev(slug, owner), []byte{1}); err != nil {
		return err
	}
	if _, err := k.addCheckedU32(ctx, types.KeyJoinCount(owner), 1); err != nil {
		return err
	}
	if paid {
		if _, err := k.addCheckedU64(ctx, types.KeyCommunitySupport(slug), 1); err != nil {
			return err
		}
		if err := k.recomputeCrown(ctx, slug); err != nil {
			return err
		}
	}
	ctx.EventManager().EmitEvent(sdk.NewEvent("community_joined",
		sdk.NewAttribute("address", owner),
		sdk.NewAttribute("community", slug),
	))
	return nil
}

func (k Keeper) LeaveCommunity(ctx sdk.Context, owner, slug string, paid bool) error {
	pref, found, err := k.GetPreference(ctx, owner, slug)
	if err != nil {
		return err
	}
	if !found {
		return fmt.Errorf("not joined: %s", slug)
	}
	if teamID, ok, err := k.getU64Key(ctx, types.KeyCurationTeamUser(owner, slug)); err != nil {
		return err
	} else if ok && teamID > 0 {
		return fmt.Errorf("cannot leave community %s while curating a team", slug)
	}
	if paid {
		if err := k.removeSupportContribution(ctx, slug, pref, true); err != nil {
			return err
		}
	}
	if err := k.storeDelete(ctx, types.KeyJoin(owner, slug)); err != nil {
		return err
	}
	has, err := k.storeHas(ctx, types.KeyJoinRev(slug, owner))
	if err != nil {
		return err
	}
	if !has {
		return fmt.Errorf("CONSENSUS_FATAL:JOIN_REVERSE_MISSING owner=%s community=%s", owner, slug)
	}
	if err := k.storeDelete(ctx, types.KeyJoinRev(slug, owner)); err != nil {
		return err
	}
	if _, err := k.addCheckedU32(ctx, types.KeyJoinCount(owner), -1); err != nil {
		return err
	}
	if err := k.recomputeCrown(ctx, slug); err != nil {
		return err
	}
	ctx.EventManager().EmitEvent(sdk.NewEvent("community_left",
		sdk.NewAttribute("address", owner),
		sdk.NewAttribute("community", slug),
	))
	return nil
}

func (k Keeper) SetCurationPreference(ctx sdk.Context, owner, slug string, mode types.CurationPreferenceMode, teamID uint64, paid bool) error {
	old, found, err := k.GetPreference(ctx, owner, slug)
	if err != nil {
		return err
	}
	if !found {
		return fmt.Errorf("not joined: %s", slug)
	}
	if mode == types.CurationPreferenceMode_CURATION_PREFERENCE_MODE_PINNED {
		team, ok, err := k.GetCurationTeam(ctx, slug, teamID)
		if err != nil {
			return err
		}
		if !ok || !k.teamLive(team) {
			return fmt.Errorf("cannot pin deleted or unknown team")
		}
	} else {
		teamID = 0
	}
	if paid {
		if err := k.removeSupportContribution(ctx, slug, old, true); err != nil {
			return err
		}
	}
	pref := &types.CommunityPreference{Mode: mode, PinnedTeamId: teamID}
	if err := k.setProto(ctx, types.KeyJoin(owner, slug), pref); err != nil {
		return err
	}
	if paid {
		if err := k.addSupportContribution(ctx, slug, pref); err != nil {
			return err
		}
	}
	if err := k.recomputeCrown(ctx, slug); err != nil {
		return err
	}
	ctx.EventManager().EmitEvent(sdk.NewEvent("community_preference_changed",
		sdk.NewAttribute("address", owner),
		sdk.NewAttribute("community", slug),
		sdk.NewAttribute("mode", fmt.Sprintf("%d", mode)),
		sdk.NewAttribute("team_id", fmt.Sprintf("%d", teamID)),
	))
	return nil
}

func (k Keeper) removeSupportContribution(ctx sdk.Context, slug string, pref *types.CommunityPreference, stalePinIsFloating bool) error {
	if pref == nil {
		return nil
	}
	switch pref.Mode {
	case types.CurationPreferenceMode_CURATION_PREFERENCE_MODE_RAW:
		return nil
	case types.CurationPreferenceMode_CURATION_PREFERENCE_MODE_PINNED:
		team, ok, err := k.GetCurationTeam(ctx, slug, pref.PinnedTeamId)
		if err != nil {
			return err
		}
		if ok && k.teamLive(team) {
			return k.adjustTeamSupport(ctx, team, -1)
		}
		if stalePinIsFloating {
			_, err := k.addCheckedU64(ctx, types.KeyCommunitySupport(slug), -1)
			return err
		}
		return nil
	default:
		_, err := k.addCheckedU64(ctx, types.KeyCommunitySupport(slug), -1)
		return err
	}
}

func (k Keeper) addSupportContribution(ctx sdk.Context, slug string, pref *types.CommunityPreference) error {
	if pref == nil {
		return nil
	}
	switch pref.Mode {
	case types.CurationPreferenceMode_CURATION_PREFERENCE_MODE_RAW:
		return nil
	case types.CurationPreferenceMode_CURATION_PREFERENCE_MODE_PINNED:
		team, ok, err := k.GetCurationTeam(ctx, slug, pref.PinnedTeamId)
		if err != nil {
			return err
		}
		if !ok || !k.teamLive(team) {
			_, err := k.addCheckedU64(ctx, types.KeyCommunitySupport(slug), 1)
			return err
		}
		return k.adjustTeamSupport(ctx, team, 1)
	default:
		_, err := k.addCheckedU64(ctx, types.KeyCommunitySupport(slug), 1)
		return err
	}
}

func (k Keeper) adjustTeamSupport(ctx sdk.Context, team *types.CurationTeam, delta int64) error {
	if err := k.removeSupportIndex(ctx, team); err != nil {
		return err
	}
	if delta >= 0 {
		sum, err := types.CheckedAddUint64(team.SupporterCount, uint64(delta))
		if err != nil {
			return err
		}
		team.SupporterCount = sum
	} else {
		sub := uint64(-delta)
		if team.SupporterCount < sub {
			return fmt.Errorf("team supporter underflow community=%s team=%d", team.Community, team.TeamId)
		}
		team.SupporterCount -= sub
	}
	if err := k.SetCurationTeam(ctx, team); err != nil {
		return err
	}
	return k.writeSupportIndex(ctx, team)
}

func (k Keeper) removeSupportIndex(ctx sdk.Context, team *types.CurationTeam) error {
	if !k.teamLive(team) {
		return nil
	}
	key := types.KeyCurationSupportOrd(team.Community, types.InvertedSupport(team.SupporterCount), team.CreatedOrder, team.TeamId)
	has, err := k.storeHas(ctx, key)
	if err != nil {
		return err
	}
	if has {
		return k.storeDelete(ctx, key)
	}
	return nil
}

func (k Keeper) writeSupportIndex(ctx sdk.Context, team *types.CurationTeam) error {
	if !k.teamLive(team) {
		return nil
	}
	eligible, err := k.teamEligible(ctx, team)
	if err != nil {
		return err
	}
	if !eligible {
		return nil
	}
	key := types.KeyCurationSupportOrd(team.Community, types.InvertedSupport(team.SupporterCount), team.CreatedOrder, team.TeamId)
	return k.storeSet(ctx, key, []byte{1})
}

func (k Keeper) writeEligibleIndex(ctx sdk.Context, team *types.CurationTeam) error {
	priority := uint64(1)
	if team.IsOriginal {
		priority = 0
	}
	return k.storeSet(ctx, types.KeyCurationEligible(team.Community, priority, team.CreatedOrder, team.TeamId), []byte{1})
}

func (k Keeper) deleteEligibleIndex(ctx sdk.Context, team *types.CurationTeam) error {
	priority := uint64(1)
	if team.IsOriginal {
		priority = 0
	}
	return k.storeDelete(ctx, types.KeyCurationEligible(team.Community, priority, team.CreatedOrder, team.TeamId))
}

func (k Keeper) recomputeCrown(ctx sdk.Context, slug string) error {
	comm, found, err := k.GetCommunity(ctx, slug)
	if err != nil || !found {
		return err
	}
	floating, err := k.GetDefaultCount(ctx, slug)
	if err != nil {
		return err
	}
	incumbentID := comm.CurrentDefaultTeamId
	var incumbent *types.CurationTeam
	incumbentEligible := false
	if incumbentID != 0 {
		incumbent, _, err = k.GetCurationTeam(ctx, slug, incumbentID)
		if err != nil {
			return err
		}
		incumbentEligible, err = k.teamEligible(ctx, incumbent)
		if err != nil {
			return err
		}
	}
	challenger, err := k.highestSupportChallenger(ctx, slug, incumbentID)
	if err != nil {
		return err
	}
	newDefault := uint64(0)
	if incumbentEligible {
		score := floating + incumbent.SupporterCount
		if challenger != nil && challenger.SupporterCount > score {
			newDefault = challenger.TeamId
		} else {
			newDefault = incumbent.TeamId
		}
	} else {
		fallback, err := k.fallbackEligibleTeam(ctx, slug)
		if err != nil {
			return err
		}
		if fallback != nil {
			newDefault = fallback.TeamId
			ch2, err := k.highestSupportChallenger(ctx, slug, fallback.TeamId)
			if err != nil {
				return err
			}
			if ch2 != nil && ch2.SupporterCount > fallback.SupporterCount+floating {
				newDefault = ch2.TeamId
			}
		}
	}
	if newDefault == comm.CurrentDefaultTeamId {
		return nil
	}
	comm.CurrentDefaultTeamId = newDefault
	if err := k.SetCommunity(ctx, comm); err != nil {
		return err
	}
	ctx.EventManager().EmitEvent(sdk.NewEvent("community_default_changed",
		sdk.NewAttribute("community", slug),
		sdk.NewAttribute("team_id", fmt.Sprintf("%d", newDefault)),
	))
	return nil
}

func (k Keeper) highestSupportChallenger(ctx sdk.Context, slug string, skipID uint64) (*types.CurationTeam, error) {
	pfx := types.KeyCurationSupportOrdPrefix(slug)
	var found *types.CurationTeam
	err := k.iterPrefixKeys(ctx, pfx, 32, func(key, _ []byte) error {
		if len(key) < 8 {
			return fmt.Errorf("stale support index for %s", slug)
		}
		teamID := binaryU64(key[len(key)-8:])
		if teamID == skipID {
			return nil
		}
		team, ok, err := k.GetCurationTeam(ctx, slug, teamID)
		if err != nil {
			return err
		}
		if !ok {
			return fmt.Errorf("CONSENSUS_FATAL:STALE_SUPPORT_INDEX community=%s team=%d", slug, teamID)
		}
		elig, err := k.teamEligible(ctx, team)
		if err != nil {
			return err
		}
		if !elig {
			return fmt.Errorf("CONSENSUS_FATAL:STALE_SUPPORT_INDEX community=%s team=%d", slug, teamID)
		}
		found = team
		return fmt.Errorf("stop")
	})
	if err != nil && err.Error() != "stop" {
		return nil, err
	}
	return found, nil
}

func (k Keeper) fallbackEligibleTeam(ctx sdk.Context, slug string) (*types.CurationTeam, error) {
	comm, ok, err := k.GetCommunity(ctx, slug)
	if err != nil || !ok {
		return nil, err
	}
	if comm.OriginalTeamId != 0 {
		orig, found, err := k.GetCurationTeam(ctx, slug, comm.OriginalTeamId)
		if err != nil {
			return nil, err
		}
		if found {
			elig, err := k.teamEligible(ctx, orig)
			if err != nil {
				return nil, err
			}
			if elig {
				return orig, nil
			}
		}
	}
	var best *types.CurationTeam
	err = k.iterPrefixKeys(ctx, types.KeyCurationTeamPrefix(slug), 0, func(_, value []byte) error {
		var t types.CurationTeam
		if err := k.cdc.Unmarshal(value, &t); err != nil {
			return err
		}
		elig, err := k.teamEligible(ctx, &t)
		if err != nil || !elig {
			return err
		}
		if best == nil || t.CreatedOrder < best.CreatedOrder || (t.CreatedOrder == best.CreatedOrder && t.TeamId < best.TeamId) {
			cp := t
			best = &cp
		}
		return nil
	})
	return best, err
}

func binaryU64(b []byte) uint64 {
	return uint64(b[0])<<56 | uint64(b[1])<<48 | uint64(b[2])<<40 | uint64(b[3])<<32 |
		uint64(b[4])<<24 | uint64(b[5])<<16 | uint64(b[6])<<8 | uint64(b[7])
}

func (k Keeper) CreateCommunity(ctx sdk.Context, founder, slug, title, desc, teamName, bio, policy string) error {
	params := k.GetParams(ctx)
	if err := types.ValidateCommunitySlug(slug, uint64(params.MinCommunitySize), uint64(params.MaxCommunitySize)); err != nil {
		return err
	}
	if uint64(utf8.RuneCountInString(title)) > params.MaxCommunityTitleLength {
		return fmt.Errorf("title exceeds max_community_title_length")
	}
	if uint64(utf8.RuneCountInString(desc)) > params.MaxCommunityDescriptionLength {
		return fmt.Errorf("description exceeds max_community_description_length")
	}
	if err := types.ValidateCurationTeamName(teamName, params.MaxCurationTeamNameLength); err != nil {
		return err
	}
	if uint64(utf8.RuneCountInString(bio)) > params.MaxCurationTeamBioLength {
		return fmt.Errorf("bio exceeds max_curation_team_bio_length")
	}
	if uint64(utf8.RuneCountInString(policy)) > params.MaxCurationTeamPolicyLength {
		return fmt.Errorf("policy exceeds max_curation_team_policy_length")
	}
	if _, found, err := k.GetCommunity(ctx, slug); err != nil {
		return err
	} else if found {
		return fmt.Errorf("community already claimed: %s", slug)
	}
	core, found, err := k.loadProfile(ctx, founder)
	if err != nil {
		return err
	}
	if !found || !core.EffectivePaid {
		return fmt.Errorf("creating a community requires an active subscriber")
	}
	tier := params.GetTierConfig(int(core.Level))
	if tier == nil {
		return fmt.Errorf("tier config not found for level %d", core.Level)
	}
	if _, found, err := k.GetPreference(ctx, founder, slug); err != nil {
		return err
	} else if !found {
		if err := k.JoinCommunity(ctx, founder, slug, true, uint32(tier.MaxJoinedCommunities), false); err != nil {
			return err
		}
	}
	nextTeam, _, err := k.getU64Key(ctx, types.KeyCurationTeamNext(slug))
	if err != nil {
		return err
	}
	if nextTeam == 0 {
		nextTeam = 1
	}
	teamID := nextTeam
	if err := k.setU64Key(ctx, types.KeyCurationTeamNext(slug), teamID+1); err != nil {
		return err
	}
	order, _, err := k.getU64Key(ctx, []byte(types.PfxCommunitySeq))
	if err != nil {
		return err
	}
	order++
	if err := k.setU64Key(ctx, []byte(types.PfxCommunitySeq), order); err != nil {
		return err
	}
	team := &types.CurationTeam{
		Community:       slug,
		TeamId:          teamID,
		Owner:           founder,
		Name:            teamName,
		Bio:             bio,
		Policy:          policy,
		IsOriginal:      true,
		CreatedHeight:   ctx.BlockHeight(),
		CreatedOrder:    order,
		NextMemberOrder: 2,
	}
	if err := k.SetCurationTeam(ctx, team); err != nil {
		return err
	}
	member := &types.CurationTeamMember{Address: founder, AcceptedOrder: 1}
	if err := k.setProto(ctx, types.KeyCurationTeamMember(slug, teamID, founder), member); err != nil {
		return err
	}
	if err := k.setU64Key(ctx, types.KeyCurationTeamUser(founder, slug), teamID); err != nil {
		return err
	}
	if _, err := k.addCheckedU32(ctx, types.KeyCurationTeamUserCount(founder), 1); err != nil {
		return err
	}
	if err := k.storeSet(ctx, types.KeyCurationTeamName(slug, types.NormalizeTeamNameKey(teamName)), putU64(teamID)); err != nil {
		return err
	}
	if err := k.writeEligibleIndex(ctx, team); err != nil {
		return err
	}
	if err := k.writeSupportIndex(ctx, team); err != nil {
		return err
	}
	comm := &types.Community{
		Slug:                 slug,
		OriginalFounder:      founder,
		CurrentFounder:       founder,
		Title:                title,
		Description:          desc,
		OriginalTeamId:       teamID,
		CurrentDefaultTeamId: teamID,
		CreatedHeight:        ctx.BlockHeight(),
		CreatedOrder:         order,
	}
	if err := k.SetCommunity(ctx, comm); err != nil {
		return err
	}
	if err := k.storeSet(ctx, types.KeyCommunityFounder(founder, slug), []byte{1}); err != nil {
		return err
	}
	if err := k.recomputeCrown(ctx, slug); err != nil {
		return err
	}
	ctx.EventManager().EmitEvent(sdk.NewEvent("community_created",
		sdk.NewAttribute("community", slug),
		sdk.NewAttribute("founder", founder),
		sdk.NewAttribute("team_id", fmt.Sprintf("%d", teamID)),
	))
	ctx.EventManager().EmitEvent(sdk.NewEvent("curation_team_created",
		sdk.NewAttribute("community", slug),
		sdk.NewAttribute("team_id", fmt.Sprintf("%d", teamID)),
		sdk.NewAttribute("owner", founder),
	))
	return nil
}

func (k Keeper) ConsumeSubscriberQuota(ctx sdk.Context, owner string) error {
	if ctx.ExecMode() != sdk.ExecModeFinalize {
		core, found, err := k.loadProfile(ctx, owner)
		if err != nil {
			return err
		}
		if !found || !core.EffectivePaid {
			return nil
		}
		params := k.GetParams(ctx)
		q, _, err := k.getQuota(ctx, owner)
		if err != nil {
			return err
		}
		epoch := types.UTCEpoch(ctx.BlockTime().Unix())
		used := q.Count
		if q.UtcEpoch != epoch {
			used = 0
		}
		if used >= params.SubscriberDailyRelayLimit {
			return fmt.Errorf("subscriber_daily_limit_reached epoch=%d limit=%d used=%d remaining=0 reset=%d",
				epoch, params.SubscriberDailyRelayLimit, used, (epoch+1)*86400)
		}
		return nil
	}
	core, found, err := k.loadProfile(ctx, owner)
	if err != nil {
		return err
	}
	if !found || !core.EffectivePaid {
		return nil
	}
	params := k.GetParams(ctx)
	epoch := types.UTCEpoch(ctx.BlockTime().Unix())
	q, _, err := k.getQuota(ctx, owner)
	if err != nil {
		return err
	}
	if q.UtcEpoch != epoch {
		q.UtcEpoch = epoch
		q.Count = 0
	}
	if q.Count >= params.SubscriberDailyRelayLimit {
		return fmt.Errorf("subscriber_daily_limit_reached epoch=%d limit=%d used=%d remaining=0 reset=%d",
			epoch, params.SubscriberDailyRelayLimit, q.Count, (epoch+1)*86400)
	}
	q.Count++
	return k.setProto(ctx, types.KeySubscriberQuota(owner), &q)
}

func (k Keeper) getQuota(ctx sdk.Context, owner string) (types.SubscriberQuota, bool, error) {
	var q types.SubscriberQuota
	found, err := k.getProto(ctx, types.KeySubscriberQuota(owner), &q)
	return q, found, err
}

func (k Keeper) GetSubscriberQuota(ctx sdk.Context, owner string) (types.SubscriberQuota, error) {
	q, _, err := k.getQuota(ctx, owner)
	return q, err
}

func (k Keeper) IsEffectivePaid(ctx sdk.Context, owner string) (bool, error) {
	core, found, err := k.loadProfile(ctx, owner)
	if err != nil {
		return false, err
	}
	return found && core.EffectivePaid, nil
}
