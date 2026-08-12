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

func (i failFastIterator) Valid() bool {
	valid := i.delegate.Valid()
	if !valid && i.ctx.ExecMode() == sdk.ExecModeFinalize {
		_ = haltFinalizeStoreError(i.ctx, "iterator_step", i.delegate.Error())
	}
	return valid
}

func (i failFastIterator) Next()         { i.delegate.Next() }
func (i failFastIterator) Key() []byte   { return i.delegate.Key() }
func (i failFastIterator) Value() []byte { return i.delegate.Value() }

func (i failFastIterator) Error() error {
	return haltFinalizeStoreError(i.ctx, "iterator_step", i.delegate.Error())
}

func (i failFastIterator) Close() error {
	return haltFinalizeStoreError(i.ctx, "iterator_close", i.delegate.Close())
}
