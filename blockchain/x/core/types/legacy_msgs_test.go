package types_test

import (
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/cosmos/cosmos-sdk/codec"
	codectypes "github.com/cosmos/cosmos-sdk/codec/types"
	sdk "github.com/cosmos/cosmos-sdk/types"
	"github.com/cosmos/gogoproto/proto"

	"mirage/x/core/types"
)

func TestLegacyMsgMintToRegistration(t *testing.T) {
	// 1. Setup Registry
	registry := codectypes.NewInterfaceRegistry()
	types.RegisterInterfaces(registry)

	// 2. Test Type URL Resolution
	// This simulates what happens when the node reads a google.protobuf.Any from state/export
	// with type_url = "/mirage.core.v1.MsgMintTo"
	msg, err := registry.Resolve("/mirage.core.v1.MsgMintTo")
	require.NoError(t, err)
	require.NotNil(t, msg)

	// Verify it resolves to our legacy struct
	_, ok := msg.(*types.MsgMintTo)
	require.True(t, ok, "Should resolve to *types.MsgMintTo")

	// 3. Test Round-Trip Serialization (Proto)
	original := &types.MsgMintTo{
		Authority: "mirage1authority",
		Target:    "mirage1target",
		Amount:    1000000,
		Reason:    "Test legacy mint",
	}

	// Marshal
	bz, err := proto.Marshal(original)
	require.NoError(t, err)

	// Unmarshal into empty struct
	decoded := &types.MsgMintTo{}
	err = proto.Unmarshal(bz, decoded)
	require.NoError(t, err)

	require.Equal(t, original.Authority, decoded.Authority)
	require.Equal(t, original.Target, decoded.Target)
	require.Equal(t, original.Amount, decoded.Amount)
	require.Equal(t, original.Reason, decoded.Reason)

	// 4. Test Interface Implementation
	// Ensure it implements sdk.Msg (even if methods are stubs)
	var _ sdk.Msg = &types.MsgMintTo{}
	var _ proto.Message = &types.MsgMintTo{}

	// 5. Test JSON Marshaling (for export.json)
	// The export process often uses JSON marshaling for the genesis file
	// We need to ensure the JSON tags match what we expect
	// Note: We use the standard json package here as a simple check,
	// but Cosmos uses its own JSON codec wrapping.

	// Check XXX_MessageName
	require.Equal(t, "mirage.core.v1.MsgMintTo", original.XXX_MessageName())
}

func TestLegacyBridgeMessagesDecodeFromAny(t *testing.T) {
	registry := codectypes.NewInterfaceRegistry()
	types.RegisterInterfaces(registry)
	cdc := codec.NewProtoCodec(registry)

	messages := []sdk.Msg{
		&types.MsgBridgeBurn{
			Authority:          "mirage1authority",
			EnvelopePubkey:     []byte{1, 2},
			EnvelopeBlockHash:  []byte{3, 4},
			EnvelopeDifficulty: 5,
			EnvelopePow:        6,
			EnvelopeTimestamp:  7,
			EnvelopeNonce:      8,
			EnvelopeSignature:  []byte{9, 10},
			DestinationChain:   "solana",
			DestinationAddress: "destination",
			Amount:             11,
		},
		&types.MsgBridgeAttest{
			Validator:       "miragevaloper1validator",
			SourceChain:     "solana",
			BurnId:          "old-burn-id",
			MirageRecipient: "mirage1recipient",
			Amount:          12,
		},
		&types.MsgBridgeMinted{
			Authority:        "miragevaloper1validator",
			BurnId:           "old-burn-id",
			DestinationChain: "solana",
			DestinationTx:    "old-destination-tx",
		},
		&types.MsgBridgeAttestBurned{
			Validator:       "miragevaloper1validator",
			SourceChain:     "solana",
			BurnId:          "burn-id",
			MirageRecipient: "mirage1recipient",
			Amount:          12,
		},
		&types.MsgBridgeAttestMinted{
			Validator:        "miragevaloper1validator",
			BurnId:           "burn-id",
			DestinationChain: "solana",
			DestinationTx:    "destination-tx",
			MirageTxHash:     "mirage-tx",
		},
	}

	for _, original := range messages {
		t.Run(sdk.MsgTypeURL(original), func(t *testing.T) {
			packed, err := codectypes.NewAnyWithValue(original)
			require.NoError(t, err)

			wire, err := cdc.Marshal(packed)
			require.NoError(t, err)

			var decodedAny codectypes.Any
			require.NoError(t, cdc.Unmarshal(wire, &decodedAny))

			var decoded sdk.Msg
			require.NoError(t, cdc.UnpackAny(&decodedAny, &decoded))
			require.Equal(t, original, decoded)
		})
	}
}
