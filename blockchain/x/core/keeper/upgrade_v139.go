package keeper

import (
	"bytes"
	"encoding/binary"
	"encoding/json"
	"fmt"
	"strconv"
	"strings"

	sdkmath "cosmossdk.io/math"
	sdk "github.com/cosmos/cosmos-sdk/types"
	authtypes "github.com/cosmos/cosmos-sdk/x/auth/types"

	"mirage/x/core/types"
)

func (k Keeper) HasUpgradeV139(ctx sdk.Context) (bool, error) {
	return k.storeHas(ctx, []byte(types.UpgradeV139CompleteKey))
}

func (k Keeper) MigrateV139(ctx sdk.Context) error {
	done, err := k.HasUpgradeV139(ctx)
	if err != nil {
		return err
	}
	if done {
		ctx.Logger().Info("v1.39.0: sentinel already set; skipping migration")
		return nil
	}

	reserveTotal := sdkmath.ZeroInt()
	type prof struct {
		owner  string
		core   types.ProfileCore
		raw    []byte
		expiry int64
		level  int32
		auto   bool
		paid   bool
	}
	var profiles []prof
	if err := k.iterPrefixKeys(ctx, []byte(types.ProfilesPrefix), 0, func(key, value []byte) error {
		owner := strings.TrimPrefix(string(key), types.ProfilesPrefix)
		var core types.ProfileCore
		if err := json.Unmarshal(value, &core); err != nil {
			return fmt.Errorf("v1.39.0: decode profile %s: %w", owner, err)
		}
		core.Owner = owner
		reserveTotal = reserveTotal.Add(sdkmath.NewIntFromUint64(core.ReserveFunds))
		profiles = append(profiles, prof{
			owner:  owner,
			core:   core,
			raw:    append([]byte(nil), value...),
			expiry: core.SubscriptionExpiry,
			level:  core.Level,
			auto:   core.AutoRenew,
		})
		return nil
	}); err != nil {
		return err
	}

	indexByOwner := map[string]int64{}
	if err := k.iterPrefixKeys(ctx, []byte(types.SubscriptionsPrefix), 0, func(key, value []byte) error {
		trimmed := strings.TrimPrefix(string(key), types.SubscriptionsPrefix)
		parts := strings.SplitN(trimmed, ":", 2)
		if len(parts) != 2 {
			return fmt.Errorf("v1.39.0: malformed subscription key %q", key)
		}
		owner := parts[1]
		if _, dup := indexByOwner[owner]; dup {
			return fmt.Errorf("v1.39.0: duplicate subscription index for %s", owner)
		}
		expiry, err := strconv.ParseInt(parts[0], 16, 64)
		if err != nil {
			return fmt.Errorf("v1.39.0: parse subscription expiry %q: %w", parts[0], err)
		}
		indexByOwner[owner] = expiry
		return nil
	}); err != nil {
		return err
	}

	for i := range profiles {
		p := &profiles[i]
		idxExpiry, hasIdx := indexByOwner[p.owner]
		validPaid := p.expiry > ctx.BlockTime().Unix() && (p.level == types.LevelSubscriber || p.level == types.LevelAgent)
		if validPaid {
			if !hasIdx || idxExpiry != p.expiry {
				return fmt.Errorf("v1.39.0: paid profile %s missing matching expiry index (profile=%d index=%v)", p.owner, p.expiry, hasIdx)
			}
			p.paid = true
		} else if hasIdx && p.expiry > 0 && idxExpiry != p.expiry {
			return fmt.Errorf("v1.39.0: mismatched subscription index for %s", p.owner)
		}
		delete(indexByOwner, p.owner)
	}
	if len(indexByOwner) > 0 {
		return fmt.Errorf("v1.39.0: orphan subscription indexes remain: %d", len(indexByOwner))
	}

	modBal := k.bankBalance(ctx, k.moduleAddress(), k.mintDenom()).Amount
	if !modBal.GTE(reserveTotal) {
		return fmt.Errorf("v1.39.0: core module cannot cover reserve liability: balance=%s reserve=%s", modBal.String(), reserveTotal.String())
	}
	if reserveTotal.IsPositive() {
		if !reserveTotal.IsUint64() {
			return fmt.Errorf("v1.39.0: reserve total exceeds uint64")
		}
		if err := k.BurnFromModuleAmount(ctx, reserveTotal.Uint64()); err != nil {
			return fmt.Errorf("v1.39.0: burn aggregate reserve: %w", err)
		}
	}

	for i := range profiles {
		p := &profiles[i]
		p.core.ReserveFunds = 0
		if p.paid {
			p.core.EffectivePaid = true
			if p.core.Level == types.LevelAgent {
				p.core.Level = types.LevelSubscriber
			}
		} else {
			p.core.EffectivePaid = false
			if p.core.Level == types.LevelAgent {
				p.core.Level = types.LevelFree
			}
		}
		if err := k.saveProfile(ctx, p.core); err != nil {
			return fmt.Errorf("v1.39.0: save profile %s: %w", p.owner, err)
		}
	}

	// Pins from paid subscribers and admins both count as team subscribers.
	subscriberEligible := map[string]bool{}
	for _, p := range profiles {
		subscriberEligible[p.owner] = types.CanCurate(p.core)
	}
	if err := k.migrateFollowedTopics(ctx); err != nil {
		return err
	}
	if err := k.migrateBlockedTopics(ctx); err != nil {
		return err
	}
	if err := k.deletePrefix(ctx, []byte(types.EnabledAgentsPrefix)); err != nil {
		return err
	}
	if err := k.deletePrefix(ctx, []byte(types.ProfileEnabledAgentsPrefix)); err != nil {
		return err
	}
	if err := k.deletePrefix(ctx, []byte(types.ProfileFollowedTopicsPrefix)); err != nil {
		return err
	}
	if err := k.deletePrefix(ctx, []byte(types.ProfileBlockedTopicsPrefix)); err != nil {
		return err
	}
	if err := k.migrateCuratorDefinedCommunities(ctx, subscriberEligible); err != nil {
		return err
	}

	params := types.DefaultParams()
	stored := k.GetParams(ctx)
	params.MintInterval = stored.MintInterval
	params.MintQuantity = stored.MintQuantity
	params.MintDynamicCreditCap = stored.MintDynamicCreditCap
	params.MintFloorSplit = stored.MintFloorSplit
	params.MintDynamicSplit = stored.MintDynamicSplit
	params.MinDifficulty = stored.MinDifficulty
	params.PowDifficultyStep = stored.PowDifficultyStep
	params.PowMessageWindow = stored.PowMessageWindow
	params.PowMessageLimit = stored.PowMessageLimit
	params.PowCalmPeriodDefinition = stored.PowCalmPeriodDefinition
	params.PowCalmSequenceThreshold = stored.PowCalmSequenceThreshold
	params.BlockHashWindow = stored.BlockHashWindow
	params.PowDifficultyAllowance = stored.PowDifficultyAllowance
	params.MinUsernameSize = stored.MinUsernameSize
	params.MaxUsernameSize = stored.MaxUsernameSize
	params.SubscriptionPeriod = stored.SubscriptionPeriod
	if params.SubscriptionPeriod == 0 {
		params.SubscriptionPeriod = 43200
	}
	if err := params.ValidateV139(); err != nil {
		return fmt.Errorf("v1.39.0: params: %w", err)
	}
	if err := k.SetParams(ctx, params); err != nil {
		return err
	}

	for i := range profiles {
		if profiles[i].core.EffectivePaid && profiles[i].core.SubscriptionExpiry > 0 {
			if err := k.ReplaceSubscriptionRenewalSchedule(ctx, profiles[i].owner); err != nil {
				return fmt.Errorf("v1.39.0: renewal schedule %s: %w", profiles[i].owner, err)
			}
		}
	}

	poolAddr := authtypes.NewModuleAddress(types.CreatorPoolName)
	surplus := k.GetBalance(ctx, poolAddr.String(), types.MintDenom)
	if err := k.SetCreatorActivationSurplus(ctx, surplus); err != nil {
		return err
	}
	creatorEpoch, err := types.CreatorEpochFromUnix(ctx.BlockTime().Unix(), params.CreatorEpochSeconds)
	if err != nil {
		return err
	}
	if err := k.SetCreatorSchedule(ctx, types.CreatorSchedule{EpochSeconds: params.CreatorEpochSeconds}); err != nil {
		return err
	}
	if err := k.SetCreatorClock(ctx, creatorEpoch); err != nil {
		return err
	}
	if err := k.AnchorCreatorStream(ctx, ctx.BlockTime().Unix()); err != nil {
		return err
	}
	if err := k.storeSet(ctx, []byte(types.UpgradeV139CompleteKey), []byte{1}); err != nil {
		return err
	}
	ctx.Logger().Info("v1.39.0: migration complete",
		"profiles", len(profiles),
		"reserve_burned", reserveTotal.String(),
		"creator_surplus", surplus.String())
	return nil
}

func (k Keeper) migrateFollowedTopics(ctx sdk.Context) error {
	type join struct {
		owner, slug string
		key         []byte
	}
	var joins []join
	var extra [][]byte
	if err := k.iterPrefixKeys(ctx, []byte(types.FollowedTopicsPrefix), 0, func(key, value []byte) error {
		rest := key[len(types.FollowedTopicsPrefix):]
		if bytes.IndexByte(rest, 0) >= 0 || bytes.IndexByte(rest, '/') < 0 {
			extra = append(extra, append([]byte(nil), key...))
			return nil
		}
		slash := bytes.IndexByte(rest, '/')
		joins = append(joins, join{owner: string(rest[:slash]), slug: string(rest[slash+1:]), key: append([]byte(nil), key...)})
		return nil
	}); err != nil {
		return err
	}
	counts := map[string]uint32{}
	for _, j := range joins {
		dest := types.KeyJoin(j.owner, j.slug)
		if has, err := k.storeHas(ctx, dest); err != nil {
			return err
		} else if has {
			return fmt.Errorf("v1.39.0: destination join key already exists for %s/%s", j.owner, j.slug)
		}
		pref := &types.CommunityPreference{Mode: types.CurationPreferenceMode_CURATION_PREFERENCE_MODE_LIVE_DEFAULT}
		if err := k.setProto(ctx, dest, pref); err != nil {
			return err
		}
		if err := k.storeSet(ctx, types.KeyJoinRev(j.slug, j.owner), []byte{1}); err != nil {
			return err
		}
		counts[j.owner]++
		if err := k.storeDelete(ctx, j.key); err != nil {
			return err
		}
	}
	for _, key := range extra {
		if err := k.storeDelete(ctx, key); err != nil {
			return err
		}
	}
	for owner, n := range counts {
		if err := k.setU32Key(ctx, types.KeyJoinCount(owner), n); err != nil {
			return err
		}
	}
	return nil
}

func (k Keeper) migrateBlockedTopics(ctx sdk.Context) error {
	type entry struct {
		owner   string
		pattern string
		seq     uint64
	}
	var entries []entry
	maxSeq := map[string]uint64{}
	counts := map[string]uint32{}
	if err := k.iterPrefixKeys(ctx, []byte(types.BlockedTopicsPrefix), 0, func(key, value []byte) error {
		rest := key[len(types.BlockedTopicsPrefix):]
		if bytes.IndexByte(rest, 0) >= 0 {
			return nil
		}
		slash := bytes.IndexByte(rest, '/')
		if slash < 0 {
			return nil
		}
		owner := string(rest[:slash])
		pattern := string(rest[slash+1:])
		seq, err := getU64(value)
		if err != nil {
			return fmt.Errorf("v1.39.0: blocked topic seq for %s: %w", owner, err)
		}
		entries = append(entries, entry{owner, pattern, seq})
		if seq > maxSeq[owner] {
			maxSeq[owner] = seq
		}
		counts[owner]++
		return nil
	}); err != nil {
		return err
	}
	for _, e := range entries {
		dest := types.KeyBlockCommunity(e.owner, e.seq, e.pattern)
		if has, err := k.storeHas(ctx, dest); err != nil {
			return err
		} else if has {
			return fmt.Errorf("v1.39.0: destination blocked-community key exists for %s", e.owner)
		}
		if err := k.storeSet(ctx, dest, []byte{1}); err != nil {
			return err
		}
		if err := k.setU64Key(ctx, types.KeyBlockCommunityIdx(e.owner, e.pattern), e.seq); err != nil {
			return err
		}
	}
	for owner, n := range counts {
		if err := k.setU32Key(ctx, types.KeyBlockCommunityCount(owner), n); err != nil {
			return err
		}
		if err := k.setU64Key(ctx, types.KeyBlockCommunityNext(owner), maxSeq[owner]+1); err != nil {
			return err
		}
	}
	return k.deletePrefix(ctx, []byte(types.BlockedTopicsPrefix))
}

func (k Keeper) migrateCuratorDefinedCommunities(ctx sdk.Context, subscriberEligible map[string]bool) error {
	if err := k.iterPrefixKeys(ctx, []byte(types.PfxCommunity), 0, func(_, value []byte) error {
		var legacy types.Community
		if err := k.cdc.Unmarshal(value, &legacy); err != nil {
			return fmt.Errorf("v1.39.0: decode legacy community: %w", err)
		}
		return nil
	}); err != nil {
		return err
	}

	type teamKey struct {
		slug string
		id   uint64
	}
	teams := map[teamKey]*types.CurationTeam{}
	var teamOrder []teamKey
	if err := k.iterPrefixKeys(ctx, []byte(types.PfxCurationTeam), 0, func(_, value []byte) error {
		var team types.CurationTeam
		if err := k.cdc.Unmarshal(value, &team); err != nil {
			return fmt.Errorf("v1.39.0: decode curation team: %w", err)
		}
		if team.Community == "" || team.TeamId == 0 {
			return fmt.Errorf("v1.39.0: curation team has empty identity")
		}
		if team.CreatedOrder == 0 {
			team.CreatedOrder = team.TeamId
		}
		team.SubscriberCount = 0
		copyTeam := team
		key := teamKey{slug: team.Community, id: team.TeamId}
		if teams[key] != nil {
			return fmt.Errorf("v1.39.0: duplicate curation team identity %s/%d", key.slug, key.id)
		}
		teams[key] = &copyTeam
		teamOrder = append(teamOrder, key)
		return nil
	}); err != nil {
		return err
	}

	joinPrefix := []byte(types.PfxJoin)
	if err := k.iterPrefixKeys(ctx, joinPrefix, 0, func(key, value []byte) error {
		rest := key[len(joinPrefix):]
		if len(rest) < 22 {
			return fmt.Errorf("v1.39.0: malformed joined-community key")
		}
		owner := sdk.AccAddress(rest[:20]).String()
		slugPart := rest[20:]
		n := int(binary.BigEndian.Uint16(slugPart[:2]))
		if len(slugPart) != 2+n {
			return fmt.Errorf("v1.39.0: malformed joined-community slug")
		}
		if !subscriberEligible[owner] || len(value) == 0 {
			return nil
		}
		var pref types.CommunityPreference
		if err := k.cdc.Unmarshal(value, &pref); err != nil {
			return fmt.Errorf("v1.39.0: decode preference for %s: %w", owner, err)
		}
		if pref.Mode != types.CurationPreferenceMode_CURATION_PREFERENCE_MODE_PINNED {
			return nil
		}
		tk := teamKey{slug: string(slugPart[2:]), id: pref.PinnedTeamId}
		team := teams[tk]
		if team == nil || team.DeletedHeight != 0 {
			return nil
		}
		next, err := types.CheckedAddUint64(team.SubscriberCount, 1)
		if err != nil {
			return fmt.Errorf("v1.39.0: subscriber recount %s/%d: %w", tk.slug, tk.id, err)
		}
		team.SubscriberCount = next
		return nil
	}); err != nil {
		return err
	}

	for _, key := range teamOrder {
		team := teams[key]
		if err := k.SetCurationTeam(ctx, team); err != nil {
			return fmt.Errorf("v1.39.0: save curation team %s/%d: %w", team.Community, team.TeamId, err)
		}
	}

	retiredPrefixes := []string{
		types.PfxCommunity,
		types.PfxCommunitySupport,
		types.PfxCommunityFounder,
		types.PfxCommunityHistory,
		types.PfxCommunityHistNext,
		types.PfxCurationEligible,
		types.PfxCurationSupportOrd,
		types.PfxCurationCreated,
	}
	for _, prefix := range retiredPrefixes {
		if err := k.deletePrefix(ctx, []byte(prefix)); err != nil {
			return fmt.Errorf("v1.39.0: delete retired prefix %q: %w", prefix, err)
		}
	}
	if err := k.storeDelete(ctx, []byte(types.PfxCommunitySeq)); err != nil {
		return fmt.Errorf("v1.39.0: delete retired community sequence: %w", err)
	}
	return nil
}

// EnsureCurationTeamFoundersSubscribed pins each live team's owner to that
// team so the founder counts as the first subscriber. Idempotent; gated by
// UpgradeV139FounderSubsKey. Safe to call from BeginBlock after v1.39.0.
func (k Keeper) EnsureCurationTeamFoundersSubscribed(ctx sdk.Context) error {
	done, err := k.storeHas(ctx, []byte(types.UpgradeV139FounderSubsKey))
	if err != nil {
		return err
	}
	if done {
		return nil
	}
	params := k.GetParams(ctx)
	pinned := 0
	if err := k.iterPrefixKeys(ctx, []byte(types.PfxCurationTeam), 0, func(_, value []byte) error {
		var team types.CurationTeam
		if err := k.cdc.Unmarshal(value, &team); err != nil {
			return fmt.Errorf("v1.39.0: decode curation team for founder pin: %w", err)
		}
		if team.DeletedHeight != 0 || team.Community == "" || team.TeamId == 0 || team.Owner == "" {
			return nil
		}
		core, found, err := k.loadProfile(ctx, team.Owner)
		if err != nil {
			return err
		}
		if !found || !types.CanCurate(core) {
			ctx.Logger().Info("v1.39.0: skip founder pin; owner cannot curate",
				"community", team.Community, "team_id", team.TeamId, "owner", team.Owner)
			return nil
		}
		tier := params.GetTierConfig(int(core.Level))
		if tier == nil {
			return fmt.Errorf("v1.39.0: tier missing for founder %s", team.Owner)
		}
		if err := k.JoinCommunity(ctx, team.Owner, team.Community, uint32(tier.MaxJoinedCommunities)); err != nil {
			return fmt.Errorf("v1.39.0: join founder %s to %s: %w", team.Owner, team.Community, err)
		}
		if err := k.SetCurationPreference(
			ctx,
			team.Owner,
			team.Community,
			types.CurationPreferenceMode_CURATION_PREFERENCE_MODE_PINNED,
			team.TeamId,
			true,
		); err != nil {
			return fmt.Errorf("v1.39.0: pin founder %s to %s/%d: %w", team.Owner, team.Community, team.TeamId, err)
		}
		pinned++
		return nil
	}); err != nil {
		return err
	}
	if err := k.storeSet(ctx, []byte(types.UpgradeV139FounderSubsKey), []byte{1}); err != nil {
		return err
	}
	ctx.Logger().Info("v1.39.0: founder subscriber pins complete", "teams_touched", pinned)
	return nil
}

func (k Keeper) deletePrefix(ctx sdk.Context, prefix []byte) error {
	var keys [][]byte
	if err := k.iterPrefixKeys(ctx, prefix, 0, func(key, _ []byte) error {
		keys = append(keys, append([]byte(nil), key...))
		return nil
	}); err != nil {
		return err
	}
	for _, key := range keys {
		if err := k.storeDelete(ctx, key); err != nil {
			return err
		}
	}
	return nil
}

func (k Keeper) ProcessBeginBlockV139(ctx sdk.Context) error {
	if done, err := k.HasUpgradeV139(ctx); err != nil {
		return err
	} else if !done {
		return nil
	}
	if err := k.EnsureCurationTeamFoundersSubscribed(ctx); err != nil {
		return err
	}
	params := k.GetParams(ctx)
	if err := k.advanceCreatorClock(ctx, params); err != nil {
		return err
	}
	if err := k.processEarlyRenewals(ctx, params); err != nil {
		return err
	}
	if err := k.processSubscriptionExpiries(ctx, params); err != nil {
		return err
	}
	if err := k.processCreatorSettlement(ctx, params); err != nil {
		return err
	}
	if err := k.processCreatorExpiries(ctx, params); err != nil {
		return err
	}
	if err := k.processCreatorPruning(ctx, params); err != nil {
		return err
	}
	return nil
}

// advanceCreatorClock walks the clock one epoch at a time, bounded per block.
//
// It used to jump straight to the epoch implied by block time and close
// whatever happened to be sitting in the ceopen| index. That worked when every
// epoch's pool had already been written at purchase time. Now an epoch's pool
// is drawn from the streaming accumulator as the epoch's end boundary passes,
// so each boundary has to actually be visited or its money would be integrated
// over and silently folded into a later epoch.
func (k Keeper) advanceCreatorClock(ctx sdk.Context, params types.Params) error {
	target, err := k.CreatorEpochAt(ctx, ctx.BlockTime().Unix())
	if err != nil {
		return err
	}
	cur, err := k.GetCreatorClock(ctx)
	if err != nil {
		return err
	}
	if target < cur {
		return fmt.Errorf("CONSENSUS_FATAL:CREATOR_CLOCK_REGRESSION have=%d new=%d", cur, target)
	}
	if target == cur {
		return nil
	}
	sched, err := k.GetCreatorSchedule(ctx)
	if err != nil {
		return err
	}
	for advanced := uint64(0); cur < target && advanced < params.CreatorEpochClosuresPerBlock; advanced++ {
		skipTo, err := k.idleCreatorClockTarget(ctx, sched, cur, target)
		if err != nil {
			return err
		}
		if skipTo > cur {
			// Nothing is streaming and no epoch in between was ever touched,
			// so every boundary up to here would draw zero and close nothing.
			// Visiting them one per block would make an idle chain crawl.
			// The stream cursor is deliberately left behind: settling it later
			// integrates a zero rate across the gap and still applies the next
			// breakpoint in order.
			cur = skipTo
			if err := k.SetCreatorClock(ctx, cur); err != nil {
				return err
			}
			continue
		}
		boundary, err := sched.EpochEnd(cur)
		if err != nil {
			return err
		}
		amount, complete, err := k.DrawCreatorStream(ctx, boundary, int(params.CreatorSettlementRecordsPerBlock))
		if err != nil {
			return err
		}
		if !complete {
			// Too many tranche boundaries in this window to apply in one
			// block. Leave the clock where it is and resume next block.
			return nil
		}
		if amount.IsPositive() {
			if err := k.addEpochPool(ctx, cur, amount); err != nil {
				return err
			}
			ctx.Logger().Debug("creator stream drew epoch pool",
				"epoch", cur,
				"boundary", boundary,
				"amount", amount.String(),
				"height", ctx.BlockHeight())
		}
		if err := k.closeCreatorEpoch(ctx, cur); err != nil {
			return err
		}
		cur++
		if err := k.SetCreatorClock(ctx, cur); err != nil {
			return err
		}
	}
	return nil
}

// idleCreatorClockTarget reports how far the clock may jump from cur without
// skipping work: no money can accrue before the next stream breakpoint, and no
// epoch below the returned bound has a record waiting to be closed. It returns
// cur when the clock must step normally.
func (k Keeper) idleCreatorClockTarget(ctx sdk.Context, sched types.CreatorSchedule, cur, target int64) (int64, error) {
	idleUntil, idle, err := k.CreatorStreamIdleUntil(ctx)
	if err != nil {
		return 0, err
	}
	if !idle {
		return cur, nil
	}
	limit := target
	if idleUntil > 0 {
		next, err := sched.EpochAt(idleUntil)
		if err != nil {
			return 0, err
		}
		if next < limit {
			limit = next
		}
	}
	open, found, err := k.earliestOpenCreatorEpoch(ctx)
	if err != nil {
		return 0, err
	}
	if found && open < limit {
		limit = open
	}
	if limit < cur {
		return cur, nil
	}
	return limit, nil
}

func (k Keeper) earliestOpenCreatorEpoch(ctx sdk.Context) (int64, bool, error) {
	pfx := []byte(types.PfxCreatorEpochOpen)
	epoch := int64(0)
	found := false
	err := k.iterPrefixKeys(ctx, pfx, 1, func(key, _ []byte) error {
		if found {
			return nil
		}
		if len(key) < len(pfx)+8 {
			return fmt.Errorf("malformed ceopen key")
		}
		epoch = int64(binary.BigEndian.Uint64(key[len(pfx):]))
		found = true
		return nil
	})
	if err != nil {
		return 0, false, err
	}
	return epoch, found, nil
}

// closeCreatorEpoch moves one elapsed epoch into settlement. An epoch that
// neither received stream money nor saw engagement has no record at all and is
// skipped, exactly as before.
func (k Keeper) closeCreatorEpoch(ctx sdk.Context, epoch int64) error {
	open, err := k.storeHas(ctx, types.KeyCreatorEpochOpen(epoch))
	if err != nil {
		return err
	}
	if !open {
		return nil
	}
	if err := k.storeDelete(ctx, types.KeyCreatorEpochOpen(epoch)); err != nil {
		return err
	}
	if err := k.storeSet(ctx, types.KeyCreatorEpochSettle(epoch), []byte{1}); err != nil {
		return err
	}
	var ce types.CreatorEpoch
	found, err := k.getProto(ctx, types.KeyCreatorEpoch(epoch), &ce)
	if err != nil {
		return err
	}
	if !found {
		return fmt.Errorf("CONSENSUS_FATAL:CREATOR_EPOCH_MISSING epoch=%d", epoch)
	}
	ce.Status = types.CreatorEpochStatus_CREATOR_EPOCH_STATUS_COUNTING
	ce.Phase = types.CreatorSettlementPhase_CREATOR_SETTLEMENT_PHASE_COUNT
	ce.SettlementCursor = nil
	ce.PartialActor = ""
	ce.PartialCount = 0
	if ce.AllocatedTotal == "" {
		ce.AllocatedTotal = "0"
	}
	if ce.ClaimedTotal == "" {
		ce.ClaimedTotal = "0"
	}
	if err := k.setProto(ctx, types.KeyCreatorEpoch(epoch), &ce); err != nil {
		return err
	}
	ctx.EventManager().EmitEvent(sdk.NewEvent("creator_epoch_closed",
		sdk.NewAttribute("epoch", fmt.Sprintf("%d", epoch)),
		sdk.NewAttribute("pool", ce.Pool),
		sdk.NewAttribute("gross_records", fmt.Sprintf("%d", ce.GrossRecords)),
	))
	return nil
}

func (k Keeper) processEarlyRenewals(ctx sdk.Context, params types.Params) error {
	now := ctx.BlockTime().Unix()
	n := uint64(0)
	var due [][]byte
	if err := k.iterPrefixKeys(ctx, []byte(types.PfxSubRenewalQueue), int(params.SubscriptionRenewalAttemptsPerBlock)+8, func(key, _ []byte) error {
		if n >= params.SubscriptionRenewalAttemptsPerBlock {
			return nil
		}
		pfx := []byte(types.PfxSubRenewalQueue)
		if len(key) < len(pfx)+8 {
			return fmt.Errorf("malformed sr key")
		}
		attempt := int64(binary.BigEndian.Uint64(key[len(pfx) : len(pfx)+8]))
		if attempt > now {
			return nil
		}
		due = append(due, append([]byte(nil), key...))
		n++
		return nil
	}); err != nil {
		return err
	}
	for _, key := range due {
		if err := k.attemptRenewalFromQueueKey(ctx, key); err != nil {
			return err
		}
	}
	return nil
}

func (k Keeper) attemptRenewalFromQueueKey(ctx sdk.Context, key []byte) error {
	pfx := []byte(types.PfxSubRenewalQueue)
	rest := key[len(pfx):]
	if len(rest) < 8+20+8+8 {
		return fmt.Errorf("sr key too short")
	}
	addr := sdk.AccAddress(rest[8 : 8+20]).String()
	core, found, err := k.loadProfile(ctx, addr)
	if err != nil {
		return err
	}
	if !found {
		return k.storeDelete(ctx, key)
	}
	if err := k.storeDelete(ctx, key); err != nil {
		return err
	}
	if !core.AutoRenew || core.SubscriptionExpiry <= 0 {
		return k.ReplaceSubscriptionRenewalSchedule(ctx, addr)
	}
	tier := k.GetParams(ctx).GetTierConfig(types.LevelSubscriber)
	if tier == nil {
		return fmt.Errorf("subscriber tier missing")
	}
	bal := k.GetBalance(ctx, addr, types.MintDenom)
	if bal.LT(sdkmath.NewIntFromUint64(tier.PeriodFee)) {
		ctx.EventManager().EmitEvent(sdk.NewEvent("subscription_renewal_warning",
			sdk.NewAttribute("address", addr),
			sdk.NewAttribute("required", fmt.Sprintf("%d", tier.PeriodFee)),
			sdk.NewAttribute("balance", bal.String()),
		))
		return k.ReplaceSubscriptionRenewalSchedule(ctx, addr)
	}
	return k.CreateTranche(ctx, addr, addr, types.SubscriptionTrancheSource_SUBSCRIPTION_TRANCHE_SOURCE_AUTO_RENEWAL, 1, "")
}

func (k Keeper) processSubscriptionExpiries(ctx sdk.Context, params types.Params) error {
	expired, err := k.GetExpiredSubscriptions(ctx, ctx.BlockTime().Unix())
	if err != nil {
		return err
	}
	n := uint64(0)
	for _, sub := range expired {
		if n >= params.SubscriptionTransitionsPerBlock {
			break
		}
		if err := k.RemoveSubscription(ctx, sub.Address, sub.Expiry); err != nil {
			return err
		}
		if err := k.TransitionPaidState(ctx, sub.Address, false); err != nil {
			return err
		}
		n++
	}
	return nil
}
