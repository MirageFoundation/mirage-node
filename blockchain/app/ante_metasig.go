package app

import (
	"crypto/sha256"
	"encoding/binary"
	"fmt"
	"time"

	secp "github.com/cosmos/cosmos-sdk/crypto/keys/secp256k1"
	sdk "github.com/cosmos/cosmos-sdk/types"
	authtypes "github.com/cosmos/cosmos-sdk/x/auth/types"
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

	// v1.20.0: envelope_nonce is mandatory. Nonce==0 is rejected.
	// Nonce generation (for clients):
	//   nonce = (Date.now() * 1_000_000) ^ (rand32)
	//   Must be >0; for JS keep <=2^53-1. Include in signature.
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
			pubHash := sha256.Sum256(m.EnvelopePubkey)
			if m.EnvelopeNonce == 0 {
				return ctx, fmt.Errorf("envelope_nonce is required (must be >0)")
			}
			if d.Keeper.HasEnvelopeNonce(ctx, pubHash[:16], m.EnvelopeNonce) {
				return ctx, fmt.Errorf("envelope replay: nonce already used")
			}
			if err := verifyRelaySignature("MsgPost", m.EnvelopePubkey, m.EnvelopeSignature, func(w *canonWriter) {
				w.writeBytes(2, m.EnvelopePubkey)
				w.writeBytes(3, m.EnvelopeBlockHash)
				w.writeUvarint(4, m.EnvelopeDifficulty)
				w.writeUvarint(5, m.EnvelopePow)
				w.writeUvarint(6, m.EnvelopeTimestamp)
				w.writeUvarint(7, m.EnvelopeNonce)
				appendPostPayload(w, m)
			}); err != nil {
				ctx.Logger().Error("RelaySig: verification failed", "msg", "MsgPost", "err", err.Error())
				return ctx, err
			}
			nonceExpiry, err := envelopeNonceExpiryUnix(ctx, m.EnvelopeTimestamp, maxAge)
			if err != nil {
				return ctx, err
			}
			if err := d.Keeper.SetEnvelopeNonce(ctx, pubHash[:16], m.EnvelopeNonce, nonceExpiry); err != nil {
				ctx.Logger().Error("RelaySig: failed to record nonce", "msg", "MsgPost", "err", err.Error())
				return ctx, fmt.Errorf("failed to record nonce: %w", err)
			}
		case *coretypes.MsgVote:
			if m.Authority == govAuthority {
				continue // Skip validation for governance
			}
			if err := validateEnvelopeTimestamp(ctx, m.EnvelopeTimestamp, maxAge); err != nil {
				ctx.Logger().Error("RelaySig: timestamp validation failed", "msg", "MsgVote", "err", err.Error())
				return ctx, err
			}
			pubHash := sha256.Sum256(m.EnvelopePubkey)
			if m.EnvelopeNonce == 0 {
				return ctx, fmt.Errorf("envelope_nonce is required (must be >0)")
			}
			if d.Keeper.HasEnvelopeNonce(ctx, pubHash[:16], m.EnvelopeNonce) {
				return ctx, fmt.Errorf("envelope replay: nonce already used")
			}
			if err := verifyRelaySignature("MsgVote", m.EnvelopePubkey, m.EnvelopeSignature, func(w *canonWriter) {
				w.writeBytes(2, m.EnvelopePubkey)
				w.writeBytes(3, m.EnvelopeBlockHash)
				w.writeUvarint(4, m.EnvelopeDifficulty)
				w.writeUvarint(5, m.EnvelopePow)
				w.writeUvarint(6, m.EnvelopeTimestamp)
				w.writeUvarint(7, m.EnvelopeNonce)
				w.writeString(100, m.Target)
				w.writeUvarint(101, uint64(uint32(m.Direction)))
			}); err != nil {
				ctx.Logger().Error("RelaySig: verification failed", "msg", "MsgVote", "err", err.Error())
				return ctx, err
			}
			nonceExpiry, err := envelopeNonceExpiryUnix(ctx, m.EnvelopeTimestamp, maxAge)
			if err != nil {
				return ctx, err
			}
			if err := d.Keeper.SetEnvelopeNonce(ctx, pubHash[:16], m.EnvelopeNonce, nonceExpiry); err != nil {
				ctx.Logger().Error("RelaySig: failed to record nonce", "msg", "MsgVote", "err", err.Error())
				return ctx, fmt.Errorf("failed to record nonce: %w", err)
			}
		case *coretypes.MsgSetUsername:
			if m.Authority == govAuthority {
				continue // Skip validation for governance
			}
			if err := validateEnvelopeTimestamp(ctx, m.EnvelopeTimestamp, maxAge); err != nil {
				ctx.Logger().Error("RelaySig: timestamp validation failed", "msg", "MsgSetUsername", "err", err.Error())
				return ctx, err
			}
			pubHash := sha256.Sum256(m.EnvelopePubkey)
			if m.EnvelopeNonce == 0 {
				return ctx, fmt.Errorf("envelope_nonce is required (must be >0)")
			}
			if d.Keeper.HasEnvelopeNonce(ctx, pubHash[:16], m.EnvelopeNonce) {
				return ctx, fmt.Errorf("envelope replay: nonce already used")
			}
			if err := verifyRelaySignature("MsgSetUsername", m.EnvelopePubkey, m.EnvelopeSignature, func(w *canonWriter) {
				w.writeBytes(2, m.EnvelopePubkey)
				w.writeBytes(3, m.EnvelopeBlockHash)
				w.writeUvarint(4, m.EnvelopeDifficulty)
				w.writeUvarint(5, m.EnvelopePow)
				w.writeUvarint(6, m.EnvelopeTimestamp)
				w.writeUvarint(7, m.EnvelopeNonce)
				w.writeString(100, m.Target)
				w.writeString(101, m.Username)
			}); err != nil {
				ctx.Logger().Error("RelaySig: verification failed", "msg", "MsgSetUsername", "err", err.Error())
				return ctx, err
			}
			nonceExpiry, err := envelopeNonceExpiryUnix(ctx, m.EnvelopeTimestamp, maxAge)
			if err != nil {
				return ctx, err
			}
			if err := d.Keeper.SetEnvelopeNonce(ctx, pubHash[:16], m.EnvelopeNonce, nonceExpiry); err != nil {
				ctx.Logger().Error("RelaySig: failed to record nonce", "msg", "MsgSetUsername", "err", err.Error())
				return ctx, fmt.Errorf("failed to record nonce: %w", err)
			}
		case *coretypes.MsgSetBiography:
			if m.Authority == govAuthority {
				continue
			}
			if err := validateEnvelopeTimestamp(ctx, m.EnvelopeTimestamp, maxAge); err != nil {
				ctx.Logger().Error("RelaySig: timestamp validation failed", "msg", "MsgSetBiography", "err", err.Error())
				return ctx, err
			}
			pubHash := sha256.Sum256(m.EnvelopePubkey)
			if m.EnvelopeNonce == 0 {
				return ctx, fmt.Errorf("envelope_nonce is required (must be >0)")
			}
			if d.Keeper.HasEnvelopeNonce(ctx, pubHash[:16], m.EnvelopeNonce) {
				return ctx, fmt.Errorf("envelope replay: nonce already used")
			}
			if err := verifyRelaySignature("MsgSetBiography", m.EnvelopePubkey, m.EnvelopeSignature, func(w *canonWriter) {
				w.writeBytes(2, m.EnvelopePubkey)
				w.writeBytes(3, m.EnvelopeBlockHash)
				w.writeUvarint(4, m.EnvelopeDifficulty)
				w.writeUvarint(5, m.EnvelopePow)
				w.writeUvarint(6, m.EnvelopeTimestamp)
				w.writeUvarint(7, m.EnvelopeNonce)
				w.writeString(100, m.Target)
				w.writeString(101, m.Biography)
			}); err != nil {
				ctx.Logger().Error("RelaySig: verification failed", "msg", "MsgSetBiography", "err", err.Error())
				return ctx, err
			}
			nonceExpiry, err := envelopeNonceExpiryUnix(ctx, m.EnvelopeTimestamp, maxAge)
			if err != nil {
				return ctx, err
			}
			if err := d.Keeper.SetEnvelopeNonce(ctx, pubHash[:16], m.EnvelopeNonce, nonceExpiry); err != nil {
				ctx.Logger().Error("RelaySig: failed to record nonce", "msg", "MsgSetBiography", "err", err.Error())
				return ctx, fmt.Errorf("failed to record nonce: %w", err)
			}
		case *coretypes.MsgFollowUser:
			if m.Authority == govAuthority {
				continue
			}
			if err := validateEnvelopeTimestamp(ctx, m.EnvelopeTimestamp, maxAge); err != nil {
				ctx.Logger().Error("RelaySig: timestamp validation failed", "msg", "MsgFollowUser", "err", err.Error())
				return ctx, err
			}
			pubHash := sha256.Sum256(m.EnvelopePubkey)
			if m.EnvelopeNonce == 0 {
				return ctx, fmt.Errorf("envelope_nonce is required (must be >0)")
			}
			if d.Keeper.HasEnvelopeNonce(ctx, pubHash[:16], m.EnvelopeNonce) {
				return ctx, fmt.Errorf("envelope replay: nonce already used")
			}
			if err := verifyRelaySignature("MsgFollowUser", m.EnvelopePubkey, m.EnvelopeSignature, func(w *canonWriter) {
				w.writeBytes(2, m.EnvelopePubkey)
				w.writeBytes(3, m.EnvelopeBlockHash)
				w.writeUvarint(4, m.EnvelopeDifficulty)
				w.writeUvarint(5, m.EnvelopePow)
				w.writeUvarint(6, m.EnvelopeTimestamp)
				w.writeUvarint(7, m.EnvelopeNonce)
				w.writeString(100, m.Target)
				w.writeString(101, m.User)
			}); err != nil {
				ctx.Logger().Error("RelaySig: verification failed", "msg", "MsgFollowUser", "err", err.Error())
				return ctx, err
			}
			nonceExpiry, err := envelopeNonceExpiryUnix(ctx, m.EnvelopeTimestamp, maxAge)
			if err != nil {
				return ctx, err
			}
			if err := d.Keeper.SetEnvelopeNonce(ctx, pubHash[:16], m.EnvelopeNonce, nonceExpiry); err != nil {
				ctx.Logger().Error("RelaySig: failed to record nonce", "msg", "MsgFollowUser", "err", err.Error())
				return ctx, fmt.Errorf("failed to record nonce: %w", err)
			}
		case *coretypes.MsgUnfollowUser:
			if m.Authority == govAuthority {
				continue
			}
			if err := validateEnvelopeTimestamp(ctx, m.EnvelopeTimestamp, maxAge); err != nil {
				ctx.Logger().Error("RelaySig: timestamp validation failed", "msg", "MsgUnfollowUser", "err", err.Error())
				return ctx, err
			}
			pubHash := sha256.Sum256(m.EnvelopePubkey)
			if m.EnvelopeNonce == 0 {
				return ctx, fmt.Errorf("envelope_nonce is required (must be >0)")
			}
			if d.Keeper.HasEnvelopeNonce(ctx, pubHash[:16], m.EnvelopeNonce) {
				return ctx, fmt.Errorf("envelope replay: nonce already used")
			}
			if err := verifyRelaySignature("MsgUnfollowUser", m.EnvelopePubkey, m.EnvelopeSignature, func(w *canonWriter) {
				w.writeBytes(2, m.EnvelopePubkey)
				w.writeBytes(3, m.EnvelopeBlockHash)
				w.writeUvarint(4, m.EnvelopeDifficulty)
				w.writeUvarint(5, m.EnvelopePow)
				w.writeUvarint(6, m.EnvelopeTimestamp)
				w.writeUvarint(7, m.EnvelopeNonce)
				w.writeString(100, m.Target)
				w.writeString(101, m.User)
			}); err != nil {
				ctx.Logger().Error("RelaySig: verification failed", "msg", "MsgUnfollowUser", "err", err.Error())
				return ctx, err
			}
			nonceExpiry, err := envelopeNonceExpiryUnix(ctx, m.EnvelopeTimestamp, maxAge)
			if err != nil {
				return ctx, err
			}
			if err := d.Keeper.SetEnvelopeNonce(ctx, pubHash[:16], m.EnvelopeNonce, nonceExpiry); err != nil {
				ctx.Logger().Error("RelaySig: failed to record nonce", "msg", "MsgUnfollowUser", "err", err.Error())
				return ctx, fmt.Errorf("failed to record nonce: %w", err)
			}
		case *coretypes.MsgFollowTopic:
			if err := d.authEnvelope(ctx, govAuthority, maxAge, "MsgFollowTopic", m.Authority, m.EnvelopePubkey, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow, m.EnvelopeTimestamp, m.EnvelopeNonce, m.EnvelopeSignature, func(w *canonWriter) {
				w.writeString(100, m.Target)
				w.writeString(101, m.Topic)
			}); err != nil {
				return ctx, err
			}
		case *coretypes.MsgUnfollowTopic:
			if err := d.authEnvelope(ctx, govAuthority, maxAge, "MsgUnfollowTopic", m.Authority, m.EnvelopePubkey, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow, m.EnvelopeTimestamp, m.EnvelopeNonce, m.EnvelopeSignature, func(w *canonWriter) {
				w.writeString(100, m.Target)
				w.writeString(101, m.Topic)
			}); err != nil {
				return ctx, err
			}
		case *coretypes.MsgBlockTopic:
			if err := d.authEnvelope(ctx, govAuthority, maxAge, "MsgBlockTopic", m.Authority, m.EnvelopePubkey, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow, m.EnvelopeTimestamp, m.EnvelopeNonce, m.EnvelopeSignature, func(w *canonWriter) {
				w.writeString(100, m.Target)
				w.writeString(101, m.Topic)
			}); err != nil {
				return ctx, err
			}
		case *coretypes.MsgUnblockTopic:
			if err := d.authEnvelope(ctx, govAuthority, maxAge, "MsgUnblockTopic", m.Authority, m.EnvelopePubkey, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow, m.EnvelopeTimestamp, m.EnvelopeNonce, m.EnvelopeSignature, func(w *canonWriter) {
				w.writeString(100, m.Target)
				w.writeString(101, m.Topic)
			}); err != nil {
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
			pubHash := sha256.Sum256(m.EnvelopePubkey)
			if m.EnvelopeNonce == 0 {
				return ctx, fmt.Errorf("envelope_nonce is required (must be >0)")
			}
			if d.Keeper.HasEnvelopeNonce(ctx, pubHash[:16], m.EnvelopeNonce) {
				return ctx, fmt.Errorf("envelope replay: nonce already used")
			}
			if err := verifyRelaySignature("MsgBlockPost", m.EnvelopePubkey, m.EnvelopeSignature, func(w *canonWriter) {
				w.writeBytes(2, m.EnvelopePubkey)
				w.writeBytes(3, m.EnvelopeBlockHash)
				w.writeUvarint(4, m.EnvelopeDifficulty)
				w.writeUvarint(5, m.EnvelopePow)
				w.writeUvarint(6, m.EnvelopeTimestamp)
				w.writeUvarint(7, m.EnvelopeNonce)
				w.writeString(100, m.Target)
			}); err != nil {
				ctx.Logger().Error("RelaySig: verification failed", "msg", "MsgBlockPost", "err", err.Error())
				return ctx, err
			}
			nonceExpiry, err := envelopeNonceExpiryUnix(ctx, m.EnvelopeTimestamp, maxAge)
			if err != nil {
				return ctx, err
			}
			if err := d.Keeper.SetEnvelopeNonce(ctx, pubHash[:16], m.EnvelopeNonce, nonceExpiry); err != nil {
				ctx.Logger().Error("RelaySig: failed to record nonce", "msg", "MsgBlockPost", "err", err.Error())
				return ctx, fmt.Errorf("failed to record nonce: %w", err)
			}
		case *coretypes.MsgUnblockPost:
			if m.Authority == govAuthority {
				continue
			}
			if err := validateEnvelopeTimestamp(ctx, m.EnvelopeTimestamp, maxAge); err != nil {
				ctx.Logger().Error("RelaySig: timestamp validation failed", "msg", "MsgUnblockPost", "err", err.Error())
				return ctx, err
			}
			pubHash := sha256.Sum256(m.EnvelopePubkey)
			if m.EnvelopeNonce == 0 {
				return ctx, fmt.Errorf("envelope_nonce is required (must be >0)")
			}
			if d.Keeper.HasEnvelopeNonce(ctx, pubHash[:16], m.EnvelopeNonce) {
				return ctx, fmt.Errorf("envelope replay: nonce already used")
			}
			if err := verifyRelaySignature("MsgUnblockPost", m.EnvelopePubkey, m.EnvelopeSignature, func(w *canonWriter) {
				w.writeBytes(2, m.EnvelopePubkey)
				w.writeBytes(3, m.EnvelopeBlockHash)
				w.writeUvarint(4, m.EnvelopeDifficulty)
				w.writeUvarint(5, m.EnvelopePow)
				w.writeUvarint(6, m.EnvelopeTimestamp)
				w.writeUvarint(7, m.EnvelopeNonce)
				w.writeString(100, m.Target)
			}); err != nil {
				ctx.Logger().Error("RelaySig: verification failed", "msg", "MsgUnblockPost", "err", err.Error())
				return ctx, err
			}
			nonceExpiry, err := envelopeNonceExpiryUnix(ctx, m.EnvelopeTimestamp, maxAge)
			if err != nil {
				return ctx, err
			}
			if err := d.Keeper.SetEnvelopeNonce(ctx, pubHash[:16], m.EnvelopeNonce, nonceExpiry); err != nil {
				ctx.Logger().Error("RelaySig: failed to record nonce", "msg", "MsgUnblockPost", "err", err.Error())
				return ctx, fmt.Errorf("failed to record nonce: %w", err)
			}
		case *coretypes.MsgBlockUser:
			if m.Authority == govAuthority {
				continue
			}
			if err := validateEnvelopeTimestamp(ctx, m.EnvelopeTimestamp, maxAge); err != nil {
				ctx.Logger().Error("RelaySig: timestamp validation failed", "msg", "MsgBlockUser", "err", err.Error())
				return ctx, err
			}
			pubHash := sha256.Sum256(m.EnvelopePubkey)
			if m.EnvelopeNonce == 0 {
				return ctx, fmt.Errorf("envelope_nonce is required (must be >0)")
			}
			if d.Keeper.HasEnvelopeNonce(ctx, pubHash[:16], m.EnvelopeNonce) {
				return ctx, fmt.Errorf("envelope replay: nonce already used")
			}
			if err := verifyRelaySignature("MsgBlockUser", m.EnvelopePubkey, m.EnvelopeSignature, func(w *canonWriter) {
				w.writeBytes(2, m.EnvelopePubkey)
				w.writeBytes(3, m.EnvelopeBlockHash)
				w.writeUvarint(4, m.EnvelopeDifficulty)
				w.writeUvarint(5, m.EnvelopePow)
				w.writeUvarint(6, m.EnvelopeTimestamp)
				w.writeUvarint(7, m.EnvelopeNonce)
				w.writeString(100, m.Target)
			}); err != nil {
				ctx.Logger().Error("RelaySig: verification failed", "msg", "MsgBlockUser", "err", err.Error())
				return ctx, err
			}
			nonceExpiry, err := envelopeNonceExpiryUnix(ctx, m.EnvelopeTimestamp, maxAge)
			if err != nil {
				return ctx, err
			}
			if err := d.Keeper.SetEnvelopeNonce(ctx, pubHash[:16], m.EnvelopeNonce, nonceExpiry); err != nil {
				ctx.Logger().Error("RelaySig: failed to record nonce", "msg", "MsgBlockUser", "err", err.Error())
				return ctx, fmt.Errorf("failed to record nonce: %w", err)
			}
		case *coretypes.MsgUnblockUser:
			if m.Authority == govAuthority {
				continue
			}
			if err := validateEnvelopeTimestamp(ctx, m.EnvelopeTimestamp, maxAge); err != nil {
				ctx.Logger().Error("RelaySig: timestamp validation failed", "msg", "MsgUnblockUser", "err", err.Error())
				return ctx, err
			}
			pubHash := sha256.Sum256(m.EnvelopePubkey)
			if m.EnvelopeNonce == 0 {
				return ctx, fmt.Errorf("envelope_nonce is required (must be >0)")
			}
			if d.Keeper.HasEnvelopeNonce(ctx, pubHash[:16], m.EnvelopeNonce) {
				return ctx, fmt.Errorf("envelope replay: nonce already used")
			}
			if err := verifyRelaySignature("MsgUnblockUser", m.EnvelopePubkey, m.EnvelopeSignature, func(w *canonWriter) {
				w.writeBytes(2, m.EnvelopePubkey)
				w.writeBytes(3, m.EnvelopeBlockHash)
				w.writeUvarint(4, m.EnvelopeDifficulty)
				w.writeUvarint(5, m.EnvelopePow)
				w.writeUvarint(6, m.EnvelopeTimestamp)
				w.writeUvarint(7, m.EnvelopeNonce)
				w.writeString(100, m.Target)
			}); err != nil {
				ctx.Logger().Error("RelaySig: verification failed", "msg", "MsgUnblockUser", "err", err.Error())
				return ctx, err
			}
			nonceExpiry, err := envelopeNonceExpiryUnix(ctx, m.EnvelopeTimestamp, maxAge)
			if err != nil {
				return ctx, err
			}
			if err := d.Keeper.SetEnvelopeNonce(ctx, pubHash[:16], m.EnvelopeNonce, nonceExpiry); err != nil {
				ctx.Logger().Error("RelaySig: failed to record nonce", "msg", "MsgUnblockUser", "err", err.Error())
				return ctx, fmt.Errorf("failed to record nonce: %w", err)
			}
		case *coretypes.MsgDelete:
			if m.Authority == govAuthority {
				continue // Skip validation for governance
			}
			if err := validateEnvelopeTimestamp(ctx, m.EnvelopeTimestamp, maxAge); err != nil {
				ctx.Logger().Error("RelaySig: timestamp validation failed", "msg", "MsgDelete", "err", err.Error())
				return ctx, err
			}
			pubHash := sha256.Sum256(m.EnvelopePubkey)
			if m.EnvelopeNonce == 0 {
				return ctx, fmt.Errorf("envelope_nonce is required (must be >0)")
			}
			if d.Keeper.HasEnvelopeNonce(ctx, pubHash[:16], m.EnvelopeNonce) {
				return ctx, fmt.Errorf("envelope replay: nonce already used")
			}
			if err := verifyRelaySignature("MsgDelete", m.EnvelopePubkey, m.EnvelopeSignature, func(w *canonWriter) {
				w.writeBytes(2, m.EnvelopePubkey)
				w.writeBytes(3, m.EnvelopeBlockHash)
				w.writeUvarint(4, m.EnvelopeDifficulty)
				w.writeUvarint(5, m.EnvelopePow)
				w.writeUvarint(6, m.EnvelopeTimestamp)
				w.writeUvarint(7, m.EnvelopeNonce)
				w.writeString(100, m.Target)
			}); err != nil {
				ctx.Logger().Error("RelaySig: verification failed", "msg", "MsgDelete", "err", err.Error())
				return ctx, err
			}
			nonceExpiry, err := envelopeNonceExpiryUnix(ctx, m.EnvelopeTimestamp, maxAge)
			if err != nil {
				return ctx, err
			}
			if err := d.Keeper.SetEnvelopeNonce(ctx, pubHash[:16], m.EnvelopeNonce, nonceExpiry); err != nil {
				ctx.Logger().Error("RelaySig: failed to record nonce", "msg", "MsgDelete", "err", err.Error())
				return ctx, fmt.Errorf("failed to record nonce: %w", err)
			}
		case *coretypes.MsgDeleteUser:
			if m.Authority == govAuthority {
				continue
			}
			if err := validateEnvelopeTimestamp(ctx, m.EnvelopeTimestamp, maxAge); err != nil {
				ctx.Logger().Error("RelaySig: timestamp validation failed", "msg", "MsgDeleteUser", "err", err.Error())
				return ctx, err
			}
			pubHash := sha256.Sum256(m.EnvelopePubkey)
			if m.EnvelopeNonce == 0 {
				return ctx, fmt.Errorf("envelope_nonce is required (must be >0)")
			}
			if d.Keeper.HasEnvelopeNonce(ctx, pubHash[:16], m.EnvelopeNonce) {
				return ctx, fmt.Errorf("envelope replay: nonce already used")
			}
			if err := verifyRelaySignature("MsgDeleteUser", m.EnvelopePubkey, m.EnvelopeSignature, func(w *canonWriter) {
				w.writeBytes(2, m.EnvelopePubkey)
				w.writeBytes(3, m.EnvelopeBlockHash)
				w.writeUvarint(4, m.EnvelopeDifficulty)
				w.writeUvarint(5, m.EnvelopePow)
				w.writeUvarint(6, m.EnvelopeTimestamp)
				w.writeUvarint(7, m.EnvelopeNonce)
				w.writeString(100, m.Target)
			}); err != nil {
				ctx.Logger().Error("RelaySig: verification failed", "msg", "MsgDeleteUser", "err", err.Error())
				return ctx, err
			}
			nonceExpiry, err := envelopeNonceExpiryUnix(ctx, m.EnvelopeTimestamp, maxAge)
			if err != nil {
				return ctx, err
			}
			if err := d.Keeper.SetEnvelopeNonce(ctx, pubHash[:16], m.EnvelopeNonce, nonceExpiry); err != nil {
				ctx.Logger().Error("RelaySig: failed to record nonce", "msg", "MsgDeleteUser", "err", err.Error())
				return ctx, fmt.Errorf("failed to record nonce: %w", err)
			}
		case *coretypes.MsgSendTokens:
			if m.Authority == govAuthority {
				continue // Skip validation for governance
			}
			if err := validateEnvelopeTimestamp(ctx, m.EnvelopeTimestamp, maxAge); err != nil {
				ctx.Logger().Error("RelaySig: timestamp validation failed", "msg", "MsgSendTokens", "err", err.Error())
				return ctx, err
			}
			pubHash := sha256.Sum256(m.EnvelopePubkey)
			if m.EnvelopeNonce == 0 {
				return ctx, fmt.Errorf("envelope_nonce is required (must be >0)")
			}
			if d.Keeper.HasEnvelopeNonce(ctx, pubHash[:16], m.EnvelopeNonce) {
				return ctx, fmt.Errorf("envelope replay: nonce already used")
			}
			if err := verifyRelaySignature("MsgSendTokens", m.EnvelopePubkey, m.EnvelopeSignature, func(w *canonWriter) {
				w.writeBytes(2, m.EnvelopePubkey)
				w.writeBytes(3, m.EnvelopeBlockHash)
				w.writeUvarint(4, m.EnvelopeDifficulty)
				w.writeUvarint(5, m.EnvelopePow)
				w.writeUvarint(6, m.EnvelopeTimestamp)
				w.writeUvarint(7, m.EnvelopeNonce)
				w.writeString(100, m.Sender)
				w.writeString(101, m.Target)
				w.writeUvarint(102, m.Amount)
			}); err != nil {
				ctx.Logger().Error("RelaySig: verification failed", "msg", "MsgSendTokens", "err", err.Error())
				return ctx, err
			}
			nonceExpiry, err := envelopeNonceExpiryUnix(ctx, m.EnvelopeTimestamp, maxAge)
			if err != nil {
				return ctx, err
			}
			if err := d.Keeper.SetEnvelopeNonce(ctx, pubHash[:16], m.EnvelopeNonce, nonceExpiry); err != nil {
				ctx.Logger().Error("RelaySig: failed to record nonce", "msg", "MsgSendTokens", "err", err.Error())
				return ctx, fmt.Errorf("failed to record nonce: %w", err)
			}
		case *coretypes.MsgEdit:
			if m.Authority == govAuthority {
				continue // Skip validation for governance
			}
			if err := validateEnvelopeTimestamp(ctx, m.EnvelopeTimestamp, maxAge); err != nil {
				ctx.Logger().Error("RelaySig: timestamp validation failed", "msg", "MsgEdit", "err", err.Error())
				return ctx, err
			}
			pubHash := sha256.Sum256(m.EnvelopePubkey)
			if m.EnvelopeNonce == 0 {
				return ctx, fmt.Errorf("envelope_nonce is required (must be >0)")
			}
			if d.Keeper.HasEnvelopeNonce(ctx, pubHash[:16], m.EnvelopeNonce) {
				return ctx, fmt.Errorf("envelope replay: nonce already used")
			}
			if err := verifyRelaySignature("MsgEdit", m.EnvelopePubkey, m.EnvelopeSignature, func(w *canonWriter) {
				w.writeBytes(2, m.EnvelopePubkey)
				w.writeBytes(3, m.EnvelopeBlockHash)
				w.writeUvarint(4, m.EnvelopeDifficulty)
				w.writeUvarint(5, m.EnvelopePow)
				w.writeUvarint(6, m.EnvelopeTimestamp)
				w.writeUvarint(7, m.EnvelopeNonce)
				w.writeString(100, m.Target)
				w.writeString(101, m.Community)
				w.writeString(102, m.Title)
				w.writeString(103, m.Content)
				w.writeString(104, m.Tag)
				w.writeString(105, m.Override)
				for _, mediaItem := range m.Media {
					w.writeString(106, mediaItem)
				}
			}); err != nil {
				ctx.Logger().Error("RelaySig: verification failed", "msg", "MsgEdit", "err", err.Error())
				return ctx, err
			}
			nonceExpiry, err := envelopeNonceExpiryUnix(ctx, m.EnvelopeTimestamp, maxAge)
			if err != nil {
				return ctx, err
			}
			if err := d.Keeper.SetEnvelopeNonce(ctx, pubHash[:16], m.EnvelopeNonce, nonceExpiry); err != nil {
				ctx.Logger().Error("RelaySig: failed to record nonce", "msg", "MsgEdit", "err", err.Error())
				return ctx, fmt.Errorf("failed to record nonce: %w", err)
			}
		case *coretypes.MsgSubscribe:
			if m.Authority == govAuthority {
				continue // Skip validation for governance
			}
			if err := validateEnvelopeTimestamp(ctx, m.EnvelopeTimestamp, maxAge); err != nil {
				ctx.Logger().Error("RelaySig: timestamp validation failed", "msg", "MsgSubscribe", "err", err.Error())
				return ctx, err
			}
			pubHash := sha256.Sum256(m.EnvelopePubkey)
			if m.EnvelopeNonce == 0 {
				return ctx, fmt.Errorf("envelope_nonce is required (must be >0)")
			}
			if d.Keeper.HasEnvelopeNonce(ctx, pubHash[:16], m.EnvelopeNonce) {
				return ctx, fmt.Errorf("envelope replay: nonce already used")
			}
			if err := verifyRelaySignature("MsgSubscribe", m.EnvelopePubkey, m.EnvelopeSignature, func(w *canonWriter) {
				w.writeBytes(2, m.EnvelopePubkey)
				w.writeBytes(3, m.EnvelopeBlockHash)
				w.writeUvarint(4, m.EnvelopeDifficulty)
				w.writeUvarint(5, m.EnvelopePow)
				w.writeUvarint(6, m.EnvelopeTimestamp)
				w.writeUvarint(7, m.EnvelopeNonce)
				appendSubscribePayload(w, m)
			}); err != nil {
				ctx.Logger().Error("RelaySig: verification failed", "msg", "MsgSubscribe", "err", err.Error())
				return ctx, err
			}
			nonceExpiry, err := envelopeNonceExpiryUnix(ctx, m.EnvelopeTimestamp, maxAge)
			if err != nil {
				return ctx, err
			}
			if err := d.Keeper.SetEnvelopeNonce(ctx, pubHash[:16], m.EnvelopeNonce, nonceExpiry); err != nil {
				ctx.Logger().Error("RelaySig: failed to record nonce", "msg", "MsgSubscribe", "err", err.Error())
				return ctx, fmt.Errorf("failed to record nonce: %w", err)
			}
		case *coretypes.MsgSetAutoRenewal:
			if m.Authority == govAuthority {
				continue // Skip validation for governance
			}
			if err := validateEnvelopeTimestamp(ctx, m.EnvelopeTimestamp, maxAge); err != nil {
				ctx.Logger().Error("RelaySig: timestamp validation failed", "msg", "MsgSetAutoRenewal", "err", err.Error())
				return ctx, err
			}
			pubHash := sha256.Sum256(m.EnvelopePubkey)
			if m.EnvelopeNonce == 0 {
				return ctx, fmt.Errorf("envelope_nonce is required (must be >0)")
			}
			if d.Keeper.HasEnvelopeNonce(ctx, pubHash[:16], m.EnvelopeNonce) {
				return ctx, fmt.Errorf("envelope replay: nonce already used")
			}
			if err := verifyRelaySignature("MsgSetAutoRenewal", m.EnvelopePubkey, m.EnvelopeSignature, func(w *canonWriter) {
				w.writeBytes(2, m.EnvelopePubkey)
				w.writeBytes(3, m.EnvelopeBlockHash)
				w.writeUvarint(4, m.EnvelopeDifficulty)
				w.writeUvarint(5, m.EnvelopePow)
				w.writeUvarint(6, m.EnvelopeTimestamp)
				w.writeUvarint(7, m.EnvelopeNonce)
				if m.AutoRenew {
					w.writeUvarint(100, 1)
				} else {
					w.writeUvarint(100, 0)
				}
			}); err != nil {
				ctx.Logger().Error("RelaySig: verification failed", "msg", "MsgSetAutoRenewal", "err", err.Error())
				return ctx, err
			}
			nonceExpiry, err := envelopeNonceExpiryUnix(ctx, m.EnvelopeTimestamp, maxAge)
			if err != nil {
				return ctx, err
			}
			if err := d.Keeper.SetEnvelopeNonce(ctx, pubHash[:16], m.EnvelopeNonce, nonceExpiry); err != nil {
				ctx.Logger().Error("RelaySig: failed to record nonce", "msg", "MsgSetAutoRenewal", "err", err.Error())
				return ctx, fmt.Errorf("failed to record nonce: %w", err)
			}
		case *coretypes.MsgAward:
			if m.Authority == govAuthority {
				continue
			}
			if err := validateEnvelopeTimestamp(ctx, m.EnvelopeTimestamp, maxAge); err != nil {
				ctx.Logger().Error("RelaySig: timestamp validation failed", "msg", "MsgAward", "err", err.Error())
				return ctx, err
			}
			pubHash := sha256.Sum256(m.EnvelopePubkey)
			if m.EnvelopeNonce == 0 {
				return ctx, fmt.Errorf("envelope_nonce is required (must be >0)")
			}
			if d.Keeper.HasEnvelopeNonce(ctx, pubHash[:16], m.EnvelopeNonce) {
				return ctx, fmt.Errorf("envelope replay: nonce already used")
			}
			if err := verifyRelaySignature("MsgAward", m.EnvelopePubkey, m.EnvelopeSignature, func(w *canonWriter) {
				w.writeBytes(2, m.EnvelopePubkey)
				w.writeBytes(3, m.EnvelopeBlockHash)
				w.writeUvarint(4, m.EnvelopeDifficulty)
				w.writeUvarint(5, m.EnvelopePow)
				w.writeUvarint(6, m.EnvelopeTimestamp)
				w.writeUvarint(7, m.EnvelopeNonce)
				w.writeString(100, m.Target)
				w.writeString(101, m.AwardType)
			}); err != nil {
				ctx.Logger().Error("RelaySig: verification failed", "msg", "MsgAward", "err", err.Error())
				return ctx, err
			}
			nonceExpiry, err := envelopeNonceExpiryUnix(ctx, m.EnvelopeTimestamp, maxAge)
			if err != nil {
				return ctx, err
			}
			if err := d.Keeper.SetEnvelopeNonce(ctx, pubHash[:16], m.EnvelopeNonce, nonceExpiry); err != nil {
				ctx.Logger().Error("RelaySig: failed to record nonce", "msg", "MsgAward", "err", err.Error())
				return ctx, fmt.Errorf("failed to record nonce: %w", err)
			}

		case *coretypes.MsgJoinCommunity:
			if err := d.authEnvelope(ctx, govAuthority, maxAge, "MsgJoinCommunity", m.Authority, m.EnvelopePubkey, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow, m.EnvelopeTimestamp, m.EnvelopeNonce, m.EnvelopeSignature, func(w *canonWriter) {
				w.writeString(100, m.Community)
				w.writeUvarint(101, uint64(m.Mode))
				w.writeUvarint(102, m.PinnedTeamId)
			}); err != nil {
				return ctx, err
			}
		case *coretypes.MsgLeaveCommunity:
			if err := d.authEnvelope(ctx, govAuthority, maxAge, "MsgLeaveCommunity", m.Authority, m.EnvelopePubkey, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow, m.EnvelopeTimestamp, m.EnvelopeNonce, m.EnvelopeSignature, func(w *canonWriter) {
				w.writeString(100, m.Community)
			}); err != nil {
				return ctx, err
			}
		case *coretypes.MsgBlockCommunity:
			if err := d.authEnvelope(ctx, govAuthority, maxAge, "MsgBlockCommunity", m.Authority, m.EnvelopePubkey, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow, m.EnvelopeTimestamp, m.EnvelopeNonce, m.EnvelopeSignature, func(w *canonWriter) {
				w.writeString(100, m.Target)
				w.writeString(101, m.Community)
			}); err != nil {
				return ctx, err
			}
		case *coretypes.MsgUnblockCommunity:
			if err := d.authEnvelope(ctx, govAuthority, maxAge, "MsgUnblockCommunity", m.Authority, m.EnvelopePubkey, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow, m.EnvelopeTimestamp, m.EnvelopeNonce, m.EnvelopeSignature, func(w *canonWriter) {
				w.writeString(100, m.Target)
				w.writeString(101, m.Community)
			}); err != nil {
				return ctx, err
			}
		case *coretypes.MsgCreateCurationTeam:
			if err := d.authEnvelope(ctx, govAuthority, maxAge, "MsgCreateCurationTeam", m.Authority, m.EnvelopePubkey, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow, m.EnvelopeTimestamp, m.EnvelopeNonce, m.EnvelopeSignature, func(w *canonWriter) {
				w.writeString(100, m.Community)
				w.writeString(101, m.Name)
				w.writeString(102, m.Description)
			}); err != nil {
				return ctx, err
			}
		case *coretypes.MsgSetCurationTeamProfile:
			if err := d.authEnvelope(ctx, govAuthority, maxAge, "MsgSetCurationTeamProfile", m.Authority, m.EnvelopePubkey, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow, m.EnvelopeTimestamp, m.EnvelopeNonce, m.EnvelopeSignature, func(w *canonWriter) {
				w.writeString(100, m.Community)
				w.writeUvarint(101, m.TeamId)
				w.writeString(102, m.Name)
				w.writeString(103, m.Description)
			}); err != nil {
				return ctx, err
			}
		case *coretypes.MsgInviteCurator:
			if err := d.authEnvelope(ctx, govAuthority, maxAge, "MsgInviteCurator", m.Authority, m.EnvelopePubkey, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow, m.EnvelopeTimestamp, m.EnvelopeNonce, m.EnvelopeSignature, func(w *canonWriter) {
				w.writeString(100, m.Community)
				w.writeUvarint(101, m.TeamId)
				w.writeString(102, m.Target)
			}); err != nil {
				return ctx, err
			}
		case *coretypes.MsgRevokeCuratorInvite:
			if err := d.authEnvelope(ctx, govAuthority, maxAge, "MsgRevokeCuratorInvite", m.Authority, m.EnvelopePubkey, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow, m.EnvelopeTimestamp, m.EnvelopeNonce, m.EnvelopeSignature, func(w *canonWriter) {
				w.writeString(100, m.Community)
				w.writeUvarint(101, m.TeamId)
				w.writeString(102, m.Target)
			}); err != nil {
				return ctx, err
			}
		case *coretypes.MsgAcceptCuratorInvite:
			if err := d.authEnvelope(ctx, govAuthority, maxAge, "MsgAcceptCuratorInvite", m.Authority, m.EnvelopePubkey, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow, m.EnvelopeTimestamp, m.EnvelopeNonce, m.EnvelopeSignature, func(w *canonWriter) {
				w.writeString(100, m.Community)
				w.writeUvarint(101, m.TeamId)
			}); err != nil {
				return ctx, err
			}
		case *coretypes.MsgDeclineCuratorInvite:
			if err := d.authEnvelope(ctx, govAuthority, maxAge, "MsgDeclineCuratorInvite", m.Authority, m.EnvelopePubkey, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow, m.EnvelopeTimestamp, m.EnvelopeNonce, m.EnvelopeSignature, func(w *canonWriter) {
				w.writeString(100, m.Community)
				w.writeUvarint(101, m.TeamId)
			}); err != nil {
				return ctx, err
			}
		case *coretypes.MsgLeaveCurationTeam:
			if err := d.authEnvelope(ctx, govAuthority, maxAge, "MsgLeaveCurationTeam", m.Authority, m.EnvelopePubkey, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow, m.EnvelopeTimestamp, m.EnvelopeNonce, m.EnvelopeSignature, func(w *canonWriter) {
				w.writeString(100, m.Community)
				w.writeUvarint(101, m.TeamId)
			}); err != nil {
				return ctx, err
			}
		case *coretypes.MsgRemoveCurator:
			if err := d.authEnvelope(ctx, govAuthority, maxAge, "MsgRemoveCurator", m.Authority, m.EnvelopePubkey, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow, m.EnvelopeTimestamp, m.EnvelopeNonce, m.EnvelopeSignature, func(w *canonWriter) {
				w.writeString(100, m.Community)
				w.writeUvarint(101, m.TeamId)
				w.writeString(102, m.Target)
			}); err != nil {
				return ctx, err
			}
		case *coretypes.MsgTransferCurationTeam:
			if err := d.authEnvelope(ctx, govAuthority, maxAge, "MsgTransferCurationTeam", m.Authority, m.EnvelopePubkey, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow, m.EnvelopeTimestamp, m.EnvelopeNonce, m.EnvelopeSignature, func(w *canonWriter) {
				w.writeString(100, m.Community)
				w.writeUvarint(101, m.TeamId)
				w.writeString(102, m.NewOwner)
			}); err != nil {
				return ctx, err
			}
		case *coretypes.MsgDeleteCurationTeam:
			if err := d.authEnvelope(ctx, govAuthority, maxAge, "MsgDeleteCurationTeam", m.Authority, m.EnvelopePubkey, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow, m.EnvelopeTimestamp, m.EnvelopeNonce, m.EnvelopeSignature, func(w *canonWriter) {
				w.writeString(100, m.Community)
				w.writeUvarint(101, m.TeamId)
			}); err != nil {
				return ctx, err
			}
		case *coretypes.MsgSetCurationPreference:
			if err := d.authEnvelope(ctx, govAuthority, maxAge, "MsgSetCurationPreference", m.Authority, m.EnvelopePubkey, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow, m.EnvelopeTimestamp, m.EnvelopeNonce, m.EnvelopeSignature, func(w *canonWriter) {
				w.writeString(100, m.Community)
				w.writeUvarint(101, uint64(m.Mode))
				w.writeUvarint(102, m.PinnedTeamId)
			}); err != nil {
				return ctx, err
			}
		case *coretypes.MsgSetCurationPostHidden:
			if err := d.authEnvelope(ctx, govAuthority, maxAge, "MsgSetCurationPostHidden", m.Authority, m.EnvelopePubkey, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow, m.EnvelopeTimestamp, m.EnvelopeNonce, m.EnvelopeSignature, func(w *canonWriter) {
				w.writeString(100, m.Community)
				w.writeUvarint(101, m.TeamId)
				w.writeString(102, m.Target)
				writeCanonBool(w, 103, m.Hidden)
			}); err != nil {
				return ctx, err
			}
		case *coretypes.MsgSetCurationUserHidden:
			if err := d.authEnvelope(ctx, govAuthority, maxAge, "MsgSetCurationUserHidden", m.Authority, m.EnvelopePubkey, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow, m.EnvelopeTimestamp, m.EnvelopeNonce, m.EnvelopeSignature, func(w *canonWriter) {
				w.writeString(100, m.Community)
				w.writeUvarint(101, m.TeamId)
				w.writeString(102, m.Target)
				writeCanonBool(w, 103, m.Hidden)
			}); err != nil {
				return ctx, err
			}
		case *coretypes.MsgSetCurationThreadLocked:
			if err := d.authEnvelope(ctx, govAuthority, maxAge, "MsgSetCurationThreadLocked", m.Authority, m.EnvelopePubkey, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow, m.EnvelopeTimestamp, m.EnvelopeNonce, m.EnvelopeSignature, func(w *canonWriter) {
				w.writeString(100, m.Community)
				w.writeUvarint(101, m.TeamId)
				w.writeString(102, m.RootHash)
				writeCanonBool(w, 103, m.Locked)
			}); err != nil {
				return ctx, err
			}
		case *coretypes.MsgSetCurationSubscriberOnly:
			if err := d.authEnvelope(ctx, govAuthority, maxAge, "MsgSetCurationSubscriberOnly", m.Authority, m.EnvelopePubkey, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow, m.EnvelopeTimestamp, m.EnvelopeNonce, m.EnvelopeSignature, func(w *canonWriter) {
				w.writeString(100, m.Community)
				w.writeUvarint(101, m.TeamId)
				writeCanonBool(w, 102, m.Enabled)
			}); err != nil {
				return ctx, err
			}
		case *coretypes.MsgSetCurationTag:
			if err := d.authEnvelope(ctx, govAuthority, maxAge, "MsgSetCurationTag", m.Authority, m.EnvelopePubkey, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow, m.EnvelopeTimestamp, m.EnvelopeNonce, m.EnvelopeSignature, func(w *canonWriter) {
				w.writeString(100, m.Community)
				w.writeUvarint(101, m.TeamId)
				w.writeString(102, m.Tag)
			}); err != nil {
				return ctx, err
			}
		case *coretypes.MsgSetCurationPostTag:
			if err := d.authEnvelope(ctx, govAuthority, maxAge, "MsgSetCurationPostTag", m.Authority, m.EnvelopePubkey, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow, m.EnvelopeTimestamp, m.EnvelopeNonce, m.EnvelopeSignature, func(w *canonWriter) {
				w.writeString(100, m.Community)
				w.writeUvarint(101, m.TeamId)
				w.writeString(102, m.Target)
				w.writeString(103, m.Tag)
				writeCanonBool(w, 104, m.Clear)
			}); err != nil {
				return ctx, err
			}
		case *coretypes.MsgClaimCreatorRewards:
			if err := d.authEnvelope(ctx, govAuthority, maxAge, "MsgClaimCreatorRewards", m.Authority, m.EnvelopePubkey, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow, m.EnvelopeTimestamp, m.EnvelopeNonce, m.EnvelopeSignature, func(w *canonWriter) {
				for _, id := range m.EpochIds {
					w.writeUvarint(100, uint64(id))
				}
			}); err != nil {
				return ctx, err
			}
		default:
			return ctx, fmt.Errorf("RelaySig: unsupported relay message %T", msg)
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

func envelopeNonceExpiryUnix(ctx sdk.Context, timestampMs uint64, maxAgeSec uint64) (int64, error) {
	maxAge, err := coretypes.CheckedEnvelopeAge(maxAgeSec)
	if err != nil {
		return 0, fmt.Errorf("max_envelope_age unusable: %w", err)
	}
	blockTime := ctx.BlockTime()
	expiry := blockTime.Add(maxAge + 5*time.Minute)
	if timestampMs > 0 {
		txTimeMs, err := coretypes.CheckedUint64ToInt64(timestampMs)
		if err != nil {
			return 0, fmt.Errorf("envelope_timestamp out of range: %w", err)
		}
		txTime := time.UnixMilli(txTimeMs)
		if candidate := txTime.Add(maxAge + 5*time.Minute); candidate.After(expiry) {
			expiry = candidate
		}
	}
	return expiry.Unix(), nil
}

// validateEnvelopeTimestamp checks that envelope_timestamp is not too old or in the future.
// timestampMs is the envelope timestamp in milliseconds.
// maxAgeSec is the maximum allowed age in seconds.
func validateEnvelopeTimestamp(ctx sdk.Context, timestampMs uint64, maxAgeSec uint64) error {
	if timestampMs == 0 {
		return fmt.Errorf("envelope_timestamp is required")
	}
	// A timestamp or max-age that cannot be represented must reject the
	// envelope. Wrapping either one silently widens or inverts the replay
	// window (review M-7).
	txTimeMs, err := coretypes.CheckedUint64ToInt64(timestampMs)
	if err != nil {
		return fmt.Errorf("envelope_timestamp out of range: %w", err)
	}
	maxAge, err := coretypes.CheckedEnvelopeAge(maxAgeSec)
	if err != nil {
		return fmt.Errorf("max_envelope_age unusable: %w", err)
	}
	txTime := time.UnixMilli(txTimeMs)
	blockTime := ctx.BlockTime()
	age := blockTime.Sub(txTime)
	if age > maxAge {
		return fmt.Errorf("envelope_timestamp too old: age=%s, max=%s (tx_time=%s, block_time=%s)", age, maxAge, txTime, blockTime)
	}
	maxFutureSkew := maxAge / 2
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
