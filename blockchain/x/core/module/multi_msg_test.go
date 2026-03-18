package core

import (
	"bytes"
	"testing"

	codectypes "github.com/cosmos/cosmos-sdk/codec/types"
	sdk "github.com/cosmos/cosmos-sdk/types"
	txtypes "github.com/cosmos/cosmos-sdk/types/tx"
	"github.com/stretchr/testify/require"

	"mirage/x/core/types"
)

// TestMultiMessageTxBody constructs a TxBody containing two distinct core
// messages (MsgSetUsername + MsgSetBiography) and verifies it serializes,
// round-trips, and preserves both type URLs. This validates that multi-message
// transactions are feasible on-chain and supports the indexer's tx_type="multi"
// classification.
func TestMultiMessageTxBody(t *testing.T) {
	pub, owner := testPubkeyOwner()

	msgA := &types.MsgSetUsername{
		Authority:      testAccAddressString(),
		EnvelopePubkey: pub,
		Target:         owner,
		Username:       "Anon-multi1",
	}
	msgB := &types.MsgSetBiography{
		Authority:      testAccAddressString(),
		EnvelopePubkey: pub,
		Target:         owner,
		Biography:      "hello from multi-msg test",
	}

	anyA, err := codectypes.NewAnyWithValue(msgA)
	require.NoError(t, err, "pack MsgSetUsername")
	anyB, err := codectypes.NewAnyWithValue(msgB)
	require.NoError(t, err, "pack MsgSetBiography")

	body := &txtypes.TxBody{
		Messages: []*codectypes.Any{anyA, anyB},
	}

	bz, err := body.Marshal()
	require.NoError(t, err, "marshal TxBody")
	require.True(t, len(bz) > 0, "serialized TxBody must be non-empty")

	var decoded txtypes.TxBody
	require.NoError(t, decoded.Unmarshal(bz), "unmarshal TxBody")
	require.Len(t, decoded.Messages, 2, "round-trip must preserve 2 messages")

	require.Equal(t, "/mirage.core.v1.MsgSetUsername", decoded.Messages[0].TypeUrl)
	require.Equal(t, "/mirage.core.v1.MsgSetBiography", decoded.Messages[1].TypeUrl)

	t.Logf("multi-msg TxBody: %d bytes, type_urls=%v",
		len(bz),
		[]string{decoded.Messages[0].TypeUrl, decoded.Messages[1].TypeUrl},
	)
}

// TestMultiMessageModuleDispatch constructs two core messages and dispatches
// them through the AppModule to verify both execute (or fail with expected
// validation errors) independently.
func TestMultiMessageModuleDispatch(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()
	am := newTestModule(mk)

	pub, owner := testPubkeyOwner()
	ensureUsername(t, mk, ctx, owner, "Anon-dispatch")
	setProfileLevel(t, mk, ctx, owner, 1)

	authority := testAccAddressString()

	msgSetUser := &types.MsgSetUsername{
		Authority:      authority,
		EnvelopePubkey: pub,
		Target:         owner,
		Username:       "Anon-multiA",
	}
	_, err := am.SetUsername(ctx, msgSetUser)
	require.NoError(t, err, "SetUsername should succeed")

	msgSetBio := &types.MsgSetBiography{
		Authority:      authority,
		EnvelopePubkey: pub,
		Target:         owner,
		Biography:      "bio from multi-msg dispatch",
	}
	_, err = am.SetBiography(ctx, msgSetBio)
	require.NoError(t, err, "SetBiography should succeed")

	t.Log("multi-msg dispatch: both messages executed independently")
}

// TestMultiMessageMixedTypes verifies that a TxBody can hold messages of
// different protobuf types (e.g. MsgFollowUser + MsgPost) and that type URLs
// are preserved after round-trip.
func TestMultiMessageMixedTypes(t *testing.T) {
	pub, owner := testPubkeyOwner()
	target := sdk.AccAddress(bytes.Repeat([]byte{0x09}, 20)).String()

	msgFollow := &types.MsgFollowUser{
		Authority:      testAccAddressString(),
		EnvelopePubkey: pub,
		Target:         owner,
		User:           target,
	}
	msgPost := &types.MsgPost{
		Authority:      testAccAddressString(),
		EnvelopePubkey: pub,
		Target:         owner,
		Topic:          "test",
		Title:          "Hello",
		Content:        "World",
	}

	anyFollow, err := codectypes.NewAnyWithValue(msgFollow)
	require.NoError(t, err)
	anyPost, err := codectypes.NewAnyWithValue(msgPost)
	require.NoError(t, err)

	body := &txtypes.TxBody{
		Messages: []*codectypes.Any{anyFollow, anyPost},
	}

	bz, err := body.Marshal()
	require.NoError(t, err)

	var decoded txtypes.TxBody
	require.NoError(t, decoded.Unmarshal(bz))
	require.Len(t, decoded.Messages, 2)
	require.Equal(t, "/mirage.core.v1.MsgFollowUser", decoded.Messages[0].TypeUrl)
	require.Equal(t, "/mirage.core.v1.MsgPost", decoded.Messages[1].TypeUrl)

	t.Logf("mixed multi-msg: type_urls=%v", []string{
		decoded.Messages[0].TypeUrl,
		decoded.Messages[1].TypeUrl,
	})
}
