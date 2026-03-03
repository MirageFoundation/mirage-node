package core

import (
	"bytes"
	"encoding/json"
	"fmt"
	"testing"

	"cosmossdk.io/log"
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
func setupModule(t *testing.T) (*mockKeeper, sdk.Context, AppModule) {
	mk := newMockKeeper()
	ctx := newMockContext().WithLogger(log.NewNopLogger())
	am := newTestModule(mk)
	return mk, ctx, am
}

// =========================================================================
// EnableAgent: hard cap (reject at limit, must disable first)
// =========================================================================

func TestEnableAgentHardCapFreeTier(t *testing.T) {
	mk, ctx, am := setupModule(t)
	pub, owner := testPubkeyOwner()

	params := mk.GetParams(ctx)
	freeTier := params.GetTierConfig(types.LevelFree)
	require.NotNil(t, freeTier)
	maxAgents := int(freeTier.MaxEnabledAgents) // 5

	// Fill to max
	agents := make([]string, maxAgents)
	for i := 0; i < maxAgents; i++ {
		agents[i] = genAddr(byte(i + 1))
	}
	require.NoError(t, mk.SetProfileEnabledAgents(ctx, owner, agents))

	// Next enable should be rejected
	_, err := am.EnableAgent(ctx, &types.MsgEnableAgent{
		Authority:      "not-gov",
		EnvelopePubkey: pub,
		Target:         owner,
		Agent:          genAddr(0xFF),
	})
	require.Error(t, err)
	require.Contains(t, err.Error(), "limit reached")

	// Verify list unchanged
	got, _ := mk.GetProfileEnabledAgents(ctx, owner)
	require.Len(t, got, maxAgents)
}

func TestEnableAgentHardCapSubscriberTier(t *testing.T) {
	mk, ctx, am := setupModule(t)
	pub, owner := testPubkeyOwner()
	setProfileLevel(t, mk, ctx, owner, int32(types.LevelSubscriber))

	params := mk.GetParams(ctx)
	subTier := params.GetTierConfig(types.LevelSubscriber)
	require.NotNil(t, subTier)
	require.Equal(t, uint64(50), subTier.MaxEnabledAgents)

	// Pre-fill to max with mock data
	agents := make([]string, 50)
	for i := 0; i < 50; i++ {
		agents[i] = fmt.Sprintf("mirage1agent%04d", i)
	}
	require.NoError(t, mk.SetProfileEnabledAgents(ctx, owner, agents))

	// Should reject
	_, err := am.EnableAgent(ctx, &types.MsgEnableAgent{
		Authority:      "not-gov",
		EnvelopePubkey: pub,
		Target:         owner,
		Agent:          genAddr(0xFF),
	})
	require.Error(t, err)
	require.Contains(t, err.Error(), "limit reached")
}

func TestEnableAgentSucceedsAfterDisable(t *testing.T) {
	mk, ctx, am := setupModule(t)
	pub, owner := testPubkeyOwner()

	params := mk.GetParams(ctx)
	params.Tiers[0].MaxEnabledAgents = 3
	require.NoError(t, mk.SetParams(ctx, params))

	agentA := genAddr(0x0A)
	agentB := genAddr(0x0B)
	agentC := genAddr(0x0C)
	agentD := genAddr(0x0D)

	for _, a := range []string{agentA, agentB, agentC} {
		_, err := am.EnableAgent(ctx, &types.MsgEnableAgent{
			Authority: "not-gov", EnvelopePubkey: pub, Target: owner, Agent: a,
		})
		require.NoError(t, err)
	}

	// At limit — next should fail
	_, err := am.EnableAgent(ctx, &types.MsgEnableAgent{
		Authority: "not-gov", EnvelopePubkey: pub, Target: owner, Agent: agentD,
	})
	require.Error(t, err)

	// Disable one
	_, err = am.DisableAgent(ctx, &types.MsgDisableAgent{
		Authority: "not-gov", EnvelopePubkey: pub, Target: owner, Agent: agentB,
	})
	require.NoError(t, err)

	// Now enabling should work
	_, err = am.EnableAgent(ctx, &types.MsgEnableAgent{
		Authority: "not-gov", EnvelopePubkey: pub, Target: owner, Agent: agentD,
	})
	require.NoError(t, err)

	got, _ := mk.GetProfileEnabledAgents(ctx, owner)
	require.Equal(t, []string{agentA, agentC, agentD}, got)
}

func TestEnableAgentIdempotent(t *testing.T) {
	mk, ctx, am := setupModule(t)
	pub, owner := testPubkeyOwner()

	params := mk.GetParams(ctx)
	params.Tiers[0].MaxEnabledAgents = 2
	require.NoError(t, mk.SetParams(ctx, params))

	agent := genAddr(0x0A)
	_, err := am.EnableAgent(ctx, &types.MsgEnableAgent{
		Authority: "not-gov", EnvelopePubkey: pub, Target: owner, Agent: agent,
	})
	require.NoError(t, err)

	// Re-enable same agent — should be idempotent, not count against limit
	_, err = am.EnableAgent(ctx, &types.MsgEnableAgent{
		Authority: "not-gov", EnvelopePubkey: pub, Target: owner, Agent: agent,
	})
	require.NoError(t, err)

	got, _ := mk.GetProfileEnabledAgents(ctx, owner)
	require.Equal(t, []string{agent}, got)
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

	got, _ := mk.GetProfileFollowedUsers(ctx, owner)
	require.Equal(t, []string{b, c}, got)
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

	got, _ := mk.GetProfileFollowedUsers(ctx, owner)
	require.Equal(t, []string{user}, got)
}

// =========================================================================
// FollowTopic: hard cap (reject at limit, must unfollow first)
// =========================================================================

func TestFollowTopicHardCapFreeTier(t *testing.T) {
	mk, ctx, am := setupModule(t)
	pub, owner := testPubkeyOwner()

	params := mk.GetParams(ctx)
	params.Tiers[0].MaxFollowedTopics = 3
	require.NoError(t, mk.SetParams(ctx, params))

	for _, topic := range []string{"alpha", "beta", "gamma"} {
		_, err := am.FollowTopic(ctx, &types.MsgFollowTopic{
			Authority: "not-gov", EnvelopePubkey: pub, Target: owner, Topic: topic,
		})
		require.NoError(t, err)
	}

	// 4th should be rejected
	_, err := am.FollowTopic(ctx, &types.MsgFollowTopic{
		Authority: "not-gov", EnvelopePubkey: pub, Target: owner, Topic: "delta",
	})
	require.Error(t, err)
	require.Contains(t, err.Error(), "limit reached")
}

func TestFollowTopicSucceedsAfterUnfollow(t *testing.T) {
	mk, ctx, am := setupModule(t)
	pub, owner := testPubkeyOwner()

	params := mk.GetParams(ctx)
	params.Tiers[0].MaxFollowedTopics = 2
	require.NoError(t, mk.SetParams(ctx, params))

	_, err := am.FollowTopic(ctx, &types.MsgFollowTopic{Authority: "not-gov", EnvelopePubkey: pub, Target: owner, Topic: "alpha"})
	require.NoError(t, err)
	_, err = am.FollowTopic(ctx, &types.MsgFollowTopic{Authority: "not-gov", EnvelopePubkey: pub, Target: owner, Topic: "beta"})
	require.NoError(t, err)

	_, err = am.FollowTopic(ctx, &types.MsgFollowTopic{Authority: "not-gov", EnvelopePubkey: pub, Target: owner, Topic: "gamma"})
	require.Error(t, err)

	_, err = am.UnfollowTopic(ctx, &types.MsgUnfollowTopic{Authority: "not-gov", EnvelopePubkey: pub, Target: owner, Topic: "alpha"})
	require.NoError(t, err)

	_, err = am.FollowTopic(ctx, &types.MsgFollowTopic{Authority: "not-gov", EnvelopePubkey: pub, Target: owner, Topic: "gamma"})
	require.NoError(t, err)

	got, _ := mk.GetProfileFollowedTopics(ctx, owner)
	require.Equal(t, []string{"beta", "gamma"}, got)
}

func TestFollowTopicIdempotent(t *testing.T) {
	mk, ctx, am := setupModule(t)
	pub, owner := testPubkeyOwner()

	params := mk.GetParams(ctx)
	params.Tiers[0].MaxFollowedTopics = 1
	require.NoError(t, mk.SetParams(ctx, params))

	_, err := am.FollowTopic(ctx, &types.MsgFollowTopic{Authority: "not-gov", EnvelopePubkey: pub, Target: owner, Topic: "alpha"})
	require.NoError(t, err)

	_, err = am.FollowTopic(ctx, &types.MsgFollowTopic{Authority: "not-gov", EnvelopePubkey: pub, Target: owner, Topic: "alpha"})
	require.NoError(t, err)

	got, _ := mk.GetProfileFollowedTopics(ctx, owner)
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

	got, _ := mk.GetProfileBlockedPosts(ctx, owner)
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

	got, _ := mk.GetProfileBlockedPosts(ctx, owner)
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

	got, _ := mk.GetProfileBlockedUsers(ctx, owner)
	require.Len(t, got, 3)
	require.Equal(t, []string{genAddr(2), genAddr(3), genAddr(4)}, got)
}

// =========================================================================
// BlockTopic: deque behavior (evict oldest, NOT reject)
// =========================================================================

func TestBlockTopicDequeEviction(t *testing.T) {
	mk, ctx, am := setupModule(t)
	pub, owner := testPubkeyOwner()

	params := mk.GetParams(ctx)
	params.Tiers[0].MaxBlockedTopics = 2
	require.NoError(t, mk.SetParams(ctx, params))

	for _, topic := range []string{"alpha", "beta", "gamma"} {
		_, err := am.BlockTopic(ctx, &types.MsgBlockTopic{
			Authority: "not-gov", EnvelopePubkey: pub, Topic: topic,
		})
		require.NoError(t, err, "blocking should always succeed (deque)")
	}

	got, _ := mk.GetProfileBlockedTopics(ctx, owner)
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

func TestTierLimitsFollowTopicFreeLowerThanSubscriber(t *testing.T) {
	mk, ctx, am := setupModule(t)
	pub, owner := testPubkeyOwner()

	params := mk.GetParams(ctx)
	params.Tiers[0].MaxFollowedTopics = 2
	require.NoError(t, mk.SetParams(ctx, params))

	_, err := am.FollowTopic(ctx, &types.MsgFollowTopic{Authority: "not-gov", EnvelopePubkey: pub, Target: owner, Topic: "alpha"})
	require.NoError(t, err)
	_, err = am.FollowTopic(ctx, &types.MsgFollowTopic{Authority: "not-gov", EnvelopePubkey: pub, Target: owner, Topic: "beta"})
	require.NoError(t, err)

	_, err = am.FollowTopic(ctx, &types.MsgFollowTopic{Authority: "not-gov", EnvelopePubkey: pub, Target: owner, Topic: "gamma"})
	require.Error(t, err)

	setProfileLevel(t, mk, ctx, owner, int32(types.LevelSubscriber))

	_, err = am.FollowTopic(ctx, &types.MsgFollowTopic{Authority: "not-gov", EnvelopePubkey: pub, Target: owner, Topic: "gamma"})
	require.NoError(t, err)
}

func TestTierLimitsEnableAgentFreeLowerThanAgent(t *testing.T) {
	mk, ctx, am := setupModule(t)
	pub, owner := testPubkeyOwner()

	params := mk.GetParams(ctx)
	params.Tiers[0].MaxEnabledAgents = 2
	require.NoError(t, mk.SetParams(ctx, params))

	_, err := am.EnableAgent(ctx, &types.MsgEnableAgent{Authority: "not-gov", EnvelopePubkey: pub, Target: owner, Agent: genAddr(1)})
	require.NoError(t, err)
	_, err = am.EnableAgent(ctx, &types.MsgEnableAgent{Authority: "not-gov", EnvelopePubkey: pub, Target: owner, Agent: genAddr(2)})
	require.NoError(t, err)

	_, err = am.EnableAgent(ctx, &types.MsgEnableAgent{Authority: "not-gov", EnvelopePubkey: pub, Target: owner, Agent: genAddr(3)})
	require.Error(t, err)

	// Agent tier (level 10) has higher limit
	setProfileLevel(t, mk, ctx, owner, int32(types.LevelAgent))

	_, err = am.EnableAgent(ctx, &types.MsgEnableAgent{Authority: "not-gov", EnvelopePubkey: pub, Target: owner, Agent: genAddr(3)})
	require.NoError(t, err)
}

// =========================================================================
// SetAgents: atomic list replacement
// =========================================================================

func TestSetAgentsBasic(t *testing.T) {
	mk, ctx, am := setupModule(t)
	pub, owner := testPubkeyOwner()

	a1, a2, a3 := genAddr(1), genAddr(2), genAddr(3)
	_, err := am.SetAgents(ctx, &types.MsgSetAgents{
		Authority: "not-gov", EnvelopePubkey: pub, Target: owner,
		Agents: []string{a1, a2, a3},
	})
	require.NoError(t, err)

	got, _ := mk.GetProfileEnabledAgents(ctx, owner)
	require.Equal(t, []string{a1, a2, a3}, got)
}

func TestSetAgentsPreservesOrder(t *testing.T) {
	mk, ctx, am := setupModule(t)
	pub, owner := testPubkeyOwner()

	a1, a2, a3 := genAddr(1), genAddr(2), genAddr(3)
	_, err := am.SetAgents(ctx, &types.MsgSetAgents{
		Authority: "not-gov", EnvelopePubkey: pub, Target: owner,
		Agents: []string{a3, a1, a2},
	})
	require.NoError(t, err)

	got, _ := mk.GetProfileEnabledAgents(ctx, owner)
	require.Equal(t, []string{a3, a1, a2}, got)
}

func TestSetAgentsEmptyClears(t *testing.T) {
	mk, ctx, am := setupModule(t)
	pub, owner := testPubkeyOwner()

	require.NoError(t, mk.SetProfileEnabledAgents(ctx, owner, []string{genAddr(1), genAddr(2)}))

	_, err := am.SetAgents(ctx, &types.MsgSetAgents{
		Authority: "not-gov", EnvelopePubkey: pub, Target: owner,
		Agents: []string{},
	})
	require.NoError(t, err)

	got, _ := mk.GetProfileEnabledAgents(ctx, owner)
	require.Len(t, got, 0)
}

func TestSetAgentsRejectsDuplicates(t *testing.T) {
	_, ctx, am := setupModule(t)
	pub, owner := testPubkeyOwner()

	a1 := genAddr(1)
	_, err := am.SetAgents(ctx, &types.MsgSetAgents{
		Authority: "not-gov", EnvelopePubkey: pub, Target: owner,
		Agents: []string{a1, a1},
	})
	require.Error(t, err)
	require.Contains(t, err.Error(), "duplicate")
}

func TestSetAgentsRejectsOverLimit(t *testing.T) {
	mk, ctx, am := setupModule(t)
	pub, owner := testPubkeyOwner()

	params := mk.GetParams(ctx)
	params.Tiers[0].MaxEnabledAgents = 3
	require.NoError(t, mk.SetParams(ctx, params))

	agents := make([]string, 4)
	for i := range agents {
		agents[i] = genAddr(byte(i + 1))
	}
	_, err := am.SetAgents(ctx, &types.MsgSetAgents{
		Authority: "not-gov", EnvelopePubkey: pub, Target: owner,
		Agents: agents,
	})
	require.Error(t, err)
	require.Contains(t, err.Error(), "too many agents")
}

func TestSetAgentsReplacesExisting(t *testing.T) {
	mk, ctx, am := setupModule(t)
	pub, owner := testPubkeyOwner()

	a1, a2, a3 := genAddr(1), genAddr(2), genAddr(3)
	require.NoError(t, mk.SetProfileEnabledAgents(ctx, owner, []string{a1, a2}))

	_, err := am.SetAgents(ctx, &types.MsgSetAgents{
		Authority: "not-gov", EnvelopePubkey: pub, Target: owner,
		Agents: []string{a3, a1},
	})
	require.NoError(t, err)

	got, _ := mk.GetProfileEnabledAgents(ctx, owner)
	require.Equal(t, []string{a3, a1}, got)
}

// =========================================================================
// SetUsername: can_remove_anon enforcement
// =========================================================================

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

// =========================================================================
// Content and title length limits per tier
// =========================================================================

func TestPostContentLengthFreeTierRejectsOversize(t *testing.T) {
	mk, ctx, am := setupModule(t)
	pub, _ := testPubkeyOwner()

	params := mk.GetParams(ctx)
	maxContent := params.Tiers[0].MaxContentLength // 1000

	_, err := am.Post(ctx, &types.MsgPost{
		Authority:      "not-gov",
		EnvelopePubkey: pub,
		Target:         "",
		Topic:          "test",
		Title:          "Valid Title",
		Content:        string(bytes.Repeat([]byte("x"), int(maxContent)+1)),
	})
	require.Error(t, err)
	require.Contains(t, err.Error(), "content exceeds limit")
}

func TestPostContentLengthSubscriberHigherLimit(t *testing.T) {
	mk, ctx, am := setupModule(t)
	pub, owner := testPubkeyOwner()
	setProfileLevel(t, mk, ctx, owner, int32(types.LevelSubscriber))

	params := mk.GetParams(ctx)
	freeMax := params.Tiers[0].MaxContentLength // 1000
	subMax := params.Tiers[1].MaxContentLength  // 20000
	require.Greater(t, subMax, freeMax)

	// Content that exceeds free limit but fits subscriber limit
	content := string(bytes.Repeat([]byte("x"), int(freeMax)+1))
	_, err := am.Post(ctx, &types.MsgPost{
		Authority:      "not-gov",
		EnvelopePubkey: pub,
		Target:         "",
		Topic:          "test",
		Title:          "Valid Title",
		Content:        content,
	})
	require.NoError(t, err)
}

func TestPostTitleLengthFreeTierRejectsOversize(t *testing.T) {
	mk, ctx, am := setupModule(t)
	pub, _ := testPubkeyOwner()

	params := mk.GetParams(ctx)
	maxTitle := params.Tiers[0].MaxTitleLength // 150

	_, err := am.Post(ctx, &types.MsgPost{
		Authority:      "not-gov",
		EnvelopePubkey: pub,
		Target:         "",
		Topic:          "test",
		Title:          string(bytes.Repeat([]byte("x"), int(maxTitle)+1)),
		Content:        "valid content",
	})
	require.Error(t, err)
	require.Contains(t, err.Error(), "title exceeds limit")
}

func TestPostTitleLengthSubscriberHigherLimit(t *testing.T) {
	mk, ctx, am := setupModule(t)
	pub, owner := testPubkeyOwner()
	setProfileLevel(t, mk, ctx, owner, int32(types.LevelSubscriber))

	params := mk.GetParams(ctx)
	freeMaxTitle := params.Tiers[0].MaxTitleLength // 150
	subMaxTitle := params.Tiers[1].MaxTitleLength  // 300
	require.Greater(t, subMaxTitle, freeMaxTitle)

	title := string(bytes.Repeat([]byte("x"), int(freeMaxTitle)+1))
	_, err := am.Post(ctx, &types.MsgPost{
		Authority:      "not-gov",
		EnvelopePubkey: pub,
		Target:         "",
		Topic:          "test",
		Title:          title,
		Content:        "valid content",
	})
	require.NoError(t, err)
}

// =========================================================================
// DefaultTiers: verify exact values from the specification
// =========================================================================

func TestDefaultTiersExactValues(t *testing.T) {
	tiers := types.DefaultTiers()
	require.Len(t, tiers, 3)

	// Free tier (index 0)
	free := tiers[0]
	require.Equal(t, uint64(0), free.PeriodFee)
	require.Equal(t, uint64(5), free.MaxEnabledAgents)
	require.Equal(t, uint64(25), free.MaxFollowedUsers)
	require.Equal(t, uint64(25), free.MaxFollowedTopics)
	require.Equal(t, uint64(25), free.MaxBlockedUsers)
	require.Equal(t, uint64(25), free.MaxBlockedPosts)
	require.Equal(t, uint64(25), free.MaxBlockedTopics)
	require.Equal(t, uint64(150), free.MaxTitleLength)
	require.Equal(t, uint64(1000), free.MaxContentLength)
	require.Equal(t, uint64(10), free.EditingTimeMins)
	require.Equal(t, 1.0, free.VoteWeight)
	require.False(t, free.CanBeAgent)
	require.False(t, free.CanRemoveAnon)
	require.False(t, free.CanHaveBiography)
	require.False(t, free.CanHaveAvatar)
	require.False(t, free.CanHaveBanner)
	require.False(t, free.CanHaveFlair)

	// Subscriber tier (index 1)
	sub := tiers[1]
	require.Equal(t, uint64(100_000_000_000), sub.PeriodFee)
	require.Equal(t, uint64(50), sub.MaxEnabledAgents)
	require.Equal(t, uint64(500), sub.MaxFollowedUsers)
	require.Equal(t, uint64(500), sub.MaxFollowedTopics)
	require.Equal(t, uint64(500), sub.MaxBlockedUsers)
	require.Equal(t, uint64(500), sub.MaxBlockedPosts)
	require.Equal(t, uint64(500), sub.MaxBlockedTopics)
	require.Equal(t, uint64(300), sub.MaxTitleLength)
	require.Equal(t, uint64(20000), sub.MaxContentLength)
	require.Equal(t, uint64(360), sub.EditingTimeMins)
	require.Equal(t, 1.33, sub.VoteWeight)
	require.False(t, sub.CanBeAgent)
	require.True(t, sub.CanRemoveAnon)
	require.True(t, sub.CanHaveBiography)
	require.True(t, sub.CanHaveAvatar)
	require.True(t, sub.CanHaveBanner)
	require.True(t, sub.CanHaveFlair)

	// Agent tier (index 2)
	agent := tiers[2]
	require.Equal(t, uint64(200_000_000_000), agent.PeriodFee)
	require.Equal(t, uint64(50), agent.MaxEnabledAgents)
	require.Equal(t, uint64(500), agent.MaxFollowedUsers)
	require.Equal(t, uint64(500), agent.MaxFollowedTopics)
	require.Equal(t, uint64(500), agent.MaxBlockedUsers)
	require.Equal(t, uint64(500), agent.MaxBlockedPosts)
	require.Equal(t, uint64(500), agent.MaxBlockedTopics)
	require.Equal(t, uint64(300), agent.MaxTitleLength)
	require.Equal(t, uint64(20000), agent.MaxContentLength)
	require.Equal(t, uint64(360), agent.EditingTimeMins)
	require.Equal(t, 1.33, agent.VoteWeight)
	require.True(t, agent.CanBeAgent, "only Agent tier can be agent")
	require.True(t, agent.CanRemoveAnon)
	require.True(t, agent.CanHaveBiography)
	require.True(t, agent.CanHaveAvatar)
	require.True(t, agent.CanHaveBanner)
	require.True(t, agent.CanHaveFlair)
}

// =========================================================================
// GetTierConfig: level-to-index mapping
// =========================================================================

func TestGetTierConfigValidLevels(t *testing.T) {
	p := types.DefaultParams()

	free := p.GetTierConfig(0)
	require.NotNil(t, free)
	require.Equal(t, uint64(0), free.PeriodFee)

	sub := p.GetTierConfig(1)
	require.NotNil(t, sub)
	require.Equal(t, uint64(100_000_000_000), sub.PeriodFee)

	agent := p.GetTierConfig(10)
	require.NotNil(t, agent)
	require.Equal(t, uint64(200_000_000_000), agent.PeriodFee)
	require.True(t, agent.CanBeAgent)

	admin := p.GetTierConfig(100)
	require.NotNil(t, admin)
	require.Equal(t, agent, admin, "admin maps to agent tier config")

	admin200 := p.GetTierConfig(200)
	require.NotNil(t, admin200)
	require.Equal(t, agent, admin200)
}

func TestGetTierConfigInvalidLevelsReturnNil(t *testing.T) {
	p := types.DefaultParams()

	for _, invalidLevel := range []int{-1, 2, 3, 4, 5, 6, 7, 8, 9, 11, 50, 99} {
		tc := p.GetTierConfig(invalidLevel)
		require.Nil(t, tc, "level %d should return nil tier config", invalidLevel)
	}
}

// =========================================================================
// ValidSubscriptionLevels
// =========================================================================

func TestValidSubscriptionLevels(t *testing.T) {
	require.True(t, types.ValidSubscriptionLevels[1])
	require.True(t, types.ValidSubscriptionLevels[10])

	require.False(t, types.ValidSubscriptionLevels[0])
	require.False(t, types.ValidSubscriptionLevels[2])
	require.False(t, types.ValidSubscriptionLevels[3])
	require.False(t, types.ValidSubscriptionLevels[9])
	require.False(t, types.ValidSubscriptionLevels[100])
}

// =========================================================================
// LevelToTierIndex
// =========================================================================

func TestLevelToTierIndexExhaustive(t *testing.T) {
	require.Equal(t, 0, types.LevelToTierIndex(0))
	require.Equal(t, 1, types.LevelToTierIndex(1))
	require.Equal(t, 2, types.LevelToTierIndex(10))
	require.Equal(t, 2, types.LevelToTierIndex(100))
	require.Equal(t, 2, types.LevelToTierIndex(255))

	for _, invalid := range []int{-1, -100, 2, 3, 4, 5, 6, 7, 8, 9, 11, 50, 99} {
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

	got, _ := mk.GetProfileBlockedUsers(ctx, owner)
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

	got, _ := mk.GetProfileBlockedPosts(ctx, owner)
	require.Len(t, got, 4)
	require.Equal(t, []string{genTxHash(4), genTxHash(5), genTxHash(6), genTxHash(7)}, got)
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

	got, _ := mk.GetProfileBlockedUsers(ctx, owner)
	require.Equal(t, []string{genAddr(11), genAddr(12)}, got, "oldest block evicted")

	followed, _ := mk.GetProfileFollowedUsers(ctx, owner)
	require.Len(t, followed, 2, "followed list unchanged after failed 3rd follow")
}
