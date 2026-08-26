package types

import (
	"log"

	codectypes "github.com/cosmos/cosmos-sdk/codec/types"
	sdk "github.com/cosmos/cosmos-sdk/types"
	"github.com/cosmos/cosmos-sdk/types/tx"
	proto "github.com/cosmos/gogoproto/proto"
)

func RegisterInterfaces(registry codectypes.InterfaceRegistry) {
	msgTypes := []sdk.Msg{
		&MsgUpdateParams{},
		&MsgPost{}, &MsgEdit{}, &MsgVote{}, &MsgSetUsername{},
		&MsgFollowUser{}, &MsgUnfollowUser{},
		&MsgJoinCommunity{}, &MsgLeaveCommunity{},
		&MsgBlockPost{}, &MsgUnblockPost{},
		&MsgBlockUser{}, &MsgUnblockUser{},
		&MsgBlockCommunity{}, &MsgUnblockCommunity{},
		&MsgDelete{}, &MsgDeleteUser{}, &MsgSendTokens{}, &MsgSetLevel{},
		&MsgPunishValidator{}, &MsgMintTokens{}, &MsgBurnTokens{}, &MsgSubscribe{},
		&MsgSetAutoRenewal{},
		&MsgAward{},
		&MsgSetBiography{},
		&MsgCreateCommunity{}, &MsgSetCommunityMetadata{}, &MsgTransferCommunity{},
		&MsgCreateCurationTeam{}, &MsgSetCurationTeamProfile{},
		&MsgInviteCurator{}, &MsgRevokeCuratorInvite{},
		&MsgAcceptCuratorInvite{}, &MsgDeclineCuratorInvite{},
		&MsgLeaveCurationTeam{}, &MsgRemoveCurator{},
		&MsgTransferCurationTeam{}, &MsgDeleteCurationTeam{},
		&MsgSetCurationPreference{},
		&MsgSetCurationPostHidden{}, &MsgSetCurationUserHidden{},
		&MsgSetCurationThreadLocked{}, &MsgSetCurationSubscriberOnly{},
		&MsgClaimCreatorRewards{},
		&MsgGovCreateCommunity{}, &MsgGovSetCommunityFounder{},
		&MsgGovCreateCurationTeam{}, &MsgGovSetCurationTeamOwner{},
		&MsgGovSetCuratorMembership{}, &MsgGovSetCommunityPreference{},
		&MsgGovSetCommunityBlock{}, &MsgGovSetCuratorInvitation{},
		&MsgGovSetSubscriptionState{}, &MsgGovClaimCreatorRewards{},
	}
	registry.RegisterImplementations((*sdk.Msg)(nil), msgTypes...)

	msgResponseTypes := []proto.Message{
		&MsgUpdateParamsResponse{},
		&MsgPostResponse{}, &MsgEditResponse{}, &MsgVoteResponse{}, &MsgSetUsernameResponse{},
		&MsgFollowUserResponse{}, &MsgUnfollowUserResponse{},
		&MsgJoinCommunityResponse{}, &MsgLeaveCommunityResponse{},
		&MsgBlockPostResponse{}, &MsgUnblockPostResponse{},
		&MsgBlockUserResponse{}, &MsgUnblockUserResponse{},
		&MsgBlockCommunityResponse{}, &MsgUnblockCommunityResponse{},
		&MsgDeleteResponse{}, &MsgDeleteUserResponse{}, &MsgSendTokensResponse{}, &MsgSetLevelResponse{},
		&MsgPunishValidatorResponse{}, &MsgMintTokensResponse{}, &MsgBurnTokensResponse{}, &MsgSubscribeResponse{},
		&MsgSetAutoRenewalResponse{},
		&MsgAwardResponse{},
		&MsgSetBiographyResponse{},
		&MsgCreateCommunityResponse{}, &MsgSetCommunityMetadataResponse{}, &MsgTransferCommunityResponse{},
		&MsgCreateCurationTeamResponse{}, &MsgSetCurationTeamProfileResponse{},
		&MsgInviteCuratorResponse{}, &MsgRevokeCuratorInviteResponse{},
		&MsgAcceptCuratorInviteResponse{}, &MsgDeclineCuratorInviteResponse{},
		&MsgLeaveCurationTeamResponse{}, &MsgRemoveCuratorResponse{},
		&MsgTransferCurationTeamResponse{}, &MsgDeleteCurationTeamResponse{},
		&MsgSetCurationPreferenceResponse{},
		&MsgSetCurationPostHiddenResponse{}, &MsgSetCurationUserHiddenResponse{},
		&MsgSetCurationThreadLockedResponse{}, &MsgSetCurationSubscriberOnlyResponse{},
		&MsgClaimCreatorRewardsResponse{},
		&MsgGovCreateCommunityResponse{}, &MsgGovSetCommunityFounderResponse{},
		&MsgGovCreateCurationTeamResponse{}, &MsgGovSetCurationTeamOwnerResponse{},
		&MsgGovSetCuratorMembershipResponse{}, &MsgGovSetCommunityPreferenceResponse{},
		&MsgGovSetCommunityBlockResponse{}, &MsgGovSetCuratorInvitationResponse{},
		&MsgGovSetSubscriptionStateResponse{}, &MsgGovClaimCreatorRewardsResponse{},
		// Historical decode-only responses.
		&MsgEnableAgentResponse{}, &MsgDisableAgentResponse{}, &MsgSetAgentsResponse{},
		&MsgFollowTopicResponse{}, &MsgUnfollowTopicResponse{},
		&MsgBlockTopicResponse{}, &MsgUnblockTopicResponse{},
		&MsgAnnotateResponse{},
	}
	registry.RegisterImplementations((*tx.MsgResponse)(nil), msgResponseTypes...)

	// Decode-only historical message types (replay, genesis export, old TxMsgData).
	registry.RegisterImplementations((*sdk.Msg)(nil),
		&MsgEnableAgent{}, &MsgDisableAgent{}, &MsgSetAgents{},
		&MsgFollowTopic{}, &MsgUnfollowTopic{},
		&MsgBlockTopic{}, &MsgUnblockTopic{},
		&MsgAnnotate{},
		&MsgMintTo{},
		&MsgFollowModerator{}, &MsgUnfollowModerator{},
		&MsgBridgeBurn{}, &MsgBridgeAttest{}, &MsgBridgeMinted{},
		&MsgBridgeAttestBurned{}, &MsgBridgeAttestMinted{},
	)
	log.Printf("core/types: registered msg interfaces (msgs=%d responses=%d)", len(msgTypes), len(msgResponseTypes))
}

func RetiredMsgTypeURLs() map[string]struct{} {
	return map[string]struct{}{
		sdk.MsgTypeURL(&MsgEnableAgent{}):   {},
		sdk.MsgTypeURL(&MsgDisableAgent{}):  {},
		sdk.MsgTypeURL(&MsgSetAgents{}):     {},
		sdk.MsgTypeURL(&MsgFollowTopic{}):   {},
		sdk.MsgTypeURL(&MsgUnfollowTopic{}): {},
		sdk.MsgTypeURL(&MsgBlockTopic{}):    {},
		sdk.MsgTypeURL(&MsgUnblockTopic{}):  {},
		sdk.MsgTypeURL(&MsgAnnotate{}):      {},
	}
}
