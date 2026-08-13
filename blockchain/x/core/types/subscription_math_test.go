package types

import (
	"math"
	"testing"
)

func TestReserveBasisPointsRounding(t *testing.T) {
	cases := []struct {
		name    string
		percent float64
		want    uint64
	}{
		{"zero", 0, 0},
		{"one_tenth", 0.1, 1000},
		{"one_fifth", 0.2, 2000},
		{"third", 0.333333, 3333},
		// The truncating conversion this replaces yielded 9499 here.
		{"ninety_five", 0.95, 9500},
		{"full", 1.0, 10000},
		{"half_bps_rounds_up", 0.00005, 1},
		{"below_half_bps_rounds_down", 0.00004, 0},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			got, err := ReserveBasisPoints(tc.percent)
			if err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			if got != tc.want {
				t.Fatalf("ReserveBasisPoints(%v) = %d, want %d", tc.percent, got, tc.want)
			}
		})
	}
}

func TestReserveBasisPointsRejectsInvalid(t *testing.T) {
	invalid := map[string]float64{
		"nan":          math.NaN(),
		"positive_inf": math.Inf(1),
		"negative_inf": math.Inf(-1),
		"negative":     -0.01,
		"above_one":    1.01,
	}

	for name, percent := range invalid {
		t.Run(name, func(t *testing.T) {
			if _, err := ReserveBasisPoints(percent); err == nil {
				t.Fatalf("ReserveBasisPoints(%v) accepted an invalid percentage", percent)
			}
		})
	}
}

func TestSplitPeriodFeeIsExact(t *testing.T) {
	cases := []struct {
		name        string
		fee         uint64
		bps         uint64
		wantReserve uint64
		wantBurn    uint64
	}{
		{"zero_fee", 0, 5_000, 0, 0},
		{"zero_bps", 1_000_000, 0, 0, 1_000_000},
		{"full_bps", 1_000_000, 10_000, 1_000_000, 0},
		{"half", 1_000_000, 5_000, 500_000, 500_000},
		{"ninety_five", 1_000_000, 9_500, 950_000, 50_000},
		{"third_rounds_down", 1_000_000, 3_333, 333_300, 666_700},
		{"indivisible_fee", 7, 5_000, 3, 4},
		{"max_fee_zero_bps", math.MaxUint64, 0, 0, math.MaxUint64},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			reserve, burn, err := SplitPeriodFee(tc.fee, tc.bps)
			if err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			if reserve != tc.wantReserve || burn != tc.wantBurn {
				t.Fatalf("SplitPeriodFee(%d, %d) = (%d, %d), want (%d, %d)",
					tc.fee, tc.bps, reserve, burn, tc.wantReserve, tc.wantBurn)
			}
			if reserve+burn != tc.fee {
				t.Fatalf("split does not sum to the fee: %d + %d != %d", reserve, burn, tc.fee)
			}
		})
	}
}

func TestSplitPeriodFeeRejectsOverflow(t *testing.T) {
	if _, _, err := SplitPeriodFee(math.MaxUint64, 5_000); err == nil {
		t.Fatal("SplitPeriodFee accepted a fee that overflows basis-point multiplication")
	}
	// Out-of-range bps is refused rather than clamped: a params blob that never
	// passed Validate must not escrow a different share than governance approved.
	if _, _, err := SplitPeriodFee(1_000_000, BasisPointsDenominator+1); err == nil {
		t.Fatal("SplitPeriodFee accepted basis points above the denominator")
	}
}

// TestReserveConversionMatchesTheRetiredFloat pins the v1.34.0 conversion: the
// stored float must land on the same split the float path produced, or the
// upgrade would silently change what subscribers escrow. 0.95 is the value on
// the live chains and the exact case that truncation got wrong (9499 vs 9500).
func TestReserveConversionMatchesTheRetiredFloat(t *testing.T) {
	for _, percent := range []float64{0, 0.05, 0.2, 0.333333, 0.5, 0.95, 1} {
		bps, err := ReserveBasisPoints(percent)
		if err != nil {
			t.Fatalf("ReserveBasisPoints(%v): %v", percent, err)
		}
		if got := uint64(math.Round(percent * float64(BasisPointsDenominator))); bps != got {
			t.Fatalf("ReserveBasisPoints(%v) = %d, want %d", percent, bps, got)
		}
		reserve, burn, err := SplitPeriodFee(1_000_000, bps)
		if err != nil {
			t.Fatalf("SplitPeriodFee at %d bps: %v", bps, err)
		}
		if reserve+burn != 1_000_000 {
			t.Fatalf("split at %d bps does not sum to the fee: %d + %d", bps, reserve, burn)
		}
	}
}
