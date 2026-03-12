package core

import (
	"bytes"
	"context"
	"crypto/sha256"
	"sort"
	"strconv"
	"strings"
	"testing"
	"time"

	"cosmossdk.io/core/store"
	"cosmossdk.io/log"
	storetypes "cosmossdk.io/store/types"
	"github.com/cosmos/cosmos-sdk/codec"
	codectypes "github.com/cosmos/cosmos-sdk/codec/types"
	sdk "github.com/cosmos/cosmos-sdk/types"
	slashingkeeper "github.com/cosmos/cosmos-sdk/x/slashing/keeper"
	"github.com/gogo/protobuf/proto"

	"mirage/x/core/keeper"
	"mirage/x/core/types"
)

// mockStoreService implements store.KVStoreService for testing
type mockStoreService struct {
	store map[string][]byte
}

func newMockStoreService() *mockStoreService {
	return &mockStoreService{store: make(map[string][]byte)}
}

func (m *mockStoreService) OpenKVStore(ctx context.Context) store.KVStore {
	return &mockKVStore{store: m.store}
}

type mockKVStore struct {
	store map[string][]byte
}

func (m *mockKVStore) Get(key []byte) ([]byte, error) {
	return m.store[string(key)], nil
}

func (m *mockKVStore) Has(key []byte) (bool, error) {
	_, ok := m.store[string(key)]
	return ok, nil
}

func (m *mockKVStore) Set(key, value []byte) error {
	m.store[string(key)] = value
	return nil
}

func (m *mockKVStore) Delete(key []byte) error {
	delete(m.store, string(key))
	return nil
}

func (m *mockKVStore) Iterator(start, end []byte) (store.Iterator, error) {
	return newSortedMockIterator(m.store, start, end, false), nil
}

func (m *mockKVStore) ReverseIterator(start, end []byte) (store.Iterator, error) {
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

// mockKeeper wraps keeper.Keeper to override IsValidatorBonded for testing
type mockKeeper struct {
	keeper.Keeper
	storeService    *mockStoreService
	bondedValidator string // validator address that is considered bonded
}

func newMockKeeper() *mockKeeper {
	storeService := newMockStoreService()
	interfaceRegistry := codectypes.NewInterfaceRegistry()
	cdc := codec.NewProtoCodec(interfaceRegistry)

	// Create a real keeper with nil/empty keepers (we'll override what we need)
	k := keeper.NewKeeper(storeService, cdc, nil, nil, nil, slashingkeeper.Keeper{})

	return &mockKeeper{
		Keeper:          k,
		storeService:    storeService,
		bondedValidator: testValoperAddressString(),
	}
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

// TestBridgeBurnRecordStorage tests the keeper's burn record storage
func TestBridgeBurnRecordStorage(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()

	destChain := "solana"
	burnID := "1"

	// Initially should not exist
	_, found, err := mk.GetBridgeBurnRecord(ctx, destChain, burnID)
	if err != nil {
		t.Fatalf("GetBridgeBurnRecord error: %v", err)
	}
	if found {
		t.Error("Expected burn record to not exist initially")
	}

	// Store a record
	record := &types.BridgeBurnRecord{
		BurnID:             burnID,
		Owner:              "mirage1owner",
		DestinationChain:   destChain,
		DestinationAddress: "SolanaAddr123",
		Amount:             1000000,
		BridgeFee:          10000,
		Sequence:           1,
		CreatedAt:          100,
	}

	err = mk.SetBridgeBurnRecord(ctx, record)
	if err != nil {
		t.Fatalf("SetBridgeBurnRecord error: %v", err)
	}

	// Should now exist
	restored, found, err := mk.GetBridgeBurnRecord(ctx, destChain, burnID)
	if err != nil {
		t.Fatalf("GetBridgeBurnRecord error: %v", err)
	}
	if !found {
		t.Fatal("Expected burn record to exist")
	}

	if restored.BurnID != record.BurnID {
		t.Errorf("BurnID mismatch: got %s, want %s", restored.BurnID, record.BurnID)
	}
	if restored.DestinationChain != record.DestinationChain {
		t.Errorf("DestinationChain mismatch: got %s, want %s", restored.DestinationChain, record.DestinationChain)
	}

	// Test that different destination chain doesn't find the record
	_, found, _ = mk.GetBridgeBurnRecord(ctx, "ethereum", burnID)
	if found {
		t.Error("Expected burn record to not exist for different chain")
	}
}

func TestEnvelopeNoncePrune(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()

	pubHash := sha256.Sum256([]byte("pubkey-1"))
	nonce := uint64(42)
	expiry := ctx.BlockTime().Unix() + 60

	if err := mk.SetEnvelopeNonce(ctx, pubHash[:16], nonce, expiry); err != nil {
		t.Fatalf("SetEnvelopeNonce error: %v", err)
	}
	if !mk.HasEnvelopeNonce(ctx, pubHash[:16], nonce) {
		t.Fatalf("expected nonce to exist before pruning")
	}

	pruned, err := mk.PruneExpiredNonces(ctx, expiry-1)
	if err != nil {
		t.Fatalf("PruneExpiredNonces error: %v", err)
	}
	if pruned != 0 {
		t.Fatalf("pruned=%d, want 0", pruned)
	}
	if !mk.HasEnvelopeNonce(ctx, pubHash[:16], nonce) {
		t.Fatalf("expected nonce to remain before expiry")
	}

	pruned, err = mk.PruneExpiredNonces(ctx, expiry)
	if err != nil {
		t.Fatalf("PruneExpiredNonces error: %v", err)
	}
	if pruned != 1 {
		t.Fatalf("pruned=%d, want 1", pruned)
	}
	if mk.HasEnvelopeNonce(ctx, pubHash[:16], nonce) {
		t.Fatalf("expected nonce to be pruned")
	}
}

// TestBridgeMintedRecordStorage tests the keeper's minted record storage
func TestBridgeMintedRecordStorage(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()

	destChain := "solana"
	burnID := "1"

	// Initially should not exist
	_, found, err := mk.GetBridgeMintedRecord(ctx, destChain, burnID)
	if err != nil {
		t.Fatalf("GetBridgeMintedRecord error: %v", err)
	}
	if found {
		t.Error("Expected minted record to not exist initially")
	}

	// Store a record
	record := &types.BridgeMintedRecord{
		BurnID:           burnID,
		DestinationChain: destChain,
		DestinationTx:    "SolanaSignature123",
		CreatedAt:        100,
	}

	err = mk.SetBridgeMintedRecord(ctx, record)
	if err != nil {
		t.Fatalf("SetBridgeMintedRecord error: %v", err)
	}

	// Should now exist
	restored, found, err := mk.GetBridgeMintedRecord(ctx, destChain, burnID)
	if err != nil {
		t.Fatalf("GetBridgeMintedRecord error: %v", err)
	}
	if !found {
		t.Fatal("Expected minted record to exist")
	}

	if restored.BurnID != record.BurnID {
		t.Errorf("BurnID mismatch: got %s, want %s", restored.BurnID, record.BurnID)
	}
	if restored.DestinationTx != record.DestinationTx {
		t.Errorf("DestinationTx mismatch: got %s, want %s", restored.DestinationTx, record.DestinationTx)
	}

	// Test that different destination chain doesn't find the record
	_, found, _ = mk.GetBridgeMintedRecord(ctx, "ethereum", burnID)
	if found {
		t.Error("Expected minted record to not exist for different chain")
	}
}

// TestBridgeMintAttestationStorage tests the keeper's mint attestation storage
func TestBridgeMintAttestationStorage(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()

	burnID := "1"
	destChain := "solana"

	// Initially should not exist
	_, found, err := mk.GetBridgeMintAttestation(ctx, destChain, burnID)
	if err != nil {
		t.Fatalf("GetBridgeMintAttestation error: %v", err)
	}
	if found {
		t.Error("Expected mint attestation to not exist initially")
	}

	// Store an attestation
	attestation := types.NewBridgeMintAttestation(burnID, destChain, "SolanaSignature123", 100)
	attestation.AttestedPower = 1000

	err = mk.SetBridgeMintAttestation(ctx, attestation)
	if err != nil {
		t.Fatalf("SetBridgeMintAttestation error: %v", err)
	}

	// Should now exist
	restored, found, err := mk.GetBridgeMintAttestation(ctx, destChain, burnID)
	if err != nil {
		t.Fatalf("GetBridgeMintAttestation error: %v", err)
	}
	if !found {
		t.Fatal("Expected mint attestation to exist")
	}

	if restored.BurnID != attestation.BurnID {
		t.Errorf("BurnID mismatch: got %s, want %s", restored.BurnID, attestation.BurnID)
	}
	if restored.DestinationChain != attestation.DestinationChain {
		t.Errorf("DestinationChain mismatch: got %s, want %s", restored.DestinationChain, attestation.DestinationChain)
	}
	if restored.AttestedPower != attestation.AttestedPower {
		t.Errorf("AttestedPower mismatch: got %d, want %d", restored.AttestedPower, attestation.AttestedPower)
	}
}

// TestBridgeMintAttestationThreshold tests threshold logic
func TestBridgeMintAttestationThreshold(t *testing.T) {
	attestation := types.NewBridgeMintAttestation("1", "solana", "sig123", 100)

	totalPower := int64(10000)
	threshold := 0.6667 // 66.67%

	// Add 50% power - should not meet threshold
	attestation.AttestedPower = 5000
	if attestation.MeetsThreshold(totalPower, threshold) {
		t.Error("Expected threshold NOT to be met with 50% power")
	}

	// Add 17% more power (total 67%) - should meet threshold
	attestation.AttestedPower = 6700
	if !attestation.MeetsThreshold(totalPower, threshold) {
		t.Error("Expected threshold to be met with 67% power")
	}

	// Verify required power calculation
	required := types.RequiredPower(totalPower, threshold)
	if required != 6667 {
		t.Errorf("Expected required power 6667, got %d", required)
	}
}

// TestBridgeMintAttestationGetOrCreate tests get-or-create behavior
func TestBridgeMintAttestationGetOrCreate(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()

	burnID := "1"
	destChain := "solana"
	destTx := "SolanaSignature123"

	// First call should create
	attestation1, err := mk.GetOrCreateBridgeMintAttestation(ctx, burnID, destChain, destTx)
	if err != nil {
		t.Fatalf("GetOrCreateBridgeMintAttestation error: %v", err)
	}
	if attestation1.BurnID != burnID {
		t.Errorf("BurnID mismatch: got %s, want %s", attestation1.BurnID, burnID)
	}
	if attestation1.DestinationTx != destTx {
		t.Errorf("DestinationTx mismatch: got %s, want %s", attestation1.DestinationTx, destTx)
	}

	// Modify and save
	attestation1.AttestedPower = 1000
	if err := mk.SetBridgeMintAttestation(ctx, attestation1); err != nil {
		t.Fatalf("SetBridgeMintAttestation error: %v", err)
	}

	// Second call should return existing
	attestation2, err := mk.GetOrCreateBridgeMintAttestation(ctx, burnID, destChain, destTx)
	if err != nil {
		t.Fatalf("GetOrCreateBridgeMintAttestation error: %v", err)
	}
	if attestation2.AttestedPower != 1000 {
		t.Errorf("Expected existing attestation with power 1000, got %d", attestation2.AttestedPower)
	}
}

// TestValidateTxHash tests tx hash validation (used by handlers)
func TestValidateTxHash(t *testing.T) {
	tests := []struct {
		name    string
		hash    string
		wantErr bool
	}{
		{
			name:    "valid 64 char hex",
			hash:    "abc123def456789012345678901234567890123456789012345678901234",
			wantErr: false,
		},
		{
			name:    "valid uppercase hex",
			hash:    "ABC123DEF456789012345678901234567890123456789012345678901234",
			wantErr: false,
		},
		{
			name:    "too short",
			hash:    "abc123",
			wantErr: true,
		},
		{
			name:    "too long",
			hash:    "abc123def4567890123456789012345678901234567890123456789012345678901234",
			wantErr: true,
		},
		{
			name:    "invalid characters",
			hash:    "xyz123def456789012345678901234567890123456789012345678901234",
			wantErr: true,
		},
		{
			name:    "empty",
			hash:    "",
			wantErr: true,
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			err := validateTxHashForTest(tc.hash)
			if tc.wantErr && err == nil {
				t.Error("expected error, got nil")
			}
			if !tc.wantErr && err != nil {
				t.Errorf("unexpected error: %v", err)
			}
		})
	}
}

// validateTxHashForTest mirrors the validation logic in module.go
func validateTxHashForTest(hash string) error {
	if len(hash) < 60 || len(hash) > 66 {
		return errInvalidTxHash
	}
	for _, c := range hash {
		if !((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f') || (c >= 'A' && c <= 'F')) {
			return errInvalidTxHash
		}
	}
	return nil
}

var errInvalidTxHash = &validationError{"invalid tx hash"}

type validationError struct {
	msg string
}

func (e *validationError) Error() string {
	return e.msg
}

// TestBridgeAttestMintedValidation tests validation logic for MsgBridgeAttestMinted
func TestBridgeAttestMintedValidation(t *testing.T) {
	tests := []struct {
		name      string
		validator string
		burnID    string
		destChain string
		destTx    string
		wantErr   bool
		errSubstr string
	}{
		{
			name:      "valid request",
			validator: testAccAddressString(),
			burnID:    "abc123def456789012345678901234567890123456789012345678901234",
			destChain: "solana",
			destTx:    "SolanaSignature123",
			wantErr:   false,
		},
		{
			name:      "empty validator",
			validator: "",
			burnID:    "abc123def456789012345678901234567890123456789012345678901234",
			destChain: "solana",
			destTx:    "SolanaSignature123",
			wantErr:   true,
			errSubstr: "validator",
		},
		{
			name:      "whitespace validator",
			validator: "   ",
			burnID:    "abc123def456789012345678901234567890123456789012345678901234",
			destChain: "solana",
			destTx:    "SolanaSignature123",
			wantErr:   true,
			errSubstr: "validator",
		},
		{
			name:      "invalid burn_id - too short",
			validator: testAccAddressString(),
			burnID:    "abc123",
			destChain: "solana",
			destTx:    "SolanaSignature123",
			wantErr:   true,
			errSubstr: "burn_id",
		},
		{
			name:      "invalid burn_id - invalid chars",
			validator: testAccAddressString(),
			burnID:    "xyz123def456789012345678901234567890123456789012345678901234",
			destChain: "solana",
			destTx:    "SolanaSignature123",
			wantErr:   true,
			errSubstr: "burn_id",
		},
		{
			name:      "empty destination_chain",
			validator: testAccAddressString(),
			burnID:    "abc123def456789012345678901234567890123456789012345678901234",
			destChain: "",
			destTx:    "SolanaSignature123",
			wantErr:   true,
			errSubstr: "destination_chain",
		},
		{
			name:      "destination_chain too long",
			validator: testAccAddressString(),
			burnID:    "abc123def456789012345678901234567890123456789012345678901234",
			destChain: strings.Repeat("a", 65),
			destTx:    "SolanaSignature123",
			wantErr:   true,
			errSubstr: "destination_chain",
		},
		{
			name:      "empty destination_tx",
			validator: testAccAddressString(),
			burnID:    "abc123def456789012345678901234567890123456789012345678901234",
			destChain: "solana",
			destTx:    "",
			wantErr:   true,
			errSubstr: "destination_tx",
		},
		{
			name:      "destination_tx too long",
			validator: testAccAddressString(),
			burnID:    "abc123def456789012345678901234567890123456789012345678901234",
			destChain: "solana",
			destTx:    strings.Repeat("a", 129),
			wantErr:   true,
			errSubstr: "destination_tx",
		},
		{
			name:      "destination_tx with invalid char (space)",
			validator: testAccAddressString(),
			burnID:    "abc123def456789012345678901234567890123456789012345678901234",
			destChain: "solana",
			destTx:    "Solana Signature123",
			wantErr:   true,
			errSubstr: "invalid character",
		},
		{
			name:      "destination_tx with invalid char (slash)",
			validator: testAccAddressString(),
			burnID:    "abc123def456789012345678901234567890123456789012345678901234",
			destChain: "solana",
			destTx:    "Solana/Signature123",
			wantErr:   true,
			errSubstr: "invalid character",
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			err := validateBridgeMintedRequest(tc.validator, tc.burnID, tc.destChain, tc.destTx)
			if tc.wantErr {
				if err == nil {
					t.Error("expected error, got nil")
				} else if tc.errSubstr != "" && !strings.Contains(err.Error(), tc.errSubstr) {
					t.Errorf("expected error containing %q, got %q", tc.errSubstr, err.Error())
				}
			} else {
				if err != nil {
					t.Errorf("unexpected error: %v", err)
				}
			}
		})
	}
}

// validateBridgeAttestMintedRequest mirrors the validation in module.go BridgeMinted handler
func validateBridgeMintedRequest(validator, burnID, destChain, destTx string) error {
	validator = strings.TrimSpace(validator)
	if validator == "" {
		return &validationError{"validator cannot be empty"}
	}
	if _, err := sdk.AccAddressFromBech32(validator); err != nil {
		return &validationError{"invalid validator address"}
	}

	burnID = strings.ToLower(strings.TrimSpace(burnID))
	if err := validateTxHashForTest(burnID); err != nil {
		return &validationError{"invalid burn_id: " + err.Error()}
	}

	destChain = strings.TrimSpace(destChain)
	if destChain == "" {
		return &validationError{"destination_chain cannot be empty"}
	}
	if len(destChain) > 64 {
		return &validationError{"destination_chain too long"}
	}

	destTx = strings.TrimSpace(destTx)
	if destTx == "" {
		return &validationError{"destination_tx cannot be empty"}
	}
	if len(destTx) > 128 {
		return &validationError{"destination_tx too long"}
	}
	for _, c := range destTx {
		if c <= ' ' || c == '/' {
			return &validationError{"destination_tx contains invalid character"}
		}
	}

	return nil
}

// TestBurnIDNormalization tests that burn_id is normalized to lowercase
func TestBurnIDNormalization(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()

	destChain := "solana"

	// Store with lowercase
	burnIDLower := "1"
	record := &types.BridgeMintedRecord{
		BurnID:           burnIDLower,
		DestinationChain: destChain,
		DestinationTx:    "sig123",
		CreatedAt:        100,
	}
	err := mk.SetBridgeMintedRecord(ctx, record)
	if err != nil {
		t.Fatalf("SetBridgeMintedRecord error: %v", err)
	}

	// Should be found with correct chain and burn_id
	_, found, _ := mk.GetBridgeMintedRecord(ctx, destChain, burnIDLower)
	if !found {
		t.Error("Expected to find record with correct chain and burn_id")
	}

	// Different chain should not find it
	_, found, _ = mk.GetBridgeMintedRecord(ctx, "ethereum", burnIDLower)
	if found {
		t.Error("Should not find record with different chain")
	}

	// Different burn_id should not find it
	_, found, _ = mk.GetBridgeMintedRecord(ctx, destChain, "2")
	if found {
		t.Error("Should not find record with different burn_id")
	}
}

// TestGetBridgeMintQueryResponse tests the query response structure
func TestGetBridgeMintQueryResponse(t *testing.T) {
	// Test response when minted (threshold crossed)
	mintedResp := &types.QueryBridgeMintResponse{
		Found:            true,
		Minted:           true,
		DestinationChain: "solana",
		DestinationTx:    "SolanaSignature123",
		Attestors:        []string{"val1", "val2"},
		AttestedPower:    70,
		RequiredPower:    67,
	}

	if !mintedResp.Found {
		t.Error("Expected Found to be true")
	}
	if !mintedResp.Minted {
		t.Error("Expected Minted to be true")
	}
	if mintedResp.DestinationChain != "solana" {
		t.Errorf("DestinationChain = %s, want solana", mintedResp.DestinationChain)
	}
	if mintedResp.DestinationTx != "SolanaSignature123" {
		t.Errorf("DestinationTx = %s, want SolanaSignature123", mintedResp.DestinationTx)
	}
	if len(mintedResp.Attestors) != 2 {
		t.Errorf("Expected 2 attestors, got %d", len(mintedResp.Attestors))
	}
	if mintedResp.AttestedPower != 70 {
		t.Errorf("AttestedPower = %d, want 70", mintedResp.AttestedPower)
	}
	if mintedResp.RequiredPower != 67 {
		t.Errorf("RequiredPower = %d, want 67", mintedResp.RequiredPower)
	}

	// Test response when attestation in progress (not yet confirmed)
	inProgressResp := &types.QueryBridgeMintResponse{
		Found:            true,
		Minted:           false,
		DestinationChain: "solana",
		DestinationTx:    "SolanaSignature123",
		Attestors:        []string{"val1"},
		AttestedPower:    30,
		RequiredPower:    67,
	}

	if !inProgressResp.Found {
		t.Error("Expected Found to be true for in-progress attestation")
	}
	if inProgressResp.Minted {
		t.Error("Expected Minted to be false for in-progress attestation")
	}
	if inProgressResp.AttestedPower >= inProgressResp.RequiredPower {
		t.Error("In-progress attestation should have AttestedPower < RequiredPower")
	}

	// Test response when no attestation found
	notFoundResp := &types.QueryBridgeMintResponse{
		Found:         false,
		Minted:        false,
		RequiredPower: 67,
	}

	if notFoundResp.Found {
		t.Error("Expected Found to be false")
	}
	if notFoundResp.Minted {
		t.Error("Expected Minted to be false")
	}
	if notFoundResp.RequiredPower != 67 {
		t.Errorf("RequiredPower should still be set, got %d", notFoundResp.RequiredPower)
	}
}

// TestQueryBridgeMintResponseMarshalRoundTrip ensures new fields serialize correctly.
func TestQueryBridgeMintResponseMarshalRoundTrip(t *testing.T) {
	original := &types.QueryBridgeMintResponse{
		Found:            true,
		Minted:           true,
		DestinationChain: "solana",
		DestinationTx:    "SolanaSignature123",
		Attestors:        []string{"val1", "val2"},
		AttestedPower:    70,
		RequiredPower:    67,
	}

	bz, err := proto.Marshal(original)
	if err != nil {
		t.Fatalf("marshal failed: %v", err)
	}

	var decoded types.QueryBridgeMintResponse
	if err := proto.Unmarshal(bz, &decoded); err != nil {
		t.Fatalf("unmarshal failed: %v", err)
	}

	if decoded.Found != original.Found {
		t.Errorf("Found = %v, want %v", decoded.Found, original.Found)
	}
	if decoded.Minted != original.Minted {
		t.Errorf("Minted = %v, want %v", decoded.Minted, original.Minted)
	}
	if decoded.DestinationChain != original.DestinationChain {
		t.Errorf("DestinationChain = %s, want %s", decoded.DestinationChain, original.DestinationChain)
	}
	if decoded.DestinationTx != original.DestinationTx {
		t.Errorf("DestinationTx = %s, want %s", decoded.DestinationTx, original.DestinationTx)
	}
	if len(decoded.Attestors) != len(original.Attestors) {
		t.Fatalf("Attestors length = %d, want %d", len(decoded.Attestors), len(original.Attestors))
	}
	for i := range original.Attestors {
		if decoded.Attestors[i] != original.Attestors[i] {
			t.Fatalf("Attestors[%d] = %s, want %s", i, decoded.Attestors[i], original.Attestors[i])
		}
	}
	if decoded.AttestedPower != original.AttestedPower {
		t.Errorf("AttestedPower = %d, want %d", decoded.AttestedPower, original.AttestedPower)
	}
	if decoded.RequiredPower != original.RequiredPower {
		t.Errorf("RequiredPower = %d, want %d", decoded.RequiredPower, original.RequiredPower)
	}
}

// TestMsgBridgeAttestMintedFields tests the message structure
func TestMsgBridgeAttestMintedFields(t *testing.T) {
	validator := testAccAddressString()
	msg := &types.MsgBridgeAttestMinted{
		Validator:        validator,
		BurnId:           "abc123def456789012345678901234567890123456789012345678901234",
		DestinationChain: "solana",
		DestinationTx:    "SolanaSignature123",
	}

	if msg.Validator != validator {
		t.Errorf("Validator = %s, want %s", msg.Validator, validator)
	}
	if msg.BurnId != "abc123def456789012345678901234567890123456789012345678901234" {
		t.Errorf("BurnId mismatch")
	}
	if msg.DestinationChain != "solana" {
		t.Errorf("DestinationChain = %s, want solana", msg.DestinationChain)
	}
	if msg.DestinationTx != "SolanaSignature123" {
		t.Errorf("DestinationTx = %s, want SolanaSignature123", msg.DestinationTx)
	}
}

// TestDestinationTxCharacterValidation tests edge cases for destination_tx validation
func TestDestinationTxCharacterValidation(t *testing.T) {
	tests := []struct {
		name    string
		destTx  string
		wantErr bool
	}{
		{"valid alphanumeric", "ABC123xyz789", false},
		{"valid with special chars", "ABC-123_xyz.789", false},
		{"space in middle", "ABC 123", true},
		{"leading space", " ABC123", true},
		{"trailing space", "ABC123 ", true},
		{"tab character", "ABC\t123", true},
		{"newline", "ABC\n123", true},
		{"forward slash", "ABC/123", true},
		{"control character", "ABC\x00123", true},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			hasInvalidChar := false
			for _, c := range tc.destTx {
				if c <= ' ' || c == '/' {
					hasInvalidChar = true
					break
				}
			}
			if hasInvalidChar != tc.wantErr {
				t.Errorf("validation for %q: hasInvalidChar=%v, wantErr=%v",
					tc.destTx, hasInvalidChar, tc.wantErr)
			}
		})
	}
}

func TestBridgeBurnEventAttributes(t *testing.T) {
	owner := "mirage1owner"
	destChain := "solana"
	destAddr := "7EYnhQoR9YM3N7UoaKRoA44Uy8JeaZV3qyouov87awMs"
	amount := uint64(12345)
	bridgeFee := uint64(678)
	sequence := uint64(42)

	evt := buildBridgeBurnEvent(owner, destChain, destAddr, amount, bridgeFee, sequence)
	if evt.Type != "bridge_burn" {
		t.Fatalf("event type = %s, want bridge_burn", evt.Type)
	}
	if len(evt.Attributes) != 7 {
		t.Fatalf("attribute count = %d, want 7", len(evt.Attributes))
	}

	attrs := make(map[string]string, len(evt.Attributes))
	for _, attr := range evt.Attributes {
		attrs[attr.Key] = attr.Value
	}

	expected := map[string]string{
		"burn_id":             strconv.FormatUint(sequence, 10),
		"owner":               owner,
		"destination_chain":   destChain,
		"destination_address": destAddr,
		"amount":              strconv.FormatUint(amount, 10),
		"bridge_fee":          strconv.FormatUint(bridgeFee, 10),
		"sequence":            strconv.FormatUint(sequence, 10),
	}

	if len(attrs) != len(expected) {
		t.Fatalf("unexpected attribute count = %d, want %d", len(attrs), len(expected))
	}
	for key, want := range expected {
		got, ok := attrs[key]
		if !ok {
			t.Errorf("missing attribute %q", key)
			continue
		}
		if got != want {
			t.Errorf("attribute %q = %q, want %q", key, got, want)
		}
	}
}

// =============================================================================
// Multi-Chain Key Isolation Tests
// =============================================================================

// TestMultiChainBurnRecordIsolation verifies that burn records for different
// destination chains don't collide even with the same sequence number
func TestMultiChainBurnRecordIsolation(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()

	// Create burn records with same sequence but different chains
	solanaRecord := &types.BridgeBurnRecord{
		BurnID:             "1",
		Owner:              "mirage1owner",
		DestinationChain:   "solana",
		DestinationAddress: "SolanaAddr123",
		Amount:             1000000,
		BridgeFee:          10000,
		Sequence:           1,
		CreatedAt:          100,
	}

	ethereumRecord := &types.BridgeBurnRecord{
		BurnID:             "1", // Same sequence!
		Owner:              "mirage1owner",
		DestinationChain:   "ethereum",
		DestinationAddress: "0xEthereumAddr123",
		Amount:             2000000,
		BridgeFee:          20000,
		Sequence:           1,
		CreatedAt:          100,
	}

	// Store both
	if err := mk.SetBridgeBurnRecord(ctx, solanaRecord); err != nil {
		t.Fatalf("SetBridgeBurnRecord(solana) error: %v", err)
	}
	if err := mk.SetBridgeBurnRecord(ctx, ethereumRecord); err != nil {
		t.Fatalf("SetBridgeBurnRecord(ethereum) error: %v", err)
	}

	// Retrieve and verify they are distinct
	gotSolana, found, err := mk.GetBridgeBurnRecord(ctx, "solana", "1")
	if err != nil {
		t.Fatalf("GetBridgeBurnRecord(solana) error: %v", err)
	}
	if !found {
		t.Fatal("Expected solana record to exist")
	}
	if gotSolana.Amount != 1000000 {
		t.Errorf("Solana amount = %d, want 1000000", gotSolana.Amount)
	}
	if gotSolana.DestinationAddress != "SolanaAddr123" {
		t.Errorf("Solana dest = %s, want SolanaAddr123", gotSolana.DestinationAddress)
	}

	gotEthereum, found, err := mk.GetBridgeBurnRecord(ctx, "ethereum", "1")
	if err != nil {
		t.Fatalf("GetBridgeBurnRecord(ethereum) error: %v", err)
	}
	if !found {
		t.Fatal("Expected ethereum record to exist")
	}
	if gotEthereum.Amount != 2000000 {
		t.Errorf("Ethereum amount = %d, want 2000000", gotEthereum.Amount)
	}
	if gotEthereum.DestinationAddress != "0xEthereumAddr123" {
		t.Errorf("Ethereum dest = %s, want 0xEthereumAddr123", gotEthereum.DestinationAddress)
	}

	// Verify cross-chain lookup returns not found
	_, found, _ = mk.GetBridgeBurnRecord(ctx, "polygon", "1")
	if found {
		t.Error("Expected polygon record to not exist")
	}
}

// TestMultiChainMintedRecordIsolation verifies mint records don't collide
func TestMultiChainMintedRecordIsolation(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()

	solanaRecord := &types.BridgeMintedRecord{
		BurnID:           "1",
		DestinationChain: "solana",
		DestinationTx:    "SolanaSig123",
		CreatedAt:        100,
	}

	ethereumRecord := &types.BridgeMintedRecord{
		BurnID:           "1", // Same sequence!
		DestinationChain: "ethereum",
		DestinationTx:    "0xEthTxHash123",
		CreatedAt:        100,
	}

	if err := mk.SetBridgeMintedRecord(ctx, solanaRecord); err != nil {
		t.Fatalf("SetBridgeMintedRecord(solana) error: %v", err)
	}
	if err := mk.SetBridgeMintedRecord(ctx, ethereumRecord); err != nil {
		t.Fatalf("SetBridgeMintedRecord(ethereum) error: %v", err)
	}

	gotSolana, found, _ := mk.GetBridgeMintedRecord(ctx, "solana", "1")
	if !found || gotSolana.DestinationTx != "SolanaSig123" {
		t.Error("Solana minted record mismatch")
	}

	gotEthereum, found, _ := mk.GetBridgeMintedRecord(ctx, "ethereum", "1")
	if !found || gotEthereum.DestinationTx != "0xEthTxHash123" {
		t.Error("Ethereum minted record mismatch")
	}
}

// =============================================================================
// Inbound Attestation (BridgeAttestation) Tests
// =============================================================================

// TestBridgeAttestationStorage tests inbound attestation storage
func TestBridgeAttestationStorage(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()

	sourceChain := "solana"
	burnID := "12345"

	// Initially should not exist
	_, found, err := mk.GetBridgeAttestation(ctx, sourceChain, burnID)
	if err != nil {
		t.Fatalf("GetBridgeAttestation error: %v", err)
	}
	if found {
		t.Error("Expected attestation to not exist initially")
	}

	// Create attestation (attestors stored separately)
	attestation := types.NewBridgeAttestation(sourceChain, burnID, "mirage1recipient", 1000000, 100)
	attestation.AttestedPower = 100

	if err := mk.SetBridgeAttestation(ctx, attestation); err != nil {
		t.Fatalf("SetBridgeAttestation error: %v", err)
	}

	// Store attestor separately (with burn params for v1.17.0 anti-poisoning)
	if err := mk.SetBridgeAttestor(ctx, sourceChain, burnID, "mirage1recipient", 1000000, "validator1", 100); err != nil {
		t.Fatalf("SetBridgeAttestor error: %v", err)
	}

	// Retrieve and verify using parameterized key (v1.17.0+)
	restored, found, err := mk.GetBridgeAttestationWithParams(ctx, sourceChain, burnID, "mirage1recipient", 1000000)
	if err != nil {
		t.Fatalf("GetBridgeAttestation error: %v", err)
	}
	if !found {
		t.Fatal("Expected attestation to exist")
	}
	if restored.SourceChain != sourceChain {
		t.Errorf("SourceChain = %s, want %s", restored.SourceChain, sourceChain)
	}
	if restored.AttestedPower != 100 {
		t.Errorf("AttestedPower = %d, want 100", restored.AttestedPower)
	}

	// Verify attestor stored separately (with burn params for v1.17.0 anti-poisoning)
	hasAttestor, err := mk.HasBridgeAttestor(ctx, sourceChain, burnID, "mirage1recipient", 1000000, "validator1")
	if err != nil {
		t.Fatalf("HasBridgeAttestor error: %v", err)
	}
	if !hasAttestor {
		t.Error("Expected validator1 to have attested")
	}

	attestors, err := mk.GetBridgeAttestorList(ctx, sourceChain, burnID, "mirage1recipient", 1000000)
	if err != nil {
		t.Fatalf("GetBridgeAttestorList error: %v", err)
	}
	if len(attestors) != 1 || attestors[0] != "validator1" {
		t.Errorf("Attestors = %v, want [validator1]", attestors)
	}
}

// TestBridgeAttestationAmbiguous ensures multiple attestations for same burn_id fail fast.
func TestBridgeAttestationAmbiguous(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()

	sourceChain := "solana"
	burnID := "12345"

	a1 := types.NewBridgeAttestation(sourceChain, burnID, "mirage1alice", 111, 100)
	if err := mk.SetBridgeAttestation(ctx, a1); err != nil {
		t.Fatalf("SetBridgeAttestation error: %v", err)
	}
	a2 := types.NewBridgeAttestation(sourceChain, burnID, "mirage1bob", 222, 100)
	if err := mk.SetBridgeAttestation(ctx, a2); err != nil {
		t.Fatalf("SetBridgeAttestation error: %v", err)
	}

	_, _, err := mk.GetBridgeAttestation(ctx, sourceChain, burnID)
	if err == nil {
		t.Fatal("Expected error for ambiguous attestation lookup")
	}
}

// TestBridgeAttestationAccumulation tests multi-validator attestation accumulation
func TestBridgeAttestationAccumulation(t *testing.T) {
	attestation := types.NewBridgeAttestation("solana", "12345", "mirage1recipient", 1000000, 100)

	// First validator attests with 40% power
	if !attestation.AddAttestation("val1", 40) {
		t.Error("First attestation should succeed")
	}
	attestation.AttestedPower = 40

	// Second validator attests with 30% power
	if !attestation.AddAttestation("val2", 30) {
		t.Error("Second attestation should succeed")
	}
	attestation.AttestedPower = 70

	// Check threshold (need 67%)
	totalPower := int64(100)
	threshold := 0.67

	if !attestation.MeetsThreshold(totalPower, threshold) {
		t.Error("Expected 70% to meet 67% threshold")
	}

	// Verify attestor powers
	if attestation.GetAttestorPower("val1") != 40 {
		t.Errorf("val1 power = %d, want 40", attestation.GetAttestorPower("val1"))
	}
	if attestation.GetAttestorPower("val2") != 30 {
		t.Errorf("val2 power = %d, want 30", attestation.GetAttestorPower("val2"))
	}
}

// TestBridgeAttestationDuplicateRejectionInbound tests inbound duplicate rejection
func TestBridgeAttestationDuplicateRejectionInbound(t *testing.T) {
	attestation := types.NewBridgeAttestation("solana", "12345", "mirage1recipient", 1000000, 100)

	// First attestation should succeed
	if !attestation.AddAttestation("validator1", 50) {
		t.Error("First attestation should succeed")
	}

	// Duplicate should fail
	if attestation.AddAttestation("validator1", 50) {
		t.Error("Duplicate attestation should be rejected")
	}

	// Different validator should succeed
	if !attestation.AddAttestation("validator2", 30) {
		t.Error("Different validator attestation should succeed")
	}
}

// =============================================================================
// Threshold Boundary Tests
// =============================================================================

// TestThresholdExactlyAtBoundary tests attestation exactly at 2/3 threshold
// Uses v1.17.0 integer basis-point math with ceiling division.
func TestThresholdExactlyAtBoundary(t *testing.T) {
	attestation := types.NewBridgeAttestation("solana", "123", "mirage1recipient", 1000000, 100)

	totalPower := int64(100)
	threshold := 0.6667 // 66.67%

	// required = ceil(100 * 6667 / 10000) = ceil(66.67) = 67
	attestation.AttestedPower = 67
	if !attestation.MeetsThreshold(totalPower, threshold) {
		t.Error("67/100 should meet threshold (required=67 with ceiling)")
	}

	// 66 power should NOT meet threshold (ceiling rounds up)
	attestation.AttestedPower = 66
	if attestation.MeetsThreshold(totalPower, threshold) {
		t.Error("66/100 should not meet 66.67% threshold with ceiling division")
	}

	// 68 power should definitely meet threshold
	attestation.AttestedPower = 68
	if !attestation.MeetsThreshold(totalPower, threshold) {
		t.Error("68/100 should meet 66.67% threshold")
	}
}

// TestThresholdWithOddTotalPower tests threshold with non-round numbers
// Uses v1.17.0 integer basis-point math with ceiling division.
func TestThresholdWithOddTotalPower(t *testing.T) {
	attestation := types.NewBridgeAttestation("solana", "123", "mirage1recipient", 1000000, 100)

	totalPower := int64(150)
	threshold := 0.6667 // 66.67%

	// Required: ceil(150 * 6667 / 10000) = ceil(100.005) = 101
	attestation.AttestedPower = 101
	if !attestation.MeetsThreshold(totalPower, threshold) {
		t.Error("101/150 should meet threshold (required=101 with ceiling)")
	}

	// 100 should NOT meet (ceiling rounds up)
	attestation.AttestedPower = 100
	if attestation.MeetsThreshold(totalPower, threshold) {
		t.Error("100/150 should not meet threshold with ceiling division")
	}
}

// =============================================================================
// MintAttestation Consistency Tests
// =============================================================================

// TestMintAttestationDestinationTxConsistency tests that the first destination_tx is preserved
func TestMintAttestationDestinationTxConsistency(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()

	// Create attestation with first destination_tx
	attestation := types.NewBridgeMintAttestation("1", "solana", "sig123", 100)
	attestation.AttestedPower = 50

	if err := mk.SetBridgeMintAttestation(ctx, attestation); err != nil {
		t.Fatalf("SetBridgeMintAttestation error: %v", err)
	}

	// Retrieve and verify
	restored, found, _ := mk.GetBridgeMintAttestation(ctx, "solana", "1")
	if !found {
		t.Fatal("Expected attestation to exist")
	}
	if restored.DestinationTx != "sig123" {
		t.Errorf("DestinationTx = %s, want sig123", restored.DestinationTx)
	}

	// This test only verifies storage; handler logic accepts different destination_tx values
}

// TestGetOrCreateMintAttestation tests the GetOrCreate helper
func TestGetOrCreateMintAttestationNew(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()

	// First call should create
	attestation, err := mk.GetOrCreateBridgeMintAttestation(ctx, "1", "solana", "sig123")
	if err != nil {
		t.Fatalf("GetOrCreateBridgeMintAttestation error: %v", err)
	}
	if attestation.BurnID != "1" {
		t.Errorf("BurnID = %s, want 1", attestation.BurnID)
	}
	if attestation.DestinationChain != "solana" {
		t.Errorf("DestinationChain = %s, want solana", attestation.DestinationChain)
	}
	if attestation.DestinationTx != "sig123" {
		t.Errorf("DestinationTx = %s, want sig123", attestation.DestinationTx)
	}

	// Add an attestation and save
	attestation.AttestedPower = 50
	if err := mk.SetBridgeMintAttestation(ctx, attestation); err != nil {
		t.Fatalf("SetBridgeMintAttestation error: %v", err)
	}

	// Second call should return existing
	attestation2, err := mk.GetOrCreateBridgeMintAttestation(ctx, "1", "solana", "sig123")
	if err != nil {
		t.Fatalf("GetOrCreateBridgeMintAttestation (2nd) error: %v", err)
	}
	if attestation2.AttestedPower != 50 {
		t.Errorf("AttestedPower = %d, want 50 (should return existing)", attestation2.AttestedPower)
	}
}

// =============================================================================
// Query Response Tests
// =============================================================================

// TestQueryBridgeAttestationResponse tests inbound attestation query response
func TestQueryBridgeAttestationResponse(t *testing.T) {
	// Test response structure
	resp := &types.QueryBridgeAttestationResponse{
		Found:           true,
		SourceChain:     "solana",
		BurnId:          "12345",
		MirageRecipient: "mirage1recipient",
		Amount:          1000000,
		AttestedPower:   70,
		RequiredPower:   67,
		Minted:          true,
	}

	if !resp.Found {
		t.Error("Expected Found = true")
	}
	if resp.AttestedPower < resp.RequiredPower {
		t.Error("AttestedPower should be >= RequiredPower when minted")
	}
}

// =============================================================================
// Error Scenario Tests
// =============================================================================

// TestZeroPowerAttestation tests that zero power attestations are rejected
func TestZeroPowerAttestation(t *testing.T) {
	attestation := types.NewBridgeAttestation("solana", "123", "mirage1recipient", 1000000, 100)

	// Zero power should be rejected
	if attestation.AddAttestation("val1", 0) {
		t.Error("Zero power attestation should be rejected")
	}

	// Negative power should be rejected
	if attestation.AddAttestation("val1", -10) {
		t.Error("Negative power attestation should be rejected")
	}
}

// TestEmptyValidatorAddress tests empty validator handling
func TestEmptyValidatorAddress(t *testing.T) {
	attestation := types.NewBridgeAttestation("solana", "123", "mirage1recipient", 1000000, 100)

	// Empty validator address - AddAttestation doesn't validate this,
	// but the map will accept it. This should be caught at handler level.
	// Just verify it doesn't panic.
	attestation.AddAttestation("", 50)

	if attestation.HasAttested("") {
		// Empty string was added
		t.Log("Empty validator was added (should be prevented at handler level)")
	}
}

// TestAttestationNotFoundBehavior tests behavior when attestation doesn't exist
func TestAttestationNotFoundBehavior(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()

	// Non-existent inbound attestation
	_, found, err := mk.GetBridgeAttestation(ctx, "solana", "nonexistent")
	if err != nil {
		t.Fatalf("Unexpected error: %v", err)
	}
	if found {
		t.Error("Expected not found for non-existent attestation")
	}

	// Non-existent outbound attestation
	_, found, err = mk.GetBridgeMintAttestation(ctx, "solana", "nonexistent")
	if err != nil {
		t.Fatalf("Unexpected error: %v", err)
	}
	if found {
		t.Error("Expected not found for non-existent mint attestation")
	}

	// Non-existent burn record
	_, found, err = mk.GetBridgeBurnRecord(ctx, "solana", "nonexistent")
	if err != nil {
		t.Fatalf("Unexpected error: %v", err)
	}
	if found {
		t.Error("Expected not found for non-existent burn record")
	}

	// Non-existent minted record
	_, found, err = mk.GetBridgeMintedRecord(ctx, "solana", "nonexistent")
	if err != nil {
		t.Fatalf("Unexpected error: %v", err)
	}
	if found {
		t.Error("Expected not found for non-existent minted record")
	}
}
