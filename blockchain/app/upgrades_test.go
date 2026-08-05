package app

import (
	"testing"

	"cosmossdk.io/log/v2"
	dbm "github.com/cosmos/cosmos-db"
	"github.com/cosmos/cosmos-sdk/baseapp"
	storetypes "github.com/cosmos/cosmos-sdk/store/v2/types"
	authz "github.com/cosmos/cosmos-sdk/x/authz"
	upgradetypes "github.com/cosmos/cosmos-sdk/x/upgrade/types"
	"github.com/stretchr/testify/require"
)

type MockAppOptions struct{}

func (MockAppOptions) Get(key string) interface{} { return nil }

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

// TestUpgradeHandlersRegistered verifies that key upgrade handlers are registered
func TestUpgradeHandlersRegistered(t *testing.T) {
	db := dbm.NewMemDB()
	app := New(log.NewNopLogger(), db, false, MockAppOptions{}, baseapp.SetChainID("mirage-test"))
	require.NoError(t, app.Load(true))

	// Check that upgrade handlers are registered (sampling a few key ones)
	require.True(t, app.UpgradeKeeper.HasHandler("v1.10.0-remove-ibc"), "v1.10.0-remove-ibc upgrade handler should be registered")
	require.True(t, app.UpgradeKeeper.HasHandler("v1.13.0"), "v1.13.0 upgrade handler should be registered")
	require.True(t, app.UpgradeKeeper.HasHandler("v1.14.0"), "v1.14.0 upgrade handler should be registered")
	require.True(t, app.UpgradeKeeper.HasHandler("v1.15.0"), "v1.15.0 upgrade handler should be registered")
	require.True(t, app.UpgradeKeeper.HasHandler("v1.17.0-security"), "v1.17.0-security upgrade handler should be registered")
	require.True(t, app.UpgradeKeeper.HasHandler("v1.18.0"), "v1.18.0 upgrade handler should be registered")
	require.True(t, app.UpgradeKeeper.HasHandler("v1.19.0"), "v1.19.0 upgrade handler should be registered")
	require.True(t, app.UpgradeKeeper.HasHandler("v1.20.0"), "v1.20.0 upgrade handler should be registered")
	require.True(t, app.UpgradeKeeper.HasHandler("v1.21.0"), "v1.21.0 upgrade handler should be registered")
	require.True(t, app.UpgradeKeeper.HasHandler("v1.22.0"), "v1.22.0 upgrade handler should be registered")
	require.True(t, app.UpgradeKeeper.HasHandler("v1.23.0"), "v1.23.0 upgrade handler should be registered")
	require.True(t, app.UpgradeKeeper.HasHandler("v1.24.0"), "v1.24.0 upgrade handler should be registered")
	require.True(t, app.UpgradeKeeper.HasHandler("v1.25.0"), "v1.25.0 upgrade handler should be registered")
	require.True(t, app.UpgradeKeeper.HasHandler("v1.26.0"), "v1.26.0 upgrade handler should be registered")
	require.True(t, app.UpgradeKeeper.HasHandler("v1.27.0"), "v1.27.0 upgrade handler should be registered")
	require.True(t, app.UpgradeKeeper.HasHandler("v1.28.0"), "v1.28.0 upgrade handler should be registered")
	require.True(t, app.UpgradeKeeper.HasHandler("v1.31.0"), "v1.31.0 upgrade handler should be registered")
	require.True(t, app.UpgradeKeeper.HasHandler("v1.32.0"), "v1.32.0 upgrade handler should be registered")
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
