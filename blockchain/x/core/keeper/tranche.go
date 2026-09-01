package keeper

import (
	"fmt"

	sdkmath "cosmossdk.io/math"
	sdk "github.com/cosmos/cosmos-sdk/types"
	sdkerrors "github.com/cosmos/cosmos-sdk/types/errors"
	authtypes "github.com/cosmos/cosmos-sdk/x/auth/types"

	"mirage/x/core/types"
)

func (k Keeper) CreateTranche(ctx sdk.Context, payer, recipient string, source types.SubscriptionTrancheSource, periodCount uint32, txhash string) error {
	if resetting, err := k.CreatorResetInProgress(ctx); err != nil {
		return err
	} else if resetting {
		return fmt.Errorf("creator reward reset in progress")
	}
	params := k.GetParams(ctx)
	if periodCount < 1 || uint64(periodCount) > params.MaxSubscriptionPeriodsPerPurchase {
		return fmt.Errorf("period_count must be in [1,%d]", params.MaxSubscriptionPeriodsPerPurchase)
	}
	rec, found, err := k.loadProfile(ctx, recipient)
	if err != nil {
		return err
	}
	if !found {
		return fmt.Errorf("recipient profile not found")
	}
	tier := params.GetTierConfig(types.LevelSubscriber)
	if tier == nil {
		return fmt.Errorf("subscriber tier missing")
	}
	onePeriod, err := types.CheckedMulUint64(params.SubscriptionPeriod, 60)
	if err != nil {
		return err
	}
	duration, err := types.CheckedMulUint64(onePeriod, uint64(periodCount))
	if err != nil {
		return err
	}
	now := ctx.BlockTime().Unix()
	start := now
	if rec.SubscriptionExpiry > start {
		start = rec.SubscriptionExpiry
	}
	end, err := types.CheckedAddInt64(start, int64(duration))
	if err != nil {
		return err
	}
	fee, err := types.CheckedMulUint64(tier.PeriodFee, uint64(periodCount))
	if err != nil {
		return err
	}
	burnAmt, creatorAmt, err := types.SplitCreatorFee(fee, params.SubscriptionCreatorBps)
	if err != nil {
		return err
	}
	if err := k.BurnFromAccount(ctx, payer, burnAmt); err != nil {
		return err
	}
	if creatorAmt > 0 {
		if err := k.sendToCreatorPool(ctx, payer, creatorAmt); err != nil {
			return err
		}
		if err := k.addCreatorLiability(ctx, sdkmath.NewIntFromUint64(creatorAmt)); err != nil {
			return err
		}
	}
	wasPaid := rec.EffectivePaid
	if rec.SubscriptionExpiry > 0 {
		if err := k.RemoveSubscription(ctx, recipient, rec.SubscriptionExpiry); err != nil {
			return err
		}
	}
	rec.SubscriptionExpiry = end
	if source == types.SubscriptionTrancheSource_SUBSCRIPTION_TRANCHE_SOURCE_SELF_PURCHASE {
		rec.AutoRenew = true
	}
	if err := k.saveProfile(ctx, rec); err != nil {
		return err
	}
	if !wasPaid {
		if err := k.TransitionPaidState(ctx, recipient, true); err != nil {
			return err
		}
	}
	if err := k.SetSubscription(ctx, recipient, types.LevelSubscriber, end); err != nil {
		return err
	}
	if err := k.ReplaceSubscriptionRenewalSchedule(ctx, recipient); err != nil {
		return err
	}
	id, _, err := k.getU64Key(ctx, []byte(types.PfxTrancheSeq))
	if err != nil {
		return err
	}
	id++
	if err := k.setU64Key(ctx, []byte(types.PfxTrancheSeq), id); err != nil {
		return err
	}
	tr := &types.SubscriptionTranche{
		Id:            id,
		Payer:         payer,
		Recipient:     recipient,
		Source:        source,
		StartTime:     start,
		EndTime:       end,
		PeriodCount:   periodCount,
		TotalFee:      fmt.Sprintf("%d", fee),
		BurnAmount:    fmt.Sprintf("%d", burnAmt),
		CreatorAmount: fmt.Sprintf("%d", creatorAmt),
		CreatorBps:    params.SubscriptionCreatorBps,
		Period:        params.SubscriptionPeriod,
		CreatedHeight: ctx.BlockHeight(),
		Txhash:        txhash,
	}
	if err := k.setProto(ctx, types.KeyTranche(id), tr); err != nil {
		return err
	}
	if err := k.storeSet(ctx, types.KeyTranchePayer(payer, id), []byte{1}); err != nil {
		return err
	}
	if err := k.storeSet(ctx, types.KeyTrancheRecipient(recipient, id), []byte{1}); err != nil {
		return err
	}
	sched, err := k.GetCreatorSchedule(ctx)
	if err != nil {
		return err
	}
	first, err := sched.EpochAt(start)
	if err != nil {
		return err
	}
	last, err := sched.EpochAt(end - 1)
	if err != nil {
		return err
	}
	remaining := sdkmath.NewIntFromUint64(creatorAmt)
	dur := sdkmath.NewIntFromUint64(duration)
	for epoch := first; epoch <= last; epoch++ {
		epochStart, err := sched.EpochStart(epoch)
		if err != nil {
			return err
		}
		epochEnd, err := sched.EpochEnd(epoch)
		if err != nil {
			return err
		}
		lo := start
		if epochStart > lo {
			lo = epochStart
		}
		hi := end
		if epochEnd < hi {
			hi = epochEnd
		}
		overlap := hi - lo
		var amount sdkmath.Int
		if epoch == last {
			amount = remaining
			remaining = sdkmath.ZeroInt()
		} else {
			amount = sdkmath.NewIntFromUint64(creatorAmt).Mul(sdkmath.NewInt(overlap)).Quo(dur)
			remaining = remaining.Sub(amount)
		}
		if amount.IsPositive() {
			if err := k.addEpochPool(ctx, epoch, amount); err != nil {
				return err
			}
		}
	}
	if !remaining.IsZero() && last >= first {
		return fmt.Errorf("tranche schedule leftover %s", remaining.String())
	}
	ctx.EventManager().EmitEvent(sdk.NewEvent("subscription_tranche_created",
		sdk.NewAttribute("payer", payer),
		sdk.NewAttribute("recipient", recipient),
		sdk.NewAttribute("source", fmt.Sprintf("%d", source)),
		sdk.NewAttribute("period_count", fmt.Sprintf("%d", periodCount)),
		sdk.NewAttribute("total_fee", tr.TotalFee),
		sdk.NewAttribute("burn_amount", tr.BurnAmount),
		sdk.NewAttribute("creator_amount", tr.CreatorAmount),
		sdk.NewAttribute("start", fmt.Sprintf("%d", start)),
		sdk.NewAttribute("end", fmt.Sprintf("%d", end)),
	))
	return nil
}

func (k Keeper) sendToCreatorPool(ctx sdk.Context, payer string, amount uint64) error {
	acc, err := sdk.AccAddressFromBech32(payer)
	if err != nil {
		return err
	}
	coin := sdk.NewCoin(k.mintDenom(), sdkmath.NewIntFromUint64(amount))
	coins := sdk.NewCoins(coin)
	if !k.bankSpendableCoins(ctx, acc).IsAllGTE(coins) {
		return sdkerrors.ErrInsufficientFunds.Wrapf("spendable balance is smaller than %s", coins)
	}
	return haltFinalizeUnexpectedBankError(ctx, "send_creator_pool",
		k.bank.SendCoinsFromAccountToModule(ctx, acc, types.CreatorPoolName, coins))
}

func (k Keeper) addCreatorLiability(ctx sdk.Context, delta sdkmath.Int) error {
	cur, err := k.GetCreatorLiability(ctx)
	if err != nil {
		return err
	}
	next := cur.Add(delta)
	if next.IsNegative() {
		return fmt.Errorf("creator liability underflow")
	}
	return k.storeSet(ctx, []byte(types.PfxCreatorLiability), []byte(next.String()))
}

func (k Keeper) GetCreatorLiability(ctx sdk.Context) (sdkmath.Int, error) {
	bz, err := k.storeGet(ctx, []byte(types.PfxCreatorLiability))
	if err != nil {
		return sdkmath.Int{}, err
	}
	if len(bz) == 0 {
		return sdkmath.ZeroInt(), nil
	}
	v, ok := sdkmath.NewIntFromString(string(bz))
	if !ok {
		return sdkmath.Int{}, fmt.Errorf("corrupt creator liability")
	}
	return v, nil
}

func (k Keeper) GetCreatorActivationSurplus(ctx sdk.Context) (sdkmath.Int, error) {
	bz, err := k.storeGet(ctx, []byte(types.PfxCreatorSurplus))
	if err != nil {
		return sdkmath.Int{}, err
	}
	if len(bz) == 0 {
		return sdkmath.ZeroInt(), nil
	}
	v, ok := sdkmath.NewIntFromString(string(bz))
	if !ok {
		return sdkmath.Int{}, fmt.Errorf("corrupt creator surplus")
	}
	return v, nil
}

func (k Keeper) SetCreatorActivationSurplus(ctx sdk.Context, v sdkmath.Int) error {
	return k.storeSet(ctx, []byte(types.PfxCreatorSurplus), []byte(v.String()))
}

func (k Keeper) CreatorPoolBalance(ctx sdk.Context) sdkmath.Int {
	addr := authtypes.NewModuleAddress(types.CreatorPoolName)
	return k.GetBalance(ctx, addr.String(), k.mintDenom())
}

func (k Keeper) addEpochPool(ctx sdk.Context, epoch int64, amount sdkmath.Int) error {
	var ce types.CreatorEpoch
	found, err := k.getProto(ctx, types.KeyCreatorEpoch(epoch), &ce)
	if err != nil {
		return err
	}
	if !found {
		ce = types.CreatorEpoch{
			EpochId:        epoch,
			Pool:           "0",
			EngagerSlice:   "0",
			AllocatedTotal: "0",
			ClaimedTotal:   "0",
		}
	}
	cur, err := k.parseInt(ce.Pool)
	if err != nil {
		return err
	}
	ce.Pool = cur.Add(amount).String()
	if err := k.setProto(ctx, types.KeyCreatorEpoch(epoch), &ce); err != nil {
		return err
	}
	return k.storeSet(ctx, types.KeyCreatorEpochOpen(epoch), []byte{1})
}

func (k Keeper) GetCreatorClock(ctx sdk.Context) (int64, error) {
	v, found, err := k.getU64Key(ctx, []byte(types.PfxCreatorClock))
	if err != nil {
		return 0, err
	}
	if !found {
		return 0, nil
	}
	return int64(v), nil
}

func (k Keeper) SetCreatorClock(ctx sdk.Context, epoch int64) error {
	return k.setU64Key(ctx, []byte(types.PfxCreatorClock), uint64(epoch))
}
