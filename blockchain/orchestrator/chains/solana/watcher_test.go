package solana

import (
	"encoding/binary"
	"fmt"
	"testing"
)

func TestParseBridgeStateLastSequence(t *testing.T) {
	// Test parsing of last_sequence from bridge_state account data
	// BridgeState layout (Anchor):
	//   8 bytes: discriminator
	//   1 byte:  bump
	//   32 bytes: authority
	//   8 bytes: last_sequence
	// Total offset for last_sequence: 8 + 1 + 32 = 41

	tests := []struct {
		name         string
		data         []byte
		expectedSeq  uint64
		expectError  bool
	}{
		{
			name:         "valid data with seq=100",
			data:         makeTestBridgeStateData(100),
			expectedSeq:  100,
			expectError:  false,
		},
		{
			name:         "valid data with seq=0",
			data:         makeTestBridgeStateData(0),
			expectedSeq:  0,
			expectError:  false,
		},
		{
			name:         "valid data with max seq",
			data:         makeTestBridgeStateData(^uint64(0)),
			expectedSeq:  ^uint64(0),
			expectError:  false,
		},
		{
			name:         "data too short",
			data:         make([]byte, 40), // Need at least 49 bytes
			expectedSeq:  0,
			expectError:  true,
		},
		{
			name:         "empty data",
			data:         []byte{},
			expectedSeq:  0,
			expectError:  true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			seq, err := parseBridgeStateLastSequence(tt.data)
			if tt.expectError {
				if err == nil {
					t.Errorf("expected error but got none")
				}
				return
			}
			if err != nil {
				t.Errorf("unexpected error: %v", err)
				return
			}
			if seq != tt.expectedSeq {
				t.Errorf("got seq=%d, want seq=%d", seq, tt.expectedSeq)
			}
		})
	}
}

// makeTestBridgeStateData creates test data for BridgeState account
func makeTestBridgeStateData(lastSeq uint64) []byte {
	// Total size: 8 (disc) + 1 (bump) + 32 (authority) + 8 (last_seq) + 128 (bitmap) = 177
	data := make([]byte, 177)
	// Discriminator (8 bytes) - arbitrary
	copy(data[0:8], []byte{0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08})
	// Bump (1 byte)
	data[8] = 255
	// Authority (32 bytes) - arbitrary pubkey
	for i := 9; i < 41; i++ {
		data[i] = byte(i)
	}
	// Last sequence (8 bytes, little endian)
	binary.LittleEndian.PutUint64(data[41:49], lastSeq)
	// Bitmap (128 bytes) - zeros
	return data
}

// parseBridgeStateLastSequence extracts last_sequence from raw account data
// This is a testable version of the parsing logic
func parseBridgeStateLastSequence(data []byte) (uint64, error) {
	if len(data) < 49 {
		return 0, fmt.Errorf("bridge state data too short: %d bytes", len(data))
	}
	return binary.LittleEndian.Uint64(data[41:49]), nil
}

func TestEventDiscriminator(t *testing.T) {
	// Verify discriminator calculation is deterministic
	disc1 := eventDiscriminator("BurnInitiated")
	disc2 := eventDiscriminator("BurnInitiated")
	
	if disc1 != disc2 {
		t.Errorf("discriminator not deterministic: %v != %v", disc1, disc2)
	}
	
	// Different names should produce different discriminators
	disc3 := eventDiscriminator("MintCompleted")
	if disc1 == disc3 {
		t.Errorf("different events should have different discriminators")
	}
}

func TestInstructionDiscriminator(t *testing.T) {
	// Verify instruction discriminator calculation
	disc1 := instructionDiscriminator("mint")
	disc2 := instructionDiscriminator("mint")
	
	if disc1 != disc2 {
		t.Errorf("discriminator not deterministic: %v != %v", disc1, disc2)
	}
	
	// Different instructions should produce different discriminators
	disc3 := instructionDiscriminator("burn")
	if disc1 == disc3 {
		t.Errorf("different instructions should have different discriminators")
	}
}
