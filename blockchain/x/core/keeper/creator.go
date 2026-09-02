package keeper

import (
	"fmt"

	sdkmath "cosmossdk.io/math"
	storetypes "github.com/cosmos/cosmos-sdk/store/v2/types"
	sdk "github.com/cosmos/cosmos-sdk/types"

	"mirage/x/core/types"
)

const MaxCreatorAccrualQueryLimit = 1000

func (k Keeper) GetCreatorEpochAccrualsPaginated(
	ctx sdk.Context,
	epoch int64,
	pageKey []byte,
	limit uint64,
) (accruals []*types.CreatorAccrual, nextKey []byte, err error) {
	if limit == 0 || limit > MaxCreatorAccrualQueryLimit {
		limit = MaxCreatorAccrualQueryLimit
	}
	prefix := types.KeyEpochCreatorAccrualPrefix(epoch)
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
	for ; it.Valid() && uint64(len(accruals)) < limit; it.Next() {
		var accrual types.CreatorAccrual
		if err := k.cdc.Unmarshal(it.Value(), &accrual); err != nil {
			return nil, nil, err
		}
		accrualCopy := accrual
		accruals = append(accruals, &accrualCopy)
	}
	if err := it.Error(); err != nil {
		return nil, nil, err
	}
	if it.Valid() {
		fullKey := it.Key()
		nextKey = append([]byte(nil), fullKey[len(prefix):]...)
	}
	return accruals, nextKey, nil
}

func (k Keeper) RecordUpvoteEngagement(ctx sdk.Context, voter, target string, direction int32) error {
	if err := k.setVoteDir(ctx, voter, target, direction); err != nil {
		return err
	}
	if direction != 1 {
		return k.clearOpenUpvote(ctx, voter, target)
	}
	if has, err := k.storeHas(ctx, types.KeyUpvoteReserved(types.MustAcc(voter), mustHash(target))); err != nil {
		return err
	} else if has {
		return nil
	}
	paid, err := k.IsEffectivePaid(ctx, voter)
	if err != nil || !paid {
		return err
	}
	meta, ok, err := k.GetPostMetadata(ctx, target)
	if err != nil || !ok || meta.Author == voter || meta.DeletedHeight != 0 {
		return err
	}
	clock, err := k.GetCreatorClock(ctx)
	if err != nil {
		return err
	}
	ce, err := k.ensureOpenEpoch(ctx, clock)
	if err != nil {
		return err
	}
	params := k.GetParams(ctx)
	if ce.GrossRecords >= params.MaxCreatorEngagementsPerEpoch {
		return nil
	}
	if err := k.setU64Key(ctx, types.KeyUpvoteReserved(types.MustAcc(voter), mustHash(target)), uint64(clock)); err != nil {
		return err
	}
	if err := k.storeSet(ctx, types.KeyEngagement(clock, types.MustAcc(voter), types.EngagementKindUpvote, mustHash(target)), []byte{}); err != nil {
		return err
	}
	ce.GrossRecords++
	if err := k.setProto(ctx, types.KeyCreatorEpoch(clock), ce); err != nil {
		return err
	}
	ctx.EventManager().EmitEvent(sdk.NewEvent("creator_engagement_eligible",
		sdk.NewAttribute("kind", "upvote"),
		sdk.NewAttribute("actor", voter),
		sdk.NewAttribute("target", target),
	))
	return nil
}

func (k Keeper) RecordDirectReplyEngagement(ctx sdk.Context, commenter, parent, sourceHash string) error {
	parentH := mustHash(parent)
	key := types.KeyReplyReserved(types.MustAcc(commenter), parentH)
	if has, err := k.storeHas(ctx, key); err != nil {
		return err
	} else if has {
		return nil
	}
	paid, err := k.IsEffectivePaid(ctx, commenter)
	if err != nil || !paid {
		return err
	}
	meta, ok, err := k.GetPostMetadata(ctx, parent)
	if err != nil || !ok || meta.Author == commenter || meta.DeletedHeight != 0 {
		return err
	}
	clock, err := k.GetCreatorClock(ctx)
	if err != nil {
		return err
	}
	ce, err := k.ensureOpenEpoch(ctx, clock)
	if err != nil {
		return err
	}
	params := k.GetParams(ctx)
	if ce.GrossRecords >= params.MaxCreatorEngagementsPerEpoch {
		return nil
	}
	src := mustHash(sourceHash)
	val := append(putU64(uint64(clock)), src...)
	if err := k.storeSet(ctx, key, val); err != nil {
		return err
	}
	if err := k.storeSet(ctx, types.KeyEngagement(clock, types.MustAcc(commenter), types.EngagementKindDirectReply, parentH), src); err != nil {
		return err
	}
	ce.GrossRecords++
	if err := k.setProto(ctx, types.KeyCreatorEpoch(clock), ce); err != nil {
		return err
	}
	ctx.EventManager().EmitEvent(sdk.NewEvent("creator_engagement_eligible",
		sdk.NewAttribute("kind", "direct_reply"),
		sdk.NewAttribute("actor", commenter),
		sdk.NewAttribute("target", parent),
		sdk.NewAttribute("source", sourceHash),
	))
	return nil
}

// newCreatorEpoch stamps an epoch with the wall-clock window it covers on the
// grid live right now. Recording it here rather than deriving it later is what
// lets a settled epoch keep reporting honest times after governance changes
// creator_epoch_seconds and renumbers the grid underneath it.
func (k Keeper) newCreatorEpoch(ctx sdk.Context, epoch int64) (types.CreatorEpoch, error) {
	sched, err := k.GetCreatorSchedule(ctx)
	if err != nil {
		return types.CreatorEpoch{}, err
	}
	start, err := sched.EpochStart(epoch)
	if err != nil {
		return types.CreatorEpoch{}, err
	}
	end, err := sched.EpochEnd(epoch)
	if err != nil {
		return types.CreatorEpoch{}, err
	}
	return types.CreatorEpoch{
		EpochId:        epoch,
		Pool:           "0",
		EngagerSlice:   "0",
		AllocatedTotal: "0",
		ClaimedTotal:   "0",
		StartUnix:      start,
		EndUnix:        end,
	}, nil
}

func (k Keeper) ensureOpenEpoch(ctx sdk.Context, epoch int64) (*types.CreatorEpoch, error) {
	var ce types.CreatorEpoch
	found, err := k.getProto(ctx, types.KeyCreatorEpoch(epoch), &ce)
	if err != nil {
		return nil, err
	}
	if !found {
		ce, err = k.newCreatorEpoch(ctx, epoch)
		if err != nil {
			return nil, err
		}
	}
	if err := k.storeSet(ctx, types.KeyCreatorEpochOpen(epoch), []byte{1}); err != nil {
		return nil, err
	}
	return &ce, nil
}

func (k Keeper) setVoteDir(ctx sdk.Context, voter, target string, direction int32) error {
	return k.setU64Key(ctx, types.KeyVoteDir(types.MustAcc(voter), mustHash(target)), uint64(uint32(direction)))
}

func (k Keeper) getVoteDir(ctx sdk.Context, voter, target string) (int32, bool, error) {
	v, found, err := k.getU64Key(ctx, types.KeyVoteDir(types.MustAcc(voter), mustHash(target)))
	return int32(v), found, err
}

func (k Keeper) clearOpenUpvote(ctx sdk.Context, voter, target string) error {
	clock, err := k.GetCreatorClock(ctx)
	if err != nil {
		return err
	}
	key := types.KeyUpvoteReserved(types.MustAcc(voter), mustHash(target))
	stored, found, err := k.getU64Key(ctx, key)
	if err != nil || !found {
		return err
	}
	if int64(stored) != clock {
		return nil
	}
	if err := k.storeDelete(ctx, key); err != nil {
		return err
	}
	if err := k.storeDelete(ctx, types.KeyEngagement(clock, types.MustAcc(voter), types.EngagementKindUpvote, mustHash(target))); err != nil {
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
		sdk.NewAttribute("kind", "upvote"),
		sdk.NewAttribute("actor", voter),
		sdk.NewAttribute("target", target),
	))
	return k.setProto(ctx, types.KeyCreatorEpoch(clock), &ce)
}

func mustHash(h string) []byte {
	b, err := types.HashBytes(h)
	if err != nil {
		panic(err)
	}
	return b
}

func (k Keeper) ClaimCreatorRewards(ctx sdk.Context, creator string, epochs []int64) error {
	params := k.GetParams(ctx)
	if len(epochs) < 1 || uint64(len(epochs)) > params.MaxCreatorClaimEpochs {
		return fmt.Errorf("epoch count must be in [1,%d]", params.MaxCreatorClaimEpochs)
	}
	for i := 1; i < len(epochs); i++ {
		if epochs[i] <= epochs[i-1] {
			return fmt.Errorf("epoch ids must be strictly increasing")
		}
	}
	now := ctx.BlockTime().Unix()
	sum := sdkmath.ZeroInt()
	type item struct {
		epoch int64
		acc   types.CreatorAccrual
	}
	var items []item
	for _, ep := range epochs {
		var acc types.CreatorAccrual
		found, err := k.getProto(ctx, types.KeyEpochCreatorAccrual(ep, types.MustAcc(creator)), &acc)
		if err != nil {
			return err
		}
		if !found {
			return fmt.Errorf("no accrual for epoch %d", ep)
		}
		var ce types.CreatorEpoch
		ok, err := k.getProto(ctx, types.KeyCreatorEpoch(ep), &ce)
		if err != nil || !ok {
			return fmt.Errorf("epoch %d missing", ep)
		}
		if ce.Status != types.CreatorEpochStatus_CREATOR_EPOCH_STATUS_CLAIMABLE {
			return fmt.Errorf("epoch %d is not claimable", ep)
		}
		if now >= ce.ClaimDeadlineUnix {
			return fmt.Errorf("epoch %d claim window closed", ep)
		}
		if has, err := k.storeHas(ctx, types.KeyEpochClaim(ep, types.MustAcc(creator))); err != nil {
			return err
		} else if has {
			return fmt.Errorf("epoch %d already claimed", ep)
		}
		earned, err := k.parseInt(acc.Amount)
		if err != nil {
			return err
		}
		claimed, err := k.parseInt(acc.ClaimedAmount)
		if err != nil {
			return err
		}
		if acc.Claimed {
			return fmt.Errorf("epoch %d already claimed", ep)
		}
		unclaimed := earned.Sub(claimed)
		if !unclaimed.IsPositive() {
			return fmt.Errorf("epoch %d has no unclaimed amount", ep)
		}
		sum = sum.Add(unclaimed)
		items = append(items, item{epoch: ep, acc: acc})
	}
	for i := range items {
		it := &items[i]
		earned, _ := k.parseInt(it.acc.Amount)
		it.acc.ClaimedAmount = earned.String()
		it.acc.Claimed = true
		it.acc.ClaimedHeight = ctx.BlockHeight()
		it.acc.ClaimedTxhash = fmt.Sprintf("%x", ctx.TxBytes())
		if err := k.setProto(ctx, types.KeyEpochCreatorAccrual(it.epoch, types.MustAcc(creator)), &it.acc); err != nil {
			return err
		}
		if err := k.storeSet(ctx, types.KeyEpochClaim(it.epoch, types.MustAcc(creator)), []byte{1}); err != nil {
			return err
		}
		var ce types.CreatorEpoch
		if _, err := k.getProto(ctx, types.KeyCreatorEpoch(it.epoch), &ce); err != nil {
			return err
		}
		claimedTotal, err := k.parseInt(ce.ClaimedTotal)
		if err != nil {
			return err
		}
		ce.ClaimedTotal = claimedTotal.Add(earned).String()
		if err := k.setProto(ctx, types.KeyCreatorEpoch(it.epoch), &ce); err != nil {
			return err
		}
	}
	if err := k.addCreatorLiability(ctx, sum.Neg()); err != nil {
		return err
	}
	accAddr, err := sdk.AccAddressFromBech32(creator)
	if err != nil {
		return err
	}
	coin := sdk.NewCoin(k.mintDenom(), sum)
	if err := haltFinalizeUnexpectedBankError(ctx, "claim_creator_rewards",
		k.bank.SendCoinsFromModuleToAccount(ctx, types.CreatorPoolName, accAddr, sdk.NewCoins(coin))); err != nil {
		return err
	}
	ctx.EventManager().EmitEvent(sdk.NewEvent("creator_rewards_claimed",
		sdk.NewAttribute("creator", creator),
		sdk.NewAttribute("amount", sum.String()),
	))
	return nil
}
