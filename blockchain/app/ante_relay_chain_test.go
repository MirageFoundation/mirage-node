package app

import (
	"reflect"
	"testing"

	"github.com/stretchr/testify/require"

	authkeeper "github.com/cosmos/cosmos-sdk/x/auth/keeper"
	bankkeeper "github.com/cosmos/cosmos-sdk/x/bank/keeper"

	corekeeper "mirage/x/core/keeper"
)

// TestRelayAnteDecoratorOrder pins the execution order of the relay ante chain.
//
// The order is the security property, not the membership. Two orderings that
// contain the same decorators differ by whether an attacker pays for the
// expensive work and whether an unauthorized account pays the gas:
//
//   - SigVerification and DeductFee must precede RelaySigDecorator and
//     PowDecorator. Before v1.32.0 the relay chain deducted the fee from an
//     attacker-chosen fee.payer with no outer signature check, which let any
//     funded account be drained through the public /chain endpoint (C-1).
//   - RelaySigDecorator must precede PowDecorator so an unauthenticated
//     envelope is rejected before Argon2id burns CPU and memory (M-1).
//
// The review flagged that this property was "implicit in a slice literal" with
// no test. If a future change reorders the chain, this test fails instead of
// the vulnerability silently returning.
func TestRelayAnteDecoratorOrder(t *testing.T) {
	// The decorators only need to be constructed, not executed, so zero-value
	// keepers are sufficient to inspect the chain's shape.
	decs := relayAnteDecorators(
		authkeeper.AccountKeeper{},
		bankkeeper.BaseKeeper{},
		corekeeper.Keeper{},
		nil,
	)

	got := make([]string, 0, len(decs))
	for _, d := range decs {
		got = append(got, reflect.TypeOf(d).String())
	}

	want := []string{
		"ante.SetUpContextDecorator",
		"ante.ValidateBasicDecorator",
		"app.GovAuthorityDecorator",
		"ante.TxTimeoutHeightDecorator",
		"ante.ConsumeTxSizeGasDecorator",
		"app.EnsureAccountsDecorator",
		"ante.SetPubKeyDecorator",
		"ante.SigGasConsumeDecorator",
		"ante.SigVerificationDecorator",
		// After SigVerification since v1.36.0: it logs one line per message and
		// hashes the whole transaction, so ahead of the signature check an
		// anonymous 1MB transaction of thousands of minimal relay messages made
		// every node write thousands of log lines for free (L-6).
		"app.LoggingDecorator",
		"app.RetiredMsgDecorator",
		"app.OnePostPerTxDecorator",
		"app.RelaySigDecorator",
		"ante.DeductFeeDecorator",
		"*app.PowDecorator",
	}
	require.Equal(t, want, got, "relay ante chain order changed; see C-1 and M-1 before updating this test")

	idx := func(name string) int {
		for i, g := range got {
			if g == name {
				return i
			}
		}
		t.Fatalf("decorator %s missing from the relay ante chain", name)
		return -1
	}

	// C-1: the gas payer must be authenticated before any fee is taken, and
	// both must happen before the envelope/PoW work.
	require.Less(t, idx("ante.SigVerificationDecorator"), idx("ante.DeductFeeDecorator"),
		"C-1: the outer signature must be verified before the fee is deducted")
	require.Less(t, idx("app.RelaySigDecorator"), idx("ante.DeductFeeDecorator"),
		"zero-fee exemption authenticates envelopes before skipping min-gas-price")
	require.Less(t, idx("ante.SigVerificationDecorator"), idx("*app.PowDecorator"),
		"C-1: the outer signature must be verified before PoW work")

	// M-1: cheap envelope rejection before expensive Argon2id.
	require.Less(t, idx("app.RelaySigDecorator"), idx("*app.PowDecorator"),
		"M-1: envelope signature must be checked before Argon2id runs")

	// SetPubKey must precede signature verification, and the account must exist
	// before its pubkey is set.
	require.Less(t, idx("app.EnsureAccountsDecorator"), idx("ante.SetPubKeyDecorator"),
		"the outer signer account must exist before its pubkey is set")
	require.Less(t, idx("ante.SetPubKeyDecorator"), idx("ante.SigVerificationDecorator"),
		"the pubkey must be set before signature verification")

	// SetUpContext establishes the gas meter and must be first.
	require.Equal(t, 0, idx("ante.SetUpContextDecorator"),
		"SetUpContextDecorator must run first to install the gas meter")
}

// TestRelayAnteOmitsSequenceIncrement documents that relay txs are unordered.
//
// IncrementSequenceDecorator must stay out of the relay chain: relay txs set
// unordered=true with a timeout_timestamp and carry sequence 0, so incrementing
// a sequence would reject every subsequent relay tx from the same signer.
func TestRelayAnteOmitsSequenceIncrement(t *testing.T) {
	decs := relayAnteDecorators(
		authkeeper.AccountKeeper{},
		bankkeeper.BaseKeeper{},
		corekeeper.Keeper{},
		nil,
	)
	for _, d := range decs {
		name := reflect.TypeOf(d).String()
		require.NotEqual(t, "ante.IncrementSequenceDecorator", name,
			"relay txs are unordered; a sequence increment would break them")
	}
}
