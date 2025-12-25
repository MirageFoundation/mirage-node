"""
Mirage Backend Settings
This module configures runtime behavior for the backend server.
Changes take effect when the server is restarted.

Variables:
- IGNORE_DELETIONS: Show all posts, regardless of deletion status.
- IGNORE_MOD_BLOCKED_POSTS: Show posts even if blocked by followed mods.
- IGNORE_MOD_BLOCKED_USERS: Show content from users even if blocked by followed mods.
"""

# Leaderboard Weights
LEADERBOARD_COMMENT_WEIGHT = 1.5
LEADERBOARD_POST_WEIGHT = 0.8
LEADERBOARD_COMMUNITY_VOTES_WEIGHT = 0.5
LEADERBOARD_VOTES_CAST_WEIGHT = 0.2
LEADERBOARD_DELETED_POST_WEIGHT = -2.0
LEADERBOARD_DELETED_COMMENT_WEIGHT = -3.0

# Fee-related settings removed

# Moderation Settings
# When false (default), standard moderation rules apply:
# - Deleted posts are hidden
# - Blocked posts from followed moderators are hidden
# - Content from blocked users (by followed moderators) is hidden
#
# Set to true to override and show all content:

# Show all posts, regardless of whether they are marked as deleted
IGNORE_DELETIONS = False

# Show all posts, even if blocked by followed moderators (only apply your own blocks)
IGNORE_MOD_BLOCKED_POSTS = False

# Show all content from users, even if blocked by followed moderators (only apply your own blocks)
IGNORE_MOD_BLOCKED_USERS = False
