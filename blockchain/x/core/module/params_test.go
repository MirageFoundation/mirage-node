package core

import (
	"errors"
	"testing"

	"github.com/cosmos/cosmos-sdk/codec"
	codectypes "github.com/cosmos/cosmos-sdk/codec/types"
	"github.com/stretchr/testify/require"

	"mirage/x/core/types"
)

// TestGetParamsReturnsDefaultsOnEmptyStore covers the legitimate
// first-boot / early-genesis path: with no "params" key, defaults are returned.
func TestGetParamsReturnsDefaultsOnEmptyStore(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()

	got := mk.GetParams(ctx)
	require.NoError(t, got.Validate(), "defaults should validate")
	require.Equal(t, types.DefaultParams().MintInterval, got.MintInterval)
}

// TestGetParamsFallsBackToDefaultsOnCorruptBytes ensures that a "params" row
// which fails to unmarshal does NOT halt the chain. We log loudly and fall
// back to DefaultParams so BeginBlock / EndBlock / message handlers keep
// running. Halting the chain on state corruption is worse than running on
// defaults per project policy.
func TestGetParamsFallsBackToDefaultsOnCorruptBytes(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()

	mk.storeService.store["params"] = []byte{0xff, 0xff, 0xff, 0xff, 0xff}

	require.NotPanics(t, func() {
		got := mk.GetParams(ctx)
		require.Equal(t, types.DefaultParams().MintInterval, got.MintInterval,
			"fallback must return DefaultParams on unmarshal failure")
		require.NoError(t, got.Validate(), "fallback params must pass Validate")
	})
}

// TestGetParamsFallsBackToDefaultsOnInvalidParams ensures that a well-formed
// but Validate-failing params row does not halt the chain. Production
// SetParams enforces Validate before writing, so reaching this branch
// implies tampering or a bypass bug — which operators must fix — but the
// chain stays live on defaults in the meantime.
func TestGetParamsFallsBackToDefaultsOnInvalidParams(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()

	invalid := types.DefaultParams()
	invalid.AwardConfigs = nil

	interfaceRegistry := codectypes.NewInterfaceRegistry()
	cdc := codec.NewProtoCodec(interfaceRegistry)
	bz, err := cdc.Marshal(&invalid)
	require.NoError(t, err)
	mk.storeService.store["params"] = bz

	require.NotPanics(t, func() {
		got := mk.GetParams(ctx)
		require.Equal(t, types.DefaultParams().MintInterval, got.MintInterval)
		require.NoError(t, got.Validate(), "fallback params must pass Validate")
	})
}

// TestGetParamsFallsBackToDefaultsOnStoreGetError covers the third
// panic-removal branch: the raw KVStore.Get call itself failing. This
// simulates an IAVL / disk / wrapper-level I/O error that is independent of
// the bytes we'd otherwise try to unmarshal. The chain must stay live on
// defaults.
func TestGetParamsFallsBackToDefaultsOnStoreGetError(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()

	mk.storeService.getErrors = map[string]error{
		"params": errors.New("simulated store.Get failure"),
	}

	require.NotPanics(t, func() {
		got := mk.GetParams(ctx)
		require.Equal(t, types.DefaultParams().MintInterval, got.MintInterval,
			"fallback must return DefaultParams on store.Get failure")
		require.NoError(t, got.Validate(), "fallback params must pass Validate")
	})
}

// TestGetParamsFallsBackToDefaultsOnStoredAwardCostAboveBound exercises the
// interaction between the AwardConfig.Cost upper bound and the GetParams
// fallback: bytes that unmarshal but fail Validate (because an AwardConfig
// exceeds MaxAwardConfigCost) still return DefaultParams instead of
// panicking. This guards against a governance proposal that bypassed
// validation on the way in.
func TestGetParamsFallsBackToDefaultsOnStoredAwardCostAboveBound(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()

	invalid := types.DefaultParams()
	invalid.AwardConfigs[0].Cost = types.MaxAwardConfigCost + 1

	interfaceRegistry := codectypes.NewInterfaceRegistry()
	cdc := codec.NewProtoCodec(interfaceRegistry)
	bz, err := cdc.Marshal(&invalid)
	require.NoError(t, err)
	mk.storeService.store["params"] = bz

	require.NotPanics(t, func() {
		got := mk.GetParams(ctx)
		require.Equal(t, types.DefaultParams().AwardConfigs[0].Cost, got.AwardConfigs[0].Cost,
			"fallback must return DefaultParams when stored params violate MaxAwardConfigCost")
	})
}
