package keeper

import (
	"context"
	"fmt"
	"testing"

	"cosmossdk.io/log/v2"
	sdkmath "cosmossdk.io/math"
	sdk "github.com/cosmos/cosmos-sdk/types"
	"github.com/stretchr/testify/require"
)

// --- mock bank implementing mintBankIface -----------------------------------

// bankCall records a single bank method invocation for assertions.
type bankCall struct {
	op     string // "mint" | "send" | "burn"
	module string
	to     sdk.AccAddress
	amount sdkmath.Int
}

// mockMintBank is a minimal mintBankIface impl with per-method failure
// injection knobs. The ledger tracks supply deltas so tests can assert
// final supply matches expectations.
type mockMintBank struct {
	calls []bankCall

	mintFail     error
	sendFailFor  map[string]error // keyed by valoper bech32 (or accAddress string)
	burnFailAll  error
	burnFailOnce map[string]error // one-shot failure per sender key

	// supply = minted - burned; sent moves coins from module to user,
	// so the module account balance = minted - sent - burned.
	moduleBalance sdkmath.Int
	supply        sdkmath.Int
}

func newMockMintBank() *mockMintBank {
	return &mockMintBank{
		sendFailFor:   make(map[string]error),
		burnFailOnce:  make(map[string]error),
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

func (m *mockMintBank) BurnCoins(_ context.Context, moduleName string, amt sdk.Coins) error {
	call := bankCall{op: "burn", module: moduleName, amount: amt[0].Amount}
	m.calls = append(m.calls, call)
	if m.burnFailAll != nil {
		return m.burnFailAll
	}
	if err, ok := m.burnFailOnce[moduleName]; ok {
		delete(m.burnFailOnce, moduleName)
		return err
	}
	m.moduleBalance = m.moduleBalance.Sub(amt[0].Amount)
	m.supply = m.supply.Sub(amt[0].Amount)
	return nil
}

// opsOf returns a compact op sequence (e.g. ["mint","send","send","burn"]).
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

	result := mintAndDistribute(ctx, bank, "core", "umirage", recipients, total)

	require.Equal(t, sdkmath.NewInt(600), result.minted)
	require.Equal(t, sdkmath.NewInt(600), result.sent)
	require.True(t, result.burnedSkipped.IsZero())
	require.True(t, result.stuckInModule.IsZero())
	require.Equal(t, []string{"mint", "send", "send", "send"}, bank.opsOf())
	require.True(t, bank.moduleBalance.IsZero(), "module balance must be zero after full distribution")
	require.Equal(t, sdkmath.NewInt(600), bank.supply, "supply increases by total minted")
}

func TestMintAndDistribute_NoOpOnZeroTotal(t *testing.T) {
	bank := newMockMintBank()
	ctx := distributeTestCtx()

	result := mintAndDistribute(ctx, bank, "core", "umirage", nil, sdkmath.ZeroInt())
	require.True(t, result.minted.IsZero())
	require.True(t, result.sent.IsZero())
	require.Empty(t, bank.calls, "no bank calls when totalMint is zero")
}

func TestMintAndDistribute_NoOpOnEmptyRecipients(t *testing.T) {
	bank := newMockMintBank()
	ctx := distributeTestCtx()

	result := mintAndDistribute(ctx, bank, "core", "umirage", nil, sdkmath.NewInt(100))
	require.True(t, result.minted.IsZero())
	require.Empty(t, bank.calls, "no bank calls when recipients are empty")
}

func TestMintAndDistribute_MintCoinsFails_NothingSent(t *testing.T) {
	bank := newMockMintBank()
	bank.mintFail = fmt.Errorf("mint-denied-by-restriction")
	ctx := distributeTestCtx()

	recipients := makeRecipients(t, byte(0x01), sdkmath.NewInt(100))
	result := mintAndDistribute(ctx, bank, "core", "umirage", recipients, sdkmath.NewInt(100))

	require.True(t, result.minted.IsZero())
	require.True(t, result.sent.IsZero())
	require.True(t, result.burnedSkipped.IsZero())
	require.True(t, result.stuckInModule.IsZero())
	require.Equal(t, []string{"mint"}, bank.opsOf(), "must not proceed past MintCoins failure")
	require.True(t, bank.supply.IsZero(), "supply unchanged on MintCoins failure")
}

func TestMintAndDistribute_SendFails_BurnSucceeds(t *testing.T) {
	bank := newMockMintBank()
	recipients := makeRecipients(t,
		byte(0x01), sdkmath.NewInt(100),
		byte(0x02), sdkmath.NewInt(200),
		byte(0x03), sdkmath.NewInt(300),
	)
	bank.sendFailFor[recipients[1].accountAddress.String()] = fmt.Errorf("send-fail-target-blocked")
	ctx := distributeTestCtx()

	result := mintAndDistribute(ctx, bank, "core", "umirage", recipients, sumAmounts(recipients))

	require.Equal(t, sdkmath.NewInt(600), result.minted)
	require.Equal(t, sdkmath.NewInt(400), result.sent, "two valid sends deliver 100+300")
	require.Equal(t, sdkmath.NewInt(200), result.burnedSkipped)
	require.True(t, result.stuckInModule.IsZero())
	require.Equal(t, []string{"mint", "send", "send", "burn", "send"}, bank.opsOf())
	require.True(t, bank.moduleBalance.IsZero(), "module balance must be zero (sent 400 + burned 200 = minted 600)")
	require.Equal(t, sdkmath.NewInt(400), bank.supply, "supply grows by sent, not by minted-but-burned portion")
}

func TestMintAndDistribute_SendFails_BurnFails_StuckInModule(t *testing.T) {
	bank := newMockMintBank()
	recipients := makeRecipients(t,
		byte(0x01), sdkmath.NewInt(100),
		byte(0x02), sdkmath.NewInt(200),
		byte(0x03), sdkmath.NewInt(300),
	)
	bank.sendFailFor[recipients[1].accountAddress.String()] = fmt.Errorf("send-fail-target-blocked")
	bank.burnFailAll = fmt.Errorf("burn-denied")
	ctx := distributeTestCtx()

	result := mintAndDistribute(ctx, bank, "core", "umirage", recipients, sumAmounts(recipients))

	require.Equal(t, sdkmath.NewInt(600), result.minted)
	require.Equal(t, sdkmath.NewInt(400), result.sent)
	require.True(t, result.burnedSkipped.IsZero(), "burn failed so nothing gets counted as burned")
	require.Equal(t, sdkmath.NewInt(200), result.stuckInModule)
	require.Equal(t, []string{"mint", "send", "send", "burn", "send"}, bank.opsOf())
	require.Equal(t, sdkmath.NewInt(200), bank.moduleBalance, "200 stuck in module")
	require.Equal(t, sdkmath.NewInt(600), bank.supply, "supply still reflects full mint because burn failed")
}

func TestMintAndDistribute_AllSendsFail_AllBurned(t *testing.T) {
	bank := newMockMintBank()
	recipients := makeRecipients(t,
		byte(0x01), sdkmath.NewInt(100),
		byte(0x02), sdkmath.NewInt(200),
	)
	for _, r := range recipients {
		bank.sendFailFor[r.accountAddress.String()] = fmt.Errorf("send-fail")
	}
	ctx := distributeTestCtx()

	result := mintAndDistribute(ctx, bank, "core", "umirage", recipients, sumAmounts(recipients))

	require.Equal(t, sdkmath.NewInt(300), result.minted)
	require.True(t, result.sent.IsZero())
	require.Equal(t, sdkmath.NewInt(300), result.burnedSkipped)
	require.True(t, result.stuckInModule.IsZero())
	require.True(t, bank.moduleBalance.IsZero())
	require.True(t, bank.supply.IsZero(), "mint(300) - burn(300) = 0 supply delta")
}

func TestMintAndDistribute_OneStuckOthersPaid(t *testing.T) {
	bank := newMockMintBank()
	recipients := makeRecipients(t,
		byte(0x01), sdkmath.NewInt(100),
		byte(0x02), sdkmath.NewInt(200),
		byte(0x03), sdkmath.NewInt(300),
	)
	// middle recipient: send fails AND burn fails (stuck)
	bank.sendFailFor[recipients[1].accountAddress.String()] = fmt.Errorf("send-fail")
	bank.burnFailAll = fmt.Errorf("burn-fail")
	ctx := distributeTestCtx()

	result := mintAndDistribute(ctx, bank, "core", "umirage", recipients, sumAmounts(recipients))

	require.Equal(t, sdkmath.NewInt(600), result.minted)
	require.Equal(t, sdkmath.NewInt(400), result.sent)
	require.True(t, result.burnedSkipped.IsZero())
	require.Equal(t, sdkmath.NewInt(200), result.stuckInModule)
	require.Equal(t, sdkmath.NewInt(200), bank.moduleBalance, "unburnable stuck 200 remains")

	// invariants
	require.Equal(t, result.minted, result.sent.Add(result.burnedSkipped).Add(result.stuckInModule),
		"minted = sent + burnedSkipped + stuckInModule")
}
