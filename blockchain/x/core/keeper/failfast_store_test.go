package keeper

import (
	"context"
	"errors"
	"testing"

	"cosmossdk.io/log/v2"
	sdk "github.com/cosmos/cosmos-sdk/types"
	sdkerrors "github.com/cosmos/cosmos-sdk/types/errors"
	"github.com/stretchr/testify/require"

	"mirage/consensusfatal"
)

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
