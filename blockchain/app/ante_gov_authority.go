package app

import (
	"fmt"
	"strings"

	sdk "github.com/cosmos/cosmos-sdk/types"
	authtypes "github.com/cosmos/cosmos-sdk/x/auth/types"
	govtypes "github.com/cosmos/cosmos-sdk/x/gov/types"
)

// GovAuthorityDecorator unconditionally rejects any broadcast transaction that
// contains a message with authority == gov module address.
//
// Legitimate governance-executed messages are dispatched by the gov module's
// EndBlocker through the message router — they never pass through ante handlers.
// Therefore any transaction arriving here with gov authority is a spoof attempt.
type GovAuthorityDecorator struct{}

func (d GovAuthorityDecorator) AnteHandle(ctx sdk.Context, tx sdk.Tx, simulate bool, next sdk.AnteHandler) (sdk.Context, error) {
	govAuthority := authtypes.NewModuleAddress(govtypes.ModuleName).String()
	for _, m := range tx.GetMsgs() {
		if am, ok := m.(interface{ GetAuthority() string }); ok {
			if strings.TrimSpace(am.GetAuthority()) == govAuthority {
				return ctx, fmt.Errorf("unauthorized: governance authority cannot be used in direct transactions")
			}
		}
	}
	return next(ctx, tx, simulate)
}
