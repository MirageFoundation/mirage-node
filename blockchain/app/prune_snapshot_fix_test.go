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

func TestFixStalePruneSnapshotHeights_TrimsToLast(t *testing.T) {
	db := dbm.NewMemDB()
	logger := log.NewNopLogger()

	heights := []uint64{14400, 28800, 43200}
	require.NoError(t, db.Set([]byte("s/prunesnapshotheights"), encodeHeights(heights)))

	fixStalePruneSnapshotHeights(db, logger)

	bz, err := db.Get([]byte("s/prunesnapshotheights"))
	require.NoError(t, err)
	require.Equal(t, []uint64{43200}, decodeHeights(bz))
}

func TestFixStalePruneSnapshotHeights_StaleZero(t *testing.T) {
	db := dbm.NewMemDB()
	logger := log.NewNopLogger()

	heights := []uint64{0, 450000, 464400, 478800}
	require.NoError(t, db.Set([]byte("s/prunesnapshotheights"), encodeHeights(heights)))

	fixStalePruneSnapshotHeights(db, logger)

	bz, err := db.Get([]byte("s/prunesnapshotheights"))
	require.NoError(t, err)
	require.Equal(t, []uint64{478800}, decodeHeights(bz))
}

func TestFixStalePruneSnapshotHeights_ManyContiguous(t *testing.T) {
	db := dbm.NewMemDB()
	logger := log.NewNopLogger()

	heights := []uint64{3513600, 3528000, 3542400, 3556800, 3571200, 3585600, 3600000}
	require.NoError(t, db.Set([]byte("s/prunesnapshotheights"), encodeHeights(heights)))

	fixStalePruneSnapshotHeights(db, logger)

	bz, err := db.Get([]byte("s/prunesnapshotheights"))
	require.NoError(t, err)
	require.Equal(t, []uint64{3600000}, decodeHeights(bz))
}

func TestFixStalePruneSnapshotHeights_MalformedLength(t *testing.T) {
	db := dbm.NewMemDB()
	logger := log.NewNopLogger()

	require.NoError(t, db.Set([]byte("s/prunesnapshotheights"), []byte{1, 2, 3}))

	require.Panics(t, func() {
		fixStalePruneSnapshotHeights(db, logger)
	})
}
