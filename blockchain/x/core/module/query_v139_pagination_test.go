package core

import (
	"encoding/binary"
	"fmt"
	"testing"

	sdkquery "github.com/cosmos/cosmos-sdk/types/query"
	"github.com/cosmos/gogoproto/proto"
	"github.com/stretchr/testify/require"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"

	"mirage/x/core/types"
)

func marshalQueryRecord(t *testing.T, mk *mockKeeper, value proto.Message) []byte {
	t.Helper()
	bz, err := mk.CDC().Marshal(value)
	require.NoError(t, err)
	return bz
}

func queryPage(limit uint64, key []byte) *sdkquery.PageRequest {
	return &sdkquery.PageRequest{Limit: limit, Key: key}
}

func TestV139AdvertisedQueriesPaginatePastOneHundred(t *testing.T) {
	mk, ctx, am := setupModule(t)
	address := genAddr(121)
	creatorBytes, err := types.CanonicalAccBytes(address)
	require.NoError(t, err)
	target := genTxHash(700)
	targetBytes, err := types.HashBytes(target)
	require.NoError(t, err)

	for i := 1; i <= 101; i++ {
		slug := fmt.Sprintf("page-%03d", i)
		teamID := uint64(i)
		require.NoError(t, mk.SetRawKVPair(ctx, types.KeyCurationInviteRev(address, slug, teamID), []byte{1}))
		require.NoError(t, mk.SetRawKVPair(ctx, types.KeyCurationInvite(slug, teamID, address), []byte(genAddr(122))))
		require.NoError(t, mk.SetRawKVPair(ctx, types.KeyCurationTeamUser(address, slug), u64Test(teamID)))

		epoch := int64(i)
		accrual := &types.CreatorAccrual{Epoch: epoch, Creator: address, Amount: fmt.Sprintf("%d", i)}
		require.NoError(t, mk.SetRawKVPair(ctx, types.KeyEpochCreatorAccrual(epoch, creatorBytes), marshalQueryRecord(t, mk, accrual)))
		require.NoError(t, mk.SetRawKVPair(ctx, types.KeyCreatorEpochIdx(creatorBytes, epoch), []byte{1}))

		earning := &types.TargetEarning{EpochId: epoch, Target: target, Creator: address, Amount: fmt.Sprintf("%d", i)}
		require.NoError(t, mk.SetRawKVPair(ctx, types.KeyEpochTarget(epoch, targetBytes), marshalQueryRecord(t, mk, earning)))
		require.NoError(t, mk.SetRawKVPair(ctx, append(append([]byte(types.PfxTargetEpoch), targetBytes...), u64Test(uint64(epoch))...), []byte{1}))

		tranche := &types.SubscriptionTranche{Id: teamID, Recipient: address}
		require.NoError(t, mk.SetRawKVPair(ctx, types.KeyTranche(teamID), marshalQueryRecord(t, mk, tranche)))
		require.NoError(t, mk.SetRawKVPair(ctx, types.KeyTrancheRecipient(address, teamID), []byte{1}))
	}

	inv1, err := am.PendingCuratorInvitations(ctx, &types.QueryPendingCuratorInvitationsRequest{
		Address: address, Pagination: queryPage(60, nil),
	})
	require.NoError(t, err)
	inv2, err := am.PendingCuratorInvitations(ctx, &types.QueryPendingCuratorInvitationsRequest{
		Address: address, Pagination: queryPage(60, inv1.Pagination.NextKey),
	})
	require.NoError(t, err)
	allInvitations := append(inv1.Invitations, inv2.Invitations...)
	require.Len(t, allInvitations, 101)
	for i, invitation := range allInvitations {
		require.Equal(t, fmt.Sprintf("page-%03d", i+1), invitation.Community)
		require.Equal(t, uint64(i+1), invitation.TeamId)
	}
	require.Nil(t, inv2.Pagination)

	mem1, err := am.CurationMemberships(ctx, &types.QueryCurationMembershipsRequest{
		Address: address, Pagination: queryPage(60, nil),
	})
	require.NoError(t, err)
	mem2, err := am.CurationMemberships(ctx, &types.QueryCurationMembershipsRequest{
		Address: address, Pagination: queryPage(60, mem1.Pagination.NextKey),
	})
	require.NoError(t, err)
	allMemberships := append(mem1.Memberships, mem2.Memberships...)
	require.Len(t, allMemberships, 101)
	for i, membership := range allMemberships {
		require.Equal(t, fmt.Sprintf("page-%03d", i+1), membership.Community)
		require.Equal(t, uint64(i+1), membership.TeamId)
	}

	acc1, err := am.CreatorAccruals(ctx, &types.QueryCreatorAccrualsRequest{
		Creator: address, Pagination: queryPage(60, nil),
	})
	require.NoError(t, err)
	acc2, err := am.CreatorAccruals(ctx, &types.QueryCreatorAccrualsRequest{
		Creator: address, Pagination: queryPage(60, acc1.Pagination.NextKey),
	})
	require.NoError(t, err)
	allAccruals := append(acc1.Accruals, acc2.Accruals...)
	require.Len(t, allAccruals, 101)
	for i, accrual := range allAccruals {
		require.Equal(t, int64(i+1), accrual.Epoch)
	}

	earn1, err := am.TargetEarnings(ctx, &types.QueryTargetEarningsRequest{
		Target: target, Pagination: queryPage(60, nil),
	})
	require.NoError(t, err)
	earn2, err := am.TargetEarnings(ctx, &types.QueryTargetEarningsRequest{
		Target: target, Pagination: queryPage(60, earn1.Pagination.NextKey),
	})
	require.NoError(t, err)
	allEarnings := append(earn1.Earnings, earn2.Earnings...)
	require.Len(t, allEarnings, 101)
	for i, earning := range allEarnings {
		require.Equal(t, int64(i+1), earning.EpochId)
	}

	tr1, err := am.SubscriptionTranches(ctx, &types.QuerySubscriptionTranchesRequest{
		Address: address, Pagination: queryPage(60, nil),
	})
	require.NoError(t, err)
	tr2, err := am.SubscriptionTranches(ctx, &types.QuerySubscriptionTranchesRequest{
		Address: address, Pagination: queryPage(60, tr1.Pagination.NextKey),
	})
	require.NoError(t, err)
	allTranches := append(tr1.Tranches, tr2.Tranches...)
	require.Len(t, allTranches, 101)
	for i, tranche := range allTranches {
		require.Equal(t, uint64(i+1), tranche.Id)
	}
}

func TestTerminalCreatorEpochsUseDeadlineIndexAndPagination(t *testing.T) {
	mk, ctx, am := setupModule(t)
	const cutoff = int64(10_000)
	for i := 0; i < 105; i++ {
		epochID := int64(500 + i)
		deadline := cutoff - 2 + int64(i)
		epoch := &types.CreatorEpoch{
			EpochId: epochID, Status: types.CreatorEpochStatus_CREATOR_EPOCH_STATUS_CLAIMABLE,
			ClaimDeadlineUnix: deadline,
		}
		require.NoError(t, mk.SetRawKVPair(ctx, types.KeyCreatorEpoch(epochID), marshalQueryRecord(t, mk, epoch)))
		require.NoError(t, mk.SetRawKVPair(ctx, types.KeyCreatorEpochDeadline(deadline, epochID), []byte{1}))
	}

	first, err := am.TerminalCreatorEpochs(ctx, &types.QueryTerminalCreatorEpochsRequest{
		CutoffDeadlineUnix: cutoff, Pagination: queryPage(60, nil),
	})
	require.NoError(t, err)
	second, err := am.TerminalCreatorEpochs(ctx, &types.QueryTerminalCreatorEpochsRequest{
		CutoffDeadlineUnix: cutoff, Pagination: queryPage(60, first.Pagination.NextKey),
	})
	require.NoError(t, err)
	all := append(first.Epochs, second.Epochs...)
	require.Len(t, all, 103)
	require.Equal(t, int64(502), all[0].EpochId)
	require.Equal(t, int64(604), all[len(all)-1].EpochId)
}

func TestV139PublicQueriesRejectMalformedInputWithoutPanicking(t *testing.T) {
	_, ctx, am := setupModule(t)
	bad := "not-an-address"
	tests := []struct {
		name string
		call func() error
	}{
		{"creator accruals", func() error {
			_, err := am.CreatorAccruals(ctx, &types.QueryCreatorAccrualsRequest{Creator: bad})
			return err
		}},
		{"subscription tranches", func() error {
			_, err := am.SubscriptionTranches(ctx, &types.QuerySubscriptionTranchesRequest{Address: bad})
			return err
		}},
		{"subscription renewal", func() error {
			_, err := am.SubscriptionRenewal(ctx, &types.QuerySubscriptionRenewalRequest{Address: bad})
			return err
		}},
		{"subscriber quota", func() error {
			_, err := am.SubscriberQuota(ctx, &types.QuerySubscriberQuotaRequest{Address: bad})
			return err
		}},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			err := tc.call()
			require.Error(t, err)
			require.Equal(t, codes.InvalidArgument, status.Code(err))
		})
	}

	_, err := am.CreatorAccruals(ctx, &types.QueryCreatorAccrualsRequest{
		Creator: genAddr(123), Pagination: &sdkquery.PageRequest{Offset: 1},
	})
	require.Equal(t, codes.InvalidArgument, status.Code(err))
	_, err = am.TerminalCreatorEpochs(ctx, &types.QueryTerminalCreatorEpochsRequest{CutoffDeadlineUnix: -1})
	require.Equal(t, codes.InvalidArgument, status.Code(err))
}

func u64Test(v uint64) []byte {
	out := make([]byte, 8)
	binary.BigEndian.PutUint64(out, v)
	return out
}
