package app

import (
	"crypto/sha256"
	"fmt"

	sdk "github.com/cosmos/cosmos-sdk/types"
	authante "github.com/cosmos/cosmos-sdk/x/auth/ante"
	authtypes "github.com/cosmos/cosmos-sdk/x/auth/types"
	govtypes "github.com/cosmos/cosmos-sdk/x/gov/types"

	sdkmath "cosmossdk.io/math"

	corekeeper "mirage/x/core/keeper"
	coretypes "mirage/x/core/types"
)

// RetiredMsgDecorator rejects decode-only historical type URLs in new txs.
type RetiredMsgDecorator struct{}

func (d RetiredMsgDecorator) AnteHandle(ctx sdk.Context, tx sdk.Tx, simulate bool, next sdk.AnteHandler) (sdk.Context, error) {
	retired := coretypes.RetiredMsgTypeURLs()
	for _, msg := range tx.GetMsgs() {
		if _, ok := retired[sdk.MsgTypeURL(msg)]; ok {
			return ctx, fmt.Errorf("retired message type %s is not accepted after v1.39.0", sdk.MsgTypeURL(msg))
		}
	}
	return next(ctx, tx, simulate)
}

// OnePostPerTxDecorator rejects more than one transitive MsgPost in a transaction.
type OnePostPerTxDecorator struct{}

func (d OnePostPerTxDecorator) AnteHandle(ctx sdk.Context, tx sdk.Tx, simulate bool, next sdk.AnteHandler) (sdk.Context, error) {
	all, err := transitiveMsgs(tx)
	if err != nil {
		return ctx, err
	}
	posts := 0
	for _, m := range all {
		if _, ok := m.(*coretypes.MsgPost); ok {
			posts++
			if posts > 1 {
				return ctx, fmt.Errorf("transactions may contain at most one MsgPost")
			}
		}
	}
	return next(ctx, tx, simulate)
}

func subscriberZeroFeeChecker(ck corekeeper.Keeper) authante.TxFeeChecker {
	return func(ctx sdk.Context, tx sdk.Tx) (sdk.Coins, int64, error) {
		feeTx, ok := tx.(sdk.FeeTx)
		if !ok {
			return nil, 0, fmt.Errorf("tx must implement the FeeTx interface")
		}
		fee := feeTx.GetFee()
		if fee.IsZero() {
			if err := requireZeroFeeEligible(ctx, ck, tx); err != nil {
				return nil, 0, err
			}
			return fee, int64(1), nil
		}
		return minGasPriceFeeChecker(ctx, tx)
	}
}

func minGasPriceFeeChecker(ctx sdk.Context, tx sdk.Tx) (sdk.Coins, int64, error) {
	feeTx, ok := tx.(sdk.FeeTx)
	if !ok {
		return nil, 0, fmt.Errorf("tx must implement the FeeTx interface")
	}
	feeCoins := feeTx.GetFee()
	gas := feeTx.GetGas()
	if ctx.IsCheckTx() {
		minGasPrices := ctx.MinGasPrices()
		if !minGasPrices.IsZero() {
			requiredFees := make(sdk.Coins, len(minGasPrices))
			glDec := sdkmath.LegacyNewDec(int64(gas))
			for i, gp := range minGasPrices {
				fee := gp.Amount.Mul(glDec)
				requiredFees[i] = sdk.NewCoin(gp.Denom, fee.Ceil().RoundInt())
			}
			if !feeCoins.IsAnyGTE(requiredFees) {
				return nil, 0, fmt.Errorf("insufficient fees; got: %s required: %s", feeCoins, requiredFees)
			}
		}
	}
	priority := int64(1)
	if gas > 0 && feeCoins.Len() > 0 {
		priority = feeCoins[0].Amount.QuoRaw(int64(gas)).Int64()
	}
	return feeCoins, priority, nil
}

func requireZeroFeeEligible(ctx sdk.Context, ck corekeeper.Keeper, tx sdk.Tx) error {
	govAuthority := authtypes.NewModuleAddress(govtypes.ModuleName).String()
	msgs := tx.GetMsgs()
	if len(msgs) == 0 {
		return fmt.Errorf("zero-fee transactions require relay messages")
	}
	for _, msg := range msgs {
		if !isRelayMessage(msg) {
			return fmt.Errorf("zero-fee is only valid for Subscriber relay messages")
		}
		if am, ok := msg.(interface{ GetAuthority() string }); ok && am.GetAuthority() == govAuthority {
			return fmt.Errorf("zero-fee is not valid for governance messages")
		}
		pk, ok := envelopePubkeyOf(msg)
		if !ok || len(pk) != 33 {
			return fmt.Errorf("zero-fee relay requires a valid envelope pubkey")
		}
		owner, err := ownerFromPubkey(pk)
		if err != nil {
			return err
		}
		paid, err := ck.IsEffectivePaid(ctx, owner)
		if err != nil {
			return err
		}
		if !paid {
			return fmt.Errorf("zero-fee Subscriber relay requires effective_paid")
		}
	}
	return nil
}

func ownerFromPubkey(pk []byte) (string, error) {
	if len(pk) != 33 {
		return "", fmt.Errorf("invalid envelope_pubkey length")
	}
	addr := deriveAddrFromPubKey(pk)
	if addr == "" {
		return "", fmt.Errorf("failed to derive address from envelope pubkey")
	}
	return addr, nil
}

func writeCanonBool(w *canonWriter, tag byte, v bool) {
	if v {
		w.writeUvarint(tag, 1)
	} else {
		w.writeUvarint(tag, 0)
	}
}

func (d RelaySigDecorator) authEnvelope(
	ctx sdk.Context,
	govAuthority string,
	maxAge uint64,
	name, authority string,
	pubkey, blockHash []byte,
	difficulty, pow, ts, nonce uint64,
	sig []byte,
	fill func(*canonWriter),
) error {
	if authority == govAuthority {
		return nil
	}
	if err := validateEnvelopeTimestamp(ctx, ts, maxAge); err != nil {
		ctx.Logger().Error("RelaySig: timestamp validation failed", "msg", name, "err", err.Error())
		return err
	}
	pubHash := sha256.Sum256(pubkey)
	if nonce == 0 {
		return fmt.Errorf("envelope_nonce is required (must be >0)")
	}
	if d.Keeper.HasEnvelopeNonce(ctx, pubHash[:16], nonce) {
		return fmt.Errorf("envelope replay: nonce already used")
	}
	if err := verifyRelaySignature(name, pubkey, sig, func(w *canonWriter) {
		w.writeBytes(2, pubkey)
		w.writeBytes(3, blockHash)
		w.writeUvarint(4, difficulty)
		w.writeUvarint(5, pow)
		w.writeUvarint(6, ts)
		w.writeUvarint(7, nonce)
		fill(w)
	}); err != nil {
		ctx.Logger().Error("RelaySig: verification failed", "msg", name, "err", err.Error())
		return err
	}
	nonceExpiry, err := envelopeNonceExpiryUnix(ctx, ts, maxAge)
	if err != nil {
		return err
	}
	if err := d.Keeper.SetEnvelopeNonce(ctx, pubHash[:16], nonce, nonceExpiry); err != nil {
		ctx.Logger().Error("RelaySig: failed to record nonce", "msg", name, "err", err.Error())
		return fmt.Errorf("failed to record nonce: %w", err)
	}
	return nil
}

func (d *PowDecorator) standardPoW(
	ctx sdk.Context,
	govAuthority, authority string,
	pubkey, blockHash []byte,
	difficulty, pow uint64,
	params coretypes.Params,
	msgCount uint64,
	name string,
	canon []byte,
	verifyPoW func(canonical []byte, lastBlockHash []byte, difficulty, pow uint64) error,
) (sdk.Context, error) {
	if authority == govAuthority {
		return ctx, nil
	}
	canPoW, err := d.routePoWTx(ctx, pubkey, params, name, msgCount)
	if err != nil {
		return ctx, err
	}
	if !canPoW {
		return ctx, nil
	}
	if err := verifyPoW(canon, blockHash, difficulty, pow); err != nil {
		ctx.Logger().Error("PoW: validation failed", "msg", name, "err", err.Error())
		return ctx, err
	}
	if ctx.Priority() <= 0 {
		ctx = ctx.WithPriority(int64(1 + difficulty))
	}
	if !ctx.IsCheckTx() && !ctx.IsReCheckTx() {
		if err := d.Keeper.RecordPoWMessage(ctx); err != nil {
			ctx.Logger().Error("PoW: failed to record message", "err", err.Error())
			return ctx, err
		}
	}
	return ctx, nil
}
