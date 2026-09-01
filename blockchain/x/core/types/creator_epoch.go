package types

import (
	"fmt"
	"math"
)

// CreatorSchedule is the live epoch grid. Epoch IDs are origin_epoch plus
// elapsed intervals since origin_unix, so a governance interval change can
// keep IDs monotonic instead of rebasing to unix/seconds.
type CreatorSchedule struct {
	OriginEpoch  int64
	OriginUnix   int64
	EpochSeconds uint64
}

func CreatorEpochFromUnix(unix int64, epochSeconds uint64) (int64, error) {
	return (CreatorSchedule{EpochSeconds: epochSeconds}).EpochAt(unix)
}

func CreatorEpochStart(epoch int64, epochSeconds uint64) (int64, error) {
	return (CreatorSchedule{EpochSeconds: epochSeconds}).EpochStart(epoch)
}

func CreatorEpochEnd(epoch int64, epochSeconds uint64) (int64, error) {
	if epoch == math.MaxInt64 {
		return 0, fmt.Errorf("creator epoch end overflows int64")
	}
	return CreatorEpochStart(epoch+1, epochSeconds)
}

func (s CreatorSchedule) EpochAt(unix int64) (int64, error) {
	if unix < 0 {
		return 0, fmt.Errorf("creator epoch time must be non-negative")
	}
	if s.OriginUnix < 0 || s.OriginEpoch < 0 {
		return 0, fmt.Errorf("creator schedule origin must be non-negative")
	}
	if unix < s.OriginUnix {
		return 0, fmt.Errorf("creator epoch time precedes schedule origin")
	}
	if s.EpochSeconds == 0 || s.EpochSeconds > math.MaxInt64 {
		return 0, fmt.Errorf("creator epoch seconds out of range: %d", s.EpochSeconds)
	}
	steps := (unix - s.OriginUnix) / int64(s.EpochSeconds)
	return CheckedAddInt64(s.OriginEpoch, steps)
}

func (s CreatorSchedule) EpochStart(epoch int64) (int64, error) {
	if epoch < 0 {
		return 0, fmt.Errorf("creator epoch must be non-negative")
	}
	if s.OriginUnix < 0 || s.OriginEpoch < 0 {
		return 0, fmt.Errorf("creator schedule origin must be non-negative")
	}
	if epoch < s.OriginEpoch {
		return 0, fmt.Errorf("creator epoch precedes schedule origin")
	}
	if s.EpochSeconds == 0 || s.EpochSeconds > math.MaxInt64 {
		return 0, fmt.Errorf("creator epoch seconds out of range: %d", s.EpochSeconds)
	}
	offset := epoch - s.OriginEpoch
	delta, err := CheckedMulInt64(offset, int64(s.EpochSeconds))
	if err != nil {
		return 0, err
	}
	return CheckedAddInt64(s.OriginUnix, delta)
}

func (s CreatorSchedule) EpochEnd(epoch int64) (int64, error) {
	if epoch == math.MaxInt64 {
		return 0, fmt.Errorf("creator epoch end overflows int64")
	}
	return s.EpochStart(epoch + 1)
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
