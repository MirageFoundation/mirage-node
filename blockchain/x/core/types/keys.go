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

	// Envelope nonce dedup (replay protection): seen nonces with TTL for pruning
	EnvelopeNoncePrefix       = "envelope_nonce/"        // envelope_nonce/{pubkey_hash}/{nonce} -> empty value (existence check)
	EnvelopeNonceExpiryPrefix = "envelope_nonce_expiry/" // envelope_nonce_expiry/{expiry_unix}/{pubkey_hash}/{nonce} -> empty value (for pruning)

	// RecentBlockHashesKey stores a deterministic, on-chain rolling window of
	// the most recently committed block hashes (lowercase hex). The PoW ante
	// uses this window to validate that an envelope's `last_block_hash`
	// references a recent committed block. Storing the window in state
	// (instead of a per-process in-memory cache) makes acceptance identical
	// across restarts and across peers. Written by BeginBlock; read by the
	// PoW ante decorator. Window length is bounded by params.BlockHashWindow.
	RecentBlockHashesKey = "recent_block_hashes"

	// ReservedProfilesBootstrappedKey is a one-shot BeginBlock sentinel.
	// Once set, the reserved module-account profile bootstrap loop is skipped
	// for all subsequent blocks (see AppModule.BeginBlock).
	ReservedProfilesBootstrappedKey = "reserved_profiles_bootstrapped"

	// BlockSupplyStartKey / BlockSupplyDeltaKey track per-block mint-denom
	// supply for the O(1) EndBlock delta check. BeginBlock writes the
	// start-of-block supply and resets delta to 0; MintCoins/BurnCoins wrappers
	// accumulate the delta; EndBlock asserts supply == start + delta before the
	// full supply-vs-balances invariant.
	BlockSupplyStartKey = "block_supply_start"
	BlockSupplyDeltaKey = "block_supply_delta"

	// CreatorPoolName is the module account that holds creator-liability funds.
	// Direct user sends to it are blocked; only create_tranche and claims move it.
	CreatorPoolName = "creator_pool"

	ProtocolVersionV139 uint32 = 1

	UpgradeV139CompleteKey = "upgrade/v1.39.0/complete"

	EngagementKindUpvote      byte = 0x01
	EngagementKindDirectReply byte = 0x02
)
