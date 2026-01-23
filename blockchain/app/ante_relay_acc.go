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
	execMode := ctx.ExecMode()
	// Only attribute on finalize or simulate (simulate for accurate gas estimation)
	if execMode != sdk.ExecModeFinalize && execMode != sdk.ExecModeSimulate {
		return next(ctx, tx, simulate)
	}
	logFinalize := execMode == sdk.ExecModeFinalize

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
		if logFinalize {
			ctx.Logger().Info("relay accounting: posts counted", "payer", payer, "count", cnt)
		} else {
			ctx.Logger().Debug("relay accounting: simulate", "payer", payer, "count", cnt)
		}
		if payer != "" && cnt > 0 {
			if valoper, err := d.Keeper.AccToValoper(payer); err == nil {
				if err2 := d.Keeper.AddRelayCredit(ctx, valoper, sdkmath.NewInt(cnt)); err2 == nil {
					if logFinalize {
						ctx.Logger().Info("relay accounting: credit added", "valoper", valoper, "credit", cnt)
					} else {
						ctx.Logger().Debug("relay accounting: credit simulated", "valoper", valoper, "credit", cnt)
					}
				}
			}
		}
	}

	return next(ctx, tx, simulate)
}
