package types

import (
	"fmt"
	"regexp"
	"strings"
	"unicode/utf8"
)

var communitySlugRe = regexp.MustCompile(`^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$`)

func ValidateCommunitySlug(slug string, minLen, maxLen uint64) error {
	if slug != strings.TrimSpace(slug) {
		return fmt.Errorf("community slug must not have surrounding whitespace")
	}
	n := uint64(len(slug))
	if n < minLen {
		return fmt.Errorf("community below minimum: %d < %d", n, minLen)
	}
	if n > maxLen {
		return fmt.Errorf("community exceeds limit: %d > %d", n, maxLen)
	}
	if !communitySlugRe.MatchString(slug) {
		return fmt.Errorf("community must be lowercase alphanumeric with single internal hyphens")
	}
	if strings.Contains(slug, "--") {
		return fmt.Errorf("community must not contain consecutive hyphens")
	}
	return nil
}

var teamNameRe = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9 _-]*[A-Za-z0-9]$|^[A-Za-z0-9]$`)

func ValidateCurationTeamName(name string, maxLen uint64) error {
	if name != strings.TrimSpace(name) {
		return fmt.Errorf("team name must not have surrounding whitespace")
	}
	n := uint64(utf8.RuneCountInString(name))
	if n == 0 {
		return fmt.Errorf("team name required")
	}
	if n > maxLen {
		return fmt.Errorf("team name exceeds limit: %d > %d", n, maxLen)
	}
	if !teamNameRe.MatchString(name) {
		return fmt.Errorf("team name must be printable ASCII letters, digits, spaces, hyphens, or underscores")
	}
	return nil
}

func ValidateCurationTeamDescription(description string, maxLen uint64) error {
	if description != "" && description != strings.TrimSpace(description) {
		return fmt.Errorf("team description must not have surrounding whitespace")
	}
	if uint64(utf8.RuneCountInString(description)) > maxLen {
		return fmt.Errorf("description exceeds max_curation_team_description_length")
	}
	return nil
}

func NormalizeTeamNameKey(name string) string {
	return strings.ToLower(name)
}

func ValidateTxHash(h string) error {
	_, err := HashBytes(h)
	return err
}
