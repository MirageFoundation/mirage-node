package keeper

import (
	"context"
	"errors"
	"testing"

	"cosmossdk.io/log/v2"
	dbm "github.com/cosmos/cosmos-db"
	"github.com/cosmos/cosmos-sdk/store/v2/cachekv"
	"github.com/cosmos/cosmos-sdk/store/v2/dbadapter"
	storetypes "github.com/cosmos/cosmos-sdk/store/v2/types"
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

// midLoopFailingStore is a real store whose iterator yields healthyKeys entries
// and then reports a read fault, the way a node-local disk error actually
// arrives: partway through a traversal, not at construction.
type midLoopFailingStore struct {
	dbadapter.Store
	healthyKeys int
	err         error
}

func (s midLoopFailingStore) Iterator(start, end []byte) storetypes.Iterator {
	return &midLoopFailingIterator{
		Iterator:    s.Store.Iterator(start, end),
		remaining:   s.healthyKeys,
		injectedErr: s.err,
	}
}

type midLoopFailingIterator struct {
	storetypes.Iterator
	remaining   int
	injectedErr error
	failed      bool
}

func (i *midLoopFailingIterator) Next() {
	if i.remaining > 0 {
		i.remaining--
		i.Iterator.Next()
		return
	}
	i.failed = true
}

func (i *midLoopFailingIterator) Valid() bool {
	if i.failed {
		return false
	}
	return i.Iterator.Valid()
}

func (i *midLoopFailingIterator) Error() error {
	if i.failed {
		return i.injectedErr
	}
	return i.Iterator.Error()
}

// TestIteratorFaultMidLoopHalts is the H-1 regression test.
//
// The bug: a fault arising *during* traversal was discarded at three layers, so
// the post-loop `if err := it.Error()` checks throughout keeper.go were
// structurally incapable of observing one. They could only ever see the
// exhaustion sentinel, which iteratorExhausted correctly maps to nil — meaning a
// truncated iteration committed as a complete one. That is AppHash divergence:
// the wrong deque entry evicted, list entries surviving a deleted count key,
// missed subscription expiries, missed nonce prunes, an incomplete relay-credit
// reset.
//
// This drives the fault through the real cachekv stack rather than a
// hand-written iterator, because cacheMergeIterator sits between the keeper and
// IAVL on every single keeper store access and was dispositive on its own.
func TestIteratorFaultMidLoopHalts(t *testing.T) {
	restore := consensusfatal.SetHaltForTest(func(err error) { panic(err) })
	defer restore()

	ctx := sdk.Context{}.
		WithContext(context.Background()).
		WithLogger(log.NewNopLogger()).
		WithExecMode(sdk.ExecModeFinalize)

	base := dbadapter.Store{DB: dbm.NewMemDB()}
	for _, k := range []string{"a", "b", "c", "d", "e"} {
		base.Set([]byte(k), []byte("v"))
	}
	parent := midLoopFailingStore{Store: base, healthyKeys: 2, err: errors.New("disk read")}
	cache := cachekv.NewStore(parent)

	it := failFastIterator{ctx: ctx, delegate: cache.Iterator(nil, nil)}
	seen := 0
	for it.Valid() {
		seen++
		it.Next()
	}

	// The loop ends early — that is the whole danger, and it is exactly what a
	// caller cannot see for itself.
	require.Less(t, seen, 5, "the injected fault should truncate the walk")

	// The fault must survive both the merge iterator and the exhaustion filter.
	require.PanicsWithError(t,
		"CONSENSUS_FATAL:CORE_STORE_IO operation=iterator_step height=0: disk read",
		func() { _ = it.Error() },
	)
}

// TestIteratorFaultMidLoopReturnsOutsideFinalize pins the other half of the
// failure policy: outside block finalization nothing is committed and no
// divergence is possible, so the same fault is returned rather than halting the
// validator.
func TestIteratorFaultMidLoopReturnsOutsideFinalize(t *testing.T) {
	restore := consensusfatal.SetHaltForTest(func(err error) { panic(err) })
	defer restore()

	ctx := sdk.Context{}.
		WithContext(context.Background()).
		WithLogger(log.NewNopLogger()).
		WithExecMode(sdk.ExecModeCheck)

	base := dbadapter.Store{DB: dbm.NewMemDB()}
	base.Set([]byte("a"), []byte("v"))
	base.Set([]byte("b"), []byte("v"))
	parent := midLoopFailingStore{Store: base, healthyKeys: 1, err: errors.New("disk read")}
	cache := cachekv.NewStore(parent)

	it := failFastIterator{ctx: ctx, delegate: cache.Iterator(nil, nil)}
	for it.Valid() {
		it.Next()
	}
	require.Error(t, it.Error(), "the fault is still reported outside finalize")
}

// TestHaltFinalizeFatalIsConfinedToFinalization is the L-1 regression test.
//
// The keeper readers with no error channel — GetParams, GetRelayCredit,
// RecordPoWMessage, the PoW counters, all four difficulty getters and
// HasEnvelopeNonce — used to call consensusfatal.HaltErr, which is os.Exit(1),
// with no exec-mode test at all. Six of them are on the ante path, which runs in
// check, recheck and simulate modes, and the backend simulates every user
// action — so a transient store fault while answering a public request killed a
// validator on a path where nothing is committed and no divergence is possible.
//
// Halting must still happen during finalization, where continuing would commit
// divergent state.
func TestHaltFinalizeFatalIsConfinedToFinalization(t *testing.T) {
	restore := consensusfatal.SetHaltForTest(func(err error) { panic(err) })
	defer restore()

	base := sdk.Context{}.
		WithContext(context.Background()).
		WithLogger(log.NewNopLogger())

	fault := errors.New("CONSENSUS_FATAL:PARAMS_STORE_GET height=0: disk read")

	var halted bool
	restoreCount := consensusfatal.SetHaltForTest(func(err error) { halted = true; panic(err) })
	defer restoreCount()

	require.Panics(t, func() { haltFinalizeFatal(base.WithExecMode(sdk.ExecModeFinalize), fault) })
	require.True(t, halted, "a fault during finalization must halt: continuing commits divergent state")

	for _, mode := range []sdk.ExecMode{
		sdk.ExecModeCheck,
		sdk.ExecModeReCheck,
		sdk.ExecModeSimulate,
		sdk.ExecModeProcessProposal,
	} {
		halted = false
		require.Panics(t, func() { haltFinalizeFatal(base.WithExecMode(mode), fault) },
			"the caller must still be rejected in mode %v", mode)
		require.False(t, halted,
			"mode %v commits nothing, so the validator must survive the fault", mode)
	}

	halted = false
	require.NotPanics(t, func() { haltFinalizeFatal(base.WithExecMode(sdk.ExecModeFinalize), nil) })
	require.False(t, halted, "a nil error is not a fault")
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
