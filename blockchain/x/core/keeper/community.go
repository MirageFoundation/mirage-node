package keeper

import (
	"fmt"

	storetypes "github.com/cosmos/cosmos-sdk/store/v2/types"
	sdk "github.com/cosmos/cosmos-sdk/types"

	"mirage/x/core/types"
)

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

func (k Keeper) GetCurationTeamsPaginated(ctx sdk.Context, prefix, pageKey []byte, limit uint64, includeDeleted bool) (teams []*types.CurationTeam, nextKey []byte, err error) {
	if limit == 0 || limit > 100 {
		limit = 100
	}
	start := prefix
	if len(pageKey) > 0 {
		start = append(append([]byte(nil), prefix...), pageKey...)
	}
	it, err := k.storeService.OpenKVStore(ctx).Iterator(start, storetypes.PrefixEndBytes(prefix))
	if err != nil {
		return nil, nil, err
	}
	defer func() {
		if closeErr := it.Close(); err == nil && closeErr != nil {
			err = closeErr
		}
	}()
	for ; it.Valid() && uint64(len(teams)) < limit; it.Next() {
		var team types.CurationTeam
		if err := k.cdc.Unmarshal(it.Value(), &team); err != nil {
			return nil, nil, err
		}
		if !includeDeleted && !k.teamLive(&team) {
			continue
		}
		teamCopy := team
		teams = append(teams, &teamCopy)
	}
	if err := it.Error(); err != nil {
		return nil, nil, err
	}
	if it.Valid() {
		fullKey := it.Key()
		nextKey = append([]byte(nil), fullKey[len(prefix):]...)
	}
	return teams, nextKey, nil
}

func (k Keeper) GetCurationTeamMembersPaginated(ctx sdk.Context, prefix, pageKey []byte, limit uint64) (members []*types.CurationTeamMember, nextKey []byte, err error) {
	max := k.GetParams(ctx).MaxCuratorsPerTeam
	if limit == 0 || limit > max {
		limit = max
	}
	start := prefix
	if len(pageKey) > 0 {
		start = append(append([]byte(nil), prefix...), pageKey...)
	}
	it, err := k.storeService.OpenKVStore(ctx).Iterator(start, storetypes.PrefixEndBytes(prefix))
	if err != nil {
		return nil, nil, err
	}
	defer func() {
		if closeErr := it.Close(); err == nil && closeErr != nil {
			err = closeErr
		}
	}()
	for ; it.Valid() && uint64(len(members)) < limit; it.Next() {
		var member types.CurationTeamMember
		if err := k.cdc.Unmarshal(it.Value(), &member); err != nil {
			return nil, nil, err
		}
		memberCopy := member
		members = append(members, &memberCopy)
	}
	if err := it.Error(); err != nil {
		return nil, nil, err
	}
	if it.Valid() {
		fullKey := it.Key()
		nextKey = append([]byte(nil), fullKey[len(prefix):]...)
	}
	return members, nextKey, nil
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

func (k Keeper) teamLive(t *types.CurationTeam) bool {
	return t != nil && t.DeletedHeight == 0
}

// ListJoinedCommunities returns every stored membership, deliberately without
// consulting the tier cap. A stored list longer than the current cap is normal,
// not corruption: the cap applies when JoinCommunity admits an entry, and a
// subscriber who joined 100 communities keeps all of them when the subscription
// lapses and the cap drops to the free tier's 25. Governance lowering a cap has
// the same effect on every existing list at once. Rejecting the read instead
// made those profiles unreadable, which crash-looped the indexer on the first
// lapsed subscriber it paginated past.
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
	switch pref.Mode {
	case types.CurationPreferenceMode_CURATION_PREFERENCE_MODE_RAW:
		return true, stored, types.CurationPreferenceMode_CURATION_PREFERENCE_MODE_RAW, storedTeam, 0, nil
	case types.CurationPreferenceMode_CURATION_PREFERENCE_MODE_PINNED:
		team, ok, err := k.GetCurationTeam(ctx, slug, pref.PinnedTeamId)
		if err != nil {
			return true, stored, stored, storedTeam, 0, err
		}
		if ok && k.teamLive(team) {
			return true, stored, types.CurationPreferenceMode_CURATION_PREFERENCE_MODE_PINNED, storedTeam, pref.PinnedTeamId, nil
		}
		return true, stored, types.CurationPreferenceMode_CURATION_PREFERENCE_MODE_LIVE_DEFAULT, storedTeam, 0, nil
	case types.CurationPreferenceMode_CURATION_PREFERENCE_MODE_LIVE_DEFAULT:
		return true, stored, types.CurationPreferenceMode_CURATION_PREFERENCE_MODE_LIVE_DEFAULT, storedTeam, 0, nil
	default:
		return true, stored, 0, storedTeam, 0, fmt.Errorf("invalid stored curation preference mode %d", pref.Mode)
	}
}

func (k Keeper) JoinCommunity(ctx sdk.Context, owner, slug string, cap uint32) error {
	params := k.GetParams(ctx)
	if err := types.ValidateCommunitySlug(slug, params.MinCommunitySize, params.MaxCommunitySize); err != nil {
		return err
	}
	if _, found, err := k.GetPreference(ctx, owner, slug); err != nil {
		return err
	} else if found {
		return nil
	}
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
		if err := k.removeCurationMembership(ctx, owner, slug, teamID, "curator_left"); err != nil {
			return err
		}
	}
	if paid {
		if err := k.removeSubscriberContribution(ctx, slug, pref); err != nil {
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
	switch mode {
	case types.CurationPreferenceMode_CURATION_PREFERENCE_MODE_PINNED:
		if teamID == 0 {
			return fmt.Errorf("PINNED preference requires a team_id")
		}
		team, ok, err := k.GetCurationTeam(ctx, slug, teamID)
		if err != nil {
			return err
		}
		if !ok || !k.teamLive(team) {
			return fmt.Errorf("cannot pin deleted or unknown team")
		}
	case types.CurationPreferenceMode_CURATION_PREFERENCE_MODE_LIVE_DEFAULT,
		types.CurationPreferenceMode_CURATION_PREFERENCE_MODE_RAW:
		if teamID != 0 {
			return fmt.Errorf("curation preference mode %d requires team_id 0", mode)
		}
	default:
		return fmt.Errorf("invalid curation preference mode %d", mode)
	}
	if old.Mode == mode && old.PinnedTeamId == teamID {
		return nil
	}
	if paid {
		if err := k.removeSubscriberContribution(ctx, slug, old); err != nil {
			return err
		}
	}
	pref := &types.CommunityPreference{Mode: mode, PinnedTeamId: teamID}
	if paid {
		if err := k.addSubscriberContribution(ctx, slug, pref); err != nil {
			return err
		}
	}
	if err := k.setProto(ctx, types.KeyJoin(owner, slug), pref); err != nil {
		return err
	}
	ctx.EventManager().EmitEvent(sdk.NewEvent("community_preference_changed",
		sdk.NewAttribute("owner", owner),
		sdk.NewAttribute("community", slug),
		sdk.NewAttribute("old_mode", fmt.Sprintf("%d", old.Mode)),
		sdk.NewAttribute("old_team_id", fmt.Sprintf("%d", old.PinnedTeamId)),
		sdk.NewAttribute("new_mode", fmt.Sprintf("%d", mode)),
		sdk.NewAttribute("new_team_id", fmt.Sprintf("%d", teamID)),
	))
	return nil
}

func (k Keeper) removeSubscriberContribution(ctx sdk.Context, slug string, pref *types.CommunityPreference) error {
	if pref == nil || pref.Mode != types.CurationPreferenceMode_CURATION_PREFERENCE_MODE_PINNED {
		return nil
	}
	team, ok, err := k.GetCurationTeam(ctx, slug, pref.PinnedTeamId)
	if err != nil {
		return err
	}
	if !ok || !k.teamLive(team) {
		return nil
	}
	return k.adjustTeamSubscriberCount(ctx, slug, pref.PinnedTeamId, -1)
}

func (k Keeper) addSubscriberContribution(ctx sdk.Context, slug string, pref *types.CommunityPreference) error {
	if pref == nil || pref.Mode != types.CurationPreferenceMode_CURATION_PREFERENCE_MODE_PINNED {
		return nil
	}
	team, ok, err := k.GetCurationTeam(ctx, slug, pref.PinnedTeamId)
	if err != nil {
		return err
	}
	if !ok || !k.teamLive(team) {
		return nil
	}
	return k.adjustTeamSubscriberCount(ctx, slug, pref.PinnedTeamId, 1)
}

func (k Keeper) adjustTeamSubscriberCount(ctx sdk.Context, slug string, teamID uint64, delta int64) error {
	team, found, err := k.GetCurationTeam(ctx, slug, teamID)
	if err != nil {
		return err
	}
	if !found || !k.teamLive(team) {
		return fmt.Errorf("cannot adjust subscriber count for deleted or unknown team")
	}
	if delta >= 0 {
		sum, err := types.CheckedAddUint64(team.SubscriberCount, uint64(delta))
		if err != nil {
			return err
		}
		team.SubscriberCount = sum
	} else {
		sub := uint64(-delta)
		if team.SubscriberCount < sub {
			return fmt.Errorf("team subscriber underflow community=%s team=%d", team.Community, team.TeamId)
		}
		team.SubscriberCount -= sub
	}
	if err := k.SetCurationTeam(ctx, team); err != nil {
		return err
	}
	ctx.EventManager().EmitEvent(sdk.NewEvent("curation_team_subscriber_count_changed",
		sdk.NewAttribute("community", slug),
		sdk.NewAttribute("team_id", fmt.Sprintf("%d", teamID)),
		sdk.NewAttribute("subscriber_count", fmt.Sprintf("%d", team.SubscriberCount)),
	))
	return nil
}

func binaryU64(b []byte) uint64 {
	return uint64(b[0])<<56 | uint64(b[1])<<48 | uint64(b[2])<<40 | uint64(b[3])<<32 |
		uint64(b[4])<<24 | uint64(b[5])<<16 | uint64(b[6])<<8 | uint64(b[7])
}

func (k Keeper) ConsumeSubscriberQuota(ctx sdk.Context, owner string) error {
	if ctx.ExecMode() != sdk.ExecModeFinalize {
		core, found, err := k.loadProfile(ctx, owner)
		if err != nil {
			return err
		}
		if !found {
			return nil
		}
		params := k.GetParams(ctx)
		limit := params.DailyRelayLimit(int(core.Level))
		if limit == 0 {
			return nil
		}
		q, _, err := k.getQuota(ctx, owner)
		if err != nil {
			return err
		}
		epoch := types.UTCEpoch(ctx.BlockTime().Unix())
		used := q.Count
		if q.UtcEpoch != epoch {
			used = 0
		}
		if used >= limit {
			return fmt.Errorf("subscriber_daily_limit_reached epoch=%d limit=%d used=%d remaining=0 reset=%d",
				epoch, limit, used, (epoch+1)*86400)
		}
		return nil
	}
	core, found, err := k.loadProfile(ctx, owner)
	if err != nil {
		return err
	}
	if !found {
		return nil
	}
	params := k.GetParams(ctx)
	limit := params.DailyRelayLimit(int(core.Level))
	if limit == 0 {
		return nil
	}
	epoch := types.UTCEpoch(ctx.BlockTime().Unix())
	q, _, err := k.getQuota(ctx, owner)
	if err != nil {
		return err
	}
	if q.UtcEpoch != epoch {
		q.UtcEpoch = epoch
		q.Count = 0
	}
	if q.Count >= limit {
		return fmt.Errorf("subscriber_daily_limit_reached epoch=%d limit=%d used=%d remaining=0 reset=%d",
			epoch, limit, q.Count, (epoch+1)*86400)
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

// UsesRelayQuota is true when the owner's tier skips PoW and consumes a daily
// envelope quota (max_daily_relays > 0). Admins qualify without EffectivePaid.
func (k Keeper) UsesRelayQuota(ctx sdk.Context, owner string) (bool, error) {
	core, found, err := k.loadProfile(ctx, owner)
	if err != nil {
		return false, err
	}
	if !found {
		return false, nil
	}
	return k.GetParams(ctx).DailyRelayLimit(int(core.Level)) > 0, nil
}
