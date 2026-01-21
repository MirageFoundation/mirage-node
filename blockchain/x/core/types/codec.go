package types

import (
	"log"

	codectypes "github.com/cosmos/cosmos-sdk/codec/types"
	sdk "github.com/cosmos/cosmos-sdk/types"
	"github.com/cosmos/cosmos-sdk/types/tx"
	proto "github.com/cosmos/gogoproto/proto"
)

// RegisterInterfaces registers the x/core interfaces.
func RegisterInterfaces(registry codectypes.InterfaceRegistry) {
	// Register message implementations for sdk.Msg interface
	msgTypes := []sdk.Msg{
		&MsgUpdateParams{},
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
	}
	registry.RegisterImplementations((*sdk.Msg)(nil), msgTypes...)

	msgResponseTypes := []proto.Message{
		&MsgUpdateParamsResponse{},
		&MsgPostResponse{}, &MsgEditResponse{}, &MsgVoteResponse{}, &MsgSetUsernameResponse{},
		&MsgFollowModeratorResponse{}, &MsgUnfollowModeratorResponse{},
		&MsgFollowUserResponse{}, &MsgUnfollowUserResponse{},
		&MsgFollowTopicResponse{}, &MsgUnfollowTopicResponse{},
		&MsgBlockPostResponse{}, &MsgUnblockPostResponse{},
		&MsgBlockUserResponse{}, &MsgUnblockUserResponse{},
		&MsgDeleteResponse{}, &MsgSendTokensResponse{}, &MsgSetLevelResponse{},
		&MsgPunishValidatorResponse{}, &MsgMintToResponse{}, &MsgUpgradeLevelResponse{},
		&MsgSetAutoRenewalResponse{},
		// IBC and Bridge responses
		&MsgIBCTransferResponse{},
		&MsgBridgeBurnResponse{},
		&MsgBridgeAttestBurnedResponse{},
		&MsgBridgeAttestMintedResponse{},
	}
	registry.RegisterImplementations((*tx.MsgResponse)(nil), msgResponseTypes...)
	log.Printf("core/types: registered msg interfaces (msgs=%d responses=%d)", len(msgTypes), len(msgResponseTypes))
}
