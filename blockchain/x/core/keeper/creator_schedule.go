package keeper

import (
	"encoding/binary"
	"fmt"

	sdk "github.com/cosmos/cosmos-sdk/types"

	"mirage/x/core/types"
)

const creatorScheduleSize = 24
const CreatorResetHeaderSize = 29

type CreatorReset struct {
	FromSeconds uint64
	ToSeconds   uint64
	SavedClock  int64
	PrefixIndex uint32
	PoolBurned  bool
	Cursor      []byte
}

func (k Keeper) GetCreatorSchedule(ctx sdk.Context) (types.CreatorSchedule, error) {
	bz, err := k.storeGet(ctx, []byte(types.PfxCreatorSchedule))
	if err != nil {
		return types.CreatorSchedule{}, err
	}
	if len(bz) == 0 {
		params := k.GetParams(ctx)
		return types.CreatorSchedule{EpochSeconds: params.CreatorEpochSeconds}, nil
	}
	if len(bz) != creatorScheduleSize {
		return types.CreatorSchedule{}, fmt.Errorf("corrupt creator schedule length %d", len(bz))
	}
	return types.CreatorSchedule{
		OriginEpoch:  int64(binary.BigEndian.Uint64(bz[0:8])),
		OriginUnix:   int64(binary.BigEndian.Uint64(bz[8:16])),
		EpochSeconds: binary.BigEndian.Uint64(bz[16:24]),
	}, nil
}

func (k Keeper) SetCreatorSchedule(ctx sdk.Context, sched types.CreatorSchedule) error {
	if sched.OriginEpoch < 0 || sched.OriginUnix < 0 {
		return fmt.Errorf("creator schedule origin must be non-negative")
	}
	if sched.EpochSeconds == 0 {
		return fmt.Errorf("creator schedule epoch seconds must be set")
	}
	bz := make([]byte, creatorScheduleSize)
	binary.BigEndian.PutUint64(bz[0:8], uint64(sched.OriginEpoch))
	binary.BigEndian.PutUint64(bz[8:16], uint64(sched.OriginUnix))
	binary.BigEndian.PutUint64(bz[16:24], sched.EpochSeconds)
	return k.storeSet(ctx, []byte(types.PfxCreatorSchedule), bz)
}

func (k Keeper) CreatorEpochAt(ctx sdk.Context, unix int64) (int64, error) {
	sched, err := k.GetCreatorSchedule(ctx)
	if err != nil {
		return 0, err
	}
	return sched.EpochAt(unix)
}

func (k Keeper) CreatorResetInProgress(ctx sdk.Context) (bool, error) {
	return k.storeHas(ctx, []byte(types.PfxCreatorReset))
}

func (k Keeper) GetCreatorReset(ctx sdk.Context) (CreatorReset, bool, error) {
	bz, err := k.storeGet(ctx, []byte(types.PfxCreatorReset))
	if err != nil {
		return CreatorReset{}, false, err
	}
	if len(bz) == 0 {
		return CreatorReset{}, false, nil
	}
	if len(bz) < CreatorResetHeaderSize {
		return CreatorReset{}, false, fmt.Errorf("corrupt creator reset length %d", len(bz))
	}
	reset := CreatorReset{
		FromSeconds: binary.BigEndian.Uint64(bz[0:8]),
		ToSeconds:   binary.BigEndian.Uint64(bz[8:16]),
		SavedClock:  int64(binary.BigEndian.Uint64(bz[16:24])),
		PrefixIndex: binary.BigEndian.Uint32(bz[24:28]),
		PoolBurned:  bz[28] != 0,
	}
	if len(bz) > CreatorResetHeaderSize {
		reset.Cursor = append([]byte(nil), bz[CreatorResetHeaderSize:]...)
	}
	return reset, true, nil
}

func (k Keeper) SetCreatorReset(ctx sdk.Context, reset CreatorReset) error {
	bz := make([]byte, CreatorResetHeaderSize+len(reset.Cursor))
	binary.BigEndian.PutUint64(bz[0:8], reset.FromSeconds)
	binary.BigEndian.PutUint64(bz[8:16], reset.ToSeconds)
	binary.BigEndian.PutUint64(bz[16:24], uint64(reset.SavedClock))
	binary.BigEndian.PutUint32(bz[24:28], reset.PrefixIndex)
	if reset.PoolBurned {
		bz[28] = 1
	}
	copy(bz[CreatorResetHeaderSize:], reset.Cursor)
	return k.storeSet(ctx, []byte(types.PfxCreatorReset), bz)
}

func (k Keeper) ClearCreatorReset(ctx sdk.Context) error {
	return k.storeDelete(ctx, []byte(types.PfxCreatorReset))
}

func (k Keeper) ApplyCreatorEpochSeconds(ctx sdk.Context, newSeconds uint64) error {
	if newSeconds == 0 {
		return fmt.Errorf("creator_epoch_seconds must be set")
	}
	inProgress, err := k.CreatorResetInProgress(ctx)
	if err != nil {
		return err
	}
	if inProgress {
		return fmt.Errorf("creator_epoch_seconds cannot change while a reset is in progress")
	}
	hasState, err := k.HasCreatorRewardState(ctx)
	if err != nil {
		return err
	}
	clock, err := k.GetCreatorClock(ctx)
	if err != nil {
		return err
	}
	current, err := k.GetCreatorSchedule(ctx)
	if err != nil {
		return err
	}
	if hasState {
		ctx.Logger().Info("creator epoch reset scheduled",
			"from_seconds", current.EpochSeconds,
			"to_seconds", newSeconds,
			"saved_clock", clock,
			"height", ctx.BlockHeight())
		if err := k.SetCreatorReset(ctx, CreatorReset{
			FromSeconds: current.EpochSeconds,
			ToSeconds:   newSeconds,
			SavedClock:  clock,
		}); err != nil {
			return err
		}
		ctx.EventManager().EmitEvent(sdk.NewEvent("creator_epoch_reset_scheduled",
			sdk.NewAttribute("from_seconds", fmt.Sprintf("%d", current.EpochSeconds)),
			sdk.NewAttribute("to_seconds", fmt.Sprintf("%d", newSeconds)),
			sdk.NewAttribute("saved_clock", fmt.Sprintf("%d", clock)),
		))
		return nil
	}
	return k.activateCreatorSchedule(ctx, newSeconds, clock, ctx.BlockTime().Unix(), false)
}

func (k Keeper) activateCreatorSchedule(ctx sdk.Context, newSeconds uint64, savedClock, now int64, afterReset bool) error {
	sched := types.CreatorSchedule{EpochSeconds: newSeconds}
	var clock int64
	if savedClock > 0 {
		originEpoch := savedClock
		if afterReset {
			next, err := types.CheckedAddInt64(savedClock, 1)
			if err != nil {
				return err
			}
			originEpoch = next
		}
		sched.OriginEpoch = originEpoch
		sched.OriginUnix = now
		clock = originEpoch
	} else {
		epoch, err := types.CreatorEpochFromUnix(now, newSeconds)
		if err != nil {
			return err
		}
		clock = epoch
	}
	if err := k.SetCreatorSchedule(ctx, sched); err != nil {
		return err
	}
	if err := k.SetCreatorClock(ctx, clock); err != nil {
		return err
	}
	ctx.Logger().Info("creator schedule activated",
		"origin_epoch", sched.OriginEpoch,
		"origin_unix", sched.OriginUnix,
		"epoch_seconds", sched.EpochSeconds,
		"clock", clock,
		"after_reset", afterReset,
		"height", ctx.BlockHeight())
	ctx.EventManager().EmitEvent(sdk.NewEvent("creator_epoch_schedule_updated",
		sdk.NewAttribute("origin_epoch", fmt.Sprintf("%d", sched.OriginEpoch)),
		sdk.NewAttribute("origin_unix", fmt.Sprintf("%d", sched.OriginUnix)),
		sdk.NewAttribute("epoch_seconds", fmt.Sprintf("%d", sched.EpochSeconds)),
		sdk.NewAttribute("clock", fmt.Sprintf("%d", clock)),
	))
	return nil
}
