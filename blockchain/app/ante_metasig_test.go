package app

import (
	"bytes"
	"strings"
	"testing"
	"time"

	cosmoslog "cosmossdk.io/log"
	sdkmath "cosmossdk.io/math"
	secp "github.com/cosmos/cosmos-sdk/crypto/keys/secp256k1"
	sdk "github.com/cosmos/cosmos-sdk/types"
	authtypes "github.com/cosmos/cosmos-sdk/x/auth/types"
	"github.com/cosmos/cosmos-sdk/x/authz"
	banktypes "github.com/cosmos/cosmos-sdk/x/bank/types"
	distrtypes "github.com/cosmos/cosmos-sdk/x/distribution/types"
	govtypes "github.com/cosmos/cosmos-sdk/x/gov/types"
	govv1 "github.com/cosmos/cosmos-sdk/x/gov/types/v1"
	minttypes "github.com/cosmos/cosmos-sdk/x/mint/types"
	slashingtypes "github.com/cosmos/cosmos-sdk/x/slashing/types"
	stakingtypes "github.com/cosmos/cosmos-sdk/x/staking/types"
	"github.com/stretchr/testify/require"
	protov2 "google.golang.org/protobuf/proto"

	coretypes "mirage/x/core/types"
)

func TestVerifyRelaySignatureBlockTopic(t *testing.T) {
	priv := secp.PrivKey{Key: bytes.Repeat([]byte{0x01}, 32)}
	pub := priv.PubKey().Bytes()

	blockHash := []byte("blockhash")
	difficulty := uint64(3)
	pow := uint64(9)
	timestamp := uint64(1710001112223)
	target := ""
	topic := "topic123"

	w := newCanonWriter("MsgBlockTopic")
	w.writeBytes(2, pub)
	w.writeBytes(3, blockHash)
	w.writeUvarint(4, difficulty)
	w.writeUvarint(5, pow)
	w.writeUvarint(6, timestamp)
	w.writeString(100, target)
	w.writeString(101, topic)
	sig, err := priv.Sign(w.buf)
	require.NoError(t, err)

	t.Logf("[debug] block_topic sig len=%d topic=%s", len(sig), topic)
	err = verifyRelaySignature("MsgBlockTopic", pub, sig, func(cw *canonWriter) {
		cw.writeBytes(2, pub)
		cw.writeBytes(3, blockHash)
		cw.writeUvarint(4, difficulty)
		cw.writeUvarint(5, pow)
		cw.writeUvarint(6, timestamp)
		cw.writeString(100, target)
		cw.writeString(101, topic)
	})
	require.NoError(t, err)
}

func TestVerifyRelaySignatureBlockTopicRejectsTopicChange(t *testing.T) {
	priv := secp.PrivKey{Key: bytes.Repeat([]byte{0x02}, 32)}
	pub := priv.PubKey().Bytes()

	blockHash := []byte("blockhash")
	difficulty := uint64(2)
	pow := uint64(1)
	timestamp := uint64(1710002223334)
	target := ""
	topic := "topicx"

	w := newCanonWriter("MsgBlockTopic")
	w.writeBytes(2, pub)
	w.writeBytes(3, blockHash)
	w.writeUvarint(4, difficulty)
	w.writeUvarint(5, pow)
	w.writeUvarint(6, timestamp)
	w.writeString(100, target)
	w.writeString(101, topic)
	sig, err := priv.Sign(w.buf)
	require.NoError(t, err)

	t.Logf("[debug] block_topic signature test with mismatched topic")
	err = verifyRelaySignature("MsgBlockTopic", pub, sig, func(cw *canonWriter) {
		cw.writeBytes(2, pub)
		cw.writeBytes(3, blockHash)
		cw.writeUvarint(4, difficulty)
		cw.writeUvarint(5, pow)
		cw.writeUvarint(6, timestamp)
		cw.writeString(100, target)
		cw.writeString(101, "topicy")
	})
	require.Error(t, err)
	require.Contains(t, err.Error(), "invalid relay signature")
}

func TestVerifyRelaySignatureAward(t *testing.T) {
	priv := secp.PrivKey{Key: bytes.Repeat([]byte{0x03}, 32)}
	pub := priv.PubKey().Bytes()

	blockHash := []byte("blockhash")
	difficulty := uint64(1)
	pow := uint64(0)
	timestamp := uint64(1710003334445)
	target := "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
	awardType := "quality_post"

	w := newCanonWriter("MsgAward")
	w.writeBytes(2, pub)
	w.writeBytes(3, blockHash)
	w.writeUvarint(4, difficulty)
	w.writeUvarint(5, pow)
	w.writeUvarint(6, timestamp)
	w.writeString(100, target)
	w.writeString(101, awardType)
	sig, err := priv.Sign(w.buf)
	require.NoError(t, err)

	t.Logf("[debug] award sig len=%d type=%s target=%s", len(sig), awardType, target)
	err = verifyRelaySignature("MsgAward", pub, sig, func(cw *canonWriter) {
		cw.writeBytes(2, pub)
		cw.writeBytes(3, blockHash)
		cw.writeUvarint(4, difficulty)
		cw.writeUvarint(5, pow)
		cw.writeUvarint(6, timestamp)
		cw.writeString(100, target)
		cw.writeString(101, awardType)
	})
	require.NoError(t, err)
}

func TestVerifyRelaySignatureAwardRejectsTypeChange(t *testing.T) {
	priv := secp.PrivKey{Key: bytes.Repeat([]byte{0x04}, 32)}
	pub := priv.PubKey().Bytes()

	blockHash := []byte("blockhash")
	difficulty := uint64(2)
	pow := uint64(1)
	timestamp := uint64(1710004445556)
	target := "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
	awardType := "quality_post"

	w := newCanonWriter("MsgAward")
	w.writeBytes(2, pub)
	w.writeBytes(3, blockHash)
	w.writeUvarint(4, difficulty)
	w.writeUvarint(5, pow)
	w.writeUvarint(6, timestamp)
	w.writeString(100, target)
	w.writeString(101, awardType)
	sig, err := priv.Sign(w.buf)
	require.NoError(t, err)

	t.Logf("[debug] award sig mismatch type=%s", awardType)
	err = verifyRelaySignature("MsgAward", pub, sig, func(cw *canonWriter) {
		cw.writeBytes(2, pub)
		cw.writeBytes(3, blockHash)
		cw.writeUvarint(4, difficulty)
		cw.writeUvarint(5, pow)
		cw.writeUvarint(6, timestamp)
		cw.writeString(100, target)
		cw.writeString(101, "based")
	})
	require.Error(t, err)
	require.Contains(t, err.Error(), "invalid relay signature")
}

func TestVerifyRelaySignatureInvalidFields(t *testing.T) {
	err := verifyRelaySignature("MsgBlockTopic", []byte{1, 2}, []byte{3, 4}, func(cw *canonWriter) {
		cw.writeString(100, "")
		cw.writeString(101, "topic")
	})
	require.Error(t, err)
	require.Contains(t, err.Error(), "invalid relay fields")
}

func TestValidateEnvelopeTimestampBoundaries(t *testing.T) {
	blockTime := time.Date(2026, 2, 14, 12, 0, 0, 0, time.UTC)
	ctx := sdk.Context{}.WithBlockTime(blockTime)
	maxAge := uint64(60)

	okPast := uint64(blockTime.Add(-30 * time.Second).UnixMilli())
	okFuture := uint64(blockTime.Add(10 * time.Second).UnixMilli())
	tooOld := uint64(blockTime.Add(-120 * time.Second).UnixMilli())
	tooFuture := uint64(blockTime.Add(40 * time.Second).UnixMilli())

	t.Logf("[debug] timestamp boundaries okPast=%d okFuture=%d tooOld=%d tooFuture=%d", okPast, okFuture, tooOld, tooFuture)
	require.NoError(t, validateEnvelopeTimestamp(ctx, okPast, maxAge))
	require.NoError(t, validateEnvelopeTimestamp(ctx, okFuture, maxAge))
	require.Error(t, validateEnvelopeTimestamp(ctx, tooOld, maxAge))
	require.Error(t, validateEnvelopeTimestamp(ctx, tooFuture, maxAge))
}

func TestRelayGasFeeDecoratorEnforcesMinGasOnCheckTx(t *testing.T) {
	minPrices := sdk.NewDecCoins(sdk.NewDecCoinFromDec("umirage", sdkmath.LegacyNewDec(1)))
	ctx := sdk.Context{}.WithMinGasPrices(minPrices).WithExecMode(sdk.ExecModeCheck).WithLogger(cosmoslog.NewNopLogger())

	tx := testFeeTx{
		fee: sdk.NewCoins(),
		gas: 1000,
	}

	dec := RelayGasFeeDecorator{}
	nextCalled := false
	next := func(ctx sdk.Context, tx sdk.Tx, simulate bool) (sdk.Context, error) {
		nextCalled = true
		return ctx, nil
	}

	t.Logf("[debug] checktx min_gas_prices=%s gas=%d fee=%s", minPrices.String(), tx.gas, tx.fee.String())
	_, err := dec.AnteHandle(ctx, tx, false, next)
	require.Error(t, err)
	require.Contains(t, err.Error(), "insufficient fee")
	require.False(t, nextCalled)
}

type testFeeTx struct {
	fee   sdk.Coins
	gas   uint64
	payer sdk.AccAddress
}

func (t testFeeTx) GetGas() uint64 { return t.gas }

func (t testFeeTx) GetFee() sdk.Coins { return t.fee }

func (t testFeeTx) FeePayer() []byte { return t.payer }

func (t testFeeTx) FeeGranter() []byte { return nil }

func (t testFeeTx) GetMsgs() []sdk.Msg { return nil }

func (t testFeeTx) GetMsgsV2() ([]protov2.Message, error) { return nil, nil }

func (t testFeeTx) ValidateBasic() error { return nil }

// --- C-1 exhaustive tests: mixed relay + SDK message rejection ---

func TestIsRelayMessage(t *testing.T) {
	relayMsgs := []sdk.Msg{
		&coretypes.MsgPost{},
		&coretypes.MsgVote{},
		&coretypes.MsgSetUsername{},
		&coretypes.MsgEnableAgent{},
		&coretypes.MsgDisableAgent{},
		&coretypes.MsgSetAgents{},
		&coretypes.MsgFollowUser{},
		&coretypes.MsgUnfollowUser{},
		&coretypes.MsgFollowTopic{},
		&coretypes.MsgUnfollowTopic{},
		&coretypes.MsgBlockPost{},
		&coretypes.MsgUnblockPost{},
		&coretypes.MsgBlockUser{},
		&coretypes.MsgUnblockUser{},
		&coretypes.MsgBlockTopic{},
		&coretypes.MsgUnblockTopic{},
		&coretypes.MsgDelete{},
		&coretypes.MsgDeleteUser{},
		&coretypes.MsgSendTokens{},
		&coretypes.MsgEdit{},
		&coretypes.MsgSubscribe{},
		&coretypes.MsgSetAutoRenewal{},
		&coretypes.MsgBridgeBurn{},
		&coretypes.MsgAward{},
		&coretypes.MsgSetBiography{},
		&coretypes.MsgAnnotate{},
	}
	for _, m := range relayMsgs {
		require.True(t, isRelayMessage(m), "expected relay: %T", m)
	}

	nonRelayMsgs := []sdk.Msg{
		&banktypes.MsgSend{},
		&banktypes.MsgMultiSend{},
		&stakingtypes.MsgDelegate{},
		&stakingtypes.MsgUndelegate{},
		&govv1.MsgSubmitProposal{},
		&slashingtypes.MsgUnjail{},
		&distrtypes.MsgSetWithdrawAddress{},
		&authz.MsgGrant{},
	}
	for _, m := range nonRelayMsgs {
		require.False(t, isRelayMessage(m), "expected non-relay: %T", m)
	}
}

func TestMixedRelaySDKMessageRejection(t *testing.T) {
	govAuthority := authtypes.NewModuleAddress(govtypes.ModuleName).String()

	sdkMsgs := []struct {
		name string
		msg  sdk.Msg
	}{
		// bank
		{"bank.MsgSend", &banktypes.MsgSend{}},
		{"bank.MsgMultiSend", &banktypes.MsgMultiSend{}},
		{"bank.MsgUpdateParams", &banktypes.MsgUpdateParams{}},
		// staking
		{"staking.MsgDelegate", &stakingtypes.MsgDelegate{}},
		{"staking.MsgUndelegate", &stakingtypes.MsgUndelegate{}},
		{"staking.MsgBeginRedelegate", &stakingtypes.MsgBeginRedelegate{}},
		{"staking.MsgCancelUnbondingDelegation", &stakingtypes.MsgCancelUnbondingDelegation{}},
		{"staking.MsgCreateValidator", &stakingtypes.MsgCreateValidator{}},
		{"staking.MsgEditValidator", &stakingtypes.MsgEditValidator{}},
		{"staking.MsgUpdateParams", &stakingtypes.MsgUpdateParams{}},
		// gov
		{"gov.MsgSubmitProposal", &govv1.MsgSubmitProposal{}},
		{"gov.MsgVote", &govv1.MsgVote{}},
		{"gov.MsgVoteWeighted", &govv1.MsgVoteWeighted{}},
		{"gov.MsgDeposit", &govv1.MsgDeposit{}},
		// authz
		{"authz.MsgGrant", &authz.MsgGrant{}},
		{"authz.MsgRevoke", &authz.MsgRevoke{}},
		{"authz.MsgExec", &authz.MsgExec{}},
		// distribution
		{"distribution.MsgSetWithdrawAddress", &distrtypes.MsgSetWithdrawAddress{}},
		{"distribution.MsgWithdrawDelegatorReward", &distrtypes.MsgWithdrawDelegatorReward{}},
		{"distribution.MsgWithdrawValidatorCommission", &distrtypes.MsgWithdrawValidatorCommission{}},
		{"distribution.MsgFundCommunityPool", &distrtypes.MsgFundCommunityPool{}},
		{"distribution.MsgUpdateParams", &distrtypes.MsgUpdateParams{}},
		// slashing
		{"slashing.MsgUnjail", &slashingtypes.MsgUnjail{}},
		{"slashing.MsgUpdateParams", &slashingtypes.MsgUpdateParams{}},
		// mint
		{"mint.MsgUpdateParams", &minttypes.MsgUpdateParams{}},
	}

	relayMsg := &coretypes.MsgPost{}

	for _, tc := range sdkMsgs {
		t.Run("relay+"+tc.name, func(t *testing.T) {
			msgs := []sdk.Msg{relayMsg, tc.msg}
			isRelay, hasNon := classifyMsgs(msgs)
			require.True(t, isRelay, "should detect relay message")
			require.True(t, hasNon, "should detect non-relay message %s", tc.name)
		})
	}

	t.Run("relay+gov_authority_short_circuit", func(t *testing.T) {
		msgs := []sdk.Msg{
			&coretypes.MsgPost{},
			&banktypes.MsgUpdateParams{Authority: govAuthority},
		}
		isRelay, hasNon := classifyMsgs(msgs)
		require.False(t, isRelay)
		require.False(t, hasNon)
	})

	// Pure relay tx must be accepted (both flags consistent).
	t.Run("pure_relay", func(t *testing.T) {
		msgs := []sdk.Msg{
			&coretypes.MsgPost{},
			&coretypes.MsgVote{},
			&coretypes.MsgFollowUser{},
		}
		isRelay, hasNon := classifyMsgs(msgs)
		require.True(t, isRelay)
		require.False(t, hasNon)
	})

	// Pure SDK tx must route to standard ante.
	t.Run("pure_sdk", func(t *testing.T) {
		msgs := []sdk.Msg{
			&banktypes.MsgSend{},
			&stakingtypes.MsgDelegate{},
		}
		isRelay, hasNon := classifyMsgs(msgs)
		require.False(t, isRelay)
		require.True(t, hasNon)
	})
}

// classifyMsgs replicates the ante handler's message classification logic
// for testability.
func classifyMsgs(msgs []sdk.Msg) (isRelayTx, hasNonRelay bool) {
	govAuthority := authtypes.NewModuleAddress(govtypes.ModuleName).String()
	for _, m := range msgs {
		if am, ok := m.(interface{ GetAuthority() string }); ok {
			if strings.TrimSpace(am.GetAuthority()) == govAuthority {
				return false, false
			}
		}
		if isRelayMessage(m) {
			isRelayTx = true
		} else {
			hasNonRelay = true
		}
	}
	return
}
