# v1.16.0: Agent System & Tier Simplification

This major release rebrands the "moderator" system to "agents" and simplifies the subscription model.

## Key Changes

### 1. Terminology: Moderator → Agent
- **Old:** Moderators, Followed Moderators, `MsgFollowModerator`, `MsgUnfollowModerator`
- **New:** Agents, Enabled Agents, `MsgEnableAgent`, `MsgDisableAgent`
- **Semantics:** Users "enable" agents to curate their feed, rather than "following" them. Agents are users whose actions (blocks, votes) propagate to those who enable them.

### 2. Tier Simplification & Renumbering
The subscription model has been simplified to three clear tiers, with a new numbering scheme to allow for future expansion:

- **Free (Level 0):** Basic access. No profile customization. PoW required for actions.
- **Subscriber (Level 1):** Paid tier (100K MIRAGE/mo). Profile customization (bio, avatar, banner). No PoW required. Higher limits.
- **Agent (Level 10):** Paid tier (200K MIRAGE/mo). All Subscriber features + **Eligible to be an Agent**. Can set a custom "Flair".

**Level 100+:** Admin levels (governance-assigned only).
**Levels 2-9:** Reserved for future subscription tiers. Invalid for user self-upgrade — the chain will reject `MsgUpgradeLevel` for any level other than 1 or 10.
**Removed Tiers:** "Trusted", "Established", "Distinguished" are gone.

#### Tier Limits

| Parameter | Free (0) | Subscriber (1) | Agent (10) |
|---|---|---|---|
| `period_fee` | 0 | 100B umirage | 200B umirage |
| `max_enabled_agents` | 25 | 500 | 500 |
| `max_followed_users` | 25 | 500 | 500 |
| `max_followed_topics` | 25 | 500 | 500 |
| `max_blocked_users` | 25 | 500 | 500 |
| `max_blocked_posts` | 25 | 500 | 500 |
| `max_blocked_topics` | 25 | 500 | 500 |
| `max_title_length` | 150 | 300 | 300 |
| `max_content_length` | 1,000 | 20,000 | 20,000 |
| `editing_time_mins` | 10 | 360 | 360 |
| `vote_weight` | 1.0 | 1.33 | 1.33 |
| `can_be_agent` | no | no | **yes** |
| `can_remove_anon` | no | yes | yes |
| `can_have_biography` | no | yes | yes |
| `can_have_avatar` | no | yes | yes |
| `can_have_banner` | no | yes | yes |
| `can_have_flair` | no | yes | yes |

#### List Limit Behavior

- **`enabled_agents`, `followed_users`, `followed_topics`:** Hard cap — the chain rejects the transaction when the limit is reached. The user must disable/unfollow first.
- **`blocked_users`, `blocked_posts`, `blocked_topics`:** Deque — the chain evicts the oldest entry when the limit is exceeded. The indexer stores the full history (up to 100k) so feed filtering still sees old blocks.

### 3. Profile Changes
- **Removed:** `is_moderator` (replaced by Tier 10 eligibility check)
- **Added:** `flair` (custom string for Agents, up to 20 chars)
- **Renamed:** `followed_moderators` → `enabled_agents`

### 4. Protocol Changes
- **KV Store Migration:** `plist_mods/` prefix migrated to `plist_agents/`.
- **Message Types:** `MsgFollowModerator` renamed to `MsgEnableAgent`, `MsgUnfollowModerator` to `MsgDisableAgent`.
- **New: `MsgSetAgents`** — atomically replaces the user's entire ordered enabled agents list in a single transaction. Accepts `repeated string agents = 101` (field 101). Validates addresses, rejects duplicates, enforces `max_enabled_agents` per tier. Replaces the need for separate enable/disable calls when reordering or bulk-updating agents.
- **Legacy Support:** Old message types (`MsgEnableAgent`, `MsgDisableAgent`) are still registered for historical block decoding. New agent management should use `MsgSetAgents`.

### 5. Indexer & Backend
- Indexer automatically migrates `followed_mods` table to `enabled_agents`.
- Backend endpoints updated: `/api/core/enable_agent`, `/api/core/disable_agent` (legacy), and new `/api/core/set_agents` (preferred).
- Indexer handles `MsgSetAgents` by refreshing the enabled_agents list from chain state. Historical `MsgEnableAgent`/`MsgDisableAgent` transactions are still decoded for replay.
- Frontend updated to reflect new tier system, Agent terminology, and uses `MsgSetAgents` for all agent management.

## Upgrade Guide
This is a breaking change. Nodes must upgrade to v1.16.0 binary to continue syncing. The upgrade handler will automatically:
1. Migrate KV store data (`plist_mods/` → `plist_agents/`).
2. Update chain parameters to new tier defaults (3 tiers: Free, Subscriber, Agent).
3. Strip `is_moderator` field from existing profiles.
4. Remap existing user levels: old 2 (Established) → 1 (Subscriber), old 3 (Distinguished) → 10 (Agent).
