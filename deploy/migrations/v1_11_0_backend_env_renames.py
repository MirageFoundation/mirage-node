"""
Migration: v1.11.0 - Rename backend.env vars for clarity

Renames environment variables in backend.env to use proper domain prefixes:

Registration domain:
- INVITE_CODES_REQUIRED -> REGISTRATION_INVITE_CODE_REQUIRED

Backend domain:
- GUNICORN_WORKERS -> BACKEND_GUNICORN_WORKERS

Quest domain:
- DAILY_QUESTS_COUNT -> QUESTS_DAILY_COUNT
- FLASH_QUESTS_COUNT -> QUESTS_FLASH_COUNT
- FLASH_QUEST_MIN_INTERVAL_HOURS -> QUESTS_FLASH_MIN_INTERVAL_HOURS
- FLASH_QUEST_MAX_INTERVAL_HOURS -> QUESTS_FLASH_MAX_INTERVAL_HOURS
- PAYOUTS_ENABLED -> QUESTS_PAYOUTS_ENABLED
- REWARDS_POOL_ADDRESS -> QUESTS_REWARDS_POOL_ADDRESS
- INVITE_RECRUIT_CHANCE -> QUESTS_INVITE_RECRUIT_CHANCE
- INVITE_EARNER_QUEST_INTERVAL -> QUESTS_INVITE_EARNER_INTERVAL
- INVITE_EARNER_CHANCE -> QUESTS_INVITE_EARNER_CHANCE

All operations are idempotent - safe to run multiple times.
"""

import re
from pathlib import Path

MIGRATION_KEY = "v1_11_0_backend_env_renames"
DESCRIPTION = "Rename backend.env vars to use REGISTRATION_*/BACKEND_*/QUESTS_* prefixes"

# Map of old key -> new key
RENAMES = {
    "INVITE_CODES_REQUIRED": "REGISTRATION_INVITE_CODE_REQUIRED",
    "GUNICORN_WORKERS": "BACKEND_GUNICORN_WORKERS",
    "DAILY_QUESTS_COUNT": "QUESTS_DAILY_COUNT",
    "FLASH_QUESTS_COUNT": "QUESTS_FLASH_COUNT",
    "FLASH_QUEST_MIN_INTERVAL_HOURS": "QUESTS_FLASH_MIN_INTERVAL_HOURS",
    "FLASH_QUEST_MAX_INTERVAL_HOURS": "QUESTS_FLASH_MAX_INTERVAL_HOURS",
    "PAYOUTS_ENABLED": "QUESTS_PAYOUTS_ENABLED",
    "REWARDS_POOL_ADDRESS": "QUESTS_REWARDS_POOL_ADDRESS",
    "INVITE_RECRUIT_CHANCE": "QUESTS_INVITE_RECRUIT_CHANCE",
    "INVITE_EARNER_QUEST_INTERVAL": "QUESTS_INVITE_EARNER_INTERVAL",
    "INVITE_EARNER_CHANCE": "QUESTS_INVITE_EARNER_CHANCE",
    # Handle intermediate renames (QUEST_ -> QUESTS_) for nodes that already ran a partial migration
    "QUEST_PAYOUTS_ENABLED": "QUESTS_PAYOUTS_ENABLED",
    "QUEST_REWARDS_POOL_ADDRESS": "QUESTS_REWARDS_POOL_ADDRESS",
    "QUEST_INVITE_RECRUIT_CHANCE": "QUESTS_INVITE_RECRUIT_CHANCE",
    "QUEST_INVITE_EARNER_INTERVAL": "QUESTS_INVITE_EARNER_INTERVAL",
    "QUEST_INVITE_EARNER_CHANCE": "QUESTS_INVITE_EARNER_CHANCE",
}


def run(config_dir: Path, logger) -> str:
    """Run the migration."""
    config_dir = Path(config_dir)
    backend_env = config_dir / "backend.env"

    if not backend_env.exists():
        logger.info("    backend.env not found, skipping")
        return "skipped (no backend.env)"

    content = backend_env.read_text()
    renamed = []

    for old_key, new_key in RENAMES.items():
        # Check if old key exists and new key doesn't
        if re.search(rf"^{re.escape(old_key)}=", content, re.MULTILINE):
            if not re.search(rf"^{re.escape(new_key)}=", content, re.MULTILINE):
                # Rename the key
                content = re.sub(
                    rf"^{re.escape(old_key)}=",
                    f"{new_key}=",
                    content,
                    flags=re.MULTILINE,
                )
                renamed.append(f"{old_key} -> {new_key}")
                logger.info(f"    Renamed {old_key} -> {new_key}")

    if renamed:
        backend_env.write_text(content)
        return f"renamed: {', '.join(renamed)}"

    return "no changes needed"
