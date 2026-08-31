package core

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"strings"

	"github.com/cosmos/cosmos-sdk/crypto/keys/secp256k1"
	sdk "github.com/cosmos/cosmos-sdk/types"
	authtypes "github.com/cosmos/cosmos-sdk/x/auth/types"
	govtypes "github.com/cosmos/cosmos-sdk/x/gov/types"

	"mirage/x/core/types"
)

func (am AppModule) envelopeOwner(req interface{ GetEnvelopePubkey() []byte }) (string, error) {
	pk := req.GetEnvelopePubkey()
	if len(pk) != 33 {
		return "", fmt.Errorf("invalid envelope_pubkey length")
	}
	pub := secp256k1.PubKey{Key: pk}
	return sdk.AccAddress(pub.Address()).String(), nil
}

func (am AppModule) consumeQuota(ctx sdk.Context, owner string) error {
	return am.k.ConsumeSubscriberQuota(ctx, owner)
}

func (am AppModule) requirePaid(ctx sdk.Context, owner, reason string) (types.ProfileCore, error) {
	core, err := am.requireUsername(ctx, owner, reason)
	if err != nil {
		return types.ProfileCore{}, err
	}
	if !core.EffectivePaid {
		return types.ProfileCore{}, fmt.Errorf("%s requires an active subscriber", reason)
	}
	return core, nil
}

func (am AppModule) requireCuratorEligible(ctx sdk.Context, owner, reason string) (types.ProfileCore, error) {
	core, err := am.requireUsername(ctx, owner, reason)
	if err != nil {
		return types.ProfileCore{}, err
	}
	if !types.CanCurate(core) {
		return types.ProfileCore{}, fmt.Errorf("%s requires an active subscriber or admin", reason)
	}
	return core, nil
}

func govAuthority() string {
	return authtypes.NewModuleAddress(govtypes.ModuleName).String()
}

func (am AppModule) JoinCommunity(ctx context.Context, req *types.MsgJoinCommunity) (*types.MsgJoinCommunityResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	owner, err := am.envelopeOwner(req)
	if err != nil {
		return nil, err
	}
	core, err := am.requireUsername(sdkCtx, owner, "JoinCommunity")
	if err != nil {
		return nil, err
	}
	if err := am.consumeQuota(sdkCtx, owner); err != nil {
		return nil, err
	}
	params := am.k.GetParams(sdkCtx)
	tier := params.GetTierConfig(int(core.Level))
	if tier == nil {
		return nil, fmt.Errorf("tier config not found")
	}
	slug := strings.TrimSpace(req.GetCommunity())
	if err := types.ValidateCommunitySlug(slug, uint64(params.MinCommunitySize), uint64(params.MaxCommunitySize)); err != nil {
		return nil, err
	}
	if err := am.k.JoinCommunity(sdkCtx, owner, slug, uint32(tier.MaxJoinedCommunities)); err != nil {
		return nil, err
	}
	return &types.MsgJoinCommunityResponse{}, nil
}

func (am AppModule) LeaveCommunity(ctx context.Context, req *types.MsgLeaveCommunity) (*types.MsgLeaveCommunityResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	owner, err := am.envelopeOwner(req)
	if err != nil {
		return nil, err
	}
	core, err := am.requireUsername(sdkCtx, owner, "LeaveCommunity")
	if err != nil {
		return nil, err
	}
	if err := am.consumeQuota(sdkCtx, owner); err != nil {
		return nil, err
	}
	if err := am.k.LeaveCommunity(sdkCtx, owner, strings.TrimSpace(req.GetCommunity()), core.EffectivePaid); err != nil {
		return nil, err
	}
	return &types.MsgLeaveCommunityResponse{}, nil
}

func (am AppModule) CreateCommunity(ctx context.Context, req *types.MsgCreateCommunity) (*types.MsgCreateCommunityResponse, error) {
	return nil, fmt.Errorf("retired message MsgCreateCommunity is not accepted after v1.39.0")
}

func (am AppModule) SetCommunityMetadata(ctx context.Context, req *types.MsgSetCommunityMetadata) (*types.MsgSetCommunityMetadataResponse, error) {
	return nil, fmt.Errorf("retired message MsgSetCommunityMetadata is not accepted after v1.39.0")
}

func (am AppModule) TransferCommunity(ctx context.Context, req *types.MsgTransferCommunity) (*types.MsgTransferCommunityResponse, error) {
	return nil, fmt.Errorf("retired message MsgTransferCommunity is not accepted after v1.39.0")
}

func (am AppModule) BlockCommunity(ctx context.Context, req *types.MsgBlockCommunity) (*types.MsgBlockCommunityResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	owner, err := am.envelopeOwner(req)
	if err != nil {
		return nil, err
	}
	core, err := am.requireUsername(sdkCtx, owner, "BlockCommunity")
	if err != nil {
		return nil, err
	}
	if err := am.consumeQuota(sdkCtx, owner); err != nil {
		return nil, err
	}
	params := am.k.GetParams(sdkCtx)
	tier := params.GetTierConfig(int(core.Level))
	if tier == nil {
		return nil, fmt.Errorf("tier config not found")
	}
	pat := strings.TrimSpace(req.GetCommunity())
	if err := validateBlockedTopicPattern(pat, uint64(params.MaxCommunitySize), uint64(params.MinCommunitySize)); err != nil {
		return nil, err
	}
	// A zero cap means the list is disabled, exactly as it does for blocked
	// users and posts. AddBlockedCommunity treats zero as "never evict", so
	// without this guard a zero limit would instead permit an unbounded list.
	if tier.MaxBlockedCommunities == 0 {
		return nil, fmt.Errorf("blocked community limit is zero for level %d", core.Level)
	}
	if err := am.k.AddBlockedCommunity(sdkCtx, owner, pat, uint32(tier.MaxBlockedCommunities)); err != nil {
		return nil, err
	}
	return &types.MsgBlockCommunityResponse{}, nil
}

func (am AppModule) UnblockCommunity(ctx context.Context, req *types.MsgUnblockCommunity) (*types.MsgUnblockCommunityResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	owner, err := am.envelopeOwner(req)
	if err != nil {
		return nil, err
	}
	if _, err := am.requireUsername(sdkCtx, owner, "UnblockCommunity"); err != nil {
		return nil, err
	}
	if err := am.consumeQuota(sdkCtx, owner); err != nil {
		return nil, err
	}
	if err := am.k.RemoveBlockedCommunity(sdkCtx, owner, strings.TrimSpace(req.GetCommunity())); err != nil {
		return nil, err
	}
	return &types.MsgUnblockCommunityResponse{}, nil
}

func (am AppModule) CreateCurationTeam(ctx context.Context, req *types.MsgCreateCurationTeam) (*types.MsgCreateCurationTeamResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	owner, err := am.envelopeOwner(req)
	if err != nil {
		return nil, err
	}
	core, err := am.requireCuratorEligible(sdkCtx, owner, "CreateCurationTeam")
	if err != nil {
		return nil, err
	}
	if err := am.consumeQuota(sdkCtx, owner); err != nil {
		return nil, err
	}
	teamID, err := am.k.CreateCurationTeam(sdkCtx, owner, strings.TrimSpace(req.GetCommunity()), req.GetName(), req.GetDescription())
	if err != nil {
		return nil, err
	}
	sdkCtx.Logger().Info("CreateCurationTeam",
		"owner", owner,
		"community", strings.TrimSpace(req.GetCommunity()),
		"team_id", teamID,
		"level", core.Level,
		"effective_paid", core.EffectivePaid,
	)
	return &types.MsgCreateCurationTeamResponse{}, nil
}

func (am AppModule) SetCurationTeamProfile(ctx context.Context, req *types.MsgSetCurationTeamProfile) (*types.MsgSetCurationTeamProfileResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	isGov := req.GetAuthority() == govAuthority()
	var owner string
	var err error
	if !isGov {
		owner, err = am.envelopeOwner(req)
		if err != nil {
			return nil, err
		}
		if err := am.consumeQuota(sdkCtx, owner); err != nil {
			return nil, err
		}
	}
	if isGov {
		return nil, fmt.Errorf("governance team profile changes must use a team recovery message")
	}
	if err := am.k.UpdateCurationTeamProfile(sdkCtx, owner, strings.TrimSpace(req.GetCommunity()), req.GetTeamId(), req.GetName(), req.GetDescription()); err != nil {
		return nil, err
	}
	return &types.MsgSetCurationTeamProfileResponse{}, nil
}

func (am AppModule) requireOwnerTeam(ctx sdk.Context, owner, slug string, teamID uint64) (*types.CurationTeam, error) {
	return am.k.RequireTeamOwner(ctx, owner, slug, teamID)
}

func (am AppModule) InviteCurator(ctx context.Context, req *types.MsgInviteCurator) (*types.MsgInviteCuratorResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	owner, err := am.envelopeOwner(req)
	if err != nil {
		return nil, err
	}
	if err := am.consumeQuota(sdkCtx, owner); err != nil {
		return nil, err
	}
	if err := am.k.InviteCurator(sdkCtx, owner, strings.TrimSpace(req.GetCommunity()), req.GetTeamId(), strings.TrimSpace(req.GetTarget())); err != nil {
		return nil, err
	}
	return &types.MsgInviteCuratorResponse{}, nil
}

func (am AppModule) RevokeCuratorInvite(ctx context.Context, req *types.MsgRevokeCuratorInvite) (*types.MsgRevokeCuratorInviteResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	owner, err := am.envelopeOwner(req)
	if err != nil {
		return nil, err
	}
	if err := am.consumeQuota(sdkCtx, owner); err != nil {
		return nil, err
	}
	team, err := am.k.RequireTeamOwner(sdkCtx, owner, strings.TrimSpace(req.GetCommunity()), req.GetTeamId())
	if err != nil {
		return nil, err
	}
	_ = team
	if err := am.k.ClearInvite(sdkCtx, strings.TrimSpace(req.GetCommunity()), req.GetTeamId(), strings.TrimSpace(req.GetTarget())); err != nil {
		return nil, err
	}
	sdkCtx.EventManager().EmitEvent(sdk.NewEvent("curator_invitation_revoked",
		sdk.NewAttribute("community", strings.TrimSpace(req.GetCommunity())),
		sdk.NewAttribute("team_id", fmt.Sprintf("%d", req.GetTeamId())),
		sdk.NewAttribute("target", strings.TrimSpace(req.GetTarget())),
		sdk.NewAttribute("inviter", owner),
		sdk.NewAttribute("status", "revoked"),
	))
	return &types.MsgRevokeCuratorInviteResponse{}, nil
}

func (am AppModule) AcceptCuratorInvite(ctx context.Context, req *types.MsgAcceptCuratorInvite) (*types.MsgAcceptCuratorInviteResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	owner, err := am.envelopeOwner(req)
	if err != nil {
		return nil, err
	}
	if err := am.consumeQuota(sdkCtx, owner); err != nil {
		return nil, err
	}
	if err := am.k.AcceptCuratorInvite(sdkCtx, owner, strings.TrimSpace(req.GetCommunity()), req.GetTeamId()); err != nil {
		return nil, err
	}
	return &types.MsgAcceptCuratorInviteResponse{}, nil
}

func (am AppModule) DeclineCuratorInvite(ctx context.Context, req *types.MsgDeclineCuratorInvite) (*types.MsgDeclineCuratorInviteResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	owner, err := am.envelopeOwner(req)
	if err != nil {
		return nil, err
	}
	if err := am.consumeQuota(sdkCtx, owner); err != nil {
		return nil, err
	}
	slug := strings.TrimSpace(req.GetCommunity())
	inviter, err := am.k.GetRaw(sdkCtx, types.KeyCurationInvite(slug, req.GetTeamId(), owner))
	if err != nil {
		return nil, err
	}
	if err := am.k.ClearInvite(sdkCtx, slug, req.GetTeamId(), owner); err != nil {
		return nil, err
	}
	sdkCtx.EventManager().EmitEvent(sdk.NewEvent("curator_invitation_declined",
		sdk.NewAttribute("community", slug),
		sdk.NewAttribute("team_id", fmt.Sprintf("%d", req.GetTeamId())),
		sdk.NewAttribute("target", owner),
		sdk.NewAttribute("inviter", string(inviter)),
		sdk.NewAttribute("status", "declined"),
	))
	return &types.MsgDeclineCuratorInviteResponse{}, nil
}

func (am AppModule) LeaveCurationTeam(ctx context.Context, req *types.MsgLeaveCurationTeam) (*types.MsgLeaveCurationTeamResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	owner, err := am.envelopeOwner(req)
	if err != nil {
		return nil, err
	}
	if err := am.consumeQuota(sdkCtx, owner); err != nil {
		return nil, err
	}
	team, ok, err := am.k.GetCurationTeam(sdkCtx, strings.TrimSpace(req.GetCommunity()), req.GetTeamId())
	if err != nil || !ok {
		return nil, fmt.Errorf("team not found")
	}
	if team.Owner == owner {
		return nil, fmt.Errorf("owner cannot leave; transfer or delete first")
	}
	if err := am.k.RemoveCuratorFromTeam(sdkCtx, team.Community, team.TeamId, owner, "curator_left"); err != nil {
		return nil, err
	}
	return &types.MsgLeaveCurationTeamResponse{}, nil
}

func (am AppModule) RemoveCurator(ctx context.Context, req *types.MsgRemoveCurator) (*types.MsgRemoveCuratorResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	owner, err := am.envelopeOwner(req)
	if err != nil {
		return nil, err
	}
	if err := am.consumeQuota(sdkCtx, owner); err != nil {
		return nil, err
	}
	target := strings.TrimSpace(req.GetTarget())
	if target == owner {
		return nil, fmt.Errorf("owner cannot remove self")
	}
	if _, err := am.k.RequireTeamOwner(sdkCtx, owner, strings.TrimSpace(req.GetCommunity()), req.GetTeamId()); err != nil {
		return nil, err
	}
	if err := am.k.RemoveCuratorFromTeam(sdkCtx, strings.TrimSpace(req.GetCommunity()), req.GetTeamId(), target, "curator_removed"); err != nil {
		return nil, err
	}
	return &types.MsgRemoveCuratorResponse{}, nil
}

func (am AppModule) TransferCurationTeam(ctx context.Context, req *types.MsgTransferCurationTeam) (*types.MsgTransferCurationTeamResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	owner, err := am.envelopeOwner(req)
	if err != nil {
		return nil, err
	}
	if err := am.consumeQuota(sdkCtx, owner); err != nil {
		return nil, err
	}
	if err := am.k.TransferCurationTeamOwner(sdkCtx, owner, strings.TrimSpace(req.GetCommunity()), req.GetTeamId(), strings.TrimSpace(req.GetNewOwner())); err != nil {
		return nil, err
	}
	return &types.MsgTransferCurationTeamResponse{}, nil
}

func (am AppModule) DeleteCurationTeam(ctx context.Context, req *types.MsgDeleteCurationTeam) (*types.MsgDeleteCurationTeamResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	slug := strings.TrimSpace(req.GetCommunity())
	owner, err := am.envelopeOwner(req)
	if err != nil {
		return nil, err
	}
	if err := am.consumeQuota(sdkCtx, owner); err != nil {
		return nil, err
	}
	if _, err := am.k.RequireTeamOwner(sdkCtx, owner, slug, req.GetTeamId()); err != nil {
		return nil, err
	}
	if err := am.k.DeleteCurationTeam(sdkCtx, slug, req.GetTeamId()); err != nil {
		return nil, err
	}
	return &types.MsgDeleteCurationTeamResponse{}, nil
}

func (am AppModule) SetCurationPreference(ctx context.Context, req *types.MsgSetCurationPreference) (*types.MsgSetCurationPreferenceResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	owner, err := am.envelopeOwner(req)
	if err != nil {
		return nil, err
	}
	core, err := am.requireUsername(sdkCtx, owner, "SetCurationPreference")
	if err != nil {
		return nil, err
	}
	if err := am.consumeQuota(sdkCtx, owner); err != nil {
		return nil, err
	}
	// Admins and paid subscribers both count toward team subscriber_count.
	if err := am.k.SetCurationPreference(sdkCtx, owner, strings.TrimSpace(req.GetCommunity()), req.GetMode(), req.GetPinnedTeamId(), types.CanCurate(core)); err != nil {
		return nil, err
	}
	return &types.MsgSetCurationPreferenceResponse{}, nil
}

func (am AppModule) SetCurationPostHidden(ctx context.Context, req *types.MsgSetCurationPostHidden) (*types.MsgSetCurationPostHiddenResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	slug := strings.TrimSpace(req.GetCommunity())
	target := strings.ToLower(req.GetTarget())
	actor, err := am.curationActor(sdkCtx, req, slug, req.GetTeamId())
	if err != nil {
		return nil, err
	}
	if req.GetHidden() {
		meta, found, err := am.k.GetPostMetadata(sdkCtx, target)
		if err != nil {
			return nil, err
		}
		if !found {
			return nil, fmt.Errorf("post metadata not found")
		}
		if meta.GetCommunity() != slug {
			return nil, fmt.Errorf("post does not belong to community")
		}
		protected, err := am.k.IsCommunityCurator(sdkCtx, meta.GetAuthor(), slug)
		if err != nil {
			return nil, err
		}
		if protected {
			return nil, fmt.Errorf("cannot ban a curator's post in this community")
		}
	}
	if err := am.k.SetCurationActionHiddenPost(sdkCtx, slug, req.GetTeamId(), target, actor, req.GetHidden()); err != nil {
		return nil, err
	}
	return &types.MsgSetCurationPostHiddenResponse{}, nil
}

func (am AppModule) SetCurationPostTag(ctx context.Context, req *types.MsgSetCurationPostTag) (*types.MsgSetCurationPostTagResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	actor, err := am.curationActor(sdkCtx, req, strings.TrimSpace(req.GetCommunity()), req.GetTeamId())
	if err != nil {
		return nil, err
	}
	tag := normalizeTag(req.GetTag())
	if req.GetClear() && tag != "" {
		return nil, fmt.Errorf("clear cannot be combined with a tag")
	}
	if err := validateTag(tag); err != nil {
		return nil, err
	}
	if err := am.k.SetCurationPostTag(sdkCtx, strings.TrimSpace(req.GetCommunity()), req.GetTeamId(), strings.ToLower(req.GetTarget()), tag, actor, req.GetClear()); err != nil {
		return nil, err
	}
	return &types.MsgSetCurationPostTagResponse{}, nil
}

func (am AppModule) SetCurationUserHidden(ctx context.Context, req *types.MsgSetCurationUserHidden) (*types.MsgSetCurationUserHiddenResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	slug := strings.TrimSpace(req.GetCommunity())
	target := strings.TrimSpace(req.GetTarget())
	actor, err := am.curationActor(sdkCtx, req, slug, req.GetTeamId())
	if err != nil {
		return nil, err
	}
	if req.GetHidden() {
		protected, err := am.k.IsCommunityCurator(sdkCtx, target, slug)
		if err != nil {
			return nil, err
		}
		if protected {
			return nil, fmt.Errorf("cannot ban a curator in this community")
		}
	}
	if err := am.k.SetCurationActionHiddenUser(sdkCtx, slug, req.GetTeamId(), target, actor, req.GetHidden()); err != nil {
		return nil, err
	}
	return &types.MsgSetCurationUserHiddenResponse{}, nil
}

func (am AppModule) SetCurationThreadLocked(ctx context.Context, req *types.MsgSetCurationThreadLocked) (*types.MsgSetCurationThreadLockedResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	actor, err := am.curationActor(sdkCtx, req, strings.TrimSpace(req.GetCommunity()), req.GetTeamId())
	if err != nil {
		return nil, err
	}
	if err := am.k.SetCurationThreadLocked(sdkCtx, strings.TrimSpace(req.GetCommunity()), req.GetTeamId(), strings.ToLower(req.GetRootHash()), actor, req.GetLocked()); err != nil {
		return nil, err
	}
	return &types.MsgSetCurationThreadLockedResponse{}, nil
}

func (am AppModule) SetCurationSubscriberOnly(ctx context.Context, req *types.MsgSetCurationSubscriberOnly) (*types.MsgSetCurationSubscriberOnlyResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	slug := strings.TrimSpace(req.GetCommunity())
	actor, err := am.envelopeOwner(req)
	if err != nil {
		return nil, err
	}
	if err := am.consumeQuota(sdkCtx, actor); err != nil {
		return nil, err
	}
	if _, err := am.k.RequireTeamOwner(sdkCtx, actor, slug, req.GetTeamId()); err != nil {
		return nil, err
	}
	team, ok, err := am.k.GetCurationTeam(sdkCtx, slug, req.GetTeamId())
	if err != nil || !ok {
		return nil, fmt.Errorf("team not found")
	}
	team.SubscriberOnly = req.GetEnabled()
	if err := am.k.SetCurationTeam(sdkCtx, team); err != nil {
		return nil, err
	}
	sdkCtx.EventManager().EmitEvent(sdk.NewEvent("curation_subscriber_only_changed",
		sdk.NewAttribute("community", slug),
		sdk.NewAttribute("team_id", fmt.Sprintf("%d", req.GetTeamId())),
		sdk.NewAttribute("enabled", fmt.Sprintf("%t", req.GetEnabled())),
		sdk.NewAttribute("actor", actor),
	))
	return &types.MsgSetCurationSubscriberOnlyResponse{}, nil
}

func (am AppModule) SetCurationTag(ctx context.Context, req *types.MsgSetCurationTag) (*types.MsgSetCurationTagResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	slug := strings.TrimSpace(req.GetCommunity())
	actor, err := am.envelopeOwner(req)
	if err != nil {
		return nil, err
	}
	if err := am.consumeQuota(sdkCtx, actor); err != nil {
		return nil, err
	}
	if _, err := am.k.RequireTeamOwner(sdkCtx, actor, slug, req.GetTeamId()); err != nil {
		return nil, err
	}
	tag := normalizeTag(req.GetTag())
	if err := validateTag(tag); err != nil {
		return nil, err
	}
	if err := am.k.SetCurationTeamTag(sdkCtx, slug, req.GetTeamId(), tag); err != nil {
		return nil, err
	}
	return &types.MsgSetCurationTagResponse{}, nil
}

type envelopeMsg interface {
	GetEnvelopePubkey() []byte
}

func (am AppModule) curationActor(ctx sdk.Context, req envelopeMsg, slug string, teamID uint64) (string, error) {
	owner, err := am.envelopeOwner(req)
	if err != nil {
		return "", err
	}
	if err := am.consumeQuota(ctx, owner); err != nil {
		return "", err
	}
	if _, err := am.k.RequireTeamCurator(ctx, owner, slug, teamID); err != nil {
		return "", err
	}
	return owner, nil
}

func (am AppModule) ClaimCreatorRewards(ctx context.Context, req *types.MsgClaimCreatorRewards) (*types.MsgClaimCreatorRewardsResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	owner, err := am.envelopeOwner(req)
	if err != nil {
		return nil, err
	}
	if err := am.consumeQuota(sdkCtx, owner); err != nil {
		return nil, err
	}
	if err := am.k.ClaimCreatorRewards(sdkCtx, owner, req.GetEpochIds()); err != nil {
		return nil, err
	}
	return &types.MsgClaimCreatorRewardsResponse{}, nil
}

func postTxHash(ctx sdk.Context) (string, error) {
	bz := ctx.TxBytes()
	if len(bz) == 0 {
		return "", fmt.Errorf("empty tx bytes")
	}
	sum := sha256.Sum256(bz)
	return hex.EncodeToString(sum[:]), nil
}
