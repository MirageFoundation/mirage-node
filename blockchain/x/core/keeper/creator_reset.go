package keeper

import (
	"fmt"

	sdkmath "cosmossdk.io/math"
	sdk "github.com/cosmos/cosmos-sdk/types"
	authtypes "github.com/cosmos/cosmos-sdk/x/auth/types"

	"mirage/x/core/types"
)

func (k Keeper) processCreatorReset(ctx sdk.Context, params types.Params) (bool, error) {
	reset, found, err := k.GetCreatorReset(ctx)
	if err != nil {
		return false, err
	}
	if !found {
		return false, nil
	}

	if !reset.PoolBurned {
		burned, err := k.burnCreatorPoolBalance(ctx)
		if err != nil {
			return true, err
		}
		if err := k.storeSet(ctx, []byte(types.PfxCreatorLiability), []byte("0")); err != nil {
			return true, err
		}
		if err := k.SetCreatorActivationSurplus(ctx, sdkmath.ZeroInt()); err != nil {
			return true, err
		}
		reset.PoolBurned = true
		if err := k.SetCreatorReset(ctx, reset); err != nil {
			return true, err
		}
		ctx.Logger().Info("creator epoch reset started",
			"from_seconds", reset.FromSeconds,
			"to_seconds", reset.ToSeconds,
			"burned", burned.String(),
			"saved_clock", reset.SavedClock,
			"height", ctx.BlockHeight())
		ctx.EventManager().EmitEvent(sdk.NewEvent("creator_epoch_reset_started",
			sdk.NewAttribute("from_seconds", fmt.Sprintf("%d", reset.FromSeconds)),
			sdk.NewAttribute("to_seconds", fmt.Sprintf("%d", reset.ToSeconds)),
			sdk.NewAttribute("burned", burned.String()),
			sdk.NewAttribute("saved_clock", fmt.Sprintf("%d", reset.SavedClock)),
		))
	}

	budget := int(params.CreatorPruneKeysPerBlock)
	if budget < 1 {
		return true, fmt.Errorf("creator_prune_keys_per_block must be positive")
	}
	prefixes := types.CreatorResetPrefixes()
	deletedTotal := 0
	for reset.PrefixIndex < uint32(len(prefixes)) && budget > 0 {
		prefix := []byte(prefixes[reset.PrefixIndex])
		deleted, last, more, err := k.deletePrefixBounded(ctx, prefix, reset.Cursor, budget)
		if err != nil {
			return true, err
		}
		deletedTotal += deleted
		budget -= deleted
		if more {
			reset.Cursor = last
			if err := k.SetCreatorReset(ctx, reset); err != nil {
				return true, err
			}
			ctx.Logger().Info("creator epoch reset progress",
				"prefix_index", reset.PrefixIndex,
				"deleted", deletedTotal,
				"height", ctx.BlockHeight())
			ctx.EventManager().EmitEvent(sdk.NewEvent("creator_epoch_reset_progress",
				sdk.NewAttribute("prefix_index", fmt.Sprintf("%d", reset.PrefixIndex)),
				sdk.NewAttribute("deleted", fmt.Sprintf("%d", deletedTotal)),
			))
			return true, nil
		}
		reset.PrefixIndex++
		reset.Cursor = nil
	}
	if reset.PrefixIndex < uint32(len(prefixes)) {
		if err := k.SetCreatorReset(ctx, reset); err != nil {
			return true, err
		}
		ctx.EventManager().EmitEvent(sdk.NewEvent("creator_epoch_reset_progress",
			sdk.NewAttribute("prefix_index", fmt.Sprintf("%d", reset.PrefixIndex)),
			sdk.NewAttribute("deleted", fmt.Sprintf("%d", deletedTotal)),
		))
		return true, nil
	}

	if reset.ToSeconds != params.CreatorEpochSeconds {
		return true, fmt.Errorf(
			"creator reset to_seconds=%d disagrees with params.creator_epoch_seconds=%d",
			reset.ToSeconds,
			params.CreatorEpochSeconds,
		)
	}
	if err := k.ClearCreatorReset(ctx); err != nil {
		return true, err
	}
	if err := k.activateCreatorSchedule(ctx, reset.ToSeconds, reset.SavedClock, ctx.BlockTime().Unix(), true); err != nil {
		return true, err
	}
	sched, err := k.GetCreatorSchedule(ctx)
	if err != nil {
		return true, err
	}
	clock, err := k.GetCreatorClock(ctx)
	if err != nil {
		return true, err
	}
	ctx.Logger().Info("creator epoch reset completed",
		"origin_epoch", sched.OriginEpoch,
		"origin_unix", sched.OriginUnix,
		"epoch_seconds", sched.EpochSeconds,
		"clock", clock,
		"deleted", deletedTotal,
		"height", ctx.BlockHeight())
	ctx.EventManager().EmitEvent(sdk.NewEvent("creator_epoch_reset_completed",
		sdk.NewAttribute("origin_epoch", fmt.Sprintf("%d", sched.OriginEpoch)),
		sdk.NewAttribute("origin_unix", fmt.Sprintf("%d", sched.OriginUnix)),
		sdk.NewAttribute("epoch_seconds", fmt.Sprintf("%d", sched.EpochSeconds)),
		sdk.NewAttribute("clock", fmt.Sprintf("%d", clock)),
		sdk.NewAttribute("from_seconds", fmt.Sprintf("%d", reset.FromSeconds)),
		sdk.NewAttribute("to_seconds", fmt.Sprintf("%d", reset.ToSeconds)),
	))
	return false, nil
}

func (k Keeper) burnCreatorPoolBalance(ctx sdk.Context) (sdkmath.Int, error) {
	addr := authtypes.NewModuleAddress(types.CreatorPoolName)
	bal := k.GetBalance(ctx, addr.String(), k.mintDenom())
	if !bal.IsPositive() {
		return sdkmath.ZeroInt(), nil
	}
	coin := sdk.NewCoin(k.mintDenom(), bal)
	if err := haltFinalizeUnexpectedBankError(ctx, "creator_reset_pool_to_core",
		k.bank.SendCoinsFromModuleToModule(ctx, types.CreatorPoolName, types.ModuleName, sdk.NewCoins(coin))); err != nil {
		return sdkmath.Int{}, err
	}
	if err := k.burnCoinsTracked(ctx, bal); err != nil {
		return sdkmath.Int{}, err
	}
	return bal, nil
}

func (k Keeper) deletePrefixBounded(ctx sdk.Context, prefix, cursor []byte, budget int) (deleted int, last []byte, more bool, err error) {
	start := prefix
	exclusive := false
	if len(cursor) > 0 {
		start = cursor
		has, hasErr := k.storeHas(ctx, cursor)
		if hasErr != nil {
			return 0, nil, false, hasErr
		}
		exclusive = has
	}
	var keys [][]byte
	if err := k.iterPrefixFrom(ctx, prefix, start, exclusive, budget+1, func(key, _ []byte) error {
		if len(keys) >= budget {
			more = true
			return nil
		}
		keys = append(keys, append([]byte(nil), key...))
		return nil
	}); err != nil {
		return 0, nil, false, err
	}
	for _, key := range keys {
		if err := k.storeDelete(ctx, key); err != nil {
			return deleted, last, false, err
		}
		deleted++
		last = key
	}
	return deleted, last, more, nil
}
