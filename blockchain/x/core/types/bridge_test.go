package types

import (
	"bytes"
	"reflect"
	"strings"
	"testing"
)

func TestBridgeBurnRecordMarshalUnmarshal(t *testing.T) {
	original := &BridgeBurnRecord{
		BurnID:             "abc123def456",
		Owner:              "mirage1abc123",
		DestinationChain:   "solana",
		DestinationAddress: "SoLANaAddress123",
		Amount:             1000000,
		BridgeFee:          10000,
		Sequence:           42,
		CreatedAt:          12345,
	}

	data, err := original.Marshal()
	if err != nil {
		t.Fatalf("Marshal failed: %v", err)
	}

	restored, err := UnmarshalBridgeBurnRecord(data)
	if err != nil {
		t.Fatalf("Unmarshal failed: %v", err)
	}

	if restored.BurnID != original.BurnID {
		t.Errorf("BurnID mismatch: got %s, want %s", restored.BurnID, original.BurnID)
	}
	if restored.Owner != original.Owner {
		t.Errorf("Owner mismatch: got %s, want %s", restored.Owner, original.Owner)
	}
	if restored.DestinationChain != original.DestinationChain {
		t.Errorf("DestinationChain mismatch: got %s, want %s", restored.DestinationChain, original.DestinationChain)
	}
	if restored.DestinationAddress != original.DestinationAddress {
		t.Errorf("DestinationAddress mismatch: got %s, want %s", restored.DestinationAddress, original.DestinationAddress)
	}
	if restored.Amount != original.Amount {
		t.Errorf("Amount mismatch: got %d, want %d", restored.Amount, original.Amount)
	}
	if restored.BridgeFee != original.BridgeFee {
		t.Errorf("BridgeFee mismatch: got %d, want %d", restored.BridgeFee, original.BridgeFee)
	}
	if restored.Sequence != original.Sequence {
		t.Errorf("Sequence mismatch: got %d, want %d", restored.Sequence, original.Sequence)
	}
	if restored.CreatedAt != original.CreatedAt {
		t.Errorf("CreatedAt mismatch: got %d, want %d", restored.CreatedAt, original.CreatedAt)
	}
}

func TestBridgeMintedRecordMarshalUnmarshal(t *testing.T) {
	original := &BridgeMintedRecord{
		BurnID:           "abc123def456",
		DestinationChain: "solana",
		DestinationTx:    "SolanaSignature123ABC",
		CreatedAt:        12345,
	}

	data, err := original.Marshal()
	if err != nil {
		t.Fatalf("Marshal failed: %v", err)
	}

	restored, err := UnmarshalBridgeMintedRecord(data)
	if err != nil {
		t.Fatalf("Unmarshal failed: %v", err)
	}

	if restored.BurnID != original.BurnID {
		t.Errorf("BurnID mismatch: got %s, want %s", restored.BurnID, original.BurnID)
	}
	if restored.DestinationChain != original.DestinationChain {
		t.Errorf("DestinationChain mismatch: got %s, want %s", restored.DestinationChain, original.DestinationChain)
	}
	if restored.DestinationTx != original.DestinationTx {
		t.Errorf("DestinationTx mismatch: got %s, want %s", restored.DestinationTx, original.DestinationTx)
	}
	if restored.CreatedAt != original.CreatedAt {
		t.Errorf("CreatedAt mismatch: got %d, want %d", restored.CreatedAt, original.CreatedAt)
	}
}

func TestBridgeMintedRecordUnmarshalInvalid(t *testing.T) {
	_, err := UnmarshalBridgeMintedRecord([]byte("not valid json"))
	if err == nil {
		t.Error("Expected error for invalid JSON, got nil")
	}
}

func TestBridgeMintAttestationMarshalUnmarshal(t *testing.T) {
	original := NewBridgeMintAttestation("1", "solana", "SolanaSignature123", 12345)
	original.AddAttestation("val1", 1000)
	original.AddAttestation("val2", 2000)
	original.Confirmed = true
	original.ConfirmedBy = "mirage1qqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqp5h6t2"
	original.FeeDistributed = true

	data, err := original.Marshal()
	if err != nil {
		t.Fatalf("Marshal failed: %v", err)
	}

	restored, err := UnmarshalBridgeMintAttestation(data)
	if err != nil {
		t.Fatalf("Unmarshal failed: %v", err)
	}

	if restored.BurnID != original.BurnID {
		t.Errorf("BurnID mismatch: got %s, want %s", restored.BurnID, original.BurnID)
	}
	if restored.DestinationChain != original.DestinationChain {
		t.Errorf("DestinationChain mismatch: got %s, want %s", restored.DestinationChain, original.DestinationChain)
	}
	if restored.DestinationTx != original.DestinationTx {
		t.Errorf("DestinationTx mismatch: got %s, want %s", restored.DestinationTx, original.DestinationTx)
	}
	if restored.AttestedPower != original.AttestedPower {
		t.Errorf("AttestedPower mismatch: got %d, want %d", restored.AttestedPower, original.AttestedPower)
	}
	if restored.Confirmed != original.Confirmed {
		t.Errorf("Confirmed mismatch: got %v, want %v", restored.Confirmed, original.Confirmed)
	}
	if restored.ConfirmedBy != original.ConfirmedBy {
		t.Errorf("ConfirmedBy mismatch: got %s, want %s", restored.ConfirmedBy, original.ConfirmedBy)
	}
	if restored.FeeDistributed != original.FeeDistributed {
		t.Errorf("FeeDistributed mismatch: got %v, want %v", restored.FeeDistributed, original.FeeDistributed)
	}
	if len(restored.Attestors) != 2 {
		t.Errorf("Attestors count mismatch: got %d, want 2", len(restored.Attestors))
	}
}

func TestBridgeMintAttestationUnmarshalInvalid(t *testing.T) {
	_, err := UnmarshalBridgeMintAttestation([]byte("not valid json"))
	if err == nil {
		t.Error("Expected error for invalid JSON, got nil")
	}
}

func TestBridgeMintAttestationUnmarshalNilAttestors(t *testing.T) {
	// Test that Attestors map is initialized even if JSON has null
	data := []byte(`{"burn_id":"1","destination_chain":"solana","attestors":null}`)
	restored, err := UnmarshalBridgeMintAttestation(data)
	if err != nil {
		t.Fatalf("Unmarshal failed: %v", err)
	}
	if restored.Attestors == nil {
		t.Error("Expected Attestors map to be initialized, got nil")
	}
}

func TestBridgeMintAttestationKey(t *testing.T) {
	tests := []struct {
		destChain string
		burnID    string
		expected  string
	}{
		{"solana", "1", "bridge_mint_attestations/solana/1"},
		{"solana", "42", "bridge_mint_attestations/solana/42"},
		{"", "1", "bridge_mint_attestations//1"},
	}

	for _, tc := range tests {
		key := BridgeMintAttestationKey(tc.destChain, tc.burnID)
		if string(key) != tc.expected {
			t.Errorf("BridgeMintAttestationKey(%s, %s) = %s, want %s", tc.destChain, tc.burnID, string(key), tc.expected)
		}
	}
}

func TestBridgeMintFeePendingKey(t *testing.T) {
	key := BridgeMintFeePendingKey("solana", "42")
	expected := "bridge_mint_fee_pending/solana/42"
	if string(key) != expected {
		t.Errorf("BridgeMintFeePendingKey = %s, want %s", string(key), expected)
	}
}

func TestMsgBridgeAttestMintedMirageTxHashTag(t *testing.T) {
	field, ok := reflect.TypeOf(MsgBridgeAttestMinted{}).FieldByName("MirageTxHash")
	if !ok {
		t.Fatal("MsgBridgeAttestMinted missing MirageTxHash field")
	}
	tag := field.Tag.Get("protobuf")
	if !strings.Contains(tag, "bytes,5") {
		t.Fatalf("MirageTxHash protobuf tag = %q, want field number 5", tag)
	}
	if !strings.Contains(tag, "name=mirage_tx_hash") {
		t.Fatalf("MirageTxHash protobuf tag = %q, want name=mirage_tx_hash", tag)
	}
}

func TestMsgBridgeAttestMintedMarshalIncludesTag5(t *testing.T) {
	msg := &MsgBridgeAttestMinted{
		MirageTxHash: "deadbeef",
	}
	bz, err := msg.Marshal()
	if err != nil {
		t.Fatalf("Marshal failed: %v", err)
	}
	expected := append([]byte{0x2a, 0x08}, []byte("deadbeef")...)
	if !bytes.Equal(bz, expected) {
		t.Fatalf("unexpected marshal bytes: got %x, want %x", bz, expected)
	}
}

func TestBridgeBurnRecordUnmarshalInvalid(t *testing.T) {
	_, err := UnmarshalBridgeBurnRecord([]byte("not valid json"))
	if err == nil {
		t.Error("Expected error for invalid JSON, got nil")
	}
}

func TestBridgeBurnKey(t *testing.T) {
	tests := []struct {
		destChain string
		burnID    string
		expected  string
	}{
		{"solana", "1", "bridge_burns/solana/1"},
		{"ethereum", "42", "bridge_burns/ethereum/42"},
		{"solana", "", "bridge_burns/solana/"},
	}

	for _, tc := range tests {
		key := BridgeBurnKey(tc.destChain, tc.burnID)
		if string(key) != tc.expected {
			t.Errorf("BridgeBurnKey(%q, %q) = %q, want %q", tc.destChain, tc.burnID, string(key), tc.expected)
		}
	}
}

func TestBridgeMintedKey(t *testing.T) {
	tests := []struct {
		destChain string
		burnID    string
		expected  string
	}{
		{"solana", "1", "bridge_mints/solana/1"},
		{"ethereum", "42", "bridge_mints/ethereum/42"},
		{"solana", "", "bridge_mints/solana/"},
	}

	for _, tc := range tests {
		key := BridgeMintedKey(tc.destChain, tc.burnID)
		if string(key) != tc.expected {
			t.Errorf("BridgeMintedKey(%q, %q) = %q, want %q", tc.destChain, tc.burnID, string(key), tc.expected)
		}
	}
}

func TestBridgeAttestationKey(t *testing.T) {
	tests := []struct {
		sourceChain string
		burnID      string
		expected    string
	}{
		{"solana", "abc123", "bridge_attestations/solana/abc123"},
		{"ethereum", "def456", "bridge_attestations/ethereum/def456"},
		{"", "", "bridge_attestations//"},
	}

	for _, tc := range tests {
		key := BridgeAttestationKey(tc.sourceChain, tc.burnID)
		if string(key) != tc.expected {
			t.Errorf("BridgeAttestationKey(%q, %q) = %q, want %q", tc.sourceChain, tc.burnID, string(key), tc.expected)
		}
	}
}

func TestValidateBridgeDestinationAddress(t *testing.T) {
	tests := []struct {
		name      string
		chainID   string
		address   string
		wantErr   bool
		errSubstr string
	}{
		{
			name:    "valid solana address",
			chainID: "solana",
			address: "7EYnhQoR9YM3N7UoaKRoA44Uy8JeaZV3qyouov87awMs",
			wantErr: false,
		},
		{
			name:      "empty address",
			chainID:   "solana",
			address:   "",
			wantErr:   true,
			errSubstr: "cannot be empty",
		},
		{
			name:      "solana address too short",
			chainID:   "solana",
			address:   "abc",
			wantErr:   true,
			errSubstr: "invalid solana address length",
		},
		{
			name:      "solana address with invalid char 0",
			chainID:   "solana",
			address:   "7EYnhQoR9YM3N7UoaKRoA44Uy8JeaZV30youov87awMs",
			wantErr:   true,
			errSubstr: "invalid character",
		},
		{
			name:      "solana address with invalid char O",
			chainID:   "solana",
			address:   "7EYnhQoR9YM3N7UoaKROA44Uy8JeaZV3qyouov87awMs",
			wantErr:   true,
			errSubstr: "invalid character",
		},
		{
			name:      "solana address with invalid char I",
			chainID:   "solana",
			address:   "7EYnhQoR9YM3N7UoaKRoA44Uy8IeaZV3qyouov87awMs",
			wantErr:   true,
			errSubstr: "invalid character",
		},
		{
			name:      "solana address with invalid char l",
			chainID:   "solana",
			address:   "7EYnhQoR9YM3N7UoaKRoA44Uy8JeaZVlqyouov87awMs",
			wantErr:   true,
			errSubstr: "invalid character",
		},
		{
			name:    "unknown chain with valid address",
			chainID: "unknown",
			address: "someaddress",
			wantErr: false,
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			err := ValidateBridgeDestinationAddress(tc.chainID, tc.address)
			if tc.wantErr {
				if err == nil {
					t.Errorf("expected error containing %q, got nil", tc.errSubstr)
				} else if tc.errSubstr != "" && !contains(err.Error(), tc.errSubstr) {
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

func TestIsBase58Char(t *testing.T) {
	// Valid base58 chars
	validChars := "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
	for _, c := range validChars {
		if !isBase58Char(c) {
			t.Errorf("isBase58Char(%q) = false, want true", c)
		}
	}

	// Invalid base58 chars (0, O, I, l)
	invalidChars := "0OIl"
	for _, c := range invalidChars {
		if isBase58Char(c) {
			t.Errorf("isBase58Char(%q) = true, want false", c)
		}
	}
}

func TestBridgeAttestationMeetsThreshold(t *testing.T) {
	tests := []struct {
		name          string
		attestedPower int64
		totalPower    int64
		threshold     uint64 // basis points
		expected      bool
	}{
		{
			name:          "exactly at threshold",
			attestedPower: 6667,
			totalPower:    10000,
			threshold:     6667,
			expected:      true,
		},
		{
			name:          "above threshold",
			attestedPower: 7000,
			totalPower:    10000,
			threshold:     6667,
			expected:      true,
		},
		{
			name:          "below threshold",
			attestedPower: 6000,
			totalPower:    10000,
			threshold:     6667,
			expected:      false,
		},
		{
			name:          "zero total power",
			attestedPower: 100,
			totalPower:    0,
			threshold:     6667,
			expected:      false,
		},
		{
			name:          "negative total power",
			attestedPower: 100,
			totalPower:    -100,
			threshold:     6667,
			expected:      false,
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			a := &BridgeAttestation{AttestedPower: tc.attestedPower}
			result := a.MeetsThreshold(tc.totalPower, tc.threshold)
			if result != tc.expected {
				t.Errorf("MeetsThreshold(%d, %d) = %v, want %v",
					tc.totalPower, tc.threshold, result, tc.expected)
			}
		})
	}
}

func TestRequiredPower(t *testing.T) {
	tests := []struct {
		name       string
		totalPower int64
		threshold  uint64
		expected   int64
	}{
		{
			name:       "standard case",
			totalPower: 10000,
			threshold:  6667,
			expected:   6667,
		},
		{
			name:       "50% threshold",
			totalPower: 10000,
			threshold:  5000,
			expected:   5000,
		},
		{
			name:       "zero total power",
			totalPower: 0,
			threshold:  6667,
			expected:   0,
		},
		{
			name:       "negative total power",
			totalPower: -100,
			threshold:  6667,
			expected:   0,
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			result := RequiredPower(tc.totalPower, tc.threshold)
			if result != tc.expected {
				t.Errorf("RequiredPower(%d, %d) = %d, want %d",
					tc.totalPower, tc.threshold, result, tc.expected)
			}
		})
	}
}

func TestBridgeAttestationAddAttestation(t *testing.T) {
	a := NewBridgeAttestation("solana", "burn123", "mirage1recipient", 1000000, 100)

	// First attestation should succeed
	if !a.AddAttestation("validator1", 100) {
		t.Error("First attestation should return true")
	}
	if a.AttestedPower != 100 {
		t.Errorf("AttestedPower = %d, want 100", a.AttestedPower)
	}

	// Duplicate attestation should fail
	if a.AddAttestation("validator1", 100) {
		t.Error("Duplicate attestation should return false")
	}
	if a.AttestedPower != 100 {
		t.Errorf("AttestedPower should not change on duplicate, got %d", a.AttestedPower)
	}

	// Second different validator should succeed
	if !a.AddAttestation("validator2", 50) {
		t.Error("Second validator attestation should return true")
	}
	if a.AttestedPower != 150 {
		t.Errorf("AttestedPower = %d, want 150", a.AttestedPower)
	}
}

func TestBridgeAttestationHasAttested(t *testing.T) {
	a := NewBridgeAttestation("solana", "burn123", "mirage1recipient", 1000000, 100)

	if a.HasAttested("validator1") {
		t.Error("HasAttested should return false before attestation")
	}

	a.AddAttestation("validator1", 100)

	if !a.HasAttested("validator1") {
		t.Error("HasAttested should return true after attestation")
	}

	if a.HasAttested("validator2") {
		t.Error("HasAttested should return false for different validator")
	}
}

func TestBridgeAttestationAttestorList(t *testing.T) {
	a := NewBridgeAttestation("solana", "burn123", "mirage1recipient", 1000000, 100)

	a.AddAttestation("validator1", 100)
	a.AddAttestation("validator2", 50)
	a.AddAttestation("validator3", 75)

	list := a.AttestorList()
	if len(list) != 3 {
		t.Errorf("AttestorList length = %d, want 3", len(list))
	}

	// Check all validators are in the list
	validators := map[string]bool{"validator1": false, "validator2": false, "validator3": false}
	for _, v := range list {
		validators[v] = true
	}
	for v, found := range validators {
		if !found {
			t.Errorf("Validator %s not found in AttestorList", v)
		}
	}
}

func TestBridgeAttestationGetAttestorPower(t *testing.T) {
	a := NewBridgeAttestation("solana", "burn123", "mirage1recipient", 1000000, 100)

	// Before attestation, power should be 0
	if power := a.GetAttestorPower("validator1"); power != 0 {
		t.Errorf("GetAttestorPower before attestation = %d, want 0", power)
	}

	a.AddAttestation("validator1", 100)
	a.AddAttestation("validator2", 50)
	a.AddAttestation("validator3", 75)

	// Verify each validator's stored power
	if power := a.GetAttestorPower("validator1"); power != 100 {
		t.Errorf("GetAttestorPower(validator1) = %d, want 100", power)
	}
	if power := a.GetAttestorPower("validator2"); power != 50 {
		t.Errorf("GetAttestorPower(validator2) = %d, want 50", power)
	}
	if power := a.GetAttestorPower("validator3"); power != 75 {
		t.Errorf("GetAttestorPower(validator3) = %d, want 75", power)
	}

	// Unknown validator should return 0
	if power := a.GetAttestorPower("unknown"); power != 0 {
		t.Errorf("GetAttestorPower(unknown) = %d, want 0", power)
	}
}

func TestBridgeMintAttestationGetAttestorPower(t *testing.T) {
	a := NewBridgeMintAttestation("1", "solana", "SolanaSignature123", 12345)

	// Before attestation, power should be 0
	if power := a.GetAttestorPower("validator1"); power != 0 {
		t.Errorf("GetAttestorPower before attestation = %d, want 0", power)
	}

	a.AddAttestation("validator1", 300)
	a.AddAttestation("validator2", 250)
	a.AddAttestation("validator3", 200)

	// Verify each validator's stored power
	if power := a.GetAttestorPower("validator1"); power != 300 {
		t.Errorf("GetAttestorPower(validator1) = %d, want 300", power)
	}
	if power := a.GetAttestorPower("validator2"); power != 250 {
		t.Errorf("GetAttestorPower(validator2) = %d, want 250", power)
	}
	if power := a.GetAttestorPower("validator3"); power != 200 {
		t.Errorf("GetAttestorPower(validator3) = %d, want 200", power)
	}

	// Verify total attested power
	if a.AttestedPower != 750 {
		t.Errorf("AttestedPower = %d, want 750", a.AttestedPower)
	}
}

func TestProportionalFeeDistribution(t *testing.T) {
	// Test the math for proportional fee distribution
	// Simulates: 3 validators with powers 300, 250, 200 = 750 total
	// Fee of 1000 should be split as: 400, 333, 266 = 999 (1 dust)
	a := NewBridgeMintAttestation("1", "solana", "SolanaSignature123", 12345)
	a.AddAttestation("validator1", 300)
	a.AddAttestation("validator2", 250)
	a.AddAttestation("validator3", 200)

	totalFee := uint64(1000)
	var distributed uint64 = 0
	expectedShares := map[string]uint64{
		"validator1": 400, // 1000 * 300 / 750 = 400
		"validator2": 333, // 1000 * 250 / 750 = 333
		"validator3": 266, // 1000 * 200 / 750 = 266
	}

	for valAddr, power := range a.Attestors {
		share := totalFee * uint64(power) / uint64(a.AttestedPower)
		if share != expectedShares[valAddr] {
			t.Errorf("Share for %s = %d, want %d", valAddr, share, expectedShares[valAddr])
		}
		distributed += share
	}

	// Should have 1 dust remaining (1000 - 999 = 1)
	dust := totalFee - distributed
	if dust != 1 {
		t.Errorf("Dust = %d, want 1", dust)
	}
}

func TestValidateBridgeChain(t *testing.T) {
	chains := []*BridgeChainConfig{
		{ChainId: "solana", Enabled: true, Fee: 100000},
		{ChainId: "ethereum", Enabled: false, Fee: 200000},
	}

	tests := []struct {
		name      string
		chainID   string
		wantErr   bool
		errSubstr string
	}{
		{
			name:    "valid enabled chain",
			chainID: "solana",
			wantErr: false,
		},
		{
			name:      "disabled chain",
			chainID:   "ethereum",
			wantErr:   true,
			errSubstr: "disabled",
		},
		{
			name:      "unknown chain",
			chainID:   "unknown",
			wantErr:   true,
			errSubstr: "unknown bridge chain",
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			config, err := ValidateBridgeChain(tc.chainID, chains)
			if tc.wantErr {
				if err == nil {
					t.Errorf("expected error containing %q, got nil", tc.errSubstr)
				} else if !contains(err.Error(), tc.errSubstr) {
					t.Errorf("expected error containing %q, got %q", tc.errSubstr, err.Error())
				}
			} else {
				if err != nil {
					t.Errorf("unexpected error: %v", err)
				}
				if config == nil {
					t.Error("expected non-nil config")
				}
			}
		})
	}
}

// contains checks if substr is in s
func contains(s, substr string) bool {
	return len(s) >= len(substr) && (s == substr || len(substr) == 0 ||
		(len(s) > 0 && len(substr) > 0 && findSubstring(s, substr)))
}

func findSubstring(s, substr string) bool {
	for i := 0; i <= len(s)-len(substr); i++ {
		if s[i:i+len(substr)] == substr {
			return true
		}
	}
	return false
}
