package types

import (
	"fmt"
	"math"
)

// Valid user levels. Only these levels can be assigned to a profile.
// Levels 2-9 are reserved for future subscription tiers.
const (
	LevelFree       = 0
	LevelSubscriber = 1
	LevelAgent      = 10
	LevelAdminMin   = 100
)

// Governance-safe upper bounds for key economics parameters.
const (
	MaxMintQuantity      = 10_000_000_000_000 // 10M MIRAGE per interval
	MaxVoteWeight        = 100.0              // no single tier gets >100x weight
	MaxRelayMinGasPrice  = 1_000_000_000      // 1000 MIRAGE per gas unit
	MaxRelayMaxGasFee    = 100_000_000_000    // 100k MIRAGE per tx
	MaxAwardConfigCost   = 1_000_000_000_000  // 1M MIRAGE per award
	MinPowDifficultyStep = 0.01
)

// Governance-safe upper bounds for parameters that size loops, windows, and time
// arithmetic. Without them a single proposal can make EndBlock sweep an
// unbounded key range, overflow an expiry, or stall difficulty adjustment
// forever (review M-7).
const (
	// MaxPowMessageWindow bounds the sliding window swept every block. Aligned
	// with the existing block_hash_window cap of 1000.
	MaxPowMessageWindow = 1_000
	// MaxMintInterval is roughly one year at the documented 3s block time.
	MaxMintInterval = 10_512_000
	// MaxSubscriptionPeriodMinutes is one year.
	MaxSubscriptionPeriodMinutes = 525_600
	// MaxEnvelopeAgeSeconds is one day.
	MaxEnvelopeAgeSeconds = 86_400
	// MaxProfileListEntries keeps uint64 governance values representable by
	// the uint32 counters used by profile-list storage.
	MaxProfileListEntries = math.MaxUint32
	// MaxPowCalmSequenceThreshold keeps the calm counter in a range that can
	// actually be reached, so difficulty can still fall.
	MaxPowCalmSequenceThreshold = 1_000_000
	// MinBlockHashWindow keeps the PoW recent-block-hash window from becoming a
	// stricter freshness rule than MaxEnvelopeAge, which would reject work the
	// age check still accepts. At the 2s block time the local chain runs and the
	// 3s the node template configures, 20 blocks is 40-60s against that param's
	// 60s default, so this is a floor and not a target; DefaultParams uses 60.
	//
	// It is deliberately NOT enforced in Validate(). The live genesis carries
	// block_hash_window 10, and InitGenesis only substitutes defaults when the
	// value is zero, so a floor in Validate() would panic InitGenesis on this
	// binary and break every node that starts from genesis. It is enforced where
	// it can be: the v1.34.0 handler widens a stored value below the floor, and
	// verify_upgrade.py bounds the live chain.
	MinBlockHashWindow = 20
)

// ValidSubscriptionLevels are the levels users can subscribe to via MsgSubscribe.
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
			PeriodFee:          0,
			MaxEnabledAgents:   5,
			MaxFollowedUsers:   25,
			MaxFollowedTopics:  25,
			MaxBlockedUsers:    25,
			MaxBlockedPosts:    25,
			MaxBlockedTopics:   25,
			MaxTitleLength:     150,
			MaxContentLength:   1000,
			EditingTimeMins:    10,
			VoteWeight:         1.0,
			CanBeAgent:         false,
			CanRemoveAnon:      false,
			CanHaveBiography:   false,
			CanHaveAvatar:      false,
			CanHaveBanner:      false,
			CanHaveFlair:       false,
			MaxBiographyLength: 0,
		},
		// Index 1 — Level 1: Subscriber (100B umirage)
		{
			PeriodFee:          100_000_000_000,
			MaxEnabledAgents:   50,
			MaxFollowedUsers:   500,
			MaxFollowedTopics:  500,
			MaxBlockedUsers:    500,
			MaxBlockedPosts:    500,
			MaxBlockedTopics:   500,
			MaxTitleLength:     300,
			MaxContentLength:   20000,
			EditingTimeMins:    360,
			VoteWeight:         1.33,
			CanBeAgent:         false,
			CanRemoveAnon:      true,
			CanHaveBiography:   true,
			CanHaveAvatar:      true,
			CanHaveBanner:      true,
			CanHaveFlair:       true,
			MaxBiographyLength: 512,
		},
		// Index 2 — Level 10: Agent (500B umirage)
		{
			PeriodFee:          500_000_000_000,
			MaxEnabledAgents:   50,
			MaxFollowedUsers:   500,
			MaxFollowedTopics:  500,
			MaxBlockedUsers:    500,
			MaxBlockedPosts:    500,
			MaxBlockedTopics:   500,
			MaxTitleLength:     300,
			MaxContentLength:   20000,
			EditingTimeMins:    360,
			VoteWeight:         1.33,
			CanBeAgent:         true,
			CanRemoveAnon:      true,
			CanHaveBiography:   true,
			CanHaveAvatar:      true,
			CanHaveBanner:      true,
			CanHaveFlair:       true,
			MaxBiographyLength: 512,
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

		// PoW difficulty step: factor = 1000 * (1+pow_difficulty_step)^difficulty, steps +/-1
		PowDifficultyStep: 0.25,

		// PoW message window
		PowMessageWindow:         20,  // sliding window in blocks for difficulty adjustment; 20 = 1 min
		PowMessageLimit:          15,  // if >= this many pow msgs in window, increase difficulty
		PowCalmPeriodDefinition:  10,  // if < this many pow msgs in window, calm period
		PowCalmSequenceThreshold: 100, // consecutive calm periods before decreasing difficulty; 100 = 5 mins

		// PoW validation. Must stay above MaxEnvelopeAge expressed in blocks
		// (60s / ~3s per block = 20), or the window rejects envelopes the age
		// check still accepts. 60 blocks is ~3 min, three times that floor.
		// The backend serves clients from the same window (get_recent_block_hashes
		// reads this param), so both sides widen together.
		BlockHashWindow: 60, // in blocks; how many recent block hashes to accept for PoW validation

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

		// Fraction of period fee escrowed as gas reserve in basis points
		// (remainder burned). The float field it replaces stays 0; see Validate.
		SubscriptionReserveBps: 9_500,

		// Min gas price for relayed txs in umirage per gas unit
		// Fee = gasConsumed * RelayMinGasPrice (no divisor)
		RelayMinGasPrice: 1000,

		// Max fee deducted per relayed tx in umirage (500 MIRAGE cap)
		RelayMaxGasFee: 500_000_000,

		// Max age in seconds for envelope_timestamp (replay protection)
		MaxEnvelopeAge: 60,

		// Award configurations (cost in umirage; 1 MIRAGE = 1,000,000 umirage)
		AwardConfigs: DefaultAwardConfigs(),
	}
}

// Validate validates the set of params.
func (p Params) Validate() error {
	if p.MinDifficulty == 0 || p.MinDifficulty > 256 {
		return fmt.Errorf("min_difficulty must be in [1,256]")
	}
	if p.PowMessageWindow == 0 || p.PowMessageWindow > MaxPowMessageWindow {
		return fmt.Errorf("pow_message_window must be in [1,%d]", MaxPowMessageWindow)
	}
	if p.PowMessageLimit == 0 {
		return fmt.Errorf("pow_message_limit must be > 0")
	}
	if p.PowCalmPeriodDefinition >= p.PowMessageLimit {
		return fmt.Errorf("pow_calm_period_definition must be < pow_message_limit")
	}
	if p.PowCalmSequenceThreshold == 0 || p.PowCalmSequenceThreshold > MaxPowCalmSequenceThreshold {
		return fmt.Errorf("pow_calm_sequence_threshold must be in [1,%d]", MaxPowCalmSequenceThreshold)
	}
	if p.MintInterval == 0 || p.MintInterval > MaxMintInterval {
		return fmt.Errorf("mint_interval must be in [1,%d]", MaxMintInterval)
	}
	if p.MintQuantity == 0 {
		return fmt.Errorf("mint_quantity must be > 0")
	}
	if p.MintQuantity > MaxMintQuantity {
		return fmt.Errorf("mint_quantity %d exceeds max %d", p.MintQuantity, MaxMintQuantity)
	}
	if math.IsNaN(p.MintDynamicSplit) || math.IsInf(p.MintDynamicSplit, 0) ||
		p.MintDynamicSplit < 0 || p.MintDynamicSplit > 1 {
		return fmt.Errorf("mint_dynamic_split must be in [0,1]")
	}
	// The floor exists because the PoW ante rejects an envelope whose
	// last_block_hash has aged out of this window. Set it below the envelope age
	// limit in blocks and the window silently becomes the binding freshness rule,
	// rejecting work the age check still accepts. 20 blocks is MaxEnvelopeAge's
	// 60s default at the ~3s block time PowMessageWindow already assumes.
	// The lower bound stays at 1, not MinBlockHashWindow: the live genesis stores
	// 10 and InitGenesis panics on a SetParams error, so a floor here would stop
	// every from-genesis node from producing a block. See MinBlockHashWindow.
	if p.BlockHashWindow == 0 || p.BlockHashWindow > 1000 {
		return fmt.Errorf("block_hash_window must be in [1,1000]")
	}
	allowanceCeiling, err := CheckedMulUint64(p.PowMessageWindow, 2)
	if err != nil {
		return fmt.Errorf("pow_message_window %d: %w", p.PowMessageWindow, err)
	}
	if p.PowDifficultyAllowance > allowanceCeiling {
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
	if p.SubscriptionReserveBps > BasisPointsDenominator {
		return fmt.Errorf("subscription_reserve_bps must be in [0,%d]", BasisPointsDenominator)
	}
	// SubscriptionReservePercent is deliberately unconstrained. It is superseded
	// by SubscriptionReserveBps and nothing reads it, but rejecting a non-zero
	// value here would make a from-genesis replay impossible: the v1.5.0, v1.8.0,
	// and v1.11.0 handlers set it and call SetParams, which validates. Governance
	// cannot reach it either way — it has no paramFieldSetters entry, so an
	// update_mask naming it is rejected as an unsupported path.
	// PowDifficultyStep must be large enough that exact rational
	// exponentiation reaches its cap without unbounded intermediate growth.
	if math.IsNaN(p.PowDifficultyStep) || math.IsInf(p.PowDifficultyStep, 0) ||
		p.PowDifficultyStep < MinPowDifficultyStep || p.PowDifficultyStep > 1 {
		return fmt.Errorf("pow_difficulty_step must be in [%.2f,1]", MinPowDifficultyStep)
	}
	// Relay gas price bounds
	if p.RelayMinGasPrice > MaxRelayMinGasPrice {
		return fmt.Errorf("relay_min_gas_price %d exceeds max %d", p.RelayMinGasPrice, MaxRelayMinGasPrice)
	}
	if p.RelayMaxGasFee > MaxRelayMaxGasFee {
		return fmt.Errorf("relay_max_gas_fee %d exceeds max %d", p.RelayMaxGasFee, MaxRelayMaxGasFee)
	}
	// MaxEnvelopeAge must be > 0 (replay protection)
	if p.MaxEnvelopeAge == 0 || p.MaxEnvelopeAge > MaxEnvelopeAgeSeconds {
		return fmt.Errorf("max_envelope_age must be in [1,%d]", MaxEnvelopeAgeSeconds)
	}
	// SubscriptionPeriod of 0 selects documented one-time-payment mode.
	if p.SubscriptionPeriod > MaxSubscriptionPeriodMinutes {
		return fmt.Errorf("subscription_period must be in [0,%d]", MaxSubscriptionPeriodMinutes)
	}
	// Validate tiers
	if len(p.Tiers) != 3 {
		return fmt.Errorf("tiers must contain exactly 3 entries")
	}
	// Free tier (index 0) must have 0 monthly fee
	if p.Tiers[0] == nil {
		return fmt.Errorf("tier 0 must not be nil")
	}
	if p.Tiers[0].PeriodFee != 0 {
		return fmt.Errorf("tier 0 (free) must have period_fee = 0")
	}
	for i, tier := range p.Tiers {
		if tier == nil {
			return fmt.Errorf("tier %d must not be nil", i)
		}
		if tier.MaxTitleLength == 0 {
			return fmt.Errorf("tier %d: max_title_length must be > 0", i)
		}
		if tier.MaxContentLength == 0 {
			return fmt.Errorf("tier %d: max_content_length must be > 0", i)
		}
		listLimits := []struct {
			name  string
			value uint64
		}{
			{"max_enabled_agents", tier.MaxEnabledAgents},
			{"max_followed_users", tier.MaxFollowedUsers},
			{"max_followed_topics", tier.MaxFollowedTopics},
			{"max_blocked_users", tier.MaxBlockedUsers},
			{"max_blocked_posts", tier.MaxBlockedPosts},
			{"max_blocked_topics", tier.MaxBlockedTopics},
		}
		for _, limit := range listLimits {
			if limit.value > MaxProfileListEntries {
				return fmt.Errorf("tier %d: %s %d exceeds max %d",
					i, limit.name, limit.value, MaxProfileListEntries)
			}
		}
		if math.IsNaN(tier.VoteWeight) || math.IsInf(tier.VoteWeight, 0) {
			return fmt.Errorf("tier %d: vote_weight must be finite", i)
		}
		if tier.VoteWeight < 0 {
			return fmt.Errorf("tier %d: vote_weight must be >= 0", i)
		}
		if tier.VoteWeight > MaxVoteWeight {
			return fmt.Errorf("tier %d: vote_weight %.2f exceeds max %.2f", i, tier.VoteWeight, MaxVoteWeight)
		}
	}
	// Validate award configs
	if len(p.AwardConfigs) == 0 {
		return fmt.Errorf("award_configs must not be empty")
	}
	awardNames := make(map[string]bool)
	for i, ac := range p.AwardConfigs {
		if ac == nil {
			return fmt.Errorf("award_configs[%d] must not be nil", i)
		}
		if ac.Name == "" {
			return fmt.Errorf("award_configs[%d]: name must not be empty", i)
		}
		if awardNames[ac.Name] {
			return fmt.Errorf("award_configs[%d]: duplicate name %q", i, ac.Name)
		}
		awardNames[ac.Name] = true
		if ac.Cost > MaxAwardConfigCost {
			return fmt.Errorf("award_configs[%d]: cost %d exceeds max allowed %d", i, ac.Cost, MaxAwardConfigCost)
		}
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
