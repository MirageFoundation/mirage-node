package iavl

import (
	"bytes"
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

// flushSplitDB reproduces the 2026-07-12 chain-halt race deterministically.
// It wraps a MemDB so that as soon as a batch Delete for armKey (the root
// record a reference-root reformat replaces) is staged, the batch reports a
// huge byte size — making BatchWithFlusher flush on the very next op, i.e.
// forcing the flush boundary to land exactly at the reformat pair. With the
// old Delete-then-Set order that splits the pair: the referenced root is
// deleted on disk while its (version, 0) replacement is still pending, so
// every later version referencing it transiently reads as missing.
type flushSplitDB struct {
	dbm.DB
	armKey  []byte
	tripped bool
}

func (d *flushSplitDB) NewBatchWithSize(size int) dbm.Batch {
	return &flushSplitBatch{Batch: d.DB.NewBatchWithSize(size), owner: d}
}

func (d *flushSplitDB) NewBatch() dbm.Batch {
	return &flushSplitBatch{Batch: d.DB.NewBatch(), owner: d}
}

type flushSplitBatch struct {
	dbm.Batch
	owner *flushSplitDB
}

func (b *flushSplitBatch) Delete(key []byte) error {
	if bytes.Equal(key, b.owner.armKey) {
		b.owner.tripped = true
	}
	return b.Batch.Delete(key)
}

func (b *flushSplitBatch) GetByteSize() (int, error) {
	if b.owner.tripped {
		return 1 << 30, nil
	}
	return b.Batch.GetByteSize()
}

func (b *flushSplitBatch) Write() error {
	b.owner.tripped = false
	return b.Batch.Write()
}

func (b *flushSplitBatch) WriteSync() error {
	b.owner.tripped = false
	return b.Batch.WriteSync()
}

// The 2026-07-12 prod chain halt: pruning a version whose successor holds a
// reference root triggers a Delete(old root)/Set(reformatted root) pair on the
// shared auto-flushing batch. A flush landing between the pair made intact
// versions read as missing (GetRoot never sees pending batch writes), the
// fail-fast guard panicked on that phantom hole, and the panic dropped the
// pending batch — persisting REAL corruption. Two independent fixes make this
// scenario survivable (either alone suffices; this test fails only if both
// regress): (1) the reformat saves the replacement BEFORE deleting the
// original, so no flush boundary can strand a dangling reference; (2) the
// guard flushes the batch and re-probes before panicking, so a pending-batch
// artifact heals instead of halting.
func TestDeleteVersionsToSurvivesReformatFlushSplit(t *testing.T) {
	db := &flushSplitDB{DB: dbm.NewMemDB()}
	tree := NewMutableTree(db, 0, false, log.NewNopLogger())

	// v1..v4 each write a key (real roots); v5..v8 save with no changes, so
	// each stores a reference root pointing at v4's literal root (4,1) — the
	// long ref chains rarely-mutated stores produce in prod.
	for v := 1; v <= 4; v++ {
		_, err := tree.Set([]byte(fmt.Sprintf("k%03d", v)), []byte(fmt.Sprintf("val%d", v)))
		require.NoError(t, err)
		_, _, err = tree.SaveVersion()
		require.NoError(t, err)
	}
	for v := 5; v <= 8; v++ {
		_, _, err := tree.SaveVersion()
		require.NoError(t, err)
	}
	for v := 9; v <= 10; v++ {
		_, err := tree.Set([]byte(fmt.Sprintf("k%03d", v)), []byte(fmt.Sprintf("val%d", v)))
		require.NoError(t, err)
		_, _, err = tree.SaveVersion()
		require.NoError(t, err)
	}

	// Arm the split on v4's literal root record — the key the reformat deletes.
	db.armKey = nodeKeyFormat.Key(GetRootKey(4))

	require.NotPanics(t, func() {
		require.NoError(t, tree.DeleteVersionsTo(8))
	})

	// Kept versions must remain fully resolvable after the pass.
	for v := int64(9); v <= 10; v++ {
		_, err := tree.ndb.GetRoot(v)
		require.NoError(t, err, "kept version %d must stay readable", v)
	}
	itree, err := tree.GetImmutable(10)
	require.NoError(t, err)
	val, err := itree.Get([]byte("k010"))
	require.NoError(t, err)
	require.Equal(t, []byte("val10"), val)
}
