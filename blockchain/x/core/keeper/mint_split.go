package keeper

import (
	"fmt"

	sdkmath "cosmossdk.io/math"
)

// mintInput is one validator's state for a mint interval. Credits are already
// capped by MintDynamicCreditCap; capping needs the keeper, the split does not.
type mintInput struct {
	tokens        sdkmath.Int
	creditsCapped sdkmath.Int
}

// mintShare is one validator's slice of a mint interval, kept split three ways
// so the logs can attribute a payout to the reason it was earned.
type mintShare struct {
	floor sdkmath.Int
	work  sdkmath.Int
	stake sdkmath.Int
}

func (s mintShare) total() sdkmath.Int {
	return s.floor.Add(s.work).Add(s.stake)
}

// splitDec converts a float split param into a LegacyDec deterministically.
// Every node must derive the same decimal from the same stored float, so the
// conversion goes through a fixed-precision string rather than binary float
// arithmetic.
func splitDec(name string, split float64) (sdkmath.LegacyDec, error) {
	dec, err := sdkmath.LegacyNewDecFromStr(fmt.Sprintf("%.18f", split))
	if err != nil {
		return sdkmath.LegacyDec{}, fmt.Errorf("invalid %s %s: %w", name, fmt.Sprintf("%.18f", split), err)
	}
	return dec, nil
}

// splitMint divides a mint interval three ways: an equal floor per bonded
// validator, a work pool weighted by relay credits alone, and the remainder
// weighted by stake.
//
// The floor is the point of the split. Weighting everything by stake means a
// small validator earns almost nothing for doing the same hosting work as a
// large one, so the floor pays for participation and the work pool pays for
// traffic served, independent of how much either validator staked.
//
// vals must already be in the caller's deterministic order; every remainder
// lands on a position in that order, so a different order is a different
// AppHash. totalStake must be the sum of vals' tokens and must be positive.
//
// The returned shares sum to exactly mint. That is asserted, not assumed:
// minting a total that disagrees with the sum of the sends would break the
// supply-delta invariant.
func splitMint(
	mint sdkmath.Int,
	floorSplit float64,
	dynamicSplit float64,
	totalStake sdkmath.Int,
	vals []mintInput,
) ([]mintShare, error) {
	if len(vals) == 0 {
		return nil, fmt.Errorf("mint split: no validators")
	}
	if !mint.IsPositive() {
		return nil, fmt.Errorf("mint split: mint %s must be positive", mint)
	}
	if !totalStake.IsPositive() {
		return nil, fmt.Errorf("mint split: total stake %s must be positive", totalStake)
	}

	floorDec, err := splitDec("mint_floor_split", floorSplit)
	if err != nil {
		return nil, fmt.Errorf("mint split: %w", err)
	}
	dynDec, err := splitDec("mint_dynamic_split", dynamicSplit)
	if err != nil {
		return nil, fmt.Errorf("mint split: %w", err)
	}

	floorPool := floorDec.MulInt(mint).TruncateInt()
	workPool := dynDec.MulInt(mint).TruncateInt()
	if floorPool.IsNegative() || workPool.IsNegative() {
		return nil, fmt.Errorf("mint split: negative pool floor=%s work=%s", floorPool, workPool)
	}
	// Params.Validate caps the sum at 1, so exceeding the mint here means a
	// stored value bypassed validation. Refuse rather than mint past quantity.
	if floorPool.Add(workPool).GT(mint) {
		return nil, fmt.Errorf("mint split: floor %s + work %s exceeds mint %s", floorPool, workPool, mint)
	}
	stakePool := mint.Sub(floorPool).Sub(workPool)

	shares := make([]mintShare, len(vals))
	for i := range shares {
		shares[i] = mintShare{floor: sdkmath.ZeroInt(), work: sdkmath.ZeroInt(), stake: sdkmath.ZeroInt()}
	}
	last := len(vals) - 1

	// Floor: equal per validator, remainder to the last position.
	if floorPool.IsPositive() {
		per := floorPool.QuoRaw(int64(len(vals)))
		assigned := sdkmath.ZeroInt()
		for i := range shares {
			shares[i].floor = per
			assigned = assigned.Add(per)
		}
		if rem := floorPool.Sub(assigned); rem.IsPositive() {
			shares[last].floor = shares[last].floor.Add(rem)
		}
	}

	// Stake: proportional to tokens, remainder to the last position.
	if stakePool.IsPositive() {
		assigned := sdkmath.ZeroInt()
		for i, v := range vals {
			alloc := v.tokens.Mul(stakePool).Quo(totalStake)
			if alloc.IsPositive() {
				shares[i].stake = alloc
				assigned = assigned.Add(alloc)
			}
		}
		if rem := stakePool.Sub(assigned); rem.IsPositive() {
			shares[last].stake = shares[last].stake.Add(rem)
		}
	}

	// Work: weighted by capped credits alone. Stake is deliberately absent —
	// multiplying by tokens made the work pool a second stake pool, so a large
	// validator out-earned a small one on identical traffic.
	if workPool.IsPositive() {
		totalCredits := sdkmath.ZeroInt()
		for _, v := range vals {
			if v.creditsCapped.IsPositive() {
				totalCredits = totalCredits.Add(v.creditsCapped)
			}
		}
		if !totalCredits.IsPositive() {
			// Nobody relayed anything this interval. Fall back to stake weighting
			// rather than folding the pool into the floor, so an idle network does
			// not quietly change what the floor means.
			assigned := sdkmath.ZeroInt()
			for i, v := range vals {
				alloc := v.tokens.Mul(workPool).Quo(totalStake)
				if alloc.IsPositive() {
					shares[i].work = alloc
					assigned = assigned.Add(alloc)
				}
			}
			if rem := workPool.Sub(assigned); rem.IsPositive() {
				shares[last].work = shares[last].work.Add(rem)
			}
		} else {
			assigned := sdkmath.ZeroInt()
			lastWithCredits := -1
			for i, v := range vals {
				if !v.creditsCapped.IsPositive() {
					continue
				}
				lastWithCredits = i
				alloc := v.creditsCapped.Mul(workPool).Quo(totalCredits)
				if alloc.IsPositive() {
					shares[i].work = alloc
					assigned = assigned.Add(alloc)
				}
			}
			// The remainder follows the credits, not the validator order: giving it
			// to a validator that relayed nothing would pay work for no work.
			if rem := workPool.Sub(assigned); rem.IsPositive() && lastWithCredits >= 0 {
				shares[lastWithCredits].work = shares[lastWithCredits].work.Add(rem)
			}
		}
	}

	distributed := sdkmath.ZeroInt()
	for _, s := range shares {
		distributed = distributed.Add(s.total())
	}
	if !distributed.Equal(mint) {
		return nil, fmt.Errorf("mint split: distributed %s != mint %s (floor=%s work=%s stake=%s)",
			distributed, mint, floorPool, workPool, stakePool)
	}
	return shares, nil
}
