package solana

import (
	"bytes"
	"encoding/hex"
	"strings"
	"testing"
)

func TestDecodeBurnHash(t *testing.T) {
	valid := strings.Repeat("a", 64)
	hash, err := decodeBurnHash(valid)
	if err != nil {
		t.Fatalf("decodeBurnHash failed: %v", err)
	}
	expected, _ := hex.DecodeString(valid)
	if !bytes.Equal(hash[:], expected) {
		t.Fatalf("decoded hash mismatch: got %x, want %x", hash[:], expected)
	}

	// Trimming should be applied
	trimmed, err := decodeBurnHash("  " + valid + "  ")
	if err != nil {
		t.Fatalf("decodeBurnHash failed on trimmed input: %v", err)
	}
	if trimmed != hash {
		t.Fatalf("trimmed hash mismatch: got %x, want %x", trimmed, hash)
	}

	if _, err := decodeBurnHash("abc123"); err == nil {
		t.Fatal("expected error for short burn_id, got nil")
	}
	if _, err := decodeBurnHash(strings.Repeat("g", 64)); err == nil {
		t.Fatal("expected error for non-hex burn_id, got nil")
	}
}
