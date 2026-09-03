package core

import (
	"errors"
	"strings"
	"testing"

	sdk "github.com/cosmos/cosmos-sdk/types"
	"github.com/stretchr/testify/require"

	"mirage/x/core/types"
)

func TestLegacyCommunityMatchesPattern(t *testing.T) {
	tests := []struct {
		name      string
		community string
		pattern   string
		want      bool
	}{
		{"exact", "general", "general", true},
		{"exact mismatch", "general", "gen", false},
		{"prefix wildcard", "technology-news", "technology*", true},
		{"prefix wildcard mismatch", "new-technology", "technology*", false},
		{"suffix wildcard", "world-news", "*news", true},
		{"suffix wildcard mismatch", "news-world", "*news", false},
		{"middle wildcard", "tech-world-news", "tech*news", true},
		{"multiple wildcards", "a-long-middle-value-z", "a*middle*z", true},
		{"repeated wildcard segments", "alpha-beta", "alpha**beta", true},
		{"unanchored", "prefix-middle-suffix", "*middle*", true},
		{"anchored end mismatch", "tech-news-extra", "tech*news", false},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			require.Equal(t, tt.want, legacyCommunityMatchesPattern(tt.community, tt.pattern))
		})
	}
}

func TestLegacyCommunityMatchesPatternHandlesMaximumAndLongInputs(t *testing.T) {
	const wildcardCount = 34
	pattern := "a" + strings.Repeat("*a", wildcardCount)
	community := strings.Repeat("a", wildcardCount+1)
	require.True(t, legacyCommunityMatchesPattern(community, pattern))

	longCommunity := strings.Repeat("a", 1_000_000) + "z"
	require.False(t, legacyCommunityMatchesPattern(longCommunity, "a*a*a*a*y"))
}

func TestLegacyTopicHandlersProjectCommunityState(t *testing.T) {
	mk, ctx, am := setupModule(t)
	pub, owner := testPubkeyOwner()

	require.NoError(t, mk.AddBlockedCommunity(ctx, owner, "tech*", 10))
	require.NoError(t, mk.AddBlockedCommunity(ctx, owner, "other*", 10))
	_, err := am.FollowTopic(ctx, &types.MsgFollowTopic{
		EnvelopePubkey: pub,
		Target:         owner,
		Topic:          "technology",
	})
	require.NoError(t, err)

	joined, err := mk.ListJoinedCommunities(ctx, owner)
	require.NoError(t, err)
	require.Equal(t, []string{"technology"}, joined)
	blocked, err := mk.ListBlockedCommunities(ctx, owner)
	require.NoError(t, err)
	require.Equal(t, []string{"other*"}, blocked)

	for _, slug := range []string{"tech-news", "sports"} {
		require.NoError(t, mk.JoinCommunity(ctx, owner, slug, 10))
	}
	_, err = am.BlockTopic(ctx, &types.MsgBlockTopic{
		EnvelopePubkey: pub,
		Target:         "",
		Topic:          "tech*",
	})
	require.NoError(t, err)

	joined, err = mk.ListJoinedCommunities(ctx, owner)
	require.NoError(t, err)
	require.Equal(t, []string{"sports"}, joined)
	blocked, err = mk.ListBlockedCommunities(ctx, owner)
	require.NoError(t, err)
	require.ElementsMatch(t, []string{"other*", "tech*"}, blocked)

	_, err = am.UnblockTopic(ctx, &types.MsgUnblockTopic{
		EnvelopePubkey: pub,
		Topic:          "tech*",
	})
	require.NoError(t, err)
	blocked, err = mk.ListBlockedCommunities(ctx, owner)
	require.NoError(t, err)
	require.Equal(t, []string{"other*"}, blocked)

	_, err = am.UnfollowTopic(ctx, &types.MsgUnfollowTopic{
		EnvelopePubkey: pub,
		Target:         owner,
		Topic:          "sports",
	})
	require.NoError(t, err)
	joined, err = mk.ListJoinedCommunities(ctx, owner)
	require.NoError(t, err)
	require.Empty(t, joined)
}

func TestLegacyTopicHandlerValidation(t *testing.T) {
	mk, ctx, am := setupModule(t)
	pub, owner := testPubkeyOwner()

	_, err := am.FollowTopic(ctx, &types.MsgFollowTopic{EnvelopePubkey: pub, Target: genAddr(44), Topic: "general"})
	require.ErrorContains(t, err, "derive to target")

	_, err = am.FollowTopic(ctx, &types.MsgFollowTopic{EnvelopePubkey: pub, Target: owner, Topic: "General"})
	require.ErrorContains(t, err, "lowercase alphanumeric")

	_, err = am.BlockTopic(ctx, &types.MsgBlockTopic{EnvelopePubkey: pub, Target: owner, Topic: "general"})
	require.ErrorContains(t, err, "target must be empty")

	_, err = am.UnblockTopic(ctx, &types.MsgUnblockTopic{EnvelopePubkey: pub, Topic: "**"})
	require.Error(t, err)

	params := mk.GetParams(ctx)
	params.Tiers[0].MaxJoinedCommunities = 0
	require.NoError(t, mk.SetParams(ctx, params))
	_, err = am.FollowTopic(ctx, &types.MsgFollowTopic{EnvelopePubkey: pub, Target: owner, Topic: "general"})
	require.ErrorContains(t, err, "cap is zero")

	params.Tiers[0].MaxJoinedCommunities = 10
	params.Tiers[0].MaxBlockedCommunities = 0
	require.NoError(t, mk.SetParams(ctx, params))
	_, err = am.BlockTopic(ctx, &types.MsgBlockTopic{EnvelopePubkey: pub, Topic: "general"})
	require.ErrorContains(t, err, "limit is zero")
}

func TestLegacyTopicHandlersConsumeQuotaOnce(t *testing.T) {
	for _, action := range []string{"follow", "unfollow", "block", "unblock"} {
		t.Run(action, func(t *testing.T) {
			mk, ctx, am := setupModule(t)
			ctx = ctx.WithExecMode(sdk.ExecModeFinalize)
			pub, owner := testPubkeyOwner()
			setProfileLevel(t, mk, ctx, owner, types.LevelSubscriber)

			var err error
			switch action {
			case "follow":
				_, err = am.FollowTopic(ctx, &types.MsgFollowTopic{
					EnvelopePubkey: pub, Target: owner, Topic: "general",
				})
			case "unfollow":
				require.NoError(t, mk.JoinCommunity(ctx, owner, "general", 10))
				_, err = am.UnfollowTopic(ctx, &types.MsgUnfollowTopic{
					EnvelopePubkey: pub, Target: owner, Topic: "general",
				})
			case "block":
				_, err = am.BlockTopic(ctx, &types.MsgBlockTopic{
					EnvelopePubkey: pub, Topic: "general",
				})
			case "unblock":
				require.NoError(t, mk.AddBlockedCommunity(ctx, owner, "general", 10))
				_, err = am.UnblockTopic(ctx, &types.MsgUnblockTopic{
					EnvelopePubkey: pub, Topic: "general",
				})
			}
			require.NoError(t, err)
			quota, err := mk.GetSubscriberQuota(ctx, owner)
			require.NoError(t, err)
			require.Equal(t, uint64(1), quota.Count)
		})
	}
}

func TestLegacyTopicHandlersReturnStoreErrors(t *testing.T) {
	t.Run("follow blocked list", func(t *testing.T) {
		mk, ctx, am := setupModule(t)
		pub, owner := testPubkeyOwner()
		mk.storeService.iterError = errors.New("blocked iterator failed")

		_, err := am.FollowTopic(ctx, &types.MsgFollowTopic{
			EnvelopePubkey: pub,
			Target:         owner,
			Topic:          "general",
		})
		require.ErrorContains(t, err, "blocked iterator failed")
	})

	t.Run("block joined list", func(t *testing.T) {
		mk, ctx, am := setupModule(t)
		pub, _ := testPubkeyOwner()
		mk.storeService.iterError = errors.New("joined iterator failed")

		_, err := am.BlockTopic(ctx, &types.MsgBlockTopic{
			EnvelopePubkey: pub,
			Topic:          "general",
		})
		require.ErrorContains(t, err, "joined iterator failed")
	})

	t.Run("follow removes matching block", func(t *testing.T) {
		mk, ctx, am := setupModule(t)
		pub, owner := testPubkeyOwner()
		require.NoError(t, mk.AddBlockedCommunity(ctx, owner, "gen*", 10))
		mk.storeService.deleteErrors = map[string]error{
			string(types.KeyBlockCommunity(owner, 0, "gen*")): errors.New("block delete failed"),
		}

		_, err := am.FollowTopic(ctx, &types.MsgFollowTopic{
			EnvelopePubkey: pub,
			Target:         owner,
			Topic:          "general",
		})
		require.ErrorContains(t, err, "block delete failed")
	})

	t.Run("follow joins community", func(t *testing.T) {
		mk, ctx, am := setupModule(t)
		pub, owner := testPubkeyOwner()
		mk.storeService.setErrors = map[string]error{
			string(types.KeyJoin(owner, "general")): errors.New("join write failed"),
		}

		_, err := am.FollowTopic(ctx, &types.MsgFollowTopic{
			EnvelopePubkey: pub,
			Target:         owner,
			Topic:          "general",
		})
		require.ErrorContains(t, err, "join write failed")
	})

	t.Run("unfollow leaves community", func(t *testing.T) {
		mk, ctx, am := setupModule(t)
		pub, owner := testPubkeyOwner()
		require.NoError(t, mk.JoinCommunity(ctx, owner, "general", 10))
		mk.storeService.deleteErrors = map[string]error{
			string(types.KeyJoin(owner, "general")): errors.New("leave delete failed"),
		}

		_, err := am.UnfollowTopic(ctx, &types.MsgUnfollowTopic{
			EnvelopePubkey: pub,
			Target:         owner,
			Topic:          "general",
		})
		require.ErrorContains(t, err, "leave delete failed")
	})

	t.Run("block writes pattern", func(t *testing.T) {
		mk, ctx, am := setupModule(t)
		pub, owner := testPubkeyOwner()
		mk.storeService.setErrors = map[string]error{
			string(types.KeyBlockCommunityNext(owner)): errors.New("block write failed"),
		}

		_, err := am.BlockTopic(ctx, &types.MsgBlockTopic{
			EnvelopePubkey: pub,
			Topic:          "general",
		})
		require.ErrorContains(t, err, "block write failed")
	})

	t.Run("block leaves matching community", func(t *testing.T) {
		mk, ctx, am := setupModule(t)
		pub, owner := testPubkeyOwner()
		require.NoError(t, mk.JoinCommunity(ctx, owner, "general", 10))
		mk.storeService.deleteErrors = map[string]error{
			string(types.KeyJoin(owner, "general")): errors.New("matched leave failed"),
		}

		_, err := am.BlockTopic(ctx, &types.MsgBlockTopic{
			EnvelopePubkey: pub,
			Topic:          "general",
		})
		require.ErrorContains(t, err, "matched leave failed")
	})

	t.Run("unblock removes pattern", func(t *testing.T) {
		mk, ctx, am := setupModule(t)
		pub, owner := testPubkeyOwner()
		require.NoError(t, mk.AddBlockedCommunity(ctx, owner, "general", 10))
		mk.storeService.deleteErrors = map[string]error{
			string(types.KeyBlockCommunity(owner, 0, "general")): errors.New("unblock delete failed"),
		}

		_, err := am.UnblockTopic(ctx, &types.MsgUnblockTopic{
			EnvelopePubkey: pub,
			Topic:          "general",
		})
		require.ErrorContains(t, err, "unblock delete failed")
	})
}

func TestPostAcceptsLegacyAndModernProtocolVersions(t *testing.T) {
	for _, version := range []uint32{0, types.ProtocolVersionV139} {
		t.Run(string(rune('0'+version)), func(t *testing.T) {
			_, ctx, am := setupModule(t)
			pub, _ := testPubkeyOwner()
			ctx = ctx.WithTxBytes([]byte{byte(version + 1)})
			_, err := am.Post(ctx, &types.MsgPost{
				Authority:       genAddr(byte(version + 50)),
				EnvelopePubkey:  pub,
				Community:       "general",
				Title:           "title",
				Content:         "content",
				ProtocolVersion: version,
			})
			require.NoError(t, err)
		})
	}

	_, ctx, am := setupModule(t)
	pub, _ := testPubkeyOwner()
	ctx = ctx.WithTxBytes([]byte("unsupported-version"))
	_, err := am.Post(ctx, &types.MsgPost{
		Authority:       genAddr(55),
		EnvelopePubkey:  pub,
		Community:       "general",
		Title:           "title",
		Content:         "content",
		ProtocolVersion: 2,
	})
	require.ErrorContains(t, err, "protocol_version must be 0 or 1")
}

func TestLegacyReplyWithoutMetadataIsReadOnly(t *testing.T) {
	_, ctx, am := setupModule(t)
	pub, _ := testPubkeyOwner()
	ctx = ctx.WithTxBytes([]byte("legacy-reply"))
	_, err := am.Post(ctx, &types.MsgPost{
		Authority:       genAddr(56),
		EnvelopePubkey:  pub,
		Target:          genTxHash(999),
		Content:         "reply",
		ProtocolVersion: 0,
	})
	require.EqualError(t, err, "legacy_thread_read_only")
}

func TestSubscribeLegacyWireValuesUseOneSubscriberPeriod(t *testing.T) {
	tests := []struct {
		name      string
		level     uint32
		gift      bool
		recipient string
	}{
		{name: "level 1 self", level: 1},
		{name: "level 10 self", level: 10},
		{name: "level 1 gift", level: 1, gift: true, recipient: genAddr(88)},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			mk, ctx, am := setupModule(t)
			pub, owner := testPubkeyOwner()
			params := mk.GetParams(ctx)
			tier := params.GetTierConfig(types.LevelSubscriber)
			require.NotNil(t, tier)
			fundAccount(mk, owner, tier.PeriodFee)

			target := ""
			expectedOwner := owner
			if tt.gift {
				target = tt.recipient
				expectedOwner = target
				ensureUsername(t, mk, ctx, target, "gift-recipient")
			}
			_, err := am.Subscribe(ctx, &types.MsgSubscribe{
				Authority:      testAccAddressString(),
				EnvelopePubkey: pub,
				Level:          tt.level,
				Target:         target,
				PeriodCount:    0,
			})
			require.NoError(t, err)

			core := loadCore(t, mk, ctx, expectedOwner)
			require.Equal(t, int32(types.LevelSubscriber), core.Level)
			require.Equal(t, ctx.BlockTime().Unix()+int64(params.SubscriptionPeriod)*60, core.SubscriptionExpiry)
		})
	}
}

func TestSubscribeRejectsLegacyAliasesOutsideLegacyWireShape(t *testing.T) {
	mk, ctx, am := setupModule(t)
	pub, owner := testPubkeyOwner()
	tier := mk.GetParams(ctx).GetTierConfig(types.LevelSubscriber)
	require.NotNil(t, tier)
	fundAccount(mk, owner, tier.PeriodFee)

	_, err := am.Subscribe(ctx, &types.MsgSubscribe{
		Authority:      testAccAddressString(),
		EnvelopePubkey: pub,
		Level:          10,
		PeriodCount:    1,
	})
	require.ErrorContains(t, err, "legacy level 10 requires period_count 0")

	// Level 0 is not purchasable on either wire shape. The legacy exemption is
	// for level 10 only, and an omitted period_count must never turn an invalid
	// level into a subscriber tranche.
	for _, period := range []uint32{0, 1, 12} {
		before := mk.bank.balances[owner]
		_, err = am.Subscribe(ctx, &types.MsgSubscribe{
			Authority:      testAccAddressString(),
			EnvelopePubkey: pub,
			Level:          0,
			PeriodCount:    period,
		})
		require.ErrorContains(t, err, "invalid level 0")
		require.True(t, mk.bank.balances[owner].Equal(before))
		core := loadCore(t, mk, ctx, owner)
		require.NotEqual(t, int32(types.LevelSubscriber), core.Level)
		require.Equal(t, int64(0), core.SubscriptionExpiry)
	}
}
