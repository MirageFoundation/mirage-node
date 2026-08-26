package keeper

import (
	"fmt"

	sdk "github.com/cosmos/cosmos-sdk/types"

	"mirage/x/core/types"
)

func (k Keeper) TransitionPaidState(ctx sdk.Context, owner string, activate bool) error {
	core, found, err := k.loadProfile(ctx, owner)
	if err != nil {
		return err
	}
	if !found {
		return fmt.Errorf("profile missing for paid-state transition: %s", owner)
	}
	if activate {
		if core.EffectivePaid {
			return nil
		}
		if core.SubscriptionExpiry <= ctx.BlockTime().Unix() {
			return fmt.Errorf("cannot activate paid state without future expiry")
		}
		core.EffectivePaid = true
		if core.Level == types.LevelFree {
			core.Level = types.LevelSubscriber
		}
		if err := k.saveProfile(ctx, core); err != nil {
			return err
		}
		slugs, err := k.ListJoinedCommunities(ctx, owner)
		if err != nil {
			return err
		}
		for _, slug := range slugs {
			pref, ok, err := k.GetPreference(ctx, owner, slug)
			if err != nil {
				return err
			}
			if !ok {
				return fmt.Errorf("CONSENSUS_FATAL:JOIN_PREF_MISSING owner=%s community=%s", owner, slug)
			}
			if err := k.addSupportContribution(ctx, slug, pref); err != nil {
				return err
			}
			if err := k.recomputeCrown(ctx, slug); err != nil {
				return err
			}
		}
		ctx.EventManager().EmitEvent(sdk.NewEvent("subscription_effective_state_changed",
			sdk.NewAttribute("address", owner),
			sdk.NewAttribute("effective_paid", "true"),
			sdk.NewAttribute("expiry", fmt.Sprintf("%d", core.SubscriptionExpiry)),
		))
		return nil
	}
	if !core.EffectivePaid {
		core.SubscriptionExpiry = 0
		core.AutoRenew = false
		if err := k.saveProfile(ctx, core); err != nil {
			return err
		}
		return k.ReplaceSubscriptionRenewalSchedule(ctx, owner)
	}
	slugs, err := k.ListJoinedCommunities(ctx, owner)
	if err != nil {
		return err
	}
	for _, slug := range slugs {
		pref, ok, err := k.GetPreference(ctx, owner, slug)
		if err != nil {
			return err
		}
		if !ok {
			return fmt.Errorf("CONSENSUS_FATAL:JOIN_PREF_MISSING owner=%s community=%s", owner, slug)
		}
		if err := k.removeSupportContribution(ctx, slug, pref, true); err != nil {
			return err
		}
		if err := k.recomputeCrown(ctx, slug); err != nil {
			return err
		}
	}
	var memberships []struct {
		slug   string
		teamID uint64
	}
	if err := k.iterPrefixKeys(ctx, types.KeyCurationTeamUserPrefix(owner), 0, func(key, value []byte) error {
		id, err := getU64(value)
		if err != nil {
			return err
		}
		pfx := types.KeyCurationTeamUserPrefix(owner)
		rest := key[len(pfx):]
		n := int(rest[0])<<8 | int(rest[1])
		slug := string(rest[2 : 2+n])
		memberships = append(memberships, struct {
			slug   string
			teamID uint64
		}{slug, id})
		return nil
	}); err != nil {
		return err
	}
	for _, m := range memberships {
		if err := k.handlePaidDeactivationMembership(ctx, owner, m.slug, m.teamID); err != nil {
			return err
		}
	}
	core.EffectivePaid = false
	if core.Level == types.LevelSubscriber {
		core.Level = types.LevelFree
	}
	core.SubscriptionExpiry = 0
	core.AutoRenew = false
	if err := k.saveProfile(ctx, core); err != nil {
		return err
	}
	if err := k.ReplaceSubscriptionRenewalSchedule(ctx, owner); err != nil {
		return err
	}
	ctx.EventManager().EmitEvent(sdk.NewEvent("subscription_effective_state_changed",
		sdk.NewAttribute("address", owner),
		sdk.NewAttribute("effective_paid", "false"),
		sdk.NewAttribute("expiry", "0"),
	))
	return nil
}

func (k Keeper) handlePaidDeactivationMembership(ctx sdk.Context, owner, slug string, teamID uint64) error {
	team, ok, err := k.GetCurationTeam(ctx, slug, teamID)
	if err != nil || !ok || !k.teamLive(team) {
		return err
	}
	if team.Owner != owner {
		return k.RemoveCuratorFromTeam(ctx, slug, teamID, owner, "curator_removed")
	}
	type mem struct {
		addr  string
		order uint64
	}
	var members []mem
	if err := k.iterPrefixKeys(ctx, types.KeyCurationTeamMemberPrefix(slug, teamID), 11, func(_, value []byte) error {
		var m types.CurationTeamMember
		if err := k.cdc.Unmarshal(value, &m); err != nil {
			return err
		}
		members = append(members, mem{addr: m.Address, order: m.AcceptedOrder})
		return nil
	}); err != nil {
		return err
	}
	var successor string
	var bestOrder uint64
	for _, m := range members {
		if m.addr == owner {
			continue
		}
		core, found, err := k.loadProfile(ctx, m.addr)
		if err != nil {
			return err
		}
		if !found || !core.EffectivePaid {
			if err := k.RemoveCuratorFromTeam(ctx, slug, teamID, m.addr, "curator_removed"); err != nil {
				return err
			}
			continue
		}
		if successor == "" || m.order < bestOrder || (m.order == bestOrder && m.addr < successor) {
			successor = m.addr
			bestOrder = m.order
		}
	}
	if successor == "" {
		return k.DeleteCurationTeam(ctx, slug, teamID)
	}
	if err := k.RemoveCuratorFromTeam(ctx, slug, teamID, owner, "curator_removed"); err != nil {
		return err
	}
	if err := k.removeSupportIndex(ctx, team); err != nil {
		return err
	}
	if err := k.deleteEligibleIndex(ctx, team); err != nil {
		return err
	}
	team.Owner = successor
	if err := k.SetCurationTeam(ctx, team); err != nil {
		return err
	}
	if err := k.writeEligibleIndex(ctx, team); err != nil {
		return err
	}
	if err := k.writeSupportIndex(ctx, team); err != nil {
		return err
	}
	if err := k.recomputeCrown(ctx, slug); err != nil {
		return err
	}
	ctx.EventManager().EmitEvent(sdk.NewEvent("curation_team_owner_changed",
		sdk.NewAttribute("community", slug),
		sdk.NewAttribute("team_id", fmt.Sprintf("%d", teamID)),
		sdk.NewAttribute("owner", successor),
	))
	return nil
}

func (k Keeper) ReplaceSubscriptionRenewalSchedule(ctx sdk.Context, owner string) error {
	var st types.SubscriptionRenewalState
	found, err := k.getProto(ctx, types.KeySubRenewalState(owner), &st)
	if err != nil {
		return err
	}
	if found {
		old := types.KeySubRenewalQueue(st.NextAttemptUnix, owner, st.Expiry, st.Generation)
		if err := k.storeDelete(ctx, old); err != nil {
			return err
		}
	}
	core, ok, err := k.loadProfile(ctx, owner)
	if err != nil {
		return err
	}
	if !ok || core.SubscriptionExpiry <= 0 {
		return k.storeDelete(ctx, types.KeySubRenewalState(owner))
	}
	params := k.GetParams(ctx)
	now := ctx.BlockTime().Unix()
	attempt := core.SubscriptionExpiry - int64(params.SubscriptionEarlyRenewalDays)*86400
	if attempt < now {
		attempt = now
	}
	gen := st.Generation + 1
	st = types.SubscriptionRenewalState{
		Expiry:          core.SubscriptionExpiry,
		NextAttemptUnix: attempt,
		WarningSent:     false,
		Generation:      gen,
	}
	if err := k.setProto(ctx, types.KeySubRenewalState(owner), &st); err != nil {
		return err
	}
	return k.storeSet(ctx, types.KeySubRenewalQueue(attempt, owner, core.SubscriptionExpiry, gen), []byte{1})
}
