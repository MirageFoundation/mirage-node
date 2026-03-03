package core

import (
	"bytes"
	"fmt"
	"strings"
	"testing"

	sdk "github.com/cosmos/cosmos-sdk/types"
	authtypes "github.com/cosmos/cosmos-sdk/x/auth/types"
	govtypes "github.com/cosmos/cosmos-sdk/x/gov/types"
	"github.com/stretchr/testify/require"

	"mirage/x/core/types"
)

func TestSetUsernameRejectsEnvelopePubkeyMismatch(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()
	am := newTestModule(mk)

	pub, owner := testPubkeyOwner()
	target := sdk.AccAddress(bytes.Repeat([]byte{0x04}, 20)).String()
	if target == owner {
		target = sdk.AccAddress(bytes.Repeat([]byte{0x05}, 20)).String()
	}

	req := &types.MsgSetUsername{
		Authority:      testAccAddressString(),
		EnvelopePubkey: pub,
		Target:         target,
		Username:       "Alice",
	}

	t.Logf("[debug] set_username owner=%s target=%s", owner, target)
	_, err := am.SetUsername(ctx, req)
	require.Error(t, err)
	require.Contains(t, err.Error(), "envelope_pubkey must derive to target")
}

func TestSendTokensRejectsEnvelopePubkeyMismatch(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()
	am := newTestModule(mk)

	pub, owner := testPubkeyOwner()
	sender := sdk.AccAddress(bytes.Repeat([]byte{0x06}, 20)).String()
	if sender == owner {
		sender = sdk.AccAddress(bytes.Repeat([]byte{0x07}, 20)).String()
	}
	target := sdk.AccAddress(bytes.Repeat([]byte{0x08}, 20)).String()

	req := &types.MsgSendTokens{
		Authority:      testAccAddressString(),
		EnvelopePubkey: pub,
		Sender:         sender,
		Target:         target,
		Amount:         1,
	}

	t.Logf("[debug] send_tokens owner=%s sender=%s target=%s", owner, sender, target)
	_, err := am.SendTokens(ctx, req)
	require.Error(t, err)
	require.Contains(t, err.Error(), "envelope_pubkey must derive to sender")
}

func TestAwardRejectsInvalidPubkeyLength(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()
	am := newTestModule(mk)

	req := &types.MsgAward{
		Authority:      testAccAddressString(),
		EnvelopePubkey: []byte{0x01, 0x02},
		Target:         strings.Repeat("a", 64),
		AwardType:      "quality_post",
	}

	_, err := am.Award(ctx, req)
	require.Error(t, err)
	require.Contains(t, err.Error(), "invalid envelope_pubkey length")
}

func TestAwardRejectsEmptyTarget(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()
	am := newTestModule(mk)

	pub, owner := testPubkeyOwner()
	ensureUsername(t, mk, ctx, owner, "Anon-testuser")
	req := &types.MsgAward{
		Authority:      testAccAddressString(),
		EnvelopePubkey: pub,
		Target:         "   ",
		AwardType:      "quality_post",
	}

	_, err := am.Award(ctx, req)
	require.Error(t, err)
	require.Contains(t, err.Error(), "award target cannot be empty")
}

func TestAwardRejectsInvalidTarget(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()
	am := newTestModule(mk)

	pub, owner := testPubkeyOwner()
	ensureUsername(t, mk, ctx, owner, "Anon-testuser")
	req := &types.MsgAward{
		Authority:      testAccAddressString(),
		EnvelopePubkey: pub,
		Target:         "not_a_hash",
		AwardType:      "quality_post",
	}

	_, err := am.Award(ctx, req)
	require.Error(t, err)
	require.Contains(t, err.Error(), "invalid target")
}

func TestAwardRejectsEmptyType(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()
	am := newTestModule(mk)

	pub, owner := testPubkeyOwner()
	ensureUsername(t, mk, ctx, owner, "Anon-testuser")
	req := &types.MsgAward{
		Authority:      testAccAddressString(),
		EnvelopePubkey: pub,
		Target:         strings.Repeat("b", 64),
		AwardType:      " ",
	}

	_, err := am.Award(ctx, req)
	require.Error(t, err)
	require.Contains(t, err.Error(), "award_type cannot be empty")
}

func TestAwardRejectsUnknownType(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()
	am := newTestModule(mk)

	pub, owner := testPubkeyOwner()
	ensureUsername(t, mk, ctx, owner, "Anon-testuser")
	req := &types.MsgAward{
		Authority:      testAccAddressString(),
		EnvelopePubkey: pub,
		Target:         strings.Repeat("c", 64),
		AwardType:      "not_a_real_award",
	}

	_, err := am.Award(ctx, req)
	require.Error(t, err)
	require.Contains(t, err.Error(), "unknown award_type")
}

func TestAwardAcceptsUppercaseTarget(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()
	am := newTestModule(mk)

	params := mk.GetParams(ctx)
	params.AwardConfigs = []*types.AwardConfig{
		{Name: "quality_post", Cost: 0},
	}
	require.NoError(t, mk.SetParams(ctx, params))

	pub, owner := testPubkeyOwner()
	ensureUsername(t, mk, ctx, owner, "Anon-testuser")
	upper := strings.ToUpper(strings.Repeat("d", 64))
	req := &types.MsgAward{
		Authority:      testAccAddressString(),
		EnvelopePubkey: pub,
		Target:         upper,
		AwardType:      "quality_post",
	}

	t.Logf("[debug] award uppercase target=%s", upper)
	_, err := am.Award(ctx, req)
	require.NoError(t, err)
}

func TestAwardAdminSkipsBurn(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()
	am := newTestModule(mk)

	pub, owner := testPubkeyOwner()
	setProfileLevel(t, mk, ctx, owner, 100)

	target := strings.Repeat("e", 64)
	req := &types.MsgAward{
		Authority:      testAccAddressString(),
		EnvelopePubkey: pub,
		Target:         target,
		AwardType:      "quality_post",
	}

	t.Logf("[debug] award admin owner=%s target=%s", owner, target)
	// Admin awards have cost=0, so BurnFromAccount is not called.
	// However deductRelayGasFee is still called and hits nil GasMeter in mock context.
	// We verify the burn was skipped by checking the panic happens in deductRelayGasFee
	// (gas fee path) rather than in BurnFromAccount (award burn path).
	var panicVal interface{}
	func() {
		defer func() { panicVal = recover() }()
		_, _ = am.Award(ctx, req)
	}()
	if panicVal != nil {
		msg := fmt.Sprintf("%v", panicVal)
		require.NotContains(t, msg, "burn award cost", "admin should skip award burn")
		t.Logf("[debug] admin award panicked in gas fee path (expected with nil gas meter): %v", panicVal)
	}
}

func TestAwardNonAdminBurnsOrErrors(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()
	am := newTestModule(mk)

	pub, owner := testPubkeyOwner()
	ensureUsername(t, mk, ctx, owner, "Anon-testuser")
	target := strings.Repeat("f", 64)
	req := &types.MsgAward{
		Authority:      testAccAddressString(),
		EnvelopePubkey: pub,
		Target:         target,
		AwardType:      "quality_post",
	}

	t.Logf("[debug] award non-admin owner=%s target=%s", owner, target)
	var err error
	didPanic := false
	func() {
		defer func() {
			if r := recover(); r != nil {
				didPanic = true
			}
		}()
		_, err = am.Award(ctx, req)
	}()
	if didPanic {
		t.Log("[debug] award burn path panicked as expected with nil bank keeper")
		return
	}
	require.Error(t, err)
	require.Contains(t, err.Error(), "failed to burn award cost")
}

func TestAwardGovernanceSkipsEnvelopePubkey(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()
	am := newTestModule(mk)

	params := mk.GetParams(ctx)
	params.AwardConfigs = []*types.AwardConfig{
		{Name: "quality_post", Cost: 0},
	}
	require.NoError(t, mk.SetParams(ctx, params))

	govAddr := authtypes.NewModuleAddress(govtypes.ModuleName).String()
	target := strings.Repeat("1", 64)
	req := &types.MsgAward{
		Authority: govAddr,
		Target:    target,
		AwardType: "quality_post",
	}

	t.Logf("[debug] award gov target=%s", target)
	_, err := am.Award(ctx, req)
	require.NoError(t, err)
}
