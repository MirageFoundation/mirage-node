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
