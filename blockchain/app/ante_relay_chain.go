package app

import (
	sdk "github.com/cosmos/cosmos-sdk/types"
	authante "github.com/cosmos/cosmos-sdk/x/auth/ante"
	authkeeper "github.com/cosmos/cosmos-sdk/x/auth/keeper"
	bankkeeper "github.com/cosmos/cosmos-sdk/x/bank/keeper"
	txsigning "github.com/cosmos/cosmos-sdk/x/tx/signing"

	corekeeper "mirage/x/core/keeper"
)

// relayAnteDecorators returns the relay ante chain in execution order.
//
// The order carries security properties that the contents alone do not:
//
//   - SigVerification and DeductFee run BEFORE the envelope and PoW decorators,
//     so the gas payer must prove consent with a real outer signature. Before
//     v1.32.0 the fee was deducted from an attacker-chosen fee.payer with no
//     signature check at all (C-1).
//   - RelaySigDecorator runs BEFORE PowDecorator, so an unauthenticated
//     envelope is rejected without paying for Argon2id (M-1).
//   - ensure precedes setPubKey so the outer signer account exists.
//   - IncrementSequenceDecorator is deliberately absent: relay txs are
//     unordered, so there is no sequence to increment.
//
// Construction lives here together with the ordering so that
// TestRelayAnteDecoratorOrder pins the chain the app actually installs. Keep
// them together: a test over a separately-built slice would not catch a
// reordering at the call site.
func relayAnteDecorators(
	ak authkeeper.AccountKeeper,
	bk bankkeeper.Keeper,
	ck corekeeper.Keeper,
	signModeHandler *txsigning.HandlerMap,
) []sdk.AnteDecorator {
	return []sdk.AnteDecorator{
		authante.NewSetUpContextDecorator(),
		authante.NewValidateBasicDecorator(),
		GovAuthorityDecorator{},
		authante.NewTxTimeoutHeightDecorator(),
		authante.NewConsumeGasForTxSizeDecorator(ak),
		LoggingDecorator{},
		NewEnsureAccountsDecorator(ak),
		authante.NewSetPubKeyDecorator(ak),
		authante.NewSigGasConsumeDecorator(ak, authante.DefaultSigVerificationGasConsumer),
		authante.NewSigVerificationDecorator(ak, signModeHandler),
		authante.NewDeductFeeDecorator(ak, bk, nil, makeRelayTxFeeChecker(ck)),
		RelaySigDecorator{Keeper: ck},
		// MinFee is zero: PoW is never skipped based on the SDK fee, the node
		// pays gas separately.
		&PowDecorator{MinFee: sdk.Coin{}, Keeper: ck},
	}
}
