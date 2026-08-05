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
			nonceExpiry := envelopeNonceExpiryUnix(ctx, m.EnvelopeTimestamp, maxAge)
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
			nonceExpiry := envelopeNonceExpiryUnix(ctx, m.EnvelopeTimestamp, maxAge)
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
			nonceExpiry := envelopeNonceExpiryUnix(ctx, m.EnvelopeTimestamp, maxAge)
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
			nonceExpiry := envelopeNonceExpiryUnix(ctx, m.EnvelopeTimestamp, maxAge)
			if err := d.Keeper.SetEnvelopeNonce(ctx, pubHash[:16], m.EnvelopeNonce, nonceExpiry); err != nil {
				ctx.Logger().Error("RelaySig: failed to record nonce", "msg", "MsgSetBiography", "err", err.Error())
				return ctx, fmt.Errorf("failed to record nonce: %w", err)
			}
		case *coretypes.MsgEnableAgent:
			if m.Authority == govAuthority {
				continue
			}
			if err := validateEnvelopeTimestamp(ctx, m.EnvelopeTimestamp, maxAge); err != nil {
				ctx.Logger().Error("RelaySig: timestamp validation failed", "msg", "MsgEnableAgent", "err", err.Error())
				return ctx, err
			}
			pubHash := sha256.Sum256(m.EnvelopePubkey)
			if m.EnvelopeNonce == 0 {
				return ctx, fmt.Errorf("envelope_nonce is required (must be >0)")
			}
			if d.Keeper.HasEnvelopeNonce(ctx, pubHash[:16], m.EnvelopeNonce) {
				return ctx, fmt.Errorf("envelope replay: nonce already used")
			}
			if err := verifyRelaySignature("MsgEnableAgent", m.EnvelopePubkey, m.EnvelopeSignature, func(w *canonWriter) {
				w.writeBytes(2, m.EnvelopePubkey)
				w.writeBytes(3, m.EnvelopeBlockHash)
				w.writeUvarint(4, m.EnvelopeDifficulty)
				w.writeUvarint(5, m.EnvelopePow)
				w.writeUvarint(6, m.EnvelopeTimestamp)
				w.writeUvarint(7, m.EnvelopeNonce)
				w.writeString(100, m.Target)
				w.writeString(101, m.Agent)
			}); err != nil {
				ctx.Logger().Error("RelaySig: verification failed", "msg", "MsgEnableAgent", "err", err.Error())
				return ctx, err
			}
			nonceExpiry := envelopeNonceExpiryUnix(ctx, m.EnvelopeTimestamp, maxAge)
			if err := d.Keeper.SetEnvelopeNonce(ctx, pubHash[:16], m.EnvelopeNonce, nonceExpiry); err != nil {
				ctx.Logger().Error("RelaySig: failed to record nonce", "msg", "MsgEnableAgent", "err", err.Error())
				return ctx, fmt.Errorf("failed to record nonce: %w", err)
			}
		case *coretypes.MsgDisableAgent:
			if m.Authority == govAuthority {
				continue
			}
			if err := validateEnvelopeTimestamp(ctx, m.EnvelopeTimestamp, maxAge); err != nil {
				ctx.Logger().Error("RelaySig: timestamp validation failed", "msg", "MsgDisableAgent", "err", err.Error())
				return ctx, err
			}
			pubHash := sha256.Sum256(m.EnvelopePubkey)
			if m.EnvelopeNonce == 0 {
				return ctx, fmt.Errorf("envelope_nonce is required (must be >0)")
			}
			if d.Keeper.HasEnvelopeNonce(ctx, pubHash[:16], m.EnvelopeNonce) {
				return ctx, fmt.Errorf("envelope replay: nonce already used")
			}
			if err := verifyRelaySignature("MsgDisableAgent", m.EnvelopePubkey, m.EnvelopeSignature, func(w *canonWriter) {
				w.writeBytes(2, m.EnvelopePubkey)
				w.writeBytes(3, m.EnvelopeBlockHash)
				w.writeUvarint(4, m.EnvelopeDifficulty)
				w.writeUvarint(5, m.EnvelopePow)
				w.writeUvarint(6, m.EnvelopeTimestamp)
				w.writeUvarint(7, m.EnvelopeNonce)
				w.writeString(100, m.Target)
				w.writeString(101, m.Agent)
			}); err != nil {
				ctx.Logger().Error("RelaySig: verification failed", "msg", "MsgDisableAgent", "err", err.Error())
				return ctx, err
			}
			nonceExpiry := envelopeNonceExpiryUnix(ctx, m.EnvelopeTimestamp, maxAge)
			if err := d.Keeper.SetEnvelopeNonce(ctx, pubHash[:16], m.EnvelopeNonce, nonceExpiry); err != nil {
				ctx.Logger().Error("RelaySig: failed to record nonce", "msg", "MsgDisableAgent", "err", err.Error())
				return ctx, fmt.Errorf("failed to record nonce: %w", err)
			}
		case *coretypes.MsgSetAgents:
			if m.Authority == govAuthority {
				continue
			}
			if err := validateEnvelopeTimestamp(ctx, m.EnvelopeTimestamp, maxAge); err != nil {
				ctx.Logger().Error("RelaySig: timestamp validation failed", "msg", "MsgSetAgents", "err", err.Error())
				return ctx, err
			}
			pubHash := sha256.Sum256(m.EnvelopePubkey)
			if m.EnvelopeNonce == 0 {
				return ctx, fmt.Errorf("envelope_nonce is required (must be >0)")
			}
			if d.Keeper.HasEnvelopeNonce(ctx, pubHash[:16], m.EnvelopeNonce) {
				return ctx, fmt.Errorf("envelope replay: nonce already used")
			}
			if err := verifyRelaySignature("MsgSetAgents", m.EnvelopePubkey, m.EnvelopeSignature, func(w *canonWriter) {
				w.writeBytes(2, m.EnvelopePubkey)
				w.writeBytes(3, m.EnvelopeBlockHash)
				w.writeUvarint(4, m.EnvelopeDifficulty)
				w.writeUvarint(5, m.EnvelopePow)
				w.writeUvarint(6, m.EnvelopeTimestamp)
				w.writeUvarint(7, m.EnvelopeNonce)
				w.writeString(100, m.Target)
				for _, agent := range m.Agents {
					w.writeString(101, agent)
				}
			}); err != nil {
				ctx.Logger().Error("RelaySig: verification failed", "msg", "MsgSetAgents", "err", err.Error())
				return ctx, err
			}
			nonceExpiry := envelopeNonceExpiryUnix(ctx, m.EnvelopeTimestamp, maxAge)
			if err := d.Keeper.SetEnvelopeNonce(ctx, pubHash[:16], m.EnvelopeNonce, nonceExpiry); err != nil {
				ctx.Logger().Error("RelaySig: failed to record nonce", "msg", "MsgSetAgents", "err", err.Error())
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
			nonceExpiry := envelopeNonceExpiryUnix(ctx, m.EnvelopeTimestamp, maxAge)
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
			nonceExpiry := envelopeNonceExpiryUnix(ctx, m.EnvelopeTimestamp, maxAge)
			if err := d.Keeper.SetEnvelopeNonce(ctx, pubHash[:16], m.EnvelopeNonce, nonceExpiry); err != nil {
				ctx.Logger().Error("RelaySig: failed to record nonce", "msg", "MsgUnfollowUser", "err", err.Error())
				return ctx, fmt.Errorf("failed to record nonce: %w", err)
			}
		case *coretypes.MsgFollowTopic:
			if m.Authority == govAuthority {
				continue
			}
			if err := validateEnvelopeTimestamp(ctx, m.EnvelopeTimestamp, maxAge); err != nil {
				ctx.Logger().Error("RelaySig: timestamp validation failed", "msg", "MsgFollowTopic", "err", err.Error())
				return ctx, err
			}
			pubHash := sha256.Sum256(m.EnvelopePubkey)
			if m.EnvelopeNonce == 0 {
				return ctx, fmt.Errorf("envelope_nonce is required (must be >0)")
			}
			if d.Keeper.HasEnvelopeNonce(ctx, pubHash[:16], m.EnvelopeNonce) {
				return ctx, fmt.Errorf("envelope replay: nonce already used")
			}
			if err := verifyRelaySignature("MsgFollowTopic", m.EnvelopePubkey, m.EnvelopeSignature, func(w *canonWriter) {
				w.writeBytes(2, m.EnvelopePubkey)
				w.writeBytes(3, m.EnvelopeBlockHash)
				w.writeUvarint(4, m.EnvelopeDifficulty)
				w.writeUvarint(5, m.EnvelopePow)
				w.writeUvarint(6, m.EnvelopeTimestamp)
				w.writeUvarint(7, m.EnvelopeNonce)
				w.writeString(100, m.Target)
				w.writeString(101, m.Topic)
			}); err != nil {
				ctx.Logger().Error("RelaySig: verification failed", "msg", "MsgFollowTopic", "err", err.Error())
				return ctx, err
			}
			nonceExpiry := envelopeNonceExpiryUnix(ctx, m.EnvelopeTimestamp, maxAge)
			if err := d.Keeper.SetEnvelopeNonce(ctx, pubHash[:16], m.EnvelopeNonce, nonceExpiry); err != nil {
				ctx.Logger().Error("RelaySig: failed to record nonce", "msg", "MsgFollowTopic", "err", err.Error())
				return ctx, fmt.Errorf("failed to record nonce: %w", err)
			}
		case *coretypes.MsgUnfollowTopic:
			if m.Authority == govAuthority {
				continue
			}
			if err := validateEnvelopeTimestamp(ctx, m.EnvelopeTimestamp, maxAge); err != nil {
				ctx.Logger().Error("RelaySig: timestamp validation failed", "msg", "MsgUnfollowTopic", "err", err.Error())
				return ctx, err
			}
			pubHash := sha256.Sum256(m.EnvelopePubkey)
			if m.EnvelopeNonce == 0 {
				return ctx, fmt.Errorf("envelope_nonce is required (must be >0)")
			}
			if d.Keeper.HasEnvelopeNonce(ctx, pubHash[:16], m.EnvelopeNonce) {
				return ctx, fmt.Errorf("envelope replay: nonce already used")
			}
			if err := verifyRelaySignature("MsgUnfollowTopic", m.EnvelopePubkey, m.EnvelopeSignature, func(w *canonWriter) {
				w.writeBytes(2, m.EnvelopePubkey)
				w.writeBytes(3, m.EnvelopeBlockHash)
				w.writeUvarint(4, m.EnvelopeDifficulty)
				w.writeUvarint(5, m.EnvelopePow)
				w.writeUvarint(6, m.EnvelopeTimestamp)
				w.writeUvarint(7, m.EnvelopeNonce)
				w.writeString(100, m.Target)
				w.writeString(101, m.Topic)
			}); err != nil {
				ctx.Logger().Error("RelaySig: verification failed", "msg", "MsgUnfollowTopic", "err", err.Error())
				return ctx, err
			}
			nonceExpiry := envelopeNonceExpiryUnix(ctx, m.EnvelopeTimestamp, maxAge)
			if err := d.Keeper.SetEnvelopeNonce(ctx, pubHash[:16], m.EnvelopeNonce, nonceExpiry); err != nil {
				ctx.Logger().Error("RelaySig: failed to record nonce", "msg", "MsgUnfollowTopic", "err", err.Error())
				return ctx, fmt.Errorf("failed to record nonce: %w", err)
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
			nonceExpiry := envelopeNonceExpiryUnix(ctx, m.EnvelopeTimestamp, maxAge)
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
			nonceExpiry := envelopeNonceExpiryUnix(ctx, m.EnvelopeTimestamp, maxAge)
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
			nonceExpiry := envelopeNonceExpiryUnix(ctx, m.EnvelopeTimestamp, maxAge)
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
			nonceExpiry := envelopeNonceExpiryUnix(ctx, m.EnvelopeTimestamp, maxAge)
			if err := d.Keeper.SetEnvelopeNonce(ctx, pubHash[:16], m.EnvelopeNonce, nonceExpiry); err != nil {
				ctx.Logger().Error("RelaySig: failed to record nonce", "msg", "MsgUnblockUser", "err", err.Error())
				return ctx, fmt.Errorf("failed to record nonce: %w", err)
			}
		case *coretypes.MsgBlockTopic:
			if m.Authority == govAuthority {
				continue
			}
			if err := validateEnvelopeTimestamp(ctx, m.EnvelopeTimestamp, maxAge); err != nil {
				ctx.Logger().Error("RelaySig: timestamp validation failed", "msg", "MsgBlockTopic", "err", err.Error())
				return ctx, err
			}
			pubHash := sha256.Sum256(m.EnvelopePubkey)
			if m.EnvelopeNonce == 0 {
				return ctx, fmt.Errorf("envelope_nonce is required (must be >0)")
			}
			if d.Keeper.HasEnvelopeNonce(ctx, pubHash[:16], m.EnvelopeNonce) {
				return ctx, fmt.Errorf("envelope replay: nonce already used")
			}
			if err := verifyRelaySignature("MsgBlockTopic", m.EnvelopePubkey, m.EnvelopeSignature, func(w *canonWriter) {
				w.writeBytes(2, m.EnvelopePubkey)
				w.writeBytes(3, m.EnvelopeBlockHash)
				w.writeUvarint(4, m.EnvelopeDifficulty)
				w.writeUvarint(5, m.EnvelopePow)
				w.writeUvarint(6, m.EnvelopeTimestamp)
				w.writeUvarint(7, m.EnvelopeNonce)
				w.writeString(100, m.Target)
				w.writeString(101, m.Topic)
			}); err != nil {
				ctx.Logger().Error("RelaySig: verification failed", "msg", "MsgBlockTopic", "err", err.Error())
				return ctx, err
			}
			nonceExpiry := envelopeNonceExpiryUnix(ctx, m.EnvelopeTimestamp, maxAge)
			if err := d.Keeper.SetEnvelopeNonce(ctx, pubHash[:16], m.EnvelopeNonce, nonceExpiry); err != nil {
				ctx.Logger().Error("RelaySig: failed to record nonce", "msg", "MsgBlockTopic", "err", err.Error())
				return ctx, fmt.Errorf("failed to record nonce: %w", err)
			}
		case *coretypes.MsgUnblockTopic:
			if m.Authority == govAuthority {
				continue
			}
			if err := validateEnvelopeTimestamp(ctx, m.EnvelopeTimestamp, maxAge); err != nil {
				ctx.Logger().Error("RelaySig: timestamp validation failed", "msg", "MsgUnblockTopic", "err", err.Error())
				return ctx, err
			}
			pubHash := sha256.Sum256(m.EnvelopePubkey)
			if m.EnvelopeNonce == 0 {
				return ctx, fmt.Errorf("envelope_nonce is required (must be >0)")
			}
			if d.Keeper.HasEnvelopeNonce(ctx, pubHash[:16], m.EnvelopeNonce) {
				return ctx, fmt.Errorf("envelope replay: nonce already used")
			}
			if err := verifyRelaySignature("MsgUnblockTopic", m.EnvelopePubkey, m.EnvelopeSignature, func(w *canonWriter) {
				w.writeBytes(2, m.EnvelopePubkey)
				w.writeBytes(3, m.EnvelopeBlockHash)
				w.writeUvarint(4, m.EnvelopeDifficulty)
				w.writeUvarint(5, m.EnvelopePow)
				w.writeUvarint(6, m.EnvelopeTimestamp)
				w.writeUvarint(7, m.EnvelopeNonce)
				w.writeString(100, m.Target)
				w.writeString(101, m.Topic)
			}); err != nil {
				ctx.Logger().Error("RelaySig: verification failed", "msg", "MsgUnblockTopic", "err", err.Error())
				return ctx, err
			}
			nonceExpiry := envelopeNonceExpiryUnix(ctx, m.EnvelopeTimestamp, maxAge)
			if err := d.Keeper.SetEnvelopeNonce(ctx, pubHash[:16], m.EnvelopeNonce, nonceExpiry); err != nil {
				ctx.Logger().Error("RelaySig: failed to record nonce", "msg", "MsgUnblockTopic", "err", err.Error())
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
			nonceExpiry := envelopeNonceExpiryUnix(ctx, m.EnvelopeTimestamp, maxAge)
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
			nonceExpiry := envelopeNonceExpiryUnix(ctx, m.EnvelopeTimestamp, maxAge)
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
			nonceExpiry := envelopeNonceExpiryUnix(ctx, m.EnvelopeTimestamp, maxAge)
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
				w.writeString(101, m.Topic)
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
			nonceExpiry := envelopeNonceExpiryUnix(ctx, m.EnvelopeTimestamp, maxAge)
			if err := d.Keeper.SetEnvelopeNonce(ctx, pubHash[:16], m.EnvelopeNonce, nonceExpiry); err != nil {
				ctx.Logger().Error("RelaySig: failed to record nonce", "msg", "MsgEdit", "err", err.Error())
				return ctx, fmt.Errorf("failed to record nonce: %w", err)
			}
		case *coretypes.MsgAnnotate:
			if m.Authority == govAuthority {
				continue // Skip validation for governance
			}
			if err := validateEnvelopeTimestamp(ctx, m.EnvelopeTimestamp, maxAge); err != nil {
				ctx.Logger().Error("RelaySig: timestamp validation failed", "msg", "MsgAnnotate", "err", err.Error())
				return ctx, err
			}
			pubHash := sha256.Sum256(m.EnvelopePubkey)
			if m.EnvelopeNonce == 0 {
				return ctx, fmt.Errorf("envelope_nonce is required (must be >0)")
			}
			if d.Keeper.HasEnvelopeNonce(ctx, pubHash[:16], m.EnvelopeNonce) {
				return ctx, fmt.Errorf("envelope replay: nonce already used")
			}
			if err := verifyRelaySignature("MsgAnnotate", m.EnvelopePubkey, m.EnvelopeSignature, func(w *canonWriter) {
				w.writeBytes(2, m.EnvelopePubkey)
				w.writeBytes(3, m.EnvelopeBlockHash)
				w.writeUvarint(4, m.EnvelopeDifficulty)
				w.writeUvarint(5, m.EnvelopePow)
				w.writeUvarint(6, m.EnvelopeTimestamp)
				w.writeUvarint(7, m.EnvelopeNonce)
				w.writeString(101, m.Topic)
				w.writeString(102, m.Title)
				w.writeString(103, m.Content)
				w.writeString(104, m.Tag)
				w.writeString(105, m.Override)
				for _, mediaItem := range m.Media {
					w.writeString(106, mediaItem)
				}
				w.writeString(107, m.Appendix)
			}); err != nil {
				ctx.Logger().Error("RelaySig: verification failed", "msg", "MsgAnnotate", "err", err.Error())
				return ctx, err
			}
			nonceExpiry := envelopeNonceExpiryUnix(ctx, m.EnvelopeTimestamp, maxAge)
			if err := d.Keeper.SetEnvelopeNonce(ctx, pubHash[:16], m.EnvelopeNonce, nonceExpiry); err != nil {
				ctx.Logger().Error("RelaySig: failed to record nonce", "msg", "MsgAnnotate", "err", err.Error())
				return ctx, fmt.Errorf("failed to record nonce: %w", err)
			}
		// MsgSetLevel is not in isRelayMessage / relayMessagePrototypes — it
		// routes through stdAnte (governance). A RelaySig branch here would be
		// unreachable via the relay ante chain.
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
				w.writeUvarint(100, uint64(uint32(m.Level)))
				if m.Target != "" {
					w.writeString(101, m.Target)
				}
			}); err != nil {
				ctx.Logger().Error("RelaySig: verification failed", "msg", "MsgSubscribe", "err", err.Error())
				return ctx, err
			}
			nonceExpiry := envelopeNonceExpiryUnix(ctx, m.EnvelopeTimestamp, maxAge)
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
			nonceExpiry := envelopeNonceExpiryUnix(ctx, m.EnvelopeTimestamp, maxAge)
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
			nonceExpiry := envelopeNonceExpiryUnix(ctx, m.EnvelopeTimestamp, maxAge)
			if err := d.Keeper.SetEnvelopeNonce(ctx, pubHash[:16], m.EnvelopeNonce, nonceExpiry); err != nil {
				ctx.Logger().Error("RelaySig: failed to record nonce", "msg", "MsgAward", "err", err.Error())
				return ctx, fmt.Errorf("failed to record nonce: %w", err)
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

func envelopeNonceExpiryUnix(ctx sdk.Context, timestampMs uint64, maxAgeSec uint64) int64 {
	maxAge := time.Duration(maxAgeSec) * time.Second
	blockTime := ctx.BlockTime()
	expiry := blockTime.Add(maxAge + 5*time.Minute)
	if timestampMs > 0 {
		txTime := time.UnixMilli(int64(timestampMs))
		if candidate := txTime.Add(maxAge + 5*time.Minute); candidate.After(expiry) {
			expiry = candidate
		}
	}
	return expiry.Unix()
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

	// Compute required fees from min gas prices for all execution modes; CheckTx enforces min-gas here.
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
		if !offered.IsAnyGTE(required) {
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
