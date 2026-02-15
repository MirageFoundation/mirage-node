package types

import (
	"fmt"
	"regexp"
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
	IsModerator        bool   `json:"is_moderator"`

	// Social lists (stored separately, loaded on demand)
	FollowedModerators []string `json:"followed_moderators"`
	FollowedUsers      []string `json:"followed_users"`
	FollowedTopics     []string `json:"followed_topics"`
	BlockedUsers       []string `json:"blocked_users"`
	BlockedPosts       []string `json:"blocked_posts"`
	BlockedTopics      []string `json:"blocked_topics"`

	// Profile customization
	Biography string `json:"biography"`
	Avatar    string `json:"avatar"`
	Banner    string `json:"banner"`
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
		IsModerator:        p.IsModerator,
		Biography:          p.Biography,
		Avatar:             p.Avatar,
		Banner:             p.Banner,
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
		IsModerator:        c.IsModerator,
		Biography:          c.Biography,
		Avatar:             c.Avatar,
		Banner:             c.Banner,
		FollowedModerators: []string{},
		FollowedUsers:      []string{},
		FollowedTopics:     []string{},
		BlockedUsers:       []string{},
		BlockedPosts:       []string{},
		BlockedTopics:      []string{},
	}
}

func (p Profile) ValidateBasic(minSize, maxSize uint64, maxModerators uint64) error {
	usernameLen := uint64(len(p.Username))
	if usernameLen < minSize {
		return fmt.Errorf("username too short: %d < %d", usernameLen, minSize)
	}
	if usernameLen > maxSize {
		return fmt.Errorf("username too long: %d > %d", usernameLen, maxSize)
	}
	// Allow only alphanumeric and '-'
	valid := regexp.MustCompile(`^[A-Za-z0-9-]+$`)
	if p.Username != "" && !valid.MatchString(p.Username) {
		return fmt.Errorf("invalid username")
	}
	if uint64(len(p.FollowedModerators)) > maxModerators {
		return fmt.Errorf("too many followed moderators: %d > %d", len(p.FollowedModerators), maxModerators)
	}
	if len(p.Biography) > 512 {
		return fmt.Errorf("biography too long")
	}
	if len(p.Avatar) > 512 {
		return fmt.Errorf("avatar too long")
	}
	if len(p.Banner) > 512 {
		return fmt.Errorf("banner too long")
	}
	return nil
}
