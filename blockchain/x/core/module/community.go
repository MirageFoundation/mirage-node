package core

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"strings"
	"unicode/utf8"

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
	if err := am.k.JoinCommunity(sdkCtx, owner, slug, core.EffectivePaid, uint32(tier.MaxJoinedCommunities), true); err != nil {
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
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	owner, err := am.envelopeOwner(req)
	if err != nil {
		return nil, err
	}
	if _, err := am.requirePaid(sdkCtx, owner, "CreateCommunity"); err != nil {
		return nil, err
	}
	if err := am.consumeQuota(sdkCtx, owner); err != nil {
		return nil, err
	}
	if err := am.k.CreateCommunity(sdkCtx, owner, strings.TrimSpace(req.GetCommunity()), req.GetTitle(), req.GetDescription(), req.GetOriginalTeamName(), req.GetBio(), req.GetPolicy()); err != nil {
		return nil, err
	}
	return &types.MsgCreateCommunityResponse{}, nil
}

func (am AppModule) SetCommunityMetadata(ctx context.Context, req *types.MsgSetCommunityMetadata) (*types.MsgSetCommunityMetadataResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	isGov := req.GetAuthority() == govAuthority()
	var owner string
	var err error
	if isGov {
		owner = req.GetAuthority()
	} else {
		owner, err = am.envelopeOwner(req)
		if err != nil {
			return nil, err
		}
		if err := am.consumeQuota(sdkCtx, owner); err != nil {
			return nil, err
		}
	}
	slug := strings.TrimSpace(req.GetCommunity())
	comm, found, err := am.k.GetCommunity(sdkCtx, slug)
	if err != nil {
		return nil, err
	}
	if !found {
		return nil, fmt.Errorf("community not found")
	}
	if !isGov && comm.CurrentFounder != owner {
		return nil, fmt.Errorf("only the current founder may set metadata")
	}
	params := am.k.GetParams(sdkCtx)
	if uint64(utf8.RuneCountInString(req.GetTitle())) > params.MaxCommunityTitleLength {
		return nil, fmt.Errorf("title too long")
	}
	if uint64(utf8.RuneCountInString(req.GetDescription())) > params.MaxCommunityDescriptionLength {
		return nil, fmt.Errorf("description too long")
	}
	comm.Title = req.GetTitle()
	comm.Description = req.GetDescription()
	if err := am.k.SetCommunity(sdkCtx, comm); err != nil {
		return nil, err
	}
	sdkCtx.EventManager().EmitEvent(sdk.NewEvent("community_metadata_updated",
		sdk.NewAttribute("community", slug),
	))
	return &types.MsgSetCommunityMetadataResponse{}, nil
}

func (am AppModule) TransferCommunity(ctx context.Context, req *types.MsgTransferCommunity) (*types.MsgTransferCommunityResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	isGov := req.GetAuthority() == govAuthority()
	var owner string
	var err error
	if isGov {
		owner = req.GetAuthority()
	} else {
		owner, err = am.envelopeOwner(req)
		if err != nil {
			return nil, err
		}
		if err := am.consumeQuota(sdkCtx, owner); err != nil {
			return nil, err
		}
	}
	slug := strings.TrimSpace(req.GetCommunity())
	comm, found, err := am.k.GetCommunity(sdkCtx, slug)
	if err != nil {
		return nil, err
	}
	if !found {
		return nil, fmt.Errorf("community not found")
	}
	if !isGov && comm.CurrentFounder != owner {
		return nil, fmt.Errorf("only the current founder may transfer")
	}
	newFounder := strings.TrimSpace(req.GetNewFounder())
	if _, err := types.CanonicalAccBytes(newFounder); err != nil {
		return nil, err
	}
	paid, err := am.k.IsEffectivePaid(sdkCtx, newFounder)
	if err != nil {
		return nil, err
	}
	if !paid {
		return nil, fmt.Errorf("new founder must be an active subscriber")
	}
	old := comm.CurrentFounder
	if err := am.k.StoreService().OpenKVStore(sdkCtx).Delete(types.KeyCommunityFounder(old, slug)); err != nil {
		return nil, err
	}
	comm.CurrentFounder = newFounder
	if err := am.k.SetCommunity(sdkCtx, comm); err != nil {
		return nil, err
	}
	if err := am.k.StoreService().OpenKVStore(sdkCtx).Set(types.KeyCommunityFounder(newFounder, slug), []byte{1}); err != nil {
		return nil, err
	}
	if orig, ok, err := am.k.GetCurationTeam(sdkCtx, slug, comm.OriginalTeamId); err != nil {
		return nil, err
	} else if ok && orig.Owner == old && orig.DeletedHeight == 0 {
		orig.Owner = newFounder
		if err := am.k.SetCurationTeam(sdkCtx, orig); err != nil {
			return nil, err
		}
	}
	sdkCtx.EventManager().EmitEvent(sdk.NewEvent("community_founder_transferred",
		sdk.NewAttribute("community", slug),
		sdk.NewAttribute("old_founder", old),
		sdk.NewAttribute("new_founder", newFounder),
	))
	return &types.MsgTransferCommunityResponse{}, nil
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
	if _, err := am.requirePaid(sdkCtx, owner, "CreateCurationTeam"); err != nil {
		return nil, err
	}
	if err := am.consumeQuota(sdkCtx, owner); err != nil {
		return nil, err
	}
	if _, err := am.k.CreateAlternativeTeam(sdkCtx, owner, strings.TrimSpace(req.GetCommunity()), req.GetName(), req.GetBio(), req.GetPolicy()); err != nil {
		return nil, err
	}
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
	slug := strings.TrimSpace(req.GetCommunity())
	var team *types.CurationTeam
	if !isGov {
		var err2 error
		team, err2 = am.k.RequireTeamOwner(sdkCtx, owner, slug, req.GetTeamId())
		if err2 != nil {
			return nil, err2
		}
	} else {
		var ok bool
		var err2 error
		team, ok, err2 = am.k.GetCurationTeam(sdkCtx, slug, req.GetTeamId())
		if err2 != nil || !ok {
			return nil, fmt.Errorf("team not found")
		}
	}
	params := am.k.GetParams(sdkCtx)
	if err := types.ValidateCurationTeamName(req.GetName(), params.MaxCurationTeamNameLength); err != nil {
		return nil, err
	}
	team.Name = req.GetName()
	team.Bio = req.GetBio()
	team.Policy = req.GetPolicy()
	if err := am.k.SetCurationTeam(sdkCtx, team); err != nil {
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
	if err := am.k.ClearInvite(sdkCtx, strings.TrimSpace(req.GetCommunity()), req.GetTeamId(), owner); err != nil {
		return nil, err
	}
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
	team, err := am.k.RequireTeamOwner(sdkCtx, owner, strings.TrimSpace(req.GetCommunity()), req.GetTeamId())
	if err != nil {
		return nil, err
	}
	paid, err := am.k.IsEffectivePaid(sdkCtx, strings.TrimSpace(req.GetNewOwner()))
	if err != nil || !paid {
		return nil, fmt.Errorf("new owner must be an active subscriber")
	}
	team.Owner = strings.TrimSpace(req.GetNewOwner())
	if err := am.k.SetCurationTeam(sdkCtx, team); err != nil {
		return nil, err
	}
	return &types.MsgTransferCurationTeamResponse{}, nil
}

func (am AppModule) DeleteCurationTeam(ctx context.Context, req *types.MsgDeleteCurationTeam) (*types.MsgDeleteCurationTeamResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	isGov := req.GetAuthority() == govAuthority()
	slug := strings.TrimSpace(req.GetCommunity())
	if !isGov {
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
	if err := am.k.SetCurationPreference(sdkCtx, owner, strings.TrimSpace(req.GetCommunity()), req.GetMode(), req.GetPinnedTeamId(), core.EffectivePaid); err != nil {
		return nil, err
	}
	return &types.MsgSetCurationPreferenceResponse{}, nil
}

func (am AppModule) SetCurationPostHidden(ctx context.Context, req *types.MsgSetCurationPostHidden) (*types.MsgSetCurationPostHiddenResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	actor, err := am.curationActor(sdkCtx, req.GetAuthority(), req)
	if err != nil {
		return nil, err
	}
	if err := am.k.SetCurationActionHiddenPost(sdkCtx, strings.TrimSpace(req.GetCommunity()), req.GetTeamId(), strings.ToLower(req.GetTarget()), actor, req.GetHidden()); err != nil {
		return nil, err
	}
	return &types.MsgSetCurationPostHiddenResponse{}, nil
}

func (am AppModule) SetCurationUserHidden(ctx context.Context, req *types.MsgSetCurationUserHidden) (*types.MsgSetCurationUserHiddenResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	actor, err := am.curationActor(sdkCtx, req.GetAuthority(), req)
	if err != nil {
		return nil, err
	}
	if err := am.k.SetCurationActionHiddenUser(sdkCtx, strings.TrimSpace(req.GetCommunity()), req.GetTeamId(), strings.TrimSpace(req.GetTarget()), actor, req.GetHidden()); err != nil {
		return nil, err
	}
	return &types.MsgSetCurationUserHiddenResponse{}, nil
}

func (am AppModule) SetCurationThreadLocked(ctx context.Context, req *types.MsgSetCurationThreadLocked) (*types.MsgSetCurationThreadLockedResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	actor, err := am.curationActor(sdkCtx, req.GetAuthority(), req)
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
	isGov := req.GetAuthority() == govAuthority()
	slug := strings.TrimSpace(req.GetCommunity())
	var actor string
	if isGov {
		actor = req.GetAuthority()
	} else {
		var err error
		actor, err = am.envelopeOwner(req)
		if err != nil {
			return nil, err
		}
		if err := am.consumeQuota(sdkCtx, actor); err != nil {
			return nil, err
		}
		if _, err := am.k.RequireTeamOwner(sdkCtx, actor, slug, req.GetTeamId()); err != nil {
			return nil, err
		}
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

type envelopeMsg interface {
	GetEnvelopePubkey() []byte
}

func (am AppModule) curationActor(ctx sdk.Context, authority string, req envelopeMsg) (string, error) {
	if authority == govAuthority() {
		return authority, nil
	}
	owner, err := am.envelopeOwner(req)
	if err != nil {
		return "", err
	}
	if err := am.consumeQuota(ctx, owner); err != nil {
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
