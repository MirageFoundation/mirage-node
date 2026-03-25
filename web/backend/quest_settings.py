"""Quest system settings (moved from indexer/settings.py during DB split)."""

# ========== Quest System Settings ==========
# Feature flags - set to False to disable without code changes
QUESTS_ENABLED = True
ACHIEVEMENTS_ENABLED = True

# Quest assignment
QUESTS_DAILY_COUNT = 2  # Number of random daily quests per user
QUESTS_FLASH_MIN_INTERVAL_HOURS = 5  # Minimum hours between flash quests
QUESTS_FLASH_MAX_INTERVAL_HOURS = 7  # Maximum hours between flash quests

# Special quest gating
QUESTS_INVITE_RECRUIT_CHANCE = 0.30  # 30% daily chance for invite_recruit quest (if user has unused codes)
QUESTS_INVITE_EARNER_INTERVAL = 10  # invite_earner quest appears every N completed quests
QUESTS_INVITE_EARNER_CHANCE = 0.30  # 30% daily chance for invite_earner quest (if eligible)

# Reward multiplier (quest-completion-based)
REWARD_MULTIPLIER_QUESTS = 50  # Completed quests to reach max multiplier
REWARD_MULTIPLIER_MAX = 5.0  # Maximum multiplier (0 quests = 0x, 50 quests = 5x)

# Daily reward cap (in umirage, 0 = no cap)
DAILY_REWARD_CAP = 0
