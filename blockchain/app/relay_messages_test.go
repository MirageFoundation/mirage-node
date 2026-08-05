package app

import (
	"testing"

	coretypes "mirage/x/core/types"

	sdk "github.com/cosmos/cosmos-sdk/types"
	"github.com/stretchr/testify/require"
)

// TestRelayMessageRegistryParity pins the shared relay registry: every
// prototype must be recognized by isRelayMessage, and MsgSetLevel (gov-only,
// routed via stdAnte) must NOT be in the registry.
func TestRelayMessageRegistryParity(t *testing.T) {
	prototypes := relayMessagePrototypes()
	require.NotEmpty(t, prototypes)
	require.Equal(t, 25, len(prototypes), "update this count when adding/removing relay message types")

	seen := make(map[string]struct{}, len(prototypes))
	for _, m := range prototypes {
		url := sdk.MsgTypeURL(m)
		_, dup := seen[url]
		require.False(t, dup, "duplicate relay prototype: %s", url)
		seen[url] = struct{}{}
		require.True(t, isRelayMessage(m), "registry entry must be isRelayMessage: %T (%s)", m, url)
	}

	// MsgSetLevel is governance-only and routes through stdAnte — it must
	// never appear in the relay registry (dead RelaySig branch was removed).
	require.False(t, isRelayMessage(&coretypes.MsgSetLevel{}),
		"MsgSetLevel must not be a relay message")
}

func TestMirageAnteRouterRejectsRemovedBridgeMessages(t *testing.T) {
	removed := []sdk.Msg{
		&coretypes.MsgBridgeBurn{},
		&coretypes.MsgBridgeAttest{},
		&coretypes.MsgBridgeMinted{},
		&coretypes.MsgBridgeAttestBurned{},
		&coretypes.MsgBridgeAttestMinted{},
	}
	unexpectedAnte := func(ctx sdk.Context, _ sdk.Tx, _ bool) (sdk.Context, error) {
		t.Fatal("removed bridge message reached an ante chain")
		return ctx, nil
	}

	for _, msg := range removed {
		t.Run(sdk.MsgTypeURL(msg), func(t *testing.T) {
			_, err := mirageAnteRouter(
				sdk.Context{},
				mockTx{msgs: []sdk.Msg{msg}},
				false,
				GovAuthorityDecorator{},
				unexpectedAnte,
				unexpectedAnte,
			)
			require.EqualError(t, err, "bridge messages were removed in v1.31.0")
		})
	}
}
