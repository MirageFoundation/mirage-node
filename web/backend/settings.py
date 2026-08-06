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
import time


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

# Public media uploads. Must only be true where a scanning edge (Bunny Shield
# upload scanning) fronts uploads, so no unscanned media can reach the node.
# Default-true preserves existing behavior; only an explicit "false" disables it
# (set per-node by migration on any node not behind a scanning edge). When false,
# /api/upload_media and the legacy /api/get_upload_url return 403.
MEDIA_UPLOADS_ENABLED = os.environ.get("MEDIA_UPLOADS_ENABLED", "true").strip().lower() != "false"

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

# Grace period for POST /api/rewards/claim while installed mobile builds catch
# up. ISO date (YYYY-MM-DD, UTC). While today < this date, a claim whose identity
# proof is absent OR fails verification is served but logged under
# authz.legacy_unsigned; on/after it, either is a 401.
# Self-expiring: removing the branch later does not change post-cutoff behaviour.
# Extended from 2026-09-05 because the original window rejected any client that
# sent a signature it could not verify, so no installed mobile build could claim
# for the whole first month of it.
LEGACY_UNSIGNED_UNTIL = os.environ.get("LEGACY_UNSIGNED_UNTIL", "2026-10-05").strip()


def legacy_unsigned_claim_allowed(now_ts: float | None = None) -> bool:
    """True while the rewards/claim legacy-proof grace period is still open."""
    if not LEGACY_UNSIGNED_UNTIL:
        return False
    from datetime import datetime, timezone

    cutoff = datetime.strptime(LEGACY_UNSIGNED_UNTIL, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    now = datetime.fromtimestamp(now_ts if now_ts is not None else time.time(), tz=timezone.utc)
    return now < cutoff
