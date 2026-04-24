package app

import (
	"cosmossdk.io/errors"

	"github.com/cosmos/cosmos-sdk/types"
	stakingtypes "github.com/cosmos/cosmos-sdk/x/staking/types"
)

var ErrDelegationDisabled = errors.Register("app", 1001, "delegation is not supported on Mirage")

// DisableDelegatorStakingDecorator rejects any staking delegation-related messages.
type DisableDelegatorStakingDecorator struct{}

func (d DisableDelegatorStakingDecorator) AnteHandle(ctx types.Context, tx types.Tx, simulate bool, next types.AnteHandler) (types.Context, error) {
	if err := rejectDelegatorStakingMsgs(tx); err != nil {
		return ctx, err
	}
	return next(ctx, tx, simulate)
}

func rejectDelegatorStakingMsgs(tx types.Tx) error {
	for _, msg := range tx.GetMsgs() {
		switch m := msg.(type) {
		case *stakingtypes.MsgBeginRedelegate:
			return ErrDelegationDisabled
		case *stakingtypes.MsgDelegate:
			// allow only self-delegation (validator's own account -> its valoper)
			delAcc, err1 := types.AccAddressFromBech32(m.DelegatorAddress)
			valOper, err2 := types.ValAddressFromBech32(m.ValidatorAddress)
			if err1 != nil || err2 != nil {
				return ErrDelegationDisabled
			}
			if !delAcc.Equals(types.AccAddress(valOper)) {
				return ErrDelegationDisabled
			}
		case *stakingtypes.MsgUndelegate:
			// allow only self-undelegation (validator's own account unbonding from its valoper)
			delAcc, err1 := types.AccAddressFromBech32(m.DelegatorAddress)
			valOper, err2 := types.ValAddressFromBech32(m.ValidatorAddress)
			if err1 != nil || err2 != nil {
				return ErrDelegationDisabled
			}
			if !delAcc.Equals(types.AccAddress(valOper)) {
				return ErrDelegationDisabled
			}
		case *stakingtypes.MsgCancelUnbondingDelegation:
			// allow only self-cancellation (validator's own account cancelling its own unbond)
			delAcc, err1 := types.AccAddressFromBech32(m.DelegatorAddress)
			valOper, err2 := types.ValAddressFromBech32(m.ValidatorAddress)
			if err1 != nil || err2 != nil {
				return ErrDelegationDisabled
			}
			if !delAcc.Equals(types.AccAddress(valOper)) {
				return ErrDelegationDisabled
			}
		}
	}
	return nil
}
