package app

import (
	"go/ast"
	"go/parser"
	"go/token"
	"reflect"
	"testing"

	coretypes "mirage/x/core/types"

	sdk "github.com/cosmos/cosmos-sdk/types"
	gogoproto "github.com/cosmos/gogoproto/proto"
	"github.com/stretchr/testify/require"
	"google.golang.org/protobuf/reflect/protoreflect"
)

// TestRelayMessageRegistryParity pins the shared relay registry: every
// prototype must be recognized by isRelayMessage, and MsgSetLevel (gov-only,
// routed via stdAnte) must NOT be in the registry.
func TestRelayMessageRegistryParity(t *testing.T) {
	prototypes := relayMessagePrototypes()
	require.NotEmpty(t, prototypes)
	require.Equal(t, 40, len(prototypes), "update this count when adding/removing relay message types")

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

// relayMessageNames returns the Go type name of every registry prototype
// (e.g. "MsgPost").
func relayMessageNames(t *testing.T) map[string]struct{} {
	t.Helper()
	names := make(map[string]struct{})
	for _, msg := range relayMessagePrototypes() {
		typ := reflect.TypeOf(msg)
		require.Equal(t, reflect.Ptr, typ.Kind(), "registry prototypes must be pointers: %T", msg)
		names[typ.Elem().Name()] = struct{}{}
	}
	return names
}

// switchedCoreMessages parses file and returns the coretypes.Msg* names that
// appear as concrete type-switch cases inside the named method.
//
// This is a source-level parity check on purpose. Both decorators dispatch
// through a large type switch whose branches need a keeper, a header and a
// signed envelope to execute; driving all 25 branches behaviorally would need
// production abstractions introduced solely for testability. Parsing the switch
// keeps the invariant enforced without reshaping the decorators.
func switchedCoreMessages(t *testing.T, file, receiverType, method string) map[string]struct{} {
	t.Helper()
	fset := token.NewFileSet()
	parsed, err := parser.ParseFile(fset, file, nil, 0)
	require.NoError(t, err, "parsing %s", file)

	cases := make(map[string]struct{})
	found := false
	for _, decl := range parsed.Decls {
		fn, ok := decl.(*ast.FuncDecl)
		if !ok || fn.Name.Name != method || fn.Recv == nil || len(fn.Recv.List) != 1 {
			continue
		}
		recv := fn.Recv.List[0].Type
		if star, isStar := recv.(*ast.StarExpr); isStar {
			recv = star.X
		}
		ident, ok := recv.(*ast.Ident)
		if !ok || ident.Name != receiverType {
			continue
		}
		found = true
		ast.Inspect(fn, func(n ast.Node) bool {
			clause, ok := n.(*ast.CaseClause)
			if !ok {
				return true
			}
			for _, expr := range clause.List {
				star, isStar := expr.(*ast.StarExpr)
				if !isStar {
					continue
				}
				sel, isSel := star.X.(*ast.SelectorExpr)
				if !isSel {
					continue
				}
				pkg, isIdent := sel.X.(*ast.Ident)
				if !isIdent || pkg.Name != "coretypes" {
					continue
				}
				cases[sel.Sel.Name] = struct{}{}
			}
			return true
		})
	}
	require.True(t, found, "method %s.%s not found in %s", receiverType, method, file)
	return cases
}

// TestRelayDecoratorSwitchParity pins L-5: every registry prototype must have
// its own concrete branch in BOTH ante decorators. A registry entry with no
// PowDecorator branch hits the fail-closed default and is unusable; a registry
// entry with no RelaySigDecorator branch would skip envelope signature
// verification, which is an authorization hole.
func TestRelayDecoratorSwitchParity(t *testing.T) {
	registry := relayMessageNames(t)
	require.Len(t, registry, 40, "update this count when adding/removing relay message types")

	powCases := switchedCoreMessages(t, "ante_pow.go", "PowDecorator", "AnteHandle")
	sigCases := switchedCoreMessages(t, "ante_metasig.go", "RelaySigDecorator", "AnteHandle")

	for name := range registry {
		require.Contains(t, powCases, name, "registry message %s has no PowDecorator branch", name)
		require.Contains(t, sigCases, name, "registry message %s has no RelaySigDecorator branch", name)
	}
	for name := range powCases {
		require.Contains(t, registry, name, "PowDecorator handles %s but it is not in the relay registry", name)
	}
	for name := range sigCases {
		require.Contains(t, registry, name, "RelaySigDecorator handles %s but it is not in the relay registry", name)
	}
}

// governanceOnlyEnvelopeMessages lists core messages that carry envelope fields
// but are never relay-routed: they are submitted by governance and travel
// through stdAnte, so envelope verification and PoW do not apply to them.
// Adding a message here is an explicit decision, not a default.
var governanceOnlyEnvelopeMessages = map[string]struct{}{
	"MsgSetLevel": {},
}

var retiredEnvelopeMessages = map[string]struct{}{
	"MsgEnableAgent":   {},
	"MsgDisableAgent":  {},
	"MsgSetAgents":     {},
	"MsgFollowTopic":   {},
	"MsgUnfollowTopic": {},
	"MsgBlockTopic":    {},
	"MsgUnblockTopic":  {},
	"MsgAnnotate":      {},
}

// TestEveryEnvelopeMessageIsRoutedOrGovernanceOnly pins the other half of L-5:
// a newly generated core message that carries envelope fields must either join
// the relay registry (and therefore both decorator switches, enforced above) or
// be explicitly recorded as governance-only. Silence is not an option — an
// envelope-bearing message that is in neither set would reach a handler with an
// unverified envelope.
func TestEveryEnvelopeMessageIsRoutedOrGovernanceOnly(t *testing.T) {
	fd, err := gogoproto.HybridResolver.FindFileByPath("mirage/core/v1/tx.proto")
	require.NoError(t, err)

	registry := relayMessageNames(t)
	checked := 0
	messages := fd.Messages()
	for i := 0; i < messages.Len(); i++ {
		msg := messages.Get(i)
		if msg.Fields().ByName(protoreflect.Name("envelope_pubkey")) == nil {
			continue
		}
		name := string(msg.Name())
		checked++
		_, relayed := registry[name]
		_, govOnly := governanceOnlyEnvelopeMessages[name]
		_, retired := retiredEnvelopeMessages[name]
		require.True(t, relayed || govOnly || retired,
			"%s carries envelope fields but is neither relay-routed, governance-only, nor retired", name)
		require.False(t, relayed && govOnly,
			"%s cannot be both relay-routed and governance-only", name)
	}
	require.GreaterOrEqual(t, checked, len(registry),
		"expected at least every registry message to be discovered through the proto descriptor")
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
