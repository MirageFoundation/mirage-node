package core

import (
	"context"
	"encoding/binary"
	"strings"

	sdk "github.com/cosmos/cosmos-sdk/types"
	query "github.com/cosmos/cosmos-sdk/types/query"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"

	"mirage/x/core/types"
)

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
	key, limit, err := v139Page(req.GetPagination())
	if err != nil {
		return nil, err
	}
	out, nextKey, err := am.k.GetCurationTeamsPaginated(sdkCtx, types.KeyCurationTeamPrefix(slug), key, limit, req.GetIncludeDeleted())
	if err != nil {
		return nil, err
	}
	return &types.QueryCurationTeamsResponse{Teams: out, Pagination: teamPageResponse(nextKey)}, nil
}

func (am AppModule) AllCurationTeams(ctx context.Context, req *types.QueryAllCurationTeamsRequest) (*types.QueryAllCurationTeamsResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	key, limit, err := v139Page(req.GetPagination())
	if err != nil {
		return nil, err
	}
	out, nextKey, err := am.k.GetCurationTeamsPaginated(sdkCtx, []byte(types.PfxCurationTeam), key, limit, req.GetIncludeDeleted())
	if err != nil {
		return nil, err
	}
	return &types.QueryAllCurationTeamsResponse{Teams: out, Pagination: teamPageResponse(nextKey)}, nil
}

func teamPageResponse(nextKey []byte) *query.PageResponse {
	if len(nextKey) == 0 {
		return nil
	}
	return &query.PageResponse{NextKey: nextKey}
}

func v139Page(page *query.PageRequest) ([]byte, uint64, error) {
	if page == nil {
		return nil, 0, nil
	}
	if page.GetOffset() != 0 {
		return nil, 0, status.Error(codes.InvalidArgument, "pagination offset is not supported; use pagination.key")
	}
	if page.GetReverse() {
		return nil, 0, status.Error(codes.InvalidArgument, "reverse pagination is not supported")
	}
	if page.GetCountTotal() {
		return nil, 0, status.Error(codes.InvalidArgument, "count_total pagination is not supported")
	}
	return page.GetKey(), page.GetLimit(), nil
}

func (am AppModule) CurationTeamMembers(ctx context.Context, req *types.QueryCurationTeamMembersRequest) (*types.QueryCurationTeamMembersResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	key, limit, err := v139Page(req.GetPagination())
	if err != nil {
		return nil, err
	}
	out, nextKey, err := am.k.GetCurationTeamMembersPaginated(
		sdkCtx,
		types.KeyCurationTeamMemberPrefix(strings.TrimSpace(req.GetCommunity()), req.GetTeamId()),
		key,
		limit,
	)
	if err != nil {
		return nil, err
	}
	return &types.QueryCurationTeamMembersResponse{Members: out, Pagination: teamPageResponse(nextKey)}, nil
}

func (am AppModule) PendingCuratorInvitations(ctx context.Context, req *types.QueryPendingCuratorInvitationsRequest) (*types.QueryPendingCuratorInvitationsResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	owner := strings.TrimSpace(req.GetAddress())
	if _, err := types.CanonicalAccBytes(owner); err != nil {
		return nil, status.Error(codes.InvalidArgument, err.Error())
	}
	key, limit, err := v139Page(req.GetPagination())
	if err != nil {
		return nil, err
	}
	out, nextKey, err := am.k.GetPendingCuratorInvitationsPaginated(sdkCtx, owner, key, limit)
	if err != nil {
		return nil, err
	}
	return &types.QueryPendingCuratorInvitationsResponse{Invitations: out, Pagination: teamPageResponse(nextKey)}, nil
}

func (am AppModule) CurationMemberships(ctx context.Context, req *types.QueryCurationMembershipsRequest) (*types.QueryCurationMembershipsResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	owner := strings.TrimSpace(req.GetAddress())
	if _, err := types.CanonicalAccBytes(owner); err != nil {
		return nil, status.Error(codes.InvalidArgument, err.Error())
	}
	key, limit, err := v139Page(req.GetPagination())
	if err != nil {
		return nil, err
	}
	out, nextKey, err := am.k.GetCurationMembershipsPaginated(sdkCtx, owner, key, limit)
	if err != nil {
		return nil, err
	}
	return &types.QueryCurationMembershipsResponse{Memberships: out, Pagination: teamPageResponse(nextKey)}, nil
}

func (am AppModule) CommunityPreference(ctx context.Context, req *types.QueryCommunityPreferenceRequest) (*types.QueryCommunityPreferenceResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	owner := strings.TrimSpace(req.GetOwner())
	if _, err := types.CanonicalAccBytes(owner); err != nil {
		return nil, status.Error(codes.InvalidArgument, err.Error())
	}
	joined, _, effective, _, effectiveTeam, err := am.k.ResolveEffectivePreference(sdkCtx, owner, strings.TrimSpace(req.GetCommunity()))
	if err != nil {
		return nil, err
	}
	if !joined {
		return nil, status.Errorf(codes.NotFound, "not joined")
	}
	pref, _, err := am.k.GetPreference(sdkCtx, owner, strings.TrimSpace(req.GetCommunity()))
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
	creatorBytes, err := types.CanonicalAccBytes(creator)
	if err != nil {
		return nil, status.Error(codes.InvalidArgument, err.Error())
	}
	key, limit, err := v139Page(req.GetPagination())
	if err != nil {
		return nil, err
	}
	out, nextKey, err := am.k.GetCreatorAccrualsPaginated(sdkCtx, creatorBytes, key, limit)
	if err != nil {
		return nil, err
	}
	return &types.QueryCreatorAccrualsResponse{Accruals: out, Pagination: teamPageResponse(nextKey)}, nil
}

func (am AppModule) CreatorEpochAccruals(
	ctx context.Context,
	req *types.QueryCreatorEpochAccrualsRequest,
) (*types.QueryCreatorEpochAccrualsResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	key, limit, err := v139Page(req.GetPagination())
	if err != nil {
		return nil, err
	}
	out, nextKey, err := am.k.GetCreatorEpochAccrualsPaginated(sdkCtx, req.GetEpochId(), key, limit)
	if err != nil {
		return nil, err
	}
	return &types.QueryCreatorEpochAccrualsResponse{Accruals: out, Pagination: teamPageResponse(nextKey)}, nil
}

func (am AppModule) CreatorEpochTargets(
	ctx context.Context,
	req *types.QueryCreatorEpochTargetsRequest,
) (*types.QueryCreatorEpochTargetsResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	key, limit, err := v139Page(req.GetPagination())
	if err != nil {
		return nil, err
	}
	out, nextKey, err := am.k.GetCreatorEpochTargetsPaginated(sdkCtx, req.GetEpochId(), key, limit)
	if err != nil {
		return nil, err
	}
	return &types.QueryCreatorEpochTargetsResponse{Earnings: out, Pagination: teamPageResponse(nextKey)}, nil
}

func (am AppModule) TargetEarnings(ctx context.Context, req *types.QueryTargetEarningsRequest) (*types.QueryTargetEarningsResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	h, err := types.HashBytes(strings.ToLower(strings.TrimSpace(req.GetTarget())))
	if err != nil {
		return nil, status.Error(codes.InvalidArgument, err.Error())
	}
	key, limit, err := v139Page(req.GetPagination())
	if err != nil {
		return nil, err
	}
	out, nextKey, err := am.k.GetTargetEarningsPaginated(sdkCtx, h, key, limit)
	if err != nil {
		return nil, err
	}
	return &types.QueryTargetEarningsResponse{Earnings: out, Pagination: teamPageResponse(nextKey)}, nil
}

func (am AppModule) SubscriptionTranches(ctx context.Context, req *types.QuerySubscriptionTranchesRequest) (*types.QuerySubscriptionTranchesResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	addr := strings.TrimSpace(req.GetAddress())
	if _, err := types.CanonicalAccBytes(addr); err != nil {
		return nil, status.Error(codes.InvalidArgument, err.Error())
	}
	key, limit, err := v139Page(req.GetPagination())
	if err != nil {
		return nil, err
	}
	out, nextKey, err := am.k.GetSubscriptionTranchesPaginated(sdkCtx, addr, key, limit)
	if err != nil {
		return nil, err
	}
	return &types.QuerySubscriptionTranchesResponse{Tranches: out, Pagination: teamPageResponse(nextKey)}, nil
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
	addr := strings.TrimSpace(req.GetAddress())
	if _, err := types.CanonicalAccBytes(addr); err != nil {
		return nil, status.Error(codes.InvalidArgument, err.Error())
	}
	var st types.SubscriptionRenewalState
	found, err := am.k.GetProto(sdkCtx, types.KeySubRenewalState(addr), &st)
	if err != nil {
		return nil, err
	}
	if !found {
		return &types.QuerySubscriptionRenewalResponse{}, nil
	}
	cnt, _, err := am.k.GetU32(sdkCtx, types.KeyCurationTeamUserCount(addr))
	if err != nil {
		return nil, err
	}
	return &types.QuerySubscriptionRenewalResponse{State: &st, CurationMembershipCount: cnt}, nil
}

func (am AppModule) SubscriberQuota(ctx context.Context, req *types.QuerySubscriberQuotaRequest) (*types.QuerySubscriberQuotaResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	params := am.k.GetParams(sdkCtx)
	addr := strings.TrimSpace(req.GetAddress())
	if _, err := types.CanonicalAccBytes(addr); err != nil {
		return nil, status.Error(codes.InvalidArgument, err.Error())
	}
	core, found, err := am.k.LoadProfile(sdkCtx, addr)
	if err != nil {
		return nil, err
	}
	level := 0
	if found {
		level = int(core.Level)
	}
	limit := params.DailyRelayLimit(level)
	q, err := am.k.GetSubscriberQuota(sdkCtx, addr)
	if err != nil {
		return nil, err
	}
	epoch := types.UTCEpoch(sdkCtx.BlockTime().Unix())
	used := q.Count
	if q.UtcEpoch != epoch {
		used = 0
	}
	remaining := uint64(0)
	if limit > used {
		remaining = limit - used
	}
	return &types.QuerySubscriberQuotaResponse{
		Epoch:     epoch,
		Limit:     limit,
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

func (am AppModule) CreatorSchedule(ctx context.Context, req *types.QueryCreatorScheduleRequest) (*types.QueryCreatorScheduleResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	sched, err := am.k.GetCreatorSchedule(sdkCtx)
	if err != nil {
		return nil, err
	}
	clock, err := am.k.GetCreatorClock(sdkCtx)
	if err != nil {
		return nil, err
	}
	return &types.QueryCreatorScheduleResponse{
		OriginEpoch:  sched.OriginEpoch,
		OriginUnix:   sched.OriginUnix,
		EpochSeconds: sched.EpochSeconds,
		CurrentEpoch: clock,
	}, nil
}

func (am AppModule) TerminalCreatorEpochs(
	ctx context.Context,
	req *types.QueryTerminalCreatorEpochsRequest,
) (*types.QueryTerminalCreatorEpochsResponse, error) {
	if req.GetCutoffDeadlineUnix() < 0 {
		return nil, status.Error(codes.InvalidArgument, "cutoff_deadline_unix must be non-negative")
	}
	key, limit, err := v139Page(req.GetPagination())
	if err != nil {
		return nil, err
	}
	epochs, nextKey, err := am.k.GetTerminalCreatorEpochsPaginated(
		sdk.UnwrapSDKContext(ctx),
		req.GetCutoffDeadlineUnix(),
		key,
		limit,
	)
	if err != nil {
		return nil, err
	}
	return &types.QueryTerminalCreatorEpochsResponse{
		Epochs:     epochs,
		Pagination: teamPageResponse(nextKey),
	}, nil
}
