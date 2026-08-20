package keeper

import (
	"testing"

	sdkmath "cosmossdk.io/math"
	"github.com/stretchr/testify/require"
)

func in(tokens, credits int64) mintInput {
	return mintInput{tokens: sdkmath.NewInt(tokens), creditsCapped: sdkmath.NewInt(credits)}
}

func totalStakeOf(vals []mintInput) sdkmath.Int {
	sum := sdkmath.ZeroInt()
	for _, v := range vals {
		sum = sum.Add(v.tokens)
	}
	return sum
}

func mustSplit(t *testing.T, mint int64, floor, dyn float64, vals []mintInput) []mintShare {
	t.Helper()
	shares, err := splitMint(sdkmath.NewInt(mint), floor, dyn, totalStakeOf(vals), vals)
	require.NoError(t, err)
	require.Len(t, shares, len(vals))
	return shares
}

// The whole reason for the upgrade: a small validator must earn a meaningful
// share for showing up, not a rounding error proportional to its stake.
func TestSplitMintFloorIsEqualRegardlessOfStake(t *testing.T) {
	vals := []mintInput{in(5_000_000, 0), in(5_000_000_000, 0)}
	shares := mustSplit(t, 1_000_000, 0.20, 0.10, vals)

	// 20% of 1,000,000 = 200,000, split equally between two validators.
	require.Equal(t, sdkmath.NewInt(100_000), shares[0].floor)
	require.Equal(t, sdkmath.NewInt(100_000), shares[1].floor)

	// Stake still dominates the remainder, which is the point of keeping 70%.
	require.True(t, shares[1].stake.GT(shares[0].stake))
}

func TestSplitMintFloorRemainderGoesToLastSortedValidator(t *testing.T) {
	vals := []mintInput{in(1, 0), in(1, 0), in(1, 0)}
	shares := mustSplit(t, 50, 0.20, 0, vals)

	// Ten floor units cannot divide evenly across three validators. The caller
	// sorts by valoper, so assigning the one-unit remainder to the last position
	// is deterministic on every node.
	require.Equal(t, sdkmath.NewInt(3), shares[0].floor)
	require.Equal(t, sdkmath.NewInt(3), shares[1].floor)
	require.Equal(t, sdkmath.NewInt(4), shares[2].floor)
}

// Deleting the `credits * tokens` multiply is the second half of the change:
// equal traffic must pay equally even when stake differs by three orders of
// magnitude.
func TestSplitMintWorkIgnoresStake(t *testing.T) {
	vals := []mintInput{in(5_000_000, 25), in(5_000_000_000, 25)}
	shares := mustSplit(t, 1_000_000, 0.20, 0.10, vals)

	require.Equal(t, shares[0].work, shares[1].work,
		"equal credits must earn equal work regardless of stake")
	require.True(t, shares[0].work.IsPositive())
}

func TestSplitMintWorkProportionalToCredits(t *testing.T) {
	vals := []mintInput{in(1_000_000, 10), in(1_000_000, 30)}
	shares := mustSplit(t, 1_000_000, 0.20, 0.10, vals)

	// 10% of 1,000,000 = 100,000 split 10:30.
	require.Equal(t, sdkmath.NewInt(25_000), shares[0].work)
	require.Equal(t, sdkmath.NewInt(75_000), shares[1].work)
}

func TestSplitMintCanonicalPoolsAreTwentyTenSeventy(t *testing.T) {
	vals := []mintInput{in(1_000_000, 10), in(3_000_000, 30)}
	shares := mustSplit(t, 1_000_000, 0.20, 0.10, vals)

	floor := sdkmath.ZeroInt()
	work := sdkmath.ZeroInt()
	stake := sdkmath.ZeroInt()
	for _, share := range shares {
		floor = floor.Add(share.floor)
		work = work.Add(share.work)
		stake = stake.Add(share.stake)
	}
	require.Equal(t, sdkmath.NewInt(200_000), floor)
	require.Equal(t, sdkmath.NewInt(100_000), work)
	require.Equal(t, sdkmath.NewInt(700_000), stake)
}

func TestSplitMintMultiplyBeforeDividePreservesExactShares(t *testing.T) {
	// Dividing 1/3 into an 18-decimal LegacyDec first produces
	// 0.333333333333333333; multiplying that by 3 truncates to 0. Integer
	// multiply-then-divide preserves the exact 1/2 allocation.
	vals := []mintInput{in(1, 0), in(2, 0)}
	shares := mustSplit(t, 3, 0, 0, vals)

	require.Equal(t, sdkmath.NewInt(1), shares[0].stake)
	require.Equal(t, sdkmath.NewInt(2), shares[1].stake)

	workVals := []mintInput{in(1, 1), in(2, 2)}
	workShares := mustSplit(t, 30, 0, 0.10, workVals)
	require.Equal(t, sdkmath.NewInt(1), workShares[0].work)
	require.Equal(t, sdkmath.NewInt(2), workShares[1].work)

	fallbackVals := []mintInput{in(1, 0), in(2, 0)}
	fallbackShares := mustSplit(t, 30, 0, 0.10, fallbackVals)
	require.Equal(t, sdkmath.NewInt(1), fallbackShares[0].work)
	require.Equal(t, sdkmath.NewInt(2), fallbackShares[1].work)
}

// A validator that relayed nothing earns floor and stake but no work.
func TestSplitMintNoCreditsEarnsNoWork(t *testing.T) {
	vals := []mintInput{in(1_000_000, 0), in(1_000_000, 40)}
	shares := mustSplit(t, 1_000_000, 0.20, 0.10, vals)

	require.True(t, shares[0].work.IsZero())
	require.Equal(t, sdkmath.NewInt(100_000), shares[1].work)
	require.True(t, shares[0].floor.IsPositive())
	require.True(t, shares[0].stake.IsPositive())
}

// An idle network keeps the old stake-weighted behavior for the work pool
// rather than silently enlarging the floor.
func TestSplitMintNoCreditsAnywhereFallsBackToStake(t *testing.T) {
	vals := []mintInput{in(1_000_000, 0), in(3_000_000, 0)}
	shares := mustSplit(t, 1_000_000, 0.20, 0.10, vals)

	require.Equal(t, sdkmath.NewInt(25_000), shares[0].work)
	require.Equal(t, sdkmath.NewInt(75_000), shares[1].work)
	require.Equal(t, sdkmath.NewInt(100_000), shares[0].floor)
	require.Equal(t, sdkmath.NewInt(100_000), shares[1].floor)
}

// Every umirage must be accounted for: the mint total is what gets minted, and
// the sum of the sends has to equal it or the supply-delta invariant breaks.
func TestSplitMintDistributesExactlyMint(t *testing.T) {
	cases := []struct {
		name  string
		mint  int64
		floor float64
		dyn   float64
		vals  []mintInput
	}{
		{"indivisible floor across three", 1_000_000, 0.20, 0.10,
			[]mintInput{in(333, 1), in(333, 0), in(334, 2)}},
		{"prime mint", 5_800_000_007, 0.20, 0.10,
			[]mintInput{in(5_000_000, 7), in(5_000_000_000, 25), in(12_345, 0)}},
		{"seven validators uneven credits", 999_999_999, 0.20, 0.10,
			[]mintInput{in(1, 1), in(2, 0), in(3, 5), in(5, 0), in(7, 9), in(11, 0), in(13, 3)}},
		{"single validator", 5_800_000_000, 0.20, 0.10,
			[]mintInput{in(5_000_000, 25)}},
		{"zero floor is the pre-upgrade shape", 1_000_000, 0, 0.75,
			[]mintInput{in(5_000_000, 25), in(5_000_000_000, 25)}},
		{"all to floor", 1_000_000, 1.0, 0,
			[]mintInput{in(5_000_000, 0), in(5_000_000_000, 3)}},
		{"floor plus work exactly one", 1_000_000, 0.30, 0.70,
			[]mintInput{in(5_000_000, 4), in(5_000_000_000, 0)}},
		{"one umirage", 1, 0.20, 0.10,
			[]mintInput{in(5_000_000, 1), in(5_000_000_000, 1)}},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			shares := mustSplit(t, tc.mint, tc.floor, tc.dyn, tc.vals)
			sum := sdkmath.ZeroInt()
			for _, s := range shares {
				require.False(t, s.floor.IsNegative())
				require.False(t, s.work.IsNegative())
				require.False(t, s.stake.IsNegative())
				sum = sum.Add(s.total())
			}
			require.Equal(t, sdkmath.NewInt(tc.mint), sum, "floor + work + stake must equal mint")
		})
	}
}

// A remainder handed to a validator that relayed nothing would pay work for no
// work, so it follows the credits instead of the validator order.
func TestSplitMintWorkRemainderFollowsCredits(t *testing.T) {
	// 10% of 1,000,001 = 100,000 (truncated); 3 credit-holders split it unevenly.
	vals := []mintInput{in(1_000, 1), in(1_000, 1), in(1_000, 1), in(1_000, 0)}
	shares := mustSplit(t, 1_000_001, 0.20, 0.10, vals)

	require.True(t, shares[3].work.IsZero(), "no credits must mean no work even for the last position")
	workSum := shares[0].work.Add(shares[1].work).Add(shares[2].work)
	require.Equal(t, sdkmath.NewInt(100_000), workSum)
}

// Pre-upgrade Params blobs have no field 55, so they decode as floor 0. That
// must keep working: it is what every node's stored state looks like right up
// to the halt.
func TestSplitMintZeroFloorMatchesStakeAndCredits(t *testing.T) {
	vals := []mintInput{in(1_000_000, 0), in(3_000_000, 0)}
	shares := mustSplit(t, 1_000_000, 0, 0.75, vals)

	for _, s := range shares {
		require.True(t, s.floor.IsZero())
	}
	// With no credits the work pool is stake-weighted, so the whole mint is.
	require.Equal(t, sdkmath.NewInt(250_000), shares[0].total())
	require.Equal(t, sdkmath.NewInt(750_000), shares[1].total())
}

func TestSplitMintRejectsBadInput(t *testing.T) {
	vals := []mintInput{in(1_000, 1)}
	stake := totalStakeOf(vals)

	_, err := splitMint(sdkmath.NewInt(1_000), 0.20, 0.10, stake, nil)
	require.Error(t, err, "no validators")

	_, err = splitMint(sdkmath.ZeroInt(), 0.20, 0.10, stake, vals)
	require.Error(t, err, "zero mint")

	_, err = splitMint(sdkmath.NewInt(1_000), 0.20, 0.10, sdkmath.ZeroInt(), vals)
	require.Error(t, err, "zero total stake")

	// Params.Validate rejects this, so reaching the keeper means validation was
	// bypassed. Minting past MintQuantity is worse than halting.
	_, err = splitMint(sdkmath.NewInt(1_000), 0.80, 0.80, stake, vals)
	require.Error(t, err, "splits summing above 1")
}
