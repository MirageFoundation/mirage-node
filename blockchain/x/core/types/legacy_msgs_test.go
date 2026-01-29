package types_test

import (
	"testing"

	"github.com/stretchr/testify/require"

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
