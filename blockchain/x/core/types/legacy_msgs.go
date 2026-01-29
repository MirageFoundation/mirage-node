package types

import (
	sdk "github.com/cosmos/cosmos-sdk/types"
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

func (m *MsgMintTo) Reset()         { *m = MsgMintTo{} }
func (m *MsgMintTo) String() string { return "MsgMintTo (legacy)" }
func (m *MsgMintTo) ProtoMessage()  {}

// XXX_MessageName returns the proto message name for type URL resolution
func (m *MsgMintTo) XXX_MessageName() string { return "mirage.core.v1.MsgMintTo" }

// Implement sdk.Msg interface (minimal, just for registration)
func (m *MsgMintTo) GetSigners() []sdk.AccAddress { return nil }
