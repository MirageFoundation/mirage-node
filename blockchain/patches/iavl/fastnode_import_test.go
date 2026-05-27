package iavl

import (
	"errors"
	"sort"
	"testing"

	"cosmossdk.io/log"
	dbm "github.com/cosmos/iavl/db"
	"github.com/stretchr/testify/require"
)

// fastNodeImportFixture builds a destination MutableTree whose canonical IAVL
// tree is fully populated (via Export/Import) at `version`, but whose
// fast-node secondary index is empty even though it claims to be current at
// `version`. This is exactly the production failure shape we're protecting
// against:
//
//   - state-sync verifies the canonical app hash and restores it
//   - the local fast-node index never gets the imported keys
//   - any read path that trusts "fast-node missing" as authoritative will
//     return nil for keys that are demonstrably in the verified state.
//
// keys are intentionally chosen to be representative — staking/params (the
// concrete BondDenom panic vector), core/recent_block_hashes (the PoW
// recent-hash read path that ran during the original divergence) and
// core/pow_msg_count:4854225 (the original divergence height marker). The
// test does not depend on Cosmos-SDK store key encoding; the IAVL invariant
// being checked is "all read paths must agree with canonical IAVL when the
// fast-node index is incomplete".
func fastNodeImportFixture(t *testing.T) (dst *MutableTree, keys map[string][]byte, version int64) {
	t.Helper()

	keys = map[string][]byte{
		"staking/params":             []byte("bond_denom=umirage"),
		"core/recent_block_hashes":   []byte(`["0c292525581082f0ee257981a555ded8a73a5efa75986ad02cde95eecf3a9e42"]`),
		"core/pow_msg_count:4854225": []byte{0, 0, 0, 0, 0, 0, 0, 1},
	}

	src := NewMutableTree(dbm.NewMemDB(), 0, false, log.NewNopLogger())
	for key, value := range keys {
		_, err := src.Set([]byte(key), value)
		require.NoError(t, err)
	}
	_, srcVersion, err := src.SaveVersion()
	require.NoError(t, err)
	version = srcVersion

	exporter, err := src.Export()
	require.NoError(t, err)
	defer exporter.Close()

	dst = NewMutableTree(dbm.NewMemDB(), 0, false, log.NewNopLogger())

	// Mark fast storage current at `version` BEFORE importing, so the destination
	// tree believes its fast index is authoritative even though it never gets
	// populated for the imported keys. This is the exact shape that produced the
	// post-state-sync BondDenom panic.
	require.NoError(t, dst.ndb.SetFastStorageVersionToBatch(version))
	require.NoError(t, dst.ndb.Commit())

	importer, err := dst.Import(version)
	require.NoError(t, err)
	for {
		node, err := exporter.Next()
		if errors.Is(err, ErrorExportDone) {
			break
		}
		require.NoError(t, err)
		require.NoError(t, importer.Add(node))
	}
	require.NoError(t, importer.Commit())

	return dst, keys, version
}

// TestImportedTreeGetReadsCanonicalTreeWhenFastNodeMissing pins
// ImmutableTree.Get correctness across the production failure shape: every
// imported key must be readable from the canonical tree even though the
// fast-node index is empty and marked current. Was the BondDenom panic
// regression vector (staking/params returned nil → mint.BondDenom == "" →
// sdk.NewCoin("", ...) panic).
func TestImportedTreeGetReadsCanonicalTreeWhenFastNodeMissing(t *testing.T) {
	dst, keys, _ := fastNodeImportFixture(t)

	for key, value := range keys {
		got, err := dst.Get([]byte(key))
		require.NoError(t, err)
		require.Equal(t, value, got, "Get for %q must come from canonical IAVL when fast-node is missing", key)
	}
}

// TestImportedTreeGetVersionedReadsCanonicalTreeWhenFastNodeMissing pins
// MutableTree.GetVersioned. Same bug class as Get: the upstream code path
// returned nil for fast-node-miss + version == latest, which is the exact
// short-circuit we removed.
func TestImportedTreeGetVersionedReadsCanonicalTreeWhenFastNodeMissing(t *testing.T) {
	dst, keys, version := fastNodeImportFixture(t)

	for key, value := range keys {
		got, err := dst.GetVersioned([]byte(key), version)
		require.NoError(t, err)
		require.Equal(t, value, got, "GetVersioned for %q must come from canonical IAVL when fast-node is missing", key)
	}
}

// TestGetVersionedReadsHistoricalCanonicalTreeWhenFastNodeIsNewer pins the
// non-latest version path. If the fast-node index has a newer value than the
// requested version, GetVersioned must not return that newer value; it must
// fall through to the canonical tree at the requested version.
func TestGetVersionedReadsHistoricalCanonicalTreeWhenFastNodeIsNewer(t *testing.T) {
	tree := NewMutableTree(dbm.NewMemDB(), 0, false, log.NewNopLogger())
	key := []byte("core/recent_block_hashes")

	_, err := tree.Set(key, []byte("v1"))
	require.NoError(t, err)
	_, version1, err := tree.SaveVersion()
	require.NoError(t, err)

	_, err = tree.Set(key, []byte("v2"))
	require.NoError(t, err)
	_, version2, err := tree.SaveVersion()
	require.NoError(t, err)
	require.Greater(t, version2, version1)

	got, err := tree.GetVersioned(key, version1)
	require.NoError(t, err)
	require.Equal(t, []byte("v1"), got, "GetVersioned must not return a newer fast-node value for an older version")
}

// TestEmptyMutableTreeIteratorDoesNotPanic pins the empty-tree path. The
// canonical iterator accepts a nil root via traversal's nil-node guard and
// should behave as an empty iterator, not panic.
func TestEmptyMutableTreeIteratorDoesNotPanic(t *testing.T) {
	tree := NewMutableTree(dbm.NewMemDB(), 0, false, log.NewNopLogger())

	itr, err := tree.Iterator(nil, nil, true)
	require.NoError(t, err)
	defer itr.Close()
	require.False(t, itr.Valid())
	require.NoError(t, itr.Error())
}

// TestImportedTreeIteratorReadsCanonicalTreeWhenFastNodeMissing pins
// ImmutableTree.Iterator. This is the gap that the first round of the patch
// missed: Get was canonical-fallback but Iterator still went through
// NewFastIterator, so range scans (e.g. "iterate every account in this
// module") would silently return zero results post state-sync.
//
// Verifies both that every imported key is visible AND that iteration is
// stable (sorted, no duplicates).
func TestImportedTreeIteratorReadsCanonicalTreeWhenFastNodeMissing(t *testing.T) {
	dst, keys, _ := fastNodeImportFixture(t)

	immutable, err := dst.GetImmutable(dst.Version())
	require.NoError(t, err)

	itr, err := immutable.Iterator(nil, nil, true)
	require.NoError(t, err)
	defer itr.Close()

	seen := map[string][]byte{}
	var ordered []string
	for ; itr.Valid(); itr.Next() {
		k := string(itr.Key())
		require.NotContains(t, seen, k, "iterator returned %q twice", k)
		seen[k] = append([]byte(nil), itr.Value()...)
		ordered = append(ordered, k)
	}
	require.NoError(t, itr.Error())

	require.Equal(t, len(keys), len(seen),
		"iterator must surface every key from canonical IAVL when fast-node is missing")
	for k, v := range keys {
		got, ok := seen[k]
		require.True(t, ok, "iterator missed key %q (would silently corrupt consensus)", k)
		require.Equal(t, v, got, "iterator value for %q does not match canonical", k)
	}

	sorted := append([]string(nil), ordered...)
	sort.Strings(sorted)
	require.Equal(t, sorted, ordered, "ascending iterator must yield keys in sorted order")
}

// TestImportedTreeRangeIterationReadsCanonicalTreeWhenFastNodeMissing pins
// the range callback APIs. They were already canonical before this patch; this
// test prevents a future refactor from putting range scans on FastIterator.
func TestImportedTreeRangeIterationReadsCanonicalTreeWhenFastNodeMissing(t *testing.T) {
	dst, keys, _ := fastNodeImportFixture(t)

	immutable, err := dst.GetImmutable(dst.Version())
	require.NoError(t, err)

	seen := map[string][]byte{}
	stopped := immutable.IterateRange([]byte("core/"), []byte("core0"), true, func(k, v []byte) bool {
		seen[string(k)] = append([]byte(nil), v...)
		return false
	})
	require.False(t, stopped)

	require.Len(t, seen, 2)
	for _, key := range []string{"core/recent_block_hashes", "core/pow_msg_count:4854225"} {
		got, ok := seen[key]
		require.True(t, ok, "IterateRange missed key %q", key)
		require.Equal(t, keys[key], got, "IterateRange value for %q does not match canonical", key)
	}

	inclusiveSeen := map[string][]byte{}
	stopped = immutable.IterateRangeInclusive([]byte("core/"), []byte("core/recent_block_hashes"), true, func(k, v []byte, _ int64) bool {
		inclusiveSeen[string(k)] = append([]byte(nil), v...)
		return false
	})
	require.False(t, stopped)

	require.Contains(t, inclusiveSeen, "core/recent_block_hashes")
	require.Equal(t, keys["core/recent_block_hashes"], inclusiveSeen["core/recent_block_hashes"])
}

// TestImportedTreeIterateReadsCanonicalTreeWhenFastNodeMissing pins
// ImmutableTree.Iterate (the callback API), which used to share the same
// FastIterator backend. Same correctness contract: must surface every
// canonical key.
func TestImportedTreeIterateReadsCanonicalTreeWhenFastNodeMissing(t *testing.T) {
	dst, keys, _ := fastNodeImportFixture(t)

	immutable, err := dst.GetImmutable(dst.Version())
	require.NoError(t, err)

	seen := map[string][]byte{}
	stopped, err := immutable.Iterate(func(k, v []byte) bool {
		seen[string(k)] = append([]byte(nil), v...)
		return false
	})
	require.NoError(t, err)
	require.False(t, stopped)

	require.Equal(t, len(keys), len(seen),
		"Iterate must surface every key from canonical IAVL when fast-node is missing")
	for k, v := range keys {
		got, ok := seen[k]
		require.True(t, ok, "Iterate missed key %q (would silently corrupt consensus)", k)
		require.Equal(t, v, got, "Iterate value for %q does not match canonical", k)
	}
}

// TestMutableTreeIteratorReadsCanonicalTreeWhenFastNodeMissing pins
// MutableTree.Iterator. The original patch left this delegating to
// NewUnsavedFastIterator, which is FastIterator + unsaved-state merge. Same
// bug class: range scans silently miss imported keys.
func TestMutableTreeIteratorReadsCanonicalTreeWhenFastNodeMissing(t *testing.T) {
	dst, keys, _ := fastNodeImportFixture(t)

	itr, err := dst.Iterator(nil, nil, true)
	require.NoError(t, err)
	defer itr.Close()

	seen := map[string][]byte{}
	for ; itr.Valid(); itr.Next() {
		seen[string(itr.Key())] = append([]byte(nil), itr.Value()...)
	}
	require.NoError(t, itr.Error())

	require.Equal(t, len(keys), len(seen),
		"MutableTree.Iterator must surface every key from canonical IAVL when fast-node is missing")
	for k, v := range keys {
		got, ok := seen[k]
		require.True(t, ok, "MutableTree.Iterator missed key %q", k)
		require.Equal(t, v, got)
	}
}
