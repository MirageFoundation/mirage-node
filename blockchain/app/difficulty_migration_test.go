package app

import (
	"math"
	"testing"

	"github.com/stretchr/testify/require"
)

// TestDifficultyMigrationMath tests the logic used in the v1.11.0 upgrade handler
// to convert old difficulty values (bit-counts or factors) to new step counts.
func TestDifficultyMigrationMath(t *testing.T) {
	baseFactor := uint64(1000)
	step := 0.25
	minDiff := uint64(10)

	tests := []struct {
		name          string
		oldDiff       uint64 // Can be bit-count (<1000) or factor (>=1000)
		expectedSteps uint64
	}{
		// Case 1: Old Bit-Counts (e.g. 10, 11, 12)
		// Logic: factor = 1000 * 2^(old - minDiff)
		// Then: steps = log(factor/1000) / log(1.25)
		// 2^1 = 2. log(2)/log(1.25) = 3.106 -> 3 steps
		// 2^2 = 4. log(4)/log(1.25) = 6.21 -> 6 steps
		
		{"Bit-count 10 (Base)", 10, 0}, // 1000 * 2^0 = 1000 -> 0 steps
		{"Bit-count 11 (+1 bit)", 11, 3}, // 1000 * 2^1 = 2000. log(2)/log(1.25) = 3.1 -> 3
		{"Bit-count 12 (+2 bits)", 12, 6}, // 1000 * 2^2 = 4000. log(4)/log(1.25) = 6.2 -> 6
		{"Bit-count 13 (+3 bits)", 13, 9}, // 1000 * 2^3 = 8000. log(8)/log(1.25) = 9.3 -> 9

		// Case 2: Already in Factor format (>= 1000)
		{"Factor 1000 (Base)", 1000, 0},
		{"Factor 1250 (Step 1)", 1250, 1}, // log(1.25)/log(1.25) = 1
		{"Factor 1563 (Step 2)", 1563, 2}, // log(1.563)/log(1.25) = 2.001 -> 2
		{"Factor 2000 (Approx Step 3)", 2000, 3}, // log(2)/log(1.25) = 3.1 -> 3
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			// Emulate the upgrade handler logic
			factor := tt.oldDiff
			
			// 1. Convert bit-count to factor if needed
			if tt.oldDiff < baseFactor {
				shift := uint64(0)
				if tt.oldDiff > minDiff {
					shift = tt.oldDiff - minDiff
				}
				factor = baseFactor << shift
			}

			// 2. Convert factor to steps
			steps := uint64(0)
			if factor > baseFactor {
				ratio := float64(factor) / float64(baseFactor)
				exp := math.Log(ratio) / math.Log(1+step)
				steps = uint64(math.Round(exp))
			}

			require.Equal(t, tt.expectedSteps, steps)
		})
	}
}
