package core

import (
	"reflect"
	"testing"

	"mirage/x/core/types"
)

// TestUpdateParamsCoversAllFields ensures all Params fields are handled in UpdateParams.
// If a new field is added to Params but not to UpdateParams, this test will fail.
func TestUpdateParamsCoversAllFields(t *testing.T) {
	// These fields are expected to be handled in UpdateParams
	// Add any new param fields here when implementing them
	handledFields := map[string]bool{
		// Minting
		"MintInterval":         true,
		"MintQuantity":         true,
		"MintDynamicCreditCap": true,
		"MintDynamicSplit":     true,
		// PoW
		"MinDifficulty":            true,
		"PowMessageWindow":         true,
		"PowMessageLimit":          true,
		"PowCalmPeriodDefinition":  true,
		"PowCalmSequenceThreshold": true,
		"PowDifficultyAllowance":   true,
		"PowDifficultyStep":        true,
		"BlockHashWindow":          true,
		// Username/Topic limits
		"MinUsernameSize": true,
		"MaxUsernameSize": true,
		"MinTopicSize":    true,
		"MaxTopicSize":    true,
		// Subscription
		"SubscriptionPeriod":         true,
		"SubscriptionReservePercent": true,
		"Tiers":                      true,
		// Relay
		"RelayMinGasPrice": true,
		"RelayMaxGasFee":   true,
		// Envelope
		"MaxEnvelopeAge": true,
		// Bridge
		"BridgeChains":               true,
		"BridgeAttestationThreshold": true,
		// Awards
		"AwardConfigs": true,
	}

	// Get all fields from Params struct using reflection
	paramsType := reflect.TypeOf(types.Params{})
	var missingFields []string

	for i := 0; i < paramsType.NumField(); i++ {
		field := paramsType.Field(i)
		// Skip protobuf internal fields
		if field.Name == "state" || field.Name == "sizeCache" || field.Name == "unknownFields" {
			continue
		}
		if !handledFields[field.Name] {
			missingFields = append(missingFields, field.Name)
		}
	}

	if len(missingFields) > 0 {
		t.Errorf("The following Params fields are not handled in UpdateParams: %v\n"+
			"Add them to UpdateParams in module.go and update the handledFields map in this test.",
			missingFields)
	}

	// Also verify we don't have stale entries in handledFields
	actualFields := make(map[string]bool)
	for i := 0; i < paramsType.NumField(); i++ {
		field := paramsType.Field(i)
		if field.Name != "state" && field.Name != "sizeCache" && field.Name != "unknownFields" {
			actualFields[field.Name] = true
		}
	}

	var staleFields []string
	for fieldName := range handledFields {
		if !actualFields[fieldName] {
			staleFields = append(staleFields, fieldName)
		}
	}

	if len(staleFields) > 0 {
		t.Errorf("The following fields are in handledFields but don't exist in Params: %v\n"+
			"Remove them from the handledFields map in this test.",
			staleFields)
	}
}
