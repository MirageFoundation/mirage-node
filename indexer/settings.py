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

# Progress reporting
CATCHUP_PROGRESS_INTERVAL = 1000

# gRPC timeout
GRPC_TIMEOUT = 3

# RPC readiness wait
RPC_READY_MAX_WAIT = 60
RPC_READY_RETRY_DELAY = 1

# ========== Moderation Settings ==========
# Show all posts, regardless of whether they are marked as deleted
IGNORE_DELETIONS = False
