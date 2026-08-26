package core

import (
	"reflect"
	"strings"
	"testing"

	authtypes "github.com/cosmos/cosmos-sdk/x/auth/types"
	govtypes "github.com/cosmos/cosmos-sdk/x/gov/types"
	gogotypes "github.com/cosmos/gogoproto/types"
	"github.com/stretchr/testify/require"

	"mirage/x/core/types"
)

// protoFieldName extracts the canonical snake_case proto field name from a
// generated struct field's protobuf tag.
func protoFieldName(t *testing.T, field reflect.StructField) string {
	t.Helper()
	for _, part := range strings.Split(field.Tag.Get("protobuf"), ",") {
		if strings.HasPrefix(part, "name=") {
			return strings.TrimPrefix(part, "name=")
		}
	}
	t.Fatalf("field %s has no protobuf name tag", field.Name)
	return ""
}

// TestUpdateParamsCoversAllFields ensures every Params field can be selected by
// an update_mask path, and that the allowlist has no stale entries. Adding a
// param without adding it to paramFieldSetters makes it ungovernable, which is
// exactly the drift this pins.
func TestUpdateParamsCoversAllFields(t *testing.T) {
	paramsType := reflect.TypeOf(types.Params{})
	actual := make(map[string]bool, paramsType.NumField())

	var missing []string
	for i := 0; i < paramsType.NumField(); i++ {
		field := paramsType.Field(i)
		if field.Name == "state" || field.Name == "sizeCache" || field.Name == "unknownFields" {
			continue
		}
		name := protoFieldName(t, field)
		actual[name] = true
		if _, deprecated := deprecatedParamFields[name]; deprecated {
			require.NotContains(t, paramFieldSetters, name,
				"a deprecated field must stay ungovernable; remove it from paramFieldSetters")
			continue
		}
		if _, ok := paramFieldSetters[name]; !ok {
			missing = append(missing, name)
		}
	}

	require.Empty(t, missing,
		"these Params fields cannot be selected by update_mask; add them to paramFieldSetters in module.go")

	var stale []string
	for name := range paramFieldSetters {
		if !actual[name] {
			stale = append(stale, name)
		}
	}
	require.Empty(t, stale, "these paramFieldSetters entries no longer exist in Params")

	for name := range deprecatedParamFields {
		require.Contains(t, actual, name,
			"a deprecated entry names a field that no longer exists in Params")
	}
}

// TestUpdateParamsRejectsDeprecatedField pins the replacement for validating the
// retired float to 0: governance gets an explicit rejection instead of writing a
// field nothing reads. Validating it to 0 was tried and reverted because the
// v1.5.0, v1.8.0, and v1.11.0 handlers set it and call SetParams, so the check
// made a from-genesis replay impossible.
func TestUpdateParamsRejectsDeprecatedField(t *testing.T) {
	base := types.DefaultParams()

	_, _, err := applyParamUpdates(base, types.Params{SubscriptionReservePercent: 0.5},
		mask("subscription_reserve_percent"))
	require.Error(t, err, "a proposal naming the retired field must be rejected")

	updated, changed, err := applyParamUpdates(base, types.Params{SubscriptionReserveBps: 8_000},
		mask("subscription_reserve_bps"))
	require.NoError(t, err)
	require.Equal(t, []string{"subscription_reserve_bps"}, changed)
	require.Equal(t, uint64(8_000), updated.SubscriptionReserveBps)
	require.NoError(t, updated.Validate())
}

// TestUpdateParamsSettersAssignOnlyTheirOwnField proves each setter is wired to
// the field its path names, catching copy-paste errors in the allowlist.
func TestUpdateParamsSettersAssignOnlyTheirOwnField(t *testing.T) {
	paramsType := reflect.TypeOf(types.Params{})
	fieldByProtoName := map[string]string{}
	for i := 0; i < paramsType.NumField(); i++ {
		field := paramsType.Field(i)
		if field.Name == "state" || field.Name == "sizeCache" || field.Name == "unknownFields" {
			continue
		}
		fieldByProtoName[protoFieldName(t, field)] = field.Name
	}

	for path, setter := range paramFieldSetters {
		t.Run(path, func(t *testing.T) {
			goField, ok := fieldByProtoName[path]
			require.True(t, ok)

			base := types.DefaultParams()
			source := mutatedParams(t, base)

			merged := base
			setter(&merged, source)

			mergedVal := reflect.ValueOf(merged)
			sourceVal := reflect.ValueOf(source)
			baseVal := reflect.ValueOf(base)

			require.True(t,
				reflect.DeepEqual(mergedVal.FieldByName(goField).Interface(), sourceVal.FieldByName(goField).Interface()),
				"setter for %q did not assign %s", path, goField)

			for otherPath, otherGoField := range fieldByProtoName {
				if otherPath == path {
					continue
				}
				require.True(t,
					reflect.DeepEqual(mergedVal.FieldByName(otherGoField).Interface(), baseVal.FieldByName(otherGoField).Interface()),
					"setter for %q also modified %s", path, otherGoField)
			}
		})
	}
}

// mutatedParams returns params whose every field differs from base, so a setter
// that assigns the wrong field is detectable.
func mutatedParams(t *testing.T, base types.Params) types.Params {
	t.Helper()
	out := base
	outVal := reflect.ValueOf(&out).Elem()
	for i := 0; i < outVal.NumField(); i++ {
		field := outVal.Type().Field(i)
		if field.Name == "state" || field.Name == "sizeCache" || field.Name == "unknownFields" {
			continue
		}
		f := outVal.Field(i)
		switch f.Kind() {
		case reflect.Uint64:
			f.SetUint(f.Uint() + 1)
		case reflect.Float64:
			f.SetFloat(f.Float() / 2)
		case reflect.Slice:
			f.Set(reflect.MakeSlice(f.Type(), 1, 1))
		default:
			t.Fatalf("unhandled Params field kind %s for %s", f.Kind(), field.Name)
		}
	}
	return out
}

func mask(paths ...string) *gogotypes.FieldMask {
	return &gogotypes.FieldMask{Paths: paths}
}

func TestApplyParamUpdatesAppliesOnlyMaskedFields(t *testing.T) {
	base := types.DefaultParams()
	updates := types.Params{
		MinDifficulty:   base.MinDifficulty + 1,
		MaxUsernameSize: base.MaxUsernameSize + 7,
		AwardConfigs:    []*types.AwardConfig{{Name: "test", Cost: 1}},
	}

	updated, changed, err := applyParamUpdates(base, updates, mask("min_difficulty", "award_configs"))
	require.NoError(t, err)
	require.Equal(t, []string{"min_difficulty", "award_configs"}, changed)

	require.Equal(t, base.MinDifficulty+1, updated.MinDifficulty)
	require.Len(t, updated.AwardConfigs, 1)
	require.Equal(t, "test", updated.AwardConfigs[0].Name)

	require.Equal(t, base.MaxUsernameSize, updated.MaxUsernameSize,
		"an unmasked field must be untouched even when the proposal carries a value for it")
	require.Equal(t, base.PowDifficultyStep, updated.PowDifficultyStep)
	require.Equal(t, base.SubscriptionPeriod, updated.SubscriptionPeriod)
}

// TestApplyParamUpdatesAppliesZeroValues is the L-9 regression: zero used to mean
// "not supplied", so no proposal could ever select it.
func TestApplyParamUpdatesAppliesZeroValues(t *testing.T) {
	base := types.DefaultParams()
	require.NotZero(t, base.SubscriptionPeriod)

	updated, changed, err := applyParamUpdates(base, types.Params{SubscriptionPeriod: 0}, mask("subscription_period"))
	require.NoError(t, err)
	require.Equal(t, []string{"subscription_period"}, changed)
	require.Zero(t, updated.SubscriptionPeriod, "a masked zero must be applied")
	require.NoError(t, updated.Validate(), "one-time-payment mode must remain valid params")

	// The same holds for a float field. mint_dynamic_split carries the case now:
	// subscription_reserve_percent is validated to 0, so masking it to 0 changes
	// nothing and the "no selected field changed" guard rejects it.
	require.NotZero(t, base.MintDynamicSplit)
	updated, changed, err = applyParamUpdates(base, types.Params{MintDynamicSplit: 0}, mask("mint_dynamic_split"))
	require.NoError(t, err)
	require.Equal(t, []string{"mint_dynamic_split"}, changed)
	require.Zero(t, updated.MintDynamicSplit, "a masked zero float must be applied")
}

func TestApplyParamUpdatesReplacesRepeatedFields(t *testing.T) {
	base := types.DefaultParams()
	require.Len(t, base.Tiers, 2)

	replacement := types.DefaultTiers()
	replacement[1].PeriodFee = 1
	updated, _, err := applyParamUpdates(base, types.Params{Tiers: replacement}, mask("tiers"))
	require.NoError(t, err)
	require.Len(t, updated.Tiers, 2)
	require.Equal(t, uint64(1), updated.Tiers[1].PeriodFee)

	// An empty repeated value is a real replacement request, and must then fail
	// validation rather than be silently ignored.
	updated, _, err = applyParamUpdates(base, types.Params{Tiers: nil}, mask("tiers"))
	require.NoError(t, err)
	require.Empty(t, updated.Tiers)
	require.Error(t, updated.Validate())
}

func TestApplyParamUpdatesRejectsBadMasks(t *testing.T) {
	base := types.DefaultParams()
	updates := types.Params{MinDifficulty: base.MinDifficulty + 1}

	cases := map[string]*gogotypes.FieldMask{
		"nil":            nil,
		"empty":          mask(),
		"blank_path":     mask("   "),
		"unknown_path":   mask("not_a_param"),
		"duplicate_path": mask("min_difficulty", "min_difficulty"),
		"nested_path":    mask("tiers.period_fee"),
		"camel_case":     mask("minDifficulty"),
		"whitespace":     mask(" min_difficulty "),
	}

	for name, m := range cases {
		t.Run(name, func(t *testing.T) {
			_, _, err := applyParamUpdates(base, updates, m)
			require.Error(t, err)
		})
	}
}

func TestApplyParamUpdatesRejectsNoOp(t *testing.T) {
	base := types.DefaultParams()

	_, _, err := applyParamUpdates(
		base,
		types.Params{MinDifficulty: base.MinDifficulty},
		mask("min_difficulty"),
	)
	require.ErrorContains(t, err, "does not change any selected field")
}

func TestUpdateParamsRejectsMissingMask(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()
	am := newTestModule(mk)

	_, err := am.UpdateParams(ctx, &types.MsgUpdateParams{
		Authority: authtypes.NewModuleAddress(govtypes.ModuleName).String(),
		Params:    types.DefaultParams(),
	})
	require.ErrorContains(t, err, "update_mask is required")
}

func TestGetProfilesReturnsCorruptProfileError(t *testing.T) {
	mk := newMockKeeper()
	ctx := newMockContext()
	am := newTestModule(mk)
	mk.storeService.store[types.ProfilesPrefix+testAccAddressString()] = []byte("{")

	_, err := am.GetProfiles(ctx, &types.QueryProfilesRequest{})
	require.ErrorContains(t, err, "corrupt profile JSON")
}

func TestApplyParamUpdatesSurfacesInvalidMergedParams(t *testing.T) {
	base := types.DefaultParams()

	updated, _, err := applyParamUpdates(base, types.Params{PowMessageWindow: types.MaxPowMessageWindow + 1}, mask("pow_message_window"))
	require.NoError(t, err, "the merge itself succeeds; validation is the gate")
	require.Error(t, updated.Validate(), "a masked value past its bound must fail Validate")

	updated, _, err = applyParamUpdates(base, types.Params{MinDifficulty: 0}, mask("min_difficulty"))
	require.NoError(t, err)
	require.Error(t, updated.Validate(), "a masked zero that is invalid must be rejected by Validate")
}
