package core

import (
	"context"
	"encoding/binary"
	"strings"

	sdk "github.com/cosmos/cosmos-sdk/types"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"

	"mirage/x/core/types"
)

func (am AppModule) Community(ctx context.Context, req *types.QueryCommunityRequest) (*types.QueryCommunityResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	slug := strings.TrimSpace(req.GetSlug())
	c, found, err := am.k.GetCommunity(sdkCtx, slug)
	if err != nil {
		return nil, err
	}
	if !found {
		return nil, status.Errorf(codes.NotFound, "community %s not found", slug)
	}
	dc, err := am.k.GetDefaultCount(sdkCtx, slug)
	if err != nil {
		return nil, err
	}
	return &types.QueryCommunityResponse{Community: c, DefaultCount: dc}, nil
}

func (am AppModule) Communities(ctx context.Context, req *types.QueryCommunitiesRequest) (*types.QueryCommunitiesResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	var out []*types.Community
	err := am.k.IterPrefix(sdkCtx, []byte(types.PfxCommunity), 100, func(_, value []byte) error {
		var c types.Community
		if err := am.k.CDC().Unmarshal(value, &c); err != nil {
			return err
		}
		out = append(out, &c)
		return nil
	})
	if err != nil {
		return nil, err
	}
	return &types.QueryCommunitiesResponse{Communities: out}, nil
}

func (am AppModule) FoundedCommunities(ctx context.Context, req *types.QueryFoundedCommunitiesRequest) (*types.QueryFoundedCommunitiesResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	owner := strings.TrimSpace(req.GetAddress())
	var out []*types.Community
	err := am.k.IterPrefix(sdkCtx, types.KeyCommunityFounderPrefix(owner), 100, func(key, _ []byte) error {
		pfx := types.KeyCommunityFounderPrefix(owner)
		rest := key[len(pfx):]
		n := int(rest[0])<<8 | int(rest[1])
		slug := string(rest[2 : 2+n])
		c, found, err := am.k.GetCommunity(sdkCtx, slug)
		if err != nil || !found {
			return err
		}
		out = append(out, c)
		return nil
	})
	if err != nil {
		return nil, err
	}
	return &types.QueryFoundedCommunitiesResponse{Communities: out}, nil
}

func (am AppModule) CurationTeam(ctx context.Context, req *types.QueryCurationTeamRequest) (*types.QueryCurationTeamResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	t, found, err := am.k.GetCurationTeam(sdkCtx, strings.TrimSpace(req.GetCommunity()), req.GetTeamId())
	if err != nil {
		return nil, err
	}
	if !found {
		return nil, status.Errorf(codes.NotFound, "team not found")
	}
	return &types.QueryCurationTeamResponse{Team: t}, nil
}

func (am AppModule) CurationTeams(ctx context.Context, req *types.QueryCurationTeamsRequest) (*types.QueryCurationTeamsResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	slug := strings.TrimSpace(req.GetCommunity())
	var out []*types.CurationTeam
	err := am.k.IterPrefix(sdkCtx, types.KeyCurationTeamPrefix(slug), 100, func(_, value []byte) error {
		var t types.CurationTeam
		if err := am.k.CDC().Unmarshal(value, &t); err != nil {
			return err
		}
		out = append(out, &t)
		return nil
	})
	if err != nil {
		return nil, err
	}
	return &types.QueryCurationTeamsResponse{Teams: out}, nil
}

func (am AppModule) CurationTeamMembers(ctx context.Context, req *types.QueryCurationTeamMembersRequest) (*types.QueryCurationTeamMembersResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	var out []*types.CurationTeamMember
	err := am.k.IterPrefix(sdkCtx, types.KeyCurationTeamMemberPrefix(strings.TrimSpace(req.GetCommunity()), req.GetTeamId()), 100, func(_, value []byte) error {
		var m types.CurationTeamMember
		if err := am.k.CDC().Unmarshal(value, &m); err != nil {
			return err
		}
		out = append(out, &m)
		return nil
	})
	if err != nil {
		return nil, err
	}
	return &types.QueryCurationTeamMembersResponse{Members: out}, nil
}

func (am AppModule) PendingCuratorInvitations(ctx context.Context, req *types.QueryPendingCuratorInvitationsRequest) (*types.QueryPendingCuratorInvitationsResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	owner := strings.TrimSpace(req.GetAddress())
	var out []*types.PendingCuratorInvitation
	err := am.k.IterPrefix(sdkCtx, types.KeyCurationInviteRevPrefix(owner), 100, func(key, _ []byte) error {
		slug, teamID, err := parseInviteRevKey(owner, key)
		if err != nil {
			return err
		}
		inviterBz, err := am.k.GetRaw(sdkCtx, types.KeyCurationInvite(slug, teamID, owner))
		if err != nil {
			return err
		}
		out = append(out, &types.PendingCuratorInvitation{
			Community: slug,
			TeamId:    teamID,
			Invitee:   owner,
			Inviter:   string(inviterBz),
		})
		return nil
	})
	if err != nil {
		return nil, err
	}
	return &types.QueryPendingCuratorInvitationsResponse{Invitations: out}, nil
}

func (am AppModule) CurationMemberships(ctx context.Context, req *types.QueryCurationMembershipsRequest) (*types.QueryCurationMembershipsResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	owner := strings.TrimSpace(req.GetAddress())
	var out []*types.CurationMembership
	err := am.k.IterPrefix(sdkCtx, types.KeyCurationTeamUserPrefix(owner), 100, func(key, value []byte) error {
		pfx := types.KeyCurationTeamUserPrefix(owner)
		slug, _, err := parseLp(key[len(pfx):])
		if err != nil {
			return err
		}
		if len(value) != 8 {
			return fmtError("malformed ctu value")
		}
		out = append(out, &types.CurationMembership{
			Community: slug,
			TeamId:    binary.BigEndian.Uint64(value),
		})
		return nil
	})
	if err != nil {
		return nil, err
	}
	return &types.QueryCurationMembershipsResponse{Memberships: out}, nil
}

func (am AppModule) CommunityPreference(ctx context.Context, req *types.QueryCommunityPreferenceRequest) (*types.QueryCommunityPreferenceResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	joined, _, effective, _, effectiveTeam, err := am.k.ResolveEffectivePreference(sdkCtx, strings.TrimSpace(req.GetOwner()), strings.TrimSpace(req.GetCommunity()))
	if err != nil {
		return nil, err
	}
	if !joined {
		return nil, status.Errorf(codes.NotFound, "not joined")
	}
	pref, _, err := am.k.GetPreference(sdkCtx, strings.TrimSpace(req.GetOwner()), strings.TrimSpace(req.GetCommunity()))
	if err != nil {
		return nil, err
	}
	return &types.QueryCommunityPreferenceResponse{Stored: pref, EffectiveMode: effective, EffectiveTeamId: effectiveTeam}, nil
}

func (am AppModule) PostMetadata(ctx context.Context, req *types.QueryPostMetadataRequest) (*types.QueryPostMetadataResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	m, found, err := am.k.GetPostMetadata(sdkCtx, strings.ToLower(req.GetTxhash()))
	if err != nil {
		return nil, err
	}
	if !found {
		return nil, status.Errorf(codes.NotFound, "post metadata not found")
	}
	return &types.QueryPostMetadataResponse{Metadata: m}, nil
}

func (am AppModule) CreatorEpoch(ctx context.Context, req *types.QueryCreatorEpochRequest) (*types.QueryCreatorEpochResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	var ce types.CreatorEpoch
	found, err := am.k.GetProto(sdkCtx, types.KeyCreatorEpoch(req.GetEpochId()), &ce)
	if err != nil {
		return nil, err
	}
	if !found {
		return nil, status.Errorf(codes.NotFound, "epoch not found")
	}
	return &types.QueryCreatorEpochResponse{Epoch: &ce}, nil
}

func (am AppModule) CreatorAccruals(ctx context.Context, req *types.QueryCreatorAccrualsRequest) (*types.QueryCreatorAccrualsResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	creator := strings.TrimSpace(req.GetCreator())
	var out []*types.CreatorAccrual
	err := am.k.IterPrefix(sdkCtx, types.KeyCreatorEpochIdxPrefix(types.MustAcc(creator)), 100, func(key, _ []byte) error {
		pfx := types.KeyCreatorEpochIdxPrefix(types.MustAcc(creator))
		if len(key) < len(pfx)+8 {
			return fmtError("malformed eca idx")
		}
		epoch := int64(binary.BigEndian.Uint64(key[len(pfx):]))
		var acc types.CreatorAccrual
		found, err := am.k.GetProto(sdkCtx, types.KeyEpochCreatorAccrual(epoch, types.MustAcc(creator)), &acc)
		if err != nil || !found {
			return err
		}
		out = append(out, &acc)
		return nil
	})
	if err != nil {
		return nil, err
	}
	return &types.QueryCreatorAccrualsResponse{Accruals: out}, nil
}

func (am AppModule) TargetEarnings(ctx context.Context, req *types.QueryTargetEarningsRequest) (*types.QueryTargetEarningsResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	h, err := types.HashBytes(strings.ToLower(strings.TrimSpace(req.GetTarget())))
	if err != nil {
		return nil, err
	}
	var out []*types.TargetEarning
	err = am.k.IterPrefix(sdkCtx, concatQuery([]byte(types.PfxTargetEpoch), h), 100, func(key, _ []byte) error {
		if len(key) < len(types.PfxTargetEpoch)+32+8 {
			return fmtError("malformed ectarget key")
		}
		epoch := int64(binary.BigEndian.Uint64(key[len(key)-8:]))
		var te types.TargetEarning
		found, err := am.k.GetProto(sdkCtx, types.KeyEpochTarget(epoch, h), &te)
		if err != nil || !found {
			return err
		}
		out = append(out, &te)
		return nil
	})
	if err != nil {
		return nil, err
	}
	return &types.QueryTargetEarningsResponse{Earnings: out}, nil
}

func (am AppModule) SubscriptionTranches(ctx context.Context, req *types.QuerySubscriptionTranchesRequest) (*types.QuerySubscriptionTranchesResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	addr := strings.TrimSpace(req.GetAddress())
	var out []*types.SubscriptionTranche
	err := am.k.IterPrefix(sdkCtx, types.KeyTrancheRecipientPrefix(addr), 100, func(key, _ []byte) error {
		pfx := types.KeyTrancheRecipientPrefix(addr)
		if len(key) < len(pfx)+8 {
			return fmtError("malformed tranche recipient idx")
		}
		id := binary.BigEndian.Uint64(key[len(pfx):])
		var t types.SubscriptionTranche
		found, err := am.k.GetProto(sdkCtx, types.KeyTranche(id), &t)
		if err != nil || !found {
			return err
		}
		out = append(out, &t)
		return nil
	})
	if err != nil {
		return nil, err
	}
	return &types.QuerySubscriptionTranchesResponse{Tranches: out}, nil
}

func parseInviteRevKey(owner string, key []byte) (string, uint64, error) {
	pfx := types.KeyCurationInviteRevPrefix(owner)
	return parseSlugTeam(key[len(pfx):])
}

func parseSlugTeam(rest []byte) (string, uint64, error) {
	slug, rest, err := parseLp(rest)
	if err != nil {
		return "", 0, err
	}
	if len(rest) != 8 {
		return "", 0, fmtError("expected team id")
	}
	return slug, binary.BigEndian.Uint64(rest), nil
}

func parseLp(rest []byte) (string, []byte, error) {
	if len(rest) < 2 {
		return "", nil, fmtError("lp too short")
	}
	n := int(binary.BigEndian.Uint16(rest[:2]))
	if len(rest) < 2+n {
		return "", nil, fmtError("lp truncated")
	}
	return string(rest[2 : 2+n]), rest[2+n:], nil
}

func concatQuery(parts ...[]byte) []byte {
	n := 0
	for _, p := range parts {
		n += len(p)
	}
	out := make([]byte, 0, n)
	for _, p := range parts {
		out = append(out, p...)
	}
	return out
}

func fmtError(msg string) error {
	return status.Errorf(codes.Internal, "%s", msg)
}

func (am AppModule) SubscriptionRenewal(ctx context.Context, req *types.QuerySubscriptionRenewalRequest) (*types.QuerySubscriptionRenewalResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	var st types.SubscriptionRenewalState
	found, err := am.k.GetProto(sdkCtx, types.KeySubRenewalState(strings.TrimSpace(req.GetAddress())), &st)
	if err != nil {
		return nil, err
	}
	if !found {
		return &types.QuerySubscriptionRenewalResponse{}, nil
	}
	cnt, _, err := am.k.GetU32(sdkCtx, types.KeyCurationTeamUserCount(strings.TrimSpace(req.GetAddress())))
	if err != nil {
		return nil, err
	}
	return &types.QuerySubscriptionRenewalResponse{State: &st, CurationMembershipCount: cnt}, nil
}

func (am AppModule) SubscriberQuota(ctx context.Context, req *types.QuerySubscriberQuotaRequest) (*types.QuerySubscriberQuotaResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	params := am.k.GetParams(sdkCtx)
	q, err := am.k.GetSubscriberQuota(sdkCtx, strings.TrimSpace(req.GetAddress()))
	if err != nil {
		return nil, err
	}
	epoch := types.UTCEpoch(sdkCtx.BlockTime().Unix())
	used := q.Count
	if q.UtcEpoch != epoch {
		used = 0
	}
	remaining := uint64(0)
	if params.SubscriberDailyRelayLimit > used {
		remaining = params.SubscriberDailyRelayLimit - used
	}
	return &types.QuerySubscriberQuotaResponse{
		Epoch:     epoch,
		Limit:     params.SubscriberDailyRelayLimit,
		Used:      used,
		Remaining: remaining,
		ResetAt:   (epoch + 1) * 86400,
	}, nil
}

func (am AppModule) CreatorLiability(ctx context.Context, req *types.QueryCreatorLiabilityRequest) (*types.QueryCreatorLiabilityResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	liab, err := am.k.GetCreatorLiability(sdkCtx)
	if err != nil {
		return nil, err
	}
	surplus, err := am.k.GetCreatorActivationSurplus(sdkCtx)
	if err != nil {
		return nil, err
	}
	bal := am.k.CreatorPoolBalance(sdkCtx)
	return &types.QueryCreatorLiabilityResponse{
		Liability:         liab.String(),
		ModuleBalance:     bal.String(),
		ActivationSurplus: surplus.String(),
	}, nil
}

