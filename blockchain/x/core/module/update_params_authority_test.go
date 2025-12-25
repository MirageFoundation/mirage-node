package core_test

import (
    "testing"
    "time"

    cmtproto "github.com/cometbft/cometbft/proto/tendermint/types"
    sdk "github.com/cosmos/cosmos-sdk/types"
    authtypes "github.com/cosmos/cosmos-sdk/x/auth/types"
    govtypes "github.com/cosmos/cosmos-sdk/x/gov/types"

    "mirage/app"
    core "mirage/x/core/module"
    "mirage/x/core/types"
)

func TestUpdateParams_AuthorityEnforced(t *testing.T) {
    a := app.Setup(t, false)
    ctx := a.BaseApp.NewUncachedContext(false, cmtproto.Header{Time: time.Now().UTC()})

    am := core.NewAppModule(a.AppCodec(), a.CoreKeeper)

    // Prepare new params with a changed field
    p := types.DefaultParams()
    p.MinDifficulty = 11

    // Unauthorized caller should fail
    _, err := am.UpdateParams(sdk.WrapSDKContext(ctx), &types.MsgUpdateParams{
        Authority: "mirage1unauthorized0000000000000000000000000000000",
        Params:    p,
    })
    if err == nil {
        t.Fatalf("expected unauthorized error")
    }

    // Authorized via governance module address should succeed
    govAuthority := authtypes.NewModuleAddress(govtypes.ModuleName).String()
    _, err = am.UpdateParams(sdk.WrapSDKContext(ctx), &types.MsgUpdateParams{
        Authority: govAuthority,
        Params:    p,
    })
    if err != nil {
        t.Fatalf("unexpected error updating params with gov authority: %v", err)
    }

    got := a.CoreKeeper.GetParams(ctx)
    if got.MinDifficulty != 11 {
        t.Fatalf("min difficulty not updated, want 11, got %d", got.MinDifficulty)
    }
}


