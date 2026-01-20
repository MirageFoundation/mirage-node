package types

import (
	codectypes "github.com/cosmos/cosmos-sdk/codec/types"
	sdk "github.com/cosmos/cosmos-sdk/types"
	"github.com/cosmos/cosmos-sdk/types/msgservice"
)

// RegisterInterfaces registers the x/core interfaces.
func RegisterInterfaces(registry codectypes.InterfaceRegistry) {
	registry.RegisterImplementations((*sdk.Msg)(nil),
		&MsgPost{}, &MsgEdit{}, &MsgVote{}, &MsgSetUsername{},
		&MsgFollowModerator{}, &MsgUnfollowModerator{},
		&MsgFollowUser{}, &MsgUnfollowUser{},
		&MsgFollowTopic{}, &MsgUnfollowTopic{},
		&MsgBlockPost{}, &MsgUnblockPost{},
		&MsgBlockUser{}, &MsgUnblockUser{},
		&MsgDelete{}, &MsgSendTokens{}, &MsgSetLevel{},
		&MsgPunishValidator{}, &MsgMintTo{}, &MsgUpgradeLevel{},
		&MsgSetAutoRenewal{},
		// IBC and Bridge messages
		&MsgIBCTransfer{},
		&MsgBridgeBurn{},
		&MsgBridgeAttestBurned{},
		&MsgBridgeAttestMinted{},
	)
	msgservice.RegisterMsgServiceDesc(registry, &_Msg_serviceDesc)
}
