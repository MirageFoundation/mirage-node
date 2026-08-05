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

func TestApplyParamUpdatesPartial(t *testing.T) {
	base := types.DefaultParams()
	updates := types.Params{
		MinDifficulty: base.MinDifficulty + 1,
		AwardConfigs: []*types.AwardConfig{
			{Name: "test", Cost: 1},
		},
	}

	updated, changed := applyParamUpdates(base, updates)
	if updated.MinDifficulty != base.MinDifficulty+1 {
		t.Fatalf("MinDifficulty = %d, want %d", updated.MinDifficulty, base.MinDifficulty+1)
	}
	if updated.MaxUsernameSize != base.MaxUsernameSize {
		t.Fatalf("MaxUsernameSize changed unexpectedly: %d", updated.MaxUsernameSize)
	}
	if updated.PowDifficultyStep != base.PowDifficultyStep {
		t.Fatalf("PowDifficultyStep changed unexpectedly: %f", updated.PowDifficultyStep)
	}
	if updated.SubscriptionPeriod != base.SubscriptionPeriod {
		t.Fatalf("SubscriptionPeriod changed unexpectedly: %d", updated.SubscriptionPeriod)
	}
	if len(updated.AwardConfigs) != 1 || updated.AwardConfigs[0].Name != "test" {
		t.Fatalf("AwardConfigs not updated as expected: %v", updated.AwardConfigs)
	}
	if len(changed) == 0 {
		t.Fatal("Expected changed fields to be reported")
	}
}
