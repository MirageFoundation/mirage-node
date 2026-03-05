package types

import (
	"fmt"
)

// Valid user levels. Only these levels can be assigned to a profile.
// Levels 2-9 are reserved for future subscription tiers.
const (
	LevelFree       = 0
	LevelSubscriber = 1
	LevelAgent      = 10
	LevelAdminMin   = 100
)

// ValidSubscriptionLevels are the levels users can self-upgrade to via MsgUpgradeLevel.
var ValidSubscriptionLevels = map[int]bool{
	LevelSubscriber: true,
	LevelAgent:      true,
}

// LevelToTierIndex maps a user level to the index in the Tiers array.
// Returns -1 for invalid/unsupported levels.
func LevelToTierIndex(level int) int {
	switch {
	case level == LevelFree:
		return 0
	case level == LevelSubscriber:
		return 1
	case level == LevelAgent:
		return 2
	case level >= LevelAdminMin:
		return 2 // admins get agent-tier capabilities
	default:
		return -1
	}
}

// DefaultTiers returns the default tier configurations.
// Index 0 = Free (level 0), 1 = Subscriber (level 1), 2 = Agent (level 10)
func DefaultTiers() []*TierConfig {
	return []*TierConfig{
		// Index 0 — Level 0: Free
		{
			PeriodFee:         0,
			MaxEnabledAgents:  5,
			MaxFollowedUsers:  25,
			MaxFollowedTopics: 25,
			MaxBlockedUsers:   25,
			MaxBlockedPosts:   25,
			MaxBlockedTopics:  25,
			MaxTitleLength:    150,
			MaxContentLength:  1000,
			EditingTimeMins:   10,
			VoteWeight:        1.0,
			CanBeAgent:        false,
			CanRemoveAnon:     false,
			CanHaveBiography:  false,
			CanHaveAvatar:     false,
			CanHaveBanner:     false,
			CanHaveFlair:      false,
		},
		// Index 1 — Level 1: Subscriber (100B umirage)
		{
			PeriodFee:         100_000_000_000,
			MaxEnabledAgents:  50,
			MaxFollowedUsers:  500,
			MaxFollowedTopics: 500,
			MaxBlockedUsers:   500,
			MaxBlockedPosts:   500,
			MaxBlockedTopics:  500,
			MaxTitleLength:    300,
			MaxContentLength:  20000,
			EditingTimeMins:   360,
			VoteWeight:        1.33,
			CanBeAgent:        false,
			CanRemoveAnon:     true,
			CanHaveBiography:  true,
			CanHaveAvatar:     true,
			CanHaveBanner:     true,
			CanHaveFlair:      true,
		},
		// Index 2 — Level 10: Agent (500B umirage)
		{
			PeriodFee:         500_000_000_000,
			MaxEnabledAgents:  50,
			MaxFollowedUsers:  500,
			MaxFollowedTopics: 500,
			MaxBlockedUsers:   500,
			MaxBlockedPosts:   500,
			MaxBlockedTopics:  500,
			MaxTitleLength:    300,
			MaxContentLength:  20000,
			EditingTimeMins:   360,
			VoteWeight:        1.33,
			CanBeAgent:        true,
			CanRemoveAnon:     true,
			CanHaveBiography:  true,
			CanHaveAvatar:     true,
			CanHaveBanner:     true,
			CanHaveFlair:      true,
		},
	}
}

// DefaultAwardConfigs returns the default award type configurations.
func DefaultAwardConfigs() []*AwardConfig {
	return []*AwardConfig{
		{Name: "quality_post", Cost: 10_000_000_000},
		{Name: "original_content", Cost: 5_000_000_000},
		{Name: "based", Cost: 5_000_000_000},
		{Name: "receipts", Cost: 5_000_000_000},
	}
}

// DefaultParams returns a default set of parameters.
// These defaults reflect v1.16.0 economics (Free=0, Subscriber=1, Agent=10).
func DefaultParams() Params {
	return Params{
		// Minting
		MintInterval:         200,             // in blocks; one block = every 3 secs, i.e. every 10 mins we mint
		MintQuantity:         125_000_000_000, // 125,000 MIRAGE per 10min
		MintDynamicCreditCap: 25,              // default cap per interval per validator (same as default PowMessageLimit)
		MintDynamicSplit:     0.5,             // 50% dynamic by default

		// min_difficulty defines the base PoW target: base_target = 2^(256 - min_difficulty)
		MinDifficulty: 10,

		// PoW difficulty step (fraction (0,1]): factor = 1000 * (1+pow_difficulty_step)^difficulty, steps +/-1
		PowDifficultyStep: 0.25,

		// PoW message window
		PowMessageWindow:         20,  // sliding window in blocks for difficulty adjustment; 20 = 1 min
		PowMessageLimit:          15,  // if >= this many pow msgs in window, increase difficulty
		PowCalmPeriodDefinition:  10,  // if < this many pow msgs in window, calm period
		PowCalmSequenceThreshold: 100, // consecutive calm periods before decreasing difficulty; 100 = 5 mins

		// PoW validation
		BlockHashWindow: 10, // in blocks; how many recent block hashes to accept for PoW validation

		// Grace window during a difficulty change where both old and new thresholds are accepted
		PowDifficultyAllowance: 2, // in blocks

		// Username limits
		MinUsernameSize: 3,
		MaxUsernameSize: 30,
		MinTopicSize:    2,
		MaxTopicSize:    35,

		// Subscription period in minutes (0 = one-time, 43200 = 30 days)
		SubscriptionPeriod: 43200,

		// Tier configurations
		Tiers: DefaultTiers(),

		// Fraction of period fee escrowed as gas reserve [0,1] (remainder burned)
		SubscriptionReservePercent: 0.95,

		// Min gas price for relayed txs in umirage per gas unit
		// Fee = gasConsumed * RelayMinGasPrice (no divisor)
		RelayMinGasPrice: 1000,

		// Max fee deducted per relayed tx in umirage (500 MIRAGE cap)
		RelayMaxGasFee: 500_000_000,

		// Max age in seconds for envelope_timestamp (replay protection)
		MaxEnvelopeAge: 60,

		// Bridge parameters
		BridgeChains:               []*BridgeChainConfig{}, // No chains enabled by default, fee is per-chain
		BridgeAttestationThreshold: 0.6667,                 // 66.67% of voting power required

		// Award configurations (cost in umirage; 1 MIRAGE = 1,000,000 umirage)
		AwardConfigs: DefaultAwardConfigs(),
	}
}

// Validate validates the set of params.
func (p Params) Validate() error {
	if p.MinDifficulty == 0 || p.MinDifficulty > 256 {
		return fmt.Errorf("min_difficulty must be in [1,256]")
	}
	if p.PowMessageWindow == 0 {
		return fmt.Errorf("pow_message_window must be > 0")
	}
	if p.PowMessageLimit == 0 {
		return fmt.Errorf("pow_message_limit must be > 0")
	}
	if p.PowCalmPeriodDefinition >= p.PowMessageLimit {
		return fmt.Errorf("pow_calm_period_definition must be < pow_message_limit")
	}
	if p.PowCalmSequenceThreshold == 0 {
		return fmt.Errorf("pow_calm_sequence_threshold must be > 0")
	}
	if p.MintInterval == 0 {
		return fmt.Errorf("mint_interval must be > 0")
	}
	if p.MintQuantity == 0 {
		return fmt.Errorf("mint_quantity must be > 0")
	}
	if p.MintDynamicSplit < 0 || p.MintDynamicSplit > 1 {
		return fmt.Errorf("mint_dynamic_split must be in [0,1]")
	}
	if p.BlockHashWindow == 0 || p.BlockHashWindow > 1000 {
		return fmt.Errorf("block_hash_window must be in [1,1000]")
	}
	if p.PowDifficultyAllowance > p.PowMessageWindow*2 {
		return fmt.Errorf("pow_difficulty_allowance must be <= 2*pow_message_window")
	}
	if p.MaxUsernameSize == 0 || p.MaxUsernameSize > 128 {
		return fmt.Errorf("max_username_size must be in [1,128]")
	}
	if p.MaxTopicSize == 0 || p.MaxTopicSize > 100 {
		return fmt.Errorf("max_topic_size must be in [1,100]")
	}
	if p.MinTopicSize == 0 || p.MinTopicSize > p.MaxTopicSize {
		return fmt.Errorf("min_topic_size must be in [1,max_topic_size]")
	}
	if p.MinUsernameSize == 0 || p.MinUsernameSize > 64 {
		return fmt.Errorf("min_username_size must be in [1,64]")
	}
	if p.MinUsernameSize > p.MaxUsernameSize {
		return fmt.Errorf("min_username_size must be <= max_username_size")
	}
	// SubscriptionReservePercent must be in [0,1]
	if p.SubscriptionReservePercent < 0 || p.SubscriptionReservePercent > 1 {
		return fmt.Errorf("subscription_reserve_percent must be in [0,1]")
	}
	// PowDifficultyStep must be in (0,1]
	if p.PowDifficultyStep <= 0 || p.PowDifficultyStep > 1 {
		return fmt.Errorf("pow_difficulty_step must be in (0,1]")
	}
	// MaxEnvelopeAge must be > 0 (replay protection)
	if p.MaxEnvelopeAge == 0 {
		return fmt.Errorf("max_envelope_age must be > 0")
	}
	// Validate tiers
	if len(p.Tiers) == 0 {
		return fmt.Errorf("tiers must not be empty")
	}
	// Free tier (index 0) must have 0 monthly fee
	if p.Tiers[0].PeriodFee != 0 {
		return fmt.Errorf("tier 0 (free) must have period_fee = 0")
	}
	for i, tier := range p.Tiers {
		if tier.MaxTitleLength == 0 {
			return fmt.Errorf("tier %d: max_title_length must be > 0", i)
		}
		if tier.MaxContentLength == 0 {
			return fmt.Errorf("tier %d: max_content_length must be > 0", i)
		}
		if tier.VoteWeight < 0 {
			return fmt.Errorf("tier %d: vote_weight must be >= 0", i)
		}
	}
	// Validate bridge params
	if p.BridgeAttestationThreshold <= 0 || p.BridgeAttestationThreshold > 1 {
		return fmt.Errorf("bridge_attestation_threshold must be in (0,1]")
	}
	// Validate award configs
	if len(p.AwardConfigs) == 0 {
		return fmt.Errorf("award_configs must not be empty")
	}
	awardNames := make(map[string]bool)
	for i, ac := range p.AwardConfigs {
		if ac.Name == "" {
			return fmt.Errorf("award_configs[%d]: name must not be empty", i)
		}
		if awardNames[ac.Name] {
			return fmt.Errorf("award_configs[%d]: duplicate name %q", i, ac.Name)
		}
		awardNames[ac.Name] = true
	}
	return nil
}

// GetAwardConfig returns the award config for the given name, or nil if not found.
func (p Params) GetAwardConfig(name string) *AwardConfig {
	for _, ac := range p.AwardConfigs {
		if ac.Name == name {
			return ac
		}
	}
	return nil
}

// GetTierConfig returns the tier config for the given user level.
// Maps user levels (0, 1, 10, 100+) to tier array indices (0, 1, 2).
// Returns nil for invalid levels (2-9, negative).
func (p Params) GetTierConfig(level int) *TierConfig {
	if len(p.Tiers) == 0 {
		return nil
	}
	idx := LevelToTierIndex(level)
	if idx < 0 || idx >= len(p.Tiers) {
		return nil
	}
	return p.Tiers[idx]
}
