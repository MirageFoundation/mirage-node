package keeper

import (
	"encoding/binary"
	"fmt"
	"math/big"
	"strings"

	sdkmath "cosmossdk.io/math"
	sdk "github.com/cosmos/cosmos-sdk/types"

	"mirage/x/core/types"
)

// Creator fee streaming.
//
// A subscription's creator share used to be split across every epoch the
// subscription spanned, one store record per epoch, written inside the purchase
// transaction. That made the payout interval a cost of buying a subscription:
// 30-day subscriptions on 5-minute epochs meant 103,680 writes per purchase,
// which is the only reason subscription_period and creator_epoch_seconds were
// ever coupled.
//
// Instead a tranche contributes a per-second rate and two breakpoints, and each
// epoch draws its pool from a running accumulator as it actually elapses. Cost
// per purchase is constant, and the two parameters no longer know about each
// other.
//
// Exactness matters here because addCreatorLiability records the full creator
// amount up front and the pool must eventually pay out exactly that. Rates are
// held in scaled units and each epoch takes floor(acc/scale) minus what has
// already been handed out, so successive epochs telescope with no drift. A
// floored rate under-pays its own tranche by less than one scaled unit per
// second, so every tranche also carries that exact deficit on its end
// breakpoint. Total emitted is therefore exactly the sum of creator amounts.
const creatorStreamScaleDigits = 18

// creatorStreamBreakpointKind distinguishes the two edges of a tranche. A
// renewal starts at the previous expiry, so a tranche can begin in the future
// and its start must be scheduled rather than applied on the spot.
const (
	creatorStreamStart byte = 0
	creatorStreamEnd   byte = 1
)

func creatorStreamScale() sdkmath.Int {
	return sdkmath.NewIntFromBigInt(new(big.Int).Exp(big.NewInt(10), big.NewInt(creatorStreamScaleDigits), nil))
}

type creatorStreamBreakpoint struct {
	key       []byte
	at        int64
	rateDelta sdkmath.Int
	accDelta  sdkmath.Int
}

func (k Keeper) creatorStreamInt(ctx sdk.Context, key string) (sdkmath.Int, error) {
	bz, err := k.storeGet(ctx, []byte(key))
	if err != nil {
		return sdkmath.Int{}, err
	}
	if len(bz) == 0 {
		return sdkmath.ZeroInt(), nil
	}
	v, ok := sdkmath.NewIntFromString(string(bz))
	if !ok {
		return sdkmath.Int{}, fmt.Errorf("corrupt %s", key)
	}
	return v, nil
}

func (k Keeper) setCreatorStreamInt(ctx sdk.Context, key string, v sdkmath.Int) error {
	return k.storeSet(ctx, []byte(key), []byte(v.String()))
}

// CreatorStreamCursor is the instant the accumulator has integrated up to. Zero
// means the stream has never run; the caller anchors it rather than treating
// the whole epoch as unfunded.
func (k Keeper) CreatorStreamCursor(ctx sdk.Context) (int64, error) {
	v, found, err := k.getU64Key(ctx, []byte(types.PfxCreatorStreamTs))
	if err != nil || !found {
		return 0, err
	}
	return int64(v), nil
}

func (k Keeper) setCreatorStreamCursor(ctx sdk.Context, at int64) error {
	if at < 0 {
		return fmt.Errorf("creator stream cursor must be non-negative")
	}
	return k.setU64Key(ctx, []byte(types.PfxCreatorStreamTs), uint64(at))
}

// AnchorCreatorStream starts the accumulator without accruing anything. Only
// a stream that has never run may be anchored: it zeroes the rate and the paid
// total, which on a live stream would strand every tranche's remaining money.
func (k Keeper) AnchorCreatorStream(ctx sdk.Context, at int64) error {
	if err := k.setCreatorStreamCursor(ctx, at); err != nil {
		return err
	}
	if err := k.setCreatorStreamInt(ctx, types.PfxCreatorStreamRate, sdkmath.ZeroInt()); err != nil {
		return err
	}
	if err := k.setCreatorStreamInt(ctx, types.PfxCreatorStreamAcc, sdkmath.ZeroInt()); err != nil {
		return err
	}
	return k.setCreatorStreamInt(ctx, types.PfxCreatorStreamPaid, sdkmath.ZeroInt())
}

func encodeCreatorStreamBreakpoint(rateDelta, accDelta sdkmath.Int) []byte {
	return []byte(rateDelta.String() + "|" + accDelta.String())
}

func decodeCreatorStreamBreakpoint(bz []byte) (sdkmath.Int, sdkmath.Int, error) {
	parts := strings.Split(string(bz), "|")
	if len(parts) != 2 {
		return sdkmath.Int{}, sdkmath.Int{}, fmt.Errorf("corrupt creator stream breakpoint")
	}
	rateDelta, ok := sdkmath.NewIntFromString(parts[0])
	if !ok {
		return sdkmath.Int{}, sdkmath.Int{}, fmt.Errorf("corrupt creator stream rate delta")
	}
	accDelta, ok := sdkmath.NewIntFromString(parts[1])
	if !ok {
		return sdkmath.Int{}, sdkmath.Int{}, fmt.Errorf("corrupt creator stream acc delta")
	}
	return rateDelta, accDelta, nil
}

// ScheduleCreatorStreamTranche registers one tranche with the accumulator. It
// writes two keys regardless of how many epochs the subscription covers, which
// is the whole point: purchase cost no longer scales with the payout interval.
func (k Keeper) ScheduleCreatorStreamTranche(ctx sdk.Context, id uint64, creatorAmt sdkmath.Int, start, end int64) error {
	if creatorAmt.IsNegative() {
		return fmt.Errorf("creator amount must be non-negative")
	}
	if end <= start {
		return fmt.Errorf("tranche must end after it starts")
	}
	if creatorAmt.IsZero() {
		return nil
	}
	// A tranche is the only thing that creates creator money, so it must not be
	// possible to book one against an unanchored stream: the accumulator would
	// start at the first boundary that happens to ask, and everything paid in
	// before that would be owed by the liability but never emitted to an epoch.
	cursor, err := k.CreatorStreamCursor(ctx)
	if err != nil {
		return err
	}
	if cursor == 0 {
		if err := k.AnchorCreatorStream(ctx, ctx.BlockTime().Unix()); err != nil {
			return err
		}
	}
	duration := sdkmath.NewInt(end - start)
	scaledTotal := creatorAmt.Mul(creatorStreamScale())
	rate := scaledTotal.Quo(duration)
	// What the floored rate will never deliver on its own. Paid out at the end
	// breakpoint so the tranche contributes exactly creatorAmt.
	deficit := scaledTotal.Sub(rate.Mul(duration))
	if deficit.IsNegative() {
		return fmt.Errorf("CONSENSUS_FATAL:CREATOR_STREAM_DEFICIT id=%d", id)
	}
	if err := k.storeSet(ctx,
		types.KeyCreatorStreamEnd(start, id<<1|uint64(creatorStreamStart)),
		encodeCreatorStreamBreakpoint(rate, sdkmath.ZeroInt()),
	); err != nil {
		return err
	}
	return k.storeSet(ctx,
		types.KeyCreatorStreamEnd(end, id<<1|uint64(creatorStreamEnd)),
		encodeCreatorStreamBreakpoint(rate.Neg(), deficit),
	)
}

// dueCreatorStreamBreakpoints returns breakpoints at or before upto, in time
// order, capped at budget. The cap keeps a block bounded when many
// subscriptions expire in the same window.
func (k Keeper) dueCreatorStreamBreakpoints(ctx sdk.Context, upto int64, budget int) ([]creatorStreamBreakpoint, error) {
	pfx := []byte(types.PfxCreatorStreamEnd)
	out := make([]creatorStreamBreakpoint, 0, budget)
	err := k.iterPrefixKeys(ctx, pfx, budget+1, func(key, val []byte) error {
		if len(out) >= budget {
			return nil
		}
		if len(key) < len(pfx)+16 {
			return fmt.Errorf("malformed cstrend key")
		}
		at := int64(binary.BigEndian.Uint64(key[len(pfx) : len(pfx)+8]))
		if at > upto {
			return nil
		}
		rateDelta, accDelta, err := decodeCreatorStreamBreakpoint(val)
		if err != nil {
			return err
		}
		out = append(out, creatorStreamBreakpoint{
			key:       append([]byte(nil), key...),
			at:        at,
			rateDelta: rateDelta,
			accDelta:  accDelta,
		})
		return nil
	})
	if err != nil {
		return nil, err
	}
	return out, nil
}

// CreatorStreamPaid is the running total the accumulator has handed to epochs.
// Once every tranche has elapsed it equals the sum of their creator shares
// exactly, which is the invariant the creator pool's solvency rests on.
func (k Keeper) CreatorStreamPaid(ctx sdk.Context) (sdkmath.Int, error) {
	return k.creatorStreamInt(ctx, types.PfxCreatorStreamPaid)
}

// CreatorStreamRate is the scaled amount currently streaming per second.
func (k Keeper) CreatorStreamRate(ctx sdk.Context) (sdkmath.Int, error) {
	return k.creatorStreamInt(ctx, types.PfxCreatorStreamRate)
}

// CreatorStreamIdleUntil reports the next instant the accumulator can produce
// anything: the earliest pending breakpoint, when nothing is currently
// streaming. Callers use it to skip epoch boundaries that provably carry no
// money instead of visiting each one.
func (k Keeper) CreatorStreamIdleUntil(ctx sdk.Context) (int64, bool, error) {
	rate, err := k.creatorStreamInt(ctx, types.PfxCreatorStreamRate)
	if err != nil {
		return 0, false, err
	}
	if !rate.IsZero() {
		return 0, false, nil
	}
	pfx := []byte(types.PfxCreatorStreamEnd)
	next := int64(0)
	found := false
	err = k.iterPrefixKeys(ctx, pfx, 1, func(key, _ []byte) error {
		if found {
			return nil
		}
		if len(key) < len(pfx)+16 {
			return fmt.Errorf("malformed cstrend key")
		}
		next = int64(binary.BigEndian.Uint64(key[len(pfx) : len(pfx)+8]))
		found = true
		return nil
	})
	if err != nil {
		return 0, false, err
	}
	if !found {
		// Nothing streaming and nothing scheduled: idle indefinitely.
		return 0, true, nil
	}
	return next, true, nil
}

// SettleCreatorStream integrates the accumulator forward to upto, applying any
// breakpoints on the way. It reports how far it actually got: when the
// breakpoint budget runs out it stops at the last one applied so the caller can
// resume next block rather than skipping money.
func (k Keeper) SettleCreatorStream(ctx sdk.Context, upto int64, budget int) (int64, error) {
	ts, err := k.CreatorStreamCursor(ctx)
	if err != nil {
		return 0, err
	}
	if ts == 0 {
		// Never anchored. Start here; nothing accrued before the stream existed.
		return upto, k.AnchorCreatorStream(ctx, upto)
	}
	if upto < ts {
		return 0, fmt.Errorf("CONSENSUS_FATAL:CREATOR_STREAM_REGRESSION have=%d want=%d", ts, upto)
	}
	if upto == ts {
		return ts, nil
	}
	rate, err := k.creatorStreamInt(ctx, types.PfxCreatorStreamRate)
	if err != nil {
		return 0, err
	}
	acc, err := k.creatorStreamInt(ctx, types.PfxCreatorStreamAcc)
	if err != nil {
		return 0, err
	}
	due, err := k.dueCreatorStreamBreakpoints(ctx, upto, budget)
	if err != nil {
		return 0, err
	}
	reached := upto
	for i, bp := range due {
		if bp.at > ts {
			acc = acc.Add(rate.Mul(sdkmath.NewInt(bp.at - ts)))
			ts = bp.at
		}
		acc = acc.Add(bp.accDelta)
		rate = rate.Add(bp.rateDelta)
		if rate.IsNegative() {
			return 0, fmt.Errorf("CONSENSUS_FATAL:CREATOR_STREAM_RATE_NEGATIVE at=%d", bp.at)
		}
		if err := k.storeDelete(ctx, bp.key); err != nil {
			return 0, err
		}
		if i == len(due)-1 && len(due) == budget {
			// Budget exhausted; there may be more breakpoints at or before
			// upto. Stop here so none are integrated over.
			reached = ts
		}
	}
	if reached > ts {
		acc = acc.Add(rate.Mul(sdkmath.NewInt(reached - ts)))
		ts = reached
	}
	if err := k.setCreatorStreamInt(ctx, types.PfxCreatorStreamRate, rate); err != nil {
		return 0, err
	}
	if err := k.setCreatorStreamInt(ctx, types.PfxCreatorStreamAcc, acc); err != nil {
		return 0, err
	}
	if err := k.setCreatorStreamCursor(ctx, ts); err != nil {
		return 0, err
	}
	return ts, nil
}

// DrawCreatorStream hands the caller every whole token the accumulator has
// produced up to boundary, and records it as paid. Taking the difference of
// floors is what makes consecutive epochs sum to the exact total instead of
// losing a unit per epoch to rounding.
func (k Keeper) DrawCreatorStream(ctx sdk.Context, boundary int64, budget int) (sdkmath.Int, bool, error) {
	reached, err := k.SettleCreatorStream(ctx, boundary, budget)
	if err != nil {
		return sdkmath.Int{}, false, err
	}
	if reached < boundary {
		return sdkmath.ZeroInt(), false, nil
	}
	acc, err := k.creatorStreamInt(ctx, types.PfxCreatorStreamAcc)
	if err != nil {
		return sdkmath.Int{}, false, err
	}
	paid, err := k.creatorStreamInt(ctx, types.PfxCreatorStreamPaid)
	if err != nil {
		return sdkmath.Int{}, false, err
	}
	earned := acc.Quo(creatorStreamScale())
	amount := earned.Sub(paid)
	if amount.IsNegative() {
		return sdkmath.Int{}, false, fmt.Errorf("CONSENSUS_FATAL:CREATOR_STREAM_PAID_REGRESSION earned=%s paid=%s", earned, paid)
	}
	if amount.IsPositive() {
		if err := k.setCreatorStreamInt(ctx, types.PfxCreatorStreamPaid, earned); err != nil {
			return sdkmath.Int{}, false, err
		}
	}
	return amount, true, nil
}
