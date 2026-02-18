# Mirage v1.13.0 Release Notes

### Overview

v1.13.0 introduces **topic blocking** — a long-requested feature that lets users hide all content from topics they don't want to see. Pick a topic, confirm the block, and every post tagged with that topic disappears from your feeds, search results, inbox, and comment trees. Blocked topics are stored on-chain and sync to the indexer, so they persist across devices and sessions. Even better, blocking is **optimistic** — posts vanish from your feed the instant you confirm, no waiting for blockchain finality.

This release also adds **wildcard topic blocking**: instead of blocking topics one by one, you can enter a glob pattern like `news*` or `*politics*` to block every topic that matches. The editable input in the block dialog lets you tweak the pattern before confirming, so a single block can cover an entire family of topics. Wildcards are validated and matched consistently across the blockchain, backend, and frontend.

On the infrastructure side, the `/server` page now shows real minting earnings computed from actual balance history instead of a theoretical projection, the test suite has been split into dedicated backend and blockchain runners, and a round of robustness fixes hardens JSON parsing against `miraged` log-line noise.

Security hardening closes a critical edge case: **NUL and control characters are now rejected on-chain and in the backend**, media URLs are validated for unsafe control characters, and the indexer strips any remaining NUL bytes before database writes. New malicious-input tests (NUL, control chars, Unicode edge cases) ensure the whole stack stays resilient.

**Upgrade Name:** `v1.13.0`

---

### Topic Blocking

Block entire topics you don't want to see. Blocked topics are filtered out of every content surface in the app.

- **Blockchain**: New `MsgBlockTopic` and `MsgUnblockTopic` message types with `target` (empty) and `topic` (field 101) fields
- **KV storage**: `plist_btopics/{address}` stores a JSON array of blocked topic strings per user
- **Tier limits**: Free users can block up to 10 topics, Tier 1 up to 125, Tier 2 up to 500, Tier 3 up to 1000
- **Topic validation**: Topics must be lowercase alphanumeric (plus `*` for wildcards), enforced at the blockchain handler and API layers
- **Indexer**: New `blocked_topics` table tracks blocks with owner, target, and position columns
- **API**: `POST /api/core/block_topic` and `POST /api/core/unblock_topic` endpoints with PoW for free-tier users
- **Public API**: `GET /api/get_user_blocked` now returns `blocked_topics` alongside `blocked_users` and `blocked_posts`

---

### Wildcard Topic Blocking

Block an entire family of topics with a single glob pattern instead of blocking them one by one.

- **Syntax**: `*` matches zero or more characters — `beer*`, `*politics`, `*news*` all work
- **Validation**: Pattern must contain at least one alphanumeric character; consecutive `**` is rejected; alphanumeric portion follows standard topic rules (2–35 chars, lowercase)
- **Blockchain**: `validateBlockedTopicPattern()` and `topicMatchesPattern()` in the handler; blocking a wildcard removes any matching followed topics
- **Backend**: Patterns converted to SQL `LIKE` clauses for feed filtering and to regex for in-memory checks
- **Frontend**: Client-side regex matching for optimistic filtering; consistent with server-side behavior
- **Editable input**: The block confirmation dialog pre-fills the post's topic and lets you edit it to add wildcards before confirming

---

### Optimistic Blocking

Posts disappear from your feed the instant you block a topic — no waiting for blockchain confirmation.

- **Immediate hide**: After confirming a block, the frontend iterates visible posts and marks matching ones as blocked; they're removed from state instantly
- **Event-driven refresh**: `TransactionHandler` dispatches a `topicBlocked` event after the transaction succeeds; `MainView` listens and refreshes the feed
- **Wildcard support**: Optimistic matching uses the same glob-to-regex logic as backend filtering

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

Filtering happens at the `_row_to_post` and `_load_candidate_posts` levels, so blocked topics are stripped before scoring, pagination, and stats loading. Wildcard patterns are expanded to SQL `LIKE` clauses at query time.

---

### Frontend

- **TransactionHandler**: `blockTopic()` and `unblockTopic()` methods with canonical signing (`MsgBlockTopic` / `MsgUnblockTopic`)
- **CardView**: "Block topic" menu item in the post action dropdown, with an editable input dialog that supports wildcard patterns
- **ViewPostView**: "Block topic" menu item in the post/comment action menus, with per-post confirmation
- **SubscriptionView**: Tier details now show `max_blocked_topics` limits instead of the removed quality posts line
- **Optimistic updates**: Blocked-topic posts removed from the feed immediately; topic follow/unfollow now updates the sidebar and card menus without a page refresh

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

### Follow/Block Mutual Exclusion

Following and blocking are now mutually exclusive — both on-chain and in the indexer.

- **Blockchain**: Blocking a user/topic automatically removes any existing follow for that user/topic, and vice versa
- **Indexer**: Mirrors the same mutual exclusion logic in the PostgreSQL database
- **Frontend**: `/follows` and `/blocks` are now dedicated routes with unfollow/unblock buttons; added to avatar dropdown under settings

---

### Minting Increase

Minting rate increased ~357x to support the growing network.

- **MintQuantity**: `350,000,000` → `125,000,000,000` umirage (350 MIRAGE → 125,000 MIRAGE per 10min)
- **Daily output**: ~18,000,000 MIRAGE/day (previously ~50,400 MIRAGE/day)
- **Server page**: Now displays "Earned (24h)" computed from actual node balance history (sum of positive deltas over the last 24 hours), replacing the old theoretical projection

---

### Test Suite

The test suite has been split and expanded for better coverage.

- **Split**: `test_local.py` separated into `test_backend.py` (API endpoint tests) and `test_blockchain.py` (direct relay/chain tests)
- **Wildcard tests**: Dedicated tests for wildcard block topic patterns across both backend and blockchain suites
- **Malicious inputs**: Added NUL/control-char rejection tests and media URL validation in both backend and blockchain suites
- **Unicode edge cases**: Content/title with zero-width, bidi, combining, and emoji are accepted; Unicode topics are rejected
- **Scale**: Backend suite now spans **520** checks; blockchain suite **146** checks (pass/fail + chain deliver/reject assertions)
- **Robustness**: All JSON parsing now locates the first `{` or `[` in `miraged` output, skipping log lines that previously broke parsers
- **Faucet fix**: Faucet sequence mismatch errors handled with retry on code 32
- **Gov module**: Address parsing now handles the `{type, value: {address}}` response format alongside `{base_account: {address}}`

---

### Input Validation Hardening

Defense-in-depth against malformed text inputs and database-stalling bytes.

- **Blockchain**: `validateSafeText` rejects NUL, C0 control chars (except tab/newline/CR), DEL, and invalid UTF-8 in `Post`, `Edit`, `SetUsername`, and media URLs
- **Backend**: `_has_unsafe_chars` blocks the same character classes in `core_post`, `core_edit`, `core_set_username`, and media validation
- **Indexer**: `_strip_nul` safety net applied to posts, profiles, and topic tables to prevent PostgreSQL NUL errors
- **Behavior**: Unicode content remains fully supported; only unsafe control characters are blocked

---

### Stress & Spam Testing

The spam-attack harness can flood the chain with concurrent transactions for soak testing.

- **Harness**: `tests/test_spam.py` (multi-worker posts/votes/comments, live TPS + latency stats)
- **Configurable**: worker count, duration, and mode allow 10k+ tx runs when needed
- **Use**: run against local docker to validate PoW stability and throughput under load

---

### Bug Fixes

- Fixed `miraged` printing log lines to stdout before JSON, breaking command output parsing
- Fixed `_miraged_cmd` and `_keyring_backend` failing on multi-line bash login output
- Fixed gov module address parsing for `type/value` response format
- Fixed topic follow/unfollow not updating sidebar and card menus without a page refresh
- Fixed faucet sequence mismatch in test suite by retrying on code 32
- Fixed `search_topics` 500 error caused by log-line noise in query output
- Prevented indexer stalls caused by NUL/control bytes in posts, media URLs, and profile fields

---

### Upgrade Handler

The v1.13.0 upgrade handler migrates existing chain state:

- Clears any leftover `quality_posts` data from all profiles
- Updates tier parameters to include the new `max_blocked_topics` values
- Initializes empty `blocked_topics` lists for all existing profiles
- Updates `MintQuantity` from 350,000,000 to 125,000,000,000

---

### Roadmap

- Push notifications for mentions and replies
- Threaded conversations with inline reply chains

Have a feature suggestion? Let us know on [Mirage](https://mirage.talk) — post it in the #feedback topic or message us directly.
