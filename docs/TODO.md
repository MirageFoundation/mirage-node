# TODO

## Architecture

### Language Consistency: Go Everywhere
- Current: Go (chain, orchestrator) + Python (indexer, backend) + JavaScript (frontend)
- Problem: Canonical serialization must match across Go/Python/JS. This is a maintenance nightmare and a source of subtle bugs (uvarint, encStr, encBytes, field ordering).
- Recommendation: Write indexer in Go, write backend in Go, keep JS on frontend. Reduce cross-language surface from 3 languages to 2.

### Use Protobuf Code Generation (No Dynamic Building)
- Current: `datatypes.py` manually builds protobuf descriptors at runtime:
  ```
  msg = file_proto.message_type.add()
  msg.name = "MsgPost"
  add_f(msg, "authority", 1, TYPE_STRING)
  add_f(msg, "envelope_pubkey", 2, TYPE_BYTES)
  # ... 50+ fields across 20+ message types
  ```
- Problem: Every Go field change must be manually mirrored in Python. Field numbers are duplicated. No compile-time verification.
- Recommendation: Use `buf generate` with Python output so `.proto` files are the single source of truth.

### Event Sourcing for the Indexer
- Current: Indexer processes blocks and directly mutates PostgreSQL.
- Recommendation: Store raw block events first, then derive views.
  - Rebuild any view without re-syncing
  - Easier debugging (replay specific events)
  - Cleaner separation between "what happened" and "current state"

## Infrastructure / Ops

### Node DB Compaction Strategy — RESOLVED
- **PebbleDB migration (Feb 2026) succeeded.** All nodes now run `app-db-backend = "pebbledb"` + `db_backend = "pebbledb"`. Compaction is working: application.db SST files are actively created and deleted (e.g., file numbers up to 13k with only ~1.5k files remaining).
- **Disk growth was NOT from PebbleDB.** The real culprits were:
  1. **CometBFT consensus WAL (`cs.wal/`)**: Rotated segments (`wal.NNN`) were never cleaned. ~200MB/day of unbounded growth. Fixed in `entrypoint.sh` — periodic cleanup now deletes rotated WAL segments older than 1 day.
  2. **Node logs**: 43MB/day with 30-day retention = ~1.3GB steady state. Acceptable.
  3. **tx_index.db**: Switched to `indexer = "null"` — no longer grows. Existing `tx_index.db/` dirs can be deleted on each node after deploy.

## Short-term cleanup (remove after March)
- Remove legacy handling of embedding image/media when the first line is a link. The `media` field already covers this.

## NEXT RELEASE: Drop migrated tables from indexer DB
After confirming `scripts/migrate_backend_db.py` has run on production, DROP these tables from the **indexer** database (`mirage_indexer`). They now live in `mirage_backend` and the indexer no longer reads or writes them:
```
push_tokens, push_budget, push_throttle, push_receipts, push_nonces,
user_daily_quests, user_flash_quests, user_quest_state,
user_achievements, pending_rewards, user_unlocks, reward_suspensions,
user_similarity_cache
```
Run `scripts/verify_upgrade.py` after dropping — warnings in section 7 should disappear.

## Performance
- Generally optimize website. Find bottlenecks. Use Firefox profiler.

## Moderation / Anti-botting

### Relay Blocking (v1.18.0 infrastructure ready)
The `relayer` field (the validator/node address that submitted a transaction) is now stored on `posts`, `votes`, and `awards` in the indexer DB, indexed via `idx_*_relayer_lower`, and exposed in all API responses. Filtering logic is not yet implemented.

**Two levels of blocking:**

1. **Node-level (operator):** The backend operator maintains a blocklist of rogue relay addresses. All content from blocked relays is excluded from API responses for every user on that node. Implementation: add `AND COALESCE(LOWER(p.relayer), '') NOT IN (...)` to the SQL queries in `web/backend/routes/public.py`, same pattern as `blocked_users`/`blocked_posts`. Blocklist could be a config file, env var, or admin endpoint.

2. **User-level (end-user preference):** Individual users can block relays the same way they block users or posts. Requires a new `blocked_relayers` table or extending the existing block tables, plus client UI to manage the list. The backend would merge user-level blocked relays into the existing per-request filter set.

## Content / UX
- Add blocking keywords (in topics or posts)?
- **On-chain `allowed_tags` (content filter preferences):** Currently `allowed_tags` is a client-side localStorage preference passed as a query param. Move it to `ProfileCore` on-chain so preferences sync across devices and the backend can enforce without trusting the client. Requires: proto field on `ProfileCore`, upgrade handler, indexer migration, backend reads from indexer DB instead of query param, new `MsgSetContentFilter` tx type. The backend would still accept the query param as an override for unauthenticated/guest users.

## Engagement
- **Streaks:** Track consecutive days of activity (posting, voting, etc.). Could be implemented as a quest type — e.g. "7-day streak" quest with token reward. Resets on missed day.
- **App store reviews:** Reward users for leaving a 5-star review on the app store. Verification is tricky — no reliable API to confirm reviews. Options: manual confirmation (user submits screenshot, admin approves), honor-system with fraud detection, or tie it to a referral/invite code printed on the review confirmation screen.

## Security
- Full security audit for every module.


# add something for cloudflare:
- so that videos and images with zero views get deleted

## Testing

### Frontend E2E Tests
- Current: Only two trivial Jest unit tests in `web/frontend/src/utils/__tests__/`. No real frontend coverage.
- Recommendation: Add headless Playwright tests in `tests/` (alongside `test_backend.py` and `test_blockchain.py`). Should cover core user flows: wallet creation, posting, voting, username setup, subscription, agent management. Run against the local Docker testnet the same way backend tests do.

# Other Ideas:
- Allow only 3 new profiles (set_username) per minute
- rename `porn` category to `explicit`

# We should explicitly add LINK as field (like media)
- and something like youtube or redgifs link should just be media link?

# New agent ideas:
- Real User agent: keeps tabs on every user and assigns them a trust score


# Video Series ideas:
- explaining the /network tab, e.g. show how difficulty spikes, how spam is handled and so on


