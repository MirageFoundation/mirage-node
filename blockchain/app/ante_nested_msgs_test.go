package app

import (
	"testing"

	cosmoslog "cosmossdk.io/log/v2"
	codectypes "github.com/cosmos/cosmos-sdk/codec/types"
	sdk "github.com/cosmos/cosmos-sdk/types"
	authtypes "github.com/cosmos/cosmos-sdk/x/auth/types"
	"github.com/cosmos/cosmos-sdk/x/authz"
	govtypes "github.com/cosmos/cosmos-sdk/x/gov/types"
	stakingtypes "github.com/cosmos/cosmos-sdk/x/staking/types"
	"github.com/stretchr/testify/require"

	coretypes "mirage/x/core/types"
)

// wrapInExec builds an authz.MsgExec carrying the given messages. MsgExec is
// the concrete wrapper that made C-1 exploitable; the module is no longer wired,
// but the type is kept here on purpose so the guard is tested against the real
// shape rather than a hand-rolled stand-in.
func wrapInExec(t *testing.T, inner ...sdk.Msg) *authz.MsgExec {
	t.Helper()
	anys := make([]*codectypes.Any, 0, len(inner))
	for _, m := range inner {
		a, err := codectypes.NewAnyWithValue(m)
		require.NoError(t, err)
		anys = append(anys, a)
	}
	return &authz.MsgExec{Grantee: "mirage1grantee", Msgs: anys}
}

// TestNestedRelayMessageRejectedForEveryPrototype is the C-1 regression test.
//
// The exploit: authz.MsgExec is not a relay message, so a transaction whose only
// top-level message is MsgExec was classified as a pure non-relay transaction and
// sent down the standard ante chain. RelaySigDecorator and PowDecorator live only
// in the relay chain, so the envelope signature, the nonce replay check and the
// proof of work were all skipped, while the handler authorized purely on an
// envelope_pubkey that nothing had verified. One ordinary signed transaction
// drained any account holding a username.
//
// Driven off relayMessagePrototypes() rather than a hand-written list so that a
// newly added relay message cannot be forgotten here.
func TestNestedRelayMessageRejectedForEveryPrototype(t *testing.T) {
	protos := relayMessagePrototypes()
	require.NotEmpty(t, protos)

	for _, proto := range protos {
		name := sdk.MsgTypeURL(proto)
		t.Run(name, func(t *testing.T) {
			ctx := sdk.Context{}.
				WithExecMode(sdk.ExecModeCheck).
				WithLogger(cosmoslog.NewNopLogger())

			tx := mockTx{msgs: []sdk.Msg{wrapInExec(t, proto)}}

			var stdCalled, relayCalled bool
			stdAnte := func(c sdk.Context, _ sdk.Tx, _ bool) (sdk.Context, error) {
				stdCalled = true
				return c, nil
			}
			relayAnte := func(c sdk.Context, _ sdk.Tx, _ bool) (sdk.Context, error) {
				relayCalled = true
				return c, nil
			}

			_, err := mirageAnteRouter(ctx, tx, false, GovAuthorityDecorator{}, stdAnte, relayAnte)
			require.Error(t, err, "a nested %s must be rejected", name)
			require.Contains(t, err.Error(), "cannot be nested")
			require.False(t, stdCalled, "nested relay message reached the standard ante chain")
			require.False(t, relayCalled, "nested relay message reached the relay ante chain")
		})
	}
}

// TestNestedStakingMessageRejected pins the second consequence of the same root
// cause: rejectDelegatorStakingMsgs was hoisted to the front of the router
// specifically so it covered both paths, but it inspected only the top level, so
// a third-party delegation nested inside MsgExec ran unfiltered. Delegation moves
// consensus voting power, so this was a consensus-relevant policy bypass.
func TestNestedStakingMessageRejected(t *testing.T) {
	ctx := sdk.Context{}.
		WithExecMode(sdk.ExecModeCheck).
		WithLogger(cosmoslog.NewNopLogger())

	thirdParty := &stakingtypes.MsgDelegate{
		DelegatorAddress: "mirage1delegator",
		ValidatorAddress: "miragevaloper1validator",
	}
	tx := mockTx{msgs: []sdk.Msg{wrapInExec(t, thirdParty)}}

	noop := func(c sdk.Context, _ sdk.Tx, _ bool) (sdk.Context, error) { return c, nil }
	_, err := mirageAnteRouter(ctx, tx, false, GovAuthorityDecorator{}, noop, noop)
	require.ErrorIs(t, err, ErrDelegationDisabled)

	// And through the standalone decorator, which is what the relay path uses.
	_, err = DisableDelegatorStakingDecorator{}.AnteHandle(ctx, tx, false, noop)
	require.ErrorIs(t, err, ErrDelegationDisabled)
}

// TestGovAuthorityDecoratorSeesNestedMessages pins the third consequence. The
// decorator documents that "any transaction arriving here with gov authority is
// a spoof attempt" and rejects unconditionally — but a transaction whose single
// top-level message is MsgExec has no GetAuthority() of its own, so the check
// passed on both paths and the documented invariant was simply false.
func TestGovAuthorityDecoratorSeesNestedMessages(t *testing.T) {
	govAuthority := authtypes.NewModuleAddress(govtypes.ModuleName).String()
	inner := &coretypes.MsgUpdateParams{Authority: govAuthority}

	ctx := sdk.Context{}.WithLogger(cosmoslog.NewNopLogger())
	tx := mockTx{msgs: []sdk.Msg{wrapInExec(t, inner)}}

	var called bool
	next := func(c sdk.Context, _ sdk.Tx, _ bool) (sdk.Context, error) {
		called = true
		return c, nil
	}

	_, err := GovAuthorityDecorator{}.AnteHandle(ctx, tx, false, next)
	require.Error(t, err)
	require.Contains(t, err.Error(), "governance authority")
	require.False(t, called, "a nested gov-authority message reached the ante chain")
}

// TestMsgNestingDepthIsBounded ensures the transitive walk cannot be turned into
// unbounded work by a deeply nested wrapper chain.
func TestMsgNestingDepthIsBounded(t *testing.T) {
	var msg sdk.Msg = &coretypes.MsgPost{}
	for i := 0; i < maxMsgNestingDepth+2; i++ {
		msg = wrapInExec(t, msg)
	}

	_, err := transitiveMsgs(mockTx{msgs: []sdk.Msg{msg}})
	require.Error(t, err)
	require.Contains(t, err.Error(), "nesting exceeds")
}

// TestTransitiveMsgsIncludesTopLevel guards the obvious regression: a flatten
// that returned only the nested messages would silently disable every check that
// now runs over the transitive set.
func TestTransitiveMsgsIncludesTopLevel(t *testing.T) {
	top := &coretypes.MsgPost{}
	plain := mockTx{msgs: []sdk.Msg{top}}

	got, err := transitiveMsgs(plain)
	require.NoError(t, err)
	require.Len(t, got, 1)
	require.Equal(t, sdk.MsgTypeURL(top), sdk.MsgTypeURL(got[0]))

	inner := &coretypes.MsgVote{}
	wrapped := mockTx{msgs: []sdk.Msg{top, wrapInExec(t, inner)}}

	got, err = transitiveMsgs(wrapped)
	require.NoError(t, err)
	urls := make([]string, 0, len(got))
	for _, m := range got {
		urls = append(urls, sdk.MsgTypeURL(m))
	}
	require.Contains(t, urls, sdk.MsgTypeURL(top))
	require.Contains(t, urls, sdk.MsgTypeURL(inner))
	require.Contains(t, urls, sdk.MsgTypeURL(&authz.MsgExec{}))
}
