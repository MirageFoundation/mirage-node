package app

import (
	"testing"

	"cosmossdk.io/log/v2"
	cmtproto "github.com/cometbft/cometbft/proto/tendermint/types"
	dbm "github.com/cosmos/cosmos-db"
	"github.com/cosmos/cosmos-sdk/codec"
	codectypes "github.com/cosmos/cosmos-sdk/codec/types"
	"github.com/cosmos/cosmos-sdk/runtime"
	"github.com/cosmos/cosmos-sdk/store/v2/rootmulti"
	storetypes "github.com/cosmos/cosmos-sdk/store/v2/types"
	sdk "github.com/cosmos/cosmos-sdk/types"
	slashingkeeper "github.com/cosmos/cosmos-sdk/x/slashing/keeper"
	"github.com/stretchr/testify/require"

	corekeeper "mirage/x/core/keeper"
	coretypes "mirage/x/core/types"
)

// powGasFixture builds a PowDecorator over a real IAVL-backed, gas-metered store
// so reads are charged exactly as they are in a block. A map-backed mock would
// defeat the point: gas is charged by the store wrapper, not by the keeper.
//
// MinDifficulty is the lowest the params validator accepts, which keeps the
// nonce search below to a handful of hashes.
func powGasFixture(t *testing.T) (PowDecorator, sdk.Context) {
	t.Helper()

	key := storetypes.NewKVStoreKey("core")
	ms := rootmulti.NewStore(dbm.NewMemDB(), log.NewNopLogger())
	ms.MountStoreWithDB(key, storetypes.StoreTypeIAVL, nil)
	require.NoError(t, ms.LoadLatestVersion())

	cdc := codec.NewProtoCodec(codectypes.NewInterfaceRegistry())
	k := corekeeper.NewKeeper(runtime.NewKVStoreService(key), cdc, nil, nil, nil, slashingkeeper.Keeper{})

	ctx := sdk.NewContext(ms, cmtproto.Header{}, false, log.NewNopLogger())

	params := coretypes.DefaultParams()
	params.MinDifficulty = 1
	require.NoError(t, k.SetParams(ctx, params))

	return PowDecorator{Keeper: k}, ctx
}

func powProbeMsg(difficulty, pow uint64) *coretypes.MsgPost {
	pubkey := make([]byte, 33)
	pubkey[0] = 0x02
	for i := 1; i < len(pubkey); i++ {
		pubkey[i] = byte(i)
	}
	return &coretypes.MsgPost{
		EnvelopePubkey:     pubkey,
		EnvelopeBlockHash:  make([]byte, 32),
		EnvelopeDifficulty: difficulty,
		EnvelopePow:        pow,
		Content:            "gas parity probe",
	}
}

// powGasProbe runs the decorator over a throwaway branch of the store, so the
// state write on the accepting path cannot make the next probe read something
// different. Returns the gas charged, or the rejection.
func powGasProbe(t *testing.T, d PowDecorator, base sdk.Context, msg *coretypes.MsgPost, simulate bool) (uint64, error) {
	t.Helper()

	ctx, _ := base.CacheContext()
	ctx = ctx.WithGasMeter(storetypes.NewGasMeter(50_000_000))
	next := func(ctx sdk.Context, _ sdk.Tx, _ bool) (sdk.Context, error) { return ctx, nil }

	_, err := d.AnteHandle(ctx, mockTx{msgs: []sdk.Msg{msg}}, simulate, next)
	return ctx.GasMeter().GasConsumed(), err
}

// TestSimulateIsChargedTheSameGasAsExecution pins the invariant that broke the
// v1.36.0 rehearsal: clients size a gas limit from Simulate, so if this
// decorator does less work under simulation than in a block, every
// proof-of-work transaction is under-provisioned and dies with "out of gas in
// location: ReadFlat" in the block, after the fee has been deducted.
//
// The M-2 fix originally returned at the top of AnteHandle on simulate, which
// skipped the params, difficulty and window reads along with the hashing. Only
// the hashing may be skipped: it is the unauthenticated CPU amplifier, and it
// is free in gas terms.
func TestSimulateIsChargedTheSameGasAsExecution(t *testing.T) {
	d, base := powGasFixture(t)
	difficulty := d.Keeper.GetCurrentDifficulty(base)

	// A proof the decorator actually accepts, so execution runs the same path to
	// the end that simulation does rather than stopping early on a rejection.
	var accepted *coretypes.MsgPost
	for nonce := uint64(0); nonce < 4096; nonce++ {
		msg := powProbeMsg(difficulty, nonce)
		if _, err := powGasProbe(t, d, base, msg, false); err == nil {
			accepted = msg
			break
		}
	}
	require.NotNil(t, accepted, "no nonce below the search bound satisfied difficulty %d", difficulty)

	executed, err := powGasProbe(t, d, base, accepted, false)
	require.NoError(t, err)
	simulated, err := powGasProbe(t, d, base, accepted, true)
	require.NoError(t, err)

	require.Positive(t, executed, "the decorator should charge for the state it reads")
	require.Equal(t, executed, simulated,
		"simulate must be charged what execution charges, or every gas estimate built on it is short by the difference")
}
