package types

import (
	"testing"

	"github.com/stretchr/testify/require"
)

func TestDefaultTiers(t *testing.T) {
	tiers := DefaultTiers()
	require.Len(t, tiers, 3, "expected 3 tiers: Free(0), Subscriber(1), Agent(2)")

	// Free tier: basic limits
	require.Equal(t, uint64(0), tiers[0].PeriodFee)
	require.Equal(t, uint64(25), tiers[0].MaxBlockedTopics)
	require.False(t, tiers[0].CanBeAgent)

	// Subscriber tier
	require.Equal(t, uint64(100_000_000_000), tiers[1].PeriodFee)
	require.Equal(t, uint64(500), tiers[1].MaxBlockedTopics)
	require.False(t, tiers[1].CanBeAgent)

	// Agent tier
	require.Equal(t, uint64(500_000_000_000), tiers[2].PeriodFee)
	require.Equal(t, uint64(500), tiers[2].MaxBlockedTopics)
	require.True(t, tiers[2].CanBeAgent)
}

func TestLevelToTierIndex(t *testing.T) {
	require.Equal(t, 0, LevelToTierIndex(0))
	require.Equal(t, 1, LevelToTierIndex(1))
	require.Equal(t, 2, LevelToTierIndex(10))
	require.Equal(t, 2, LevelToTierIndex(100))
	require.Equal(t, 2, LevelToTierIndex(255))

	// Invalid levels return -1
	require.Equal(t, -1, LevelToTierIndex(2))
	require.Equal(t, -1, LevelToTierIndex(5))
	require.Equal(t, -1, LevelToTierIndex(9))
	require.Equal(t, -1, LevelToTierIndex(-1))
}

func TestGetTierConfigMapping(t *testing.T) {
	p := DefaultParams()

	// Valid levels
	require.NotNil(t, p.GetTierConfig(0))
	require.NotNil(t, p.GetTierConfig(1))
	require.NotNil(t, p.GetTierConfig(10))
	require.NotNil(t, p.GetTierConfig(100))

	// Invalid levels
	require.Nil(t, p.GetTierConfig(2))
	require.Nil(t, p.GetTierConfig(5))
	require.Nil(t, p.GetTierConfig(9))
	require.Nil(t, p.GetTierConfig(-1))

	// Level 10 and level 100 should return the same tier config (Agent)
	require.Equal(t, p.GetTierConfig(10), p.GetTierConfig(100))
	require.True(t, p.GetTierConfig(10).CanBeAgent)
}

func TestDefaultAwardConfigs(t *testing.T) {
	cfgs := DefaultAwardConfigs()
	require.Len(t, cfgs, 4)

	names := map[string]uint64{}
	for _, c := range cfgs {
		names[c.Name] = c.Cost
	}

	t.Logf("[debug] award configs=%v", names)
	require.Equal(t, uint64(10_000_000_000), names["quality_post"])
	require.Equal(t, uint64(5_000_000_000), names["original_content"])
	require.Equal(t, uint64(5_000_000_000), names["based"])
	require.Equal(t, uint64(5_000_000_000), names["receipts"])
}

func TestParamsValidateAwardConfigs(t *testing.T) {
	p := DefaultParams()

	p.AwardConfigs = []*AwardConfig{}
	require.Error(t, p.Validate())

	p = DefaultParams()
	p.AwardConfigs = []*AwardConfig{
		{Name: "dup", Cost: 1},
		{Name: "dup", Cost: 2},
	}
	require.Error(t, p.Validate())

	p = DefaultParams()
	p.AwardConfigs = []*AwardConfig{
		{Name: "", Cost: 1},
	}
	require.Error(t, p.Validate())

	p = DefaultParams()
	require.NoError(t, p.Validate())
}

func TestGetAwardConfig(t *testing.T) {
	p := DefaultParams()
	cfg := p.GetAwardConfig("based")
	require.NotNil(t, cfg)
	require.Equal(t, "based", cfg.Name)
	require.Equal(t, uint64(5_000_000_000), cfg.Cost)

	require.Nil(t, p.GetAwardConfig("not_a_real_award"))
}

func TestC1BugCondition(t *testing.T) {
	// Reproduce the C-1 bug condition: the old code used
	//   if core.Level <= 0 || int(core.Level) >= len(params.Tiers)
	// With 3 tiers (indices 0,1,2), level 10 evaluates to int(10) >= 3 = true,
	// causing Agent users to skip renewal/downgrade entirely.
	p := DefaultParams()
	require.Len(t, p.Tiers, 3)

	// Old buggy condition would skip Agent (level 10)
	level10 := 10
	buggySkip := level10 <= 0 || level10 >= len(p.Tiers)
	require.True(t, buggySkip, "demonstrates the old bug: level 10 was incorrectly skipped")

	// New code uses LevelToTierIndex which correctly maps level 10 → index 2
	tierIdx := LevelToTierIndex(level10)
	require.Equal(t, 2, tierIdx, "LevelToTierIndex(10) must return 2")
	require.True(t, tierIdx > 0, "Agent tier index must be > 0 (not skipped)")

	// Admin (level 100) also must not be skipped
	adminIdx := LevelToTierIndex(100)
	require.Equal(t, 2, adminIdx)
	require.True(t, adminIdx > 0)
}
