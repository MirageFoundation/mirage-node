package app

import (
	"testing"

	"cosmossdk.io/log/v2"
	dbm "github.com/cosmos/cosmos-db"
	"github.com/cosmos/cosmos-sdk/baseapp"
	"github.com/stretchr/testify/require"
)

// closeOncePanicDB mimics a PebbleDB handle: the first Close() succeeds, any
// subsequent Close() panics ("pebble: closed"). A MemDB cannot reproduce the
// regression because its Close() is a safe no-op.
type closeOncePanicDB struct {
	dbm.DB
	closes int
}

func (d *closeOncePanicDB) Close() error {
	d.closes++
	if d.closes > 1 {
		panic("pebble: closed")
	}
	return d.DB.Close()
}

// TestAppCloseIsIdempotent guards the shutdown double-close regression. cosmos-sdk
// server.startInProcess calls app.Close() twice, and baseapp.Close() closes both
// application.db and snapshots/metadata.db unconditionally, so a second close
// re-closes an already-closed PebbleDB handle and panics, crashing every graceful
// shutdown. App.Close must run the underlying close exactly once. Without the
// App.Close override this test panics on the second call.
func TestAppCloseIsIdempotent(t *testing.T) {
	db := &closeOncePanicDB{DB: dbm.NewMemDB()}
	a := New(log.NewNopLogger(), db, false, MockAppOptions{}, baseapp.SetChainID("mirage-test"))

	require.NoError(t, a.Close())
	require.NotPanics(t, func() {
		require.NoError(t, a.Close())
	}, "second Close must not re-close the underlying DB")
	require.Equal(t, 1, db.closes, "underlying DB must be closed exactly once")
}
