package core

import (
	"bytes"
	"encoding/json"
	"fmt"
	"testing"

	"cosmossdk.io/log/v2"
	"github.com/cosmos/cosmos-sdk/crypto/keys/secp256k1"
	sdk "github.com/cosmos/cosmos-sdk/types"
	"github.com/stretchr/testify/require"

	"mirage/x/core/types"
)

// genAddr returns a deterministic mirage1... address based on an index byte.
func genAddr(i byte) string {
	raw := bytes.Repeat([]byte{i}, 20)
	return sdk.AccAddress(raw).String()
}

// genTxHash returns a deterministic 64-char hex hash for tests.
func genTxHash(i int) string {
	return fmt.Sprintf("%064x", i)
}

// setupModule creates a mock keeper, context, and module with default params.
// It also ensures the test pubkey owner has a username set (required for all user txs).
func setupModule(t *testing.T) (*mockKeeper, sdk.Context, AppModule) {
	mk := newMockKeeper()
	ctx := newMockContext().WithLogger(log.NewNopLogger())
	am := newTestModule(mk)
	_, owner := testPubkeyOwner()
	ensureUsername(t, mk, ctx, owner, "Anon-testuser")
	return mk, ctx, am
}

func seedClaimedCommunity(t *testing.T, mk *mockKeeper, ctx sdk.Context, slug string) sdk.Context {
	t.Helper()
	return ctx.WithTxBytes([]byte("test-post-tx"))
}

// =========================================================================
// FollowUser: hard cap (reject at limit, must unfollow first)
// =========================================================================

func TestFollowUserHardCapFreeTier(t *testing.T) {
	mk, ctx, am := setupModule(t)
	pub, owner := testPubkeyOwner()

	params := mk.GetParams(ctx)
	params.Tiers[0].MaxFollowedUsers = 3
	require.NoError(t, mk.SetParams(ctx, params))

	for i := byte(1); i <= 3; i++ {
		_, err := am.FollowUser(ctx, &types.MsgFollowUser{
			Authority: "not-gov", EnvelopePubkey: pub, Target: owner, User: genAddr(i),
		})
		require.NoError(t, err)
	}

	// 4th should be rejected
	_, err := am.FollowUser(ctx, &types.MsgFollowUser{
		Authority: "not-gov", EnvelopePubkey: pub, Target: owner, User: genAddr(0xFF),
	})
	require.Error(t, err)
	require.Contains(t, err.Error(), "limit reached")
}

func TestFollowUserSucceedsAfterUnfollow(t *testing.T) {
	mk, ctx, am := setupModule(t)
	pub, owner := testPubkeyOwner()

	params := mk.GetParams(ctx)
	params.Tiers[0].MaxFollowedUsers = 2
	require.NoError(t, mk.SetParams(ctx, params))

	a := genAddr(0x0A)
	b := genAddr(0x0B)
	c := genAddr(0x0C)

	_, err := am.FollowUser(ctx, &types.MsgFollowUser{Authority: "not-gov", EnvelopePubkey: pub, Target: owner, User: a})
	require.NoError(t, err)
	_, err = am.FollowUser(ctx, &types.MsgFollowUser{Authority: "not-gov", EnvelopePubkey: pub, Target: owner, User: b})
	require.NoError(t, err)

	// At limit
	_, err = am.FollowUser(ctx, &types.MsgFollowUser{Authority: "not-gov", EnvelopePubkey: pub, Target: owner, User: c})
	require.Error(t, err)

	// Unfollow one
	_, err = am.UnfollowUser(ctx, &types.MsgUnfollowUser{Authority: "not-gov", EnvelopePubkey: pub, Target: owner, User: a})
	require.NoError(t, err)

	// Now follow should work
	_, err = am.FollowUser(ctx, &types.MsgFollowUser{Authority: "not-gov", EnvelopePubkey: pub, Target: owner, User: c})
	require.NoError(t, err)

	got, _ := mk.ListFollowedUsers(ctx, owner)
	require.ElementsMatch(t, []string{b, c}, got)
}

func TestFollowUserIdempotent(t *testing.T) {
	mk, ctx, am := setupModule(t)
	pub, owner := testPubkeyOwner()

	params := mk.GetParams(ctx)
	params.Tiers[0].MaxFollowedUsers = 1
	require.NoError(t, mk.SetParams(ctx, params))

	user := genAddr(0x01)
	_, err := am.FollowUser(ctx, &types.MsgFollowUser{Authority: "not-gov", EnvelopePubkey: pub, Target: owner, User: user})
	require.NoError(t, err)

	// Re-follow same — should be idempotent
	_, err = am.FollowUser(ctx, &types.MsgFollowUser{Authority: "not-gov", EnvelopePubkey: pub, Target: owner, User: user})
	require.NoError(t, err)

	got, _ := mk.ListFollowedUsers(ctx, owner)
	require.Equal(t, []string{user}, got)
}

// =========================================================================
// JoinCommunity: hard cap (reject at limit, must leave first)
// =========================================================================

func TestJoinCommunityHardCapFreeTier(t *testing.T) {
	mk, ctx, am := setupModule(t)
	pub, _ := testPubkeyOwner()

	params := mk.GetParams(ctx)
	params.Tiers[0].MaxJoinedCommunities = 3
	require.NoError(t, mk.SetParams(ctx, params))

	for _, slug := range []string{"alpha", "beta", "gamma"} {
		_, err := am.JoinCommunity(ctx, &types.MsgJoinCommunity{EnvelopePubkey: pub, Community: slug})
		require.NoError(t, err)
	}

	// 4th should be rejected
	_, err := am.JoinCommunity(ctx, &types.MsgJoinCommunity{EnvelopePubkey: pub, Community: "delta"})
	require.Error(t, err)
	require.Contains(t, err.Error(), "cap reached")
}

func TestJoinCommunitySucceedsAfterLeave(t *testing.T) {
	mk, ctx, am := setupModule(t)
	pub, owner := testPubkeyOwner()

	params := mk.GetParams(ctx)
	params.Tiers[0].MaxJoinedCommunities = 2
	require.NoError(t, mk.SetParams(ctx, params))

	_, err := am.JoinCommunity(ctx, &types.MsgJoinCommunity{EnvelopePubkey: pub, Community: "alpha"})
	require.NoError(t, err)
	_, err = am.JoinCommunity(ctx, &types.MsgJoinCommunity{EnvelopePubkey: pub, Community: "beta"})
	require.NoError(t, err)

	_, err = am.JoinCommunity(ctx, &types.MsgJoinCommunity{EnvelopePubkey: pub, Community: "gamma"})
	require.Error(t, err)

	_, err = am.LeaveCommunity(ctx, &types.MsgLeaveCommunity{EnvelopePubkey: pub, Community: "alpha"})
	require.NoError(t, err)

	_, err = am.JoinCommunity(ctx, &types.MsgJoinCommunity{EnvelopePubkey: pub, Community: "gamma"})
	require.NoError(t, err)

	got, err := mk.ListJoinedCommunities(ctx, owner)
	require.NoError(t, err)
	require.ElementsMatch(t, []string{"beta", "gamma"}, got)
}

// A stored list longer than the current cap has to stay readable. It happens
// whenever a subscriber lapses to the free tier or governance lowers the limit,
// and when the reader enforced the cap instead it failed GetProfiles for those
// accounts, which crash-looped the indexer.
func TestListJoinedCommunitiesReadsPastLoweredCap(t *testing.T) {
	mk, ctx, am := setupModule(t)
	pub, owner := testPubkeyOwner()

	params := mk.GetParams(ctx)
	params.Tiers[0].MaxJoinedCommunities = 3
	require.NoError(t, mk.SetParams(ctx, params))

	for _, slug := range []string{"alpha", "beta", "gamma"} {
		_, err := am.JoinCommunity(ctx, &types.MsgJoinCommunity{EnvelopePubkey: pub, Community: slug})
		require.NoError(t, err)
	}

	params.Tiers[0].MaxJoinedCommunities = 1
	require.NoError(t, mk.SetParams(ctx, params))

	got, err := mk.ListJoinedCommunities(ctx, owner)
	require.NoError(t, err)
	require.ElementsMatch(t, []string{"alpha", "beta", "gamma"}, got)

	// Still a hard cap for new joins.
	_, err = am.JoinCommunity(ctx, &types.MsgJoinCommunity{EnvelopePubkey: pub, Community: "delta"})
	require.ErrorContains(t, err, "cap reached")
}

func TestJoinCommunityIdempotent(t *testing.T) {
	mk, ctx, am := setupModule(t)
	pub, owner := testPubkeyOwner()

	params := mk.GetParams(ctx)
	params.Tiers[0].MaxJoinedCommunities = 1
	require.NoError(t, mk.SetParams(ctx, params))

	_, err := am.JoinCommunity(ctx, &types.MsgJoinCommunity{EnvelopePubkey: pub, Community: "alpha"})
	require.NoError(t, err)

	_, err = am.JoinCommunity(ctx, &types.MsgJoinCommunity{EnvelopePubkey: pub, Community: "alpha"})
	require.NoError(t, err)

	got, err := mk.ListJoinedCommunities(ctx, owner)
	require.NoError(t, err)
	require.Equal(t, []string{"alpha"}, got)
}

// =========================================================================
// BlockPost: deque behavior (evict oldest, NOT reject)
// =========================================================================

func TestBlockPostDequeEviction(t *testing.T) {
	mk, ctx, am := setupModule(t)
	pub, owner := testPubkeyOwner()

	params := mk.GetParams(ctx)
	params.Tiers[0].MaxBlockedPosts = 3
	require.NoError(t, mk.SetParams(ctx, params))

	hashes := []string{genTxHash(1), genTxHash(2), genTxHash(3), genTxHash(4)}
	for _, h := range hashes {
		_, err := am.BlockPost(ctx, &types.MsgBlockPost{
			Authority: "not-gov", EnvelopePubkey: pub, Target: h,
		})
		require.NoError(t, err, "blocking %s should succeed (deque)", h)
	}

	got, _ := mk.ListBlockedPosts(ctx, owner)
	require.Len(t, got, 3, "deque should cap at 3")
	require.Equal(t, []string{genTxHash(2), genTxHash(3), genTxHash(4)}, got, "oldest should be evicted")
}

func TestBlockPostDequeEvictsOldestNotNewest(t *testing.T) {
	mk, ctx, am := setupModule(t)
	pub, owner := testPubkeyOwner()

	params := mk.GetParams(ctx)
	params.Tiers[0].MaxBlockedPosts = 2
	require.NoError(t, mk.SetParams(ctx, params))

	h1, h2, h3 := genTxHash(1), genTxHash(2), genTxHash(3)
	for _, h := range []string{h1, h2, h3} {
		_, err := am.BlockPost(ctx, &types.MsgBlockPost{Authority: "not-gov", EnvelopePubkey: pub, Target: h})
		require.NoError(t, err)
	}

	got, _ := mk.ListBlockedPosts(ctx, owner)
	require.Equal(t, []string{h2, h3}, got, "first entry should have been evicted")
}

// =========================================================================
// BlockUser: deque behavior (evict oldest, NOT reject)
// =========================================================================

func TestBlockUserDequeEviction(t *testing.T) {
	mk, ctx, am := setupModule(t)
	pub, owner := testPubkeyOwner()

	params := mk.GetParams(ctx)
	params.Tiers[0].MaxBlockedUsers = 3
	require.NoError(t, mk.SetParams(ctx, params))

	targets := []string{genAddr(1), genAddr(2), genAddr(3), genAddr(4)}
	for _, target := range targets {
		_, err := am.BlockUser(ctx, &types.MsgBlockUser{
			Authority: "not-gov", EnvelopePubkey: pub, Target: target,
		})
		require.NoError(t, err, "blocking should always succeed (deque)")
	}

	got, _ := mk.ListBlockedUsers(ctx, owner)
	require.Len(t, got, 3)
	require.Equal(t, []string{genAddr(2), genAddr(3), genAddr(4)}, got)
}

// =========================================================================
// BlockCommunity: deque behavior (evict oldest, NOT reject)
// =========================================================================

func TestBlockCommunityDequeEviction(t *testing.T) {
	mk, ctx, am := setupModule(t)
	pub, owner := testPubkeyOwner()

	params := mk.GetParams(ctx)
	params.Tiers[0].MaxBlockedCommunities = 2
	require.NoError(t, mk.SetParams(ctx, params))

	for _, slug := range []string{"alpha", "beta", "gamma"} {
		_, err := am.BlockCommunity(ctx, &types.MsgBlockCommunity{
			EnvelopePubkey: pub, Community: slug,
		})
		require.NoError(t, err, "blocking should always succeed (deque)")
	}

	got, err := mk.ListBlockedCommunities(ctx, owner)
	require.NoError(t, err)
	require.Equal(t, []string{"beta", "gamma"}, got, "oldest should be evicted")
}

// =========================================================================
// Tier-based limits differ between Free, Subscriber, Agent
// =========================================================================

func TestTierLimitsFollowUserFreeLowerThanSubscriber(t *testing.T) {
	mk, ctx, am := setupModule(t)
	pub, owner := testPubkeyOwner()

	params := mk.GetParams(ctx)
	freeTier := params.GetTierConfig(types.LevelFree)
	subTier := params.GetTierConfig(types.LevelSubscriber)
	require.Less(t, freeTier.MaxFollowedUsers, subTier.MaxFollowedUsers)

	// Set free-tier limit to 2 for fast testing
	params.Tiers[0].MaxFollowedUsers = 2
	require.NoError(t, mk.SetParams(ctx, params))

	_, err := am.FollowUser(ctx, &types.MsgFollowUser{Authority: "not-gov", EnvelopePubkey: pub, Target: owner, User: genAddr(1)})
	require.NoError(t, err)
	_, err = am.FollowUser(ctx, &types.MsgFollowUser{Authority: "not-gov", EnvelopePubkey: pub, Target: owner, User: genAddr(2)})
	require.NoError(t, err)

	// Free at limit
	_, err = am.FollowUser(ctx, &types.MsgFollowUser{Authority: "not-gov", EnvelopePubkey: pub, Target: owner, User: genAddr(3)})
	require.Error(t, err)

	// Upgrade to subscriber
	setProfileLevel(t, mk, ctx, owner, int32(types.LevelSubscriber))

	// Now should succeed (subscriber limit is higher)
	_, err = am.FollowUser(ctx, &types.MsgFollowUser{Authority: "not-gov", EnvelopePubkey: pub, Target: owner, User: genAddr(3)})
	require.NoError(t, err)
}

func TestTierLimitsJoinCommunityFreeLowerThanSubscriber(t *testing.T) {
	mk, ctx, am := setupModule(t)
	pub, owner := testPubkeyOwner()

	params := mk.GetParams(ctx)
	params.Tiers[0].MaxJoinedCommunities = 2
	require.NoError(t, mk.SetParams(ctx, params))

	_, err := am.JoinCommunity(ctx, &types.MsgJoinCommunity{EnvelopePubkey: pub, Community: "alpha"})
	require.NoError(t, err)
	_, err = am.JoinCommunity(ctx, &types.MsgJoinCommunity{EnvelopePubkey: pub, Community: "beta"})
	require.NoError(t, err)

	_, err = am.JoinCommunity(ctx, &types.MsgJoinCommunity{EnvelopePubkey: pub, Community: "gamma"})
	require.Error(t, err)

	setProfileLevel(t, mk, ctx, owner, int32(types.LevelSubscriber))

	_, err = am.JoinCommunity(ctx, &types.MsgJoinCommunity{EnvelopePubkey: pub, Community: "gamma"})
	require.NoError(t, err)
}

func TestSetUsernameFreeTierForcesAnonPrefix(t *testing.T) {
	mk, ctx, am := setupModule(t)
	pub, owner := testPubkeyOwner()
	setProfileLevel(t, mk, ctx, owner, 0)

	_, err := am.SetUsername(ctx, &types.MsgSetUsername{
		Authority:      "not-gov",
		EnvelopePubkey: pub,
		Target:         owner,
		Username:       "coolname",
	})
	require.NoError(t, err)

	bz, found, _ := mk.GetProfileCore(ctx, owner)
	require.True(t, found)
	var core types.ProfileCore
	require.NoError(t, json.Unmarshal(bz, &core))
	require.Contains(t, core.Username, "Anon-", "free tier must have Anon- prefix")
}

func TestSetUsernameSubscriberCanRemoveAnon(t *testing.T) {
	mk, ctx, am := setupModule(t)
	pub, owner := testPubkeyOwner()
	setProfileLevel(t, mk, ctx, owner, int32(types.LevelSubscriber))

	_, err := am.SetUsername(ctx, &types.MsgSetUsername{
		Authority:      "not-gov",
		EnvelopePubkey: pub,
		Target:         owner,
		Username:       "coolname",
	})
	require.NoError(t, err)

	bz, found, _ := mk.GetProfileCore(ctx, owner)
	require.True(t, found)
	var core types.ProfileCore
	require.NoError(t, json.Unmarshal(bz, &core))
	require.Equal(t, "coolname", core.Username, "subscriber can set custom username")
}

func TestSetUsernameRejectsLeadingHyphen(t *testing.T) {
	cases := []struct {
		name     string
		level    int32
		username string
	}{
		{"subscriber", int32(types.LevelSubscriber), "-coolname"},
		{"subscriber_double_hyphen", int32(types.LevelSubscriber), "--coolname"},
		{"free", int32(types.LevelFree), "-coolname"},
		{"free_behind_anon_prefix", int32(types.LevelFree), "Anon--coolname"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			mk, ctx, am := setupModule(t)
			pub, owner := testPubkeyOwner()
			setProfileLevel(t, mk, ctx, owner, tc.level)

			_, err := am.SetUsername(ctx, &types.MsgSetUsername{
				Authority:      "not-gov",
				EnvelopePubkey: pub,
				Target:         owner,
				Username:       tc.username,
			})
			require.Error(t, err)
			require.Contains(t, err.Error(), "invalid username")
		})
	}
}

// =========================================================================
// Content and title length limits per tier
// =========================================================================

func TestPostContentLengthFreeTierRejectsOversize(t *testing.T) {
	mk, ctx, am := setupModule(t)
	ctx = seedClaimedCommunity(t, mk, ctx, "test")
	pub, _ := testPubkeyOwner()
	authority := genAddr(40)

	params := mk.GetParams(ctx)
	maxContent := params.Tiers[0].MaxContentLength // 1000

	_, err := am.Post(ctx, &types.MsgPost{
		Authority:       authority,
		EnvelopePubkey:  pub,
		Target:          "",
		Community:       "test",
		ProtocolVersion: types.ProtocolVersionV139,
		Title:           "Valid Title",
		Content:         string(bytes.Repeat([]byte("x"), int(maxContent)+1)),
	})
	require.Error(t, err)
	require.Contains(t, err.Error(), "content exceeds limit")
	valoper, err := mk.AccToValoper(authority)
	require.NoError(t, err)
	require.True(t, mk.GetRelayCredit(ctx, valoper).IsZero(), "failed post must not earn relay credit")
}

func TestPostContentLengthSubscriberHigherLimit(t *testing.T) {
	mk, ctx, am := setupModule(t)
	ctx = seedClaimedCommunity(t, mk, ctx, "test")
	pub, owner := testPubkeyOwner()
	setProfileLevel(t, mk, ctx, owner, int32(types.LevelSubscriber))

	params := mk.GetParams(ctx)
	freeMax := params.Tiers[0].MaxContentLength // 1000
	subMax := params.Tiers[1].MaxContentLength  // 20000
	require.Greater(t, subMax, freeMax)
	authority := genAddr(41)

	content := string(bytes.Repeat([]byte("x"), int(freeMax)+1))
	_, err := am.Post(ctx, &types.MsgPost{
		Authority:       authority,
		EnvelopePubkey:  pub,
		Target:          "",
		Community:       "test",
		ProtocolVersion: types.ProtocolVersionV139,
		Title:           "Valid Title",
		Content:         content,
	})
	require.NoError(t, err)
	valoper, err := mk.AccToValoper(authority)
	require.NoError(t, err)
	require.Equal(t, "1", mk.GetRelayCredit(ctx, valoper).String())
}

func TestPostTitleLengthFreeTierRejectsOversize(t *testing.T) {
	mk, ctx, am := setupModule(t)
	ctx = seedClaimedCommunity(t, mk, ctx, "test")
	pub, _ := testPubkeyOwner()
	authority := genAddr(42)

	params := mk.GetParams(ctx)
	maxTitle := params.Tiers[0].MaxTitleLength // 150

	_, err := am.Post(ctx, &types.MsgPost{
		Authority:       authority,
		EnvelopePubkey:  pub,
		Target:          "",
		Community:       "test",
		ProtocolVersion: types.ProtocolVersionV139,
		Title:           string(bytes.Repeat([]byte("x"), int(maxTitle)+1)),
		Content:         "valid content",
	})
	require.Error(t, err)
	require.Contains(t, err.Error(), "title exceeds limit")
	valoper, err := mk.AccToValoper(authority)
	require.NoError(t, err)
	require.True(t, mk.GetRelayCredit(ctx, valoper).IsZero(), "failed post must not earn relay credit")
}

func TestPostTitleLengthSubscriberHigherLimit(t *testing.T) {
	mk, ctx, am := setupModule(t)
	ctx = seedClaimedCommunity(t, mk, ctx, "test")
	pub, owner := testPubkeyOwner()
	setProfileLevel(t, mk, ctx, owner, int32(types.LevelSubscriber))

	params := mk.GetParams(ctx)
	freeMaxTitle := params.Tiers[0].MaxTitleLength // 150
	subMaxTitle := params.Tiers[1].MaxTitleLength  // 300
	require.Greater(t, subMaxTitle, freeMaxTitle)
	authority := genAddr(43)

	title := string(bytes.Repeat([]byte("x"), int(freeMaxTitle)+1))
	_, err := am.Post(ctx, &types.MsgPost{
		Authority:       authority,
		EnvelopePubkey:  pub,
		Target:          "",
		Community:       "test",
		ProtocolVersion: types.ProtocolVersionV139,
		Title:           title,
		Content:         "valid content",
	})
	require.NoError(t, err)
	valoper, err := mk.AccToValoper(authority)
	require.NoError(t, err)
	require.Equal(t, "1", mk.GetRelayCredit(ctx, valoper).String())
}

// =========================================================================
// DefaultTiers: verify exact values from the specification
// =========================================================================

func TestDefaultTiersExactValues(t *testing.T) {
	tiers := types.DefaultTiers()
	require.Len(t, tiers, 3)

	free := tiers[0]
	require.Equal(t, uint64(0), free.PeriodFee)
	require.Equal(t, uint64(25), free.MaxFollowedUsers)
	require.Equal(t, uint64(25), free.MaxJoinedCommunities)
	require.Equal(t, uint64(25), free.MaxBlockedUsers)
	require.Equal(t, uint64(25), free.MaxBlockedPosts)
	require.Equal(t, uint64(25), free.MaxBlockedCommunities)
	require.Equal(t, uint64(150), free.MaxTitleLength)
	require.Equal(t, uint64(1000), free.MaxContentLength)
	require.Equal(t, uint64(10), free.EditingTimeMins)
	require.Equal(t, 1.0, free.VoteWeight)
	require.Equal(t, uint64(0), free.MaxCurationMemberships)
	require.Equal(t, uint64(0), free.MaxDailyRelays)
	require.False(t, free.CanRemoveAnon)
	require.False(t, free.CanHaveBiography)
	require.False(t, free.CanHaveAvatar)
	require.False(t, free.CanHaveBanner)
	require.False(t, free.CanHaveFlair)

	sub := tiers[1]
	require.Equal(t, uint64(100_000_000_000), sub.PeriodFee)
	require.Equal(t, uint64(500), sub.MaxFollowedUsers)
	require.Equal(t, uint64(500), sub.MaxJoinedCommunities)
	require.Equal(t, uint64(500), sub.MaxBlockedUsers)
	require.Equal(t, uint64(500), sub.MaxBlockedPosts)
	require.Equal(t, uint64(500), sub.MaxBlockedCommunities)
	require.Equal(t, uint64(300), sub.MaxTitleLength)
	require.Equal(t, uint64(20000), sub.MaxContentLength)
	require.Equal(t, uint64(360), sub.EditingTimeMins)
	require.Equal(t, 1.33, sub.VoteWeight)
	require.Equal(t, uint64(10), sub.MaxCurationMemberships)
	require.Equal(t, uint64(250), sub.MaxDailyRelays)
	require.True(t, sub.CanRemoveAnon)
	require.True(t, sub.CanHaveBiography)
	require.True(t, sub.CanHaveAvatar)
	require.True(t, sub.CanHaveBanner)
	require.True(t, sub.CanHaveFlair)

	admin := tiers[2]
	require.Equal(t, uint64(0), admin.PeriodFee)
	require.Equal(t, uint64(1000), admin.MaxCurationMemberships)
	require.Equal(t, uint64(1000), admin.MaxDailyRelays)
	require.Equal(t, uint64(20000), admin.MaxContentLength)
}

func TestGetTierConfigValidLevels(t *testing.T) {
	p := types.DefaultParams()

	free := p.GetTierConfig(0)
	require.NotNil(t, free)
	require.Equal(t, uint64(0), free.PeriodFee)

	sub := p.GetTierConfig(1)
	require.NotNil(t, sub)
	require.Equal(t, uint64(100_000_000_000), sub.PeriodFee)

	require.Nil(t, p.GetTierConfig(10))

	admin := p.GetTierConfig(100)
	require.NotNil(t, admin)
	require.Equal(t, uint64(1000), admin.MaxCurationMemberships)
	require.NotEqual(t, sub, admin, "admin has its own tier config")

	admin200 := p.GetTierConfig(200)
	require.NotNil(t, admin200)
	require.Equal(t, admin, admin200)
}

func TestGetTierConfigInvalidLevelsReturnNil(t *testing.T) {
	p := types.DefaultParams()

	for _, invalidLevel := range []int{-1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 50, 99} {
		tc := p.GetTierConfig(invalidLevel)
		require.Nil(t, tc, "level %d should return nil tier config", invalidLevel)
	}
}

func TestValidSubscriptionLevels(t *testing.T) {
	require.True(t, types.ValidSubscriptionLevels[1])
	require.False(t, types.ValidSubscriptionLevels[10])

	require.False(t, types.ValidSubscriptionLevels[0])
	require.False(t, types.ValidSubscriptionLevels[2])
	require.False(t, types.ValidSubscriptionLevels[3])
	require.False(t, types.ValidSubscriptionLevels[9])
	require.False(t, types.ValidSubscriptionLevels[100])
}

func TestLevelToTierIndexExhaustive(t *testing.T) {
	require.Equal(t, 0, types.LevelToTierIndex(0))
	require.Equal(t, 1, types.LevelToTierIndex(1))
	require.Equal(t, -1, types.LevelToTierIndex(10))
	require.Equal(t, 2, types.LevelToTierIndex(100))
	require.Equal(t, 2, types.LevelToTierIndex(255))

	for _, invalid := range []int{-1, -100, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 50, 99} {
		require.Equal(t, -1, types.LevelToTierIndex(invalid), "level %d should map to -1", invalid)
	}
}

// =========================================================================
// Blocked lists: verify deque keeps newest entries
// =========================================================================

func TestBlockUserDequeKeepsNewest(t *testing.T) {
	mk, ctx, am := setupModule(t)
	pub, owner := testPubkeyOwner()

	params := mk.GetParams(ctx)
	params.Tiers[0].MaxBlockedUsers = 5
	require.NoError(t, mk.SetParams(ctx, params))

	// Block 8 users — only last 5 should remain
	for i := byte(1); i <= 8; i++ {
		_, err := am.BlockUser(ctx, &types.MsgBlockUser{
			Authority: "not-gov", EnvelopePubkey: pub, Target: genAddr(i),
		})
		require.NoError(t, err)
	}

	got, _ := mk.ListBlockedUsers(ctx, owner)
	require.Len(t, got, 5)
	// Should be addresses 4,5,6,7,8
	for i, addr := range got {
		expected := genAddr(byte(i + 4))
		require.Equal(t, expected, addr)
	}
}

func TestBlockPostDequeKeepsNewest(t *testing.T) {
	mk, ctx, am := setupModule(t)
	pub, owner := testPubkeyOwner()

	params := mk.GetParams(ctx)
	params.Tiers[0].MaxBlockedPosts = 4
	require.NoError(t, mk.SetParams(ctx, params))

	for i := 1; i <= 7; i++ {
		_, err := am.BlockPost(ctx, &types.MsgBlockPost{
			Authority: "not-gov", EnvelopePubkey: pub, Target: genTxHash(i),
		})
		require.NoError(t, err)
	}

	got, _ := mk.ListBlockedPosts(ctx, owner)
	require.Len(t, got, 4)
	require.Equal(t, []string{genTxHash(4), genTxHash(5), genTxHash(6), genTxHash(7)}, got)
}

func TestBlockedListZeroLimitRejectsAdds(t *testing.T) {
	mk, ctx, am := setupModule(t)
	pub, _ := testPubkeyOwner()

	params := mk.GetParams(ctx)
	params.Tiers[0].MaxBlockedUsers = 0
	params.Tiers[0].MaxBlockedPosts = 0
	params.Tiers[0].MaxBlockedCommunities = 0
	require.NoError(t, mk.SetParams(ctx, params))

	_, err := am.BlockUser(ctx, &types.MsgBlockUser{
		Authority: "not-gov", EnvelopePubkey: pub, Target: genAddr(1),
	})
	require.ErrorContains(t, err, "blocked user limit is zero")

	_, err = am.BlockPost(ctx, &types.MsgBlockPost{
		Authority: "not-gov", EnvelopePubkey: pub, Target: genTxHash(1),
	})
	require.ErrorContains(t, err, "blocked post limit is zero")

	// The keeper's deque helper reads a zero cap as "never evict", so this
	// must be refused at the handler like the two lists above rather than
	// growing without bound.
	_, err = am.BlockCommunity(ctx, &types.MsgBlockCommunity{
		Authority: "not-gov", EnvelopePubkey: pub, Community: "technology",
	})
	require.ErrorContains(t, err, "blocked community limit is zero")
}

// =========================================================================
// Hard cap vs deque: combined test to show the behavioral difference
// =========================================================================

func TestHardCapVsDequeContrast(t *testing.T) {
	mk, ctx, am := setupModule(t)
	pub, owner := testPubkeyOwner()

	params := mk.GetParams(ctx)
	params.Tiers[0].MaxFollowedUsers = 2
	params.Tiers[0].MaxBlockedUsers = 2
	require.NoError(t, mk.SetParams(ctx, params))

	// Follow 2 users (at limit)
	_, err := am.FollowUser(ctx, &types.MsgFollowUser{Authority: "not-gov", EnvelopePubkey: pub, Target: owner, User: genAddr(1)})
	require.NoError(t, err)
	_, err = am.FollowUser(ctx, &types.MsgFollowUser{Authority: "not-gov", EnvelopePubkey: pub, Target: owner, User: genAddr(2)})
	require.NoError(t, err)

	// 3rd follow: REJECTED (hard cap)
	_, err = am.FollowUser(ctx, &types.MsgFollowUser{Authority: "not-gov", EnvelopePubkey: pub, Target: owner, User: genAddr(3)})
	require.Error(t, err, "follow should be rejected at hard cap")

	// Block 2 users (at limit)
	_, err = am.BlockUser(ctx, &types.MsgBlockUser{Authority: "not-gov", EnvelopePubkey: pub, Target: genAddr(10)})
	require.NoError(t, err)
	_, err = am.BlockUser(ctx, &types.MsgBlockUser{Authority: "not-gov", EnvelopePubkey: pub, Target: genAddr(11)})
	require.NoError(t, err)

	// 3rd block: SUCCEEDS (deque — evicts oldest)
	_, err = am.BlockUser(ctx, &types.MsgBlockUser{Authority: "not-gov", EnvelopePubkey: pub, Target: genAddr(12)})
	require.NoError(t, err, "block should succeed with deque eviction")

	got, _ := mk.ListBlockedUsers(ctx, owner)
	require.Equal(t, []string{genAddr(11), genAddr(12)}, got, "oldest block evicted")

	followed, _ := mk.ListFollowedUsers(ctx, owner)
	require.Len(t, followed, 2, "followed list unchanged after failed 3rd follow")
}

// =========================================================================
// Username requirement enforcement
// =========================================================================

func TestRequireUsernameRejectsNoProfile(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext().WithLogger(log.NewNopLogger())
	am := newTestModule(mk)

	// Use a fresh pubkey with NO profile at all
	pub2, _ := func() ([]byte, string) {
		priv := secp256k1.PrivKey{Key: bytes.Repeat([]byte{0x04}, 32)}
		return priv.PubKey().Bytes(), sdk.AccAddress(priv.PubKey().Address()).String()
	}()

	_, err := am.Post(ctx, &types.MsgPost{
		Authority:       "not-gov",
		EnvelopePubkey:  pub2,
		Community:       "test",
		ProtocolVersion: types.ProtocolVersionV139,
		Title:           "title",
		Content:         "body",
	})
	require.Error(t, err)
	require.Contains(t, err.Error(), "username required")
}

func TestRequireUsernameRejectsEmptyUsername(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext().WithLogger(log.NewNopLogger())
	am := newTestModule(mk)

	pub, owner := testPubkeyOwner()
	// Create a profile with empty username
	core := types.ProfileCore{Owner: owner, Username: "", Level: 0}
	bz, _ := json.Marshal(core)
	_ = mk.SetProfileCore(ctx, owner, bz)

	_, err := am.FollowUser(ctx, &types.MsgFollowUser{
		Authority:      "not-gov",
		EnvelopePubkey: pub,
		Target:         owner,
		User:           genAddr(1),
	})
	require.Error(t, err)
	require.Contains(t, err.Error(), "username required")
}

func TestRequireUsernameAllowsSetUsername(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext().WithLogger(log.NewNopLogger())
	am := newTestModule(mk)

	pub, owner := testPubkeyOwner()
	// No profile at all — SetUsername should still work (it's exempt)
	_, err := am.SetUsername(ctx, &types.MsgSetUsername{
		Authority:      "not-gov",
		EnvelopePubkey: pub,
		Target:         owner,
		Username:       "newuser",
	})
	require.NoError(t, err)
}

func TestRequireUsernamePassesWithUsername(t *testing.T) {
	mk, ctx, am := setupModule(t)
	pub, owner := testPubkeyOwner()

	_, err := am.FollowUser(ctx, &types.MsgFollowUser{
		Authority:      "not-gov",
		EnvelopePubkey: pub,
		Target:         owner,
		User:           genAddr(1),
	})
	require.NoError(t, err)

	followed, _ := mk.ListFollowedUsers(ctx, owner)
	require.Equal(t, []string{genAddr(1)}, followed)
}

func TestRequireUsernameRejectsSubscribe(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext().WithLogger(log.NewNopLogger())
	am := newTestModule(mk)

	pub, _ := testPubkeyOwner()
	_, err := am.Subscribe(ctx, &types.MsgSubscribe{
		Authority:      "not-gov",
		EnvelopePubkey: pub,
		Level:          uint32(types.LevelSubscriber),
	})
	require.Error(t, err)
	require.Contains(t, err.Error(), "username required")
}

func TestRequireUsernameRejectsSetAutoRenewal(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext().WithLogger(log.NewNopLogger())
	am := newTestModule(mk)

	pub, _ := testPubkeyOwner()
	_, err := am.SetAutoRenewal(ctx, &types.MsgSetAutoRenewal{
		Authority:      "not-gov",
		EnvelopePubkey: pub,
		AutoRenew:      true,
	})
	require.Error(t, err)
	require.Contains(t, err.Error(), "username required")
}
