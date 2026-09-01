package types

import (
	"testing"

	"github.com/stretchr/testify/require"
)

func TestCreatorScheduleKeepsUnixDivisionWhenOriginIsZero(t *testing.T) {
	unix := int64(1_700_000_000)
	sched := CreatorSchedule{EpochSeconds: 300}
	epoch, err := sched.EpochAt(unix)
	require.NoError(t, err)
	require.Equal(t, unix/300, epoch)
	start, err := sched.EpochStart(epoch)
	require.NoError(t, err)
	require.Equal(t, epoch*300, start)
}

func TestCreatorScheduleIsMonotonicAcrossIntervalChange(t *testing.T) {
	now := int64(1_700_000_000)
	old := CreatorSchedule{EpochSeconds: SecondsPerUTCDay}
	oldEpoch, err := old.EpochAt(now)
	require.NoError(t, err)

	next := CreatorSchedule{
		OriginEpoch:  oldEpoch + 1,
		OriginUnix:   now,
		EpochSeconds: 300,
	}
	current, err := next.EpochAt(now)
	require.NoError(t, err)
	require.Equal(t, oldEpoch+1, current)
	later, err := next.EpochAt(now + 300)
	require.NoError(t, err)
	require.Equal(t, oldEpoch+2, later)

	daily := CreatorSchedule{
		OriginEpoch:  later,
		OriginUnix:   now + 600,
		EpochSeconds: SecondsPerUTCDay,
	}
	rebased, err := daily.EpochAt(now + 600)
	require.NoError(t, err)
	require.Equal(t, later, rebased)
	require.Greater(t, rebased, oldEpoch)
}
