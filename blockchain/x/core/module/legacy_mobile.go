package core

import (
	"context"
	"fmt"
	"strings"

	sdk "github.com/cosmos/cosmos-sdk/types"

	"mirage/x/core/types"
)

func legacyCommunityMatchesPattern(community, pattern string) bool {
	if !strings.Contains(pattern, "*") {
		return community == pattern
	}

	parts := strings.Split(pattern, "*")
	pos := 0
	for i, part := range parts {
		if part == "" {
			continue
		}
		offset := strings.Index(community[pos:], part)
		if offset < 0 {
			return false
		}
		idx := pos + offset
		if i == 0 && idx != 0 {
			return false
		}
		pos = idx + len(part)
	}

	if len(parts) > 0 && parts[len(parts)-1] != "" {
		return strings.HasSuffix(community, parts[len(parts)-1])
	}
	return true
}

func (am AppModule) requireLegacyOwnerTarget(req interface {
	GetEnvelopePubkey() []byte
	GetTarget() string
}) (string, error) {
	owner, err := am.envelopeOwner(req)
	if err != nil {
		return "", err
	}
	target := strings.ToLower(strings.TrimSpace(req.GetTarget()))
	if target == "" {
		return "", fmt.Errorf("target cannot be empty")
	}
	if target != owner {
		return "", fmt.Errorf("envelope_pubkey must derive to target")
	}
	return owner, nil
}

func (am AppModule) requireLegacyEmptyTarget(req interface {
	GetEnvelopePubkey() []byte
	GetTarget() string
}) (string, error) {
	owner, err := am.envelopeOwner(req)
	if err != nil {
		return "", err
	}
	if strings.TrimSpace(req.GetTarget()) != "" {
		return "", fmt.Errorf("legacy topic block target must be empty")
	}
	return owner, nil
}

func (am AppModule) removeLegacyBlocksMatchingCommunity(ctx sdk.Context, owner, community string) error {
	patterns, err := am.k.ListBlockedCommunities(ctx, owner)
	if err != nil {
		return err
	}
	for _, pattern := range patterns {
		if legacyCommunityMatchesPattern(community, pattern) {
			if err := am.k.RemoveBlockedCommunity(ctx, owner, pattern); err != nil {
				return err
			}
		}
	}
	return nil
}

func (am AppModule) leaveLegacyCommunitiesMatchingPattern(ctx sdk.Context, owner, pattern string, paid bool) error {
	communities, err := am.k.ListJoinedCommunities(ctx, owner)
	if err != nil {
		return err
	}
	for _, community := range communities {
		if legacyCommunityMatchesPattern(community, pattern) {
			if err := am.k.LeaveCommunity(ctx, owner, community, paid); err != nil {
				return err
			}
		}
	}
	return nil
}

func (am AppModule) FollowTopic(ctx context.Context, req *types.MsgFollowTopic) (*types.MsgFollowTopicResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	owner, err := am.requireLegacyOwnerTarget(req)
	if err != nil {
		return nil, err
	}
	core, err := am.requireUsername(sdkCtx, owner, "FollowTopic")
	if err != nil {
		return nil, err
	}
	if err := am.consumeQuota(sdkCtx, owner); err != nil {
		return nil, err
	}

	params := am.k.GetParams(sdkCtx)
	topic := strings.TrimSpace(req.GetTopic())
	if err := types.ValidateCommunitySlug(topic, uint64(params.MinCommunitySize), uint64(params.MaxCommunitySize)); err != nil {
		return nil, err
	}
	tier := params.GetTierConfig(int(core.Level))
	if tier == nil {
		return nil, fmt.Errorf("tier config not found")
	}
	if err := am.removeLegacyBlocksMatchingCommunity(sdkCtx, owner, topic); err != nil {
		return nil, err
	}
	if err := am.k.JoinCommunityWithLens(
		sdkCtx,
		owner,
		topic,
		uint32(tier.MaxJoinedCommunities),
		types.CurationPreferenceMode_CURATION_PREFERENCE_MODE_LIVE_DEFAULT,
		0,
		types.CanCurate(core),
	); err != nil {
		return nil, err
	}
	sdkCtx.Logger().Info("legacy_mobile", "message", "MsgFollowTopic", "topic", topic)
	return &types.MsgFollowTopicResponse{}, nil
}

func (am AppModule) UnfollowTopic(ctx context.Context, req *types.MsgUnfollowTopic) (*types.MsgUnfollowTopicResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	owner, err := am.requireLegacyOwnerTarget(req)
	if err != nil {
		return nil, err
	}
	core, err := am.requireUsername(sdkCtx, owner, "UnfollowTopic")
	if err != nil {
		return nil, err
	}
	if err := am.consumeQuota(sdkCtx, owner); err != nil {
		return nil, err
	}

	params := am.k.GetParams(sdkCtx)
	topic := strings.TrimSpace(req.GetTopic())
	if err := types.ValidateCommunitySlug(topic, uint64(params.MinCommunitySize), uint64(params.MaxCommunitySize)); err != nil {
		return nil, err
	}
	if err := am.k.LeaveCommunity(sdkCtx, owner, topic, core.EffectivePaid); err != nil {
		return nil, err
	}
	sdkCtx.Logger().Info("legacy_mobile", "message", "MsgUnfollowTopic", "topic", topic)
	return &types.MsgUnfollowTopicResponse{}, nil
}

func (am AppModule) BlockTopic(ctx context.Context, req *types.MsgBlockTopic) (*types.MsgBlockTopicResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	owner, err := am.requireLegacyEmptyTarget(req)
	if err != nil {
		return nil, err
	}
	core, err := am.requireUsername(sdkCtx, owner, "BlockTopic")
	if err != nil {
		return nil, err
	}
	if err := am.consumeQuota(sdkCtx, owner); err != nil {
		return nil, err
	}

	params := am.k.GetParams(sdkCtx)
	pattern := strings.TrimSpace(req.GetTopic())
	if err := validateBlockedCommunityPattern(pattern, uint64(params.MaxCommunitySize), uint64(params.MinCommunitySize)); err != nil {
		return nil, err
	}
	tier := params.GetTierConfig(int(core.Level))
	if tier == nil {
		return nil, fmt.Errorf("tier config not found")
	}
	if tier.MaxBlockedCommunities == 0 {
		return nil, fmt.Errorf("blocked community limit is zero for level %d", core.Level)
	}
	if err := am.k.AddBlockedCommunity(sdkCtx, owner, pattern, uint32(tier.MaxBlockedCommunities)); err != nil {
		return nil, err
	}
	if err := am.leaveLegacyCommunitiesMatchingPattern(sdkCtx, owner, pattern, core.EffectivePaid); err != nil {
		return nil, err
	}
	sdkCtx.Logger().Info("legacy_mobile", "message", "MsgBlockTopic", "topic", pattern)
	return &types.MsgBlockTopicResponse{}, nil
}

func (am AppModule) UnblockTopic(ctx context.Context, req *types.MsgUnblockTopic) (*types.MsgUnblockTopicResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	owner, err := am.requireLegacyEmptyTarget(req)
	if err != nil {
		return nil, err
	}
	if _, err := am.requireUsername(sdkCtx, owner, "UnblockTopic"); err != nil {
		return nil, err
	}
	if err := am.consumeQuota(sdkCtx, owner); err != nil {
		return nil, err
	}

	params := am.k.GetParams(sdkCtx)
	pattern := strings.TrimSpace(req.GetTopic())
	if err := validateBlockedCommunityPattern(pattern, uint64(params.MaxCommunitySize), uint64(params.MinCommunitySize)); err != nil {
		return nil, err
	}
	if err := am.k.RemoveBlockedCommunity(sdkCtx, owner, pattern); err != nil {
		return nil, err
	}
	sdkCtx.Logger().Info("legacy_mobile", "message", "MsgUnblockTopic", "topic", pattern)
	return &types.MsgUnblockTopicResponse{}, nil
}
