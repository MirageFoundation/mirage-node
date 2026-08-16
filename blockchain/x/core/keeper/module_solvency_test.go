package keeper

import (
	"context"
	"encoding/json"
	"testing"

	"cosmossdk.io/log/v2"
	sdkmath "cosmossdk.io/math"
	cmtproto "github.com/cometbft/cometbft/proto/tendermint/types"
	dbm "github.com/cosmos/cosmos-db"
	"github.com/cosmos/cosmos-sdk/runtime"
	"github.com/cosmos/cosmos-sdk/store/v2/rootmulti"
	storetypes "github.com/cosmos/cosmos-sdk/store/v2/types"
	sdk "github.com/cosmos/cosmos-sdk/types"
	bankkeeper "github.com/cosmos/cosmos-sdk/x/bank/keeper"
	slashingkeeper "github.com/cosmos/cosmos-sdk/x/slashing/keeper"
	"github.com/stretchr/testify/require"

	"mirage/consensusfatal"
	"mirage/x/core/types"
)

// solvencyMockBank answers only GetAllBalances, which is all the solvency
// invariant consumes through bankBalance. The embedded nil interface satisfies
// the rest at compile time, so an unmocked call panics rather than quietly
// returning a zero value.
type solvencyMockBank struct {
	bankkeeper.Keeper
	moduleBalance int64
}

func (m *solvencyMockBank) GetAllBalances(_ context.Context, _ sdk.AccAddress) sdk.Coins {
	return sdk.NewCoins(sdk.NewInt64Coin(types.MintDenom, m.moduleBalance))
}

// solvencyFixture builds a real IAVL-backed store so GetAllProfiles walks a real
// iterator, and seeds one profile per reserve value.
func solvencyFixture(t *testing.T, moduleBalance int64, reserves []uint64) (Keeper, sdk.Context) {
	t.Helper()
	key := storetypes.NewKVStoreKey("core")
	ms := rootmulti.NewStore(dbm.NewMemDB(), log.NewNopLogger())
	ms.MountStoreWithDB(key, storetypes.StoreTypeIAVL, nil)
	require.NoError(t, ms.LoadLatestVersion())

	ctx := sdk.NewContext(ms, cmtproto.Header{}, false, log.NewNopLogger()).
		WithContext(context.Background()).
		WithExecMode(sdk.ExecModeFinalize)

	k := NewKeeper(runtime.NewKVStoreService(key), nil,
		&solvencyMockBank{moduleBalance: moduleBalance}, nil, nil, slashingkeeper.Keeper{})

	for i, reserve := range reserves {
		core := types.ProfileCore{
			Owner:        sdk.AccAddress{byte(i + 1)}.String(),
			ReserveFunds: reserve,
		}
		bz, err := json.Marshal(core)
		require.NoError(t, err)
		require.NoError(t, k.SetProfileCore(ctx, core.Owner, bz))
	}
	return k, ctx
}

// TestModuleSolvencyInvariantHolds is item #3 from the review's "not determined
// from source" list. Every reserve mutation was shown by inspection to preserve
// module balance >= Σ recorded reserves, but nothing proved that no other module
// drains the core account out-of-band — and M-3 established the account is not
// even blocked from receiving. This converts that from believed-safe to
// asserted-safe at runtime.
func TestModuleSolvencyInvariantHolds(t *testing.T) {
	k, ctx := solvencyFixture(t, 1_000_000, []uint64{400_000, 300_000, 1})
	require.NoError(t, k.AssertModuleSolvencyInvariant(ctx))
}

// Exact coverage is solvent: the invariant is >=, not >.
func TestModuleSolvencyInvariantAllowsExactCoverage(t *testing.T) {
	k, ctx := solvencyFixture(t, 700_000, []uint64{400_000, 300_000})
	require.NoError(t, k.AssertModuleSolvencyInvariant(ctx))
}

func TestModuleSolvencyInvariantWithNoProfiles(t *testing.T) {
	k, ctx := solvencyFixture(t, 0, nil)
	require.NoError(t, k.AssertModuleSolvencyInvariant(ctx))
}

// A shortfall must halt during finalization: recorded liabilities exceeding
// their backing means the next reserve spend burns coins that are not there.
func TestModuleSolvencyShortfallHaltsDuringFinalize(t *testing.T) {
	restore := consensusfatal.SetHaltForTest(func(err error) { panic(err) })
	defer restore()

	k, ctx := solvencyFixture(t, 699_999, []uint64{400_000, 300_000})
	require.Panics(t, func() { _ = k.AssertModuleSolvencyInvariant(ctx) })
}

// Outside finalization the same shortfall returns an error rather than taking
// the process down, per the chain failure policy in AGENTS.md.
func TestModuleSolvencyShortfallReturnsOutsideFinalize(t *testing.T) {
	restore := consensusfatal.SetHaltForTest(func(err error) {
		t.Fatal("a query-mode fault must never halt the node")
	})
	defer restore()

	k, ctx := solvencyFixture(t, 10, []uint64{5_000})
	err := k.AssertModuleSolvencyInvariant(ctx.WithExecMode(sdk.ExecModeCheck))
	require.Error(t, err)
	require.Contains(t, err.Error(), "module solvency invariant violated")
	require.Contains(t, err.Error(), "short by 4990")
}

// Reserves are uint64 and there can be many profiles, so the sum must not
// overflow the way a uint64 accumulator would. sdkmath.Int is arbitrary
// precision; this pins that choice.
func TestModuleSolvencyInvariantSumsBeyondUint64(t *testing.T) {
	const nearMax = uint64(1) << 63
	k, ctx := solvencyFixture(t, 0, []uint64{nearMax, nearMax, nearMax})

	err := k.AssertModuleSolvencyInvariant(ctx.WithExecMode(sdk.ExecModeCheck))
	require.Error(t, err)

	want := sdkmath.NewIntFromUint64(nearMax).MulRaw(3)
	require.Contains(t, err.Error(), want.String(),
		"three reserves of 2^63 must sum to 3*2^63, not wrap around")
}
