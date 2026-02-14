package types

import (
	"fmt"
)

// DefaultTiers returns the default tier configurations.
// Index 0 = Free, 1 = Trusted, 2 = Established, 3 = Distinguished
// Pricing assumes $0.00001/MIRAGE (post 10,000x multiplier economics)
func DefaultTiers() []*TierConfig {
	return []*TierConfig{
		// Level 0: Free
		{
			PeriodFee:           0,
			MaxFollowedMods:     5,
			MaxFollowedUsers:    25,
			MaxFollowedTopics:   50,
			MaxBlockedUsers:     10,
			MaxBlockedPosts:     25,
			MaxQualityPosts:     0,
			MaxTitleLength:      130,
			MaxContentLength:    1000,
			EditingTimeMins:     10,
			ArchiveDurationDays: 30,
			VoteWeight:          1.0,
			AwardPermissions:    0,
			EligibleForMod:      false,
			CanChangeName:       false,
			CanHaveBiography:    false,
			CanHaveAvatar:       false,
			CanHaveBanner:       false,
		},
		// Level 1: Trusted (100K MIRAGE = $1/mo at $0.00001/MIRAGE)
		{
			PeriodFee:           100_000_000_000,
			MaxFollowedMods:     10,
			MaxFollowedUsers:    125,
			MaxFollowedTopics:   250,
			MaxBlockedUsers:     125,
			MaxBlockedPosts:     100,
			MaxQualityPosts:     0,
			MaxTitleLength:      165,
			MaxContentLength:    2000,
			EditingTimeMins:     60,
			ArchiveDurationDays: 90,
			VoteWeight:          1.15,
			AwardPermissions:    1,
			EligibleForMod:      false,
			CanChangeName:       true,
			CanHaveBiography:    true,
			CanHaveAvatar:       true,
			CanHaveBanner:       true,
		},
		// Level 2: Established (200K MIRAGE = $2/mo at $0.00001/MIRAGE)
		{
			PeriodFee:           200_000_000_000,
			MaxFollowedMods:     25,
			MaxFollowedUsers:    500,
			MaxFollowedTopics:   500,
			MaxBlockedUsers:     500,
			MaxBlockedPosts:     200,
			MaxQualityPosts:     50,
			MaxTitleLength:      200,
			MaxContentLength:    5000,
			EditingTimeMins:     360,
			ArchiveDurationDays: 180,
			VoteWeight:          1.30,
			AwardPermissions:    2,
			EligibleForMod:      true,
			CanChangeName:       true,
			CanHaveBiography:    true,
			CanHaveAvatar:       true,
			CanHaveBanner:       true,
		},
		// Level 3: Distinguished (300K MIRAGE = $3/mo at $0.00001/MIRAGE)
		{
			PeriodFee:           300_000_000_000,
			MaxFollowedMods:     50,
			MaxFollowedUsers:    1000,
			MaxFollowedTopics:   1000,
			MaxBlockedUsers:     1000,
			MaxBlockedPosts:     500,
			MaxQualityPosts:     100,
			MaxTitleLength:      250,
			MaxContentLength:    25000,
			EditingTimeMins:     720,
			ArchiveDurationDays: 365,
			VoteWeight:          1.45,
			AwardPermissions:    3,
			EligibleForMod:      true,
			CanChangeName:       true,
			CanHaveBiography:    true,
			CanHaveAvatar:       true,
			CanHaveBanner:       true,
		},
	}
}

// DefaultParams returns a default set of parameters.
// These defaults reflect v1.8.0 economics (post 10,000x multiplier).
func DefaultParams() Params {
	return Params{
		// Minting
		MintInterval:         200,         // in blocks; one block = every 3 secs, i.e. every 10 mins we mint
		MintQuantity:         350_000_000, // 350 MIRAGE per 10min
		MintDynamicCreditCap: 25,          // default cap per interval per validator (same as default PowIncreaseThreshold)
		MintDynamicFraction:  0.5,         // 50% dynamic by default

		// pow_base_bits defines the base PoW target: base_target = 2^(256 - pow_base_bits)
		PowBaseBits: 10,

		// PoW factor size (fraction (0,1]): factor = 1000 * (1+pow_factor)^difficulty, steps +/-1
		PowFactor: 0.25,

		// PoW message window
		PowMessageWindow:         20,  // sliding window in blocks for difficulty adjustment; 20 = 1 min
		PowIncreaseThreshold:     15,  // if >= this many pow msgs in window, increase difficulty
		PowCalmPeriodDefinition:  10,  // if < this many pow msgs in window, calm period
		PowCalmSequenceThreshold: 100, // consecutive calm periods before decreasing difficulty; 100 = 5 mins

		// PoW validation
		BlockHashWindow: 10, // in blocks; how many recent block hashes to accept for PoW validation

		// Grace window during a difficulty change where both old and new thresholds are accepted
		PowDifficultyGracePeriod: 2, // in blocks

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
		SubscriptionReserveFraction: 0.80,

		// Min gas price for relayed txs in umirage per gas unit
		// Fee = gasConsumed * RelayMinGasPrice (no divisor)
		RelayMinGasPrice: 5000,

		// Max fee deducted per relayed tx in umirage (500 MIRAGE cap)
		RelayMaxGasFee: 500_000_000,

		// Max age in seconds for envelope_timestamp (replay protection)
		MaxEnvelopeAge: 60,

		// Bridge parameters
		BridgeChains:               []*BridgeChainConfig{}, // No chains enabled by default, fee is per-chain
		BridgeAttestationThreshold: 0.6667,                 // 66.67% of voting power required
	}
}

// Validate validates the set of params.
func (p Params) Validate() error {
	if p.PowBaseBits == 0 || p.PowBaseBits > 256 {
		return fmt.Errorf("pow_base_bits must be in [1,256]")
	}
	if p.PowMessageWindow == 0 {
		return fmt.Errorf("pow_message_window must be > 0")
	}
	if p.PowIncreaseThreshold == 0 {
		return fmt.Errorf("pow_increase_threshold must be > 0")
	}
	if p.PowCalmPeriodDefinition >= p.PowIncreaseThreshold {
		return fmt.Errorf("pow_calm_period_definition must be < pow_increase_threshold")
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
	if p.MintDynamicFraction < 0 || p.MintDynamicFraction > 1 {
		return fmt.Errorf("mint_dynamic_fraction must be in [0,1]")
	}
	if p.BlockHashWindow == 0 || p.BlockHashWindow > 1000 {
		return fmt.Errorf("block_hash_window must be in [1,1000]")
	}
	if p.PowDifficultyGracePeriod > p.PowMessageWindow*2 {
		return fmt.Errorf("pow_difficulty_grace_period must be <= 2*pow_message_window")
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
	// SubscriptionReserveFraction must be in [0,1]
	if p.SubscriptionReserveFraction < 0 || p.SubscriptionReserveFraction > 1 {
		return fmt.Errorf("subscription_reserve_fraction must be in [0,1]")
	}
	// PowFactor must be in (0,1]
	if p.PowFactor <= 0 || p.PowFactor > 1 {
		return fmt.Errorf("pow_factor must be in (0,1]")
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
	if len(p.Tiers) > 0 && p.Tiers[0].PeriodFee != 0 {
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
	return nil
}

// GetTierConfig returns the tier config for the given level.
// Returns the free tier for negative levels, highest tier for levels exceeding max.
func (p Params) GetTierConfig(level int) *TierConfig {
	if len(p.Tiers) == 0 {
		return nil
	}
	if level < 0 {
		return p.Tiers[0]
	}
	if level >= len(p.Tiers) {
		return p.Tiers[len(p.Tiers)-1]
	}
	return p.Tiers[level]
}
