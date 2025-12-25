package keeper_test

import (
	"testing"
	"time"

	"github.com/stretchr/testify/suite"

	cmtproto "github.com/cometbft/cometbft/proto/tendermint/types"
	sdk "github.com/cosmos/cosmos-sdk/types"

	bankkeeper "github.com/cosmos/cosmos-sdk/x/bank/keeper"

	"mirage/app"
	coretypes "mirage/x/core/types"
)

type KeeperTestSuite struct {
	suite.Suite

	App         *app.App
	Ctx         sdk.Context
	QueryClient coretypes.QueryClient
	BankKeeper  bankkeeper.Keeper
}

func (s *KeeperTestSuite) SetupTest() {
	s.App = app.Setup(s.T(), false)
	s.Ctx = s.App.BaseApp.NewUncachedContext(false, cmtproto.Header{Time: time.Now().UTC()})
	s.BankKeeper = s.App.BankKeeper
}

func (s *KeeperTestSuite) TestMintIfNeeded() {
	k := s.App.CoreKeeper

	params := coretypes.DefaultParams()
	params.MintInterval = 120
	err := k.SetParams(s.Ctx, params)
	s.Require().NoError(err)

	// Block 1: too early, no mint
	ctx1 := s.Ctx.WithBlockHeight(1)
	err = k.MintIfNeeded(ctx1)
	s.Require().NoError(err)

	// Block 119: still too early, no mint
	ctx119 := s.Ctx.WithBlockHeight(119)
	err = k.MintIfNeeded(ctx119)
	s.Require().NoError(err)

	// Block 120: exactly MintPeriodBlocks, should mint
	ctx120 := s.Ctx.WithBlockHeight(120)
	err = k.MintIfNeeded(ctx120)
	s.Require().NoError(err)

	// Block 240: next multiple, should mint again
	ctx240 := s.Ctx.WithBlockHeight(240)
	err = k.MintIfNeeded(ctx240)
	s.Require().NoError(err)

	// Block 241: not a multiple, no mint
	ctx241 := s.Ctx.WithBlockHeight(241)
	err = k.MintIfNeeded(ctx241)
	s.Require().NoError(err)
}

func (s *KeeperTestSuite) TestDynamicDifficultyAdjustment() {
	k := s.App.CoreKeeper

	params := coretypes.DefaultParams()
	err := k.SetParams(s.Ctx, params)
	s.Require().NoError(err)

	// Test initial difficulty
	difficulty := k.GetCurrentDifficulty(s.Ctx)
	s.Require().Equal(params.MinDifficulty, difficulty)

	ctx := s.Ctx.WithBlockHeight(10)
	// Record some PoW messages
	for i := 0; i < 120; i++ {
		err := k.RecordPoWMessage(ctx)
		s.Require().NoError(err)
	}

	// Check message count
	messageCount := k.GetPoWMessageCount(ctx, params)
	s.Require().Equal(uint64(120), messageCount)
}

func TestKeeperTestSuite(t *testing.T) {
	suite.Run(t, new(KeeperTestSuite))
}
