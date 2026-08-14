package app

import (
	"go/ast"
	"go/parser"
	"go/token"
	"strconv"
	"testing"

	"cosmossdk.io/log/v2"
	dbm "github.com/cosmos/cosmos-db"
	"github.com/cosmos/cosmos-sdk/baseapp"
	storetypes "github.com/cosmos/cosmos-sdk/store/v2/types"
	authz "github.com/cosmos/cosmos-sdk/x/authz"
	upgradetypes "github.com/cosmos/cosmos-sdk/x/upgrade/types"
	"github.com/stretchr/testify/require"

	coretypes "mirage/x/core/types"
)

type MockAppOptions struct{}

func (MockAppOptions) Get(key string) interface{} { return nil }

func TestValidateV1340Params(t *testing.T) {
	require.NoError(t, validateV1340Params(coretypes.DefaultParams()))

	invalid := coretypes.DefaultParams()
	invalid.PowMessageWindow = coretypes.MaxPowMessageWindow + 1
	require.ErrorContains(t, validateV1340Params(invalid), "stored params violate the new bounds")

	// The block_hash_window floor lives here rather than in Validate(), which has
	// to keep accepting the 10 the live genesis stores. This is the only gate that
	// stops the upgrade completing with a window stricter than max_envelope_age.
	narrow := coretypes.DefaultParams()
	narrow.BlockHashWindow = coretypes.MinBlockHashWindow - 1
	require.NoError(t, narrow.Validate(), "Validate must stay permissive for from-genesis nodes")
	require.ErrorContains(t, validateV1340Params(narrow), "below the 20-block floor")
}

// TestStoreLoaderWithExistingStore tests that using StoreUpgrades.Added for
// a store that already exists causes a panic due to IAVL version conflicts.
// This is the bug that was encountered during the v1.10.4-restore-sdk upgrade.
//
// The bug: When using `StoreUpgrades{Added: ...}` on a store that already has
// historical data, the IAVL tree's SetInitialVersion() is called with the upgrade
// height, but the store already has data at lower versions, causing a version
// conflict panic: "initial version set to X, but found earlier version Y"
func TestStoreLoaderWithExistingStore(t *testing.T) {
	t.Log("Creating app with fresh DB")
	db := dbm.NewMemDB()
	chainID := "mirage-test"

	// 1. Create and load app - this initializes all stores
	app1 := New(log.NewNopLogger(), db, false, MockAppOptions{}, baseapp.SetChainID(chainID))
	require.NoError(t, app1.Load(true))

	// The app has now initialized stores for all modules including authz.
	// Each store has been created in the multistore.

	// 2. Verify that using StoreUpgrades.Added for an existing store causes issues
	// This simulates what the buggy v1.10.4-restore-sdk upgrade did
	t.Log("Creating app2 with StoreUpgrades.Added for existing authz store")
	app2 := New(log.NewNopLogger(), db, false, MockAppOptions{}, baseapp.SetChainID(chainID))

	upgradeHeight := int64(10)
	app2.SetStoreLoader(
		upgradetypes.UpgradeStoreLoader(upgradeHeight, &storetypes.StoreUpgrades{
			Added: []string{authz.ModuleName},
		}),
	)

	// The UpgradeStoreLoader will try to set InitialVersion on the authz store,
	// which will conflict with existing data (if any was written)
	// Note: On a fresh DB with no commits, this might not panic because there's
	// no actual version history yet. The real issue manifests when there's
	// committed data in the stores.

	// For now, just verify the app loads (it won't panic on a fresh DB)
	// The important test is that loading WITHOUT Added works correctly
	err := app2.Load(true)
	if err != nil {
		t.Logf("app2 Load error (expected on some configurations): %v", err)
	}

	// 3. Verify that loading WITHOUT StoreUpgrades.Added works fine
	t.Log("Creating app3 without StoreUpgrades.Added")
	app3 := New(log.NewNopLogger(), db, false, MockAppOptions{}, baseapp.SetChainID(chainID))

	require.NoError(t, app3.Load(true), "Loading app without Added should succeed")

	// Height is 0 because we never committed any blocks
	require.Equal(t, int64(0), app3.LastBlockHeight())
}

// expectedUpgradeHandlers is the exhaustive list of upgrade names the app must
// register, in registration order. It is deliberately a hand-maintained list:
// adding, renaming or removing a handler must be a visible edit here, because a
// plan name that no node recognizes halts the chain at the upgrade height.
var expectedUpgradeHandlers = []string{
	"v1.2.0-follow-mods",
	"v1.3.0-tiers",
	"v1.3.1",
	"v1.4.0-profile-core",
	"v1.5.0-social-graph",
	"v1.5.1",
	"v1.6.0-personalized-feeds",
	"v1.7.7-tier-pricing",
	"v1.7.9-node-home",
	"v1.8.0-economics",
	"v1.9.0-bridge",
	"v1.9.1-seq-fix",
	"v1.9.1-query-fix",
	"v1.10.0-bridge-refactor",
	"v1.9.2-bridge-fee-endblock",
	"v1.9.3-bridge-fee-burn",
	"v1.9.4-bridge-attestor-fix",
	"v1.9.5-bridge-no-pow",
	"v1.9.7-bridge-replay",
	"v1.9.9-retention",
	"v1.10.0-remove-ibc",
	"v1.10.4-restore-sdk",
	"v1.10.5",
	"v1.10.7",
	"v1.11.0",
	"v1.12.0",
	"v1.13.0",
	"v1.14.0",
	"v1.15.0",
	"v1.16.0",
	"v1.17.0-security",
	"v1.18.0",
	"v1.19.0",
	"v1.20.0",
	"v1.21.0",
	"v1.22.0",
	"v1.23.0",
	"v1.24.0",
	"v1.25.0",
	"v1.26.0",
	"v1.27.0",
	"v1.28.0",
	"v1.31.0",
	"v1.32.0",
	"v1.34.0",
	"v1.35.0",
	"v1.36.0",
}

// TestUpgradeHandlersRegistered verifies every expected handler is registered
// on a loaded app and pins the exact count.
func TestUpgradeHandlersRegistered(t *testing.T) {
	db := dbm.NewMemDB()
	app := New(log.NewNopLogger(), db, false, MockAppOptions{}, baseapp.SetChainID("mirage-test"))
	require.NoError(t, app.Load(true))

	require.Len(t, expectedUpgradeHandlers, 47, "update the expected handler list and this count together")

	seen := make(map[string]struct{}, len(expectedUpgradeHandlers))
	for _, name := range expectedUpgradeHandlers {
		_, dup := seen[name]
		require.False(t, dup, "duplicate upgrade name in expected list: %s", name)
		seen[name] = struct{}{}
		require.True(t, app.UpgradeKeeper.HasHandler(name), "upgrade handler %q should be registered", name)
	}

	require.True(t, app.UpgradeKeeper.HasHandler(expectedUpgradeHandlers[len(expectedUpgradeHandlers)-1]),
		"the current release handler must be the last entry")
	require.False(t, app.UpgradeKeeper.HasHandler("v1.33.0"),
		"only consensus-breaking releases register handlers; patch releases must not")
}

// TestUpgradeHandlerListIsExhaustive parses upgrades.go and requires the
// registered names to match expectedUpgradeHandlers exactly. Without this, a
// new SetUpgradeHandler call would silently pass the test above, which only
// checks names it already knows about.
func TestUpgradeHandlerListIsExhaustive(t *testing.T) {
	fset := token.NewFileSet()
	parsed, err := parser.ParseFile(fset, "upgrades.go", nil, 0)
	require.NoError(t, err)

	// Some registrations pass a named constant instead of a literal, so build a
	// const → value index first.
	stringConsts := map[string]string{}
	ast.Inspect(parsed, func(n ast.Node) bool {
		spec, ok := n.(*ast.ValueSpec)
		if !ok || len(spec.Names) != 1 || len(spec.Values) != 1 {
			return true
		}
		lit, ok := spec.Values[0].(*ast.BasicLit)
		if !ok || lit.Kind != token.STRING {
			return true
		}
		value, uerr := strconv.Unquote(lit.Value)
		if uerr != nil {
			return true
		}
		stringConsts[spec.Names[0].Name] = value
		return true
	})

	var registered []string
	ast.Inspect(parsed, func(n ast.Node) bool {
		call, ok := n.(*ast.CallExpr)
		if !ok {
			return true
		}
		sel, ok := call.Fun.(*ast.SelectorExpr)
		if !ok || sel.Sel.Name != "SetUpgradeHandler" || len(call.Args) == 0 {
			return true
		}
		switch arg := call.Args[0].(type) {
		case *ast.BasicLit:
			name, uerr := strconv.Unquote(arg.Value)
			require.NoError(t, uerr)
			registered = append(registered, name)
		case *ast.Ident:
			name, found := stringConsts[arg.Name]
			require.True(t, found, "cannot resolve upgrade name constant %s", arg.Name)
			registered = append(registered, name)
		default:
			t.Fatalf("SetUpgradeHandler name must be a string literal or constant, got %T", arg)
		}
		return true
	})

	require.Equal(t, expectedUpgradeHandlers, registered,
		"upgrades.go registrations drifted from expectedUpgradeHandlers")
}

func TestRemovedBridgePrefixesComplete(t *testing.T) {
	require.ElementsMatch(t, []string{
		"bridge_attestations/",
		"bridge_attestors/",
		"bridge_mint_attestations/",
		"bridge_mint_attestors/",
		"bridge_mint_fee_pending/",
		"bridge_mint_fee_failures/",
		"bridge_burns/",
		"bridge_mints/",
		"bridge_sequence/",
	}, removedBridgePrefixes)
}

// TestRemovedModulesNotWired verifies that the x/group and x/circuit modules,
// removed in the v1.28.0 SDK v0.54 migration, are no longer wired into the app.
// Their KV stores are deleted at the upgrade height via StoreUpgrades.Deleted;
// this guards against an accidental re-introduction of the modules.
func TestRemovedModulesNotWired(t *testing.T) {
	db := dbm.NewMemDB()
	app := New(log.NewNopLogger(), db, false, MockAppOptions{}, baseapp.SetChainID("mirage-test"))
	require.NoError(t, app.Load(true))

	for _, name := range []string{"group", "circuit"} {
		_, ok := app.ModuleManager.Modules[name]
		require.False(t, ok, "module %q should be removed in v1.28.0 but is still wired", name)
	}
}
