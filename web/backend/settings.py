"""
Mirage Backend Settings
This module configures runtime behavior for the backend server.
Changes take effect when the server is restarted.

Variables:
- IGNORE_DELETIONS: Show all posts, regardless of deletion status.
"""

import logging
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


def require_int_env(key: str, minimum: int | None = None) -> int:
    """Read a required integer env var. Crashes if missing or out of range."""
    raw = os.environ[key]  # KeyError if missing
    try:
        value = int(raw.strip())
    except ValueError as e:
        raise ValueError(f"Env var {key} must be an integer, got '{raw}'") from e
    if minimum is not None and value < minimum:
        raise ValueError(f"Env var {key} must be >= {minimum}, got {value}")
    return value


def require_probability_env(key: str) -> float:
    """Read a required probability env var in [0, 1]."""
    raw = os.environ[key]  # KeyError if missing
    try:
        value = float(raw.strip())
    except ValueError as e:
        raise ValueError(f"Env var {key} must be a number, got '{raw}'") from e
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"Env var {key} must be between 0 and 1, got {value}")
    return value


# ── Required env vars (validated at import time) ────────────────────────────

REGISTRATION_ENABLED = require_bool_env("REGISTRATION_ENABLED")
REGISTRATION_INVITE_CODE_REQUIRED = require_bool_env("REGISTRATION_INVITE_CODE_REQUIRED")
if REGISTRATION_INVITE_CODE_REQUIRED:
    # v1.39 dropped invite_codes together with the referral tables, so an
    # invite-gated node could accept no signup at all. Refuse to start rather
    # than fail every registration at query time.
    raise ValueError("REGISTRATION_INVITE_CODE_REQUIRED must be false: invite codes were removed in v1.39")
OPEN_BROWSING_ENABLED = require_bool_env("OPEN_BROWSING_ENABLED")
QUESTS_ENABLED = require_bool_env("QUESTS_ENABLED")
QUESTS_PAYOUTS_ENABLED = require_bool_env("QUESTS_PAYOUTS_ENABLED")
ACHIEVEMENTS_ENABLED = require_bool_env("ACHIEVEMENTS_ENABLED")
PUSH_NOTIFICATIONS_ENABLED = require_bool_env("PUSH_NOTIFICATIONS_ENABLED")

# Quest assignment shape. Every path that assigns or tracks quests reads these;
# a second hardcoded copy used to keep quests running on nodes that had them off.
QUESTS_DAILY_COUNT = require_int_env("QUESTS_DAILY_COUNT", minimum=0)
QUESTS_FLASH_COUNT = require_int_env("QUESTS_FLASH_COUNT", minimum=0)
QUESTS_FLASH_MIN_INTERVAL_HOURS = require_int_env("QUESTS_FLASH_MIN_INTERVAL_HOURS", minimum=0)
QUESTS_FLASH_MAX_INTERVAL_HOURS = require_int_env("QUESTS_FLASH_MAX_INTERVAL_HOURS", minimum=0)
if QUESTS_FLASH_MIN_INTERVAL_HOURS > QUESTS_FLASH_MAX_INTERVAL_HOURS:
    raise ValueError(
        "QUESTS_FLASH_MIN_INTERVAL_HOURS must not exceed QUESTS_FLASH_MAX_INTERVAL_HOURS "
        f"(min={QUESTS_FLASH_MIN_INTERVAL_HOURS}, max={QUESTS_FLASH_MAX_INTERVAL_HOURS})"
    )

# Special quest gating. A zero chance means the quest is never offered, which is
# how referral payouts are switched off.
QUESTS_INVITE_RECRUIT_CHANCE = require_probability_env("QUESTS_INVITE_RECRUIT_CHANCE")
QUESTS_INVITE_EARNER_CHANCE = require_probability_env("QUESTS_INVITE_EARNER_CHANCE")
QUESTS_INVITE_EARNER_INTERVAL = require_int_env("QUESTS_INVITE_EARNER_INTERVAL", minimum=1)

QUESTS_REWARDS_POOL_ADDRESS = os.environ.get("QUESTS_REWARDS_POOL_ADDRESS", "").strip().lower()
if QUESTS_PAYOUTS_ENABLED and not re.fullmatch(r"mirage1[0-9a-z]{38}", QUESTS_REWARDS_POOL_ADDRESS):
    raise ValueError(
        "QUESTS_PAYOUTS_ENABLED=true requires QUESTS_REWARDS_POOL_ADDRESS to be a mirage1 address, "
        f"got '{QUESTS_REWARDS_POOL_ADDRESS}'"
    )

# Public media uploads. Must only be true where a scanning edge (Bunny Shield
# upload scanning) fronts uploads, so no unscanned media can reach the node. A
# node with no scanning edge sets this false and /api/upload_media returns 403.
MEDIA_UPLOADS_ENABLED = require_bool_env("MEDIA_UPLOADS_ENABLED")

# Every other security-relevant setting in this module is required; this one was
# silently defaulted, and empty means _expo_headers omits the Authorization header
# entirely — so a missing or mistyped token quietly downgraded to unauthenticated
# pushes instead of failing. Required only when push is actually on, since a node
# with push disabled has no reason to hold an Expo credential.
EXPO_ACCESS_TOKEN = os.environ.get("EXPO_ACCESS_TOKEN", "").strip()
if PUSH_NOTIFICATIONS_ENABLED and not EXPO_ACCESS_TOKEN:
    # Not raised, deliberately. Every node in the fleet currently runs push with
    # this key present but empty, so failing the import would take the whole fleet
    # offline on upgrade. Empty means _expo_headers omits Authorization entirely,
    # and Expo accepts unauthenticated sends unless the project has enhanced
    # security switched on — so anyone holding a copy of the push-token table can
    # push arbitrary text to users. Closing that needs a token issued and enforcement
    # enabled in the Expo dashboard first; this logs loudly until then.
    logging.getLogger(__name__).error(
        "EXPO_ACCESS_TOKEN is empty while PUSH_NOTIFICATIONS_ENABLED=true: "
        "push sends are unauthenticated. Set a token and enable enhanced security in Expo."
    )

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

# New-user highlight: number of days after registration to show green "New User" badge.
# Set to 0 to disable the feature entirely.
NEW_USER_HIGHLIGHT_DAYS = int(os.environ.get("NEW_USER_HIGHLIGHT_DAYS", "7"))
