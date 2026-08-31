package types

import (
	"strings"
	"testing"

	"github.com/stretchr/testify/require"
)

func TestValidateCurationTeamName(t *testing.T) {
	valid := []string{
		"A",
		"Signal Desk",
		"signal-desk_2",
		strings.Repeat("a", 30),
	}
	for _, name := range valid {
		t.Run("valid_"+name, func(t *testing.T) {
			require.NoError(t, ValidateCurationTeamName(name, 30))
		})
	}

	invalid := []struct {
		name string
		err  string
	}{
		{"", "required"},
		{"   ", "surrounding whitespace"},
		{" Signal", "surrounding whitespace"},
		{"Signal ", "surrounding whitespace"},
		{strings.Repeat("a", 31), "exceeds limit"},
		{"Signal!", "printable ASCII"},
		{"Sïgnal", "printable ASCII"},
		{"-Signal", "printable ASCII"},
		{"Signal_", "printable ASCII"},
	}
	for _, tc := range invalid {
		t.Run("invalid_"+tc.err+"_"+tc.name, func(t *testing.T) {
			require.ErrorContains(t, ValidateCurationTeamName(tc.name, 30), tc.err)
		})
	}
}

func TestValidateCurationTeamDescription(t *testing.T) {
	valid := []string{
		"",
		"Moderation guidance",
		strings.Repeat("x", 800),
		strings.Repeat("🙂", 800),
	}
	for _, description := range valid {
		require.NoError(t, ValidateCurationTeamDescription(description, 800))
	}

	invalid := []struct {
		description string
		err         string
	}{
		{"   ", "surrounding whitespace"},
		{" guidance", "surrounding whitespace"},
		{"guidance\n", "surrounding whitespace"},
		{strings.Repeat("x", 801), "description exceeds"},
		{strings.Repeat("🙂", 801), "description exceeds"},
	}
	for _, tc := range invalid {
		require.ErrorContains(t, ValidateCurationTeamDescription(tc.description, 800), tc.err)
	}
}
