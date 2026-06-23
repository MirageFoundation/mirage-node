package iavl

import (
	"fmt"
	"testing"

	"cosmossdk.io/log"
	dbm "github.com/cosmos/iavl/db"
	"github.com/stretchr/testify/require"
)

// buildVersionedTree saves n versions, each writing a distinct key so every
// version has its own canonical root node persisted to the backing db.
func buildVersionedTree(t *testing.T, n int) *MutableTree {
	t.Helper()
	tree := NewMutableTree(dbm.NewMemDB(), 0, false, log.NewNopLogger())
	for v := 1; v <= n; v++ {
		_, err := tree.Set([]byte(fmt.Sprintf("k%03d", v)), []byte(fmt.Sprintf("val%d", v)))
		require.NoError(t, err)
		_, _, err = tree.SaveVersion()
		require.NoError(t, err)
	}
	return tree
}

// dropVersionRoot removes a single version's root entry from the backing db,
// making GetRoot(version) return ErrVersionDoesNotExist — i.e. it punches a
// hole in the persisted version history without touching its neighbours.
func dropVersionRoot(t *testing.T, tree *MutableTree, version int64) {
	t.Helper()
	b := tree.ndb.db.NewBatch()
	require.NoError(t, b.Delete(nodeKeyFormat.Key(GetRootKey(version))))
	require.NoError(t, b.WriteSync())
	require.NoError(t, b.Close())
	_, err := tree.ndb.GetRoot(version)
	require.ErrorIs(t, err, ErrVersionDoesNotExist, "expected version %d to read as missing", version)
}

func capturePanic(f func()) (msg string) {
	defer func() {
		if r := recover(); r != nil {
			msg = fmt.Sprint(r)
		}
	}()
	f()
	return ""
}

// A version missing in the MIDDLE of present history is DB corruption, not a
// state-sync gap: pruning must halt loudly (CONSENSUS_FATAL) rather than
// silently skip and advance past it (the prune-race app-hash divergence vector).
func TestDeleteVersionsToHaltsOnMidHistoryHole(t *testing.T) {
	tree := buildVersionedTree(t, 8)
	dropVersionRoot(t, tree, 4) // v1..3 present, v4 missing, v5..8 present

	msg := capturePanic(func() { _ = tree.DeleteVersionsTo(6) })
	require.Contains(t, msg, "CONSENSUS_FATAL:PRUNE_HOLE")
	require.Contains(t, msg, "version=4")
}

// Versions missing as a CONTIGUOUS prefix at the bottom are the legitimate
// state-sync gap (those versions were never written to this node). Pruning must
// skip them and keep going — no panic, no error.
func TestDeleteVersionsToSkipsBottomStateSyncGap(t *testing.T) {
	tree := buildVersionedTree(t, 8)
	dropVersionRoot(t, tree, 1)
	dropVersionRoot(t, tree, 2) // v1,v2 missing (bottom gap), v3..8 present

	require.NotPanics(t, func() {
		require.NoError(t, tree.DeleteVersionsTo(6))
	})
}
