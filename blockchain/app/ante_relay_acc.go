package app

import (
	corekeeper "mirage/x/core/keeper"
	coretypes "mirage/x/core/types"

	sdkmath "cosmossdk.io/math"
	sdk "github.com/cosmos/cosmos-sdk/types"
)

// RelayAccountingDecorator attributes relay credits to the fee payer's validator.
// Credits are computed as +1 per MsgPost (post or comment) seen in a successful tx.
type RelayAccountingDecorator struct {
	Keeper corekeeper.Keeper
}

func (d RelayAccountingDecorator) AnteHandle(ctx sdk.Context, tx sdk.Tx, simulate bool, next sdk.AnteHandler) (sdk.Context, error) {
	// Pass-through simulate
	if simulate {
		return next(ctx, tx, simulate)
	}

	// Only attribute on deliver (Finalize) phase
	if ctx.ExecMode() != sdk.ExecModeFinalize {
		return next(ctx, tx, simulate)
	}

	if ftx, ok := tx.(sdk.FeeTx); ok {
		payer := ""
		if p := ftx.FeePayer(); len(p) > 0 {
			payer = sdk.AccAddress(p).String()
		}
		// Only count MsgPost (both posts and comments)
		// Why not MsgVote? Because votes can already be gamed, and we don't want to reward this any further
		cnt := int64(0)
		for _, msg := range tx.GetMsgs() {
			switch msg.(type) {
			case *coretypes.MsgPost:
				cnt++
			}
		}
		ctx.Logger().Info("relay accounting: posts counted", "payer", payer, "count", cnt)
		if payer != "" && cnt > 0 {
			if valoper, err := d.Keeper.AccToValoper(payer); err == nil {
				if err2 := d.Keeper.AddRelayCredit(ctx, valoper, sdkmath.NewInt(cnt)); err2 == nil {
					ctx.Logger().Info("relay accounting: credit added", "valoper", valoper, "credit", cnt)
				}
			}
		}
	}

	return next(ctx, tx, simulate)
}
