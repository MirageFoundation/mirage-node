package keeper

import (
	"encoding/binary"
	"fmt"

	sdk "github.com/cosmos/cosmos-sdk/types"

	"mirage/x/core/types"
)

const creatorScheduleSize = 24

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

// ApplyCreatorEpochSeconds re-grids creator epochs without destroying anything.
//
// This used to burn the outstanding creator pool and wipe every engagement,
// accrual, claim and tranche, because pools were pre-computed per epoch id and
// a new interval made those ids meaningless. Nothing is keyed that way any
// more: the fee accumulator runs on wall-clock time and claim windows close at
// a wall-clock instant, so both survive the switch untouched.
//
// The only care needed is the epoch in flight. It gets whatever the stream owes
// it up to this instant and is closed on the old grid, then the new grid starts
// here. Epoch ids stay monotonic across the change so settled epochs, accruals
// and claims keep working.
func (k Keeper) ApplyCreatorEpochSeconds(ctx sdk.Context, newSeconds uint64) error {
	if newSeconds == 0 {
		return fmt.Errorf("creator_epoch_seconds must be set")
	}
	now := ctx.BlockTime().Unix()
	clock, err := k.GetCreatorClock(ctx)
	if err != nil {
		return err
	}
	current, err := k.GetCreatorSchedule(ctx)
	if err != nil {
		return err
	}
	if current.EpochSeconds == newSeconds {
		return nil
	}
	if clock > 0 {
		if err := k.settleCreatorEpochInFlight(ctx, clock, now); err != nil {
			return err
		}
	}
	ctx.Logger().Info("creator epoch interval changing",
		"from_seconds", current.EpochSeconds,
		"to_seconds", newSeconds,
		"clock", clock,
		"height", ctx.BlockHeight())
	return k.activateCreatorSchedule(ctx, newSeconds, clock, now)
}

// settleCreatorEpochInFlight pays the partially elapsed epoch what the stream
// produced during it and closes it on the outgoing grid, so no money is
// stranded between the two grids.
func (k Keeper) settleCreatorEpochInFlight(ctx sdk.Context, epoch, now int64) error {
	params := k.GetParams(ctx)
	amount, complete, err := k.DrawCreatorStream(ctx, now, int(params.CreatorSettlementRecordsPerBlock))
	if err != nil {
		return err
	}
	if !complete {
		return fmt.Errorf("creator stream has too many pending boundaries to change the epoch interval this block")
	}
	if amount.IsPositive() {
		if err := k.addEpochPool(ctx, epoch, amount); err != nil {
			return err
		}
	}
	return k.closeCreatorEpoch(ctx, epoch)
}

func (k Keeper) activateCreatorSchedule(ctx sdk.Context, newSeconds uint64, savedClock, now int64) error {
	sched := types.CreatorSchedule{EpochSeconds: newSeconds}
	var clock int64
	if savedClock > 0 {
		// The in-flight epoch was just closed, so the new grid opens at the
		// next id. Ids therefore never repeat across an interval change.
		originEpoch, err := types.CheckedAddInt64(savedClock, 1)
		if err != nil {
			return err
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
	// The fee stream runs on wall-clock time, so it carries across a grid
	// change untouched and must not be re-anchored here: doing so would zero
	// the rate and the paid total and strand every tranche's remaining money.
	// Only a stream that has never run needs a starting point.
	cursor, err := k.CreatorStreamCursor(ctx)
	if err != nil {
		return err
	}
	if cursor == 0 {
		if err := k.AnchorCreatorStream(ctx, now); err != nil {
			return err
		}
	}
	ctx.Logger().Info("creator schedule activated",
		"origin_epoch", sched.OriginEpoch,
		"origin_unix", sched.OriginUnix,
		"epoch_seconds", sched.EpochSeconds,
		"clock", clock,
		"height", ctx.BlockHeight())
	ctx.EventManager().EmitEvent(sdk.NewEvent("creator_epoch_schedule_updated",
		sdk.NewAttribute("origin_epoch", fmt.Sprintf("%d", sched.OriginEpoch)),
		sdk.NewAttribute("origin_unix", fmt.Sprintf("%d", sched.OriginUnix)),
		sdk.NewAttribute("epoch_seconds", fmt.Sprintf("%d", sched.EpochSeconds)),
		sdk.NewAttribute("clock", fmt.Sprintf("%d", clock)),
	))
	return nil
}
