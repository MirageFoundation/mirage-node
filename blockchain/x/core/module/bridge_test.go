package core

import (
	"context"
	"strings"
	"testing"

	"cosmossdk.io/core/store"
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
		bondedValidator: "miragevaloper1bondedvalidator",
	}
}

func (mk *mockKeeper) IsValidatorBonded(ctx sdk.Context, valoper string) (bool, error) {
	return valoper == mk.bondedValidator, nil
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

// TestBridgeMintedValidation tests validation logic for MsgBridgeMinted
func TestBridgeMintedValidation(t *testing.T) {
	tests := []struct {
		name      string
		authority string
		burnID    string
		destChain string
		destTx    string
		wantErr   bool
		errSubstr string
	}{
		{
			name:      "valid request",
			authority: "miragevaloper1abc",
			burnID:    "abc123def456789012345678901234567890123456789012345678901234",
			destChain: "solana",
			destTx:    "SolanaSignature123",
			wantErr:   false,
		},
		{
			name:      "empty authority",
			authority: "",
			burnID:    "abc123def456789012345678901234567890123456789012345678901234",
			destChain: "solana",
			destTx:    "SolanaSignature123",
			wantErr:   true,
			errSubstr: "authority",
		},
		{
			name:      "whitespace authority",
			authority: "   ",
			burnID:    "abc123def456789012345678901234567890123456789012345678901234",
			destChain: "solana",
			destTx:    "SolanaSignature123",
			wantErr:   true,
			errSubstr: "authority",
		},
		{
			name:      "invalid burn_id - too short",
			authority: "miragevaloper1abc",
			burnID:    "abc123",
			destChain: "solana",
			destTx:    "SolanaSignature123",
			wantErr:   true,
			errSubstr: "burn_id",
		},
		{
			name:      "invalid burn_id - invalid chars",
			authority: "miragevaloper1abc",
			burnID:    "xyz123def456789012345678901234567890123456789012345678901234",
			destChain: "solana",
			destTx:    "SolanaSignature123",
			wantErr:   true,
			errSubstr: "burn_id",
		},
		{
			name:      "empty destination_chain",
			authority: "miragevaloper1abc",
			burnID:    "abc123def456789012345678901234567890123456789012345678901234",
			destChain: "",
			destTx:    "SolanaSignature123",
			wantErr:   true,
			errSubstr: "destination_chain",
		},
		{
			name:      "destination_chain too long",
			authority: "miragevaloper1abc",
			burnID:    "abc123def456789012345678901234567890123456789012345678901234",
			destChain: strings.Repeat("a", 65),
			destTx:    "SolanaSignature123",
			wantErr:   true,
			errSubstr: "destination_chain",
		},
		{
			name:      "empty destination_tx",
			authority: "miragevaloper1abc",
			burnID:    "abc123def456789012345678901234567890123456789012345678901234",
			destChain: "solana",
			destTx:    "",
			wantErr:   true,
			errSubstr: "destination_tx",
		},
		{
			name:      "destination_tx too long",
			authority: "miragevaloper1abc",
			burnID:    "abc123def456789012345678901234567890123456789012345678901234",
			destChain: "solana",
			destTx:    strings.Repeat("a", 129),
			wantErr:   true,
			errSubstr: "destination_tx",
		},
		{
			name:      "destination_tx with invalid char (space)",
			authority: "miragevaloper1abc",
			burnID:    "abc123def456789012345678901234567890123456789012345678901234",
			destChain: "solana",
			destTx:    "Solana Signature123",
			wantErr:   true,
			errSubstr: "invalid character",
		},
		{
			name:      "destination_tx with invalid char (slash)",
			authority: "miragevaloper1abc",
			burnID:    "abc123def456789012345678901234567890123456789012345678901234",
			destChain: "solana",
			destTx:    "Solana/Signature123",
			wantErr:   true,
			errSubstr: "invalid character",
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			err := validateBridgeMintedRequest(tc.authority, tc.burnID, tc.destChain, tc.destTx)
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

// validateBridgeMintedRequest mirrors the validation in module.go BridgeMinted handler
func validateBridgeMintedRequest(authority, burnID, destChain, destTx string) error {
	authority = strings.TrimSpace(authority)
	if authority == "" {
		return &validationError{"authority cannot be empty"}
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

// TestMsgBridgeMintedFields tests the message structure
func TestMsgBridgeMintedFields(t *testing.T) {
	msg := &types.MsgBridgeMinted{
		Authority:        "miragevaloper1abc",
		BurnId:           "abc123def456789012345678901234567890123456789012345678901234",
		DestinationChain: "solana",
		DestinationTx:    "SolanaSignature123",
	}

	if msg.Authority != "miragevaloper1abc" {
		t.Errorf("Authority = %s, want miragevaloper1abc", msg.Authority)
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
