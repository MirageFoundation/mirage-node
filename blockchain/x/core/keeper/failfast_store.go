package keeper

import (
	"context"
	"errors"
	"fmt"

	corestore "cosmossdk.io/core/store"
	sdkmath "cosmossdk.io/math"
	sdk "github.com/cosmos/cosmos-sdk/types"
	sdkerrors "github.com/cosmos/cosmos-sdk/types/errors"
	banktypes "github.com/cosmos/cosmos-sdk/x/bank/types"
	slashingtypes "github.com/cosmos/cosmos-sdk/x/slashing/types"

	"mirage/consensusfatal"
)

// failFastKVStoreService keeps query/check failures observable as returned
// errors wherever the existing API has an error channel, but terminates the
// node when the same node-local I/O failure occurs while finalizing a block.
// Returning an ordinary MsgServer error during Finalize would roll back the
// transaction only on this validator while peers could commit it, producing an
// app-hash split.
type failFastKVStoreService struct {
	delegate corestore.KVStoreService
}

func (s failFastKVStoreService) OpenKVStore(ctx context.Context) corestore.KVStore {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	return failFastKVStore{
		ctx:      sdkCtx,
		delegate: s.delegate.OpenKVStore(ctx),
	}
}

type failFastKVStore struct {
	ctx      sdk.Context
	delegate corestore.KVStore
}

func haltFinalizeStoreError(ctx sdk.Context, operation string, err error) error {
	if err == nil {
		return nil
	}
	wrapped := fmt.Errorf(
		"CONSENSUS_FATAL:CORE_STORE_IO operation=%s height=%d: %w",
		operation, ctx.BlockHeight(), err,
	)
	if ctx.ExecMode() == sdk.ExecModeFinalize {
		ctx.Logger().Error("CONSENSUS_FATAL:CORE_STORE_IO",
			"operation", operation, "height", ctx.BlockHeight(), "err", err)
		// CONSENSUS_FATAL class: node-local
		consensusfatal.HaltErr(wrapped)
	}
	return wrapped
}

func haltFinalizeBankError(ctx sdk.Context, operation string, err error) error {
	if err == nil {
		return nil
	}
	if errors.Is(err, sdkerrors.ErrInsufficientFunds) ||
		errors.Is(err, sdkerrors.ErrUnauthorized) ||
		errors.Is(err, sdkerrors.ErrInvalidCoins) ||
		errors.Is(err, banktypes.ErrSendDisabled) {
		return err
	}
	wrapped := fmt.Errorf(
		"CONSENSUS_FATAL:CORE_BANK_IO operation=%s height=%d: %w",
		operation, ctx.BlockHeight(), err,
	)
	if ctx.ExecMode() == sdk.ExecModeFinalize {
		ctx.Logger().Error("CONSENSUS_FATAL:CORE_BANK_IO",
			"operation", operation, "height", ctx.BlockHeight(), "err", err)
		// CONSENSUS_FATAL class: node-local
		consensusfatal.HaltErr(wrapped)
	}
	return wrapped
}

func haltFinalizeUnexpectedBankError(ctx sdk.Context, operation string, err error) error {
	if errors.Is(err, sdkerrors.ErrInsufficientFunds) {
		wrapped := fmt.Errorf(
			"CONSENSUS_FATAL:CORE_BANK_IO operation=%s height=%d unexpected insufficient funds after spendable-balance check: %w",
			operation, ctx.BlockHeight(), err,
		)
		if ctx.ExecMode() == sdk.ExecModeFinalize {
			ctx.Logger().Error("CONSENSUS_FATAL:CORE_BANK_IO",
				"operation", operation, "height", ctx.BlockHeight(), "err", err)
			// CONSENSUS_FATAL class: node-local
			consensusfatal.HaltErr(wrapped)
		}
		return wrapped
	}
	return haltFinalizeBankError(ctx, operation, err)
}

func haltFinalizeSlashingError(ctx sdk.Context, operation string, err error) error {
	if err == nil {
		return nil
	}
	if errors.Is(err, slashingtypes.ErrNoValidatorForAddress) ||
		errors.Is(err, slashingtypes.ErrBadValidatorAddr) ||
		errors.Is(err, slashingtypes.ErrValidatorJailed) ||
		errors.Is(err, slashingtypes.ErrValidatorNotJailed) ||
		errors.Is(err, slashingtypes.ErrMissingSelfDelegation) ||
		errors.Is(err, slashingtypes.ErrSelfDelegationTooLowToUnjail) ||
		errors.Is(err, slashingtypes.ErrNoSigningInfoFound) ||
		errors.Is(err, slashingtypes.ErrValidatorTombstoned) {
		return err
	}
	return haltFinalizeStoreError(ctx, operation, err)
}

func haltFinalizeInvariantError(ctx sdk.Context, invariant string, err error) error {
	if err == nil {
		return nil
	}
	if ctx.ExecMode() == sdk.ExecModeFinalize {
		ctx.Logger().Error("CONSENSUS_FATAL:CORE_INVARIANT",
			"invariant", invariant, "height", ctx.BlockHeight(), "err", err)
		// CONSENSUS_FATAL class: deterministic
		consensusfatal.HaltErr(err)
	}
	return err
}

// haltFinalizeFatal is for the keeper readers that have no error channel —
// GetParams, GetRelayCredit, the PoW counters, the four difficulty getters and
// HasEnvelopeNonce all return a bare value, so a fault has nowhere to go.
//
// During finalization it halts: continuing would commit state derived from a
// value this node could not read while its peers could, which is divergence.
//
// Everywhere else it panics instead of exiting. Six of these sit on the ante
// path, which runs in check, recheck and simulate modes, and the backend
// simulates every user action — so a transient store fault while answering a
// public query used to call os.Exit(1) on a validator, on a path where nothing
// is committed and no divergence is possible. baseapp recovers the panic into an
// error response for that one caller and the node stays up, which is the whole
// point. Never substitute a default here: that is the silent divergence the
// fail-closed contract exists to prevent.
func haltFinalizeFatal(ctx sdk.Context, err error) {
	if err == nil {
		return
	}
	if ctx.ExecMode() == sdk.ExecModeFinalize {
		ctx.Logger().Error("CONSENSUS_FATAL", "height", ctx.BlockHeight(), "err", err)
		// CONSENSUS_FATAL class: node-local|deterministic
		consensusfatal.HaltErr(err)
	}
	ctx.Logger().Error("core keeper read failed outside finalization; rejecting this request only",
		"height", ctx.BlockHeight(), "exec_mode", ctx.ExecMode(), "err", err)
	panic(err)
}

func haltFinalizeBankPanic(ctx sdk.Context, operation string) {
	recovered := recover()
	if recovered == nil {
		return
	}
	err := fmt.Errorf(
		"CONSENSUS_FATAL:CORE_BANK_PANIC operation=%s height=%d: %v",
		operation, ctx.BlockHeight(), recovered,
	)
	if ctx.ExecMode() == sdk.ExecModeFinalize {
		ctx.Logger().Error("CONSENSUS_FATAL:CORE_BANK_PANIC",
			"operation", operation, "height", ctx.BlockHeight(), "panic", recovered)
		// CONSENSUS_FATAL class: node-local|deterministic
		consensusfatal.HaltErr(err)
	}
	panic(recovered)
}

func (k Keeper) bankBalance(ctx sdk.Context, address sdk.AccAddress, denom string) (coin sdk.Coin) {
	defer haltFinalizeBankPanic(ctx, "get_balance")
	return sdk.NewCoin(denom, k.bank.GetAllBalances(ctx, address).AmountOf(denom))
}

func (k Keeper) bankSupply(ctx sdk.Context, denom string) (coin sdk.Coin) {
	defer haltFinalizeBankPanic(ctx, "get_supply")
	coin = sdk.NewCoin(denom, sdkmath.ZeroInt())
	k.bank.IterateTotalSupply(ctx, func(current sdk.Coin) bool {
		if current.Denom == denom {
			coin = current
			return true
		}
		return false
	})
	return coin
}

func (k Keeper) bankSpendableCoins(ctx sdk.Context, address sdk.AccAddress) (coins sdk.Coins) {
	defer haltFinalizeBankPanic(ctx, "spendable_coins")
	return k.bank.SpendableCoins(ctx, address)
}

func (k Keeper) iterateAllBankBalances(ctx sdk.Context, cb func(sdk.AccAddress, sdk.Coin) bool) {
	defer haltFinalizeBankPanic(ctx, "iterate_all_balances")
	k.bank.IterateAllBalances(ctx, cb)
}

func (s failFastKVStore) Get(key []byte) ([]byte, error) {
	value, err := s.delegate.Get(key)
	return value, haltFinalizeStoreError(s.ctx, fmt.Sprintf("get key=%x", key), err)
}

func (s failFastKVStore) Has(key []byte) (bool, error) {
	found, err := s.delegate.Has(key)
	return found, haltFinalizeStoreError(s.ctx, fmt.Sprintf("has key=%x", key), err)
}

func (s failFastKVStore) Set(key, value []byte) error {
	return haltFinalizeStoreError(s.ctx, fmt.Sprintf("set key=%x", key), s.delegate.Set(key, value))
}

func (s failFastKVStore) Delete(key []byte) error {
	return haltFinalizeStoreError(s.ctx, fmt.Sprintf("delete key=%x", key), s.delegate.Delete(key))
}

func (s failFastKVStore) Iterator(start, end []byte) (corestore.Iterator, error) {
	iterator, err := s.delegate.Iterator(start, end)
	if err != nil {
		return nil, haltFinalizeStoreError(s.ctx,
			fmt.Sprintf("iterator start=%x end=%x", start, end), err)
	}
	return failFastIterator{ctx: s.ctx, delegate: iterator}, nil
}

func (s failFastKVStore) ReverseIterator(start, end []byte) (corestore.Iterator, error) {
	iterator, err := s.delegate.ReverseIterator(start, end)
	if err != nil {
		return nil, haltFinalizeStoreError(s.ctx,
			fmt.Sprintf("reverse_iterator start=%x end=%x", start, end), err)
	}
	return failFastIterator{ctx: s.ctx, delegate: iterator}, nil
}

type failFastIterator struct {
	ctx      sdk.Context
	delegate corestore.Iterator
}

func (i failFastIterator) Domain() ([]byte, []byte) { return i.delegate.Domain() }

func (i failFastIterator) Valid() bool   { return i.delegate.Valid() }
func (i failFastIterator) Next()         { i.delegate.Next() }
func (i failFastIterator) Key() []byte   { return i.delegate.Key() }
func (i failFastIterator) Value() []byte { return i.delegate.Value() }

// iteratorExhausted reports whether err only means "iteration finished".
// The cache layer every keeper iteration runs over reports exhaustion through
// Error rather than leaving it nil: memIterator and cacheMergeIterator both
// return these sentinels whenever Valid is false. Halting on them would kill
// the node at the end of a healthy loop, so only a lower-layer error is fatal.
// TestIteratorExhaustionIsNotAFault pins the wording against the linked store.
func iteratorExhausted(err error) bool {
	switch err.Error() {
	case "invalid memIterator", "invalid cacheMergeIterator":
		return true
	default:
		return false
	}
}

func (i failFastIterator) Error() error {
	err := i.delegate.Error()
	if err == nil || iteratorExhausted(err) {
		return nil
	}
	return haltFinalizeStoreError(i.ctx, "iterator_step", err)
}

func (i failFastIterator) Close() error {
	return haltFinalizeStoreError(i.ctx, "iterator_close", i.delegate.Close())
}
