package app

import (
	coretypes "mirage/x/core/types"

	sdk "github.com/cosmos/cosmos-sdk/types"
)

// relayMessagePrototypes is the canonical registry of relay-routed message
// types (envelope PoW + RelaySig instead of standard SDK signatures).
//
// isRelayMessage is derived from this list. The PowDecorator.AnteHandle
// switch and RelaySigDecorator.AnteHandle switch MUST stay in lockstep with
// this registry — add a prototype here when introducing a new relay message,
// and cover it in both ante switches. TestRelayMessageRegistryParity pins
// the enumeration.
func relayMessagePrototypes() []sdk.Msg {
	return []sdk.Msg{
		&coretypes.MsgPost{},
		&coretypes.MsgVote{},
		&coretypes.MsgSetUsername{},
		&coretypes.MsgFollowUser{},
		&coretypes.MsgUnfollowUser{},
		&coretypes.MsgJoinCommunity{},
		&coretypes.MsgLeaveCommunity{},
		&coretypes.MsgBlockPost{},
		&coretypes.MsgUnblockPost{},
		&coretypes.MsgBlockUser{},
		&coretypes.MsgUnblockUser{},
		&coretypes.MsgBlockCommunity{},
		&coretypes.MsgUnblockCommunity{},
		&coretypes.MsgDelete{},
		&coretypes.MsgDeleteUser{},
		&coretypes.MsgSendTokens{},
		&coretypes.MsgEdit{},
		&coretypes.MsgSubscribe{},
		&coretypes.MsgSetAutoRenewal{},
		&coretypes.MsgAward{},
		&coretypes.MsgSetBiography{},
		&coretypes.MsgCreateCurationTeam{},
		&coretypes.MsgSetCurationTeamProfile{},
		&coretypes.MsgInviteCurator{},
		&coretypes.MsgRevokeCuratorInvite{},
		&coretypes.MsgAcceptCuratorInvite{},
		&coretypes.MsgDeclineCuratorInvite{},
		&coretypes.MsgLeaveCurationTeam{},
		&coretypes.MsgRemoveCurator{},
		&coretypes.MsgTransferCurationTeam{},
		&coretypes.MsgDeleteCurationTeam{},
		&coretypes.MsgSetCurationPreference{},
		&coretypes.MsgSetCurationPostHidden{},
		&coretypes.MsgSetCurationUserHidden{},
		&coretypes.MsgSetCurationThreadLocked{},
		&coretypes.MsgSetCurationSubscriberOnly{},
		&coretypes.MsgSetCurationTag{},
		&coretypes.MsgSetCurationPostTag{},
		&coretypes.MsgClaimCreatorRewards{},
	}
}

// relayMessageURLs indexes MsgTypeURL for O(1) isRelayMessage checks.
var relayMessageURLs = func() map[string]struct{} {
	m := make(map[string]struct{}, len(relayMessagePrototypes()))
	for _, msg := range relayMessagePrototypes() {
		m[sdk.MsgTypeURL(msg)] = struct{}{}
	}
	return m
}()
