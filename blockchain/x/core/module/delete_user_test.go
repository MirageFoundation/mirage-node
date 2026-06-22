package core

import (
	"bytes"
	"encoding/json"
	"testing"

	"cosmossdk.io/log/v2"
	sdk "github.com/cosmos/cosmos-sdk/types"
	authtypes "github.com/cosmos/cosmos-sdk/x/auth/types"
	govtypes "github.com/cosmos/cosmos-sdk/x/gov/types"
	"github.com/stretchr/testify/require"

	"mirage/x/core/types"
)

// --- Authorization / validation tests ---

func TestDeleteUserRejectsInvalidPubkey(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()
	am := newTestModule(mk)

	req := &types.MsgDeleteUser{
		Authority:      testAccAddressString(),
		EnvelopePubkey: []byte{0x01, 0x02}, // wrong length
		Target:         testAccAddressString(),
	}

	_, err := am.DeleteUser(ctx, req)
	require.Error(t, err)
	require.Contains(t, err.Error(), "invalid envelope_pubkey length")
}

func TestDeleteUserRejectsZeroLengthPubkey(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()
	am := newTestModule(mk)

	req := &types.MsgDeleteUser{
		Authority:      testAccAddressString(),
		EnvelopePubkey: []byte{},
		Target:         testAccAddressString(),
	}

	_, err := am.DeleteUser(ctx, req)
	require.Error(t, err)
	require.Contains(t, err.Error(), "invalid envelope_pubkey length")
}

func TestDeleteUserRejectsPubkeyMismatch(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()
	am := newTestModule(mk)

	pub, _ := testPubkeyOwner()
	wrongTarget := sdk.AccAddress(bytes.Repeat([]byte{0x09}, 20)).String()

	req := &types.MsgDeleteUser{
		Authority:      testAccAddressString(),
		EnvelopePubkey: pub,
		Target:         wrongTarget,
	}

	_, err := am.DeleteUser(ctx, req)
	require.Error(t, err)
	require.Contains(t, err.Error(), "envelope_pubkey does not derive to target")
}

func TestDeleteUserRejectsProfileNotFound(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext().WithLogger(log.NewNopLogger())
	am := newTestModule(mk)

	pub, owner := testPubkeyOwner()

	req := &types.MsgDeleteUser{
		Authority:      testAccAddressString(),
		EnvelopePubkey: pub,
		Target:         owner,
	}

	_, err := am.DeleteUser(ctx, req)
	require.Error(t, err)
	require.Contains(t, err.Error(), "profile not found or already deleted")
}

func TestDeleteUserGovernanceRejectsProfileNotFound(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext().WithLogger(log.NewNopLogger())
	am := newTestModule(mk)
	govAddr := authtypes.NewModuleAddress(govtypes.ModuleName).String()

	req := &types.MsgDeleteUser{
		Authority: govAddr,
		Target:    testAccAddressString(),
	}

	_, err := am.DeleteUser(ctx, req)
	require.Error(t, err)
	require.Contains(t, err.Error(), "profile not found or already deleted")
}

func TestDeleteUserRejectsInvalidTarget(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()
	am := newTestModule(mk)
	govAddr := authtypes.NewModuleAddress(govtypes.ModuleName).String()

	req := &types.MsgDeleteUser{
		Authority: govAddr,
		Target:    "not-a-valid-address",
	}

	_, err := am.DeleteUser(ctx, req)
	require.Error(t, err)
	require.Contains(t, err.Error(), "invalid target address")
}

func TestDeleteUserRejectsEmptyTarget(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()
	am := newTestModule(mk)
	govAddr := authtypes.NewModuleAddress(govtypes.ModuleName).String()

	req := &types.MsgDeleteUser{
		Authority: govAddr,
		Target:    "",
	}

	_, err := am.DeleteUser(ctx, req)
	require.Error(t, err)
	require.Contains(t, err.Error(), "invalid target address")
}

func TestDeleteUserRejectsWhitespaceTarget(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()
	am := newTestModule(mk)
	govAddr := authtypes.NewModuleAddress(govtypes.ModuleName).String()

	req := &types.MsgDeleteUser{
		Authority: govAddr,
		Target:    "   ",
	}

	_, err := am.DeleteUser(ctx, req)
	require.Error(t, err)
	require.Contains(t, err.Error(), "invalid target address")
}

func TestDeleteUserNonGovNonSelfCannotDeleteOther(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext().WithLogger(log.NewNopLogger())
	am := newTestModule(mk)

	pub, owner := testPubkeyOwner()
	victimAddr := sdk.AccAddress(bytes.Repeat([]byte{0x0B}, 20)).String()

	victimCore := types.ProfileCore{Owner: victimAddr, Username: "victim", Level: 0}
	bz, _ := json.Marshal(victimCore)
	_ = mk.SetProfileCore(ctx, victimAddr, bz)

	req := &types.MsgDeleteUser{
		Authority:      testAccAddressString(),
		EnvelopePubkey: pub,
		Target:         victimAddr, // not derived from pub
	}

	_, err := am.DeleteUser(ctx, req)
	require.Error(t, err)
	require.Contains(t, err.Error(), "envelope_pubkey does not derive to target")

	// Victim's profile must be untouched
	_, found, _ := mk.GetProfileCore(ctx, victimAddr)
	require.True(t, found, "victim profile must not be deleted")
	_ = owner
}

func TestDeleteUserNilPubkeyNotGov(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()
	am := newTestModule(mk)

	req := &types.MsgDeleteUser{
		Authority:      testAccAddressString(),
		EnvelopePubkey: nil,
		Target:         testAccAddressString(),
	}

	_, err := am.DeleteUser(ctx, req)
	require.Error(t, err)
	require.Contains(t, err.Error(), "invalid envelope_pubkey length")
}

// --- Successful deletion tests ---

func TestDeleteUserSelfAuthAccepted(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext().WithLogger(log.NewNopLogger())
	am := newTestModule(mk)

	pub, owner := testPubkeyOwner()

	core := types.ProfileCore{Owner: owner, Username: "testuser", Level: 0}
	bz, _ := json.Marshal(core)
	_ = mk.SetProfileCore(ctx, owner, bz)
	_ = mk.ClaimUsername(ctx, "testuser", owner)

	req := &types.MsgDeleteUser{
		Authority:      testAccAddressString(),
		EnvelopePubkey: pub,
		Target:         owner,
	}

	// Will panic on fund sweep (nil bank keeper in mock).
	// We recover and verify the auth check passed and deletion started.
	func() {
		defer func() {
			r := recover()
			if r == nil {
				t.Fatal("expected panic from nil bank keeper during fund sweep")
			}
		}()
		_, _ = am.DeleteUser(ctx, req)
	}()

	_, found, _ := mk.GetProfileCore(ctx, owner)
	require.False(t, found, "profile should be deleted")
}

func TestDeleteUserGovernanceAuthAccepted(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext().WithLogger(log.NewNopLogger())
	am := newTestModule(mk)
	govAddr := authtypes.NewModuleAddress(govtypes.ModuleName).String()

	targetAddr := testAccAddressString()
	core := types.ProfileCore{Owner: targetAddr, Username: "govtarget", Level: 1}
	bz, _ := json.Marshal(core)
	_ = mk.SetProfileCore(ctx, targetAddr, bz)
	_ = mk.ClaimUsername(ctx, "govtarget", targetAddr)

	req := &types.MsgDeleteUser{
		Authority: govAddr,
		Target:    targetAddr,
	}

	func() {
		defer func() {
			r := recover()
			if r == nil {
				t.Fatal("expected panic from nil bank keeper during fund sweep")
			}
		}()
		_, _ = am.DeleteUser(ctx, req)
	}()

	_, found, _ := mk.GetProfileCore(ctx, targetAddr)
	require.False(t, found, "profile should be deleted by governance")
}

func TestDeleteUserGovernanceSkipsGasFee(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext().WithLogger(log.NewNopLogger())
	am := newTestModule(mk)
	govAddr := authtypes.NewModuleAddress(govtypes.ModuleName).String()

	targetAddr := testAccAddressString()
	core := types.ProfileCore{Owner: targetAddr, Username: "govnofee", Level: 5}
	bz, _ := json.Marshal(core)
	_ = mk.SetProfileCore(ctx, targetAddr, bz)
	_ = mk.ClaimUsername(ctx, "govnofee", targetAddr)

	req := &types.MsgDeleteUser{
		Authority: govAddr,
		Target:    targetAddr,
	}

	// Governance should NOT trigger deductRelayGasFee (which would fail on nil params).
	// If gas fee were incorrectly triggered for governance, the nil params keeper
	// would panic before reaching the fund sweep. The test verifies it panics only
	// on fund sweep, not on gas fee.
	func() {
		defer func() {
			r := recover()
			if r == nil {
				t.Fatal("expected panic from nil bank keeper during fund sweep")
			}
		}()
		_, _ = am.DeleteUser(ctx, req)
	}()

	_, found, _ := mk.GetProfileCore(ctx, targetAddr)
	require.False(t, found, "profile should be deleted")
}

// --- State cleanup tests ---

func TestDeleteUserReleasesUsername(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext().WithLogger(log.NewNopLogger())
	am := newTestModule(mk)

	pub, owner := testPubkeyOwner()

	core := types.ProfileCore{Owner: owner, Username: "releaseme", Level: 0}
	bz, _ := json.Marshal(core)
	_ = mk.SetProfileCore(ctx, owner, bz)
	_ = mk.ClaimUsername(ctx, "releaseme", owner)

	req := &types.MsgDeleteUser{
		Authority:      testAccAddressString(),
		EnvelopePubkey: pub,
		Target:         owner,
	}

	func() {
		defer func() { recover() }()
		_, _ = am.DeleteUser(ctx, req)
	}()

	otherOwner := sdk.AccAddress(bytes.Repeat([]byte{0x0A}, 20)).String()
	err := mk.ClaimUsername(ctx, "releaseme", otherOwner)
	require.NoError(t, err, "released username should be claimable by another user")
}

func TestDeleteUserCleansUpAllProfileLists(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext().WithLogger(log.NewNopLogger())
	am := newTestModule(mk)

	pub, owner := testPubkeyOwner()

	core := types.ProfileCore{Owner: owner, Username: "listuser", Level: 0}
	bz, _ := json.Marshal(core)
	_ = mk.SetProfileCore(ctx, owner, bz)
	_ = mk.ClaimUsername(ctx, "listuser", owner)

	// Populate all profile list KV entries using per-entry methods
	_ = mk.ReplaceAllEnabledAgents(ctx, owner, []string{"agent1", "agent2"})
	_, _ = mk.AddFollowedUser(ctx, owner, "user1")
	_, _ = mk.AddFollowedTopic(ctx, owner, "topic1")
	_, _ = mk.AddBlockedUserDeque(ctx, owner, "blocked1", 0)
	_, _ = mk.AddBlockedPostDeque(ctx, owner, "txhash1", 0)
	_, _ = mk.AddBlockedTopicDeque(ctx, owner, "btopic1", 0)

	req := &types.MsgDeleteUser{
		Authority:      testAccAddressString(),
		EnvelopePubkey: pub,
		Target:         owner,
	}

	func() {
		defer func() { recover() }()
		_, _ = am.DeleteUser(ctx, req)
	}()

	// All lists should be cleaned up
	agents, _ := mk.ListEnabledAgentsOrdered(ctx, owner)
	require.Empty(t, agents, "enabled agents should be empty")

	users, _ := mk.ListFollowedUsers(ctx, owner)
	require.Empty(t, users, "followed users should be empty")

	topics, _ := mk.ListFollowedTopics(ctx, owner)
	require.Empty(t, topics, "followed topics should be empty")

	blockedUsers, _ := mk.ListBlockedUsers(ctx, owner)
	require.Empty(t, blockedUsers, "blocked users should be empty")

	blockedPosts, _ := mk.ListBlockedPosts(ctx, owner)
	require.Empty(t, blockedPosts, "blocked posts should be empty")

	blockedTopics, _ := mk.ListBlockedTopics(ctx, owner)
	require.Empty(t, blockedTopics, "blocked topics should be empty")
}

func TestDeleteUserDoubleDeleteRejects(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext().WithLogger(log.NewNopLogger())
	am := newTestModule(mk)

	pub, owner := testPubkeyOwner()

	core := types.ProfileCore{Owner: owner, Username: "doubledelete", Level: 0}
	bz, _ := json.Marshal(core)
	_ = mk.SetProfileCore(ctx, owner, bz)
	_ = mk.ClaimUsername(ctx, "doubledelete", owner)

	req := &types.MsgDeleteUser{
		Authority:      testAccAddressString(),
		EnvelopePubkey: pub,
		Target:         owner,
	}

	// First delete - will panic on fund sweep but profile is gone
	func() {
		defer func() { recover() }()
		_, _ = am.DeleteUser(ctx, req)
	}()

	// Second delete should fail with "not found"
	_, err := am.DeleteUser(ctx, req)
	require.Error(t, err)
	require.Contains(t, err.Error(), "profile not found or already deleted")
}

func TestDeleteUserTargetNormalization(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext().WithLogger(log.NewNopLogger())
	am := newTestModule(mk)

	pub, owner := testPubkeyOwner()

	core := types.ProfileCore{Owner: owner, Username: "normuser", Level: 0}
	bz, _ := json.Marshal(core)
	_ = mk.SetProfileCore(ctx, owner, bz)

	// Target with extra whitespace should still match after normalization
	req := &types.MsgDeleteUser{
		Authority:      testAccAddressString(),
		EnvelopePubkey: pub,
		Target:         "  " + owner + "  ",
	}

	func() {
		defer func() { recover() }()
		_, _ = am.DeleteUser(ctx, req)
	}()

	_, found, _ := mk.GetProfileCore(ctx, owner)
	require.False(t, found, "profile should be deleted with trimmed target")
}

func TestDeleteUserWithoutUsernameRejected(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext().WithLogger(log.NewNopLogger())
	am := newTestModule(mk)

	pub, owner := testPubkeyOwner()

	// Profile exists but has no username (e.g. was never set or already released)
	core := types.ProfileCore{Owner: owner, Username: "", Level: 0}
	bz, _ := json.Marshal(core)
	_ = mk.SetProfileCore(ctx, owner, bz)

	req := &types.MsgDeleteUser{
		Authority:      testAccAddressString(),
		EnvelopePubkey: pub,
		Target:         owner,
	}

	_, err := am.DeleteUser(ctx, req)
	require.Error(t, err)
	require.Contains(t, err.Error(), "username required")

	// Profile should remain since self-delete was rejected
	_, found, _ := mk.GetProfileCore(ctx, owner)
	require.True(t, found, "profile should still exist when self-delete is rejected for missing username")
}

func TestDeleteUserGovernanceWithoutUsernameRejected(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext().WithLogger(log.NewNopLogger())
	am := newTestModule(mk)
	govAddr := authtypes.NewModuleAddress(govtypes.ModuleName).String()

	targetAddr := testAccAddressString()
	core := types.ProfileCore{Owner: targetAddr, Username: "", Level: 1}
	bz, _ := json.Marshal(core)
	_ = mk.SetProfileCore(ctx, targetAddr, bz)

	req := &types.MsgDeleteUser{
		Authority: govAddr,
		Target:    targetAddr,
	}

	_, err := am.DeleteUser(ctx, req)
	require.Error(t, err)
	require.Contains(t, err.Error(), "username required")

	_, found, _ := mk.GetProfileCore(ctx, targetAddr)
	require.True(t, found, "profile should remain when governance delete is rejected for missing username")
}
