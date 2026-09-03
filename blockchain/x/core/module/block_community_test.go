package core

import (
	"bytes"
	"encoding/json"
	"testing"

	"cosmossdk.io/log/v2"
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
	var existing types.ProfileCore
	if bz, found, _ := mk.GetProfileCore(ctx, owner); found {
		_ = json.Unmarshal(bz, &existing)
	}
	existing.Owner = owner
	existing.Level = level
	if existing.Username == "" {
		existing.Username = "Anon-testuser"
	}
	bz, err := json.Marshal(existing)
	require.NoError(t, err)
	require.NoError(t, mk.SetProfileCore(ctx, owner, bz))
}

func ensureUsername(t *testing.T, mk *mockKeeper, ctx sdk.Context, owner, username string) {
	var existing types.ProfileCore
	if bz, found, _ := mk.GetProfileCore(ctx, owner); found {
		_ = json.Unmarshal(bz, &existing)
	}
	existing.Owner = owner
	existing.Username = username
	bz, err := json.Marshal(existing)
	require.NoError(t, err)
	require.NoError(t, mk.SetProfileCore(ctx, owner, bz))
}

func TestValidateCommunity(t *testing.T) {
	tests := []struct {
		name      string
		community string
		minLen    uint64
		maxLen    uint64
		wantErr   bool
		errPart   string
	}{
		{"valid", "abc123", 2, 10, false, ""},
		{"too short", "a", 2, 10, true, "below minimum"},
		{"too long", "abcdefghijk", 2, 10, true, "exceeds limit"},
		{"uppercase", "Abc", 2, 10, true, "lowercase alphanumeric"},
		{"internal hyphen", "ab-c", 2, 10, false, ""},
		{"consecutive hyphens", "ab--c", 2, 10, true, "consecutive hyphens"},
		{"empty", " ", 2, 10, true, "community required"},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			err := validateCommunity(tt.community, tt.maxLen, tt.minLen)
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

func TestValidateBlockedCommunityPattern(t *testing.T) {
	tests := []struct {
		name      string
		community string
		minLen    uint64
		maxLen    uint64
		wantErr   bool
		errPart   string
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
		{"hyphenated slug", "foo-bar", 2, 10, false, ""},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			err := validateBlockedCommunityPattern(tt.community, tt.maxLen, tt.minLen)
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

func TestBlockCommunityNormalizesAndDedups(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext().WithLogger(log.NewNopLogger())
	am := newTestModule(mk)

	pub, owner := testPubkeyOwner()
	ensureUsername(t, mk, ctx, owner, "Anon-testuser")

	_, err := am.BlockCommunity(ctx, &types.MsgBlockCommunity{
		EnvelopePubkey: pub,
		Community:      "  beer1 ",
	})
	require.NoError(t, err)

	_, err = am.BlockCommunity(ctx, &types.MsgBlockCommunity{
		EnvelopePubkey: pub,
		Community:      "beer1",
	})
	require.NoError(t, err)

	blocked, err := mk.ListBlockedCommunities(ctx, owner)
	require.NoError(t, err)
	t.Logf("[debug] blocked communities=%v", blocked)
	require.Equal(t, []string{"beer1"}, blocked)
}

func TestBlockCommunityInvalidSlug(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()
	am := newTestModule(mk)

	pub, owner := testPubkeyOwner()
	ensureUsername(t, mk, ctx, owner, "Anon-testuser")
	_, err := am.BlockCommunity(ctx, &types.MsgBlockCommunity{
		EnvelopePubkey: pub,
		Community:      "bad_slug",
	})
	require.Error(t, err)
	require.Contains(t, err.Error(), "lowercase alphanumeric")
}

func TestUnblockCommunityRemovesEntry(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()
	am := newTestModule(mk)

	pub, owner := testPubkeyOwner()
	ensureUsername(t, mk, ctx, owner, "Anon-testuser")
	for _, slug := range []string{"alpha", "beta", "gamma"} {
		require.NoError(t, mk.AddBlockedCommunity(ctx, owner, slug, 3))
	}

	_, err := am.UnblockCommunity(ctx, &types.MsgUnblockCommunity{
		EnvelopePubkey: pub,
		Community:      " beta ",
	})
	require.NoError(t, err)

	blocked, err := mk.ListBlockedCommunities(ctx, owner)
	require.NoError(t, err)
	t.Logf("[debug] unblocked communities=%v", blocked)
	require.Equal(t, []string{"alpha", "gamma"}, blocked)

	_, err = am.UnblockCommunity(ctx, &types.MsgUnblockCommunity{
		EnvelopePubkey: pub,
		Community:      "delta",
	})
	require.NoError(t, err)
	blocked, err = mk.ListBlockedCommunities(ctx, owner)
	require.NoError(t, err)
	require.Equal(t, []string{"alpha", "gamma"}, blocked)
}

func TestBlockUserRemovesFollowedUser(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()
	am := newTestModule(mk)

	pub, owner := testPubkeyOwner()
	ensureUsername(t, mk, ctx, owner, "Anon-testuser")
	target := testAccAddressString()
	_, _ = mk.AddFollowedUser(ctx, owner, target)

	_, err := am.BlockUser(ctx, &types.MsgBlockUser{
		Authority:      "not-gov",
		EnvelopePubkey: pub,
		Target:         target,
	})
	require.NoError(t, err)

	followed, err := mk.ListFollowedUsers(ctx, owner)
	require.NoError(t, err)
	require.Empty(t, followed)

	blocked, err := mk.ListBlockedUsers(ctx, owner)
	require.NoError(t, err)
	require.Equal(t, []string{target}, blocked)
}

func TestFollowUserRemovesBlockedUser(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()
	am := newTestModule(mk)

	pub, owner := testPubkeyOwner()
	ensureUsername(t, mk, ctx, owner, "Anon-testuser")
	target := testAccAddressString()
	_, _ = mk.AddBlockedUserDeque(ctx, owner, target, 0)

	_, err := am.FollowUser(ctx, &types.MsgFollowUser{
		Authority:      "not-gov",
		EnvelopePubkey: pub,
		Target:         owner,
		User:           target,
	})
	require.NoError(t, err)

	blocked, err := mk.ListBlockedUsers(ctx, owner)
	require.NoError(t, err)
	require.Empty(t, blocked)

	followed, err := mk.ListFollowedUsers(ctx, owner)
	require.NoError(t, err)
	require.Equal(t, []string{target}, followed)
}

func TestBlockUserAlreadyBlockedStillRemovesFollow(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()
	am := newTestModule(mk)

	pub, owner := testPubkeyOwner()
	ensureUsername(t, mk, ctx, owner, "Anon-testuser")
	target := testAccAddressString()
	_, _ = mk.AddFollowedUser(ctx, owner, target)
	_, _ = mk.AddBlockedUserDeque(ctx, owner, target, 0)

	_, err := am.BlockUser(ctx, &types.MsgBlockUser{
		Authority:      "not-gov",
		EnvelopePubkey: pub,
		Target:         target,
	})
	require.NoError(t, err)

	followed, err := mk.ListFollowedUsers(ctx, owner)
	require.NoError(t, err)
	require.Empty(t, followed)

	blocked, err := mk.ListBlockedUsers(ctx, owner)
	require.NoError(t, err)
	require.Equal(t, []string{target}, blocked)
}

// TestRetiredMessageHandlersReject pins the messages that remain retired at the
// msg-server level.
func TestRetiredMessageHandlersReject(t *testing.T) {
	_, ctx, am := setupModule(t)

	_, err := am.EnableAgent(ctx, &types.MsgEnableAgent{})
	require.ErrorContains(t, err, "retired message MsgEnableAgent")

	_, err = am.DisableAgent(ctx, &types.MsgDisableAgent{})
	require.ErrorContains(t, err, "retired message MsgDisableAgent")

	_, err = am.SetAgents(ctx, &types.MsgSetAgents{})
	require.ErrorContains(t, err, "retired message MsgSetAgents")
}
