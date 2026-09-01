package keeper

import (
	"bytes"
	"encoding/binary"
	"encoding/hex"
	"fmt"

	sdkmath "cosmossdk.io/math"
	sdk "github.com/cosmos/cosmos-sdk/types"

	"mirage/x/core/types"
)

const engagementKeySuffixLen = 20 + 1 + 32

func (k Keeper) processCreatorSettlement(ctx sdk.Context, params types.Params) error {
	budget := int(params.CreatorSettlementRecordsPerBlock)
	if budget < 1 {
		return fmt.Errorf("creator_settlement_records_per_block must be positive")
	}
	var epochs []int64
	if err := k.iterPrefixKeys(ctx, []byte(types.PfxCreatorEpochSettle), 32, func(key, _ []byte) error {
		if len(key) < len(types.PfxCreatorEpochSettle)+8 {
			return fmt.Errorf("malformed cesettle key")
		}
		epochs = append(epochs, int64(binary.BigEndian.Uint64(key[len(types.PfxCreatorEpochSettle):])))
		return nil
	}); err != nil {
		return err
	}
	for _, epoch := range epochs {
		if budget <= 0 {
			return nil
		}
		remaining, err := k.settleOneEpoch(ctx, epoch, budget)
		if err != nil {
			return err
		}
		budget = remaining
	}
	return nil
}

func (k Keeper) settleOneEpoch(ctx sdk.Context, epoch int64, budget int) (int, error) {
	var ce types.CreatorEpoch
	found, err := k.getProto(ctx, types.KeyCreatorEpoch(epoch), &ce)
	if err != nil {
		return budget, err
	}
	if !found {
		return budget, haltFinalizeInvariantError(ctx, "creator_epoch_missing",
			fmt.Errorf("settlement epoch %d missing", epoch))
	}
	switch ce.Status {
	case types.CreatorEpochStatus_CREATOR_EPOCH_STATUS_COUNTING:
		if ce.Phase != types.CreatorSettlementPhase_CREATOR_SETTLEMENT_PHASE_COUNT {
			return budget, fmt.Errorf("epoch %d status/phase mismatch", epoch)
		}
		return k.countEpoch(ctx, &ce, budget)
	case types.CreatorEpochStatus_CREATOR_EPOCH_STATUS_ALLOCATING:
		if ce.Phase != types.CreatorSettlementPhase_CREATOR_SETTLEMENT_PHASE_ALLOCATE {
			return budget, fmt.Errorf("epoch %d status/phase mismatch", epoch)
		}
		return k.allocateEpoch(ctx, &ce, budget)
	default:
		if err := k.storeDelete(ctx, types.KeyCreatorEpochSettle(epoch)); err != nil {
			return budget, err
		}
		return budget, nil
	}
}

func (k Keeper) countEpoch(ctx sdk.Context, ce *types.CreatorEpoch, budget int) (int, error) {
	pfx := types.KeyEngagementEpochPrefix(ce.EpochId)
	start := pfx
	exclusive := false
	if len(ce.SettlementCursor) > 0 {
		start = ce.SettlementCursor
		exclusive = true
	}
	processed := 0
	exhausted := true
	if err := k.iterPrefixFrom(ctx, pfx, start, exclusive, budget+1, func(key, value []byte) error {
		if processed >= budget {
			exhausted = false
			return nil
		}
		actor, kind, target, err := parseEngagementKey(key)
		if err != nil {
			return err
		}
		actorStr := sdk.AccAddress(actor).String()
		if ce.PartialActor != "" && ce.PartialActor != actorStr {
			if err := k.flushCountActor(ctx, ce); err != nil {
				return err
			}
		}
		ce.PartialActor = actorStr
		valid, err := k.engagementValid(ctx, ce.EpochId, actorStr, kind, target, value)
		if err != nil {
			return err
		}
		if valid {
			ce.PartialCount++
		}
		ce.SettlementCursor = append([]byte(nil), key...)
		processed++
		return nil
	}); err != nil {
		return budget, err
	}
	if exhausted {
		if ce.PartialActor != "" {
			if err := k.flushCountActor(ctx, ce); err != nil {
				return budget, err
			}
		}
		return k.finishCount(ctx, ce, budget-processed)
	}
	ctx.EventManager().EmitEvent(sdk.NewEvent("creator_settlement_progress",
		sdk.NewAttribute("epoch", fmt.Sprintf("%d", ce.EpochId)),
		sdk.NewAttribute("phase", "count"),
		sdk.NewAttribute("processed", fmt.Sprintf("%d", processed)),
	))
	if err := k.setProto(ctx, types.KeyCreatorEpoch(ce.EpochId), ce); err != nil {
		return budget, err
	}
	return budget - processed, nil
}

func (k Keeper) flushCountActor(ctx sdk.Context, ce *types.CreatorEpoch) error {
	if ce.PartialActor == "" {
		return nil
	}
	if err := k.setU64Key(ctx, types.KeyEngagementCount(ce.EpochId, types.MustAcc(ce.PartialActor)), ce.PartialCount); err != nil {
		return err
	}
	if ce.PartialCount > 0 {
		next, err := types.CheckedAddUint64(ce.ActiveEngagers, 1)
		if err != nil {
			return err
		}
		ce.ActiveEngagers = next
	}
	ce.PartialActor = ""
	ce.PartialCount = 0
	return nil
}

func (k Keeper) finishCount(ctx sdk.Context, ce *types.CreatorEpoch, remaining int) (int, error) {
	pool, err := k.parseInt(ce.Pool)
	if err != nil {
		return remaining, err
	}
	if ce.ActiveEngagers == 0 {
		if err := k.expireEpochUnallocated(ctx, ce, pool); err != nil {
			return remaining, err
		}
		return remaining, nil
	}
	slice := pool.Quo(sdkmath.NewIntFromUint64(ce.ActiveEngagers))
	ce.EngagerSlice = slice.String()
	ce.Status = types.CreatorEpochStatus_CREATOR_EPOCH_STATUS_ALLOCATING
	ce.Phase = types.CreatorSettlementPhase_CREATOR_SETTLEMENT_PHASE_ALLOCATE
	ce.SettlementCursor = nil
	ce.PartialActor = ""
	ce.PartialCount = 0
	if ce.AllocatedTotal == "" {
		ce.AllocatedTotal = "0"
	}
	if err := k.setProto(ctx, types.KeyCreatorEpoch(ce.EpochId), ce); err != nil {
		return remaining, err
	}
	ctx.EventManager().EmitEvent(sdk.NewEvent("creator_settlement_progress",
		sdk.NewAttribute("epoch", fmt.Sprintf("%d", ce.EpochId)),
		sdk.NewAttribute("phase", "count_complete"),
		sdk.NewAttribute("active_engagers", fmt.Sprintf("%d", ce.ActiveEngagers)),
		sdk.NewAttribute("engager_slice", ce.EngagerSlice),
	))
	if remaining <= 0 {
		return remaining, nil
	}
	return k.allocateEpoch(ctx, ce, remaining)
}

func (k Keeper) allocateEpoch(ctx sdk.Context, ce *types.CreatorEpoch, budget int) (int, error) {
	pfx := types.KeyEngagementEpochPrefix(ce.EpochId)
	start := pfx
	exclusive := false
	if len(ce.SettlementCursor) > 0 {
		start = ce.SettlementCursor
		exclusive = true
	}
	slice, err := k.parseInt(ce.EngagerSlice)
	if err != nil {
		return budget, err
	}
	allocated, err := k.parseInt(ce.AllocatedTotal)
	if err != nil {
		return budget, err
	}
	processed := 0
	exhausted := true
	if err := k.iterPrefixFrom(ctx, pfx, start, exclusive, budget+1, func(key, value []byte) error {
		if processed >= budget {
			exhausted = false
			return nil
		}
		actor, kind, target, err := parseEngagementKey(key)
		if err != nil {
			return err
		}
		actorStr := sdk.AccAddress(actor).String()
		valid, err := k.engagementValid(ctx, ce.EpochId, actorStr, kind, target, value)
		if err != nil {
			return err
		}
		if valid {
			units, found, err := k.getU64Key(ctx, types.KeyEngagementCount(ce.EpochId, actor))
			if err != nil {
				return err
			}
			if !found || units == 0 {
				return fmt.Errorf("CONSENSUS_FATAL:CREATOR_EVC_MISSING actor=%s epoch=%d", actorStr, ce.EpochId)
			}
			perUnit := slice.Quo(sdkmath.NewIntFromUint64(units))
			if err := k.applyAllocation(ctx, ce, kind, target, perUnit); err != nil {
				return err
			}
			if perUnit.IsPositive() {
				allocated = allocated.Add(perUnit)
			}
		}
		ce.SettlementCursor = append([]byte(nil), key...)
		ce.AllocatedTotal = allocated.String()
		processed++
		return nil
	}); err != nil {
		return budget, err
	}
	ce.AllocatedTotal = allocated.String()
	if exhausted {
		return k.finishAllocate(ctx, ce, allocated, budget-processed)
	}
	ctx.EventManager().EmitEvent(sdk.NewEvent("creator_settlement_progress",
		sdk.NewAttribute("epoch", fmt.Sprintf("%d", ce.EpochId)),
		sdk.NewAttribute("phase", "allocate"),
		sdk.NewAttribute("processed", fmt.Sprintf("%d", processed)),
		sdk.NewAttribute("allocated_total", ce.AllocatedTotal),
	))
	if err := k.setProto(ctx, types.KeyCreatorEpoch(ce.EpochId), ce); err != nil {
		return budget, err
	}
	return budget - processed, nil
}

func (k Keeper) applyAllocation(ctx sdk.Context, ce *types.CreatorEpoch, kind byte, target []byte, perUnit sdkmath.Int) error {
	targetHex := hex.EncodeToString(target)
	meta, ok, err := k.GetPostMetadata(ctx, targetHex)
	if err != nil {
		return err
	}
	if !ok {
		return haltFinalizeInvariantError(ctx, "creator_target_metadata_missing",
			fmt.Errorf("target %s missing during allocate epoch %d", targetHex, ce.EpochId))
	}
	var te types.TargetEarning
	found, err := k.getProto(ctx, types.KeyEpochTarget(ce.EpochId, target), &te)
	if err != nil {
		return err
	}
	if !found {
		te = types.TargetEarning{
			EpochId: ce.EpochId,
			Target:  targetHex,
			Creator: meta.Author,
			Amount:  "0",
		}
	}
	if kind == types.EngagementKindUpvote {
		next, err := types.CheckedAddUint64(te.UpvoteUnits, 1)
		if err != nil {
			return err
		}
		te.UpvoteUnits = next
	} else {
		next, err := types.CheckedAddUint64(te.DirectReplyUnits, 1)
		if err != nil {
			return err
		}
		te.DirectReplyUnits = next
	}
	if perUnit.IsPositive() {
		cur, err := k.parseInt(te.Amount)
		if err != nil {
			return err
		}
		te.Amount = cur.Add(perUnit).String()
		if err := k.addTargetTotal(ctx, target, perUnit); err != nil {
			return err
		}
		if err := k.addCreatorAccrual(ctx, ce.EpochId, meta.Author, perUnit); err != nil {
			return err
		}
	}
	if err := k.setProto(ctx, types.KeyEpochTarget(ce.EpochId, target), &te); err != nil {
		return err
	}
	return k.storeSet(ctx, types.KeyTargetEpoch(target, ce.EpochId), []byte{1})
}

func (k Keeper) addTargetTotal(ctx sdk.Context, target []byte, delta sdkmath.Int) error {
	bz, err := k.storeGet(ctx, types.KeyTargetTotal(target))
	if err != nil {
		return err
	}
	cur := sdkmath.ZeroInt()
	if len(bz) > 0 {
		v, ok := sdkmath.NewIntFromString(string(bz))
		if !ok {
			return fmt.Errorf("corrupt target total")
		}
		cur = v
	}
	return k.storeSet(ctx, types.KeyTargetTotal(target), []byte(cur.Add(delta).String()))
}

func (k Keeper) addCreatorAccrual(ctx sdk.Context, epoch int64, creator string, delta sdkmath.Int) error {
	key := types.KeyEpochCreatorAccrual(epoch, types.MustAcc(creator))
	var acc types.CreatorAccrual
	found, err := k.getProto(ctx, key, &acc)
	if err != nil {
		return err
	}
	if !found {
		acc = types.CreatorAccrual{Epoch: epoch, Creator: creator, Amount: "0", ClaimedAmount: "0"}
	}
	cur, err := k.parseInt(acc.Amount)
	if err != nil {
		return err
	}
	acc.Amount = cur.Add(delta).String()
	if err := k.setProto(ctx, key, &acc); err != nil {
		return err
	}
	return k.storeSet(ctx, types.KeyCreatorEpochIdx(types.MustAcc(creator), epoch), []byte{1})
}

func (k Keeper) finishAllocate(ctx sdk.Context, ce *types.CreatorEpoch, allocated sdkmath.Int, remaining int) (int, error) {
	pool, err := k.parseInt(ce.Pool)
	if err != nil {
		return remaining, err
	}
	if allocated.GT(pool) {
		return remaining, haltFinalizeInvariantError(ctx, "creator_allocated_exceeds_pool",
			fmt.Errorf("epoch %d allocated %s pool %s", ce.EpochId, allocated.String(), pool.String()))
	}
	if !allocated.IsPositive() {
		if err := k.expireEpochUnallocated(ctx, ce, pool); err != nil {
			return remaining, err
		}
		return remaining, nil
	}
	clock, err := k.GetCreatorClock(ctx)
	if err != nil {
		return remaining, err
	}
	params := k.GetParams(ctx)
	ce.FinalizedEpoch = clock
	ce.ClaimWindowDays = int64(params.CreatorClaimWindowDays)
	deadline, err := types.CreatorClaimDeadline(
		clock,
		params.CreatorClaimWindowDays,
		params.CreatorEpochSeconds,
	)
	if err != nil {
		return remaining, err
	}
	ce.ClaimDeadlineEpoch = deadline
	ce.Status = types.CreatorEpochStatus_CREATOR_EPOCH_STATUS_CLAIMABLE
	ce.SettlementCursor = nil
	if err := k.setProto(ctx, types.KeyCreatorEpoch(ce.EpochId), ce); err != nil {
		return remaining, err
	}
	if err := k.storeDelete(ctx, types.KeyCreatorEpochSettle(ce.EpochId)); err != nil {
		return remaining, err
	}
	if err := k.storeSet(ctx, types.KeyCreatorEpochDeadline(ce.ClaimDeadlineEpoch, ce.EpochId), []byte{1}); err != nil {
		return remaining, err
	}
	ctx.EventManager().EmitEvent(sdk.NewEvent("creator_epoch_claimable",
		sdk.NewAttribute("epoch", fmt.Sprintf("%d", ce.EpochId)),
		sdk.NewAttribute("allocated_total", allocated.String()),
		sdk.NewAttribute("claim_deadline_epoch", fmt.Sprintf("%d", ce.ClaimDeadlineEpoch)),
	))
	return remaining, nil
}

func (k Keeper) expireEpochUnallocated(ctx sdk.Context, ce *types.CreatorEpoch, burn sdkmath.Int) error {
	if err := k.burnCreatorPool(ctx, burn); err != nil {
		return err
	}
	ce.Status = types.CreatorEpochStatus_CREATOR_EPOCH_STATUS_EXPIRED
	ce.PrunePending = true
	ce.SettlementCursor = nil
	if ce.EngagerSlice == "" {
		ce.EngagerSlice = "0"
	}
	if ce.AllocatedTotal == "" {
		ce.AllocatedTotal = "0"
	}
	if ce.ClaimedTotal == "" {
		ce.ClaimedTotal = "0"
	}
	if err := k.setProto(ctx, types.KeyCreatorEpoch(ce.EpochId), ce); err != nil {
		return err
	}
	if err := k.storeDelete(ctx, types.KeyCreatorEpochSettle(ce.EpochId)); err != nil {
		return err
	}
	if err := k.storeSet(ctx, types.KeyCreatorEpochPrune(ce.EpochId), []byte{1}); err != nil {
		return err
	}
	ctx.EventManager().EmitEvent(sdk.NewEvent("creator_epoch_expired",
		sdk.NewAttribute("epoch", fmt.Sprintf("%d", ce.EpochId)),
		sdk.NewAttribute("burned", burn.String()),
	))
	return nil
}

func (k Keeper) processCreatorExpiries(ctx sdk.Context, params types.Params) error {
	clock, err := k.GetCreatorClock(ctx)
	if err != nil {
		return err
	}
	n := uint64(0)
	var due []int64
	if err := k.iterPrefixKeys(ctx, []byte(types.PfxCreatorEpochDeadline), int(params.CreatorEpochExpiriesPerBlock)+1, func(key, _ []byte) error {
		if n >= params.CreatorEpochExpiriesPerBlock {
			return nil
		}
		pfx := []byte(types.PfxCreatorEpochDeadline)
		if len(key) < len(pfx)+16 {
			return fmt.Errorf("malformed cedeadline key")
		}
		deadline := int64(binary.BigEndian.Uint64(key[len(pfx) : len(pfx)+8]))
		if deadline > clock {
			return nil
		}
		epoch := int64(binary.BigEndian.Uint64(key[len(pfx)+8:]))
		due = append(due, epoch)
		n++
		return nil
	}); err != nil {
		return err
	}
	for _, epoch := range due {
		if err := k.expireClaimableEpoch(ctx, epoch); err != nil {
			return err
		}
	}
	return nil
}

func (k Keeper) expireClaimableEpoch(ctx sdk.Context, epoch int64) error {
	var ce types.CreatorEpoch
	found, err := k.getProto(ctx, types.KeyCreatorEpoch(epoch), &ce)
	if err != nil {
		return err
	}
	if !found {
		return fmt.Errorf("CONSENSUS_FATAL:CREATOR_EPOCH_MISSING epoch=%d", epoch)
	}
	if ce.Status != types.CreatorEpochStatus_CREATOR_EPOCH_STATUS_CLAIMABLE {
		return k.storeDelete(ctx, types.KeyCreatorEpochDeadline(ce.ClaimDeadlineEpoch, epoch))
	}
	pool, err := k.parseInt(ce.Pool)
	if err != nil {
		return err
	}
	claimed, err := k.parseInt(ce.ClaimedTotal)
	if err != nil {
		return err
	}
	burn := pool.Sub(claimed)
	if burn.IsNegative() {
		return haltFinalizeInvariantError(ctx, "creator_claimed_exceeds_pool",
			fmt.Errorf("epoch %d claimed %s pool %s", epoch, claimed.String(), pool.String()))
	}
	if err := k.burnCreatorPool(ctx, burn); err != nil {
		return err
	}
	ce.Status = types.CreatorEpochStatus_CREATOR_EPOCH_STATUS_EXPIRED
	ce.PrunePending = true
	if err := k.setProto(ctx, types.KeyCreatorEpoch(epoch), &ce); err != nil {
		return err
	}
	if err := k.storeDelete(ctx, types.KeyCreatorEpochDeadline(ce.ClaimDeadlineEpoch, epoch)); err != nil {
		return err
	}
	if err := k.storeSet(ctx, types.KeyCreatorEpochPrune(epoch), []byte{1}); err != nil {
		return err
	}
	ctx.EventManager().EmitEvent(sdk.NewEvent("creator_epoch_expired",
		sdk.NewAttribute("epoch", fmt.Sprintf("%d", epoch)),
		sdk.NewAttribute("burned", burn.String()),
	))
	return nil
}

func (k Keeper) processCreatorPruning(ctx sdk.Context, params types.Params) error {
	budget := int(params.CreatorPruneKeysPerBlock)
	if budget < 1 {
		return fmt.Errorf("creator_prune_keys_per_block must be positive")
	}
	var epochs []int64
	if err := k.iterPrefixKeys(ctx, []byte(types.PfxCreatorEpochPrune), 8, func(key, _ []byte) error {
		if len(key) < len(types.PfxCreatorEpochPrune)+8 {
			return fmt.Errorf("malformed ceprune key")
		}
		epochs = append(epochs, int64(binary.BigEndian.Uint64(key[len(types.PfxCreatorEpochPrune):])))
		return nil
	}); err != nil {
		return err
	}
	for _, epoch := range epochs {
		if budget <= 0 {
			return nil
		}
		left, err := k.pruneEpochDetails(ctx, epoch, budget)
		if err != nil {
			return err
		}
		budget = left
	}
	return nil
}

func (k Keeper) pruneEpochDetails(ctx sdk.Context, epoch int64, budget int) (int, error) {
	deleted := 0
	if err := k.iterPrefixKeys(ctx, types.KeyEngagementEpochPrefix(epoch), budget, func(key, _ []byte) error {
		if err := k.storeDelete(ctx, key); err != nil {
			return err
		}
		deleted++
		return nil
	}); err != nil {
		return budget, err
	}
	budget -= deleted
	if budget <= 0 {
		return 0, nil
	}
	evcPfx := types.KeyEngagementCount(epoch, nil)
	// KeyEngagementCount with nil actor is "evc|"+epoch; actor is appended after.
	evcPfx = concatBytes([]byte(types.PfxEngagementCount), i64bytes(epoch))
	deleted = 0
	if err := k.iterPrefixKeys(ctx, evcPfx, budget, func(key, _ []byte) error {
		if err := k.storeDelete(ctx, key); err != nil {
			return err
		}
		deleted++
		return nil
	}); err != nil {
		return budget, err
	}
	budget -= deleted
	if budget > 0 {
		var ce types.CreatorEpoch
		found, err := k.getProto(ctx, types.KeyCreatorEpoch(epoch), &ce)
		if err != nil || !found {
			return budget, err
		}
		ce.PrunePending = false
		ce.PruneComplete = true
		ce.SettlementCursor = nil
		if err := k.setProto(ctx, types.KeyCreatorEpoch(epoch), &ce); err != nil {
			return budget, err
		}
		if err := k.storeDelete(ctx, types.KeyCreatorEpochPrune(epoch)); err != nil {
			return budget, err
		}
	}
	return budget, nil
}

func (k Keeper) burnCreatorPool(ctx sdk.Context, amount sdkmath.Int) error {
	if !amount.IsPositive() {
		return nil
	}
	coin := sdk.NewCoin(k.mintDenom(), amount)
	if err := haltFinalizeUnexpectedBankError(ctx, "creator_pool_to_core",
		k.bank.SendCoinsFromModuleToModule(ctx, types.CreatorPoolName, types.ModuleName, sdk.NewCoins(coin))); err != nil {
		return err
	}
	if err := k.burnCoinsTracked(ctx, amount); err != nil {
		return err
	}
	return k.addCreatorLiability(ctx, amount.Neg())
}

func (k Keeper) engagementValid(ctx sdk.Context, epoch int64, actor string, kind byte, target, value []byte) (bool, error) {
	targetHex := hex.EncodeToString(target)
	meta, ok, err := k.GetPostMetadata(ctx, targetHex)
	if err != nil {
		return false, err
	}
	if !ok {
		return false, haltFinalizeInvariantError(ctx, "creator_target_metadata_missing",
			fmt.Errorf("engagement target %s missing epoch=%d", targetHex, epoch))
	}
	if meta.Author == actor {
		return false, haltFinalizeInvariantError(ctx, "creator_self_target",
			fmt.Errorf("self-authored engagement actor=%s target=%s", actor, targetHex))
	}
	if meta.DeletedEpoch != 0 && meta.DeletedEpoch <= epoch {
		return false, nil
	}
	switch kind {
	case types.EngagementKindUpvote:
		dir, found, err := k.getVoteDir(ctx, actor, targetHex)
		if err != nil {
			return false, err
		}
		if !found || dir != 1 {
			return false, nil
		}
		return true, nil
	case types.EngagementKindDirectReply:
		if len(value) != 32 {
			return false, haltFinalizeInvariantError(ctx, "creator_reply_source_hash",
				fmt.Errorf("direct-reply value length %d", len(value)))
		}
		srcHex := hex.EncodeToString(value)
		src, ok, err := k.GetPostMetadata(ctx, srcHex)
		if err != nil {
			return false, err
		}
		if !ok {
			return false, haltFinalizeInvariantError(ctx, "creator_source_metadata_missing",
				fmt.Errorf("direct-reply source %s missing", srcHex))
		}
		if src.Author != actor || src.ParentHash != targetHex {
			return false, haltFinalizeInvariantError(ctx, "creator_source_mismatch",
				fmt.Errorf("source %s author/parent mismatch", srcHex))
		}
		if src.DeletedEpoch != 0 && src.DeletedEpoch <= epoch {
			return false, nil
		}
		return true, nil
	default:
		return false, fmt.Errorf("unknown engagement kind %d", kind)
	}
}

func parseEngagementKey(key []byte) (actor []byte, kind byte, target []byte, err error) {
	pfx := []byte(types.PfxEngagement)
	if len(key) != len(pfx)+8+engagementKeySuffixLen {
		return nil, 0, nil, fmt.Errorf("malformed ev key len=%d", len(key))
	}
	rest := key[len(pfx)+8:]
	actor = rest[:20]
	kind = rest[20]
	target = rest[21:]
	return actor, kind, target, nil
}

func concatBytes(parts ...[]byte) []byte {
	n := 0
	for _, p := range parts {
		n += len(p)
	}
	out := make([]byte, 0, n)
	for _, p := range parts {
		out = append(out, p...)
	}
	return out
}

func i64bytes(v int64) []byte {
	out := make([]byte, 8)
	binary.BigEndian.PutUint64(out, uint64(v))
	return out
}

func (k Keeper) ClearOpenDirectReply(ctx sdk.Context, author, parent, sourceHash string) error {
	clock, err := k.GetCreatorClock(ctx)
	if err != nil {
		return err
	}
	key := types.KeyReplyReserved(types.MustAcc(author), mustHash(parent))
	bz, err := k.storeGet(ctx, key)
	if err != nil || len(bz) == 0 {
		return err
	}
	if len(bz) != 40 {
		return fmt.Errorf("malformed rr value len=%d", len(bz))
	}
	storedEpoch := int64(binary.BigEndian.Uint64(bz[:8]))
	if storedEpoch != clock {
		return nil
	}
	if !bytes.Equal(bz[8:], mustHash(sourceHash)) {
		return nil
	}
	if err := k.storeDelete(ctx, key); err != nil {
		return err
	}
	if err := k.storeDelete(ctx, types.KeyEngagement(clock, types.MustAcc(author), types.EngagementKindDirectReply, mustHash(parent))); err != nil {
		return err
	}
	var ce types.CreatorEpoch
	ok, err := k.getProto(ctx, types.KeyCreatorEpoch(clock), &ce)
	if err != nil || !ok {
		return err
	}
	if ce.GrossRecords == 0 {
		return fmt.Errorf("gross_records underflow")
	}
	ce.GrossRecords--
	ctx.EventManager().EmitEvent(sdk.NewEvent("creator_engagement_removed",
		sdk.NewAttribute("kind", "direct_reply"),
		sdk.NewAttribute("actor", author),
		sdk.NewAttribute("target", parent),
		sdk.NewAttribute("source", sourceHash),
	))
	return k.setProto(ctx, types.KeyCreatorEpoch(clock), &ce)
}
