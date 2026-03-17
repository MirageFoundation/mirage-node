package app

import (
	"testing"

	sdk "github.com/cosmos/cosmos-sdk/types"
	authtypes "github.com/cosmos/cosmos-sdk/x/auth/types"
	banktypes "github.com/cosmos/cosmos-sdk/x/bank/types"
	govtypes "github.com/cosmos/cosmos-sdk/x/gov/types"
	"github.com/stretchr/testify/require"

	coretypes "mirage/x/core/types"
)

func TestGovAuthorityDecorator_RejectsGovAuthority(t *testing.T) {
	govAddr := authtypes.NewModuleAddress(govtypes.ModuleName).String()
	dec := GovAuthorityDecorator{}
	passthrough := func(ctx sdk.Context, tx sdk.Tx, simulate bool) (sdk.Context, error) {
		return ctx, nil
	}

	tests := []struct {
		name string
		msgs []sdk.Msg
	}{
		{
			"MsgPost with gov authority",
			[]sdk.Msg{&coretypes.MsgPost{Authority: govAddr}},
		},
		{
			"MsgSetLevel with gov authority",
			[]sdk.Msg{&coretypes.MsgSetLevel{Authority: govAddr}},
		},
		{
			"MsgMintTokens with gov authority",
			[]sdk.Msg{&coretypes.MsgMintTokens{Authority: govAddr}},
		},
		{
			"MsgBurnTokens with gov authority",
			[]sdk.Msg{&coretypes.MsgBurnTokens{Authority: govAddr}},
		},
		{
			"MsgVote with gov authority",
			[]sdk.Msg{&coretypes.MsgVote{Authority: govAddr}},
		},
		{
			"MsgDelete with gov authority",
			[]sdk.Msg{&coretypes.MsgDelete{Authority: govAddr}},
		},
		{
			"mixed: normal + gov authority",
			[]sdk.Msg{
				&coretypes.MsgPost{Authority: "mirage1abc"},
				&coretypes.MsgSetLevel{Authority: govAddr},
			},
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			tx := mockTx{msgs: tc.msgs}
			_, err := dec.AnteHandle(sdk.Context{}, tx, false, passthrough)
			require.Error(t, err)
			require.Contains(t, err.Error(), "governance authority cannot be used in direct transactions")
		})
	}
}

func TestGovAuthorityDecorator_AllowsNonGovAuthority(t *testing.T) {
	dec := GovAuthorityDecorator{}
	called := false
	passthrough := func(ctx sdk.Context, tx sdk.Tx, simulate bool) (sdk.Context, error) {
		called = true
		return ctx, nil
	}

	tests := []struct {
		name string
		msgs []sdk.Msg
	}{
		{
			"MsgPost with validator authority",
			[]sdk.Msg{&coretypes.MsgPost{Authority: "mirage1validator"}},
		},
		{
			"MsgSetLevel with validator authority",
			[]sdk.Msg{&coretypes.MsgSetLevel{Authority: "mirage1validator"}},
		},
		{
			"bank MsgSend (no gov authority)",
			[]sdk.Msg{&banktypes.MsgSend{FromAddress: "mirage1abc"}},
		},
		{
			"empty authority",
			[]sdk.Msg{&coretypes.MsgPost{Authority: ""}},
		},
		{
			"multiple relay msgs, no gov",
			[]sdk.Msg{
				&coretypes.MsgPost{Authority: "mirage1abc"},
				&coretypes.MsgVote{Authority: "mirage1abc"},
			},
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			called = false
			tx := mockTx{msgs: tc.msgs}
			_, err := dec.AnteHandle(sdk.Context{}, tx, false, passthrough)
			require.NoError(t, err)
			require.True(t, called, "next handler should have been called")
		})
	}
}
