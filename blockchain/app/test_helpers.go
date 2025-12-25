package app

import (
	"encoding/json"
	"testing"

	"cosmossdk.io/log"
	abcitypes "github.com/cometbft/cometbft/abci/types"
	"github.com/cosmos/cosmos-sdk/crypto/keys/secp256k1"
	"github.com/cosmos/cosmos-sdk/testutil/mock"
	"github.com/cosmos/cosmos-sdk/testutil/sims"
	sdk "github.com/cosmos/cosmos-sdk/types"
	authtypes "github.com/cosmos/cosmos-sdk/x/auth/types"
	banktypes "github.com/cosmos/cosmos-sdk/x/bank/types"
	"github.com/stretchr/testify/require"

	cosmosdb "github.com/cosmos/cosmos-db"
)

func Setup(t *testing.T, isCheckTx bool) *App {
	t.Helper()

	privVal := mock.NewPV()
	_, err := privVal.GetPubKey()
	require.NoError(t, err)

	// generate genesis account
	senderPrivKey := secp256k1.GenPrivKey()
	acc := authtypes.NewBaseAccount(senderPrivKey.PubKey().Address().Bytes(), senderPrivKey.PubKey(), 0, 0)
	balance := banktypes.Balance{
		Address: acc.GetAddress().String(),
		Coins:   sdk.NewCoins(sdk.NewInt64Coin(sdk.DefaultBondDenom, 100000000000000)),
	}

	app := New(log.NewNopLogger(), cosmosdb.NewMemDB(), nil, true, sims.EmptyAppOptions{})
	genesisState := app.DefaultGenesis()

	// Manually set bank genesis with balance
	bankGenState := banktypes.DefaultGenesisState()
	bankGenState.Balances = []banktypes.Balance{balance}
	genesisState[banktypes.ModuleName] = app.AppCodec().MustMarshalJSON(bankGenState)

	stateBytes, err := json.Marshal(genesisState)
	require.NoError(t, err)

	// init chain will set the validator set and initialize the genesis accounts
	app.InitChain(
		&abcitypes.RequestInitChain{
			Validators:      []abcitypes.ValidatorUpdate{},
			ConsensusParams: sims.DefaultConsensusParams,
			AppStateBytes:   stateBytes,
		},
	)

	// commit genesis changes
	app.Commit()

	// TODO: Fix BeginBlock call
	// header := tmproto.Header{
	// 	Height: app.LastBlockHeight() + 1,
	// 	AppHash: app.LastCommitID().Hash,
	// 	Time: time.Now().UTC(),
	// }
	// req := abcitypes.RequestBeginBlock{Header: &header}
	// ctx := sdk.NewContext(app.CommitMultiStore(), header, false, log.NewNopLogger())
	// app.App.BeginBlock(ctx, req)

	return app
}
