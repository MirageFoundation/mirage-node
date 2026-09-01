"""
Indexer configuration constants.

NOTE: Validation constants (community size, username size, content size, title size)
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
COMMUNITY_VOTE_MAX_COMMUNITY_VOTES = 10  # Votes in community needed for full weight
COMMUNITY_VOTE_MIN_NET_VOTES = -10  # Min net votes required for full formula; below this = baseline only
COMMUNITY_VOTE_MATURITY_DAYS = 7  # Account age (days) to reach full potential
COMMUNITY_VOTE_MIN_ROOT_POSTS = 3  # Unique root posts voted required for full weight
COMMUNITY_VOTE_MAX_POSTS = 3  # Posts/comments in community needed for full weight (0 = baseline only)
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

# Startup profile reconciliation: refuse to soft-delete more than this fraction of
# known profiles in one sync. The blocked_* rows dropped alongside a soft-delete are
# the indexer's own retained history, which the chain does not keep and cannot
# rebuild, so a suspicious inventory has to stop startup rather than destroy them.
PROFILE_SYNC_MAX_ABSENT_FRACTION = 0.10

# gRPC timeout
GRPC_TIMEOUT = 3

# Overall budget for one balance batch. Bounds the whole prefetch for a block, which
# per-call timeouts alone do not: a block touching many distinct addresses would
# otherwise cost addresses * GRPC_TIMEOUT before the block transaction even opens.
BALANCE_BATCH_DEADLINE = 30

# RPC readiness wait
RPC_READY_MAX_WAIT = 60
RPC_READY_RETRY_DELAY = 1

# ========== Moderation Settings ==========
# Show all posts, regardless of whether they are marked as deleted
IGNORE_DELETIONS = False
