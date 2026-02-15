# Mirage v1.13.0 Release Notes

### Overview

v1.13.0 introduces **topic blocking** — a long-requested feature that lets users hide all content from topics they don't want to see. It works just like blocking users and posts: pick a topic, confirm the block, and every post tagged with that topic disappears from your feeds, search results, inbox, and comment trees. Blocked topics are stored on-chain and sync to the indexer, so they persist across devices and sessions.

The release also removes the unused `quality_posts` infrastructure that was partially implemented in earlier versions but never shipped. The TierConfig slot it occupied has been repurposed for `max_blocked_topics`, with tier-dependent limits: 10 for free users, 125 for Tier 1, 500 for Tier 2, and 1000 for Tier 3.

**Upgrade Name:** `v1.13.0`

---

### Topic Blocking

Block entire topics you don't want to see. Blocked topics are filtered out of every content surface in the app.

- **Blockchain**: New `MsgBlockTopic` and `MsgUnblockTopic` message types with `target` (empty) and `topic` (field 101) fields
- **KV storage**: `plist_btopics/{address}` stores a JSON array of blocked topic strings per user
- **Tier limits**: Free users can block up to 10 topics, Tier 1 up to 125, Tier 2 up to 500, Tier 3 up to 1000
- **Topic validation**: Topics must be lowercase alphanumeric, enforced at the blockchain handler and API layers
- **Indexer**: New `blocked_topics` table tracks blocks with owner, target, and position columns
- **API**: `POST /api/core/block_topic` and `POST /api/core/unblock_topic` endpoints with PoW for free-tier users
- **Public API**: `GET /api/get_user_blocked` now returns `blocked_topics` alongside `blocked_users` and `blocked_posts`

---

### Feed & Search Filtering

Posts from blocked topics are excluded everywhere content is served.

- Home feed (magic, newest, and guest variants)
- Following feed (magic and newest)
- User posts (`/api/get_user_posts`)
- Search results (`/api/search`)
- Single post view (`/api/get_post`)
- Comment trees (nested replies under a blocked topic are hidden)
- Inbox notifications
- Topic listings and topic search

Filtering happens at the `_row_to_post` and `_load_candidate_posts` levels, so blocked topics are stripped before scoring, pagination, and stats loading.

---

### Frontend

- **TransactionHandler**: `blockTopic()` and `unblockTopic()` methods with canonical signing (`MsgBlockTopic` / `MsgUnblockTopic`)
- **CardView**: "Block topic" menu item in the post action dropdown, with confirmation dialog
- **ViewPostView**: "Block topic" menu item in the post/comment action menus, with per-post confirmation
- **SubscriptionView**: Tier details now show `max_blocked_topics` limits instead of the removed quality posts line

---

### quality_posts Removal

The partially implemented `quality_posts` feature has been fully removed.

- **Proto**: `max_quality_posts` renamed to `max_blocked_topics` in `TierConfig` (field 7); `quality_posts` renamed to `blocked_topics` in `InitialProfile` and `QueryProfileResponse`
- **KV store**: `plist_quality/` prefix replaced with `plist_btopics/`
- **Keeper**: `SetProfileQualityPosts` / `GetProfileQualityPosts` replaced with `SetProfileBlockedTopics` / `GetProfileBlockedTopics`
- **Indexer**: `quality_posts` table replaced with `blocked_topics` table
- **Settings**: `DB_MAX_QUALITY_POSTS` replaced with `DB_MAX_BLOCKED_TOPICS`
- **Frontend**: No quality_posts references remained; SubscriptionView already updated

---

### Upgrade Handler

The v1.13.0 upgrade handler migrates existing chain state:

- Clears any leftover `quality_posts` data from all profiles
- Updates tier parameters to include the new `max_blocked_topics` values
- Initializes empty `blocked_topics` lists for all existing profiles

---

### Roadmap

- Push notifications for mentions and replies
- Threaded conversations with inline reply chains
- Keyword-level content filtering

Have a feature suggestion? Let us know on [Mirage](https://mirage.talk) — post it in the #feedback topic or message us directly.
