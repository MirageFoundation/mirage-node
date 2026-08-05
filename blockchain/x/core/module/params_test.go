package core

import (
	"errors"
	"testing"

	"github.com/cosmos/cosmos-sdk/codec"
	codectypes "github.com/cosmos/cosmos-sdk/codec/types"
	"github.com/stretchr/testify/require"

	"mirage/consensusfatal"
	"mirage/x/core/types"
)

// FAIL-FAST CONTRACT for GetParams (consensus determinism hardening):
//
// The previous behavior — silently substituting DefaultParams() on store /
// unmarshal / validate failure — produced single-node app-hash divergence
// when one node's stored params bytes diverged from peers'. The fix is to
// halt loudly via consensusfatal so the auto-recovery watchdog can state-sync
// from healthy peers, which is strictly safer than silent divergence.
//
// These tests pin the new contract; any regression that reintroduces a
// silent fallback will fail here. Tests inject a panic halt hook so
// require.Panics* still works without os.Exit.

// TestGetParamsReturnsValidParamsAfterSetParams covers the happy path: once
// SetParams writes valid params, GetParams returns them without panic.
func TestGetParamsReturnsValidParamsAfterSetParams(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()

	want := types.DefaultParams()
	require.NoError(t, mk.SetParams(ctx, want))

	got := mk.GetParams(ctx)
	require.NoError(t, got.Validate(), "stored params must validate")
	require.Equal(t, want.MintInterval, got.MintInterval)
}

// TestGetParamsPanicsOnEmptyStore: an empty store post-genesis is a bug we
// want to surface. InitGenesis writes SetParams before any block handler
// runs, so a missing "params" key indicates either ordering corruption or
// state truncation. Falling back to DefaultParams here would cause peers
// (with intact params) to compute a different app-hash than this node.
func TestGetParamsPanicsOnEmptyStore(t *testing.T) {
	defer consensusfatal.SetHaltForTest(func(err error) { panic(err) })()

	mk := newMockKeeper()
	ctx := newMockContext()

	// newMockKeeper seeds default params; clear them to exercise the
	// empty-store branch.
	delete(mk.storeService.store, "params")

	require.PanicsWithError(t, "CONSENSUS_FATAL:PARAMS_EMPTY height=100: params not initialized (InitGenesis must SetParams)", func() {
		_ = mk.GetParams(ctx)
	})
}

// TestGetParamsPanicsOnCorruptBytes: bytes that fail to unmarshal MUST halt
// the chain. Substituting defaults would produce different state mutations
// (mint interval, fee rates, tier configs) than peers, diverging the
// app-hash on the next consensus round.
func TestGetParamsPanicsOnCorruptBytes(t *testing.T) {
	defer consensusfatal.SetHaltForTest(func(err error) { panic(err) })()

	mk := newMockKeeper()
	ctx := newMockContext()

	mk.storeService.store["params"] = []byte{0xff, 0xff, 0xff, 0xff, 0xff}

	require.PanicsWithError(t,
		"CONSENSUS_FATAL:PARAMS_UNMARSHAL height=100 bytes=5: unexpected EOF",
		func() { _ = mk.GetParams(ctx) },
	)
}

// TestGetParamsPanicsOnInvalidParams: a well-formed but Validate-failing
// params row halts the chain rather than silently using defaults. SetParams
// enforces Validate before writing, so reaching this branch means tampering
// or a bypass bug — operators must fix the stored params via state-sync or
// upgrade migration, not paper over them with defaults.
func TestGetParamsPanicsOnInvalidParams(t *testing.T) {
	defer consensusfatal.SetHaltForTest(func(err error) { panic(err) })()

	mk := newMockKeeper()
	ctx := newMockContext()

	invalid := types.DefaultParams()
	invalid.AwardConfigs = nil

	interfaceRegistry := codectypes.NewInterfaceRegistry()
	cdc := codec.NewProtoCodec(interfaceRegistry)
	bz, err := cdc.Marshal(&invalid)
	require.NoError(t, err)
	mk.storeService.store["params"] = bz

	require.Panics(t, func() { _ = mk.GetParams(ctx) },
		"GetParams must halt on Validate failure to prevent silent divergence")
}

// TestGetParamsPanicsOnStoreGetError covers the third panic-removal branch:
// the raw KVStore.Get call itself failing. This simulates an IAVL / disk /
// wrapper-level I/O error that is independent of the bytes we'd otherwise
// try to unmarshal. The chain MUST halt — silently returning defaults on
// only the affected node would diverge it from peers.
func TestGetParamsPanicsOnStoreGetError(t *testing.T) {
	defer consensusfatal.SetHaltForTest(func(err error) { panic(err) })()

	mk := newMockKeeper()
	ctx := newMockContext()

	mk.storeService.getErrors = map[string]error{
		"params": errors.New("simulated store.Get failure"),
	}

	require.Panics(t, func() { _ = mk.GetParams(ctx) },
		"GetParams must halt on store.Get failure to prevent silent divergence")
}

// TestGetParamsPanicsOnStoredAwardCostAboveBound exercises the interaction
// between the AwardConfig.Cost upper bound and the GetParams fail-fast
// contract: bytes that unmarshal but fail Validate (because an AwardConfig
// exceeds MaxAwardConfigCost) MUST panic. This guards against a governance
// proposal that bypassed validation on the way in.
func TestGetParamsPanicsOnStoredAwardCostAboveBound(t *testing.T) {
	defer consensusfatal.SetHaltForTest(func(err error) { panic(err) })()

	mk := newMockKeeper()
	ctx := newMockContext()

	invalid := types.DefaultParams()
	invalid.AwardConfigs[0].Cost = types.MaxAwardConfigCost + 1

	interfaceRegistry := codectypes.NewInterfaceRegistry()
	cdc := codec.NewProtoCodec(interfaceRegistry)
	bz, err := cdc.Marshal(&invalid)
	require.NoError(t, err)
	mk.storeService.store["params"] = bz

	require.Panics(t, func() { _ = mk.GetParams(ctx) },
		"GetParams must halt when stored params violate MaxAwardConfigCost")
}
