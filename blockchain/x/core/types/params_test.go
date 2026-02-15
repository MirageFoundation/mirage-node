package types

import (
	"testing"

	"github.com/stretchr/testify/require"
)

func TestDefaultTiersMaxBlockedTopics(t *testing.T) {
	tiers := DefaultTiers()
	require.Len(t, tiers, 4)

	got := []uint64{
		tiers[0].MaxBlockedTopics,
		tiers[1].MaxBlockedTopics,
		tiers[2].MaxBlockedTopics,
		tiers[3].MaxBlockedTopics,
	}
	t.Logf("[debug] MaxBlockedTopics tiers=%v", got)
	require.Equal(t, []uint64{10, 125, 500, 1000}, got)
}
