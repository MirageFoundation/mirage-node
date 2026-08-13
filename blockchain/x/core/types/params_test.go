package types

import (
	"math"
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

func TestParamsValidateUpperBounds(t *testing.T) {
	p := DefaultParams()

	// MintQuantity exceeds max
	p.MintQuantity = MaxMintQuantity + 1
	require.Error(t, p.Validate())
	require.Contains(t, p.Validate().Error(), "mint_quantity")

	// Reset and test VoteWeight
	p = DefaultParams()
	p.Tiers[1].VoteWeight = MaxVoteWeight + 1
	require.Error(t, p.Validate())
	require.Contains(t, p.Validate().Error(), "vote_weight")

	// Reset and test RelayMinGasPrice
	p = DefaultParams()
	p.RelayMinGasPrice = MaxRelayMinGasPrice + 1
	require.Error(t, p.Validate())
	require.Contains(t, p.Validate().Error(), "relay_min_gas_price")

	// Reset and test RelayMaxGasFee
	p = DefaultParams()
	p.RelayMaxGasFee = MaxRelayMaxGasFee + 1
	require.Error(t, p.Validate())
	require.Contains(t, p.Validate().Error(), "relay_max_gas_fee")

	// Reset and test AwardConfig.Cost upper bound (boundary + overshoot)
	p = DefaultParams()
	p.AwardConfigs = append([]*AwardConfig{}, DefaultAwardConfigs()...)
	p.AwardConfigs[0].Cost = MaxAwardConfigCost
	require.NoError(t, p.Validate(), "cost at max should be accepted")

	p.AwardConfigs[0].Cost = MaxAwardConfigCost + 1
	require.Error(t, p.Validate())
	require.Contains(t, p.Validate().Error(), "cost")
	require.Contains(t, p.Validate().Error(), "exceeds max allowed")

	// Default params should pass
	p = DefaultParams()
	require.NoError(t, p.Validate())
}

func TestParamsValidateRejectsNonFiniteFloats(t *testing.T) {
	tests := []struct {
		name   string
		mutate func(*Params)
	}{
		{"mint_dynamic_split_nan", func(p *Params) { p.MintDynamicSplit = math.NaN() }},
		{"mint_dynamic_split_inf", func(p *Params) { p.MintDynamicSplit = math.Inf(1) }},
		// subscription_reserve_percent is absent on purpose: v1.34.0 retired it in
		// favour of subscription_reserve_bps, nothing reads it, and constraining it
		// would break the from-genesis replay of the handlers that set it.
		// TestSubscriptionReserveBpsIsBounded covers the field that is read.
		{"pow_difficulty_step_nan", func(p *Params) { p.PowDifficultyStep = math.NaN() }},
		{"pow_difficulty_step_inf", func(p *Params) { p.PowDifficultyStep = math.Inf(1) }},
		{"pow_difficulty_step_too_small", func(p *Params) { p.PowDifficultyStep = MinPowDifficultyStep / 2 }},
		{"vote_weight_nan", func(p *Params) { p.Tiers[0].VoteWeight = math.NaN() }},
		{"vote_weight_inf", func(p *Params) { p.Tiers[0].VoteWeight = math.Inf(1) }},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			p := DefaultParams()
			tt.mutate(&p)
			require.Error(t, p.Validate())
		})
	}
}

// TestSubscriptionReserveBpsIsBounded covers the field that actually drives the
// reserve/burn split. The retired float is unconstrained by design, so this is
// the only bound standing between governance and an over-100% reserve.
func TestSubscriptionReserveBpsIsBounded(t *testing.T) {
	p := DefaultParams()
	require.Equal(t, uint64(9_500), p.SubscriptionReserveBps, "default must be 95% in basis points")

	p.SubscriptionReserveBps = BasisPointsDenominator
	require.NoError(t, p.Validate(), "a full reserve is a legitimate setting")

	p.SubscriptionReserveBps = BasisPointsDenominator + 1
	require.Error(t, p.Validate(), "more than 100% must be rejected")

	// The retired float must not affect validity in either direction.
	p = DefaultParams()
	p.SubscriptionReservePercent = 0.4
	require.NoError(t, p.Validate(),
		"a stored pre-upgrade percentage must still validate so a from-genesis replay can run")
}

func TestParamsValidateRejectsNilEntries(t *testing.T) {
	p := DefaultParams()
	p.Tiers = p.Tiers[:2]
	require.EqualError(t, p.Validate(), "tiers must contain exactly 3 entries")

	p = DefaultParams()
	p.Tiers[0] = nil
	require.EqualError(t, p.Validate(), "tier 0 must not be nil")

	p = DefaultParams()
	p.Tiers[1] = nil
	require.EqualError(t, p.Validate(), "tier 1 must not be nil")

	p = DefaultParams()
	p.AwardConfigs[0] = nil
	require.EqualError(t, p.Validate(), "award_configs[0] must not be nil")
}

func TestProfileValidateBasicRuneCounts(t *testing.T) {
	// 512 single-byte ASCII chars should pass
	asciiStr := ""
	for i := 0; i < 512; i++ {
		asciiStr += "a"
	}
	p := Profile{Username: "testuser", Biography: asciiStr}
	require.NoError(t, p.ValidateBasic(3, 30, 50))

	// 512 multi-byte runes should pass (each is 3 bytes in UTF-8)
	multiByteStr := ""
	for i := 0; i < 512; i++ {
		multiByteStr += "\u4e16" // Chinese character, 3 bytes
	}
	p = Profile{Username: "testuser", Biography: multiByteStr}
	require.NoError(t, p.ValidateBasic(3, 30, 50))

	// 513 runes should fail (regardless of byte count)
	tooLong := multiByteStr + "\u4e16"
	p = Profile{Username: "testuser", Biography: tooLong}
	require.Error(t, p.ValidateBasic(3, 30, 50))
	require.Contains(t, p.ValidateBasic(3, 30, 50).Error(), "biography too long")

	// Avatar rune count
	p = Profile{Username: "testuser", Avatar: tooLong}
	require.Error(t, p.ValidateBasic(3, 30, 50))
	require.Contains(t, p.ValidateBasic(3, 30, 50).Error(), "avatar too long")

	// Banner rune count
	p = Profile{Username: "testuser", Banner: tooLong}
	require.Error(t, p.ValidateBasic(3, 30, 50))
	require.Contains(t, p.ValidateBasic(3, 30, 50).Error(), "banner too long")

	// Flair rune count (limit 20)
	flairOk := ""
	for i := 0; i < 20; i++ {
		flairOk += "\u4e16"
	}
	p = Profile{Username: "testuser", Flair: flairOk}
	require.NoError(t, p.ValidateBasic(3, 30, 50))

	flairTooLong := flairOk + "\u4e16"
	p = Profile{Username: "testuser", Flair: flairTooLong}
	require.Error(t, p.ValidateBasic(3, 30, 50))
	require.Contains(t, p.ValidateBasic(3, 30, 50).Error(), "flair too long")
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
