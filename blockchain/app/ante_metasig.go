package app

import (
	"crypto/sha256"
	"encoding/binary"
	"fmt"
	"time"

	secp "github.com/cosmos/cosmos-sdk/crypto/keys/secp256k1"
	sdk "github.com/cosmos/cosmos-sdk/types"
	authsigning "github.com/cosmos/cosmos-sdk/x/auth/signing"
	authtypes "github.com/cosmos/cosmos-sdk/x/auth/types"
	bankkeeper "github.com/cosmos/cosmos-sdk/x/bank/keeper"
	govtypes "github.com/cosmos/cosmos-sdk/x/gov/types"

	corekeeper "mirage/x/core/keeper"
	coretypes "mirage/x/core/types"
)

// RelaySigDecorator verifies per-message relay signatures embedded in msgs.
// It allows transactions without outer signatures by authenticating each
// message author through fields {pubkey, signature}.
//
// Canonical bytes for signing are constructed deterministically for each
// supported message by concatenating tagged fields with length-prefixes:
//
//	prefix "mirage.core.v1:" + MsgName + 0x00
//	for each field in numeric order (excluding signature):
//	  - a single-byte field tag (the proto field number, clamped to [1,254])
//	  - for strings/bytes: uvarint(len) + raw bytes
//	  - for uint64/int32: uvarint(value)
//
// The signature is ECDSA secp256k1 over sha256(canonical_bytes) using a 64-byte
// fixed-length (R||S) encoding, and pubkey is 33-byte compressed secp256k1.
type RelaySigDecorator struct {
	Keeper corekeeper.Keeper
}

func (d RelaySigDecorator) AnteHandle(ctx sdk.Context, tx sdk.Tx, simulate bool, next sdk.AnteHandler) (sdk.Context, error) {
	govAuthority := authtypes.NewModuleAddress(govtypes.ModuleName).String()
	params := d.Keeper.GetParams(ctx)
	maxAge := params.MaxEnvelopeAge

	for _, msg := range tx.GetMsgs() {
		switch m := msg.(type) {
		case *coretypes.MsgPost:
			if m.Authority == govAuthority {
				continue // Skip validation for governance
			}
			if err := validateEnvelopeTimestamp(ctx, m.EnvelopeTimestamp, maxAge); err != nil {
				ctx.Logger().Error("RelaySig: timestamp validation failed", "msg", "MsgPost", "err", err.Error())
				return ctx, err
			}
			if err := verifyRelaySignature("MsgPost", m.EnvelopePubkey, m.EnvelopeSignature, func(w *canonWriter) {
				w.writeBytes(2, m.EnvelopePubkey)
				w.writeBytes(3, m.EnvelopeBlockHash)
				w.writeUvarint(4, m.EnvelopeDifficulty)
				w.writeUvarint(5, m.EnvelopePow)
				w.writeUvarint(6, m.EnvelopeTimestamp)
				w.writeString(100, m.Target)
				w.writeString(101, m.Topic)
				w.writeString(102, m.Title)
				w.writeString(103, m.Content)
				w.writeString(104, m.Tag)
				for _, media := range m.Media {
					w.writeString(105, media)
				}
			}); err != nil {
				ctx.Logger().Error("RelaySig: verification failed", "msg", "MsgPost", "err", err.Error())
				return ctx, err
			}
		case *coretypes.MsgVote:
			if m.Authority == govAuthority {
				continue // Skip validation for governance
			}
			if err := validateEnvelopeTimestamp(ctx, m.EnvelopeTimestamp, maxAge); err != nil {
				ctx.Logger().Error("RelaySig: timestamp validation failed", "msg", "MsgVote", "err", err.Error())
				return ctx, err
			}
			if err := verifyRelaySignature("MsgVote", m.EnvelopePubkey, m.EnvelopeSignature, func(w *canonWriter) {
				w.writeBytes(2, m.EnvelopePubkey)
				w.writeBytes(3, m.EnvelopeBlockHash)
				w.writeUvarint(4, m.EnvelopeDifficulty)
				w.writeUvarint(5, m.EnvelopePow)
				w.writeUvarint(6, m.EnvelopeTimestamp)
				w.writeString(100, m.Target)
				w.writeUvarint(101, uint64(uint32(m.Direction)))
			}); err != nil {
				ctx.Logger().Error("RelaySig: verification failed", "msg", "MsgVote", "err", err.Error())
				return ctx, err
			}
		case *coretypes.MsgSetUsername:
			if m.Authority == govAuthority {
				continue // Skip validation for governance
			}
			if err := validateEnvelopeTimestamp(ctx, m.EnvelopeTimestamp, maxAge); err != nil {
				ctx.Logger().Error("RelaySig: timestamp validation failed", "msg", "MsgSetUsername", "err", err.Error())
				return ctx, err
			}
			if err := verifyRelaySignature("MsgSetUsername", m.EnvelopePubkey, m.EnvelopeSignature, func(w *canonWriter) {
				w.writeBytes(2, m.EnvelopePubkey)
				w.writeBytes(3, m.EnvelopeBlockHash)
				w.writeUvarint(4, m.EnvelopeDifficulty)
				w.writeUvarint(5, m.EnvelopePow)
				w.writeUvarint(6, m.EnvelopeTimestamp)
				w.writeString(100, m.Target)
				w.writeString(101, m.Username)
			}); err != nil {
				ctx.Logger().Error("RelaySig: verification failed", "msg", "MsgSetUsername", "err", err.Error())
				return ctx, err
			}
		case *coretypes.MsgFollowModerator:
			if m.Authority == govAuthority {
				continue
			}
			if err := validateEnvelopeTimestamp(ctx, m.EnvelopeTimestamp, maxAge); err != nil {
				ctx.Logger().Error("RelaySig: timestamp validation failed", "msg", "MsgFollowModerator", "err", err.Error())
				return ctx, err
			}
			if err := verifyRelaySignature("MsgFollowModerator", m.EnvelopePubkey, m.EnvelopeSignature, func(w *canonWriter) {
				w.writeBytes(2, m.EnvelopePubkey)
				w.writeBytes(3, m.EnvelopeBlockHash)
				w.writeUvarint(4, m.EnvelopeDifficulty)
				w.writeUvarint(5, m.EnvelopePow)
				w.writeUvarint(6, m.EnvelopeTimestamp)
				w.writeString(100, m.Target)
				w.writeString(101, m.Moderator)
			}); err != nil {
				ctx.Logger().Error("RelaySig: verification failed", "msg", "MsgFollowModerator", "err", err.Error())
				return ctx, err
			}
		case *coretypes.MsgUnfollowModerator:
			if m.Authority == govAuthority {
				continue
			}
			if err := validateEnvelopeTimestamp(ctx, m.EnvelopeTimestamp, maxAge); err != nil {
				ctx.Logger().Error("RelaySig: timestamp validation failed", "msg", "MsgUnfollowModerator", "err", err.Error())
				return ctx, err
			}
			if err := verifyRelaySignature("MsgUnfollowModerator", m.EnvelopePubkey, m.EnvelopeSignature, func(w *canonWriter) {
				w.writeBytes(2, m.EnvelopePubkey)
				w.writeBytes(3, m.EnvelopeBlockHash)
				w.writeUvarint(4, m.EnvelopeDifficulty)
				w.writeUvarint(5, m.EnvelopePow)
				w.writeUvarint(6, m.EnvelopeTimestamp)
				w.writeString(100, m.Target)
				w.writeString(101, m.Moderator)
			}); err != nil {
				ctx.Logger().Error("RelaySig: verification failed", "msg", "MsgUnfollowModerator", "err", err.Error())
				return ctx, err
			}
		case *coretypes.MsgFollowUser:
			if m.Authority == govAuthority {
				continue
			}
			if err := validateEnvelopeTimestamp(ctx, m.EnvelopeTimestamp, maxAge); err != nil {
				ctx.Logger().Error("RelaySig: timestamp validation failed", "msg", "MsgFollowUser", "err", err.Error())
				return ctx, err
			}
			if err := verifyRelaySignature("MsgFollowUser", m.EnvelopePubkey, m.EnvelopeSignature, func(w *canonWriter) {
				w.writeBytes(2, m.EnvelopePubkey)
				w.writeBytes(3, m.EnvelopeBlockHash)
				w.writeUvarint(4, m.EnvelopeDifficulty)
				w.writeUvarint(5, m.EnvelopePow)
				w.writeUvarint(6, m.EnvelopeTimestamp)
				w.writeString(100, m.Target)
				w.writeString(101, m.User)
			}); err != nil {
				ctx.Logger().Error("RelaySig: verification failed", "msg", "MsgFollowUser", "err", err.Error())
				return ctx, err
			}
		case *coretypes.MsgUnfollowUser:
			if m.Authority == govAuthority {
				continue
			}
			if err := validateEnvelopeTimestamp(ctx, m.EnvelopeTimestamp, maxAge); err != nil {
				ctx.Logger().Error("RelaySig: timestamp validation failed", "msg", "MsgUnfollowUser", "err", err.Error())
				return ctx, err
			}
			if err := verifyRelaySignature("MsgUnfollowUser", m.EnvelopePubkey, m.EnvelopeSignature, func(w *canonWriter) {
				w.writeBytes(2, m.EnvelopePubkey)
				w.writeBytes(3, m.EnvelopeBlockHash)
				w.writeUvarint(4, m.EnvelopeDifficulty)
				w.writeUvarint(5, m.EnvelopePow)
				w.writeUvarint(6, m.EnvelopeTimestamp)
				w.writeString(100, m.Target)
				w.writeString(101, m.User)
			}); err != nil {
				ctx.Logger().Error("RelaySig: verification failed", "msg", "MsgUnfollowUser", "err", err.Error())
				return ctx, err
			}
		case *coretypes.MsgFollowTopic:
			if m.Authority == govAuthority {
				continue
			}
			if err := validateEnvelopeTimestamp(ctx, m.EnvelopeTimestamp, maxAge); err != nil {
				ctx.Logger().Error("RelaySig: timestamp validation failed", "msg", "MsgFollowTopic", "err", err.Error())
				return ctx, err
			}
			if err := verifyRelaySignature("MsgFollowTopic", m.EnvelopePubkey, m.EnvelopeSignature, func(w *canonWriter) {
				w.writeBytes(2, m.EnvelopePubkey)
				w.writeBytes(3, m.EnvelopeBlockHash)
				w.writeUvarint(4, m.EnvelopeDifficulty)
				w.writeUvarint(5, m.EnvelopePow)
				w.writeUvarint(6, m.EnvelopeTimestamp)
				w.writeString(100, m.Target)
				w.writeString(101, m.Topic)
			}); err != nil {
				ctx.Logger().Error("RelaySig: verification failed", "msg", "MsgFollowTopic", "err", err.Error())
				return ctx, err
			}
		case *coretypes.MsgUnfollowTopic:
			if m.Authority == govAuthority {
				continue
			}
			if err := validateEnvelopeTimestamp(ctx, m.EnvelopeTimestamp, maxAge); err != nil {
				ctx.Logger().Error("RelaySig: timestamp validation failed", "msg", "MsgUnfollowTopic", "err", err.Error())
				return ctx, err
			}
			if err := verifyRelaySignature("MsgUnfollowTopic", m.EnvelopePubkey, m.EnvelopeSignature, func(w *canonWriter) {
				w.writeBytes(2, m.EnvelopePubkey)
				w.writeBytes(3, m.EnvelopeBlockHash)
				w.writeUvarint(4, m.EnvelopeDifficulty)
				w.writeUvarint(5, m.EnvelopePow)
				w.writeUvarint(6, m.EnvelopeTimestamp)
				w.writeString(100, m.Target)
				w.writeString(101, m.Topic)
			}); err != nil {
				ctx.Logger().Error("RelaySig: verification failed", "msg", "MsgUnfollowTopic", "err", err.Error())
				return ctx, err
			}
		case *coretypes.MsgBlockPost:
			if m.Authority == govAuthority {
				continue
			}
			if err := validateEnvelopeTimestamp(ctx, m.EnvelopeTimestamp, maxAge); err != nil {
				ctx.Logger().Error("RelaySig: timestamp validation failed", "msg", "MsgBlockPost", "err", err.Error())
				return ctx, err
			}
			if err := verifyRelaySignature("MsgBlockPost", m.EnvelopePubkey, m.EnvelopeSignature, func(w *canonWriter) {
				w.writeBytes(2, m.EnvelopePubkey)
				w.writeBytes(3, m.EnvelopeBlockHash)
				w.writeUvarint(4, m.EnvelopeDifficulty)
				w.writeUvarint(5, m.EnvelopePow)
				w.writeUvarint(6, m.EnvelopeTimestamp)
				w.writeString(100, m.Target)
			}); err != nil {
				ctx.Logger().Error("RelaySig: verification failed", "msg", "MsgBlockPost", "err", err.Error())
				return ctx, err
			}
		case *coretypes.MsgUnblockPost:
			if m.Authority == govAuthority {
				continue
			}
			if err := validateEnvelopeTimestamp(ctx, m.EnvelopeTimestamp, maxAge); err != nil {
				ctx.Logger().Error("RelaySig: timestamp validation failed", "msg", "MsgUnblockPost", "err", err.Error())
				return ctx, err
			}
			if err := verifyRelaySignature("MsgUnblockPost", m.EnvelopePubkey, m.EnvelopeSignature, func(w *canonWriter) {
				w.writeBytes(2, m.EnvelopePubkey)
				w.writeBytes(3, m.EnvelopeBlockHash)
				w.writeUvarint(4, m.EnvelopeDifficulty)
				w.writeUvarint(5, m.EnvelopePow)
				w.writeUvarint(6, m.EnvelopeTimestamp)
				w.writeString(100, m.Target)
			}); err != nil {
				ctx.Logger().Error("RelaySig: verification failed", "msg", "MsgUnblockPost", "err", err.Error())
				return ctx, err
			}
		case *coretypes.MsgBlockUser:
			if m.Authority == govAuthority {
				continue
			}
			if err := validateEnvelopeTimestamp(ctx, m.EnvelopeTimestamp, maxAge); err != nil {
				ctx.Logger().Error("RelaySig: timestamp validation failed", "msg", "MsgBlockUser", "err", err.Error())
				return ctx, err
			}
			if err := verifyRelaySignature("MsgBlockUser", m.EnvelopePubkey, m.EnvelopeSignature, func(w *canonWriter) {
				w.writeBytes(2, m.EnvelopePubkey)
				w.writeBytes(3, m.EnvelopeBlockHash)
				w.writeUvarint(4, m.EnvelopeDifficulty)
				w.writeUvarint(5, m.EnvelopePow)
				w.writeUvarint(6, m.EnvelopeTimestamp)
				w.writeString(100, m.Target)
			}); err != nil {
				ctx.Logger().Error("RelaySig: verification failed", "msg", "MsgBlockUser", "err", err.Error())
				return ctx, err
			}
		case *coretypes.MsgUnblockUser:
			if m.Authority == govAuthority {
				continue
			}
			if err := validateEnvelopeTimestamp(ctx, m.EnvelopeTimestamp, maxAge); err != nil {
				ctx.Logger().Error("RelaySig: timestamp validation failed", "msg", "MsgUnblockUser", "err", err.Error())
				return ctx, err
			}
			if err := verifyRelaySignature("MsgUnblockUser", m.EnvelopePubkey, m.EnvelopeSignature, func(w *canonWriter) {
				w.writeBytes(2, m.EnvelopePubkey)
				w.writeBytes(3, m.EnvelopeBlockHash)
				w.writeUvarint(4, m.EnvelopeDifficulty)
				w.writeUvarint(5, m.EnvelopePow)
				w.writeUvarint(6, m.EnvelopeTimestamp)
				w.writeString(100, m.Target)
			}); err != nil {
				ctx.Logger().Error("RelaySig: verification failed", "msg", "MsgUnblockUser", "err", err.Error())
				return ctx, err
			}
		case *coretypes.MsgDelete:
			if m.Authority == govAuthority {
				continue // Skip validation for governance
			}
			if err := validateEnvelopeTimestamp(ctx, m.EnvelopeTimestamp, maxAge); err != nil {
				ctx.Logger().Error("RelaySig: timestamp validation failed", "msg", "MsgDelete", "err", err.Error())
				return ctx, err
			}
			if err := verifyRelaySignature("MsgDelete", m.EnvelopePubkey, m.EnvelopeSignature, func(w *canonWriter) {
				w.writeBytes(2, m.EnvelopePubkey)
				w.writeBytes(3, m.EnvelopeBlockHash)
				w.writeUvarint(4, m.EnvelopeDifficulty)
				w.writeUvarint(5, m.EnvelopePow)
				w.writeUvarint(6, m.EnvelopeTimestamp)
				w.writeString(100, m.Target)
			}); err != nil {
				ctx.Logger().Error("RelaySig: verification failed", "msg", "MsgDelete", "err", err.Error())
				return ctx, err
			}
		case *coretypes.MsgSendTokens:
			if m.Authority == govAuthority {
				continue // Skip validation for governance
			}
			if err := validateEnvelopeTimestamp(ctx, m.EnvelopeTimestamp, maxAge); err != nil {
				ctx.Logger().Error("RelaySig: timestamp validation failed", "msg", "MsgSendTokens", "err", err.Error())
				return ctx, err
			}
			if err := verifyRelaySignature("MsgSendTokens", m.EnvelopePubkey, m.EnvelopeSignature, func(w *canonWriter) {
				w.writeBytes(2, m.EnvelopePubkey)
				w.writeBytes(3, m.EnvelopeBlockHash)
				w.writeUvarint(4, m.EnvelopeDifficulty)
				w.writeUvarint(5, m.EnvelopePow)
				w.writeUvarint(6, m.EnvelopeTimestamp)
				w.writeString(100, m.Sender)
				w.writeString(101, m.Target)
				w.writeUvarint(102, m.Amount)
			}); err != nil {
				ctx.Logger().Error("RelaySig: verification failed", "msg", "MsgSendTokens", "err", err.Error())
				return ctx, err
			}
		case *coretypes.MsgEdit:
			if m.Authority == govAuthority {
				continue // Skip validation for governance
			}
			if err := validateEnvelopeTimestamp(ctx, m.EnvelopeTimestamp, maxAge); err != nil {
				ctx.Logger().Error("RelaySig: timestamp validation failed", "msg", "MsgEdit", "err", err.Error())
				return ctx, err
			}
			if err := verifyRelaySignature("MsgEdit", m.EnvelopePubkey, m.EnvelopeSignature, func(w *canonWriter) {
				w.writeBytes(2, m.EnvelopePubkey)
				w.writeBytes(3, m.EnvelopeBlockHash)
				w.writeUvarint(4, m.EnvelopeDifficulty)
				w.writeUvarint(5, m.EnvelopePow)
				w.writeUvarint(6, m.EnvelopeTimestamp)
				w.writeString(100, m.Target)
				w.writeString(101, m.Topic)
				w.writeString(102, m.Title)
				w.writeString(103, m.Content)
				w.writeString(104, m.Tag)
				w.writeString(105, m.Override)
			}); err != nil {
				ctx.Logger().Error("RelaySig: verification failed", "msg", "MsgEdit", "err", err.Error())
				return ctx, err
			}
		case *coretypes.MsgSetLevel:
			if m.Authority == govAuthority {
				continue // Skip validation for governance
			}
			if err := validateEnvelopeTimestamp(ctx, m.EnvelopeTimestamp, maxAge); err != nil {
				ctx.Logger().Error("RelaySig: timestamp validation failed", "msg", "MsgSetLevel", "err", err.Error())
				return ctx, err
			}
			if err := verifyRelaySignature("MsgSetLevel", m.EnvelopePubkey, m.EnvelopeSignature, func(w *canonWriter) {
				w.writeBytes(2, m.EnvelopePubkey)
				w.writeBytes(3, m.EnvelopeBlockHash)
				w.writeUvarint(4, m.EnvelopeDifficulty)
				w.writeUvarint(5, m.EnvelopePow)
				w.writeUvarint(6, m.EnvelopeTimestamp)
				w.writeString(100, m.Target)
				w.writeUvarint(101, uint64(uint32(m.Level)))
			}); err != nil {
				ctx.Logger().Error("RelaySig: verification failed", "msg", "MsgSetLevel", "err", err.Error())
				return ctx, err
			}
		case *coretypes.MsgUpgradeLevel:
			if m.Authority == govAuthority {
				continue // Skip validation for governance
			}
			if err := validateEnvelopeTimestamp(ctx, m.EnvelopeTimestamp, maxAge); err != nil {
				ctx.Logger().Error("RelaySig: timestamp validation failed", "msg", "MsgUpgradeLevel", "err", err.Error())
				return ctx, err
			}
			if err := verifyRelaySignature("MsgUpgradeLevel", m.EnvelopePubkey, m.EnvelopeSignature, func(w *canonWriter) {
				w.writeBytes(2, m.EnvelopePubkey)
				w.writeBytes(3, m.EnvelopeBlockHash)
				w.writeUvarint(4, m.EnvelopeDifficulty)
				w.writeUvarint(5, m.EnvelopePow)
				w.writeUvarint(6, m.EnvelopeTimestamp)
				w.writeUvarint(100, uint64(uint32(m.Level)))
			}); err != nil {
				ctx.Logger().Error("RelaySig: verification failed", "msg", "MsgUpgradeLevel", "err", err.Error())
				return ctx, err
			}
		case *coretypes.MsgSetAutoRenewal:
			if m.Authority == govAuthority {
				continue // Skip validation for governance
			}
			if err := validateEnvelopeTimestamp(ctx, m.EnvelopeTimestamp, maxAge); err != nil {
				ctx.Logger().Error("RelaySig: timestamp validation failed", "msg", "MsgSetAutoRenewal", "err", err.Error())
				return ctx, err
			}
			if err := verifyRelaySignature("MsgSetAutoRenewal", m.EnvelopePubkey, m.EnvelopeSignature, func(w *canonWriter) {
				w.writeBytes(2, m.EnvelopePubkey)
				w.writeBytes(3, m.EnvelopeBlockHash)
				w.writeUvarint(4, m.EnvelopeDifficulty)
				w.writeUvarint(5, m.EnvelopePow)
				w.writeUvarint(6, m.EnvelopeTimestamp)
				if m.AutoRenew {
					w.writeUvarint(100, 1)
				} else {
					w.writeUvarint(100, 0)
				}
			}); err != nil {
				ctx.Logger().Error("RelaySig: verification failed", "msg", "MsgSetAutoRenewal", "err", err.Error())
				return ctx, err
			}
		case *coretypes.MsgBridgeBurn:
			if m.Authority == govAuthority {
				continue // Skip validation for governance
			}
			if err := validateEnvelopeTimestamp(ctx, m.EnvelopeTimestamp, maxAge); err != nil {
				ctx.Logger().Error("RelaySig: timestamp validation failed", "msg", "MsgBridgeBurn", "err", err.Error())
				return ctx, err
			}
			if err := verifyRelaySignature("MsgBridgeBurn", m.EnvelopePubkey, m.EnvelopeSignature, func(w *canonWriter) {
				w.writeBytes(2, m.EnvelopePubkey)
				w.writeBytes(3, m.EnvelopeBlockHash)
				w.writeUvarint(4, m.EnvelopeDifficulty)
				w.writeUvarint(5, m.EnvelopePow)
				w.writeUvarint(6, m.EnvelopeTimestamp)
				w.writeString(100, m.DestinationChain)
				w.writeString(101, m.DestinationAddress)
				w.writeUvarint(102, m.Amount)
			}); err != nil {
				ctx.Logger().Error("RelaySig: verification failed", "msg", "MsgBridgeBurn", "err", err.Error())
				return ctx, err
			}
		// Note: MsgBridgeAttest does NOT use envelope - it's signed directly by validators
		default:
			// ignore others
		}
	}
	return next(ctx, tx, simulate)
}

type canonWriter struct{ buf []byte }

func newCanonWriter(prefix string) *canonWriter {
	c := &canonWriter{buf: make([]byte, 0, 256)}
	c.buf = append(c.buf, []byte("mirage.core.v1:")...)
	c.buf = append(c.buf, []byte(prefix)...)
	c.buf = append(c.buf, 0x00)
	return c
}

func (w *canonWriter) writeTag(tag byte) { w.buf = append(w.buf, tag) }

func (w *canonWriter) writeUvarint(tag byte, v uint64) {
	w.writeTag(tag)
	var tmp [10]byte
	n := binary.PutUvarint(tmp[:], v)
	w.buf = append(w.buf, tmp[:n]...)
}

func (w *canonWriter) writeString(tag byte, s string) {
	w.writeTag(tag)
	var tmp [10]byte
	n := binary.PutUvarint(tmp[:], uint64(len(s)))
	w.buf = append(w.buf, tmp[:n]...)
	w.buf = append(w.buf, []byte(s)...)
}

func (w *canonWriter) writeBytes(tag byte, b []byte) {
	w.writeTag(tag)
	var tmp [10]byte
	n := binary.PutUvarint(tmp[:], uint64(len(b)))
	w.buf = append(w.buf, tmp[:n]...)
	w.buf = append(w.buf, b...)
}

func (w *canonWriter) writeRepeatedString(tag byte, ss []string) {
	for _, s := range ss {
		w.writeString(tag, s)
	}
}

func verifyRelaySignature(msgName string, pubkey []byte, sig []byte, fill func(*canonWriter)) error {
	if len(pubkey) != 33 || len(sig) != 64 {
		return fmt.Errorf("invalid relay fields")
	}
	w := newCanonWriter(msgName)
	fill(w)
	_ = sha256.Sum256(w.buf) // keep for reference; VerifySignature hashes internally
	pk := secp.PubKey{Key: pubkey}
	if ok := pk.VerifySignature(w.buf, sig); !ok {
		return fmt.Errorf("invalid relay signature")
	}
	return nil
}

// validateEnvelopeTimestamp checks that envelope_timestamp is not too old or in the future.
// timestampMs is the envelope timestamp in milliseconds.
// maxAgeSec is the maximum allowed age in seconds.
func validateEnvelopeTimestamp(ctx sdk.Context, timestampMs uint64, maxAgeSec uint64) error {
	if timestampMs == 0 {
		return fmt.Errorf("envelope_timestamp is required")
	}
	txTime := time.UnixMilli(int64(timestampMs))
	blockTime := ctx.BlockTime()
	age := blockTime.Sub(txTime)
	maxAge := time.Duration(maxAgeSec) * time.Second
	if age > maxAge {
		return fmt.Errorf("envelope_timestamp too old: age=%s, max=%s (tx_time=%s, block_time=%s)", age, maxAge, txTime, blockTime)
	}
	// Allow a small window for envelope_timestamp to be slightly ahead of block_time.
	// Derive this from max_envelope_age so it is tunable via Params (governance).
	// We cap it to keep replay protection meaningful.
	maxFutureSkew := maxAge / 2 // e.g., 30s when max_age=60s
	if maxFutureSkew < 5*time.Second {
		maxFutureSkew = 5 * time.Second
	}
	if maxFutureSkew > 30*time.Second {
		maxFutureSkew = 30 * time.Second
	}
	if age < -maxFutureSkew {
		return fmt.Errorf("envelope_timestamp in future: age=%s (tx_time=%s, block_time=%s)", age, txTime, blockTime)
	}
	return nil
}

// RelayGasFeeDecorator enforces min-gas-prices on CheckTx and deducts SDK fees on DeliverTx
// for relay transactions by deriving the fee payer from the embedded pubkey.
type RelayGasFeeDecorator struct {
	BankKeeper bankkeeper.Keeper
}

func (d RelayGasFeeDecorator) AnteHandle(ctx sdk.Context, tx sdk.Tx, simulate bool, next sdk.AnteHandler) (sdk.Context, error) {
	ftx, ok := tx.(sdk.FeeTx)
	if !ok {
		return ctx, fmt.Errorf("relay fee: expected FeeTx")
	}

	// Compute required fees from min gas prices only for Prepare/Process/Finalize; allow CheckTx to rely on node's mempool min-gas-prices
	minPrices := ctx.MinGasPrices()
	if !minPrices.IsZero() {
		required := sdk.NewCoins()
		gas := ftx.GetGas()
		for _, gp := range minPrices {
			amt := gp.Amount.MulInt64(int64(gas)).Ceil().TruncateInt()
			if amt.IsPositive() {
				required = required.Add(sdk.NewCoin(gp.Denom, amt))
			}
		}
		offered := ftx.GetFee()
		// In CheckTx, Comet’s mempool enforces min-gas-prices; we don’t need to replicate it here.
		if ctx.ExecMode() != sdk.ExecModeCheck && !offered.IsAnyGTE(required) {
			ctx.Logger().Warn("relay insufficient fee", "offered", offered.String(), "required", required.String(), "min_gas_prices", minPrices.String(), "gas", gas)
			return ctx, fmt.Errorf("insufficient fee: got %s required any >= %s (minGasPrices=%s, gas=%d)", offered, required, minPrices, gas)
		}

		// Early reject in CheckTx if payer cannot cover offered fees
		if ctx.IsCheckTx() && !offered.IsZero() {
			// resolve payer (explicit fee.payer preferred, then outer signer)
			var payerAddr sdk.AccAddress
			if payerBz := ftx.FeePayer(); len(payerBz) > 0 {
				payerAddr = sdk.AccAddress(payerBz)
			}
			if payerAddr == nil {
				if svtx, ok := tx.(authsigning.SigVerifiableTx); ok {
					if pubs, err := svtx.GetPubKeys(); err == nil {
						if len(pubs) > 0 && pubs[0] != nil {
							if bz := pubs[0].Address(); len(bz) > 0 {
								payerAddr = sdk.AccAddress(bz)
							}
						}
					}
				}
			}
			if payerAddr == nil {
				ctx.Logger().Warn("relay fee payer not resolvable in CheckTx (require fee.payer or outer signer)")
				return ctx, fmt.Errorf("relay fee: missing payer (require fee.payer or outer signer)")
			}
			// check each offered coin against balance
			for _, c := range offered {
				bal := d.BankKeeper.GetBalance(ctx, payerAddr, c.Denom).Amount
				if bal.LT(c.Amount) {
					ctx.Logger().Warn("relay fee payer insufficient funds", "payer", payerAddr.String(), "denom", c.Denom, "need", c.Amount.String(), "bal", bal.String())
					return ctx, fmt.Errorf("insufficient funds: payer %s needs %s%s has %s%s", payerAddr.String(), c.Amount.String(), c.Denom, bal.String(), c.Denom)
				}
			}
		}
	}

	// Deduct fees during Finalize and Simulate (simulate for accurate gas estimation).
	// Do NOT deduct during Prepare/ProcessProposal.
	if ctx.ExecMode() == sdk.ExecModeFinalize || ctx.ExecMode() == sdk.ExecModeSimulate {
		payer := ""
		if payerBz := ftx.FeePayer(); len(payerBz) > 0 {
			payer = sdk.AccAddress(payerBz).String()
		}
		if payer == "" {
			if svtx, ok := tx.(authsigning.SigVerifiableTx); ok {
				if pubs, err := svtx.GetPubKeys(); err == nil {
					if len(pubs) > 0 && pubs[0] != nil {
						if bz := pubs[0].Address(); len(bz) > 0 {
							payer = sdk.AccAddress(bz).String()
						}
					}
				}
			}
		}
		if payer == "" {
			ctx.Logger().Warn("relay fee: unable to resolve fee payer")
			return ctx, fmt.Errorf("relay fee: unable to resolve fee payer")
		}
		fees := ftx.GetFee()
		if !fees.IsZero() {
			addr, err := sdk.AccAddressFromBech32(payer)
			if err != nil {
				ctx.Logger().Warn("relay invalid fee payer address", "err", err.Error())
				return ctx, fmt.Errorf("invalid fee payer address: %w", err)
			}
			if err := d.BankKeeper.SendCoinsFromAccountToModule(ctx, addr, authtypes.FeeCollectorName, fees); err != nil {
				ctx.Logger().Warn("relay fee deduction failed", "payer", payer, "fees", fees.String(), "err", err.Error())
				return ctx, fmt.Errorf("fee deduction failed: %w", err)
			}
			if ctx.ExecMode() == sdk.ExecModeSimulate {
				ctx.Logger().Debug("relay fee: simulated deduction", "payer", payer, "fees", fees.String())
			}
		}
	}

	return next(ctx, tx, simulate)
}
