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

func TestNormalizeCurationTeamDescription(t *testing.T) {
	// Surrounding whitespace is stripped and the trimmed text is what the
	// caller must store, so each case pins the returned value.
	normalized := []struct {
		description string
		want        string
	}{
		{"", ""},
		{"Moderation guidance", "Moderation guidance"},
		{"   ", ""},
		{" guidance", "guidance"},
		{"guidance\n", "guidance"},
		{"  spaced out  ", "spaced out"},
		{strings.Repeat("x", 800), strings.Repeat("x", 800)},
		{strings.Repeat("🙂", 800), strings.Repeat("🙂", 800)},
		// The limit applies after trimming, so padding cannot push a legal
		// description over the edge.
		{" " + strings.Repeat("x", 800) + " ", strings.Repeat("x", 800)},
	}
	for _, tc := range normalized {
		got, err := NormalizeCurationTeamDescription(tc.description, 800)
		require.NoError(t, err, "description %q", tc.description)
		require.Equal(t, tc.want, got, "description %q", tc.description)
	}

	tooLong := []string{
		strings.Repeat("x", 801),
		strings.Repeat("🙂", 801),
	}
	for _, description := range tooLong {
		_, err := NormalizeCurationTeamDescription(description, 800)
		require.ErrorContains(t, err, "description exceeds")
	}
}
