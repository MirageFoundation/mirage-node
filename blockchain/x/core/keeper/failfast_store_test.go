package keeper

import (
	"context"
	"errors"
	"testing"

	"cosmossdk.io/log/v2"
	dbm "github.com/cosmos/cosmos-db"
	"github.com/cosmos/cosmos-sdk/store/v2/cachekv"
	"github.com/cosmos/cosmos-sdk/store/v2/dbadapter"
	sdk "github.com/cosmos/cosmos-sdk/types"
	sdkerrors "github.com/cosmos/cosmos-sdk/types/errors"
	"github.com/stretchr/testify/require"

	"mirage/consensusfatal"
)

// TestIteratorExhaustionIsNotAFault runs the real cache-wrapped store every
// keeper iteration actually uses. Walking it to the end reports an error that
// means "finished", not "the disk failed"; halting on that killed the node one
// block after the v1.34.0 upgrade. This fails if the linked store changes the
// wording iteratorExhausted matches, which is the point of using the real type.
func TestIteratorExhaustionIsNotAFault(t *testing.T) {
	restore := consensusfatal.SetHaltForTest(func(err error) { panic(err) })
	defer restore()

	ctx := sdk.Context{}.
		WithContext(context.Background()).
		WithLogger(log.NewNopLogger()).
		WithExecMode(sdk.ExecModeFinalize)

	parent := dbadapter.Store{DB: dbm.NewMemDB()}
	parent.Set([]byte("a"), []byte("1"))
	cache := cachekv.NewStore(parent)
	cache.Set([]byte("b"), []byte("2"))

	it := failFastIterator{ctx: ctx, delegate: cache.Iterator(nil, nil)}
	seen := 0
	for it.Valid() {
		seen++
		it.Next()
	}

	require.Equal(t, 2, seen)
	require.Error(t, it.delegate.Error(), "the store still reports exhaustion as an error")
	require.NoError(t, it.Error(), "exhaustion must not surface as a store fault")
	require.NoError(t, it.Close())
}

// TestIteratorRealErrorStillHalts proves filtering the exhaustion sentinel did
// not disable detection of a genuine lower-layer read failure.
func TestIteratorRealErrorStillHalts(t *testing.T) {
	restore := consensusfatal.SetHaltForTest(func(err error) { panic(err) })
	defer restore()

	ctx := sdk.Context{}.
		WithContext(context.Background()).
		WithLogger(log.NewNopLogger()).
		WithExecMode(sdk.ExecModeFinalize)

	it := failFastIterator{ctx: ctx, delegate: failingIterator{err: errors.New("disk read")}}
	require.PanicsWithError(t,
		"CONSENSUS_FATAL:CORE_STORE_IO operation=iterator_step height=0: disk read",
		func() { _ = it.Error() },
	)
}

type failingIterator struct {
	err error
}

func (f failingIterator) Domain() ([]byte, []byte) { return nil, nil }
func (f failingIterator) Valid() bool              { return false }
func (f failingIterator) Next()                    {}
func (f failingIterator) Key() []byte              { return nil }
func (f failingIterator) Value() []byte            { return nil }
func (f failingIterator) Error() error             { return f.err }
func (f failingIterator) Close() error             { return nil }

func TestHaltFinalizeStoreError(t *testing.T) {
	restore := consensusfatal.SetHaltForTest(func(err error) { panic(err) })
	defer restore()

	base := sdk.Context{}.
		WithContext(context.Background()).
		WithLogger(log.NewNopLogger())

	require.Error(t, haltFinalizeStoreError(base.WithExecMode(sdk.ExecModeCheck), "get", errors.New("disk read")))
	require.PanicsWithError(t,
		"CONSENSUS_FATAL:CORE_STORE_IO operation=get height=0: disk read",
		func() {
			_ = haltFinalizeStoreError(
				base.WithExecMode(sdk.ExecModeFinalize),
				"get",
				errors.New("disk read"),
			)
		},
	)
}

func TestHaltFinalizeBankError(t *testing.T) {
	restore := consensusfatal.SetHaltForTest(func(err error) { panic(err) })
	defer restore()

	ctx := sdk.Context{}.
		WithContext(context.Background()).
		WithLogger(log.NewNopLogger()).
		WithExecMode(sdk.ExecModeFinalize)

	require.ErrorIs(t,
		haltFinalizeBankError(ctx, "send", sdkerrors.ErrInsufficientFunds),
		sdkerrors.ErrInsufficientFunds,
	)
	require.PanicsWithError(t,
		"CONSENSUS_FATAL:CORE_BANK_IO operation=send height=0: disk write",
		func() {
			_ = haltFinalizeBankError(ctx, "send", errors.New("disk write"))
		},
	)
}

func TestHaltFinalizeBankPanic(t *testing.T) {
	restore := consensusfatal.SetHaltForTest(func(err error) { panic(err) })
	defer restore()

	ctx := sdk.Context{}.
		WithContext(context.Background()).
		WithLogger(log.NewNopLogger()).
		WithExecMode(sdk.ExecModeFinalize)

	require.PanicsWithError(t,
		"CONSENSUS_FATAL:CORE_BANK_PANIC operation=get_balance height=0: disk panic",
		func() {
			defer haltFinalizeBankPanic(ctx, "get_balance")
			panic("disk panic")
		},
	)
}
