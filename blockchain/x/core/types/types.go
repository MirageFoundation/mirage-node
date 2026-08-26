package types

import (
	"fmt"
	"regexp"
	"unicode/utf8"
)

func NewProfilesPrefix() []byte { return []byte(ProfilesPrefix) }

type Profile struct {
	Owner              string `json:"owner"`
	Username           string `json:"username"`
	Level              int32  `json:"level"`
	CreatedAt          int64  `json:"created_at"`
	SubscriptionExpiry int64  `json:"subscription_expiry"`
	AutoRenew          bool   `json:"auto_renew"`
	ReserveFunds       uint64 `json:"reserve_funds"`
	EffectivePaid      bool   `json:"effective_paid"`

	FollowedUsers      []string `json:"followed_users"`
	JoinedCommunities  []string `json:"joined_communities"`
	BlockedUsers       []string `json:"blocked_users"`
	BlockedPosts       []string `json:"blocked_posts"`
	BlockedCommunities []string `json:"blocked_communities"`

	Biography string `json:"biography"`
	Avatar    string `json:"avatar"`
	Banner    string `json:"banner"`
	Flair     string `json:"flair"`
}

func (p *Profile) ToCore() *ProfileCore {
	return &ProfileCore{
		Owner:              p.Owner,
		Username:           p.Username,
		Level:              p.Level,
		CreatedAt:          p.CreatedAt,
		SubscriptionExpiry: p.SubscriptionExpiry,
		AutoRenew:          p.AutoRenew,
		ReserveFunds:       p.ReserveFunds,
		EffectivePaid:      p.EffectivePaid,
		Biography:          p.Biography,
		Avatar:             p.Avatar,
		Banner:             p.Banner,
		Flair:              p.Flair,
	}
}

func (c *ProfileCore) ToProfile() Profile {
	return Profile{
		Owner:              c.Owner,
		Username:           c.Username,
		Level:              c.Level,
		CreatedAt:          c.CreatedAt,
		SubscriptionExpiry: c.SubscriptionExpiry,
		AutoRenew:          c.AutoRenew,
		ReserveFunds:       c.ReserveFunds,
		EffectivePaid:      c.EffectivePaid,
		FollowedUsers:      []string{},
		JoinedCommunities:  []string{},
		BlockedUsers:       []string{},
		BlockedPosts:       []string{},
		BlockedCommunities: []string{},
		Biography:          c.Biography,
		Avatar:             c.Avatar,
		Banner:             c.Banner,
		Flair:              c.Flair,
	}
}

func (p Profile) ValidateBasic(minSize, maxSize uint64) error {
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
