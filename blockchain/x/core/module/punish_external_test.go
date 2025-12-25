package core_test

import (
	"testing"
	"time"

	cmtproto "github.com/cometbft/cometbft/proto/tendermint/types"
	authtypes "github.com/cosmos/cosmos-sdk/x/auth/types"
	govtypes "github.com/cosmos/cosmos-sdk/x/gov/types"

	"mirage/app"
	coremodule "mirage/x/core/module"
	coretypes "mirage/x/core/types"
)

func TestPunishValidator_AuthorityChecks(t *testing.T) {
	a := app.Setup(t, false)
	am := coremodule.NewAppModule(a.AppCodec(), a.CoreKeeper)

	ctx := a.BaseApp.NewUncachedContext(false, cmtproto.Header{Time: time.Now().UTC()})

	// unauthorized authority
	if _, err := am.PunishValidator(ctx, &coretypes.MsgPunishValidator{
		Authority: authtypes.NewModuleAddress("not-gov").String(),
		Valoper:   "",
		Fraction:  "0.1",
	}); err == nil {
		t.Fatalf("expected unauthorized error")
	}

	// authorized but empty valoper
	if _, err := am.PunishValidator(ctx, &coretypes.MsgPunishValidator{
		Authority: authtypes.NewModuleAddress(govtypes.ModuleName).String(),
		Valoper:   "",
		Fraction:  "0.1",
	}); err == nil {
		t.Fatalf("expected error for empty valoper")
	}

	// authorized with invalid valoper format
	if _, err := am.PunishValidator(ctx, &coretypes.MsgPunishValidator{
		Authority: authtypes.NewModuleAddress(govtypes.ModuleName).String(),
		Valoper:   "invalid",
		Fraction:  "0.1",
	}); err == nil {
		t.Fatalf("expected error for invalid valoper")
	}
}
