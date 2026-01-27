"""
Indexer configuration constants.

NOTE: Validation constants (topic size, username size, content size, title size)
are NOT defined here - they come from chain params loaded at startup via gRPC.
See indexer/params.py for the param loading logic.
"""

# Vote directions
ALLOWED_DIRECTIONS = {-1, 0, 1}

# When enabled, votes are weighted by voter's tier (1.0, 1.15, 1.30, 1.45)
# When disabled, all votes count as +1/-1
WEIGHTED_VOTES = True

# Community vote weight algorithm
COMMUNITY_VOTE_BASELINE = 0.0  # Downvotes from outsiders don't affect community score
COMMUNITY_VOTE_MAX_TOPIC_VOTES = 10  # Votes in topic needed for full weight
COMMUNITY_VOTE_MIN_NET_VOTES = -10  # Min net votes required for full formula; below this = baseline only
COMMUNITY_VOTE_MATURITY_DAYS = 7  # Account age (days) to reach full potential
COMMUNITY_VOTE_MIN_ROOT_POSTS = 3  # Unique root posts voted required for full weight
COMMUNITY_VOTE_MAX_POSTS = 3  # Posts/comments in topic needed for full weight (0 = baseline only)
COMMUNITY_VOTE_BOOST_MULTIPLIER = 1  # No boost - upvotes always full, downvotes gated by activity

# Network timeouts
HTTP_TIMEOUT_SHORT = 2
HTTP_TIMEOUT_MEDIUM = 3
HTTP_TIMEOUT_LONG = 10

# WebSocket configuration
WS_PING_INTERVAL = 20
WS_PING_TIMEOUT = 10
WS_RECONNECT_DELAY = 5

# Transaction deduplication
SEEN_TXS_MAX_SIZE = 5000
SEEN_TXS_CLEANUP_BATCH = 500

# Progress reporting
CATCHUP_PROGRESS_INTERVAL = 1000

# gRPC timeout
GRPC_TIMEOUT = 3

# RPC readiness wait
RPC_READY_MAX_WAIT = 60
RPC_READY_RETRY_DELAY = 1

# DB list caps (can be higher than on-chain caps)
# These are multipliers over the tier-based on-chain cap
DB_LIST_CAP_MULTIPLIER = 2  # Store 2x the on-chain cap
# Absolute limits for lists stored in DB
DB_MAX_FOLLOWED_USERS = 2000
DB_MAX_FOLLOWED_TOPICS = 2000
DB_MAX_BLOCKED_USERS = 2000
DB_MAX_BLOCKED_POSTS = 1000
DB_MAX_QUALITY_POSTS = 200

# ========== Quest System Settings ==========
# Feature flags - set to False to disable without code changes
QUESTS_ENABLED = True
ACHIEVEMENTS_ENABLED = True

# Quest assignment
DAILY_QUESTS_COUNT = 2  # Number of random daily quests per user
FLASH_QUEST_MIN_INTERVAL_HOURS = 4  # Minimum hours between flash quests
FLASH_QUEST_MAX_INTERVAL_HOURS = 8  # Maximum hours between flash quests

# Reward multiplier (account age-based)
REWARD_MULTIPLIER_DAYS = 30  # Days to reach max multiplier
REWARD_MULTIPLIER_MIN = 1.0  # Minimum multiplier (new accounts get 1x)
REWARD_MULTIPLIER_MAX = 5.0  # Maximum multiplier (mature accounts get 5x)

# Daily reward cap (in umirage, 0 = no cap)
DAILY_REWARD_CAP = 0
