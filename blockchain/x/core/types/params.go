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
	LevelAdminMin   = 100
)

// LevelAgent is the retired v1.16–v1.38 paid tier. Kept so historical
// upgrade handlers and decode paths can name it; it is not a valid
// current subscription level.
const LevelAgent = 10

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
	// age check still accepts. At the 3s block time the fleet and the local
	// testnet run, 20 blocks is exactly MaxEnvelopeAge's 60s default, so this is
	// a hard floor with no margin, not a target; DefaultParams uses 60 (180s).
	//
	// It is deliberately NOT enforced in Validate(). The live genesis carries
	// block_hash_window 10, and InitGenesis only substitutes defaults when the
	// value is zero, so a floor in Validate() would panic InitGenesis on this
	// binary and break every node that starts from genesis. It is enforced where
	// it can be: ValidateGovernanceUpdate below rejects a proposal that would set
	// it lower, the v1.34.0 handler widens a stored value below the floor, and
	// verify_upgrade.py bounds the live chain.
	MinBlockHashWindow = 20

	// MaxGovernableMinDifficulty caps min_difficulty at a value proof of work can
	// actually satisfy. The target is derived by right-shifting the maximum hash
	// by this many bits, so at 256 the target is exactly zero and no Argon2id
	// output can ever clear it: every free-tier message is rejected in the ante
	// while paid tiers, being PoW-exempt, notice nothing. Anything above roughly
	// 40 is already unsatisfiable in practice; 32 is generous against a default
	// of 10. Governance-path only, for the same replay reason as the floor above.
	MaxGovernableMinDifficulty = 32

	// SupplyFullScanInterval is how often EndBlock runs the O(accounts)
	// supply-vs-balances scan. The O(1) delta check still runs every block; only
	// the full walk is periodic, because its cost is charged to no transaction
	// while the set it walks is user-growable and irreversible (review M-5).
	//
	// Not a governance parameter on purpose: it decides at which heights a node
	// halts, so a proposal setting it to 0 or to a huge value would either divide
	// by zero or disable the divergence guard outright.
	//
	// At the documented 3s block time this is a full scan every five minutes and
	// a bounded detection delay of the same, against a twenty-fold reduction in
	// per-block lifecycle work.
	SupplyFullScanInterval = 100
)

// ValidSubscriptionLevels are the levels users can subscribe to via MsgSubscribe.
var ValidSubscriptionLevels = map[int]bool{
	LevelSubscriber: true,
}

// LevelToTierIndex maps a user level to the index in the Tiers array.
// Returns -1 for invalid/unsupported levels.
func LevelToTierIndex(level int) int {
	switch {
	case level == LevelFree:
		return 0
	case level == LevelSubscriber:
		return 1
	case level >= LevelAdminMin:
		return 2
	default:
		return -1
	}
}

// CanCurate reports whether a profile may lead or join curator teams.
// Paid subscribers and admins (level >= 100) are eligible; free accounts are not.
func CanCurate(core ProfileCore) bool {
	return core.EffectivePaid || int(core.Level) >= LevelAdminMin
}

// UsesRelayPath reports whether this tier skips PoW and consumes a daily relay quota.
func (t *TierConfig) UsesRelayPath() bool {
	return t != nil && t.MaxDailyRelays > 0
}

// DailyRelayLimit returns the UTC-day envelope quota for a user level.
// 0 means the account uses proof of work (no relay quota).
func (p Params) DailyRelayLimit(level int) uint64 {
	tier := p.GetTierConfig(level)
	if tier == nil {
		return 0
	}
	return tier.MaxDailyRelays
}

// HistoricalDefaultTiers is the three-tier config written by pre-v1.39
// upgrade handlers. Do not use for current defaults.
func HistoricalDefaultTiers() []*TierConfig {
	return []*TierConfig{
		{
			PeriodFee:             0,
			MaxFollowedUsers:      25,
			MaxJoinedCommunities:  25,
			MaxBlockedUsers:       25,
			MaxBlockedPosts:       25,
			MaxBlockedCommunities: 25,
			MaxTitleLength:        150,
			MaxContentLength:      1000,
			EditingTimeMins:       10,
			VoteWeight:            1.0,
			CanHaveBiography:      false,
			CanHaveAvatar:         false,
			CanHaveBanner:         false,
			CanHaveFlair:          false,
			MaxBiographyLength:    0,
		},
		{
			PeriodFee:             100_000_000_000,
			MaxFollowedUsers:      500,
			MaxJoinedCommunities:  500,
			MaxBlockedUsers:       500,
			MaxBlockedPosts:       500,
			MaxBlockedCommunities: 500,
			MaxTitleLength:        300,
			MaxContentLength:      20000,
			EditingTimeMins:       360,
			VoteWeight:            1.33,
			CanHaveBiography:      true,
			CanHaveAvatar:         true,
			CanHaveBanner:         true,
			CanHaveFlair:          true,
			MaxBiographyLength:    512,
		},
		{
			PeriodFee:             500_000_000_000,
			MaxFollowedUsers:      500,
			MaxJoinedCommunities:  500,
			MaxBlockedUsers:       500,
			MaxBlockedPosts:       500,
			MaxBlockedCommunities: 500,
			MaxTitleLength:        300,
			MaxContentLength:      20000,
			EditingTimeMins:       360,
			VoteWeight:            1.33,
			CanHaveBiography:      true,
			CanHaveAvatar:         true,
			CanHaveBanner:         true,
			CanHaveFlair:          true,
			MaxBiographyLength:    512,
		},
	}
}

func DefaultTiers() []*TierConfig {
	return []*TierConfig{
		{
			PeriodFee:              0,
			MaxFollowedUsers:       25,
			MaxJoinedCommunities:   25,
			MaxBlockedUsers:        25,
			MaxBlockedPosts:        25,
			MaxBlockedCommunities:  25,
			MaxTitleLength:         150,
			MaxContentLength:       1000,
			EditingTimeMins:        10,
			VoteWeight:             1.0,
			CanHaveBiography:       false,
			CanHaveAvatar:          false,
			CanHaveBanner:          false,
			CanHaveFlair:           false,
			MaxBiographyLength:     0,
			MaxCurationMemberships: 0,
			MaxDailyRelays:         0,
		},
		{
			PeriodFee:              100_000_000_000,
			MaxFollowedUsers:       500,
			MaxJoinedCommunities:   500,
			MaxBlockedUsers:        500,
			MaxBlockedPosts:        500,
			MaxBlockedCommunities:  500,
			MaxTitleLength:         300,
			MaxContentLength:       20000,
			EditingTimeMins:        360,
			VoteWeight:             1.33,
			CanHaveBiography:       true,
			CanHaveAvatar:          true,
			CanHaveBanner:          true,
			CanHaveFlair:           true,
			MaxBiographyLength:     512,
			MaxCurationMemberships: 10,
			MaxDailyRelays:         250,
		},
		{
			// Admin is appointed via governance, not purchased. PeriodFee must stay 0.
			PeriodFee:              0,
			MaxFollowedUsers:       500,
			MaxJoinedCommunities:   500,
			MaxBlockedUsers:        500,
			MaxBlockedPosts:        500,
			MaxBlockedCommunities:  500,
			MaxTitleLength:         300,
			MaxContentLength:       20000,
			EditingTimeMins:        360,
			VoteWeight:             1.33,
			CanHaveBiography:       true,
			CanHaveAvatar:          true,
			CanHaveBanner:          true,
			CanHaveFlair:           true,
			MaxBiographyLength:     512,
			MaxCurationMemberships: 1000,
			MaxDailyRelays:         1000,
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
// These defaults reflect v1.39.0 economics (Free=0, Subscriber=1, Admin>=100).
func DefaultParams() Params {
	return Params{
		// Minting
		MintInterval:         200,             // in blocks; one block = every 3 secs, i.e. every 10 mins we mint
		MintQuantity:         125_000_000_000, // 125,000 MIRAGE per 10min
		MintDynamicCreditCap: 25,              // default cap per interval per validator (same as default PowMessageLimit)
		MintFloorSplit:       0.20,
		MintDynamicSplit:     0.10,

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
		MinUsernameSize:  3,
		MaxUsernameSize:  30,
		MinCommunitySize: 2,
		MaxCommunitySize: 35,

		// Subscription period in minutes (43200 = 30 days)
		SubscriptionPeriod: 43200,

		Tiers: DefaultTiers(),

		SubscriptionReserveBps: 0,
		SubscriptionCreatorBps: 5_000,

		RelayMinGasPrice: 1000,
		RelayMaxGasFee:   500_000_000,
		MaxEnvelopeAge:   60,
		AwardConfigs:     DefaultAwardConfigs(),

		MaxCuratorsPerTeam:                  10,
		MaxPendingCuratorInvitesPerTeam:     10,
		MaxPendingCuratorInvitesPerUser:     100,
		MaxCurationTeamNameLength:           30,
		MaxCurationTeamDescriptionLength:    800,
		SubscriptionTransitionsPerBlock:     100,
		CurationPruneKeysPerBlock:           500,
		CreatorEpochClosuresPerBlock:        4,
		CreatorSettlementRecordsPerBlock:    1000,
		CreatorPruneKeysPerBlock:            1000,
		CreatorClaimWindowDays:              30,
		MaxCreatorClaimEpochs:               30,
		MaxCreatorEngagementsPerEpoch:       1_000_000,
		CreatorEpochExpiriesPerBlock:        4,
		SubscriptionEarlyRenewalDays:        7,
		SubscriptionRenewalAttemptsPerBlock: 100,
		SubscriberDailyRelayLimit:           250,
		MaxSubscriptionPeriodsPerPurchase:   12,
	}
}

// HistoricalDefaultParams freezes pre-v1.39 defaults for upgrade handlers.
func HistoricalDefaultParams() Params {
	p := DefaultParams()
	p.Tiers = HistoricalDefaultTiers()
	p.SubscriptionReserveBps = 9_500
	p.SubscriptionCreatorBps = 0
	p.MaxCuratorsPerTeam = 0
	p.MaxPendingCuratorInvitesPerTeam = 0
	p.MaxPendingCuratorInvitesPerUser = 0
	p.MaxCurationTeamNameLength = 0
	p.MaxCurationTeamDescriptionLength = 0
	p.SubscriptionTransitionsPerBlock = 0
	p.CurationPruneKeysPerBlock = 0
	p.CreatorEpochClosuresPerBlock = 0
	p.CreatorSettlementRecordsPerBlock = 0
	p.CreatorPruneKeysPerBlock = 0
	p.CreatorClaimWindowDays = 0
	p.MaxCreatorClaimEpochs = 0
	p.MaxCreatorEngagementsPerEpoch = 0
	p.CreatorEpochExpiriesPerBlock = 0
	p.SubscriptionEarlyRenewalDays = 0
	p.SubscriptionRenewalAttemptsPerBlock = 0
	p.SubscriberDailyRelayLimit = 0
	p.MaxSubscriptionPeriodsPerPurchase = 0
	return p
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
	if math.IsNaN(p.MintFloorSplit) || math.IsInf(p.MintFloorSplit, 0) ||
		p.MintFloorSplit < 0 || p.MintFloorSplit > 1 {
		return fmt.Errorf("mint_floor_split must be in [0,1]")
	}
	// The stake pool is the remainder, so a sum above 1 would mint more than
	// MintQuantity. Checked here rather than in the keeper because MsgUpdateParams
	// can move either field independently.
	if p.MintFloorSplit+p.MintDynamicSplit > 1 {
		return fmt.Errorf("mint_floor_split + mint_dynamic_split must be <= 1, got %v", p.MintFloorSplit+p.MintDynamicSplit)
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
	if p.MaxCommunitySize > 100 {
		return fmt.Errorf("max_community_size must be in [0,100]")
	}
	if p.MinCommunitySize > 0 && p.MaxCommunitySize > 0 && p.MinCommunitySize > p.MaxCommunitySize {
		return fmt.Errorf("min_community_size must be <= max_community_size")
	}
	if p.MinCommunitySize > 100 {
		return fmt.Errorf("min_community_size must be in [0,100]")
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
	// Validate tiers. Pre-v1.39 blobs have 2 or 3; v1.39 requires exactly 3.
	if n := len(p.Tiers); n != 2 && n != 3 {
		return fmt.Errorf("tiers must contain exactly 2 or 3 entries")
	}
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
			{"max_followed_users", tier.MaxFollowedUsers},
			{"max_joined_communities", tier.MaxJoinedCommunities},
			{"max_blocked_users", tier.MaxBlockedUsers},
			{"max_blocked_posts", tier.MaxBlockedPosts},
			{"max_blocked_communities", tier.MaxBlockedCommunities},
			{"max_curation_memberships", tier.MaxCurationMemberships},
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
	if p.SubscriptionCreatorBps > BasisPointsDenominator {
		return fmt.Errorf("subscription_creator_bps must be in [0,%d]", BasisPointsDenominator)
	}
	return nil
}

func (p Params) ValidateV139() error {
	if err := p.Validate(); err != nil {
		return err
	}
	if len(p.Tiers) != 3 {
		return fmt.Errorf("v1.39: tiers must contain exactly 3 entries")
	}
	if p.Tiers[2].PeriodFee != 0 {
		return fmt.Errorf("v1.39: admin tier period_fee must be 0")
	}
	if p.MinCommunitySize == 0 || p.MaxCommunitySize == 0 || p.MinCommunitySize > p.MaxCommunitySize || p.MaxCommunitySize > 100 {
		return fmt.Errorf("v1.39: min/max_community_size must be in [1,100] with min <= max")
	}
	if p.SubscriptionReserveBps != 0 {
		return fmt.Errorf("v1.39: subscription_reserve_bps must be 0")
	}
	if p.SubscriptionCreatorBps != 5000 {
		return fmt.Errorf("v1.39: subscription_creator_bps must be 5000")
	}
	if p.SubscriptionPeriod < 1 || p.SubscriptionPeriod > MaxSubscriptionPeriodMinutes {
		return fmt.Errorf("subscription_period must be in [1,%d]", MaxSubscriptionPeriodMinutes)
	}
	if p.SubscriptionEarlyRenewalDays < 1 || p.SubscriptionEarlyRenewalDays > 30 {
		return fmt.Errorf("subscription_early_renewal_days must be in [1,30]")
	}
	if p.SubscriptionEarlyRenewalDays*1440 >= p.SubscriptionPeriod {
		return fmt.Errorf("subscription_early_renewal_days must be strictly shorter than subscription_period")
	}
	if p.SubscriberDailyRelayLimit < 1 || p.SubscriberDailyRelayLimit > 10000 {
		return fmt.Errorf("subscriber_daily_relay_limit must be in [1,10000]")
	}
	if p.Tiers[0].MaxDailyRelays != 0 {
		return fmt.Errorf("free tier max_daily_relays must be 0 (PoW path)")
	}
	if p.Tiers[1].MaxDailyRelays < 1 || p.Tiers[1].MaxDailyRelays > 10000 {
		return fmt.Errorf("subscriber tier max_daily_relays must be in [1,10000]")
	}
	if p.Tiers[1].MaxDailyRelays != p.SubscriberDailyRelayLimit {
		return fmt.Errorf("subscriber_daily_relay_limit must equal tiers[1].max_daily_relays")
	}
	if p.Tiers[2].MaxDailyRelays < 1 || p.Tiers[2].MaxDailyRelays > 10000 {
		return fmt.Errorf("admin tier max_daily_relays must be in [1,10000]")
	}
	if p.MaxSubscriptionPeriodsPerPurchase < 1 || p.MaxSubscriptionPeriodsPerPurchase > 12 {
		return fmt.Errorf("max_subscription_periods_per_purchase must be in [1,12]")
	}
	if p.SubscriptionPeriod > 527040/p.MaxSubscriptionPeriodsPerPurchase {
		return fmt.Errorf("subscription_period * max_subscription_periods_per_purchase exceeds 527040 minutes")
	}
	required := []struct {
		name string
		val  uint64
		min  uint64
		max  uint64
	}{
		{"max_curators_per_team", p.MaxCuratorsPerTeam, 1, 10},
		{"max_pending_curator_invites_per_team", p.MaxPendingCuratorInvitesPerTeam, 1, p.MaxCuratorsPerTeam},
		{"max_pending_curator_invites_per_user", p.MaxPendingCuratorInvitesPerUser, 1, 1000},
		{"max_curation_team_name_length", p.MaxCurationTeamNameLength, 1, 100000},
		{"max_curation_team_description_length", p.MaxCurationTeamDescriptionLength, 1, 100000},
		{"subscription_transitions_per_block", p.SubscriptionTransitionsPerBlock, 1, 100000},
		{"curation_prune_keys_per_block", p.CurationPruneKeysPerBlock, 1, 100000},
		{"creator_epoch_closures_per_block", p.CreatorEpochClosuresPerBlock, 1, 100000},
		{"creator_settlement_records_per_block", p.CreatorSettlementRecordsPerBlock, 1, 100000},
		{"creator_prune_keys_per_block", p.CreatorPruneKeysPerBlock, 1, 100000},
		{"creator_epoch_expiries_per_block", p.CreatorEpochExpiriesPerBlock, 1, 100000},
		{"subscription_renewal_attempts_per_block", p.SubscriptionRenewalAttemptsPerBlock, 1, 100000},
		{"creator_claim_window_days", p.CreatorClaimWindowDays, 1, 365},
		{"max_creator_claim_epochs", p.MaxCreatorClaimEpochs, 1, 30},
		{"max_creator_engagements_per_epoch", p.MaxCreatorEngagementsPerEpoch, 1, 10_000_000},
	}
	for _, r := range required {
		if r.val < r.min || r.val > r.max {
			return fmt.Errorf("%s must be in [%d,%d]", r.name, r.min, r.max)
		}
	}
	if p.Tiers[0].MaxCurationMemberships != 0 {
		return fmt.Errorf("free tier max_curation_memberships must be 0")
	}
	return nil
}

// ValidateGovernanceUpdate applies the constraints that a governance proposal
// must satisfy but a historical params blob need not.
//
// These live here rather than in Validate() for one reason: Validate() runs on
// every GetParams read, so a constraint added there is retroactively applied to
// every params blob the chain has ever stored. A from-genesis replay would then
// halt at the first height whose stored value predates the constraint — turning
// a governance guard into a liveness bug. The same reasoning is already recorded
// for MinBlockHashWindow and for the deprecated fields.
//
// Every value rejected here passes Validate() and breaks the chain in a way the
// upper bounds do not catch (review M-1).
func (p Params) ValidateGovernanceUpdate() error {
	// min_difficulty = 256 makes the PoW target exactly zero, so proof of work
	// becomes mathematically unsatisfiable and every free-tier user is censored
	// while paid tiers, being PoW-exempt, see nothing wrong.
	if p.MinDifficulty > MaxGovernableMinDifficulty {
		return fmt.Errorf("min_difficulty %d exceeds the governable maximum of %d: "+
			"the PoW target is max_hash >> min_difficulty, so anything this large is unsatisfiable "+
			"and censors every free-tier user", p.MinDifficulty, MaxGovernableMinDifficulty)
	}
	// Either relay fee input at zero makes calculateRelayFee return zero. Paid
	// tiers are PoW-exempt by design, so this fee is their only per-message cost:
	// at zero every paid tier gets unlimited free chain writes, and because their
	// reserves never drain they never hit the usage-based downgrade either.
	if p.RelayMinGasPrice == 0 {
		return fmt.Errorf("relay_min_gas_price must be > 0: zero removes the only per-message " +
			"cost paid tiers bear, since they are exempt from proof of work")
	}
	if p.RelayMaxGasFee == 0 {
		return fmt.Errorf("relay_max_gas_fee must be > 0: zero removes the only per-message " +
			"cost paid tiers bear, since they are exempt from proof of work")
	}
	if err := p.ValidateV139(); err != nil {
		return err
	}
	// A window shorter than this is a stricter freshness rule than
	// max_envelope_age, rejecting work the age check still accepts.
	if p.BlockHashWindow < MinBlockHashWindow {
		return fmt.Errorf("block_hash_window %d is below the floor of %d, which would make the "+
			"recent-hash window a stricter freshness rule than max_envelope_age",
			p.BlockHashWindow, MinBlockHashWindow)
	}
	// max_biography_length is documented as "0 = disabled", but the handler read
	// zero as "no limit", so a proposal turning biographies on for a tier without
	// also setting a length left that tier with no tier-level cap at all — bounded
	// only by the generic text validator (review I-6). Requiring the two fields to
	// agree removes the ambiguity at the source rather than picking one reading.
	for i, tier := range p.Tiers {
		if tier == nil {
			continue // Validate() already rejects this
		}
		if tier.CanHaveBiography && tier.MaxBiographyLength == 0 {
			return fmt.Errorf("tiers[%d]: can_have_biography is set but max_biography_length is 0, "+
				"which the field documents as disabled; set a length or disable biographies", i)
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
// Maps user levels (0, 1, 100+) to tier array indices (0, 1, 2).
// Returns nil for invalid levels (2-99 except 100+, and negative).
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
