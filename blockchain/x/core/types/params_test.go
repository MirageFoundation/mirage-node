package types

import (
	"bytes"
	"math"
	"os"
	"testing"

	"github.com/cosmos/gogoproto/jsonpb"
	"github.com/stretchr/testify/require"
)

func TestDefaultTiers(t *testing.T) {
	tiers := DefaultTiers()
	require.Len(t, tiers, 3, "expected 3 tiers: Free(0), Subscriber(1), Admin(2)")

	require.Equal(t, uint64(0), tiers[0].PeriodFee)
	require.Equal(t, uint64(25), tiers[0].MaxBlockedCommunities)
	require.Equal(t, uint64(0), tiers[0].MaxCurationMemberships)
	require.Equal(t, uint64(0), tiers[0].MaxDailyRelays)

	require.Equal(t, uint64(100_000_000_000), tiers[1].PeriodFee)
	require.Equal(t, uint64(500), tiers[1].MaxBlockedCommunities)
	require.Equal(t, uint64(10), tiers[1].MaxCurationMemberships)
	require.Equal(t, uint64(250), tiers[1].MaxDailyRelays)

	require.Equal(t, uint64(0), tiers[2].PeriodFee)
	require.Equal(t, uint64(1000), tiers[2].MaxCurationMemberships)
	require.Equal(t, uint64(1000), tiers[2].MaxDailyRelays)
}

func TestLevelToTierIndex(t *testing.T) {
	require.Equal(t, 0, LevelToTierIndex(0))
	require.Equal(t, 1, LevelToTierIndex(1))
	require.Equal(t, 2, LevelToTierIndex(100))
	require.Equal(t, 2, LevelToTierIndex(255))

	require.Equal(t, -1, LevelToTierIndex(2))
	require.Equal(t, -1, LevelToTierIndex(5))
	require.Equal(t, -1, LevelToTierIndex(9))
	require.Equal(t, -1, LevelToTierIndex(10))
	require.Equal(t, -1, LevelToTierIndex(-1))
}

func TestDailyRelayLimit(t *testing.T) {
	p := DefaultParams()
	require.Equal(t, uint64(0), p.DailyRelayLimit(0))
	require.Equal(t, uint64(250), p.DailyRelayLimit(1))
	require.Equal(t, uint64(1000), p.DailyRelayLimit(100))
	require.Equal(t, uint64(0), p.DailyRelayLimit(10), "retired agent level has no quota")
	require.False(t, p.GetTierConfig(0).UsesRelayPath())
	require.True(t, p.GetTierConfig(1).UsesRelayPath())
	require.True(t, p.GetTierConfig(100).UsesRelayPath())
}

func TestCanCurate(t *testing.T) {
	require.False(t, CanCurate(ProfileCore{Level: 0, EffectivePaid: false}))
	require.True(t, CanCurate(ProfileCore{Level: 1, EffectivePaid: true}))
	require.False(t, CanCurate(ProfileCore{Level: 1, EffectivePaid: false}))
	require.True(t, CanCurate(ProfileCore{Level: 100, EffectivePaid: false}))
	require.True(t, CanCurate(ProfileCore{Level: 100, EffectivePaid: true}))
}

func TestGetTierConfigMapping(t *testing.T) {
	p := DefaultParams()

	require.NotNil(t, p.GetTierConfig(0))
	require.NotNil(t, p.GetTierConfig(1))
	require.NotNil(t, p.GetTierConfig(100))
	require.Nil(t, p.GetTierConfig(10))
	require.Nil(t, p.GetTierConfig(2))
	require.Nil(t, p.GetTierConfig(5))
	require.Nil(t, p.GetTierConfig(9))
	require.Nil(t, p.GetTierConfig(-1))

	require.NotEqual(t, p.GetTierConfig(1), p.GetTierConfig(100))
	require.Equal(t, uint64(10), p.GetTierConfig(1).MaxCurationMemberships)
	require.Equal(t, uint64(1000), p.GetTierConfig(100).MaxCurationMemberships)
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
		{"mint_floor_split_nan", func(p *Params) { p.MintFloorSplit = math.NaN() }},
		{"mint_floor_split_inf", func(p *Params) { p.MintFloorSplit = math.Inf(1) }},
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

// TestMintSplitsCannotExceedWholeMint guards the invariant the keeper relies on:
// the stake pool is whatever is left after the floor and work pools, so a sum
// above 1 would mint more than mint_quantity. Governance can move either field
// on its own, so the combined bound has to live in Validate.
func TestMintSplitsCannotExceedWholeMint(t *testing.T) {
	p := DefaultParams()
	require.NoError(t, p.Validate())

	p.MintFloorSplit = 0.20
	p.MintDynamicSplit = 0.80
	require.NoError(t, p.Validate(), "summing to exactly 1 leaves an empty stake pool, which is legal")

	p.MintDynamicSplit = 0.81
	err := p.Validate()
	require.Error(t, err)
	require.Contains(t, err.Error(), "mint_floor_split + mint_dynamic_split")

	// Zero floor is what every pre-v1.38.0 stored Params blob decodes to, so it
	// has to stay valid alongside the live 0.75 dynamic split.
	p.MintFloorSplit = 0
	p.MintDynamicSplit = 0.75
	require.NoError(t, p.Validate())

	for _, bad := range []float64{-0.01, 1.01} {
		p = DefaultParams()
		p.MintFloorSplit = bad
		require.Error(t, p.Validate(), "mint_floor_split %v must be rejected", bad)
	}
}

// TestSubscriptionReserveBpsIsBounded covers the field that actually drives the
// reserve/burn split. The retired float is unconstrained by design, so this is
// the only bound standing between governance and an over-100% reserve.
func TestSubscriptionReserveBpsIsBounded(t *testing.T) {
	p := DefaultParams()
	require.Equal(t, uint64(0), p.SubscriptionReserveBps, "v1.39 default must be 0: there is no relay reserve")

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

// TestGenesisParamsStillValidate is the general form of the block_hash_window
// regression below: every bound added to Validate() must still accept the params
// a real genesis carries, because InitGenesis panics when SetParams fails and a
// genesis file cannot be edited after the fact. The fixture is the core params
// from the genesis a chain actually boots from, which is what
// scripts/reset_local_testnet.py builds from a state export.
//
// InitGenesis substitutes DefaultParams() only when min_difficulty,
// pow_message_window, mint_interval, mint_quantity or block_hash_window is zero,
// so a set-but-now-out-of-bounds value is passed straight through and panics. A
// new bound that this test rejects must either widen to admit the fixture or be
// enforced outside Validate(), the way MinBlockHashWindow is.
func TestGenesisParamsStillValidate(t *testing.T) {
	raw, err := os.ReadFile("testdata/genesis_core_params.json")
	require.NoError(t, err)

	var p Params
	require.NoError(t, (&jsonpb.Unmarshaler{AllowUnknownFields: true}).Unmarshal(bytes.NewReader(raw), &p),
		"fixture must decode through the same proto-JSON path InitGenesis uses")

	require.NoError(t, p.Validate(),
		"a real genesis must validate on this binary or every from-genesis node panics in InitGenesis")
	require.Zero(t, p.MintFloorSplit,
		"a pre-v1.38.0 params blob has no field 55 and must decode with the floor disabled")
}

// TestGenesisCarriesSubscriptionReserveBps is the M-1(c) regression test.
//
// The fixture used to have no subscription_reserve_bps key at all, so proto3
// decoded it as 0 — and zero is legal to Validate(), which is precisely why
// TestGenesisParamsStillValidate above passed while the chain was broken. Zero
// short-circuits the reserve split, so all three call sites burn the whole
// period fee and escrow nothing: the subscriber reaches level 1 with an empty
// reserve and is demoted to free on their very next relay message.
//
// Every chain started from this file ran inverted until the v1.34.0 handler
// executed, which includes every reset_local_testnet.py run.
func TestGenesisCarriesSubscriptionReserveBps(t *testing.T) {
	raw, err := os.ReadFile("testdata/genesis_core_params.json")
	require.NoError(t, err)

	var p Params
	require.NoError(t, (&jsonpb.Unmarshaler{AllowUnknownFields: true}).Unmarshal(bytes.NewReader(raw), &p))

	require.Equal(t, uint64(9_500), p.SubscriptionReserveBps,
		"historical genesis must still carry the pre-v1.39 95% reserve so InitGenesis can replay")
	require.Zero(t, DefaultParams().SubscriptionReserveBps,
		"v1.39 defaults have no relay reserve; the handler writes 0 at upgrade height")
}

// TestValidateGovernanceUpdateRejectsChainBreakingValues is the M-1(a)/(b)
// regression test. Each value here passes Validate() — that is the whole point
// of the finding — and breaks the chain in a way none of the upper bounds catch.
func TestValidateGovernanceUpdateRejectsChainBreakingValues(t *testing.T) {
	t.Run("min_difficulty 256 makes PoW unsatisfiable", func(t *testing.T) {
		p := DefaultParams()
		p.MinDifficulty = 256
		require.NoError(t, p.Validate(), "the finding is that this passes Validate()")
		require.ErrorContains(t, p.ValidateGovernanceUpdate(), "min_difficulty")
	})

	t.Run("min_difficulty at the governable ceiling is allowed", func(t *testing.T) {
		p := DefaultParams()
		p.MinDifficulty = MaxGovernableMinDifficulty
		require.NoError(t, p.ValidateGovernanceUpdate())
	})

	t.Run("zero relay_min_gas_price makes paid tiers free", func(t *testing.T) {
		p := DefaultParams()
		p.RelayMinGasPrice = 0
		require.NoError(t, p.Validate())
		require.ErrorContains(t, p.ValidateGovernanceUpdate(), "relay_min_gas_price")
	})

	t.Run("zero relay_max_gas_fee makes paid tiers free", func(t *testing.T) {
		p := DefaultParams()
		p.RelayMaxGasFee = 0
		require.NoError(t, p.Validate())
		require.ErrorContains(t, p.ValidateGovernanceUpdate(), "relay_max_gas_fee")
	})

	t.Run("nonzero subscription_reserve_bps is retired", func(t *testing.T) {
		p := DefaultParams()
		p.SubscriptionReserveBps = 9_500
		require.NoError(t, p.Validate())
		require.ErrorContains(t, p.ValidateGovernanceUpdate(), "subscription_reserve_bps")
	})

	t.Run("block_hash_window below the floor", func(t *testing.T) {
		p := DefaultParams()
		p.BlockHashWindow = MinBlockHashWindow - 1
		require.NoError(t, p.Validate(), "kept legal so a from-genesis replay still works")
		require.ErrorContains(t, p.ValidateGovernanceUpdate(), "block_hash_window")
	})

	t.Run("the defaults are governable", func(t *testing.T) {
		require.NoError(t, DefaultParams().ValidateGovernanceUpdate())
	})
}

// TestValidateGovernanceUpdateStaysOutOfTheReadPath pins the reason these checks
// are not in Validate(): GetParams validates on every read, so a constraint
// there is applied retroactively to every blob the chain has ever stored, and a
// from-genesis replay halts at the first height that predates it. The live
// genesis carries block_hash_window 10 and a zero reserve, and both must keep
// validating.
func TestValidateGovernanceUpdateStaysOutOfTheReadPath(t *testing.T) {
	p := DefaultParams()
	p.BlockHashWindow = 10
	p.SubscriptionReserveBps = 0
	p.RelayMinGasPrice = 0
	p.RelayMaxGasFee = 0

	require.NoError(t, p.Validate(),
		"historical values must still validate on the read path or replay halts")
	require.Error(t, p.ValidateGovernanceUpdate(),
		"but governance must not be able to set them")
}

// TestBlockHashWindowAcceptsTheGenesisValue guards a from-genesis start. The
// live genesis stores block_hash_window 10 and InitGenesis panics when SetParams
// fails, so raising the Validate() lower bound to MinBlockHashWindow would stop
// every node that starts from genesis from ever producing a block. The floor is
// enforced by the v1.34.0 handler and verify_upgrade.py instead.
func TestBlockHashWindowAcceptsTheGenesisValue(t *testing.T) {
	p := DefaultParams()
	require.Equal(t, uint64(60), p.BlockHashWindow, "default must span more than MaxEnvelopeAge")

	p.BlockHashWindow = 10
	require.NoError(t, p.Validate(),
		"the value stored in the live genesis must validate or InitGenesis panics")

	p.BlockHashWindow = 0
	require.Error(t, p.Validate(), "an unset window must still be rejected")

	p.BlockHashWindow = 1001
	require.Error(t, p.Validate(), "an unbounded window must still be rejected")
}

func TestParamsValidateRejectsNilEntries(t *testing.T) {
	p := DefaultParams()
	p.Tiers = p.Tiers[:1]
	require.EqualError(t, p.Validate(), "tiers must contain exactly 2 or 3 entries")

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
	require.NoError(t, p.ValidateBasic(3, 30))

	// 512 multi-byte runes should pass (each is 3 bytes in UTF-8)
	multiByteStr := ""
	for i := 0; i < 512; i++ {
		multiByteStr += "\u4e16" // Chinese character, 3 bytes
	}
	p = Profile{Username: "testuser", Biography: multiByteStr}
	require.NoError(t, p.ValidateBasic(3, 30))

	// 513 runes should fail (regardless of byte count)
	tooLong := multiByteStr + "\u4e16"
	p = Profile{Username: "testuser", Biography: tooLong}
	require.Error(t, p.ValidateBasic(3, 30))
	require.Contains(t, p.ValidateBasic(3, 30).Error(), "biography too long")

	// Avatar rune count
	p = Profile{Username: "testuser", Avatar: tooLong}
	require.Error(t, p.ValidateBasic(3, 30))
	require.Contains(t, p.ValidateBasic(3, 30).Error(), "avatar too long")

	// Banner rune count
	p = Profile{Username: "testuser", Banner: tooLong}
	require.Error(t, p.ValidateBasic(3, 30))
	require.Contains(t, p.ValidateBasic(3, 30).Error(), "banner too long")

	// Flair rune count (limit 20)
	flairOk := ""
	for i := 0; i < 20; i++ {
		flairOk += "\u4e16"
	}
	p = Profile{Username: "testuser", Flair: flairOk}
	require.NoError(t, p.ValidateBasic(3, 30))

	flairTooLong := flairOk + "\u4e16"
	p = Profile{Username: "testuser", Flair: flairTooLong}
	require.Error(t, p.ValidateBasic(3, 30))
	require.Contains(t, p.ValidateBasic(3, 30).Error(), "flair too long")
}

func TestValidateUsernameFormat(t *testing.T) {
	for _, ok := range []string{"alice", "Alice-Bob", "0alice", "a-b-c", "Anon-alice"} {
		require.NoError(t, ValidateUsernameFormat(ok), ok)
	}
	for _, bad := range []string{"-alice", "--alice", "-", "alice bob", "alice.bob", "alice@bob"} {
		require.EqualError(t, ValidateUsernameFormat(bad), "invalid username", bad)
	}
}

func TestFiveMinuteCreatorEpochParams(t *testing.T) {
	p := DefaultParams()
	p.CreatorEpochSeconds = 300
	p.SubscriptionPeriod = 60
	p.SubscriptionEarlyRenewalDays = 0
	p.MaxSubscriptionPeriodsPerPurchase = 1
	require.NoError(t, p.ValidateV139())

	p.CreatorEpochSeconds = 301
	require.ErrorContains(t, p.ValidateV139(), "must divide")

	p = DefaultParams()
	p.CreatorEpochSeconds = 300
	p.SubscriptionPeriod = MaxSubscriptionPeriodMinutes
	p.SubscriptionEarlyRenewalDays = 0
	p.MaxSubscriptionPeriodsPerPurchase = 1
	require.ErrorContains(t, p.ValidateV139(), "creator epochs")
}

func TestCreatorEpochClockDoesNotChangeDailyRelayEpoch(t *testing.T) {
	unix := int64(1_777_777_777)
	creatorEpoch, err := CreatorEpochFromUnix(unix, 300)
	require.NoError(t, err)
	require.Equal(t, unix/300, creatorEpoch)
	require.Equal(t, unix/SecondsPerUTCDay, UTCEpoch(unix))
	require.NotEqual(t, creatorEpoch, UTCEpoch(unix))

	deadline, err := CreatorClaimDeadline(creatorEpoch, 30, 300)
	require.NoError(t, err)
	require.Equal(t, creatorEpoch+30*288+1, deadline)
}

func TestC1BugCondition(t *testing.T) {
	// Reproduce the C-1 bug condition: the old code used
	//   if core.Level <= 0 || int(core.Level) >= len(params.Tiers)
	// With 3 historical tiers (indices 0,1,2), level 10 evaluates to
	// int(10) >= 3 = true, causing Agent users to skip renewal/downgrade.
	p := HistoricalDefaultParams()
	require.Len(t, p.Tiers, 3)

	level10 := 10
	buggySkip := level10 <= 0 || level10 >= len(p.Tiers)
	require.True(t, buggySkip, "demonstrates the old bug: level 10 was incorrectly skipped")

	// v1.39 retired Agent: level 10 is no longer a valid subscription level.
	require.Equal(t, -1, LevelToTierIndex(level10))
	require.Equal(t, 2, LevelToTierIndex(100), "admin maps to the admin tier")
}
