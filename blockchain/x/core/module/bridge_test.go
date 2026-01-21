package core

import (
	"bytes"
	"context"
	"strconv"
	"strings"
	"testing"

	"cosmossdk.io/core/store"
	sdkmath "cosmossdk.io/math"
	"github.com/cosmos/cosmos-sdk/codec"
	codectypes "github.com/cosmos/cosmos-sdk/codec/types"
	sdk "github.com/cosmos/cosmos-sdk/types"
	slashingkeeper "github.com/cosmos/cosmos-sdk/x/slashing/keeper"

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
	return &mockIterator{}, nil
}

func (m *mockKVStore) ReverseIterator(start, end []byte) (store.Iterator, error) {
	return &mockIterator{}, nil
}

type mockIterator struct{}

func (m *mockIterator) Domain() ([]byte, []byte) { return nil, nil }
func (m *mockIterator) Valid() bool              { return false }
func (m *mockIterator) Next()                    {}
func (m *mockIterator) Key() []byte              { return nil }
func (m *mockIterator) Value() []byte            { return nil }
func (m *mockIterator) Close() error             { return nil }
func (m *mockIterator) Error() error             { return nil }

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
	// Create a minimal context for testing
	return sdk.Context{}.WithContext(context.Background()).WithBlockHeight(100)
}

// TestBridgeBurnRecordStorage tests the keeper's burn record storage
func TestBridgeBurnRecordStorage(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()

	burnID := "abc123def456789012345678901234567890123456789012345678901234"

	// Initially should not exist
	_, found, err := mk.GetBridgeBurnRecord(ctx, burnID)
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
		DestinationChain:   "solana",
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
	restored, found, err := mk.GetBridgeBurnRecord(ctx, burnID)
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
}

// TestBridgeMintedRecordStorage tests the keeper's minted record storage
func TestBridgeMintedRecordStorage(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()

	burnID := "abc123def456789012345678901234567890123456789012345678901234"

	// Initially should not exist
	_, found, err := mk.GetBridgeMintedRecord(ctx, burnID)
	if err != nil {
		t.Fatalf("GetBridgeMintedRecord error: %v", err)
	}
	if found {
		t.Error("Expected minted record to not exist initially")
	}

	// Store a record
	record := &types.BridgeMintedRecord{
		BurnID:           burnID,
		DestinationChain: "solana",
		DestinationTx:    "SolanaSignature123",
		CreatedAt:        100,
	}

	err = mk.SetBridgeMintedRecord(ctx, record)
	if err != nil {
		t.Fatalf("SetBridgeMintedRecord error: %v", err)
	}

	// Should now exist
	restored, found, err := mk.GetBridgeMintedRecord(ctx, burnID)
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
	attestation.AddAttestation("miragevaloper1abc", 1000)
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

// TestBridgeMintAttestationMultiValidator tests multi-validator accumulation
func TestBridgeMintAttestationMultiValidator(t *testing.T) {
	attestation := types.NewBridgeMintAttestation("1", "solana", "sig123", 100)

	// First validator attests
	added := attestation.AddAttestation("val1", 1000)
	if !added {
		t.Error("Expected first attestation to be added")
	}
	if attestation.AttestedPower != 1000 {
		t.Errorf("Expected attested power 1000, got %d", attestation.AttestedPower)
	}

	// Second validator attests
	added = attestation.AddAttestation("val2", 2000)
	if !added {
		t.Error("Expected second attestation to be added")
	}
	if attestation.AttestedPower != 3000 {
		t.Errorf("Expected attested power 3000, got %d", attestation.AttestedPower)
	}

	// Third validator attests
	added = attestation.AddAttestation("val3", 500)
	if !added {
		t.Error("Expected third attestation to be added")
	}
	if attestation.AttestedPower != 3500 {
		t.Errorf("Expected attested power 3500, got %d", attestation.AttestedPower)
	}

	// Test zero or negative power should be rejected
	if attestation.AddAttestation("valZero", 0) {
		t.Error("Expected zero power attestation to be rejected")
	}
	if attestation.AddAttestation("valNeg", -100) {
		t.Error("Expected negative power attestation to be rejected")
	}

	// Verify attestor list
	attestors := attestation.AttestorList()
	if len(attestors) != 3 {
		t.Errorf("Expected 3 attestors, got %d", len(attestors))
	}

	// Verify individual attestor powers are stored correctly (for proportional fee distribution)
	if power := attestation.GetAttestorPower("val1"); power != 1000 {
		t.Errorf("GetAttestorPower(val1) = %d, want 1000", power)
	}
	if power := attestation.GetAttestorPower("val2"); power != 2000 {
		t.Errorf("GetAttestorPower(val2) = %d, want 2000", power)
	}
	if power := attestation.GetAttestorPower("val3"); power != 500 {
		t.Errorf("GetAttestorPower(val3) = %d, want 500", power)
	}
}

// TestBridgeMintAttestationProportionalFeeDistribution tests the proportional fee math
func TestBridgeMintAttestationProportionalFeeDistribution(t *testing.T) {
	attestation := types.NewBridgeMintAttestation("1", "solana", "sig123", 100)

	// Three validators with different powers
	attestation.AddAttestation("val1", 300) // 40%
	attestation.AddAttestation("val2", 250) // 33.3%
	attestation.AddAttestation("val3", 200) // 26.7%
	// Total: 750

	if attestation.AttestedPower != 750 {
		t.Fatalf("Expected attested power 750, got %d", attestation.AttestedPower)
	}

	// Simulate fee distribution with 1000 umirage fee
	totalFee := uint64(1000)
	var distributed uint64 = 0
	shares := make(map[string]uint64)

	for valAddr, power := range attestation.Attestors {
		if power <= 0 {
			continue
		}
		share := sdkmath.NewIntFromUint64(totalFee).
			MulRaw(power).
			QuoRaw(attestation.AttestedPower).
			Uint64()
		shares[valAddr] = share
		distributed += share
	}

	// Check proportional shares
	// val1: 1000 * 300 / 750 = 400
	// val2: 1000 * 250 / 750 = 333
	// val3: 1000 * 200 / 750 = 266
	// Total: 999 (1 dust)
	expectedShares := map[string]uint64{
		"val1": 400,
		"val2": 333,
		"val3": 266,
	}

	for val, expected := range expectedShares {
		if shares[val] != expected {
			t.Errorf("Share for %s = %d, want %d", val, shares[val], expected)
		}
	}

	// Check dust
	dust := totalFee - distributed
	if dust != 1 {
		t.Errorf("Dust = %d, want 1", dust)
	}

	// Total distributed + dust should equal total fee
	if distributed+dust != totalFee {
		t.Errorf("distributed(%d) + dust(%d) = %d, want %d", distributed, dust, distributed+dust, totalFee)
	}
}

// TestBridgeMintAttestationDuplicateRejection tests duplicate attestation rejection
func TestBridgeMintAttestationDuplicateRejection(t *testing.T) {
	attestation := types.NewBridgeMintAttestation("1", "solana", "sig123", 100)

	// First attestation from validator
	added := attestation.AddAttestation("val1", 1000)
	if !added {
		t.Error("Expected first attestation to be added")
	}
	if attestation.AttestedPower != 1000 {
		t.Errorf("Expected attested power 1000, got %d", attestation.AttestedPower)
	}

	// Duplicate attestation from same validator
	added = attestation.AddAttestation("val1", 1000)
	if added {
		t.Error("Expected duplicate attestation to be rejected")
	}
	if attestation.AttestedPower != 1000 {
		t.Errorf("Expected attested power to remain 1000, got %d", attestation.AttestedPower)
	}

	// HasAttested should return true for val1
	if !attestation.HasAttested("val1") {
		t.Error("Expected HasAttested to return true for val1")
	}
	// HasAttested should return false for val2
	if attestation.HasAttested("val2") {
		t.Error("Expected HasAttested to return false for val2")
	}
}

// TestBridgeMintAttestationThreshold tests threshold logic
func TestBridgeMintAttestationThreshold(t *testing.T) {
	attestation := types.NewBridgeMintAttestation("1", "solana", "sig123", 100)

	totalPower := int64(10000)
	threshold := uint64(6667) // 66.67%

	// Add 50% power - should not meet threshold
	attestation.AddAttestation("val1", 5000)
	if attestation.MeetsThreshold(totalPower, threshold) {
		t.Error("Expected threshold NOT to be met with 50% power")
	}

	// Add 17% more power (total 67%) - should meet threshold
	attestation.AddAttestation("val2", 1700)
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
	attestation1.AddAttestation("val1", 1000)
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

	// Store with lowercase
	burnIDLower := "abc123def456789012345678901234567890123456789012345678901234"
	record := &types.BridgeMintedRecord{
		BurnID:           burnIDLower,
		DestinationChain: "solana",
		DestinationTx:    "sig123",
		CreatedAt:        100,
	}
	err := mk.SetBridgeMintedRecord(ctx, record)
	if err != nil {
		t.Fatalf("SetBridgeMintedRecord error: %v", err)
	}

	// Should be found with lowercase
	_, found, _ := mk.GetBridgeMintedRecord(ctx, burnIDLower)
	if !found {
		t.Error("Expected to find record with lowercase burn_id")
	}

	// Store should use exact key, so uppercase won't find it
	burnIDUpper := "ABC123DEF456789012345678901234567890123456789012345678901234"
	_, found, _ = mk.GetBridgeMintedRecord(ctx, burnIDUpper)
	if found {
		t.Error("Should not find record with uppercase burn_id (keys are case-sensitive)")
	}

	// After normalization (as done in handler), uppercase should map to lowercase
	normalizedBurnID := strings.ToLower(burnIDUpper)
	if normalizedBurnID != burnIDLower {
		t.Errorf("Normalization failed: got %s, want %s", normalizedBurnID, burnIDLower)
	}
}

// TestGetBridgeMintedQueryResponse tests the query response structure
func TestGetBridgeMintedQueryResponse(t *testing.T) {
	// Test response when minted
	mintedResp := &types.QueryBridgeMintedResponse{
		Minted:           true,
		DestinationChain: "solana",
		DestinationTx:    "SolanaSignature123",
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

	// Test response when not minted
	notMintedResp := &types.QueryBridgeMintedResponse{
		Minted: false,
	}

	if notMintedResp.Minted {
		t.Error("Expected Minted to be false")
	}
	if notMintedResp.DestinationChain != "" {
		t.Errorf("DestinationChain should be empty, got %s", notMintedResp.DestinationChain)
	}
	if notMintedResp.DestinationTx != "" {
		t.Errorf("DestinationTx should be empty, got %s", notMintedResp.DestinationTx)
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
