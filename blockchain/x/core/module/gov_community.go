package core

import (
	"context"
	"fmt"
	"strings"

	sdk "github.com/cosmos/cosmos-sdk/types"

	"mirage/x/core/types"
)

func requireGov(authority string) error {
	if authority != govAuthority() {
		return fmt.Errorf("expected gov authority")
	}
	return nil
}

func (am AppModule) GovCreateCommunity(ctx context.Context, req *types.MsgGovCreateCommunity) (*types.MsgGovCreateCommunityResponse, error) {
	if err := requireGov(req.GetAuthority()); err != nil {
		return nil, err
	}
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	if err := am.k.CreateCommunity(sdkCtx, strings.TrimSpace(req.GetFounder()), strings.TrimSpace(req.GetCommunity()), req.GetTitle(), req.GetDescription(), req.GetOriginalTeamName(), req.GetBio(), req.GetPolicy()); err != nil {
		return nil, err
	}
	return &types.MsgGovCreateCommunityResponse{}, nil
}

func (am AppModule) GovSetCommunityFounder(ctx context.Context, req *types.MsgGovSetCommunityFounder) (*types.MsgGovSetCommunityFounderResponse, error) {
	if err := requireGov(req.GetAuthority()); err != nil {
		return nil, err
	}
	wrapped := &types.MsgTransferCommunity{Authority: req.GetAuthority(), Community: req.GetCommunity(), NewFounder: req.GetNewFounder()}
	if _, err := am.TransferCommunity(ctx, wrapped); err != nil {
		return nil, err
	}
	return &types.MsgGovSetCommunityFounderResponse{}, nil
}

func (am AppModule) GovCreateCurationTeam(ctx context.Context, req *types.MsgGovCreateCurationTeam) (*types.MsgGovCreateCurationTeamResponse, error) {
	if err := requireGov(req.GetAuthority()); err != nil {
		return nil, err
	}
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	if _, err := am.k.CreateAlternativeTeam(sdkCtx, strings.TrimSpace(req.GetOwner()), strings.TrimSpace(req.GetCommunity()), req.GetName(), req.GetBio(), req.GetPolicy()); err != nil {
		return nil, err
	}
	return &types.MsgGovCreateCurationTeamResponse{}, nil
}

func (am AppModule) GovSetCurationTeamOwner(ctx context.Context, req *types.MsgGovSetCurationTeamOwner) (*types.MsgGovSetCurationTeamOwnerResponse, error) {
	if err := requireGov(req.GetAuthority()); err != nil {
		return nil, err
	}
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	team, ok, err := am.k.GetCurationTeam(sdkCtx, strings.TrimSpace(req.GetCommunity()), req.GetTeamId())
	if err != nil || !ok {
		return nil, fmt.Errorf("team not found")
	}
	team.Owner = strings.TrimSpace(req.GetNewOwner())
	if err := am.k.SetCurationTeam(sdkCtx, team); err != nil {
		return nil, err
	}
	return &types.MsgGovSetCurationTeamOwnerResponse{}, nil
}

func (am AppModule) GovSetCuratorMembership(ctx context.Context, req *types.MsgGovSetCuratorMembership) (*types.MsgGovSetCuratorMembershipResponse, error) {
	if err := requireGov(req.GetAuthority()); err != nil {
		return nil, err
	}
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	slug := strings.TrimSpace(req.GetCommunity())
	target := strings.TrimSpace(req.GetTarget())
	if !req.GetPresent() {
		if err := am.k.RemoveCuratorFromTeam(sdkCtx, slug, req.GetTeamId(), target, "curator_removed"); err != nil {
			return nil, err
		}
		return &types.MsgGovSetCuratorMembershipResponse{}, nil
	}
	return &types.MsgGovSetCuratorMembershipResponse{}, fmt.Errorf("governance membership add must go through invitation+membership helpers")
}

func (am AppModule) GovSetCommunityPreference(ctx context.Context, req *types.MsgGovSetCommunityPreference) (*types.MsgGovSetCommunityPreferenceResponse, error) {
	if err := requireGov(req.GetAuthority()); err != nil {
		return nil, err
	}
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	owner := strings.TrimSpace(req.GetOwner())
	slug := strings.TrimSpace(req.GetCommunity())
	core, found, err := am.k.LoadProfile(sdkCtx, owner)
	if err != nil || !found {
		return nil, fmt.Errorf("profile not found")
	}
	if !req.GetPresent() {
		if err := am.k.LeaveCommunity(sdkCtx, owner, slug, core.EffectivePaid); err != nil {
			return nil, err
		}
		return &types.MsgGovSetCommunityPreferenceResponse{}, nil
	}
	if _, joined, err := am.k.GetPreference(sdkCtx, owner, slug); err != nil {
		return nil, err
	} else if !joined {
		params := am.k.GetParams(sdkCtx)
		tier := params.GetTierConfig(int(core.Level))
		if err := am.k.JoinCommunity(sdkCtx, owner, slug, core.EffectivePaid, uint32(tier.MaxJoinedCommunities), true); err != nil {
			return nil, err
		}
	}
	if err := am.k.SetCurationPreference(sdkCtx, owner, slug, req.GetMode(), req.GetTeamId(), core.EffectivePaid); err != nil {
		return nil, err
	}
	return &types.MsgGovSetCommunityPreferenceResponse{}, nil
}

func (am AppModule) GovSetCommunityBlock(ctx context.Context, req *types.MsgGovSetCommunityBlock) (*types.MsgGovSetCommunityBlockResponse, error) {
	if err := requireGov(req.GetAuthority()); err != nil {
		return nil, err
	}
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	owner := strings.TrimSpace(req.GetOwner())
	pat := strings.TrimSpace(req.GetCommunity())
	if req.GetBlocked() {
		core, found, err := am.k.LoadProfile(sdkCtx, owner)
		if err != nil || !found {
			return nil, fmt.Errorf("profile not found")
		}
		params := am.k.GetParams(sdkCtx)
		tier := params.GetTierConfig(int(core.Level))
		if err := am.k.AddBlockedCommunity(sdkCtx, owner, pat, uint32(tier.MaxBlockedCommunities)); err != nil {
			return nil, err
		}
	} else {
		if err := am.k.RemoveBlockedCommunity(sdkCtx, owner, pat); err != nil {
			return nil, err
		}
	}
	return &types.MsgGovSetCommunityBlockResponse{}, nil
}

func (am AppModule) GovSetCuratorInvitation(ctx context.Context, req *types.MsgGovSetCuratorInvitation) (*types.MsgGovSetCuratorInvitationResponse, error) {
	if err := requireGov(req.GetAuthority()); err != nil {
		return nil, err
	}
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	slug := strings.TrimSpace(req.GetCommunity())
	invitee := strings.TrimSpace(req.GetInvitee())
	switch req.GetAction() {
	case types.CuratorInvitationAction_CURATOR_INVITATION_ACTION_CREATE:
		team, ok, err := am.k.GetCurationTeam(sdkCtx, slug, req.GetTeamId())
		if err != nil || !ok {
			return nil, fmt.Errorf("team not found")
		}
		if err := am.k.InviteCurator(sdkCtx, team.Owner, slug, req.GetTeamId(), invitee); err != nil {
			return nil, err
		}
	case types.CuratorInvitationAction_CURATOR_INVITATION_ACTION_REVOKE, types.CuratorInvitationAction_CURATOR_INVITATION_ACTION_DECLINE:
		if err := am.k.ClearInvite(sdkCtx, slug, req.GetTeamId(), invitee); err != nil {
			return nil, err
		}
	default:
		return nil, fmt.Errorf("unknown invitation action")
	}
	return &types.MsgGovSetCuratorInvitationResponse{}, nil
}

func (am AppModule) GovSetSubscriptionState(ctx context.Context, req *types.MsgGovSetSubscriptionState) (*types.MsgGovSetSubscriptionStateResponse, error) {
	if err := requireGov(req.GetAuthority()); err != nil {
		return nil, err
	}
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	owner := strings.TrimSpace(req.GetUser())
	core, found, err := am.k.LoadProfile(sdkCtx, owner)
	if err != nil || !found {
		return nil, fmt.Errorf("profile not found")
	}
	now := sdkCtx.BlockTime().Unix()
	if req.GetSubscribed() {
		if req.GetNominalExpiry() <= now {
			return nil, fmt.Errorf("subscribed=true requires expiry after block time")
		}
		if core.SubscriptionExpiry > 0 {
			_ = am.k.RemoveSubscription(sdkCtx, owner, core.SubscriptionExpiry)
		}
		core.SubscriptionExpiry = req.GetNominalExpiry()
		core.AutoRenew = req.GetAutoRenew()
		if err := am.k.SaveProfile(sdkCtx, core); err != nil {
			return nil, err
		}
		if !core.EffectivePaid {
			if err := am.k.TransitionPaidState(sdkCtx, owner, true); err != nil {
				return nil, err
			}
		} else {
			if err := am.k.SetSubscription(sdkCtx, owner, int(core.Level), core.SubscriptionExpiry); err != nil {
				return nil, err
			}
			if err := am.k.ReplaceSubscriptionRenewalSchedule(sdkCtx, owner); err != nil {
				return nil, err
			}
		}
	} else {
		if req.GetNominalExpiry() != 0 || req.GetAutoRenew() {
			return nil, fmt.Errorf("subscribed=false requires expiry 0 and auto_renew false")
		}
		if err := am.k.TransitionPaidState(sdkCtx, owner, false); err != nil {
			return nil, err
		}
	}
	return &types.MsgGovSetSubscriptionStateResponse{}, nil
}

func (am AppModule) GovClaimCreatorRewards(ctx context.Context, req *types.MsgGovClaimCreatorRewards) (*types.MsgGovClaimCreatorRewardsResponse, error) {
	if err := requireGov(req.GetAuthority()); err != nil {
		return nil, err
	}
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	if err := am.k.ClaimCreatorRewards(sdkCtx, strings.TrimSpace(req.GetCreator()), req.GetEpochIds()); err != nil {
		return nil, err
	}
	return &types.MsgGovClaimCreatorRewardsResponse{}, nil
}
