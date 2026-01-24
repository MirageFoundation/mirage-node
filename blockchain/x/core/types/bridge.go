package types

import (
	"encoding/json"
	"fmt"

	sdkmath "cosmossdk.io/math"
)

const (
	// BridgeAttestationsPrefix is the KVStore prefix for bridge attestation records (inbound)
	// Key format: bridge_attestations/{source_chain}/{burn_id}
	BridgeAttestationsPrefix = "bridge_attestations/"

	// BridgeMintAttestationsPrefix is the KVStore prefix for outbound mint attestation records
	// Key format: bridge_mint_attestations/{destination_chain}/{burn_id}
	BridgeMintAttestationsPrefix = "bridge_mint_attestations/"

	// BridgeMintAttestorsPrefix stores per-validator attestations for outbound mints.
	// Attestors are stored separately to keep the attestation record size stable and
	// avoid gas variance from growing attestor maps.
	// Key format: bridge_mint_attestors/{destination_chain}/{burn_id}/{valoper}
	BridgeMintAttestorsPrefix = "bridge_mint_attestors/"


	// BridgeBurnsPrefix is the KVStore prefix for outbound bridge burn records
	// Key format: bridge_burns/{burn_id}
	BridgeBurnsPrefix = "bridge_burns/"

	// BridgeMintsPrefix is the KVStore prefix for outbound bridge mint confirmations
	// Key format: bridge_mints/{burn_id}
	BridgeMintsPrefix = "bridge_mints/"

	// BridgePendingCountKey stores the count of pending (unminted) attestations
	BridgePendingCountKey = "bridge_pending_count"

	// BridgeSequencePrefix stores the next sequence number for a destination chain
	// Key: bridge_sequence/{dest_chain} -> uint64 (BigEndian)
	BridgeSequencePrefix = "bridge_sequence/"
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

	// Attestors maps validator operator address to their voting power at attestation time.
	// Used for threshold tracking and reporting.
	Attestors map[string]int64 `json:"attestors"`

	// AttestedPower is the total voting power that has attested
	AttestedPower int64 `json:"attested_power"`

	// Minted indicates whether tokens have been minted for this attestation
	Minted bool `json:"minted"`

	// CreatedAt is the block height when this attestation was first created
	CreatedAt int64 `json:"created_at"`
}

// BridgeBurnRecord tracks an outbound bridge burn on Mirage.
type BridgeBurnRecord struct {
	// BurnID is the Mirage burn sequence (string)
	BurnID string `json:"burn_id"`

	// Owner is the Mirage address that initiated the burn
	Owner string `json:"owner"`

	// DestinationChain is the external chain identifier (e.g., "solana")
	DestinationChain string `json:"destination_chain"`

	// DestinationAddress is the recipient address on the destination chain
	DestinationAddress string `json:"destination_address"`

	// Amount is the gross amount (in umirage). Fee is deducted from this amount.
	Amount uint64 `json:"amount"`

	// BridgeFee is the fee deducted from the amount (in umirage)
	BridgeFee uint64 `json:"bridge_fee"`

	// Sequence is the outbound bridge sequence for the destination chain
	Sequence uint64 `json:"sequence"`

	// CreatedAt is the block height when the burn occurred
	CreatedAt int64 `json:"created_at"`
}

// BridgeMintedRecord tracks an outbound bridge mint confirmation (final record after threshold met).
type BridgeMintedRecord struct {
	// BurnID is the Mirage burn sequence number (as string)
	BurnID string `json:"burn_id"`

	// DestinationChain is the external chain identifier (e.g., "solana")
	DestinationChain string `json:"destination_chain"`

	// DestinationTx is the tx hash/signature on the destination chain
	DestinationTx string `json:"destination_tx"`

	// CreatedAt is the block height when the mint was confirmed
	CreatedAt int64 `json:"created_at"`
}

// BridgeMintAttestation tracks validator attestations for outbound mint confirmations.
// Similar to BridgeAttestation but for outbound (Mirage -> external chain) transfers.
// Validators attest that they've minted tokens on the external chain.
type BridgeMintAttestation struct {
	// BurnID is the Mirage burn sequence number (as string)
	BurnID string `json:"burn_id"`

	// DestinationChain is the external chain identifier (e.g., "solana")
	DestinationChain string `json:"destination_chain"`

	// DestinationTx is the tx hash/signature on the destination chain (from first attestor)
	DestinationTx string `json:"destination_tx"`

	// Attestors maps validator operator address to their voting power at attestation time.
	// Attestors are stored under BridgeMintAttestorsPrefix; this map is kept empty in state.
	Attestors map[string]int64 `json:"attestors"`

	// AttestedPower is the total voting power that has attested
	AttestedPower int64 `json:"attested_power"`

	// Confirmed indicates whether threshold has been met and mint is confirmed
	Confirmed bool `json:"confirmed"`

	// ConfirmedBy is the account address (sdk.AccAddress bech32) of the validator whose
	// attestation crossed the confirmation threshold.
	ConfirmedBy string `json:"confirmed_by"`

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
		Attestors:       make(map[string]int64),
		AttestedPower:   0,
		Minted:          false,
		CreatedAt:       createdAt,
	}
}

// BridgeAttestationKey returns the store key for a bridge attestation
func BridgeAttestationKey(sourceChain, burnID string) []byte {
	return []byte(fmt.Sprintf("%s%s/%s", BridgeAttestationsPrefix, sourceChain, burnID))
}

// BridgeBurnKey returns the store key for a bridge burn record.
// Key includes destination chain to prevent collisions when bridging to multiple chains.
func BridgeBurnKey(destChain, burnID string) []byte {
	return []byte(fmt.Sprintf("%s%s/%s", BridgeBurnsPrefix, destChain, burnID))
}

// BridgeMintedKey returns the store key for a bridge mint confirmation.
// Key includes destination chain to prevent collisions when bridging to multiple chains.
func BridgeMintedKey(destChain, burnID string) []byte {
	return []byte(fmt.Sprintf("%s%s/%s", BridgeMintsPrefix, destChain, burnID))
}

// BridgeMintAttestationKey returns the store key for a bridge mint attestation
func BridgeMintAttestationKey(destChain, burnID string) []byte {
	return []byte(fmt.Sprintf("%s%s/%s", BridgeMintAttestationsPrefix, destChain, burnID))
}

// BridgeMintAttestorKey returns the store key for a bridge mint attestor entry.
func BridgeMintAttestorKey(destChain, burnID, valoper string) []byte {
	return []byte(fmt.Sprintf("%s%s/%s/%s", BridgeMintAttestorsPrefix, destChain, burnID, valoper))
}


// NewBridgeMintAttestation creates a new BridgeMintAttestation with initialized maps
func NewBridgeMintAttestation(burnID, destChain, destTx string, createdAt int64) *BridgeMintAttestation {
	return &BridgeMintAttestation{
		BurnID:           burnID,
		DestinationChain: destChain,
		DestinationTx:    destTx,
		Attestors:        make(map[string]int64),
		AttestedPower:    0,
		Confirmed:        false,
		CreatedAt:        createdAt,
	}
}

// HasAttested returns true if the validator has already attested to this mint
func (a *BridgeMintAttestation) HasAttested(validatorAddr string) bool {
	_, exists := a.Attestors[validatorAddr]
	return exists
}

// AddAttestation records a validator's attestation and adds their voting power.
// Stores the validator's power for threshold tracking and reporting.
// Returns true if the attestation is new (validator hadn't attested before)
func (a *BridgeMintAttestation) AddAttestation(validatorAddr string, votingPower int64) bool {
	if votingPower <= 0 {
		return false
	}
	if _, exists := a.Attestors[validatorAddr]; exists {
		return false
	}
	a.Attestors[validatorAddr] = votingPower
	a.AttestedPower += votingPower
	return true
}

// MeetsThreshold returns true if the attested power meets or exceeds the threshold
// threshold is in basis points (e.g., 6667 = 66.67%)
func (a *BridgeMintAttestation) MeetsThreshold(totalPower int64, thresholdBasisPoints uint64) bool {
	if totalPower <= 0 {
		return false
	}
	required := sdkmath.NewInt(totalPower).
		MulRaw(int64(thresholdBasisPoints)).
		QuoRaw(10000)
	return sdkmath.NewInt(a.AttestedPower).GTE(required)
}

// AttestorList returns a slice of validator addresses that have attested
func (a *BridgeMintAttestation) AttestorList() []string {
	result := make([]string, 0, len(a.Attestors))
	for addr := range a.Attestors {
		result = append(result, addr)
	}
	return result
}

// GetAttestorPower returns the voting power for a specific attestor (0 if not found)
func (a *BridgeMintAttestation) GetAttestorPower(validatorAddr string) int64 {
	return a.Attestors[validatorAddr]
}


// Marshal serializes the mint attestation to JSON
func (a *BridgeMintAttestation) Marshal() ([]byte, error) {
	return json.Marshal(a)
}

// UnmarshalBridgeMintAttestation deserializes JSON to a BridgeMintAttestation
func UnmarshalBridgeMintAttestation(data []byte) (*BridgeMintAttestation, error) {
	var a BridgeMintAttestation
	if err := json.Unmarshal(data, &a); err != nil {
		return nil, err
	}
	// Ensure map is initialized
	if a.Attestors == nil {
		a.Attestors = make(map[string]int64)
	}
	return &a, nil
}

// HasAttested returns true if the validator has already attested to this burn
func (a *BridgeAttestation) HasAttested(validatorAddr string) bool {
	_, exists := a.Attestors[validatorAddr]
	return exists
}

// AddAttestation records a validator's attestation and adds their voting power.
// Stores the validator's power for threshold tracking and reporting.
// Returns true if the attestation is new (validator hadn't attested before)
func (a *BridgeAttestation) AddAttestation(validatorAddr string, votingPower int64) bool {
	if votingPower <= 0 {
		return false
	}
	if _, exists := a.Attestors[validatorAddr]; exists {
		return false
	}
	a.Attestors[validatorAddr] = votingPower
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
		a.Attestors = make(map[string]int64)
	}
	return &a, nil
}

// Marshal serializes a bridge burn record to JSON
func (b *BridgeBurnRecord) Marshal() ([]byte, error) {
	return json.Marshal(b)
}

// UnmarshalBridgeBurnRecord deserializes JSON to a BridgeBurnRecord
func UnmarshalBridgeBurnRecord(data []byte) (*BridgeBurnRecord, error) {
	var b BridgeBurnRecord
	if err := json.Unmarshal(data, &b); err != nil {
		return nil, err
	}
	return &b, nil
}

// Marshal serializes a bridge mint record to JSON
func (m *BridgeMintedRecord) Marshal() ([]byte, error) {
	return json.Marshal(m)
}

// UnmarshalBridgeMintedRecord deserializes JSON to a BridgeMintedRecord
func UnmarshalBridgeMintedRecord(data []byte) (*BridgeMintedRecord, error) {
	var m BridgeMintedRecord
	if err := json.Unmarshal(data, &m); err != nil {
		return nil, err
	}
	return &m, nil
}

// AttestorList returns a slice of validator addresses that have attested
func (a *BridgeAttestation) AttestorList() []string {
	result := make([]string, 0, len(a.Attestors))
	for addr := range a.Attestors {
		result = append(result, addr)
	}
	return result
}

// GetAttestorPower returns the voting power for a specific attestor (0 if not found)
func (a *BridgeAttestation) GetAttestorPower(validatorAddr string) int64 {
	return a.Attestors[validatorAddr]
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

// FindIBCChainConfig finds an enabled IBC chain config by its channel ID
func FindIBCChainConfig(ibcChannel string, chains []*BridgeChainConfig) *BridgeChainConfig {
	for _, chain := range chains {
		if chain.Enabled && chain.IbcChannel == ibcChannel {
			return chain
		}
	}
	return nil
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
