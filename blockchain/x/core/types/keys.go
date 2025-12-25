package types

const (
	// ModuleName defines the module name.
	ModuleName = "core"

	// StoreKey is the string store representation.
	StoreKey = ModuleName

	// RouterKey is the message route for slashing.
	RouterKey = ModuleName

	// MemStoreKey defines the in-memory store key.
	MemStoreKey = "mem_core"

	// ProfilesPrefix is the KVStore prefix for core profile data (scalars only)
	ProfilesPrefix = "profiles/"

	// UsernamesPrefix maps lowercased username -> owner address (bech32 string)
	UsernamesPrefix = "usernames/"

	// RelayCreditsPrefix maps valoper address -> normalized relay credits for current window
	RelayCreditsPrefix = "relay_credits/"

	// SubscriptionsPrefix maps expiry_timestamp_hex:address -> level for renewal tracking
	SubscriptionsPrefix = "subs/"

	// Profile list prefixes - stored separately from core profile for performance
	ProfileFollowedModsPrefix   = "plist_mods/"    // address -> JSON array of moderator addresses
	ProfileFollowedUsersPrefix  = "plist_users/"   // address -> JSON array of user addresses
	ProfileFollowedTopicsPrefix = "plist_topics/"  // address -> JSON array of topic strings
	ProfileBlockedUsersPrefix   = "plist_blocked/" // address -> JSON array of blocked user addresses
	ProfileBlockedPostsPrefix   = "plist_bposts/"  // address -> JSON array of blocked post txhashes
	ProfileQualityPostsPrefix   = "plist_quality/" // address -> JSON array of quality post txhashes

	// MintDenom is the base denom used for minting and burning
	MintDenom = "umirage"
)
