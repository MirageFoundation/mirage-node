package keeper

import (
	"bytes"
	"context"
	"sort"
	"testing"

	"cosmossdk.io/core/store"
	"cosmossdk.io/log/v2"
	sdkmath "cosmossdk.io/math"
	"github.com/cosmos/cosmos-sdk/codec"
	codectypes "github.com/cosmos/cosmos-sdk/codec/types"
	sdk "github.com/cosmos/cosmos-sdk/types"
	stakingtypes "github.com/cosmos/cosmos-sdk/x/staking/types"
	"github.com/stretchr/testify/require"

	"mirage/x/core/types"
)

type mintStakingMock struct {
	validators []stakingtypes.Validator
}

func (m mintStakingMock) GetValidator(_ context.Context, addr sdk.ValAddress) (stakingtypes.Validator, error) {
	for _, validator := range m.validators {
		if validator.OperatorAddress == addr.String() {
			return validator, nil
		}
	}
	return stakingtypes.Validator{}, stakingtypes.ErrNoValidatorFound
}

func (mintStakingMock) PowerReduction(context.Context) sdkmath.Int {
	return sdkmath.OneInt()
}

func (m mintStakingMock) IterateValidators(
	_ context.Context,
	fn func(int64, stakingtypes.ValidatorI) bool,
) error {
	for i := range m.validators {
		if fn(int64(i), m.validators[i]) {
			break
		}
	}
	return nil
}

func (m mintStakingMock) IterateBondedValidatorsByPower(
	ctx context.Context,
	fn func(int64, stakingtypes.ValidatorI) bool,
) error {
	return m.IterateValidators(ctx, fn)
}

type mintKVService struct {
	data map[string][]byte
}

func (s mintKVService) OpenKVStore(context.Context) store.KVStore {
	return &mintKVStore{data: s.data}
}

type mintKVStore struct {
	data map[string][]byte
}

func (s *mintKVStore) Get(key []byte) ([]byte, error) {
	return s.data[string(key)], nil
}

func (s *mintKVStore) Has(key []byte) (bool, error) {
	_, ok := s.data[string(key)]
	return ok, nil
}

func (s *mintKVStore) Set(key, value []byte) error {
	s.data[string(key)] = bytes.Clone(value)
	return nil
}

func (s *mintKVStore) Delete(key []byte) error {
	delete(s.data, string(key))
	return nil
}

func (s *mintKVStore) Iterator(start, end []byte) (store.Iterator, error) {
	keys := make([]string, 0)
	for key := range s.data {
		raw := []byte(key)
		if (start == nil || bytes.Compare(raw, start) >= 0) && (end == nil || bytes.Compare(raw, end) < 0) {
			keys = append(keys, key)
		}
	}
	sort.Strings(keys)
	return &mintIterator{data: s.data, keys: keys, start: bytes.Clone(start), end: bytes.Clone(end)}, nil
}

func (s *mintKVStore) ReverseIterator(start, end []byte) (store.Iterator, error) {
	it, err := s.Iterator(start, end)
	if err != nil {
		return nil, err
	}
	for left, right := 0, len(it.(*mintIterator).keys)-1; left < right; left, right = left+1, right-1 {
		it.(*mintIterator).keys[left], it.(*mintIterator).keys[right] =
			it.(*mintIterator).keys[right], it.(*mintIterator).keys[left]
	}
	return it, nil
}

type mintIterator struct {
	data       map[string][]byte
	keys       []string
	index      int
	start, end []byte
}

func (it *mintIterator) Domain() ([]byte, []byte) { return it.start, it.end }
func (it *mintIterator) Valid() bool              { return it.index < len(it.keys) }
func (it *mintIterator) Next()                    { it.index++ }
func (it *mintIterator) Key() []byte              { return []byte(it.keys[it.index]) }
func (it *mintIterator) Value() []byte            { return it.data[it.keys[it.index]] }
func (it *mintIterator) Error() error             { return nil }
func (it *mintIterator) Close() error             { return nil }

func TestMintIfNeededUsesFloorWorkAndStakePlan(t *testing.T) {
	small := stakingtypes.Validator{
		OperatorAddress: sdk.ValAddress(bytes.Repeat([]byte{0x11}, 20)).String(),
		Tokens:          sdkmath.NewInt(1_000_000),
		Status:          stakingtypes.Bonded,
	}
	large := stakingtypes.Validator{
		OperatorAddress: sdk.ValAddress(bytes.Repeat([]byte{0x22}, 20)).String(),
		Tokens:          sdkmath.NewInt(3_000_000),
		Status:          stakingtypes.Bonded,
	}
	storeService := mintKVService{data: make(map[string][]byte)}
	bank := newMockMintBank()
	cdc := codec.NewProtoCodec(codectypes.NewInterfaceRegistry())
	k := Keeper{
		storeService: storeService,
		cdc:          cdc,
		bank:         bank,
		staking:      mintStakingMock{validators: []stakingtypes.Validator{large, small}},
	}
	ctx := sdk.Context{}.
		WithContext(context.Background()).
		WithBlockHeight(200).
		WithLogger(log.NewNopLogger())

	params := types.DefaultParams()
	params.MintInterval = 200
	params.MintQuantity = 1_000_000
	params.MintFloorSplit = 0.20
	params.MintDynamicSplit = 0.10
	params.MintDynamicCreditCap = 25
	require.NoError(t, k.SetParams(ctx, params))
	require.NoError(t, k.AddRelayCredit(ctx, small.OperatorAddress, sdkmath.NewInt(25)))
	require.NoError(t, k.AddRelayCredit(ctx, large.OperatorAddress, sdkmath.NewInt(25)))

	require.NoError(t, k.MintIfNeeded(ctx))

	sent := make(map[string]sdkmath.Int)
	for _, call := range bank.calls {
		if call.op == "send" {
			sent[call.to.String()] = call.amount
		}
	}
	require.Equal(t, sdkmath.NewInt(325_000), sent[sdk.AccAddress(bytes.Repeat([]byte{0x11}, 20)).String()])
	require.Equal(t, sdkmath.NewInt(675_000), sent[sdk.AccAddress(bytes.Repeat([]byte{0x22}, 20)).String()])
	require.Equal(t, sdkmath.NewInt(1_000_000), bank.supply)
	require.True(t, bank.moduleBalance.IsZero())
	require.True(t, k.GetRelayCredit(ctx, small.OperatorAddress).IsZero())
	require.True(t, k.GetRelayCredit(ctx, large.OperatorAddress).IsZero())
}
