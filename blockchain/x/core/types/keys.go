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

	// ── Per-entry set/deque prefixes ────────────────────────────────────
	//
	// All six profile lists use per-entry KV keys for O(1) add/remove/has.
	// Three flavors share the same underlying pattern:
	//
	//  Unordered set  (followed_users, followed_topics)
	//    Entry:  {prefix}{owner}/{entry}  → []byte{1}  (1-byte sentinel)
	//    Count:  {prefix}{owner}\x00c     → uint32 big-endian
	//
	//  Ordered set  (enabled_agents)
	//    Entry:  {prefix}{owner}/{entry}  → uint64 big-endian (position)
	//    Count:  {prefix}{owner}\x00c     → uint32 big-endian
	//    Seq:    {prefix}{owner}\x00s     → uint64 big-endian (next position)
	//
	//  Deque  (blocked_users, blocked_posts, blocked_topics)
	//    Entry:  {prefix}{owner}/{entry}  → uint64 big-endian (sequence)
	//    Count:  {prefix}{owner}\x00c     → uint32 big-endian
	//    Seq:    {prefix}{owner}\x00s     → uint64 big-endian (next sequence)
	//    When over cap, the entry with the lowest sequence is evicted.
	//
	// The \x00c / \x00s suffixes contain a NUL byte so they can never collide
	// with entry keys (bech32 addresses and topic names never contain NUL).

	FollowedUsersPrefix  = "fu/" // unordered set — followed users
	FollowedTopicsPrefix = "ft/" // unordered set — followed topics
	EnabledAgentsPrefix  = "ea/" // ordered set   — enabled agents
	BlockedUsersPrefix   = "bu/" // deque         — blocked users
	BlockedPostsPrefix   = "bp/" // deque         — blocked posts
	BlockedTopicsPrefix  = "bt/" // deque         — blocked topics

	SetCountSuffix = "\x00c" // appended to {prefix}{owner} for the count key
	DequeSeqSuffix = "\x00s" // appended to {prefix}{owner} for the next-sequence key

	// Legacy JSON-blob prefixes — kept so the v1.3.0-tiers historical upgrade
	// handler (which references them at compile time) still compiles, and so
	// the v1.16.0 migration can read old data.
	ProfileEnabledAgentsPrefix  = "plist_agents/"
	ProfileFollowedUsersPrefix  = "plist_users/"
	ProfileFollowedTopicsPrefix = "plist_topics/"
	ProfileBlockedUsersPrefix   = "plist_blocked/"
	ProfileBlockedPostsPrefix   = "plist_bposts/"
	ProfileBlockedTopicsPrefix  = "plist_btopics/"

	// MintDenom is the base denom used for minting and burning
	MintDenom = "umirage"

	// Bridge-related prefixes (defined in bridge.go for detailed comments)
	// BridgeAttestationsPrefix = "bridge_attestations/"
	// BridgePendingCountKey = "bridge_pending_count"
)
