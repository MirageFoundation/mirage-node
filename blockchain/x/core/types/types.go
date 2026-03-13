package types

import (
	"fmt"
	"regexp"
	"unicode/utf8"
)

// Profiles key helpers
func NewProfilesPrefix() []byte { return []byte(ProfilesPrefix) }

// NOTE: ProfileCore is now defined in genesis.pb.go (generated from proto).
// This ensures a single source of truth for the profile structure.

// Profile represents the full profile data including lists.
// Lists are stored separately for performance but combined here for convenience.
type Profile struct {
	Owner              string `json:"owner"`
	Username           string `json:"username"`
	Level              int32  `json:"level"`
	CreatedAt          int64  `json:"created_at"`
	SubscriptionExpiry int64  `json:"subscription_expiry"`
	AutoRenew          bool   `json:"auto_renew"`
	ReserveFunds       uint64 `json:"reserve_funds"`

	// Social lists (stored separately, loaded on demand)
	EnabledAgents  []string `json:"enabled_agents"`
	FollowedUsers  []string `json:"followed_users"`
	FollowedTopics []string `json:"followed_topics"`
	BlockedUsers   []string `json:"blocked_users"`
	BlockedPosts   []string `json:"blocked_posts"`
	BlockedTopics  []string `json:"blocked_topics"`

	// Profile customization
	Biography string `json:"biography"`
	Avatar    string `json:"avatar"`
	Banner    string `json:"banner"`
	Flair     string `json:"flair"`
}

// ToCore extracts the core scalar fields from a full Profile
func (p *Profile) ToCore() *ProfileCore {
	return &ProfileCore{
		Owner:              p.Owner,
		Username:           p.Username,
		Level:              p.Level,
		CreatedAt:          p.CreatedAt,
		SubscriptionExpiry: p.SubscriptionExpiry,
		AutoRenew:          p.AutoRenew,
		ReserveFunds:       p.ReserveFunds,
		Biography:          p.Biography,
		Avatar:             p.Avatar,
		Banner:             p.Banner,
		Flair:              p.Flair,
	}
}

// ToProfile converts a ProfileCore to a full Profile with empty lists
func (c *ProfileCore) ToProfile() Profile {
	return Profile{
		Owner:              c.Owner,
		Username:           c.Username,
		Level:              c.Level,
		CreatedAt:          c.CreatedAt,
		SubscriptionExpiry: c.SubscriptionExpiry,
		AutoRenew:          c.AutoRenew,
		ReserveFunds:       c.ReserveFunds,
		Biography:          c.Biography,
		Avatar:             c.Avatar,
		Banner:             c.Banner,
		Flair:              c.Flair,
		EnabledAgents:      []string{},
		FollowedUsers:      []string{},
		FollowedTopics:     []string{},
		BlockedUsers:       []string{},
		BlockedPosts:       []string{},
		BlockedTopics:      []string{},
	}
}

func (p Profile) ValidateBasic(minSize, maxSize uint64, maxAgents uint64) error {
	usernameLen := uint64(len(p.Username))
	if usernameLen < minSize {
		return fmt.Errorf("username too short: %d < %d", usernameLen, minSize)
	}
	if usernameLen > maxSize {
		return fmt.Errorf("username too long: %d > %d", usernameLen, maxSize)
	}
	valid := regexp.MustCompile(`^[A-Za-z0-9-]+$`)
	if p.Username != "" && !valid.MatchString(p.Username) {
		return fmt.Errorf("invalid username")
	}
	if uint64(len(p.EnabledAgents)) > maxAgents {
		return fmt.Errorf("too many enabled agents: %d > %d", len(p.EnabledAgents), maxAgents)
	}
	if utf8.RuneCountInString(p.Biography) > 512 {
		return fmt.Errorf("biography too long")
	}
	if utf8.RuneCountInString(p.Avatar) > 512 {
		return fmt.Errorf("avatar too long")
	}
	if utf8.RuneCountInString(p.Banner) > 512 {
		return fmt.Errorf("banner too long")
	}
	if utf8.RuneCountInString(p.Flair) > 20 {
		return fmt.Errorf("flair too long")
	}
	return nil
}
