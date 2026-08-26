package core

import (
	"fmt"
	"strings"
	"testing"

	sdk "github.com/cosmos/cosmos-sdk/types"
	authtypes "github.com/cosmos/cosmos-sdk/x/auth/types"
	govtypes "github.com/cosmos/cosmos-sdk/x/gov/types"

	"mirage/x/core/types"
)

// govTokenKeeper interface for testing MintTokens/BurnTokens
type govTokenKeeper interface {
	MintToAccount(ctx sdk.Context, recipient string, amount uint64) error
	BurnFromAccount(ctx sdk.Context, addr string, amount uint64) error
}

// govMockKeeper implements govTokenKeeper for testing
type govMockKeeper struct {
	balances map[string]uint64
}

func newGovMockKeeper() *govMockKeeper {
	return &govMockKeeper{
		balances: make(map[string]uint64),
	}
}

func (mk *govMockKeeper) MintToAccount(ctx sdk.Context, recipient string, amount uint64) error {
	mk.balances[recipient] += amount
	return nil
}

func (mk *govMockKeeper) BurnFromAccount(ctx sdk.Context, addr string, amount uint64) error {
	bal := mk.balances[addr]
	if bal < amount {
		return fmt.Errorf("insufficient balance: have %d, need %d", bal, amount)
	}
	mk.balances[addr] = bal - amount
	return nil
}

// mintTokens is a testable implementation of the MintTokens logic
func mintTokens(k govTokenKeeper, ctx sdk.Context, req *types.MsgMintTokens) (*types.MsgMintTokensResponse, error) {
	if req.Authority != authtypes.NewModuleAddress(govtypes.ModuleName).String() {
		return nil, fmt.Errorf("unauthorized: only governance can mint")
	}

	target := strings.TrimSpace(req.Target)
	if target == "" {
		return nil, fmt.Errorf("target cannot be empty")
	}
	if req.Amount == 0 {
		return nil, fmt.Errorf("amount must be > 0")
	}

	if err := k.MintToAccount(ctx, target, req.Amount); err != nil {
		return nil, err
	}

	return &types.MsgMintTokensResponse{}, nil
}

// burnTokens is a testable implementation of the BurnTokens logic
func burnTokens(k govTokenKeeper, ctx sdk.Context, req *types.MsgBurnTokens) (*types.MsgBurnTokensResponse, error) {
	if req.Authority != authtypes.NewModuleAddress(govtypes.ModuleName).String() {
		return nil, fmt.Errorf("unauthorized: only governance can burn")
	}

	target := strings.TrimSpace(req.Target)
	if target == "" {
		return nil, fmt.Errorf("target cannot be empty")
	}
	if req.Amount == 0 {
		return nil, fmt.Errorf("amount must be > 0")
	}

	if err := k.BurnFromAccount(ctx, target, req.Amount); err != nil {
		return nil, err
	}

	return &types.MsgBurnTokensResponse{}, nil
}

// TestMintTokens_NonGovAuthority tests that non-governance addresses cannot mint
func TestMintTokens_NonGovAuthority(t *testing.T) {
	mk := newGovMockKeeper()
	ctx := sdk.Context{}

	req := &types.MsgMintTokens{
		Authority: "mirage1abc123def456",
		Target:    "mirage1recipient",
		Amount:    1000000,
		Reason:    "test mint",
	}

	_, err := mintTokens(mk, ctx, req)
	if err == nil {
		t.Fatal("expected error for non-governance authority, got nil")
	}
	if err.Error() != "unauthorized: only governance can mint" {
		t.Fatalf("unexpected error: %v", err)
	}
}

// TestMintTokens_Success tests successful governance mint
func TestMintTokens_Success(t *testing.T) {
	mk := newGovMockKeeper()
	ctx := sdk.Context{}

	target := "mirage1recipient"
	amount := uint64(1000000)

	req := &types.MsgMintTokens{
		Authority: govAuthority(),
		Target:    target,
		Amount:    amount,
		Reason:    "governance mint test",
	}

	_, err := mintTokens(mk, ctx, req)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if mk.balances[target] != amount {
		t.Fatalf("expected balance %d, got %d", amount, mk.balances[target])
	}
}

// TestMintTokens_EmptyTarget tests that empty target is rejected
func TestMintTokens_EmptyTarget(t *testing.T) {
	mk := newGovMockKeeper()
	ctx := sdk.Context{}

	req := &types.MsgMintTokens{
		Authority: govAuthority(),
		Target:    "",
		Amount:    1000000,
		Reason:    "test",
	}

	_, err := mintTokens(mk, ctx, req)
	if err == nil {
		t.Fatal("expected error for empty target, got nil")
	}
	if err.Error() != "target cannot be empty" {
		t.Fatalf("unexpected error: %v", err)
	}
}

// TestMintTokens_WhitespaceTarget tests that whitespace-only target is rejected
func TestMintTokens_WhitespaceTarget(t *testing.T) {
	mk := newGovMockKeeper()
	ctx := sdk.Context{}

	req := &types.MsgMintTokens{
		Authority: govAuthority(),
		Target:    "   ",
		Amount:    1000000,
		Reason:    "test",
	}

	_, err := mintTokens(mk, ctx, req)
	if err == nil {
		t.Fatal("expected error for whitespace target, got nil")
	}
	if err.Error() != "target cannot be empty" {
		t.Fatalf("unexpected error: %v", err)
	}
}

// TestMintTokens_ZeroAmount tests that zero amount is rejected
func TestMintTokens_ZeroAmount(t *testing.T) {
	mk := newGovMockKeeper()
	ctx := sdk.Context{}

	req := &types.MsgMintTokens{
		Authority: govAuthority(),
		Target:    "mirage1recipient",
		Amount:    0,
		Reason:    "test",
	}

	_, err := mintTokens(mk, ctx, req)
	if err == nil {
		t.Fatal("expected error for zero amount, got nil")
	}
	if err.Error() != "amount must be > 0" {
		t.Fatalf("unexpected error: %v", err)
	}
}

// TestMintTokens_MultipleMintsAccumulate tests that multiple mints accumulate
func TestMintTokens_MultipleMintsAccumulate(t *testing.T) {
	mk := newGovMockKeeper()
	ctx := sdk.Context{}

	target := "mirage1recipient"

	_, err := mintTokens(mk, ctx, &types.MsgMintTokens{
		Authority: govAuthority(),
		Target:    target,
		Amount:    1000000,
	})
	if err != nil {
		t.Fatalf("first mint failed: %v", err)
	}

	_, err = mintTokens(mk, ctx, &types.MsgMintTokens{
		Authority: govAuthority(),
		Target:    target,
		Amount:    500000,
	})
	if err != nil {
		t.Fatalf("second mint failed: %v", err)
	}

	expected := uint64(1500000)
	if mk.balances[target] != expected {
		t.Fatalf("expected balance %d, got %d", expected, mk.balances[target])
	}
}

// TestBurnTokens_NonGovAuthority tests that non-governance addresses cannot burn
func TestBurnTokens_NonGovAuthority(t *testing.T) {
	mk := newGovMockKeeper()
	ctx := sdk.Context{}

	mk.balances["mirage1target"] = 1000000

	req := &types.MsgBurnTokens{
		Authority: "mirage1abc123def456",
		Target:    "mirage1target",
		Amount:    500000,
		Reason:    "test burn",
	}

	_, err := burnTokens(mk, ctx, req)
	if err == nil {
		t.Fatal("expected error for non-governance authority, got nil")
	}
	if err.Error() != "unauthorized: only governance can burn" {
		t.Fatalf("unexpected error: %v", err)
	}
}

// TestBurnTokens_Success tests successful governance burn
func TestBurnTokens_Success(t *testing.T) {
	mk := newGovMockKeeper()
	ctx := sdk.Context{}

	target := "mirage1target"
	initial := uint64(1000000)
	burnAmount := uint64(400000)
	mk.balances[target] = initial

	req := &types.MsgBurnTokens{
		Authority: govAuthority(),
		Target:    target,
		Amount:    burnAmount,
		Reason:    "governance burn test",
	}

	_, err := burnTokens(mk, ctx, req)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	expected := initial - burnAmount
	if mk.balances[target] != expected {
		t.Fatalf("expected balance %d, got %d", expected, mk.balances[target])
	}
}

// TestBurnTokens_InsufficientBalance tests that burning more than balance fails
func TestBurnTokens_InsufficientBalance(t *testing.T) {
	mk := newGovMockKeeper()
	ctx := sdk.Context{}

	target := "mirage1target"
	mk.balances[target] = 100000

	req := &types.MsgBurnTokens{
		Authority: govAuthority(),
		Target:    target,
		Amount:    500000,
		Reason:    "test",
	}

	_, err := burnTokens(mk, ctx, req)
	if err == nil {
		t.Fatal("expected error for insufficient balance, got nil")
	}
	if err.Error() != "insufficient balance: have 100000, need 500000" {
		t.Fatalf("unexpected error: %v", err)
	}
}

// TestBurnTokens_EmptyTarget tests that empty target is rejected
func TestBurnTokens_EmptyTarget(t *testing.T) {
	mk := newGovMockKeeper()
	ctx := sdk.Context{}

	req := &types.MsgBurnTokens{
		Authority: govAuthority(),
		Target:    "",
		Amount:    1000000,
		Reason:    "test",
	}

	_, err := burnTokens(mk, ctx, req)
	if err == nil {
		t.Fatal("expected error for empty target, got nil")
	}
	if err.Error() != "target cannot be empty" {
		t.Fatalf("unexpected error: %v", err)
	}
}

// TestBurnTokens_ZeroAmount tests that zero amount is rejected
func TestBurnTokens_ZeroAmount(t *testing.T) {
	mk := newGovMockKeeper()
	ctx := sdk.Context{}

	req := &types.MsgBurnTokens{
		Authority: govAuthority(),
		Target:    "mirage1target",
		Amount:    0,
		Reason:    "test",
	}

	_, err := burnTokens(mk, ctx, req)
	if err == nil {
		t.Fatal("expected error for zero amount, got nil")
	}
	if err.Error() != "amount must be > 0" {
		t.Fatalf("unexpected error: %v", err)
	}
}

// TestBurnTokens_BurnEntireBalance tests burning exactly the full balance
func TestBurnTokens_BurnEntireBalance(t *testing.T) {
	mk := newGovMockKeeper()
	ctx := sdk.Context{}

	target := "mirage1target"
	balance := uint64(1000000)
	mk.balances[target] = balance

	req := &types.MsgBurnTokens{
		Authority: govAuthority(),
		Target:    target,
		Amount:    balance,
		Reason:    "burn all",
	}

	_, err := burnTokens(mk, ctx, req)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if mk.balances[target] != 0 {
		t.Fatalf("expected zero balance, got %d", mk.balances[target])
	}
}

// TestBurnTokens_FromZeroBalance tests burning from zero balance fails
func TestBurnTokens_FromZeroBalance(t *testing.T) {
	mk := newGovMockKeeper()
	ctx := sdk.Context{}

	target := "mirage1empty"

	req := &types.MsgBurnTokens{
		Authority: govAuthority(),
		Target:    target,
		Amount:    1,
		Reason:    "test",
	}

	_, err := burnTokens(mk, ctx, req)
	if err == nil {
		t.Fatal("expected error for burning from zero balance, got nil")
	}
}

// TestMintThenBurn tests minting then burning
func TestMintThenBurn(t *testing.T) {
	mk := newGovMockKeeper()
	ctx := sdk.Context{}

	target := "mirage1target"

	_, err := mintTokens(mk, ctx, &types.MsgMintTokens{
		Authority: govAuthority(),
		Target:    target,
		Amount:    1000000,
	})
	if err != nil {
		t.Fatalf("mint failed: %v", err)
	}

	_, err = burnTokens(mk, ctx, &types.MsgBurnTokens{
		Authority: govAuthority(),
		Target:    target,
		Amount:    300000,
	})
	if err != nil {
		t.Fatalf("burn failed: %v", err)
	}

	expected := uint64(700000)
	if mk.balances[target] != expected {
		t.Fatalf("expected balance %d, got %d", expected, mk.balances[target])
	}
}

// TestMintTokens_TargetTrimmed tests that target addresses are trimmed
func TestMintTokens_TargetTrimmed(t *testing.T) {
	mk := newGovMockKeeper()
	ctx := sdk.Context{}

	_, err := mintTokens(mk, ctx, &types.MsgMintTokens{
		Authority: govAuthority(),
		Target:    "  mirage1recipient  ",
		Amount:    1000000,
	})
	if err != nil {
		t.Fatalf("mint failed: %v", err)
	}

	if mk.balances["mirage1recipient"] != 1000000 {
		t.Fatalf("balance not stored at trimmed address, got: %v", mk.balances)
	}
}
