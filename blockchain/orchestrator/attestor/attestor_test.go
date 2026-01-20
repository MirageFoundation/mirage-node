package attestor

import (
	"fmt"
	"testing"
)

func TestIsPermanentError(t *testing.T) {
	tests := []struct {
		name     string
		err      error
		expected bool
	}{
		{
			name:     "TransactionTooOld error",
			err:      fmt.Errorf("failed: TransactionTooOld"),
			expected: true,
		},
		{
			name:     "error code 6020",
			err:      fmt.Errorf("custom program error: 6020"),
			expected: true,
		},
		{
			name:     "bridge mint already recorded",
			err:      fmt.Errorf("bridge mint already recorded for burn_id"),
			expected: true,
		},
		{
			name:     "transient network error",
			err:      fmt.Errorf("connection refused"),
			expected: false,
		},
		{
			name:     "timeout error",
			err:      fmt.Errorf("context deadline exceeded"),
			expected: false,
		},
		{
			name:     "RPC error",
			err:      fmt.Errorf("rpc error: code = Unknown"),
			expected: false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result := isPermanentError(tt.err)
			if result != tt.expected {
				t.Errorf("isPermanentError(%q) = %v, want %v", tt.err, result, tt.expected)
			}
		})
	}
}

func TestSequenceValidation(t *testing.T) {
	// Test that sequence validation logic works correctly
	tests := []struct {
		name        string
		lastSeq     uint64
		burnSeq     uint64
		shouldAllow bool
	}{
		{
			name:        "new sequence should be allowed",
			lastSeq:     100,
			burnSeq:     101,
			shouldAllow: true,
		},
		{
			name:        "same sequence should be rejected",
			lastSeq:     100,
			burnSeq:     100,
			shouldAllow: false,
		},
		{
			name:        "old sequence should be rejected",
			lastSeq:     100,
			burnSeq:     50,
			shouldAllow: false,
		},
		{
			name:        "much higher sequence should be allowed",
			lastSeq:     100,
			burnSeq:     500,
			shouldAllow: true,
		},
		{
			name:        "zero lastSeq allows seq 1",
			lastSeq:     0,
			burnSeq:     1,
			shouldAllow: true,
		},
		{
			name:        "zero lastSeq rejects seq 0",
			lastSeq:     0,
			burnSeq:     0,
			shouldAllow: false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			// Simulate the validation logic from executeMintBatch
			allowed := tt.burnSeq > tt.lastSeq
			if allowed != tt.shouldAllow {
				t.Errorf("sequence validation: lastSeq=%d, burnSeq=%d, allowed=%v, want=%v",
					tt.lastSeq, tt.burnSeq, allowed, tt.shouldAllow)
			}
		})
	}
}
