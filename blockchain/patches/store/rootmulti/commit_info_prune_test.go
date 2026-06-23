package rootmulti

// Mirage patch tests (NOT upstream). They pin the behavior of pruneCommitInfo,
// added to PruneStores so the rootmulti commit-info store (s/<version>) does not
// grow without bound. See store.go and docs/troubleshooting/divergence-recovery.md
// (action item 12).

import (
	"fmt"
	"testing"

	dbm "github.com/cosmos/cosmos-db"
	"github.com/stretchr/testify/require"

	pruningtypes "cosmossdk.io/store/pruning/types"
)

// countCommitInfoKeys counts only the numeric commit-info records (s/<digits>),
// using the same tight half-open range the pruner uses so that s/latest and the
// IAVL substore data (s/_/..., s/k:.../...) are excluded.
func countCommitInfoKeys(t *testing.T, db dbm.DB) int {
	t.Helper()
	iter, err := db.Iterator([]byte("s/0"), []byte("s/:"))
	require.NoError(t, err)
	defer iter.Close()
	n := 0
	for ; iter.Valid(); iter.Next() {
		n++
	}
	require.NoError(t, iter.Error())
	return n
}

func TestPruneCommitInfoDeletesStaleRecords(t *testing.T) {
	db := dbm.NewMemDB()
	ms := newMultiStoreWithMounts(db, pruningtypes.NewPruningOptions(pruningtypes.PruningNothing))
	require.NoError(t, ms.LoadLatestVersion())

	const n = 50
	for i := 0; i < n; i++ {
		ms.Commit()
	}
	// PruningNothing means upstream never deletes commit-info: all are present.
	require.Equal(t, n, countCommitInfoKeys(t, db))

	require.NoError(t, ms.pruneCommitInfo(40))

	// Versions strictly below 40 are gone; 40..50 are retained.
	require.Equal(t, 11, countCommitInfoKeys(t, db))

	for _, v := range []int64{1, 39} {
		has, err := db.Has([]byte(fmt.Sprintf("s/%d", v)))
		require.NoError(t, err)
		require.False(t, has, "stale commit-info s/%d should be pruned", v)
	}
	for _, v := range []int64{40, 50} {
		has, err := db.Has([]byte(fmt.Sprintf("s/%d", v)))
		require.NoError(t, err)
		require.True(t, has, "commit-info s/%d (>= prune height) should be retained", v)
	}

	has, err := db.Has([]byte(latestVersionKey))
	require.NoError(t, err)
	require.True(t, has, "s/latest must never be pruned")
}

func TestPruneCommitInfoRespectsBatchCapAndIgnoresOtherKeys(t *testing.T) {
	db := dbm.NewMemDB()
	ms := newMultiStoreWithMounts(db, pruningtypes.NewPruningOptions(pruningtypes.PruningNothing))

	const total = commitInfoPruneBatch + 5000
	for v := 1; v <= total; v++ {
		require.NoError(t, db.Set([]byte(fmt.Sprintf("s/%d", v)), []byte{1}))
	}
	// Keys that share the "s/" prefix but are NOT numeric commit-info records.
	// They sort after the digit range and must never be touched.
	decoys := []string{latestVersionKey, "s/k:bank/value", "s/_/value"}
	for _, k := range decoys {
		require.NoError(t, db.Set([]byte(k), []byte{9}))
	}

	require.Equal(t, total, countCommitInfoKeys(t, db))

	// First pass is bounded by the batch cap.
	require.NoError(t, ms.pruneCommitInfo(int64(total)+1))
	require.Equal(t, total-commitInfoPruneBatch, countCommitInfoKeys(t, db),
		"a single pass must delete at most commitInfoPruneBatch records")

	// Subsequent pass drains the remaining backlog.
	require.NoError(t, ms.pruneCommitInfo(int64(total)+1))
	require.Equal(t, 0, countCommitInfoKeys(t, db))

	for _, k := range decoys {
		has, err := db.Has([]byte(k))
		require.NoError(t, err)
		require.True(t, has, "non-commit-info key %q must not be pruned", k)
	}
}
