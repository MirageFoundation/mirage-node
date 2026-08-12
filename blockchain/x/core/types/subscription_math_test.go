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
		percent     float64
		wantReserve uint64
		wantBurn    uint64
	}{
		{"zero_fee", 0, 0.5, 0, 0},
		{"zero_percent", 1_000_000, 0, 0, 1_000_000},
		{"full_percent", 1_000_000, 1.0, 1_000_000, 0},
		{"half", 1_000_000, 0.5, 500_000, 500_000},
		{"ninety_five", 1_000_000, 0.95, 950_000, 50_000},
		{"third_rounds_down", 1_000_000, 0.333333, 333_300, 666_700},
		{"indivisible_fee", 7, 0.5, 3, 4},
		{"max_fee_zero_percent", math.MaxUint64, 0, 0, math.MaxUint64},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			reserve, burn, err := SplitPeriodFee(tc.fee, tc.percent)
			if err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			if reserve != tc.wantReserve || burn != tc.wantBurn {
				t.Fatalf("SplitPeriodFee(%d, %v) = (%d, %d), want (%d, %d)",
					tc.fee, tc.percent, reserve, burn, tc.wantReserve, tc.wantBurn)
			}
			if reserve+burn != tc.fee {
				t.Fatalf("split does not sum to the fee: %d + %d != %d", reserve, burn, tc.fee)
			}
		})
	}
}

func TestSplitPeriodFeeRejectsOverflow(t *testing.T) {
	if _, _, err := SplitPeriodFee(math.MaxUint64, 0.5); err == nil {
		t.Fatal("SplitPeriodFee accepted a fee that overflows basis-point multiplication")
	}
	if _, _, err := SplitPeriodFee(1_000_000, math.NaN()); err == nil {
		t.Fatal("SplitPeriodFee accepted a non-finite percentage")
	}
}
