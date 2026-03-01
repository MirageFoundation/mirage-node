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
		&MsgEnableAgent{}, &MsgDisableAgent{},
		&MsgFollowUser{}, &MsgUnfollowUser{},
		&MsgFollowTopic{}, &MsgUnfollowTopic{},
		&MsgBlockPost{}, &MsgUnblockPost{},
		&MsgBlockUser{}, &MsgUnblockUser{},
		&MsgBlockTopic{}, &MsgUnblockTopic{},
		&MsgDelete{}, &MsgDeleteUser{}, &MsgSendTokens{}, &MsgSetLevel{},
		&MsgPunishValidator{}, &MsgMintTokens{}, &MsgBurnTokens{}, &MsgUpgradeLevel{},
		&MsgSetAutoRenewal{},
		// Bridge messages
		&MsgBridgeBurn{},
		&MsgBridgeAttestBurned{},
		&MsgBridgeAttestMinted{},
		// Award
		&MsgAward{},
	}
	registry.RegisterImplementations((*sdk.Msg)(nil), msgTypes...)

	msgResponseTypes := []proto.Message{
		&MsgUpdateParamsResponse{},
		&MsgPostResponse{}, &MsgEditResponse{}, &MsgVoteResponse{}, &MsgSetUsernameResponse{},
		&MsgEnableAgentResponse{}, &MsgDisableAgentResponse{},
		&MsgFollowUserResponse{}, &MsgUnfollowUserResponse{},
		&MsgFollowTopicResponse{}, &MsgUnfollowTopicResponse{},
		&MsgBlockPostResponse{}, &MsgUnblockPostResponse{},
		&MsgBlockUserResponse{}, &MsgUnblockUserResponse{},
		&MsgBlockTopicResponse{}, &MsgUnblockTopicResponse{},
		&MsgDeleteResponse{}, &MsgDeleteUserResponse{}, &MsgSendTokensResponse{}, &MsgSetLevelResponse{},
		&MsgPunishValidatorResponse{}, &MsgMintTokensResponse{}, &MsgBurnTokensResponse{}, &MsgUpgradeLevelResponse{},
		&MsgSetAutoRenewalResponse{},
		// Bridge responses
		&MsgBridgeBurnResponse{},
		&MsgBridgeAttestBurnedResponse{},
		&MsgBridgeAttestMintedResponse{},
		// Award
		&MsgAwardResponse{},
	}
	registry.RegisterImplementations((*tx.MsgResponse)(nil), msgResponseTypes...)

	// Register legacy message types for backwards compatibility (decoding old transactions)
	registry.RegisterImplementations((*sdk.Msg)(nil), &MsgMintTo{})
	registry.RegisterImplementations((*sdk.Msg)(nil), &MsgFollowModerator{}, &MsgUnfollowModerator{})
	log.Printf("core/types: registered msg interfaces (msgs=%d responses=%d)", len(msgTypes), len(msgResponseTypes))
}
