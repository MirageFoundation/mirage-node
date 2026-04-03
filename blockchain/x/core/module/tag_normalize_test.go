package core

import (
	"testing"
)

func TestNormalizeTag(t *testing.T) {
	tests := []struct {
		input string
		want  string
	}{
		{"porn", "adult"},
		{" porn ", "adult"},
		{"adult", "adult"},
		{"sensitive", "sensitive"},
		{"gore", "gore"},
		{"violence", "violence"},
		{"death", "death"},
		{"", ""},
		{"unknown", "unknown"},
	}
	for _, tc := range tests {
		got := normalizeTag(tc.input)
		if got != tc.want {
			t.Errorf("normalizeTag(%q) = %q, want %q", tc.input, got, tc.want)
		}
	}
}

func TestValidateTagAcceptsPornAsAdult(t *testing.T) {
	if err := validateTag("porn"); err != nil {
		t.Errorf("validateTag(\"porn\") returned error: %v (should be accepted via alias)", err)
	}
	if err := validateTag("adult"); err != nil {
		t.Errorf("validateTag(\"adult\") returned error: %v", err)
	}
}

func TestValidateTagRejectsInvalid(t *testing.T) {
	if err := validateTag("nsfw"); err == nil {
		t.Error("validateTag(\"nsfw\") should return error for unrecognized tag")
	}
}

func TestValidateTagAllAllowed(t *testing.T) {
	for tag := range allowedTags {
		if err := validateTag(tag); err != nil {
			t.Errorf("validateTag(%q) returned error: %v (should be allowed)", tag, err)
		}
	}
}
