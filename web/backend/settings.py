"""
Mirage Backend Settings
This module configures runtime behavior for the backend server.
Changes take effect when the server is restarted.

Variables:
- IGNORE_DELETIONS: Show all posts, regardless of deletion status.
- IGNORE_MOD_BLOCKED_POSTS: Show posts even if blocked by followed mods.
- IGNORE_MOD_BLOCKED_USERS: Show content from users even if blocked by followed mods.
"""

import os


def require_bool_env(key: str) -> bool:
    """Read a required boolean env var. Crashes if missing or not 'true'/'false'."""
    raw = os.environ[key]  # KeyError if missing
    low = raw.strip().lower()
    if low == "true":
        return True
    if low == "false":
        return False
    raise ValueError(f"Env var {key} must be 'true' or 'false', got '{raw}'")


# ── Required env vars (validated at import time) ────────────────────────────

REGISTRATION_ENABLED = require_bool_env("REGISTRATION_ENABLED")
REGISTRATION_INVITE_CODE_REQUIRED = require_bool_env("REGISTRATION_INVITE_CODE_REQUIRED")
QUESTS_ENABLED = require_bool_env("QUESTS_ENABLED")
QUESTS_PAYOUTS_ENABLED = require_bool_env("QUESTS_PAYOUTS_ENABLED")

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
