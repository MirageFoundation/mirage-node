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
		&MsgPunishValidator{}, &MsgMintTokens{}, &MsgBurnTokens{}, &MsgUpgradeLevel{},
		&MsgSetAutoRenewal{},
		// Bridge messages
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
		&MsgPunishValidatorResponse{}, &MsgMintTokensResponse{}, &MsgBurnTokensResponse{}, &MsgUpgradeLevelResponse{},
		&MsgSetAutoRenewalResponse{},
		// Bridge responses
		&MsgBridgeBurnResponse{},
		&MsgBridgeAttestBurnedResponse{},
		&MsgBridgeAttestMintedResponse{},
	}
	registry.RegisterImplementations((*tx.MsgResponse)(nil), msgResponseTypes...)

	// Register legacy message types for backwards compatibility (decoding old gov proposals)
	// MsgMintTo was renamed to MsgMintTokens - we need to decode old proposals that used it
	registry.RegisterImplementations((*sdk.Msg)(nil), &MsgMintTo{})
	log.Printf("core/types: registered msg interfaces (msgs=%d responses=%d)", len(msgTypes), len(msgResponseTypes))
}
