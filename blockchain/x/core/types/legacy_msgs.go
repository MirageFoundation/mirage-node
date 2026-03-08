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
