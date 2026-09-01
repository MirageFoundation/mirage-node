package core

import (
	"bytes"
	"context"

	"sort"

	"time"

	"cosmossdk.io/core/store"
	"cosmossdk.io/log/v2"
	sdkmath "cosmossdk.io/math"
	"github.com/cosmos/cosmos-sdk/codec"
	codectypes "github.com/cosmos/cosmos-sdk/codec/types"
	storetypes "github.com/cosmos/cosmos-sdk/store/v2/types"
	sdk "github.com/cosmos/cosmos-sdk/types"
	bankkeeper "github.com/cosmos/cosmos-sdk/x/bank/keeper"
	slashingkeeper "github.com/cosmos/cosmos-sdk/x/slashing/keeper"

	"mirage/x/core/keeper"
	"mirage/x/core/types"
)

// mockStoreService implements store.KVStoreService for testing.
//
// Error-injection knobs are optional (nil maps → clean passthrough, default
// behavior unchanged for existing callers). They let tests force specific
// store operations to fail so we can exercise the fail-fast paths in
// GetParams, BeginBlock, EndBlock, etc.
type mockStoreService struct {
	store        map[string][]byte
	getErrors    map[string]error // per-key Get failures
	setErrors    map[string]error // per-key Set failures
	deleteErrors map[string]error // per-key Delete failures
	iterError    error            // global Iterator failure
}

func newMockStoreService() *mockStoreService {
	return &mockStoreService{store: make(map[string][]byte)}
}

func (m *mockStoreService) OpenKVStore(ctx context.Context) store.KVStore {
	return &mockKVStore{
		store:        m.store,
		getErrors:    m.getErrors,
		setErrors:    m.setErrors,
		deleteErrors: m.deleteErrors,
		iterError:    m.iterError,
	}
}

type mockKVStore struct {
	store        map[string][]byte
	getErrors    map[string]error
	setErrors    map[string]error
	deleteErrors map[string]error
	iterError    error
}

func (m *mockKVStore) Get(key []byte) ([]byte, error) {
	if err, ok := m.getErrors[string(key)]; ok {
		return nil, err
	}
	return m.store[string(key)], nil
}

func (m *mockKVStore) Has(key []byte) (bool, error) {
	if err, ok := m.getErrors[string(key)]; ok {
		return false, err
	}
	_, ok := m.store[string(key)]
	return ok, nil
}

func (m *mockKVStore) Set(key, value []byte) error {
	if err, ok := m.setErrors[string(key)]; ok {
		return err
	}
	m.store[string(key)] = value
	return nil
}

func (m *mockKVStore) Delete(key []byte) error {
	if err, ok := m.deleteErrors[string(key)]; ok {
		return err
	}
	delete(m.store, string(key))
	return nil
}

func (m *mockKVStore) Iterator(start, end []byte) (store.Iterator, error) {
	if m.iterError != nil {
		return nil, m.iterError
	}
	return newSortedMockIterator(m.store, start, end, false), nil
}

func (m *mockKVStore) ReverseIterator(start, end []byte) (store.Iterator, error) {
	if m.iterError != nil {
		return nil, m.iterError
	}
	return newSortedMockIterator(m.store, start, end, true), nil
}

// sortedMockIterator iterates over map keys in lexicographic order within [start, end).
type sortedMockIterator struct {
	keys    []string
	values  [][]byte
	pos     int
	start   []byte
	end     []byte
	reverse bool
}

func newSortedMockIterator(data map[string][]byte, start, end []byte, reverse bool) *sortedMockIterator {
	var filtered []string
	for k := range data {
		kb := []byte(k)
		if start != nil && bytes.Compare(kb, start) < 0 {
			continue
		}
		if end != nil && bytes.Compare(kb, end) >= 0 {
			continue
		}
		filtered = append(filtered, k)
	}
	sort.Strings(filtered)
	if reverse {
		for i, j := 0, len(filtered)-1; i < j; i, j = i+1, j-1 {
			filtered[i], filtered[j] = filtered[j], filtered[i]
		}
	}
	vals := make([][]byte, len(filtered))
	for i, k := range filtered {
		vals[i] = data[k]
	}
	return &sortedMockIterator{keys: filtered, values: vals, pos: 0, start: start, end: end, reverse: reverse}
}

func (it *sortedMockIterator) Domain() ([]byte, []byte) { return it.start, it.end }
func (it *sortedMockIterator) Valid() bool              { return it.pos < len(it.keys) }
func (it *sortedMockIterator) Next()                    { it.pos++ }
func (it *sortedMockIterator) Key() []byte {
	if it.pos < len(it.keys) {
		return []byte(it.keys[it.pos])
	}
	return nil
}
func (it *sortedMockIterator) Value() []byte {
	if it.pos < len(it.values) {
		return it.values[it.pos]
	}
	return nil
}
func (it *sortedMockIterator) Close() error { return nil }
func (it *sortedMockIterator) Error() error { return nil }

// mockBank is a minimal bankkeeper.Keeper used only so EndBlock's supply
// invariant guard (AssertSupplyInvariant) can run in unit tests. An empty bank
// trivially satisfies supply == sum(balances) (0 == 0). Only IterateAllBalances
// and GetSupply are exercised by the guard; the embedded nil interface means any
// other bank call panics, surfacing an unmocked path rather than hiding it.
type mockBank struct {
	bankkeeper.Keeper

	// sendToModuleErr is returned by SendCoinsFromAccountToModule when set, so
	// tests can distinguish a typed insufficient-funds rejection from a
	// node-local bank/store failure.
	sendToModuleErr error

	sendModuleToModuleErr  error
	sendModuleToAccountErr error
	burnCoinsErr           error
	sentModuleToAccount    sdk.Coins

	// balances overrides the default empty balance per bech32 address. Needed to
	// back escrowed reserve, which BurnFromModuleAmount refuses to burn without
	// a matching module balance.
	balances map[string]sdkmath.Int
}

func (mockBank) IterateAllBalances(context.Context, func(sdk.AccAddress, sdk.Coin) bool) {}

func (mockBank) GetSupply(_ context.Context, denom string) sdk.Coin {
	return sdk.NewCoin(denom, sdkmath.ZeroInt())
}

func (mockBank) IterateTotalSupply(_ context.Context, _ func(sdk.Coin) bool) {}

// GetBalance reports every account as empty unless a test says otherwise, which
// is what BeginBlock's fee-collector burn needs to reach its early return.
// Without it the embedded nil bankkeeper.Keeper panics and BeginBlock cannot be
// exercised at all.
func (m *mockBank) GetBalance(_ context.Context, addr sdk.AccAddress, denom string) sdk.Coin {
	if amt, ok := m.balances[addr.String()]; ok {
		return sdk.NewCoin(denom, amt)
	}
	return sdk.NewCoin(denom, sdkmath.ZeroInt())
}

func (m *mockBank) GetAllBalances(_ context.Context, addr sdk.AccAddress) sdk.Coins {
	if amt, ok := m.balances[addr.String()]; ok && amt.IsPositive() {
		return sdk.NewCoins(sdk.NewCoin(types.MintDenom, amt))
	}
	return sdk.NewCoins()
}

// SpendableCoins mirrors the configured balances. Most tests leave the map
// empty, so DeleteUserState still has nothing to sweep.
func (m *mockBank) SpendableCoins(ctx context.Context, addr sdk.AccAddress) sdk.Coins {
	return m.GetAllBalances(ctx, addr)
}

func (m *mockBank) SendCoinsFromAccountToModule(_ context.Context, _ sdk.AccAddress, _ string, _ sdk.Coins) error {
	return m.sendToModuleErr
}

func (m *mockBank) SendCoinsFromModuleToModule(_ context.Context, _, _ string, _ sdk.Coins) error {
	return m.sendModuleToModuleErr
}

func (m *mockBank) SendCoinsFromModuleToAccount(_ context.Context, _ string, _ sdk.AccAddress, coins sdk.Coins) error {
	if m.sendModuleToAccountErr != nil {
		return m.sendModuleToAccountErr
	}
	m.sentModuleToAccount = m.sentModuleToAccount.Add(coins...)
	return nil
}

func (m *mockBank) BurnCoins(_ context.Context, _ string, _ sdk.Coins) error {
	return m.burnCoinsErr
}

// mockKeeper wraps keeper.Keeper to override IsValidatorBonded for testing
type mockKeeper struct {
	keeper.Keeper
	storeService    *mockStoreService
	bank            *mockBank
	bondedValidator string // validator address that is considered bonded
}

func newMockKeeper() *mockKeeper {
	storeService := newMockStoreService()
	interfaceRegistry := codectypes.NewInterfaceRegistry()
	cdc := codec.NewProtoCodec(interfaceRegistry)

	// Create a real keeper with a minimal mock bank and nil/empty keepers
	// (we'll override what we need). The bank is a pointer so tests can inject
	// failures after construction.
	bank := &mockBank{}
	k := keeper.NewKeeper(storeService, cdc, bank, nil, nil, slashingkeeper.Keeper{})

	mk := &mockKeeper{
		Keeper:          k,
		storeService:    storeService,
		bank:            bank,
		bondedValidator: testValoperAddressString(),
	}

	// Seed default params so GetParams' fail-fast contract (panic on empty
	// store) does not fire from unrelated tests. Tests that exercise the
	// fail-fast path itself bypass this by deleting / corrupting the
	// "params" key before calling GetParams.
	if err := mk.SetParams(newMockContext(), types.DefaultParams()); err != nil {
		panic("test setup: SetParams failed: " + err.Error())
	}
	return mk
}

func (mk *mockKeeper) IsValidatorBonded(ctx sdk.Context, valoper string) (bool, error) {
	return valoper == mk.bondedValidator, nil
}

func testAccAddress() sdk.AccAddress {
	return sdk.AccAddress(bytes.Repeat([]byte{0x01}, 20))
}

func testAccAddressString() string {
	return testAccAddress().String()
}

func testValoperAddressString() string {
	return sdk.ValAddress(testAccAddress()).String()
}

// Helper to create a mock SDK context
func newMockContext() sdk.Context {
	return sdk.Context{}.
		WithContext(context.Background()).
		WithBlockHeight(100).
		WithBlockTime(time.Unix(1700000000, 0)).
		WithEventManager(sdk.NewEventManager()).
		WithGasMeter(storetypes.NewInfiniteGasMeter()).
		WithLogger(log.NewNopLogger())
}
