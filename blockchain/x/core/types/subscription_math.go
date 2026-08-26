package types

import (
	"fmt"
	"math"
)

// BasisPointsDenominator is the basis-point scale: 10000 bps == 100%.
const BasisPointsDenominator uint64 = 10000

// ReserveBasisPoints converts a reserve percentage in [0,1] to basis points.
//
// Rounding is explicit rather than truncating. uint64(0.95 * 10000) can yield
// 9499 because 0.95 has no exact binary representation, which under-escrows the
// reserve by one basis point (review L-4). Params validation also rejects
// out-of-range percentages; this rejects them again so a raw imported or
// upgraded params blob cannot reach the arithmetic.
//
// Only the v1.34.0 upgrade calls this now, to convert the stored float once.
// The split itself reads params.SubscriptionReserveBps, so no float is involved
// at runtime and the conversion cannot be repeated per block.
func ReserveBasisPoints(reservePercent float64) (uint64, error) {
	if math.IsNaN(reservePercent) || math.IsInf(reservePercent, 0) {
		return 0, fmt.Errorf("reserve percent is not a finite number: %v", reservePercent)
	}
	if reservePercent < 0 || reservePercent > 1 {
		return 0, fmt.Errorf("reserve percent out of range [0,1]: %v", reservePercent)
	}
	bps := uint64(math.Round(reservePercent * float64(BasisPointsDenominator)))
	if bps > BasisPointsDenominator {
		return 0, fmt.Errorf("reserve basis points out of range: %d", bps)
	}
	return bps, nil
}

// SplitPeriodFee splits a subscription period fee into the escrowed reserve and
// the burned remainder. reserve + burn always equals periodFee exactly, so no
// value is created or stranded by the split.
//
// bps comes straight from params and is rejected rather than clamped when out of
// range: a params blob that never passed Validate must not silently escrow a
// different share than governance approved.
func SplitPeriodFee(periodFee uint64, bps uint64) (reserve uint64, burn uint64, err error) {
	if bps > BasisPointsDenominator {
		return 0, 0, fmt.Errorf("reserve basis points out of range: %d", bps)
	}
	if periodFee == 0 || bps == 0 {
		return 0, periodFee, nil
	}
	if periodFee > math.MaxUint64/bps {
		return 0, 0, fmt.Errorf("period fee %d overflows basis-point multiplication at %d bps", periodFee, bps)
	}
	reserve = periodFee * bps / BasisPointsDenominator
	return reserve, periodFee - reserve, nil
}

// SplitCreatorFee splits a subscription fee into burn and creator-pool amounts.
// burn + creator always equals periodFee. Creator BPS of 5000 on an odd fee of 7
// yields burn 3 and creator 4 (remainder goes to the creator pool).
func SplitCreatorFee(periodFee uint64, creatorBps uint64) (burn uint64, creator uint64, err error) {
	if creatorBps > BasisPointsDenominator {
		return 0, 0, fmt.Errorf("creator basis points out of range: %d", creatorBps)
	}
	if periodFee == 0 || creatorBps == 0 {
		return periodFee, 0, nil
	}
	if periodFee > math.MaxUint64/creatorBps {
		return 0, 0, fmt.Errorf("period fee %d overflows basis-point multiplication at %d bps", periodFee, creatorBps)
	}
	creator = periodFee * creatorBps / BasisPointsDenominator
	return periodFee - creator, creator, nil
}
