package keeper

import (
	"context"
	"testing"

	"cosmossdk.io/log/v2"
	cmtproto "github.com/cometbft/cometbft/proto/tendermint/types"
	dbm "github.com/cosmos/cosmos-db"
	"github.com/cosmos/cosmos-sdk/runtime"
	"github.com/cosmos/cosmos-sdk/store/v2/rootmulti"
	storetypes "github.com/cosmos/cosmos-sdk/store/v2/types"
	sdk "github.com/cosmos/cosmos-sdk/types"
	slashingkeeper "github.com/cosmos/cosmos-sdk/x/slashing/keeper"
	"github.com/stretchr/testify/require"
)

// nonceRoundTripFixture builds a real IAVL-backed multistore over db, so the
// test exercises the same commit and reload path a node does rather than a map.
func nonceRoundTripFixture(t *testing.T, db dbm.DB) (Keeper, sdk.Context, *rootmulti.Store) {
	t.Helper()
	key := storetypes.NewKVStoreKey("core")
	ms := rootmulti.NewStore(db, log.NewNopLogger())
	ms.MountStoreWithDB(key, storetypes.StoreTypeIAVL, nil)
	require.NoError(t, ms.LoadLatestVersion())

	ctx := sdk.NewContext(ms, cmtproto.Header{}, false, log.NewNopLogger()).
		WithContext(context.Background()).
		WithExecMode(sdk.ExecModeFinalize)

	k := NewKeeper(runtime.NewKVStoreService(key), nil, nil, nil, nil, slashingkeeper.Keeper{})
	return k, ctx, ms
}

// TestEnvelopeNoncePersistsAcrossCommitAndRestart is the "not determined from
// source" item #5 from the 2026-08-14 review.
//
// Envelope replay protection is the reason a captured relay message cannot be
// resubmitted, and its entire on-disk representation is a key with an EMPTY
// value. HasEnvelopeNonce asks the store `Has(key)`, and cachekv answers Has
// through Get — so if any layer between the keeper and IAVL ever normalised a
// committed empty value to nil, every recorded nonce would silently read as
// absent and replay protection would be gone with nothing failing loudly.
//
// The review could not settle that from source. This settles it by writing a
// nonce, committing, discarding the store, reopening the same database and
// asserting the nonce is still there.
func TestEnvelopeNoncePersistsAcrossCommitAndRestart(t *testing.T) {
	db := dbm.NewMemDB()
	pubkeyHash := []byte{0xab, 0xcd, 0xef, 0x01}
	const nonce = uint64(1723766400123456789)

	k, ctx, ms := nonceRoundTripFixture(t, db)
	require.False(t, k.HasEnvelopeNonce(ctx, pubkeyHash, nonce), "fresh store must not know the nonce")
	require.NoError(t, k.SetEnvelopeNonce(ctx, pubkeyHash, nonce, 1_800_000_000))
	require.True(t, k.HasEnvelopeNonce(ctx, pubkeyHash, nonce), "the nonce must be visible before commit")
	ms.Commit()

	// Reopen from the same database, as a restarted node does.
	restarted, restartedCtx, _ := nonceRoundTripFixture(t, db)
	require.True(t, restarted.HasEnvelopeNonce(restartedCtx, pubkeyHash, nonce),
		"a committed envelope nonce must survive a restart; if this fails, every relay message is replayable")

	// A nonce that was never written must still read as absent, so the assertion
	// above cannot be satisfied by a Has that returns true for everything.
	require.False(t, restarted.HasEnvelopeNonce(restartedCtx, pubkeyHash, nonce+1))
	require.False(t, restarted.HasEnvelopeNonce(restartedCtx, []byte{0x99}, nonce))
}

// TestEnvelopeNoncePersistsThroughCacheContext covers the path a real
// transaction takes: the ante writes into the cache-wrapped context baseapp
// creates per transaction, and the write only reaches the parent when that cache
// is flushed. An empty value has to survive the extra cachekv hop too.
func TestEnvelopeNoncePersistsThroughCacheContext(t *testing.T) {
	db := dbm.NewMemDB()
	pubkeyHash := []byte{0x11, 0x22}
	const nonce = uint64(42)

	k, ctx, ms := nonceRoundTripFixture(t, db)

	cacheCtx, write := ctx.CacheContext()
	require.NoError(t, k.SetEnvelopeNonce(cacheCtx, pubkeyHash, nonce, 1_800_000_000))
	require.False(t, k.HasEnvelopeNonce(ctx, pubkeyHash, nonce),
		"an uncommitted cache write must not be visible to the parent")
	write()

	require.True(t, k.HasEnvelopeNonce(ctx, pubkeyHash, nonce),
		"flushing the tx cache must publish the nonce")
	ms.Commit()

	restarted, restartedCtx, _ := nonceRoundTripFixture(t, db)
	require.True(t, restarted.HasEnvelopeNonce(restartedCtx, pubkeyHash, nonce))
}

// TestEnvelopeNonceRejectsNonPositiveExpiry pins the guard that keeps a nonce
// out of the expiry index, where it would never be pruned.
func TestEnvelopeNonceRejectsNonPositiveExpiry(t *testing.T) {
	k, ctx, _ := nonceRoundTripFixture(t, dbm.NewMemDB())
	require.Error(t, k.SetEnvelopeNonce(ctx, []byte{0x01}, 1, 0))
	require.Error(t, k.SetEnvelopeNonce(ctx, []byte{0x01}, 1, -1))
	require.False(t, k.HasEnvelopeNonce(ctx, []byte{0x01}, 1))
}
