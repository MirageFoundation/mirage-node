package core

import (
	"bytes"
	"encoding/json"
	"testing"

	"cosmossdk.io/log"
	"github.com/cosmos/cosmos-sdk/codec"
	codectypes "github.com/cosmos/cosmos-sdk/codec/types"
	secp256k1 "github.com/cosmos/cosmos-sdk/crypto/keys/secp256k1"
	sdk "github.com/cosmos/cosmos-sdk/types"
	"github.com/stretchr/testify/require"

	"mirage/x/core/types"
)

func newTestModule(mk *mockKeeper) AppModule {
	interfaceRegistry := codectypes.NewInterfaceRegistry()
	cdc := codec.NewProtoCodec(interfaceRegistry)
	return NewAppModule(cdc, mk.Keeper)
}

func testPubkeyOwner() ([]byte, string) {
	priv := secp256k1.PrivKey{Key: bytes.Repeat([]byte{0x03}, 32)}
	pub := priv.PubKey().Bytes()
	owner := sdk.AccAddress(priv.PubKey().Address()).String()
	return pub, owner
}

func setProfileLevel(t *testing.T, mk *mockKeeper, ctx sdk.Context, owner string, level int32) {
	core := types.ProfileCore{
		Owner: owner,
		Level: level,
	}
	bz, err := json.Marshal(core)
	require.NoError(t, err)
	require.NoError(t, mk.SetProfileCore(ctx, owner, bz))
}

func TestValidateTopic(t *testing.T) {
	tests := []struct {
		name    string
		topic   string
		minLen  uint64
		maxLen  uint64
		wantErr bool
		errPart string
	}{
		{"valid", "abc123", 2, 10, false, ""},
		{"too short", "a", 2, 10, true, "below minimum"},
		{"too long", "abcdefghijk", 2, 10, true, "exceeds limit"},
		{"uppercase", "Abc", 2, 10, true, "lowercase alphanumeric"},
		{"symbol", "ab-c", 2, 10, true, "lowercase alphanumeric"},
		{"empty", " ", 2, 10, true, "topic required"},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			err := validateTopic(tt.topic, tt.maxLen, tt.minLen)
			if tt.wantErr {
				require.Error(t, err)
				if tt.errPart != "" {
					require.Contains(t, err.Error(), tt.errPart)
				}
			} else {
				require.NoError(t, err)
			}
		})
	}
}

func TestValidateBlockedTopicPattern(t *testing.T) {
	tests := []struct {
		name    string
		topic   string
		minLen  uint64
		maxLen  uint64
		wantErr bool
		errPart string
	}{
		{"exact valid", "beer123", 3, 10, false, ""},
		{"wildcard trailing", "beer*", 3, 10, false, ""},
		{"wildcard leading", "*beer", 3, 10, false, ""},
		{"wildcard middle", "be*er", 3, 10, false, ""},
		{"wildcard both ends", "*beer*", 3, 10, false, ""},
		{"wildcard too short", "be*", 3, 10, true, "below minimum"},
		{"wildcard only star", "*", 1, 10, true, "must contain alphanumeric"},
		{"wildcard double star", "beer**", 2, 10, true, "consecutive wildcards"},
		{"wildcard uppercase", "Beer*", 2, 10, true, "lowercase alphanumeric"},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			err := validateBlockedTopicPattern(tt.topic, tt.maxLen, tt.minLen)
			if tt.wantErr {
				require.Error(t, err)
				if tt.errPart != "" {
					require.Contains(t, err.Error(), tt.errPart)
				}
			} else {
				require.NoError(t, err)
			}
		})
	}
}

func TestBlockTopicNormalizesAndDedups(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext().WithLogger(log.NewNopLogger())
	am := newTestModule(mk)

	params := mk.GetParams(ctx)
	params.Tiers[0].MaxBlockedTopics = 10
	require.NoError(t, mk.SetParams(ctx, params))

	pub, owner := testPubkeyOwner()

	req := &types.MsgBlockTopic{
		Authority:      "not-gov",
		EnvelopePubkey: pub,
		Topic:          "  ToPic1 ",
	}
	_, err := am.BlockTopic(ctx, req)
	require.NoError(t, err)

	_, err = am.BlockTopic(ctx, &types.MsgBlockTopic{
		Authority:      "not-gov",
		EnvelopePubkey: pub,
		Topic:          "topic1",
	})
	require.NoError(t, err)

	topics, err := mk.GetProfileBlockedTopics(ctx, owner)
	require.NoError(t, err)
	t.Logf("[debug] blocked topics=%v", topics)
	require.Equal(t, []string{"topic1"}, topics)
}

func TestBlockTopicCapsToTierLimit(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()
	am := newTestModule(mk)

	params := mk.GetParams(ctx)
	params.Tiers[0].MaxBlockedTopics = 3
	require.NoError(t, mk.SetParams(ctx, params))

	pub, owner := testPubkeyOwner()
	for _, topic := range []string{"Alpha", "Beta", "Gamma", "Delta"} {
		_, err := am.BlockTopic(ctx, &types.MsgBlockTopic{
			Authority:      "not-gov",
			EnvelopePubkey: pub,
			Topic:          topic,
		})
		require.NoError(t, err)
	}

	topics, err := mk.GetProfileBlockedTopics(ctx, owner)
	require.NoError(t, err)
	t.Logf("[debug] capped blocked topics=%v", topics)
	require.Equal(t, []string{"beta", "gamma", "delta"}, topics)

	_, err = am.BlockTopic(ctx, &types.MsgBlockTopic{
		Authority:      "not-gov",
		EnvelopePubkey: pub,
		Topic:          "Gamma",
	})
	require.NoError(t, err)
	topics, err = mk.GetProfileBlockedTopics(ctx, owner)
	require.NoError(t, err)
	require.Equal(t, []string{"beta", "gamma", "delta"}, topics)
}

func TestBlockTopicInvalidTopic(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()
	am := newTestModule(mk)

	pub, _ := testPubkeyOwner()
	_, err := am.BlockTopic(ctx, &types.MsgBlockTopic{
		Authority:      "not-gov",
		EnvelopePubkey: pub,
		Topic:          "bad-topic",
	})
	require.Error(t, err)
	require.Contains(t, err.Error(), "invalid topic")
}

func TestUnblockTopicRemovesEntry(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()
	am := newTestModule(mk)

	pub, owner := testPubkeyOwner()
	setProfileLevel(t, mk, ctx, owner, 0)
	require.NoError(t, mk.SetProfileBlockedTopics(ctx, owner, []string{"alpha", "beta", "gamma"}))

	_, err := am.UnblockTopic(ctx, &types.MsgUnblockTopic{
		Authority:      "not-gov",
		EnvelopePubkey: pub,
		Topic:          " BeTa ",
	})
	require.NoError(t, err)

	topics, err := mk.GetProfileBlockedTopics(ctx, owner)
	require.NoError(t, err)
	t.Logf("[debug] unblocked topics=%v", topics)
	require.Equal(t, []string{"alpha", "gamma"}, topics)

	_, err = am.UnblockTopic(ctx, &types.MsgUnblockTopic{
		Authority:      "not-gov",
		EnvelopePubkey: pub,
		Topic:          "delta",
	})
	require.NoError(t, err)
	topics, err = mk.GetProfileBlockedTopics(ctx, owner)
	require.NoError(t, err)
	require.Equal(t, []string{"alpha", "gamma"}, topics)
}

func TestBlockTopicRemovesFollowedTopic(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()
	am := newTestModule(mk)

	pub, owner := testPubkeyOwner()
	require.NoError(t, mk.SetProfileFollowedTopics(ctx, owner, []string{"alpha", "beta"}))

	_, err := am.BlockTopic(ctx, &types.MsgBlockTopic{
		Authority:      "not-gov",
		EnvelopePubkey: pub,
		Topic:          " Alpha ",
	})
	require.NoError(t, err)

	followed, err := mk.GetProfileFollowedTopics(ctx, owner)
	require.NoError(t, err)
	require.Equal(t, []string{"beta"}, followed)

	blocked, err := mk.GetProfileBlockedTopics(ctx, owner)
	require.NoError(t, err)
	require.Equal(t, []string{"alpha"}, blocked)
}

func TestTopicMatchesPattern(t *testing.T) {
	tests := []struct {
		topic   string
		pattern string
		want    bool
	}{
		{"beer", "beer", true},
		{"beer", "wine", false},
		{"beer123", "beer*", true},
		{"beer", "beer*", true},
		{"wine", "beer*", false},
		{"mybeer", "*beer", true},
		{"mybeer123", "*beer*", true},
		{"gaming", "gam*g", true},
		{"gambling", "gam*g", true},
		{"game", "gam*g", false},
		{"beer", "*beer*", true},
		{"test", "*", true},
	}
	for _, tt := range tests {
		got := topicMatchesPattern(tt.topic, tt.pattern)
		if got != tt.want {
			t.Errorf("topicMatchesPattern(%q, %q) = %v, want %v", tt.topic, tt.pattern, got, tt.want)
		}
	}
}

func TestBlockTopicWildcardRemovesFollowedTopics(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()
	am := newTestModule(mk)

	pub, owner := testPubkeyOwner()
	require.NoError(t, mk.SetProfileFollowedTopics(ctx, owner, []string{"beer", "beerman123", "wine"}))

	_, err := am.BlockTopic(ctx, &types.MsgBlockTopic{
		Authority:      "not-gov",
		EnvelopePubkey: pub,
		Topic:          "beer*",
	})
	require.NoError(t, err)

	followed, err := mk.GetProfileFollowedTopics(ctx, owner)
	require.NoError(t, err)
	require.Equal(t, []string{"wine"}, followed)

	blocked, err := mk.GetProfileBlockedTopics(ctx, owner)
	require.NoError(t, err)
	require.Equal(t, []string{"beer*"}, blocked)
}

func TestFollowTopicRemovesBlockedTopic(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()
	am := newTestModule(mk)

	pub, owner := testPubkeyOwner()
	require.NoError(t, mk.SetProfileBlockedTopics(ctx, owner, []string{"alpha", "beta"}))

	_, err := am.FollowTopic(ctx, &types.MsgFollowTopic{
		Authority:      "not-gov",
		EnvelopePubkey: pub,
		Target:         owner,
		Topic:          " Alpha ",
	})
	require.NoError(t, err)

	blocked, err := mk.GetProfileBlockedTopics(ctx, owner)
	require.NoError(t, err)
	require.Equal(t, []string{"beta"}, blocked)

	followed, err := mk.GetProfileFollowedTopics(ctx, owner)
	require.NoError(t, err)
	require.Equal(t, []string{"alpha"}, followed)
}

func TestFollowTopicRemovesBlockedWildcard(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()
	am := newTestModule(mk)

	pub, owner := testPubkeyOwner()
	require.NoError(t, mk.SetProfileBlockedTopics(ctx, owner, []string{"beer*", "wine"}))

	_, err := am.FollowTopic(ctx, &types.MsgFollowTopic{
		Authority:      "not-gov",
		EnvelopePubkey: pub,
		Target:         owner,
		Topic:          "beerman123",
	})
	require.NoError(t, err)

	blocked, err := mk.GetProfileBlockedTopics(ctx, owner)
	require.NoError(t, err)
	require.Equal(t, []string{"wine"}, blocked)

	followed, err := mk.GetProfileFollowedTopics(ctx, owner)
	require.NoError(t, err)
	require.Equal(t, []string{"beerman123"}, followed)
}

func TestBlockUserRemovesFollowedUser(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()
	am := newTestModule(mk)

	pub, owner := testPubkeyOwner()
	target := testAccAddressString()
	require.NoError(t, mk.SetProfileFollowedUsers(ctx, owner, []string{target}))

	_, err := am.BlockUser(ctx, &types.MsgBlockUser{
		Authority:      "not-gov",
		EnvelopePubkey: pub,
		Target:         target,
	})
	require.NoError(t, err)

	followed, err := mk.GetProfileFollowedUsers(ctx, owner)
	require.NoError(t, err)
	require.Empty(t, followed)

	blocked, err := mk.GetProfileBlockedUsers(ctx, owner)
	require.NoError(t, err)
	require.Equal(t, []string{target}, blocked)
}

func TestFollowUserRemovesBlockedUser(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()
	am := newTestModule(mk)

	pub, owner := testPubkeyOwner()
	target := testAccAddressString()
	require.NoError(t, mk.SetProfileBlockedUsers(ctx, owner, []string{target}))

	_, err := am.FollowUser(ctx, &types.MsgFollowUser{
		Authority:      "not-gov",
		EnvelopePubkey: pub,
		Target:         owner,
		User:           target,
	})
	require.NoError(t, err)

	blocked, err := mk.GetProfileBlockedUsers(ctx, owner)
	require.NoError(t, err)
	require.Empty(t, blocked)

	followed, err := mk.GetProfileFollowedUsers(ctx, owner)
	require.NoError(t, err)
	require.Equal(t, []string{target}, followed)
}

func TestBlockUserAlreadyBlockedStillRemovesFollow(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()
	am := newTestModule(mk)

	pub, owner := testPubkeyOwner()
	target := testAccAddressString()
	require.NoError(t, mk.SetProfileFollowedUsers(ctx, owner, []string{target}))
	require.NoError(t, mk.SetProfileBlockedUsers(ctx, owner, []string{target}))

	_, err := am.BlockUser(ctx, &types.MsgBlockUser{
		Authority:      "not-gov",
		EnvelopePubkey: pub,
		Target:         target,
	})
	require.NoError(t, err)

	followed, err := mk.GetProfileFollowedUsers(ctx, owner)
	require.NoError(t, err)
	require.Empty(t, followed)

	blocked, err := mk.GetProfileBlockedUsers(ctx, owner)
	require.NoError(t, err)
	require.Equal(t, []string{target}, blocked)
}

func TestFollowTopicAlreadyFollowedStillRemovesBlock(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()
	am := newTestModule(mk)

	pub, owner := testPubkeyOwner()
	require.NoError(t, mk.SetProfileFollowedTopics(ctx, owner, []string{"alpha"}))
	require.NoError(t, mk.SetProfileBlockedTopics(ctx, owner, []string{"alpha"}))

	_, err := am.FollowTopic(ctx, &types.MsgFollowTopic{
		Authority:      "not-gov",
		EnvelopePubkey: pub,
		Target:         owner,
		Topic:          "Alpha",
	})
	require.NoError(t, err)

	blocked, err := mk.GetProfileBlockedTopics(ctx, owner)
	require.NoError(t, err)
	require.Empty(t, blocked)

	followed, err := mk.GetProfileFollowedTopics(ctx, owner)
	require.NoError(t, err)
	require.Equal(t, []string{"alpha"}, followed)
}
