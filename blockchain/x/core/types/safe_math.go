package types

import (
	"fmt"
	"math"
	"time"
)

// Checked conversions and arithmetic for consensus paths (review M-7).
//
// Every helper returns an error instead of clamping, wrapping, or falling back.
// Params validation rejects out-of-range values up front, but raw genesis
// imports, raw-state imports, and upgrade writes bypass it, so runtime paths
// call these defensively and fail hard rather than silently computing a
// different value than peers.

// CheckedUint64ToInt64 converts a uint64 to int64, rejecting values that would
// wrap into a negative number.
func CheckedUint64ToInt64(v uint64) (int64, error) {
	if v > math.MaxInt64 {
		return 0, fmt.Errorf("value %d overflows int64", v)
	}
	return int64(v), nil
}

// CheckedMulUint64 multiplies two uint64 values, rejecting overflow.
func CheckedMulUint64(a, b uint64) (uint64, error) {
	if a == 0 || b == 0 {
		return 0, nil
	}
	if a > math.MaxUint64/b {
		return 0, fmt.Errorf("multiplication overflows uint64: %d * %d", a, b)
	}
	return a * b, nil
}

// CheckedAddUint64 adds two uint64 values, rejecting overflow.
func CheckedAddUint64(a, b uint64) (uint64, error) {
	if a > math.MaxUint64-b {
		return 0, fmt.Errorf("addition overflows uint64: %d + %d", a, b)
	}
	return a + b, nil
}

// CheckedMulInt64 multiplies two non-negative int64 values, rejecting negatives
// and overflow.
func CheckedMulInt64(a, b int64) (int64, error) {
	if a < 0 || b < 0 {
		return 0, fmt.Errorf("multiplication requires non-negative operands: %d * %d", a, b)
	}
	if a == 0 || b == 0 {
		return 0, nil
	}
	if a > math.MaxInt64/b {
		return 0, fmt.Errorf("multiplication overflows int64: %d * %d", a, b)
	}
	return a * b, nil
}

// CheckedAddInt64 adds two non-negative int64 values, rejecting negatives and
// overflow.
func CheckedAddInt64(a, b int64) (int64, error) {
	if a < 0 || b < 0 {
		return 0, fmt.Errorf("addition requires non-negative operands: %d + %d", a, b)
	}
	if a > math.MaxInt64-b {
		return 0, fmt.Errorf("addition overflows int64: %d + %d", a, b)
	}
	return a + b, nil
}

// CheckedSubscriptionExpiry computes base + periodMinutes*60 as a unix seconds
// timestamp. A wrapped expiry would sort before now in the subscription index
// and expire immediately, or never.
func CheckedSubscriptionExpiry(base int64, periodMinutes uint64) (int64, error) {
	if periodMinutes > MaxSubscriptionPeriodMinutes {
		return 0, fmt.Errorf("subscription period %d exceeds max %d minutes",
			periodMinutes, MaxSubscriptionPeriodMinutes)
	}
	minutes, err := CheckedUint64ToInt64(periodMinutes)
	if err != nil {
		return 0, err
	}
	seconds, err := CheckedMulInt64(minutes, 60)
	if err != nil {
		return 0, err
	}
	return CheckedAddInt64(base, seconds)
}

// CheckedWindowStart returns the first height of a window of the given size
// ending at currentHeight, never below 1. It rejects window sizes that cannot be
// represented, so a corrupted window cannot turn into an unbounded sweep.
func CheckedWindowStart(currentHeight int64, window uint64) (int64, error) {
	if currentHeight < 0 {
		return 0, fmt.Errorf("current height must be non-negative: %d", currentHeight)
	}
	if window == 0 {
		return 0, fmt.Errorf("window must be > 0")
	}
	if window > MaxPowMessageWindow {
		return 0, fmt.Errorf("window %d exceeds max %d", window, MaxPowMessageWindow)
	}
	size, err := CheckedUint64ToInt64(window)
	if err != nil {
		return 0, err
	}
	start := currentHeight - size + 1
	if start < 1 {
		start = 1
	}
	return start, nil
}

// CheckedEnvelopeAge converts a max envelope age in seconds to a duration,
// rejecting values outside the governance-safe bound.
func CheckedEnvelopeAge(seconds uint64) (time.Duration, error) {
	if seconds == 0 {
		return 0, fmt.Errorf("max envelope age must be > 0")
	}
	if seconds > MaxEnvelopeAgeSeconds {
		return 0, fmt.Errorf("max envelope age %d exceeds max %d seconds", seconds, MaxEnvelopeAgeSeconds)
	}
	return time.Duration(seconds) * time.Second, nil
}
