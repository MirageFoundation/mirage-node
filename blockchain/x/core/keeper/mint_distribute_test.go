package keeper

import (
	"context"
	"fmt"
	"testing"

	"cosmossdk.io/log/v2"
	sdkmath "cosmossdk.io/math"
	sdk "github.com/cosmos/cosmos-sdk/types"
	bankkeeper "github.com/cosmos/cosmos-sdk/x/bank/keeper"
	"github.com/stretchr/testify/require"
)

// --- mock bank implementing mintBankIface -----------------------------------

// bankCall records a single bank method invocation for assertions.
type bankCall struct {
	op     string // "mint" | "send"
	module string
	to     sdk.AccAddress
	amount sdkmath.Int
}

// mockMintBank is a minimal mintBankIface impl with per-method failure
// injection knobs. The ledger tracks supply deltas so tests can assert
// final supply matches expectations.
type mockMintBank struct {
	bankkeeper.Keeper
	calls []bankCall

	mintFail    error
	sendFailFor map[string]error // keyed by valoper bech32 (or accAddress string)

	// Sent coins move from the module account to users without changing supply.
	moduleBalance sdkmath.Int
	supply        sdkmath.Int
}

func newMockMintBank() *mockMintBank {
	return &mockMintBank{
		sendFailFor:   make(map[string]error),
		moduleBalance: sdkmath.ZeroInt(),
		supply:        sdkmath.ZeroInt(),
	}
}

func (m *mockMintBank) MintCoins(_ context.Context, moduleName string, amt sdk.Coins) error {
	call := bankCall{op: "mint", module: moduleName, amount: amt[0].Amount}
	m.calls = append(m.calls, call)
	if m.mintFail != nil {
		return m.mintFail
	}
	m.moduleBalance = m.moduleBalance.Add(amt[0].Amount)
	m.supply = m.supply.Add(amt[0].Amount)
	return nil
}

func (m *mockMintBank) SendCoinsFromModuleToAccount(_ context.Context, senderModule string, recipient sdk.AccAddress, amt sdk.Coins) error {
	call := bankCall{op: "send", module: senderModule, to: recipient, amount: amt[0].Amount}
	m.calls = append(m.calls, call)
	if err, ok := m.sendFailFor[recipient.String()]; ok {
		return err
	}
	m.moduleBalance = m.moduleBalance.Sub(amt[0].Amount)
	return nil
}

// opsOf returns a compact op sequence (e.g. ["mint","send","send"]).
func (m *mockMintBank) opsOf() []string {
	out := make([]string, len(m.calls))
	for i, c := range m.calls {
		out[i] = c.op
	}
	return out
}

// --- helpers ----------------------------------------------------------------

func distributeTestCtx() sdk.Context {
	return sdk.Context{}.WithContext(context.Background()).WithLogger(log.NewNopLogger())
}

func makeRecipients(t *testing.T, pairs ...any) []mintRecipient {
	t.Helper()
	if len(pairs)%2 != 0 {
		t.Fatalf("makeRecipients: odd number of args (%d)", len(pairs))
	}
	out := make([]mintRecipient, 0, len(pairs)/2)
	for i := 0; i < len(pairs); i += 2 {
		seed := pairs[i].(byte)
		amount := pairs[i+1].(sdkmath.Int)
		bz := bytesRepeat(seed, 20)
		valAddr := sdk.ValAddress(bz)
		out = append(out, mintRecipient{
			operatorAddress: valAddr.String(),
			accountAddress:  sdk.AccAddress(valAddr),
			amount:          amount,
		})
	}
	return out
}

func bytesRepeat(b byte, n int) []byte {
	out := make([]byte, n)
	for i := range out {
		out[i] = b
	}
	return out
}

func sumAmounts(rs []mintRecipient) sdkmath.Int {
	total := sdkmath.ZeroInt()
	for _, r := range rs {
		total = total.Add(r.amount)
	}
	return total
}

// --- tests ------------------------------------------------------------------

func TestMintAndDistribute_HappyPath(t *testing.T) {
	bank := newMockMintBank()
	ctx := distributeTestCtx()

	recipients := makeRecipients(t,
		byte(0x01), sdkmath.NewInt(100),
		byte(0x02), sdkmath.NewInt(200),
		byte(0x03), sdkmath.NewInt(300),
	)
	total := sumAmounts(recipients)

	result, err := mintAndDistribute(ctx, bank, "core", "umirage", recipients, total)

	require.NoError(t, err)
	require.Equal(t, sdkmath.NewInt(600), result.minted)
	require.Equal(t, sdkmath.NewInt(600), result.sent)
	require.Equal(t, []string{"mint", "send", "send", "send"}, bank.opsOf())
	require.True(t, bank.moduleBalance.IsZero(), "module balance must be zero after full distribution")
	require.Equal(t, sdkmath.NewInt(600), bank.supply, "supply increases by total minted")
}

func TestMintAndDistribute_NoOpOnZeroTotal(t *testing.T) {
	bank := newMockMintBank()
	ctx := distributeTestCtx()

	result, err := mintAndDistribute(ctx, bank, "core", "umirage", nil, sdkmath.ZeroInt())
	require.NoError(t, err)
	require.True(t, result.minted.IsZero())
	require.True(t, result.sent.IsZero())
	require.Empty(t, bank.calls, "no bank calls when totalMint is zero")
}

func TestMintAndDistribute_NoOpOnEmptyRecipients(t *testing.T) {
	bank := newMockMintBank()
	ctx := distributeTestCtx()

	result, err := mintAndDistribute(ctx, bank, "core", "umirage", nil, sdkmath.NewInt(100))
	require.NoError(t, err)
	require.True(t, result.minted.IsZero())
	require.Empty(t, bank.calls, "no bank calls when recipients are empty")
}

func TestMintAndDistribute_MintCoinsFails_NothingSent(t *testing.T) {
	bank := newMockMintBank()
	bank.mintFail = fmt.Errorf("mint-denied-by-restriction")
	ctx := distributeTestCtx()

	recipients := makeRecipients(t, byte(0x01), sdkmath.NewInt(100))
	result, err := mintAndDistribute(ctx, bank, "core", "umirage", recipients, sdkmath.NewInt(100))

	require.ErrorContains(t, err, "mint-denied-by-restriction")
	require.True(t, result.minted.IsZero())
	require.True(t, result.sent.IsZero())
	require.Equal(t, []string{"mint"}, bank.opsOf(), "must not proceed past MintCoins failure")
	require.True(t, bank.supply.IsZero(), "supply unchanged on MintCoins failure")
}

func TestMintAndDistribute_SendFailurePropagates(t *testing.T) {
	bank := newMockMintBank()
	recipients := makeRecipients(t,
		byte(0x01), sdkmath.NewInt(100),
		byte(0x02), sdkmath.NewInt(200),
		byte(0x03), sdkmath.NewInt(300),
	)
	bank.sendFailFor[recipients[1].accountAddress.String()] = fmt.Errorf("send-fail-target-blocked")
	ctx := distributeTestCtx()

	result, err := mintAndDistribute(ctx, bank, "core", "umirage", recipients, sumAmounts(recipients))

	require.ErrorContains(t, err, "send-fail-target-blocked")
	require.Equal(t, sdkmath.NewInt(600), result.minted)
	require.Equal(t, sdkmath.NewInt(100), result.sent, "distribution stops at the first failed send")
	require.Equal(t, []string{"mint", "send", "send"}, bank.opsOf())
}
