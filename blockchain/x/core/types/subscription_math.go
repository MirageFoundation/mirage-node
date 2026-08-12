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
func SplitPeriodFee(periodFee uint64, reservePercent float64) (reserve uint64, burn uint64, err error) {
	bps, err := ReserveBasisPoints(reservePercent)
	if err != nil {
		return 0, 0, err
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
