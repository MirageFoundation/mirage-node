package types

import (
	sdk "github.com/cosmos/cosmos-sdk/types"
	"github.com/cosmos/gogoproto/proto"
)

// MsgMintTo is a legacy message type (renamed to MsgMintTokens).
// Kept for backwards compatibility so we can decode old governance proposals.
// This is NOT used for new transactions - only for reading historical data.
type MsgMintTo struct {
	Authority string `protobuf:"bytes,1,opt,name=authority,proto3" json:"authority,omitempty"`
	Target    string `protobuf:"bytes,2,opt,name=target,proto3" json:"target,omitempty"`
	Amount    uint64 `protobuf:"varint,3,opt,name=amount,proto3" json:"amount,omitempty"`
	Reason    string `protobuf:"bytes,4,opt,name=reason,proto3" json:"reason,omitempty"`
}

func init() {
	proto.RegisterType((*MsgMintTo)(nil), "mirage.core.v1.MsgMintTo")
	proto.RegisterType((*MsgFollowModerator)(nil), "mirage.core.v1.MsgFollowModerator")
	proto.RegisterType((*MsgUnfollowModerator)(nil), "mirage.core.v1.MsgUnfollowModerator")
	proto.RegisterType((*MsgBridgeBurn)(nil), "mirage.core.v1.MsgBridgeBurn")
	proto.RegisterType((*MsgBridgeAttest)(nil), "mirage.core.v1.MsgBridgeAttest")
	proto.RegisterType((*MsgBridgeMinted)(nil), "mirage.core.v1.MsgBridgeMinted")
	proto.RegisterType((*MsgBridgeAttestBurned)(nil), "mirage.core.v1.MsgBridgeAttestBurned")
	proto.RegisterType((*MsgBridgeAttestMinted)(nil), "mirage.core.v1.MsgBridgeAttestMinted")
}

func (m *MsgMintTo) Reset()         { *m = MsgMintTo{} }
func (m *MsgMintTo) String() string { return "MsgMintTo (legacy)" }
func (m *MsgMintTo) ProtoMessage()  {}

// XXX_MessageName returns the proto message name for type URL resolution
func (m *MsgMintTo) XXX_MessageName() string { return "mirage.core.v1.MsgMintTo" }

// Implement sdk.Msg interface (minimal, just for registration)
func (m *MsgMintTo) GetSigners() []sdk.AccAddress { return nil }

// MsgFollowModerator is a legacy message type (renamed to MsgEnableAgent).
// Kept for backwards compatibility so we can decode old transactions.
type MsgFollowModerator struct {
	Authority string `protobuf:"bytes,1,opt,name=authority,proto3" json:"authority,omitempty"`
	Target    string `protobuf:"bytes,100,opt,name=target,proto3" json:"target,omitempty"`
	Moderator string `protobuf:"bytes,101,opt,name=moderator,proto3" json:"moderator,omitempty"`
}

func (m *MsgFollowModerator) Reset()                       { *m = MsgFollowModerator{} }
func (m *MsgFollowModerator) String() string               { return "MsgFollowModerator (legacy)" }
func (m *MsgFollowModerator) ProtoMessage()                {}
func (m *MsgFollowModerator) XXX_MessageName() string      { return "mirage.core.v1.MsgFollowModerator" }
func (m *MsgFollowModerator) GetSigners() []sdk.AccAddress { return nil }

// MsgUnfollowModerator is a legacy message type (renamed to MsgDisableAgent).
type MsgUnfollowModerator struct {
	Authority string `protobuf:"bytes,1,opt,name=authority,proto3" json:"authority,omitempty"`
	Target    string `protobuf:"bytes,100,opt,name=target,proto3" json:"target,omitempty"`
	Moderator string `protobuf:"bytes,101,opt,name=moderator,proto3" json:"moderator,omitempty"`
}

func (m *MsgUnfollowModerator) Reset()                       { *m = MsgUnfollowModerator{} }
func (m *MsgUnfollowModerator) String() string               { return "MsgUnfollowModerator (legacy)" }
func (m *MsgUnfollowModerator) ProtoMessage()                {}
func (m *MsgUnfollowModerator) XXX_MessageName() string      { return "mirage.core.v1.MsgUnfollowModerator" }
func (m *MsgUnfollowModerator) GetSigners() []sdk.AccAddress { return nil }

// MsgBridgeBurn is a legacy message type (bridge removed in v1.31.0).
// Kept for backwards compatibility so we can decode old transactions.
// This is NOT used for new transactions - only for reading historical data.
type MsgBridgeBurn struct {
	Authority          string `protobuf:"bytes,1,opt,name=authority,proto3" json:"authority,omitempty"`
	EnvelopePubkey     []byte `protobuf:"bytes,2,opt,name=envelope_pubkey,json=envelopePubkey,proto3" json:"envelope_pubkey,omitempty"`
	EnvelopeBlockHash  []byte `protobuf:"bytes,3,opt,name=envelope_block_hash,json=envelopeBlockHash,proto3" json:"envelope_block_hash,omitempty"`
	EnvelopeDifficulty uint64 `protobuf:"varint,4,opt,name=envelope_difficulty,json=envelopeDifficulty,proto3" json:"envelope_difficulty,omitempty"`
	EnvelopePow        uint64 `protobuf:"varint,5,opt,name=envelope_pow,json=envelopePow,proto3" json:"envelope_pow,omitempty"`
	EnvelopeTimestamp  uint64 `protobuf:"varint,6,opt,name=envelope_timestamp,json=envelopeTimestamp,proto3" json:"envelope_timestamp,omitempty"`
	EnvelopeNonce      uint64 `protobuf:"varint,7,opt,name=envelope_nonce,json=envelopeNonce,proto3" json:"envelope_nonce,omitempty"`
	EnvelopeSignature  []byte `protobuf:"bytes,10,opt,name=envelope_signature,json=envelopeSignature,proto3" json:"envelope_signature,omitempty"`
	DestinationChain   string `protobuf:"bytes,100,opt,name=destination_chain,json=destinationChain,proto3" json:"destination_chain,omitempty"`
	DestinationAddress string `protobuf:"bytes,101,opt,name=destination_address,json=destinationAddress,proto3" json:"destination_address,omitempty"`
	Amount             uint64 `protobuf:"varint,102,opt,name=amount,proto3" json:"amount,omitempty"`
}

func (m *MsgBridgeBurn) Reset()                       { *m = MsgBridgeBurn{} }
func (m *MsgBridgeBurn) String() string               { return "MsgBridgeBurn (legacy)" }
func (m *MsgBridgeBurn) ProtoMessage()                {}
func (m *MsgBridgeBurn) XXX_MessageName() string      { return "mirage.core.v1.MsgBridgeBurn" }
func (m *MsgBridgeBurn) GetSigners() []sdk.AccAddress { return nil }
func (m *MsgBridgeBurn) GetAuthority() string {
	if m != nil {
		return m.Authority
	}
	return ""
}
func (m *MsgBridgeBurn) GetEnvelopePubkey() []byte {
	if m != nil {
		return m.EnvelopePubkey
	}
	return nil
}
func (m *MsgBridgeBurn) GetEnvelopeBlockHash() []byte {
	if m != nil {
		return m.EnvelopeBlockHash
	}
	return nil
}
func (m *MsgBridgeBurn) GetEnvelopeDifficulty() uint64 {
	if m != nil {
		return m.EnvelopeDifficulty
	}
	return 0
}
func (m *MsgBridgeBurn) GetEnvelopePow() uint64 {
	if m != nil {
		return m.EnvelopePow
	}
	return 0
}
func (m *MsgBridgeBurn) GetEnvelopeTimestamp() uint64 {
	if m != nil {
		return m.EnvelopeTimestamp
	}
	return 0
}
func (m *MsgBridgeBurn) GetEnvelopeNonce() uint64 {
	if m != nil {
		return m.EnvelopeNonce
	}
	return 0
}
func (m *MsgBridgeBurn) GetEnvelopeSignature() []byte {
	if m != nil {
		return m.EnvelopeSignature
	}
	return nil
}
func (m *MsgBridgeBurn) GetDestinationChain() string {
	if m != nil {
		return m.DestinationChain
	}
	return ""
}
func (m *MsgBridgeBurn) GetDestinationAddress() string {
	if m != nil {
		return m.DestinationAddress
	}
	return ""
}
func (m *MsgBridgeBurn) GetAmount() uint64 {
	if m != nil {
		return m.Amount
	}
	return 0
}

// MsgBridgeAttest is the pre-v1.10 name of MsgBridgeAttestBurned.
type MsgBridgeAttest struct {
	Validator       string `protobuf:"bytes,1,opt,name=validator,proto3" json:"validator,omitempty"`
	SourceChain     string `protobuf:"bytes,2,opt,name=source_chain,json=sourceChain,proto3" json:"source_chain,omitempty"`
	BurnId          string `protobuf:"bytes,3,opt,name=burn_id,json=burnId,proto3" json:"burn_id,omitempty"`
	MirageRecipient string `protobuf:"bytes,4,opt,name=mirage_recipient,json=mirageRecipient,proto3" json:"mirage_recipient,omitempty"`
	Amount          uint64 `protobuf:"varint,5,opt,name=amount,proto3" json:"amount,omitempty"`
}

func (m *MsgBridgeAttest) Reset()                       { *m = MsgBridgeAttest{} }
func (m *MsgBridgeAttest) String() string               { return "MsgBridgeAttest (legacy)" }
func (m *MsgBridgeAttest) ProtoMessage()                {}
func (m *MsgBridgeAttest) XXX_MessageName() string      { return "mirage.core.v1.MsgBridgeAttest" }
func (m *MsgBridgeAttest) GetSigners() []sdk.AccAddress { return nil }

// MsgBridgeMinted is the pre-v1.10 name of MsgBridgeAttestMinted.
type MsgBridgeMinted struct {
	Authority        string `protobuf:"bytes,1,opt,name=authority,proto3" json:"authority,omitempty"`
	BurnId           string `protobuf:"bytes,2,opt,name=burn_id,json=burnId,proto3" json:"burn_id,omitempty"`
	DestinationChain string `protobuf:"bytes,3,opt,name=destination_chain,json=destinationChain,proto3" json:"destination_chain,omitempty"`
	DestinationTx    string `protobuf:"bytes,4,opt,name=destination_tx,json=destinationTx,proto3" json:"destination_tx,omitempty"`
}

func (m *MsgBridgeMinted) Reset()                       { *m = MsgBridgeMinted{} }
func (m *MsgBridgeMinted) String() string               { return "MsgBridgeMinted (legacy)" }
func (m *MsgBridgeMinted) ProtoMessage()                {}
func (m *MsgBridgeMinted) XXX_MessageName() string      { return "mirage.core.v1.MsgBridgeMinted" }
func (m *MsgBridgeMinted) GetSigners() []sdk.AccAddress { return nil }

// MsgBridgeAttestBurned is a legacy message type (bridge removed in v1.31.0).
type MsgBridgeAttestBurned struct {
	Validator       string `protobuf:"bytes,1,opt,name=validator,proto3" json:"validator,omitempty"`
	SourceChain     string `protobuf:"bytes,2,opt,name=source_chain,json=sourceChain,proto3" json:"source_chain,omitempty"`
	BurnId          string `protobuf:"bytes,3,opt,name=burn_id,json=burnId,proto3" json:"burn_id,omitempty"`
	MirageRecipient string `protobuf:"bytes,4,opt,name=mirage_recipient,json=mirageRecipient,proto3" json:"mirage_recipient,omitempty"`
	Amount          uint64 `protobuf:"varint,5,opt,name=amount,proto3" json:"amount,omitempty"`
}

func (m *MsgBridgeAttestBurned) Reset()         { *m = MsgBridgeAttestBurned{} }
func (m *MsgBridgeAttestBurned) String() string { return "MsgBridgeAttestBurned (legacy)" }
func (m *MsgBridgeAttestBurned) ProtoMessage()  {}
func (m *MsgBridgeAttestBurned) XXX_MessageName() string {
	return "mirage.core.v1.MsgBridgeAttestBurned"
}
func (m *MsgBridgeAttestBurned) GetSigners() []sdk.AccAddress { return nil }

// MsgBridgeAttestMinted is a legacy message type (bridge removed in v1.31.0).
type MsgBridgeAttestMinted struct {
	Validator        string `protobuf:"bytes,1,opt,name=validator,proto3" json:"validator,omitempty"`
	BurnId           string `protobuf:"bytes,2,opt,name=burn_id,json=burnId,proto3" json:"burn_id,omitempty"`
	DestinationChain string `protobuf:"bytes,3,opt,name=destination_chain,json=destinationChain,proto3" json:"destination_chain,omitempty"`
	DestinationTx    string `protobuf:"bytes,4,opt,name=destination_tx,json=destinationTx,proto3" json:"destination_tx,omitempty"`
	MirageTxHash     string `protobuf:"bytes,5,opt,name=mirage_tx_hash,json=mirageTxHash,proto3" json:"mirage_tx_hash,omitempty"`
}

func (m *MsgBridgeAttestMinted) Reset()         { *m = MsgBridgeAttestMinted{} }
func (m *MsgBridgeAttestMinted) String() string { return "MsgBridgeAttestMinted (legacy)" }
func (m *MsgBridgeAttestMinted) ProtoMessage()  {}
func (m *MsgBridgeAttestMinted) XXX_MessageName() string {
	return "mirage.core.v1.MsgBridgeAttestMinted"
}
func (m *MsgBridgeAttestMinted) GetSigners() []sdk.AccAddress { return nil }
