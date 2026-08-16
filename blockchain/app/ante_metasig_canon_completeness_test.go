package app

import (
	"go/ast"
	"go/parser"
	"go/token"
	"reflect"
	"sort"
	"strings"
	"testing"

	sdk "github.com/cosmos/cosmos-sdk/types"
	"github.com/stretchr/testify/require"
)

// canonExemptFields are the message fields a metasig closure must NOT sign.
//
// Authority is the relay operator's own address, which the outer Cosmos
// signature already covers, and EnvelopeSignature is the signature itself.
var canonExemptFields = map[string]bool{
	"Authority":         true,
	"EnvelopeSignature": true,
}

// TestMetasigCanonCoversEveryField is the L-8 regression test.
//
// The existing completeness harness drives the buildCanonFor* PoW builders, but
// those are not the authentication boundary — the 25 closures inside
// RelaySigDecorator.AnteHandle are, and nothing covered them. Two of the pinned
// PoW builders (Award, Subscribe) are in fact dead code, because both types
// reject proof of work outright, so for those two the harness was checking
// something the chain never runs.
//
// This walks the real switch in ante_metasig.go and asserts that every field of
// every relay message appears inside that type's signature closure. A field
// added to a relay message without a matching line in its closure is a field the
// user does not sign but the handler acts on, which is the single most dangerous
// shape in the whole envelope scheme.
func TestMetasigCanonCoversEveryField(t *testing.T) {
	fset := token.NewFileSet()
	file, err := parser.ParseFile(fset, "ante_metasig.go", nil, 0)
	require.NoError(t, err)

	signed := signedFieldsByMessage(t, file)
	require.NotEmpty(t, signed, "found no signature closures; the switch was probably restructured")

	for _, proto := range relayMessagePrototypes() {
		typ := reflect.TypeOf(proto).Elem()
		name := typ.Name()

		t.Run(name, func(t *testing.T) {
			got, ok := signed[name]
			require.True(t, ok, "%s has no signature closure in ante_metasig.go, so nothing about it is authenticated", name)

			var missing []string
			for i := 0; i < typ.NumField(); i++ {
				field := typ.Field(i).Name
				if strings.HasPrefix(field, "XXX_") || canonExemptFields[field] {
					continue
				}
				if !got[field] {
					missing = append(missing, field)
				}
			}
			sort.Strings(missing)
			require.Empty(t, missing,
				"%s: these fields execute but are not covered by the signature closure: %v", name, missing)
		})
	}
}

// TestEveryRelayMessageHasASignatureClosure pins the other direction: a relay
// message with no closure at all would fall through the switch unauthenticated.
func TestEveryRelayMessageHasASignatureClosure(t *testing.T) {
	fset := token.NewFileSet()
	file, err := parser.ParseFile(fset, "ante_metasig.go", nil, 0)
	require.NoError(t, err)

	signed := signedFieldsByMessage(t, file)
	for _, proto := range relayMessagePrototypes() {
		name := reflect.TypeOf(proto).Elem().Name()
		require.Contains(t, signed, name,
			"%s is registered as a relay message but has no signature closure", name)
	}
	require.Len(t, signed, len(relayMessagePrototypes()),
		"a signature closure exists for a type that is not a registered relay message, or vice versa")
}

// signedFieldsByMessage returns, per message type name, the set of field names
// referenced inside that type's verifyRelaySignature closure.
func signedFieldsByMessage(t *testing.T, file *ast.File) map[string]map[string]bool {
	t.Helper()
	out := map[string]map[string]bool{}

	ast.Inspect(file, func(n ast.Node) bool {
		clause, ok := n.(*ast.CaseClause)
		if !ok || len(clause.List) != 1 {
			return true
		}
		star, ok := clause.List[0].(*ast.StarExpr)
		if !ok {
			return true
		}
		sel, ok := star.X.(*ast.SelectorExpr)
		if !ok {
			return true
		}
		pkg, ok := sel.X.(*ast.Ident)
		if !ok || pkg.Name != "coretypes" {
			return true
		}

		fields := map[string]bool{}
		for _, stmt := range clause.Body {
			ast.Inspect(stmt, func(inner ast.Node) bool {
				call, ok := inner.(*ast.CallExpr)
				if !ok {
					return true
				}
				fn, ok := call.Fun.(*ast.Ident)
				if !ok || fn.Name != "verifyRelaySignature" {
					return true
				}
				// The closure is the last argument.
				lit, ok := call.Args[len(call.Args)-1].(*ast.FuncLit)
				if !ok {
					return true
				}
				ast.Inspect(lit, func(node ast.Node) bool {
					s, ok := node.(*ast.SelectorExpr)
					if !ok {
						return true
					}
					recv, ok := s.X.(*ast.Ident)
					if !ok || recv.Name != "m" {
						return true
					}
					fields[s.Sel.Name] = true
					return true
				})
				return true
			})
		}
		if len(fields) > 0 {
			out[sel.Sel.Name] = fields
		}
		return true
	})

	return out
}

// TestRelayPrototypesAreMessages is a guard for the two tests above: they key off
// reflect over relayMessagePrototypes(), so a prototype that is not a struct
// pointer would silently cover nothing.
func TestRelayPrototypesAreMessages(t *testing.T) {
	for _, proto := range relayMessagePrototypes() {
		typ := reflect.TypeOf(proto)
		require.Equal(t, reflect.Ptr, typ.Kind(), "%T must be a pointer", proto)
		require.Equal(t, reflect.Struct, typ.Elem().Kind(), "%T must point at a struct", proto)
		require.NotEmpty(t, sdk.MsgTypeURL(proto))
	}
}
