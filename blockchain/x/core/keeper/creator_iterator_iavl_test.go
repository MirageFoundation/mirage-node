package keeper

import (
	"testing"

	dbm "github.com/cosmos/cosmos-db"
	"github.com/stretchr/testify/require"

	"mirage/x/core/types"
)

func TestCreatorPruningCollectsBeforeMutatingIAVL(t *testing.T) {
	k, ctx, _ := nonceRoundTripFixture(t, dbm.NewMemDB())
	const epoch = int64(42)
	for i := byte(1); i <= 3; i++ {
		actor := make([]byte, 20)
		actor[19] = i
		target := make([]byte, 32)
		target[31] = i
		require.NoError(t, k.storeSet(ctx, types.KeyEngagement(epoch, actor, types.EngagementKindUpvote, target), []byte{}))
		require.NoError(t, k.storeSet(ctx, types.KeyEngagementCount(epoch, actor), putU64(1)))
		require.NoError(t, k.storeSet(ctx, types.KeyEngagementValid(epoch, actor, types.EngagementKindUpvote, target), []byte{1}))
	}

	prefixes := [][]byte{
		types.KeyEngagementEpochPrefix(epoch),
		concatBytes([]byte(types.PfxEngagementCount), i64bytes(epoch)),
		types.KeyEngagementValidEpochPrefix(epoch),
	}
	for _, prefix := range prefixes {
		for {
			remaining, err := k.deleteCreatorPrefixBudget(ctx, prefix, 2)
			require.NoError(t, err)
			count := 0
			require.NoError(t, k.iterPrefixKeys(ctx, prefix, 0, func(_, _ []byte) error {
				count++
				return nil
			}))
			if count == 0 {
				require.Greater(t, remaining, 0)
				break
			}
			require.Zero(t, remaining)
		}
	}
}
