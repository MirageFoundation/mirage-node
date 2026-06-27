"""
Mirage Backend Settings
This module configures runtime behavior for the backend server.
Changes take effect when the server is restarted.

Variables:
- IGNORE_DELETIONS: Show all posts, regardless of deletion status.
- IGNORE_AGENT_BLOCKED_POSTS: Show posts even if blocked by enabled agents.
- IGNORE_AGENT_BLOCKED_USERS: Show content from users even if blocked by enabled agents.
- AUTO_ENABLED_AGENTS: Comma-separated agent mirage1 addresses injected for every user.
"""

import os
import re


def require_bool_env(key: str) -> bool:
    """Read a required boolean env var. Crashes if missing or not 'true'/'false'."""
    raw = os.environ[key]  # KeyError if missing
    low = raw.strip().lower()
    if low == "true":
        return True
    if low == "false":
        return False
    raise ValueError(f"Env var {key} must be 'true' or 'false', got '{raw}'")


def _parse_address_csv_env(key: str) -> tuple[str, ...]:
    raw = os.environ.get(key, "").strip()
    if not raw:
        return ()
    values: list[str] = []
    seen: set[str] = set()
    for part in raw.split(","):
        value = part.strip()
        if not value:
            raise ValueError(f"Env var {key} contains an empty entry")
        lower = value.lower()
        if not re.fullmatch(r"mirage1[0-9a-z]{38}", lower):
            raise ValueError(f"Env var {key} must contain comma-separated mirage1 addresses, got '{value}'")
        if lower in seen:
            raise ValueError(f"Env var {key} contains duplicate entry '{value}'")
        seen.add(lower)
        values.append(lower)
    return tuple(values)


# ── Required env vars (validated at import time) ────────────────────────────

REGISTRATION_ENABLED = require_bool_env("REGISTRATION_ENABLED")
REGISTRATION_INVITE_CODE_REQUIRED = require_bool_env("REGISTRATION_INVITE_CODE_REQUIRED")
OPEN_BROWSING_ENABLED = require_bool_env("OPEN_BROWSING_ENABLED")
QUESTS_ENABLED = require_bool_env("QUESTS_ENABLED")
QUESTS_PAYOUTS_ENABLED = require_bool_env("QUESTS_PAYOUTS_ENABLED")
PUSH_NOTIFICATIONS_ENABLED = require_bool_env("PUSH_NOTIFICATIONS_ENABLED")

EXPO_ACCESS_TOKEN = os.environ.get("EXPO_ACCESS_TOKEN", "")

# Trending post push notifications. When false, the trending poller does nothing.
TRENDING_PUSH_ENABLED = require_bool_env("TRENDING_PUSH_ENABLED")

ANDROID_BANNER_ENABLED = require_bool_env("ANDROID_BANNER_ENABLED")
IOS_BANNER_ENABLED = require_bool_env("IOS_BANNER_ENABLED")

# Moderation Settings
# When false (default), standard moderation rules apply:
# - Deleted posts are hidden
# - Blocked posts from enabled agents are hidden
# - Content from blocked users (by enabled agents) is hidden
#
# Set to true to override and show all content:

# Show all posts, regardless of whether they are marked as deleted
IGNORE_DELETIONS = False

# Show all posts, even if blocked by enabled agents (only apply your own blocks)
IGNORE_AGENT_BLOCKED_POSTS = False

# Show all content from users, even if blocked by enabled agents (only apply your own blocks)
IGNORE_AGENT_BLOCKED_USERS = False

# Comma-separated agent mirage1 addresses to serve as enabled for every user.
AUTO_ENABLED_AGENTS = _parse_address_csv_env("AUTO_ENABLED_AGENTS")

# New-user highlight: number of days after registration to show green "New User" badge.
# Set to 0 to disable the feature entirely.
NEW_USER_HIGHLIGHT_DAYS = int(os.environ.get("NEW_USER_HIGHLIGHT_DAYS", "7"))
