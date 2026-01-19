package types

import (
	"encoding/json"
	"fmt"

	sdkmath "cosmossdk.io/math"
)

const (
	// BridgeAttestationsPrefix is the KVStore prefix for bridge attestation records
	// Key format: bridge_attestations/{source_chain}/{burn_id}
	BridgeAttestationsPrefix = "bridge_attestations/"

	// BridgePendingCountKey stores the count of pending (unminted) attestations
	BridgePendingCountKey = "bridge_pending_count"
)

// BridgeAttestation tracks the state of an incoming bridge transfer from an external chain.
// Validators submit attestations, and once the threshold is met, tokens are minted.
type BridgeAttestation struct {
	// SourceChain is the external chain identifier (e.g., "solana", "ethereum")
	SourceChain string `json:"source_chain"`

	// BurnID is the unique identifier of the burn on the external chain (tx hash)
	BurnID string `json:"burn_id"`

	// MirageRecipient is the destination address on Mirage chain
	MirageRecipient string `json:"mirage_recipient"`

	// Amount is the amount to be minted (in umirage)
	Amount uint64 `json:"amount"`

	// Attestors maps validator operator address to whether they've attested
	Attestors map[string]bool `json:"attestors"`

	// AttestedPower is the total voting power that has attested
	AttestedPower int64 `json:"attested_power"`

	// Minted indicates whether tokens have been minted for this attestation
	Minted bool `json:"minted"`

	// CreatedAt is the block height when this attestation was first created
	CreatedAt int64 `json:"created_at"`
}

// NewBridgeAttestation creates a new BridgeAttestation with initialized maps
func NewBridgeAttestation(sourceChain, burnID, mirageRecipient string, amount uint64, createdAt int64) *BridgeAttestation {
	return &BridgeAttestation{
		SourceChain:     sourceChain,
		BurnID:          burnID,
		MirageRecipient: mirageRecipient,
		Amount:          amount,
		Attestors:       make(map[string]bool),
		AttestedPower:   0,
		Minted:          false,
		CreatedAt:       createdAt,
	}
}

// BridgeAttestationKey returns the store key for a bridge attestation
func BridgeAttestationKey(sourceChain, burnID string) []byte {
	return []byte(fmt.Sprintf("%s%s/%s", BridgeAttestationsPrefix, sourceChain, burnID))
}

// HasAttested returns true if the validator has already attested to this burn
func (a *BridgeAttestation) HasAttested(validatorAddr string) bool {
	return a.Attestors[validatorAddr]
}

// AddAttestation records a validator's attestation and adds their voting power
// Returns true if the attestation is new (validator hadn't attested before)
func (a *BridgeAttestation) AddAttestation(validatorAddr string, votingPower int64) bool {
	if a.Attestors[validatorAddr] {
		return false
	}
	a.Attestors[validatorAddr] = true
	a.AttestedPower += votingPower
	return true
}

// MeetsThreshold returns true if the attested power meets or exceeds the threshold
// threshold is in basis points (e.g., 6667 = 66.67%)
func (a *BridgeAttestation) MeetsThreshold(totalPower int64, thresholdBasisPoints uint64) bool {
	if totalPower <= 0 {
		return false
	}
	// Calculate required power safely: (totalPower * threshold) / 10000
	required := sdkmath.NewInt(totalPower).
		MulRaw(int64(thresholdBasisPoints)).
		QuoRaw(10000)
	return sdkmath.NewInt(a.AttestedPower).GTE(required)
}

// RequiredPower calculates the voting power required to meet the threshold
func RequiredPower(totalPower int64, thresholdBasisPoints uint64) int64 {
	if totalPower <= 0 {
		return 0
	}
	required := sdkmath.NewInt(totalPower).
		MulRaw(int64(thresholdBasisPoints)).
		QuoRaw(10000)
	if !required.IsInt64() {
		return int64(^uint64(0) >> 1) // math.MaxInt64 without importing math
	}
	return required.Int64()
}

// Marshal serializes the attestation to JSON
func (a *BridgeAttestation) Marshal() ([]byte, error) {
	return json.Marshal(a)
}

// UnmarshalBridgeAttestation deserializes JSON to a BridgeAttestation
func UnmarshalBridgeAttestation(data []byte) (*BridgeAttestation, error) {
	var a BridgeAttestation
	if err := json.Unmarshal(data, &a); err != nil {
		return nil, err
	}
	// Ensure map is initialized
	if a.Attestors == nil {
		a.Attestors = make(map[string]bool)
	}
	return &a, nil
}

// AttestorList returns a slice of validator addresses that have attested
func (a *BridgeAttestation) AttestorList() []string {
	result := make([]string, 0, len(a.Attestors))
	for addr := range a.Attestors {
		result = append(result, addr)
	}
	return result
}

// ValidateBridgeChain checks if a chain_id is valid for bridging
func ValidateBridgeChain(chainID string, chains []*BridgeChainConfig) (*BridgeChainConfig, error) {
	for _, chain := range chains {
		if chain.ChainId == chainID {
			if !chain.Enabled {
				return nil, fmt.Errorf("bridge chain %s is disabled", chainID)
			}
			return chain, nil
		}
	}
	return nil, fmt.Errorf("unknown bridge chain: %s", chainID)
}

// ValidateBridgeDestinationAddress validates the destination address format for a given chain
func ValidateBridgeDestinationAddress(chainID, address string) error {
	if address == "" {
		return fmt.Errorf("destination address cannot be empty")
	}

	switch chainID {
	case "solana":
		// Solana addresses are base58-encoded 32-byte public keys
		// Valid base58 alphabet: 123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz
		if len(address) < 32 || len(address) > 44 {
			return fmt.Errorf("invalid solana address length: expected 32-44 chars, got %d", len(address))
		}
		// Check for valid base58 characters (no 0, O, I, l)
		for _, c := range address {
			if !isBase58Char(c) {
				return fmt.Errorf("invalid solana address: contains invalid character '%c'", c)
			}
		}
	default:
		// For unknown chains, just ensure non-empty (already checked above)
		// Additional validation can be added as new chains are supported
	}

	return nil
}

// isBase58Char returns true if the character is valid in base58 encoding
func isBase58Char(c rune) bool {
	// Base58 alphabet: 123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz
	// Excludes: 0, O, I, l
	return (c >= '1' && c <= '9') ||
		(c >= 'A' && c <= 'H') ||
		(c >= 'J' && c <= 'N') ||
		(c >= 'P' && c <= 'Z') ||
		(c >= 'a' && c <= 'k') ||
		(c >= 'm' && c <= 'z')
}
