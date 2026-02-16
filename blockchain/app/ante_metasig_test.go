package app

import (
	"bytes"
	"testing"
	"time"

	sdkmath "cosmossdk.io/math"
	secp "github.com/cosmos/cosmos-sdk/crypto/keys/secp256k1"
	sdk "github.com/cosmos/cosmos-sdk/types"
	"github.com/stretchr/testify/require"
	protov2 "google.golang.org/protobuf/proto"
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
	ctx := sdk.Context{}.WithMinGasPrices(minPrices).WithExecMode(sdk.ExecModeCheck)

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
