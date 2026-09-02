package keeper

import (
	"encoding/binary"
	"fmt"

	storetypes "github.com/cosmos/cosmos-sdk/store/v2/types"
	sdk "github.com/cosmos/cosmos-sdk/types"

	"mirage/x/core/types"
)

const MaxV139ListQueryLimit = 100

type prefixPageRecord struct {
	Key   []byte
	Value []byte
}

func (k Keeper) getPrefixPage(
	ctx sdk.Context,
	prefix, pageKey []byte,
	limit, maxLimit uint64,
) (records []prefixPageRecord, nextKey []byte, err error) {
	if limit == 0 || limit > maxLimit {
		limit = maxLimit
	}
	start := prefix
	if len(pageKey) > 0 {
		start = append(append([]byte(nil), prefix...), pageKey...)
	}
	it, err := k.storeService.OpenKVStore(ctx).Iterator(start, storetypes.PrefixEndBytes(prefix))
	if err != nil {
		return nil, nil, err
	}
	defer func() {
		if closeErr := it.Close(); err == nil && closeErr != nil {
			err = closeErr
		}
	}()
	for ; it.Valid() && uint64(len(records)) < limit; it.Next() {
		records = append(records, prefixPageRecord{
			Key:   append([]byte(nil), it.Key()...),
			Value: append([]byte(nil), it.Value()...),
		})
	}
	if err := it.Error(); err != nil {
		return nil, nil, err
	}
	if it.Valid() {
		nextKey = append([]byte(nil), it.Key()[len(prefix):]...)
	}
	return records, nextKey, nil
}

func (k Keeper) GetPendingCuratorInvitationsPaginated(
	ctx sdk.Context,
	owner string,
	pageKey []byte,
	limit uint64,
) ([]*types.PendingCuratorInvitation, []byte, error) {
	prefix := types.KeyCurationInviteRevPrefix(owner)
	records, nextKey, err := k.getPrefixPage(ctx, prefix, pageKey, limit, MaxV139ListQueryLimit)
	if err != nil {
		return nil, nil, err
	}
	out := make([]*types.PendingCuratorInvitation, 0, len(records))
	for _, record := range records {
		rest := record.Key[len(prefix):]
		if len(rest) < 10 {
			return nil, nil, fmt.Errorf("malformed reverse invitation key")
		}
		n := int(binary.BigEndian.Uint16(rest[:2]))
		if len(rest) != 2+n+8 {
			return nil, nil, fmt.Errorf("malformed reverse invitation key")
		}
		slug := string(rest[2 : 2+n])
		teamID := binary.BigEndian.Uint64(rest[2+n:])
		inviter, err := k.storeGet(ctx, types.KeyCurationInvite(slug, teamID, owner))
		if err != nil {
			return nil, nil, err
		}
		if len(inviter) == 0 {
			return nil, nil, fmt.Errorf("invitation reverse index points to missing invitation")
		}
		out = append(out, &types.PendingCuratorInvitation{
			Community: slug,
			TeamId:    teamID,
			Invitee:   owner,
			Inviter:   string(inviter),
		})
	}
	return out, nextKey, nil
}

func (k Keeper) GetCurationMembershipsPaginated(
	ctx sdk.Context,
	owner string,
	pageKey []byte,
	limit uint64,
) ([]*types.CurationMembership, []byte, error) {
	prefix := types.KeyCurationTeamUserPrefix(owner)
	records, nextKey, err := k.getPrefixPage(ctx, prefix, pageKey, limit, MaxV139ListQueryLimit)
	if err != nil {
		return nil, nil, err
	}
	out := make([]*types.CurationMembership, 0, len(records))
	for _, record := range records {
		rest := record.Key[len(prefix):]
		if len(rest) < 2 {
			return nil, nil, fmt.Errorf("malformed curation membership key")
		}
		n := int(binary.BigEndian.Uint16(rest[:2]))
		if len(rest) != 2+n || len(record.Value) != 8 {
			return nil, nil, fmt.Errorf("malformed curation membership")
		}
		out = append(out, &types.CurationMembership{
			Community: string(rest[2:]),
			TeamId:    binary.BigEndian.Uint64(record.Value),
		})
	}
	return out, nextKey, nil
}

func (k Keeper) GetCreatorAccrualsPaginated(
	ctx sdk.Context,
	creator []byte,
	pageKey []byte,
	limit uint64,
) ([]*types.CreatorAccrual, []byte, error) {
	prefix := types.KeyCreatorEpochIdxPrefix(creator)
	records, nextKey, err := k.getPrefixPage(ctx, prefix, pageKey, limit, MaxCreatorAccrualQueryLimit)
	if err != nil {
		return nil, nil, err
	}
	out := make([]*types.CreatorAccrual, 0, len(records))
	for _, record := range records {
		if len(record.Key) != len(prefix)+8 {
			return nil, nil, fmt.Errorf("malformed creator accrual index")
		}
		epoch := int64(binary.BigEndian.Uint64(record.Key[len(prefix):]))
		var accrual types.CreatorAccrual
		found, err := k.getProto(ctx, types.KeyEpochCreatorAccrual(epoch, creator), &accrual)
		if err != nil {
			return nil, nil, err
		}
		if !found {
			return nil, nil, fmt.Errorf("creator accrual index points to missing accrual")
		}
		copyAccrual := accrual
		out = append(out, &copyAccrual)
	}
	return out, nextKey, nil
}

func (k Keeper) GetTargetEarningsPaginated(
	ctx sdk.Context,
	target []byte,
	pageKey []byte,
	limit uint64,
) ([]*types.TargetEarning, []byte, error) {
	prefix := concatBytes([]byte(types.PfxTargetEpoch), target)
	records, nextKey, err := k.getPrefixPage(ctx, prefix, pageKey, limit, MaxCreatorAccrualQueryLimit)
	if err != nil {
		return nil, nil, err
	}
	out := make([]*types.TargetEarning, 0, len(records))
	for _, record := range records {
		if len(record.Key) != len(prefix)+8 {
			return nil, nil, fmt.Errorf("malformed target earning index")
		}
		epoch := int64(binary.BigEndian.Uint64(record.Key[len(prefix):]))
		var earning types.TargetEarning
		found, err := k.getProto(ctx, types.KeyEpochTarget(epoch, target), &earning)
		if err != nil {
			return nil, nil, err
		}
		if !found {
			return nil, nil, fmt.Errorf("target earning index points to missing earning")
		}
		copyEarning := earning
		out = append(out, &copyEarning)
	}
	return out, nextKey, nil
}

func (k Keeper) GetSubscriptionTranchesPaginated(
	ctx sdk.Context,
	address string,
	pageKey []byte,
	limit uint64,
) ([]*types.SubscriptionTranche, []byte, error) {
	prefix := types.KeyTrancheRecipientPrefix(address)
	records, nextKey, err := k.getPrefixPage(ctx, prefix, pageKey, limit, MaxV139ListQueryLimit)
	if err != nil {
		return nil, nil, err
	}
	out := make([]*types.SubscriptionTranche, 0, len(records))
	for _, record := range records {
		if len(record.Key) != len(prefix)+8 {
			return nil, nil, fmt.Errorf("malformed tranche recipient index")
		}
		id := binary.BigEndian.Uint64(record.Key[len(prefix):])
		var tranche types.SubscriptionTranche
		found, err := k.getProto(ctx, types.KeyTranche(id), &tranche)
		if err != nil {
			return nil, nil, err
		}
		if !found {
			return nil, nil, fmt.Errorf("tranche recipient index points to missing tranche")
		}
		copyTranche := tranche
		out = append(out, &copyTranche)
	}
	return out, nextKey, nil
}

func (k Keeper) GetTerminalCreatorEpochsPaginated(
	ctx sdk.Context,
	cutoffDeadlineUnix int64,
	pageKey []byte,
	limit uint64,
) ([]*types.CreatorEpoch, []byte, error) {
	prefix := []byte(types.PfxCreatorEpochDeadline)
	if len(pageKey) == 0 {
		pageKey = i64bytes(cutoffDeadlineUnix)
	}
	records, nextKey, err := k.getPrefixPage(ctx, prefix, pageKey, limit, MaxCreatorAccrualQueryLimit)
	if err != nil {
		return nil, nil, err
	}
	out := make([]*types.CreatorEpoch, 0, len(records))
	for _, record := range records {
		if len(record.Key) != len(prefix)+16 {
			return nil, nil, fmt.Errorf("malformed creator epoch deadline index")
		}
		epochID := int64(binary.BigEndian.Uint64(record.Key[len(prefix)+8:]))
		var epoch types.CreatorEpoch
		found, err := k.getProto(ctx, types.KeyCreatorEpoch(epochID), &epoch)
		if err != nil {
			return nil, nil, err
		}
		if !found {
			return nil, nil, fmt.Errorf("creator epoch deadline index points to missing epoch")
		}
		if epoch.Status != types.CreatorEpochStatus_CREATOR_EPOCH_STATUS_CLAIMABLE {
			return nil, nil, fmt.Errorf("creator epoch deadline index points to non-claimable epoch")
		}
		copyEpoch := epoch
		out = append(out, &copyEpoch)
	}
	return out, nextKey, nil
}
