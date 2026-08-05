package keeper

import (
	"context"
	"fmt"
	"testing"

	"cosmossdk.io/core/store"
	"cosmossdk.io/log/v2"
	sdkmath "cosmossdk.io/math"
	sdk "github.com/cosmos/cosmos-sdk/types"
	bankkeeper "github.com/cosmos/cosmos-sdk/x/bank/keeper"
	slashingkeeper "github.com/cosmos/cosmos-sdk/x/slashing/keeper"
	"github.com/stretchr/testify/require"

	"mirage/x/core/types"
)

// supplyMockBank implements just the bankkeeper.Keeper methods the supply
// invariant guards consume. The embedded nil interface satisfies the rest at
// compile time; any other call would panic, surfacing an unmocked path.
type supplyMockBank struct {
	bankkeeper.Keeper
	supply   int64
	balances []int64
}

func (m *supplyMockBank) IterateAllBalances(_ context.Context, cb func(sdk.AccAddress, sdk.Coin) bool) {
	for i, b := range m.balances {
		if cb(sdk.AccAddress{byte(i + 1)}, sdk.NewInt64Coin(types.MintDenom, b)) {
			return
		}
	}
}

func (m *supplyMockBank) GetSupply(_ context.Context, denom string) sdk.Coin {
	return sdk.NewInt64Coin(denom, m.supply)
}

type supplyKVService struct {
	data map[string][]byte
}

func newSupplyKVService() *supplyKVService {
	return &supplyKVService{data: make(map[string][]byte)}
}

func (s *supplyKVService) OpenKVStore(_ context.Context) store.KVStore {
	return &supplyKVStore{data: s.data}
}

type supplyKVStore struct {
	data map[string][]byte
}

func (k *supplyKVStore) Get(key []byte) ([]byte, error) { return k.data[string(key)], nil }
func (k *supplyKVStore) Has(key []byte) (bool, error) {
	_, ok := k.data[string(key)]
	return ok, nil
}
func (k *supplyKVStore) Set(key, value []byte) error {
	k.data[string(key)] = value
	return nil
}
func (k *supplyKVStore) Delete(key []byte) error {
	delete(k.data, string(key))
	return nil
}
func (k *supplyKVStore) Iterator(_, _ []byte) (store.Iterator, error) {
	return nil, fmt.Errorf("iterator not implemented")
}
func (k *supplyKVStore) ReverseIterator(_, _ []byte) (store.Iterator, error) {
	return nil, fmt.Errorf("reverse iterator not implemented")
}

func newSupplyTestKeeper(supply int64, balances []int64) Keeper {
	return NewKeeper(nil, nil, &supplyMockBank{supply: supply, balances: balances}, nil, nil, slashingkeeper.Keeper{})
}

func newDeltaTestKeeper(supply int64, balances []int64) (Keeper, *supplyMockBank) {
	svc := newSupplyKVService()
	bank := &supplyMockBank{supply: supply, balances: balances}
	return NewKeeper(svc, nil, bank, nil, nil, slashingkeeper.Keeper{}), bank
}

// TestAssertSupplyInvariant_Consistent: when recorded supply equals the sum of
// all balances (the only state correct serial execution can produce), the guard
// passes.
func TestAssertSupplyInvariant_Consistent(t *testing.T) {
	k := newSupplyTestKeeper(100, []int64{60, 40})
	require.NoError(t, k.AssertSupplyInvariant(sdk.Context{}))
}

// TestAssertSupplyInvariant_DoubleBurnFingerprint: reproduces the 2026-06-12
// divergence shape — balances unchanged but supply low by a prior block's fees
// (a double burn) — and asserts the guard fires with a descriptive error so the
// node halts with the culprit named instead of committing a divergent app hash.
func TestAssertSupplyInvariant_DoubleBurnFingerprint(t *testing.T) {
	const fees = 164124000
	balances := []int64{300_000_000, 200_000_000} // sum = 500,000,000
	k := newSupplyTestKeeper(500_000_000-fees, balances)
	err := k.AssertSupplyInvariant(sdk.Context{})
	require.Error(t, err)
	require.Contains(t, err.Error(), "supply invariant violated")
}

func TestAssertSupplyDeltaInvariant_Consistent(t *testing.T) {
	k, bank := newDeltaTestKeeper(1000, nil)
	ctx := sdk.Context{}.WithContext(context.Background()).WithLogger(log.NewNopLogger())

	require.NoError(t, k.CaptureBlockSupplyStart(ctx))
	// Simulate a mint of 50 then a burn of 20 → net +30
	require.NoError(t, k.addSupplyDelta(ctx, sdkmath.NewInt(50)))
	require.NoError(t, k.addSupplyDelta(ctx, sdkmath.NewInt(-20)))
	bank.supply = 1030
	require.NoError(t, k.AssertSupplyDeltaInvariant(ctx))
}

func TestAssertSupplyDeltaInvariant_Mismatch(t *testing.T) {
	k, _ := newDeltaTestKeeper(1000, nil)
	ctx := sdk.Context{}.WithContext(context.Background()).WithLogger(log.NewNopLogger())

	require.NoError(t, k.CaptureBlockSupplyStart(ctx))
	require.NoError(t, k.addSupplyDelta(ctx, sdkmath.NewInt(50)))
	// Supply not updated → mismatch (stale-read / missed tracking shape)
	err := k.AssertSupplyDeltaInvariant(ctx)
	require.Error(t, err)
	require.Contains(t, err.Error(), "supply delta invariant violated")
}

func TestAssertSupplyDeltaInvariant_AbsentStartFallsBack(t *testing.T) {
	k, _ := newDeltaTestKeeper(100, []int64{60, 40})
	ctx := sdk.Context{}.WithContext(context.Background()).WithLogger(log.NewNopLogger())
	// No CaptureBlockSupplyStart → falls back to full scan
	require.NoError(t, k.AssertSupplyDeltaInvariant(ctx))
}
