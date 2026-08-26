package types

import (
	"math"
	"testing"
	"time"

	"github.com/stretchr/testify/require"
)

func TestCheckedUint64ToInt64(t *testing.T) {
	v, err := CheckedUint64ToInt64(math.MaxInt64)
	require.NoError(t, err)
	require.Equal(t, int64(math.MaxInt64), v)

	_, err = CheckedUint64ToInt64(uint64(math.MaxInt64) + 1)
	require.Error(t, err, "a value that would wrap negative must be rejected")
}

func TestCheckedMulUint64(t *testing.T) {
	got, err := CheckedMulUint64(0, math.MaxUint64)
	require.NoError(t, err)
	require.Equal(t, uint64(0), got)

	got, err = CheckedMulUint64(MaxPowMessageWindow, 2)
	require.NoError(t, err)
	require.Equal(t, uint64(2*MaxPowMessageWindow), got)

	_, err = CheckedMulUint64(math.MaxUint64/2+1, 2)
	require.Error(t, err)
}

func TestCheckedAddUint64(t *testing.T) {
	got, err := CheckedAddUint64(12, 34)
	require.NoError(t, err)
	require.Equal(t, uint64(46), got)

	_, err = CheckedAddUint64(math.MaxUint64, 1)
	require.Error(t, err)
}

func TestCheckedMulAndAddInt64(t *testing.T) {
	_, err := CheckedMulInt64(-1, 2)
	require.Error(t, err, "negative operands are a programming error, not a value to wrap")

	_, err = CheckedMulInt64(math.MaxInt64/2+1, 2)
	require.Error(t, err)

	got, err := CheckedAddInt64(math.MaxInt64-1, 1)
	require.NoError(t, err)
	require.Equal(t, int64(math.MaxInt64), got)

	_, err = CheckedAddInt64(math.MaxInt64, 1)
	require.Error(t, err)
}

func TestCheckedSubscriptionExpiry(t *testing.T) {
	base := int64(1_800_000_000)

	got, err := CheckedSubscriptionExpiry(base, 0)
	require.NoError(t, err)
	require.Equal(t, base, got, "one-time mode adds no period")

	got, err = CheckedSubscriptionExpiry(base, MaxSubscriptionPeriodMinutes)
	require.NoError(t, err)
	require.Equal(t, base+int64(MaxSubscriptionPeriodMinutes)*60, got)

	_, err = CheckedSubscriptionExpiry(base, MaxSubscriptionPeriodMinutes+1)
	require.Error(t, err, "a period past the governance bound must not produce an expiry")

	_, err = CheckedSubscriptionExpiry(math.MaxInt64, 1)
	require.Error(t, err, "an expiry that overflows must be rejected, not wrapped")
}

func TestCheckedWindowStartIsBounded(t *testing.T) {
	start, err := CheckedWindowStart(100, 20)
	require.NoError(t, err)
	require.Equal(t, int64(81), start)

	start, err = CheckedWindowStart(5, 20)
	require.NoError(t, err)
	require.Equal(t, int64(1), start, "the window never reaches below genesis")

	start, err = CheckedWindowStart(1_000_000, MaxPowMessageWindow)
	require.NoError(t, err)
	require.Equal(t, int64(1_000_000-MaxPowMessageWindow+1), start)

	_, err = CheckedWindowStart(1_000_000, MaxPowMessageWindow+1)
	require.Error(t, err, "a window past the bound would be an unbounded per-block sweep")

	_, err = CheckedWindowStart(100, 0)
	require.Error(t, err)
}

func TestCheckedEnvelopeAge(t *testing.T) {
	d, err := CheckedEnvelopeAge(60)
	require.NoError(t, err)
	require.Equal(t, 60*time.Second, d)

	d, err = CheckedEnvelopeAge(MaxEnvelopeAgeSeconds)
	require.NoError(t, err)
	require.Equal(t, time.Duration(MaxEnvelopeAgeSeconds)*time.Second, d)

	_, err = CheckedEnvelopeAge(0)
	require.Error(t, err)

	_, err = CheckedEnvelopeAge(MaxEnvelopeAgeSeconds + 1)
	require.Error(t, err)
}

// TestParamsBoundsRejectRunawayValues pins the M-7 operational caps: each
// parameter accepts its documented maximum and rejects max+1.
func TestParamsBoundsRejectRunawayValues(t *testing.T) {
	cases := map[string]struct {
		atMax   func(p *Params)
		overMax func(p *Params)
	}{
		"pow_message_window": {
			func(p *Params) { p.PowMessageWindow = MaxPowMessageWindow },
			func(p *Params) { p.PowMessageWindow = MaxPowMessageWindow + 1 },
		},
		"pow_calm_sequence_threshold": {
			func(p *Params) { p.PowCalmSequenceThreshold = MaxPowCalmSequenceThreshold },
			func(p *Params) { p.PowCalmSequenceThreshold = MaxPowCalmSequenceThreshold + 1 },
		},
		"mint_interval": {
			func(p *Params) { p.MintInterval = MaxMintInterval },
			func(p *Params) { p.MintInterval = MaxMintInterval + 1 },
		},
		"subscription_period": {
			func(p *Params) { p.SubscriptionPeriod = MaxSubscriptionPeriodMinutes },
			func(p *Params) { p.SubscriptionPeriod = MaxSubscriptionPeriodMinutes + 1 },
		},
		"max_envelope_age": {
			func(p *Params) { p.MaxEnvelopeAge = MaxEnvelopeAgeSeconds },
			func(p *Params) { p.MaxEnvelopeAge = MaxEnvelopeAgeSeconds + 1 },
		},
	}

	for name, tc := range cases {
		t.Run(name, func(t *testing.T) {
			atMax := DefaultParams()
			tc.atMax(&atMax)
			require.NoError(t, atMax.Validate(), "the documented maximum must remain valid")

			overMax := DefaultParams()
			tc.overMax(&overMax)
			require.Error(t, overMax.Validate(), "one past the maximum must be rejected")
		})
	}
}

func TestParamsRejectProfileListCounterOverflow(t *testing.T) {
	cases := map[string]func(*TierConfig){
		"max_followed_users":       func(t *TierConfig) { t.MaxFollowedUsers = MaxProfileListEntries + 1 },
		"max_joined_communities":   func(t *TierConfig) { t.MaxJoinedCommunities = MaxProfileListEntries + 1 },
		"max_blocked_users":        func(t *TierConfig) { t.MaxBlockedUsers = MaxProfileListEntries + 1 },
		"max_blocked_posts":        func(t *TierConfig) { t.MaxBlockedPosts = MaxProfileListEntries + 1 },
		"max_blocked_communities":  func(t *TierConfig) { t.MaxBlockedCommunities = MaxProfileListEntries + 1 },
		"max_curation_memberships": func(t *TierConfig) { t.MaxCurationMemberships = MaxProfileListEntries + 1 },
	}

	for name, mutate := range cases {
		t.Run(name, func(t *testing.T) {
			params := DefaultParams()
			mutate(params.Tiers[0])
			require.ErrorContains(t, params.Validate(), name)
		})
	}
}

// TestDefaultParamsSatisfyNewBounds guards against a default drifting past a cap.
func TestDefaultParamsSatisfyNewBounds(t *testing.T) {
	p := DefaultParams()
	require.NoError(t, p.Validate())
	require.LessOrEqual(t, p.PowMessageWindow, uint64(MaxPowMessageWindow))
	require.LessOrEqual(t, p.PowCalmSequenceThreshold, uint64(MaxPowCalmSequenceThreshold))
	require.LessOrEqual(t, p.MintInterval, uint64(MaxMintInterval))
	require.LessOrEqual(t, p.SubscriptionPeriod, uint64(MaxSubscriptionPeriodMinutes))
	require.LessOrEqual(t, p.MaxEnvelopeAge, uint64(MaxEnvelopeAgeSeconds))

	// Zero selects documented one-time-payment mode and stays valid.
	oneTime := DefaultParams()
	oneTime.SubscriptionPeriod = 0
	require.NoError(t, oneTime.Validate())
}
