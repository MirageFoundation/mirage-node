package types

import (
	"fmt"
	"math"
)

func CreatorEpochFromUnix(unix int64, epochSeconds uint64) (int64, error) {
	if unix < 0 {
		return 0, fmt.Errorf("creator epoch time must be non-negative")
	}
	if epochSeconds == 0 || epochSeconds > math.MaxInt64 {
		return 0, fmt.Errorf("creator epoch seconds out of range: %d", epochSeconds)
	}
	return unix / int64(epochSeconds), nil
}

func CreatorEpochStart(epoch int64, epochSeconds uint64) (int64, error) {
	if epoch < 0 {
		return 0, fmt.Errorf("creator epoch must be non-negative")
	}
	if epochSeconds == 0 || epochSeconds > math.MaxInt64 {
		return 0, fmt.Errorf("creator epoch seconds out of range: %d", epochSeconds)
	}
	seconds := int64(epochSeconds)
	if epoch > math.MaxInt64/seconds {
		return 0, fmt.Errorf("creator epoch start overflows int64")
	}
	return epoch * seconds, nil
}

func CreatorEpochEnd(epoch int64, epochSeconds uint64) (int64, error) {
	if epoch == math.MaxInt64 {
		return 0, fmt.Errorf("creator epoch end overflows int64")
	}
	return CreatorEpochStart(epoch+1, epochSeconds)
}

func CreatorClaimDeadline(currentEpoch int64, claimWindowDays, epochSeconds uint64) (int64, error) {
	if epochSeconds == 0 || SecondsPerUTCDay%epochSeconds != 0 {
		return 0, fmt.Errorf("creator epoch seconds must divide %d exactly", SecondsPerUTCDay)
	}
	windowEpochs, err := CheckedMulUint64(claimWindowDays, SecondsPerUTCDay/epochSeconds)
	if err != nil {
		return 0, err
	}
	return CheckedAddInt64(currentEpoch, int64(windowEpochs)+1)
}
