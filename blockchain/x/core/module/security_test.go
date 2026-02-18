package core

import (
	"bytes"
	"testing"

	sdk "github.com/cosmos/cosmos-sdk/types"
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
