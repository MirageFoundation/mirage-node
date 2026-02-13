# Mirage v1.10.1 Release Notes

### Overview

Get rewarded for being part of the conversation. v1.10.1 introduces the Quest System—a gamification layer that turns daily engagement into MIRAGE tokens. Post your thoughts, vote on content you care about, follow interesting people—and watch the rewards roll in.

The system is designed to reward genuine participation, not grinding. Daily quests reset every 24 hours with achievable goals. Flash quests pop up randomly throughout the day for bonus opportunities. And the longer you've been part of the community, the more you earn—account age multipliers boost rewards up to 5x for established members.

This is just the beginning. The Quest System lays the foundation for a richer engagement layer where quality contributions are recognized and rewarded. Your voice matters—now it pays too.

---

### Quest System

- Daily quests: Create posts, vote on content, follow users and topics
- Flash quests: Time-limited bonus quests that appear randomly
- Real-time progress tracking with animated UI
- Automatic quest refresh every 24 hours
- Achievement tracking for long-term engagement

---

### Rewards Distribution

- MIRAGE token rewards paid directly to your wallet
- Account-age multiplier: 1x to 5x over your first 30 days
- Claim rewards with a single tap
- Public rewards stats showing total distributed
- Transparent on-chain transfers

---

### Rewards Pool Setup

- New `setup_rewards_pool.py` script for node operators
- Interactive wallet configuration with balance checks
- Enable/disable quests and payouts per node
- `--config` flag for updating existing settings

---

### Bug fixes

- Fix reward claim error handling
- Fix blocked user/post confirmation dialogs
- Fix donate UI edge cases

---

### For developers

- **API:** `GET /api/quests` - Quest definitions and user progress
- **API:** `POST /api/quests/claim` - Claim completed quest rewards
- **API:** `GET /api/rewards/stats` - Public rewards statistics
- **New script:** `deploy/setup_rewards_pool.py`
- **Env vars:** `QUESTS_ENABLED`, `QUEST_PAYOUTS_ENABLED`, `QUEST_REWARDS_POOL_ADDRESS`
