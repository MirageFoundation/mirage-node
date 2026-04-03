package app

import (
	"encoding/binary"
	"testing"

	"cosmossdk.io/log"
	dbm "github.com/cosmos/cosmos-db"
	"github.com/stretchr/testify/require"
)

func encodeHeights(heights []uint64) []byte {
	buf := make([]byte, len(heights)*8)
	for i, h := range heights {
		binary.BigEndian.PutUint64(buf[i*8:], h)
	}
	return buf
}

func decodeHeights(bz []byte) []uint64 {
	out := make([]uint64, len(bz)/8)
	for i := range out {
		out[i] = binary.BigEndian.Uint64(bz[i*8:])
	}
	return out
}

func TestFixStalePruneSnapshotHeights_Empty(t *testing.T) {
	db := dbm.NewMemDB()
	logger := log.NewNopLogger()

	fixStalePruneSnapshotHeights(db, logger)

	bz, err := db.Get([]byte("s/prunesnapshotheights"))
	require.NoError(t, err)
	require.Nil(t, bz)
}

func TestFixStalePruneSnapshotHeights_SingleEntry(t *testing.T) {
	db := dbm.NewMemDB()
	logger := log.NewNopLogger()

	require.NoError(t, db.Set([]byte("s/prunesnapshotheights"), encodeHeights([]uint64{14400})))

	fixStalePruneSnapshotHeights(db, logger)

	bz, err := db.Get([]byte("s/prunesnapshotheights"))
	require.NoError(t, err)
	require.Equal(t, []uint64{14400}, decodeHeights(bz))
}

func TestFixStalePruneSnapshotHeights_Contiguous(t *testing.T) {
	db := dbm.NewMemDB()
	logger := log.NewNopLogger()

	heights := []uint64{14400, 28800, 43200}
	require.NoError(t, db.Set([]byte("s/prunesnapshotheights"), encodeHeights(heights)))

	fixStalePruneSnapshotHeights(db, logger)

	bz, err := db.Get([]byte("s/prunesnapshotheights"))
	require.NoError(t, err)
	require.Equal(t, heights, decodeHeights(bz))
}

func TestFixStalePruneSnapshotHeights_StaleZero(t *testing.T) {
	db := dbm.NewMemDB()
	logger := log.NewNopLogger()

	// Simulates state-sync bug: [0, 450000, 464400, 478800]
	// 0 is the stale seed, gap between 0 and 450000 breaks contiguity.
	// interval = 478800 - 464400 = 14400
	// Contiguous tail from 450000: 450000, 464400, 478800 (all 14400 apart)
	heights := []uint64{0, 450000, 464400, 478800}
	require.NoError(t, db.Set([]byte("s/prunesnapshotheights"), encodeHeights(heights)))

	fixStalePruneSnapshotHeights(db, logger)

	bz, err := db.Get([]byte("s/prunesnapshotheights"))
	require.NoError(t, err)
	fixed := decodeHeights(bz)
	require.Equal(t, []uint64{450000, 464400, 478800}, fixed)
}

func TestFixStalePruneSnapshotHeights_MultipleGaps(t *testing.T) {
	db := dbm.NewMemDB()
	logger := log.NewNopLogger()

	// [0, 100, 450000, 464400, 478800] — two non-contiguous entries before tail
	heights := []uint64{0, 100, 450000, 464400, 478800}
	require.NoError(t, db.Set([]byte("s/prunesnapshotheights"), encodeHeights(heights)))

	fixStalePruneSnapshotHeights(db, logger)

	bz, err := db.Get([]byte("s/prunesnapshotheights"))
	require.NoError(t, err)
	fixed := decodeHeights(bz)
	require.Equal(t, []uint64{450000, 464400, 478800}, fixed)
}

func TestFixStalePruneSnapshotHeights_MalformedLength(t *testing.T) {
	db := dbm.NewMemDB()
	logger := log.NewNopLogger()

	require.NoError(t, db.Set([]byte("s/prunesnapshotheights"), []byte{1, 2, 3}))

	require.Panics(t, func() {
		fixStalePruneSnapshotHeights(db, logger)
	})
}
