package app

import (
	"fmt"

	coretypes "mirage/x/core/types"

	sdk "github.com/cosmos/cosmos-sdk/types"
	authkeeper "github.com/cosmos/cosmos-sdk/x/auth/keeper"
	authsigning "github.com/cosmos/cosmos-sdk/x/auth/signing"
	authtypes "github.com/cosmos/cosmos-sdk/x/auth/types"
)

// EnsureAccountsDecorator creates missing accounts on the fly for whitelisted messages
// so first transactions do not require a separate funding tx. Signatures are still required.
type EnsureAccountsDecorator struct {
	ak authkeeper.AccountKeeper
}

func NewEnsureAccountsDecorator(ak authkeeper.AccountKeeper) EnsureAccountsDecorator {
	return EnsureAccountsDecorator{ak: ak}
}

func (d EnsureAccountsDecorator) AnteHandle(ctx sdk.Context, tx sdk.Tx, simulate bool, next sdk.AnteHandler) (sdk.Context, error) {
	if sigTx, ok := tx.(authsigning.SigVerifiableTx); ok {
		signers, err := sigTx.GetSigners()
		if err != nil {
			return ctx, err
		}
		for _, si := range signers {
			if d.ak.GetAccount(ctx, si) == nil {
				acc := d.ak.NewAccountWithAddress(ctx, si)
				if _, ok := acc.(*authtypes.BaseAccount); !ok {
					return ctx, fmt.Errorf("unsupported account type")
				}
				d.ak.SetAccount(ctx, acc)
			}
		}
	}
	// Ensure accounts for authority addresses in our custom messages
	for _, m := range tx.GetMsgs() {
		var addrStr string
		switch mm := m.(type) {
		case *coretypes.MsgPost:
			addrStr = mm.Authority
		case *coretypes.MsgVote:
			addrStr = mm.Authority
		case *coretypes.MsgSetUsername:
			addrStr = mm.Authority
		case *coretypes.MsgEnableAgent:
			addrStr = mm.Authority
		case *coretypes.MsgDisableAgent:
			addrStr = mm.Authority
		case *coretypes.MsgSetAgents:
			addrStr = mm.Authority
		case *coretypes.MsgBlockPost:
			addrStr = mm.Authority
		case *coretypes.MsgBlockUser:
			addrStr = mm.Authority
		case *coretypes.MsgDelete:
			addrStr = mm.Authority
		case *coretypes.MsgSendTokens:
			addrStr = mm.Authority
		case *coretypes.MsgAward:
			addrStr = mm.Authority
		case *coretypes.MsgSetBiography:
			addrStr = mm.Authority
		case *coretypes.MsgAnnotate:
			addrStr = mm.Authority
		default:
		}
		if addrStr == "" {
			continue
		}
		addr, err := sdk.AccAddressFromBech32(addrStr)
		if err != nil {
			return ctx, err
		}
		if d.ak.GetAccount(ctx, addr) == nil {
			acc := d.ak.NewAccountWithAddress(ctx, addr)
			if _, ok := acc.(*authtypes.BaseAccount); !ok {
				return ctx, fmt.Errorf("unsupported account type")
			}
			d.ak.SetAccount(ctx, acc)
		}
	}
	return next(ctx, tx, simulate)
}
