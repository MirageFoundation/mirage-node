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
//   - LoggingDecorator runs AFTER SigVerification, so an unauthenticated
//     transaction cannot make the node write logs. It used to sit at index 5,
//     four places ahead of SigVerification, while looping over every message with
//     a logger.Info call plus a SHA-256 over the whole transaction — so a 1MB
//     transaction of thousands of minimal relay messages with a garbage signature
//     produced thousands of log lines on every node that CheckTx'd it, from an
//     anonymous sender (L-6). That contradicted the ordering contract stated
//     right here.
//   - ensure precedes setPubKey so the outer signer account exists.
//   - IncrementSequenceDecorator is deliberately absent: relay txs are
//     unordered, so there is no sequence to increment.
//
// DeductFee uses the SDK default fee checker (nil), which enforces only the
// minimum-gas-price floor during CheckTx. There is deliberately no fee ceiling:
// SigVerification has already proven the payer signed the SignDoc, and the
// SignDoc covers auth_info (fee amount, gas, payer), so the payer consented to
// the exact amount. C-1 was an authorization hole, not a magnitude problem. An
// added ceiling of min(gas*relay_min_gas_price, relay_max_gas_fee) crosses the
// floor at relay_max_gas_fee/min_gas_price gas — at the current 500 MIRAGE cap
// that made every relay tx above 500k gas (posts over ~10.7k chars, well inside
// the 20k tier limit) unpayable, because the required fee exceeded the allowed
// one. Do not reintroduce it. relay_max_gas_fee still bounds the separate
// deduction from a paid user's own reserve in x/core/module.
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
		NewEnsureAccountsDecorator(ak),
		authante.NewSetPubKeyDecorator(ak),
		authante.NewSigGasConsumeDecorator(ak, authante.DefaultSigVerificationGasConsumer),
		authante.NewSigVerificationDecorator(ak, signModeHandler),
		LoggingDecorator{},
		authante.NewDeductFeeDecorator(ak, bk, nil, nil),
		RelaySigDecorator{Keeper: ck},
		&PowDecorator{Keeper: ck},
	}
}
