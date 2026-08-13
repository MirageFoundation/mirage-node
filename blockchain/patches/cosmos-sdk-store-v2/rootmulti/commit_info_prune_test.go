package rootmulti

// Mirage patch tests (NOT upstream). They pin the behavior of pruneCommitInfo,
// added to PruneStores so the rootmulti commit-info store (s/<version>) does not
// grow without bound, and the pruning-failure escalation that replaced upstream's
// log-and-swallow (security finding L-11). See store.go and
// docs/troubleshooting/divergence-recovery.md (action item 12).

import (
	"bytes"
	"errors"
	"fmt"
	"testing"

	dbm "github.com/cosmos/cosmos-db"
	"github.com/stretchr/testify/require"

	"cosmossdk.io/log/v2"

	pruningtypes "github.com/cosmos/cosmos-sdk/store/v2/pruning/types"
)

// countCommitInfoKeys counts only the numeric commit-info records (s/<digits>),
// using the same tight half-open range the pruner uses so that s/latest,
// s/earliest, and the IAVL substore data (s/_/..., s/k:.../...) are excluded.
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
	decoys := []string{latestVersionKey, earliestVersionKey, "s/k:bank/value", "s/_/value"}
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

var errInjectedWriteFailure = errors.New("injected batch write failure")

// failWriteDB fails every batch write while armed, reproducing the disk-level
// shape (full/read-only/wedged volume) that makes IAVL version deletion, the
// s/earliest bump, and commit-info deletion all fail mid-pass.
type failWriteDB struct {
	dbm.DB
	armed bool
}

func (d *failWriteDB) NewBatch() dbm.Batch {
	return &failWriteBatch{Batch: d.DB.NewBatch(), owner: d}
}

func (d *failWriteDB) NewBatchWithSize(size int) dbm.Batch {
	return &failWriteBatch{Batch: d.DB.NewBatchWithSize(size), owner: d}
}

type failWriteBatch struct {
	dbm.Batch
	owner *failWriteDB
}

func (b *failWriteBatch) Write() error {
	if b.owner.armed {
		return errInjectedWriteFailure
	}
	return b.Batch.Write()
}

func (b *failWriteBatch) WriteSync() error {
	if b.owner.armed {
		return errInjectedWriteFailure
	}
	return b.Batch.WriteSync()
}

// Upstream logged each per-store prune failure (and the s/earliest write
// failure) and then returned nil, so a node that had stopped reclaiming disk
// reported success to every caller. A failure must now reach the caller and
// carry the greppable marker plus a counter, while still pruning the remaining
// stores — pruning is local housekeeping, so degrading loudly beats halting.
func TestPruneStoresSurfacesInjectedFailure(t *testing.T) {
	db := &failWriteDB{DB: dbm.NewMemDB()}
	var logs bytes.Buffer

	ms := newMultiStoreWithMounts(db, pruningtypes.NewPruningOptions(pruningtypes.PruningNothing))
	ms.logger = log.NewLogger(&logs)
	// Synchronous pruning keeps DeleteVersionsTo's failure on this goroutine.
	ms.SetIAVLSyncPruning(true)
	require.NoError(t, ms.LoadLatestVersion())

	for i := 0; i < 10; i++ {
		ms.Commit()
	}

	db.armed = true
	err := ms.PruneStores(5)

	require.Error(t, err, "an injected prune failure must reach the caller, not be swallowed")
	require.ErrorIs(t, err, errInjectedWriteFailure)
	require.ErrorContains(t, err, "prune store store1")
	require.ErrorContains(t, err, "persist earliest version 6")
	require.GreaterOrEqual(t, ms.PruneFailures(), uint64(2))
	require.Contains(t, logs.String(), pruneDegradedMarker)

	// Every mounted IAVL store is still attempted: one wedged store must not
	// short-circuit the pass.
	for _, name := range []string{"store1", "store2", "store3"} {
		require.ErrorContains(t, err, "prune store "+name)
	}

	// A failed pass degrades, never poisons: the next healthy pass succeeds.
	db.armed = false
	require.NoError(t, ms.PruneStores(5))
}
