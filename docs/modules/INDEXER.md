# Mirage Blockchain Indexer

This document provides a comprehensive technical overview of the Mirage blockchain indexer, the off-chain service responsible for consuming blockchain data and maintaining a queryable PostgreSQL database for the web backend. It is intended for senior engineers, architects, and project managers who need to understand the system's design philosophy, data transformation logic, and the rationale behind key implementation choices.

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture Philosophy](#architecture-philosophy)
3. [Event-Driven Processing Model](#event-driven-processing-model)
4. [Component Structure](#component-structure)
5. [Message Processing](#message-processing)
6. [Database Schema](#database-schema)
7. [Denormalization Strategy](#denormalization-strategy)
8. [Vote Weighting System](#vote-weighting-system)
9. [Profile Synchronization](#profile-synchronization)
10. [Governance Proposal Handling](#governance-proposal-handling)
11. [Content Processing](#content-processing)
12. [Security Model](#security-model)
13. [Observability](#observability)
14. [Operational Considerations](#operational-considerations)

---

## Overview

The indexer is a Python service that transforms raw blockchain data into a denormalized, query-optimized PostgreSQL database. While the blockchain stores the authoritative state, its key-value storage model is not optimized for the complex queries needed by a social platform (feeds, recommendations, search, analytics). The indexer bridges this gap by:

- Consuming blocks via JSON-RPC (historical catch-up) and WebSocket (live streaming)
- Decoding protobuf transactions and extracting relevant messages
- Applying business logic (validation, authorization, denormalization)
- Persisting processed data to PostgreSQL with appropriate indexes

**Key Design Principle:** The indexer is the queryable projection of chain-derived data. It enforces authorization rules that the blockchain intentionally delegates, applies vote weighting, and maintains derived preferences, community statistics, curator teams, and lens state for personalized feeds.

**Database Ownership:** The indexer writes exclusively to the `mirage_indexer` database. Backend-owned operational data such as push notifications, reports, similarity cache, and user activity tracking lives in the separate `mirage_backend` database. The backend reads from the indexer DB via the read-only `mirage_indexer_ro` role.

---

## Architecture Philosophy

### Why an Indexer?

The blockchain's Cosmos SDK storage model uses a key-value store optimized for consensus and state proofs, not for application queries. Consider a simple query: "Get the 50 most recent posts in community X through this viewer's selected lens." On-chain, this would require:

1. Iterating all posts (no community feed index)
2. Checking each post's community field
3. Loading user preferences for blocked users
4. Computing vote aggregates per post
5. Sorting and paginating

This is impractical at scale. The indexer pre-computes and indexes this data:

```
Blockchain (KV Store)          →      Indexer      →      PostgreSQL (Relational)
┌──────────────────────┐              ┌──────────┐         ┌────────────────────────┐
│ posts/{txhash}       │   decode     │          │  upsert │ posts (indexed by      │
│ profiles/{addr}      │ ──────────►  │  Python  │ ──────► │   topic, owner, time)  │
│ votes/...            │   process    │  Service │         │ votes (indexed by      │
└──────────────────────┘              └──────────┘         │   target, owner)       │
                                                           │ preferences, etc.      │
                                                           └────────────────────────┘
```

### Consistency Model

The indexer operates on an eventual consistency model, bounded by an atomic per-block commit:

- **Blockchain is authoritative for current state, not for history:** the chain is pruned, and the indexer deliberately retains more than the chain does (blocked lists keep up to `INDEXER_LIST_CAP` = 100,000 entries per user while the chain keeps a small deque). PostgreSQL is therefore a **long-history artifact, not a disposable cache** — it cannot be fully rebuilt from a pruned chain.
- **Indexer may lag:** during catch-up or network issues, the database trails the chain.
- **Atomic per-block projection:** every required write for a block plus its checkpoint (`meta.last_height`, `meta.last_block_hash`, `meta.chain_id`) commit in **one** PostgreSQL transaction. A failure rolls the whole block back and the checkpoint never moves past a partially applied block.
- **Replay is not idempotent against a populated database:** cumulative rows (topic stats, `user_topic_stats`, preferences) would be double-applied. `--height` is rejected outright when the database already holds a checkpoint; see [Replay and `--height`](#replay-and---height).
- **Required vs. optional:** required projection writes fail the block. Optional telemetry (difficulty/supply samples, peers, observed chain head) runs *outside* the block transaction and is warn-only.
- **No remote enrichment:** thumbnail derivation is deterministic and offline. The indexer issues no outbound requests on behalf of post content.

### History Completeness

History is never silently skipped. When blocks between the checkpoint and the head are unreachable (node pruning, an override start height), the range is recorded in `meta.history_gaps` and `meta.history_complete` flips to `false`. Both are exposed through the backend's indexer health payload (`get_indexer_health()` in `web/backend/chain.py`), together with `meta.continuity_status`.

This is an **accepted, guard-railed** behavior rather than a hard stop: indexing auto-continues from the earliest retained height so a node that was offline past the pruning window still comes back, but it can no longer claim complete history. Recovering the missing range requires restoring a PostgreSQL dump that covers it.

### Single-Instance Execution

The indexer enforces single-instance execution per node using a file lock (`/tmp/mirage-indexer.lock`). This prevents race conditions from duplicate indexers processing the same chain data:

```python
# File lock ensures only one indexer runs per node; taken before anything
# touches the database, so a second process cannot run migrations concurrently.
self._lock_file = open(LOCK_PATH, "a+")
fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
```

**Rationale:** Multiple indexers would cause duplicate writes, inconsistent vote counting, and database corruption. The lock is placed in `/tmp` so it clears automatically on container restart. Failing to take the lock exits **non-zero** with the holder PID, so a supervisor cannot mistake it for a successful start. Migrations additionally serialize on a PostgreSQL advisory lock, which covers multiple hosts sharing one database.

---

## Event-Driven Processing Model

### Two-Phase Startup

The indexer operates in two distinct phases:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            STARTUP SEQUENCE                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│  1. Wait for RPC readiness (poll until node responds)                       │
│  2. Load chain params (tier configs, limits, etc.)                          │
│  3. Continuity check: chain_id + checkpoint block hash must match the node  │
│  4. KV Sync: Reload all profiles from chain state                           │
│  5. Startup resync: supply, auth params, validators, balances, peers        │
│  6. Catch-up: Process blocks from last_height to current_height             │
│  7. Transition to live mode (WebSocket subscription)                        │
└─────────────────────────────────────────────────────────────────────────────┘
```

Step 3 runs **before** anything overwrites recent-block rows, because those rows are the evidence a mismatch is detected with. See [Continuity Verification](#continuity-verification).

**Phase 1: Historical Catch-Up**

During catch-up, the indexer processes blocks sequentially via JSON-RPC. `_process_block` advances the checkpoint itself, inside the block transaction:

```python
for height in range(start, end + 1):
    self._process_block(height)
```

Key behaviors:
- Respects the node pruning window (can't fetch blocks older than the retained range)
- Any range below the node's earliest retained height is recorded in `meta.history_gaps` rather than silently skipped
- Progress logging every N blocks for monitoring
- Proposal message resolution uses chain gRPC (live data still available)
- The "Completed successfully" banner is only logged when the loop exits normally; a failing height propagates and exits non-zero

**Phase 2: Live Streaming**

After catch-up, the indexer subscribes to `tm.event='NewBlock'` via WebSocket:

```python
ws.send(json.dumps({
    "jsonrpc": "2.0",
    "method": "subscribe",
    "id": 1,
    "params": {"query": "tm.event='NewBlock'"}
}))
```

Live mode features:
- Processes blocks as they're produced (~6 second intervals)
- Samples difficulty per delivered WebSocket event and supply every 200th block — head samples only, see [Telemetry Sampling](#telemetry-sampling)
- Automatic reconnection with backoff on WebSocket disconnect
- Gap detection: if WebSocket delivers height N but we're at N-5, process N-4 through N

### Telemetry Sampling

Difficulty and supply are **observational samples of the current chain head**, not per-historical-block records:

- They are read from the live chain (`get_difficulty_info()`, `get_total_supply()`), which only reports head state.
- They are recorded **outside** the block transaction and are warn-only; a sampling failure never fails a block.
- They are **skipped entirely during catch-up** (`_catch_up_mode`), because sampling head state while replaying an old height would attribute today's difficulty to a block from days ago.
- In live mode, when the WebSocket delivers height N after a gap, the blocks N-4..N-1 are fully projected but only one difficulty sample is taken.

The consequence is intentional: difficulty and supply charts have holes after every disconnect and across every catch-up window. They are operational telemetry, not a reconstructable historical series.

### Block Processing Pipeline

For each block, the processing pipeline is:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         BLOCK PROCESSING PIPELINE                            │
├─────────────────────────────────────────────────────────────────────────────┤
│  1. Fetch block via /block?height=N (hash and chain_id are required)        │
│  2. Fetch block_results, retrying until len(txs_results) == len(txs)        │
│  ┌── BEGIN ONE POSTGRESQL TRANSACTION ───────────────────────────────────┐  │
│  │  3. For each transaction:                                             │  │
│  │     a. Decode TxRaw protobuf                                          │  │
│  │     b. Check tx_results.code == 0 (failed txs recorded, not applied)  │  │
│  │     c. For each message in tx_body:                                   │  │
│  │        - Route to appropriate handler by type_url                     │  │
│  │  4. Process end_block_events:                                         │  │
│  │     - Governance proposals (passed/executed)                          │  │
│  │     - Subscription events (expired/renewed)                           │  │
│  │  5. Upsert recent block, refresh touched balances                     │  │
│  │  6. Set checkpoint: last_height + last_block_hash + chain_id          │  │
│  └── COMMIT (or roll the entire block back) ─────────────────────────────┘  │
│  7. Optional telemetry outside the transaction (warn-only)                  │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Critical Detail:** Failed transactions (code != 0) are recorded in `tx_index` but never reach a message handler. The blockchain accepted the transaction but the message handler rejected it; applying it would create inconsistent state.

**Result cardinality is enforced.** A node can commit a block before exposing complete `txs_results`. A short results list is *not* treated as "these transactions succeeded": `get_block_results_matching()` retries until the count matches, within a bounded deadline, and a final mismatch raises rather than advancing the height.

**Atomic checkpoint semantics.** `set_checkpoint(height, block_hash, chain_id)` writes all three `meta` keys through the block's connection and refuses to run outside a transaction. So the checkpoint is only ever observable together with the writes it describes, and it always carries enough provenance (which chain, which block hash) to verify on the next startup. There is no separate `set_last_height` call in the block path — `meta.last_height` is the single height authority, which is what the backend health check reads. Databases predating this change kept a frozen `indexer_state.last_processed_height` row, which read like a stalled indexer during an incident; the `v1.33.8_drop_stale_indexer_state_height` migration removes it.

**Required vs. optional writes.** Everything inside the transaction is required: a failure in any handler, governance resolution, or balance refresh aborts the whole block. Everything in step 7 (difficulty/supply samples, peer list, observed chain head, block pruning) is optional telemetry and only logs a warning on failure.

**A message the chain accepted is never fatal.** Aborting the block is for *indexer* failures — a dead database, an unresolvable proposal, a decode error. It is not for message content, because the chain's admission rules are looser than the index's shape. `MsgVote` only has to carry a well-formed 64-hex target, so the chain happily accepts a vote on a target that was never posted, and it does not constrain `direction` at all; `MsgEdit` does not have to agree with the stored post's target. Handlers log a warning and skip in those cases. Raising instead would hand any user a one-transaction kill switch for every indexer on the network: the block can never be projected, so no node could ever advance past that height.

---

## Component Structure

### Core Components

```
indexer/
├── main.py              # Entry point, Indexer class, lifecycle management
├── message_processor.py # Message routing and handler logic
├── database.py          # PostgreSQL schema and operations
├── chain_client.py      # JSON-RPC, gRPC, and WebSocket client
├── migrations/          # Database migrations (run on startup)
├── params.py            # Chain parameter loading and caching
├── settings.py          # Configuration constants
└── address_utils.py     # Address derivation from envelope pubkey
```

### Class Responsibilities

**Indexer (main.py)**
- Lifecycle management (start, stop, signal handling)
- Catch-up and live mode orchestration
- Block fetching and transaction decoding
- WebSocket connection management

**MessageProcessor (message_processor.py)**
- Message type routing (`/mirage.core.v1.MsgPost` → `_handle_post`)
- Authorization the chain delegates (edit ownership, delete rights)
- Denormalization and derived-stat updates
- Database operations via DatabaseManager
- Event processing for subscription updates

**DatabaseManager (database.py)**
- Schema initialization (idempotent CREATE TABLE IF NOT EXISTS)
- Block-scoped transactions (`transaction()`) and the atomic checkpoint (`set_checkpoint()`)
- UPSERT operations for posts, votes, profiles
- Complex queries for denormalization
- Migration management

---

## Message Processing

### Message Type Routing

The indexer handles all `mirage.core.v1` message types, routing each to a specialized handler:

```python
TYPE_URL_TO_PROTO = {
    "/mirage.core.v1.MsgPost": MsgPost,
    "/mirage.core.v1.MsgEdit": MsgEdit,
    "/mirage.core.v1.MsgAnnotate": MsgAnnotate,
    "/mirage.core.v1.MsgVote": MsgVote,
    "/mirage.core.v1.MsgSetUsername": MsgSetUsername,
    "/mirage.core.v1.MsgDelete": MsgDelete,
    # ... 15+ message types
}
```

### Post Processing (MsgPost)

Post handling involves several transformations:

1. **No re-validation of consensus rules:** topic/title/content size limits are chain admission rules that the transaction has already passed with `code=0`. The indexer used to re-check them against *current-head* params, which silently dropped committed posts (it also invented a `min_title_size = 1` the chain does not have) and made the result depend on when indexing ran. Only database-safety checks that cannot disagree with consensus remain.
2. **Owner derivation:** Extract from `envelope_pubkey` field
3. **Paid flag derivation:** `paid = not (envelope_difficulty > 0 or envelope_pow > 0)`
4. **Root resolution:** For comments, resolve `root_topic` and `root_post_id`
5. **Auto-vote creation:** Author automatically upvotes their own post
6. **Thumbnail discovery:** For root posts, extract preview image from content URLs
7. **Topic stats update:** Increment `topic_content_stats` for content classification

**Root Topic Denormalization:**

For efficient feed queries, every post stores its root topic (the topic of the thread's root post):

```
Root Post (txhash=abc123)     Comment (txhash=def456)
┌────────────────────────┐    ┌────────────────────────┐
│ topic: "technology"    │    │ topic: ""              │
│ target: ""             │    │ target: "abc123"       │
│ root_topic: technology │    │ root_topic: technology │  ← Denormalized
│ root_post_id: abc123   │    │ root_post_id: abc123   │  ← Denormalized
└────────────────────────┘    └────────────────────────┘
```

This enables queries like "all posts/comments in topic X" without recursive parent traversal.

### Vote Processing (MsgVote)

Vote handling is the most complex message type, involving:

1. **Direction validation:** Must be -1, 0, or +1
2. **Target existence check:** Reject votes for unknown posts
3. **Previous vote lookup:** Handle vote changes (flip from +1 to -1)
4. **Weight calculation:** Apply tier-based and topic-activity weighting
5. **Preference updates:** Update topic and author preference scores
6. **Topic stats update:** Track user's voting activity per topic

**Dual Vote Values:**

Each vote stores two values:
- `user_vote`: Raw direction (-1, 0, +1) for personalized recommendations
- `user_weight`: Weighted contribution to post score for community ranking

This separation allows personal preferences to use unweighted votes while community rankings use weighted votes that consider user standing.

---

## Database Schema

### Core Tables

```sql
-- Posts (content)
CREATE TABLE posts (
    txhash TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    topic TEXT,
    title TEXT,
    content TEXT,
    target TEXT,                    -- Parent post (empty for root posts)
    created_at BIGINT NOT NULL,
    edited_at BIGINT,
    paid BOOLEAN NOT NULL DEFAULT FALSE,
    deleted BOOLEAN NOT NULL DEFAULT FALSE,
    thumbnail_url TEXT,
    tag TEXT NOT NULL DEFAULT '',   -- Content classification (sensitive, gore, etc.)
    root_topic TEXT,                -- Denormalized: topic of thread's root post
    root_post_id TEXT               -- Denormalized: txhash of thread's root post
);

-- Votes (engagement)
CREATE TABLE votes (
    txhash TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    target TEXT,                    -- Post being voted on
    user_vote DOUBLE PRECISION NOT NULL,    -- Raw direction (-1, 0, +1)
    user_weight DOUBLE PRECISION NOT NULL,  -- Weighted contribution
    created_at BIGINT NOT NULL,
    paid BOOLEAN NOT NULL DEFAULT FALSE
);

-- Profiles (users)
CREATE TABLE profiles (
    owner TEXT PRIMARY KEY,
    username TEXT,
    level INTEGER NOT NULL DEFAULT 0,
    created_at BIGINT NOT NULL DEFAULT 0,
    subscription_expiry BIGINT NOT NULL DEFAULT 0,
    auto_renew BOOLEAN NOT NULL DEFAULT FALSE,
    biography TEXT NOT NULL DEFAULT '',
    avatar TEXT NOT NULL DEFAULT '',
    banner TEXT NOT NULL DEFAULT ''
);
```

### Derived Tables

```sql
-- User preferences (for personalized feeds)
CREATE TABLE preferences (
    owner TEXT NOT NULL,
    pref_type TEXT NOT NULL,        -- 'topic' or 'author'
    target TEXT NOT NULL,           -- Topic name or author address
    weight DOUBLE PRECISION NOT NULL,
    updated_at BIGINT NOT NULL,
    PRIMARY KEY (owner, pref_type, target)
);

-- User similarity cache (for recommendations)
CREATE TABLE user_similarity_cache (
    owner TEXT NOT NULL,
    similar_user TEXT NOT NULL,
    similarity DOUBLE PRECISION NOT NULL,
    shared_dims INT NOT NULL,
    computed_at BIGINT NOT NULL,
    expires_at BIGINT NOT NULL,
    PRIMARY KEY (owner, similar_user)
);

-- Per-user per-topic voting stats (for vote weighting)
CREATE TABLE user_topic_stats (
    owner TEXT NOT NULL,
    topic TEXT NOT NULL,
    vote_count INTEGER NOT NULL DEFAULT 0,
    net_votes INTEGER NOT NULL DEFAULT 0,      -- Sum of vote directions
    unique_root_posts INTEGER NOT NULL DEFAULT 0,
    post_count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (owner, topic)
);
```

### Index Strategy

Indexes are designed for common query patterns:

```sql
-- Feed queries (posts by topic, by time)
CREATE INDEX idx_posts_topic_lower ON posts(LOWER(topic));
CREATE INDEX idx_posts_created_at ON posts(created_at DESC);
CREATE INDEX idx_posts_root_post_id ON posts(LOWER(root_post_id));

-- Vote aggregation (votes by target)
CREATE INDEX idx_votes_target_lower ON votes(LOWER(target));
CREATE UNIQUE INDEX uniq_votes_owner_target ON votes(LOWER(owner), LOWER(target));

-- Profile lookups
CREATE INDEX idx_profiles_owner_lower ON profiles(LOWER(owner));
```

**Design Rationale:** All text columns are indexed with `LOWER()` because Mirage uses case-insensitive matching for addresses and topics. The unique constraint on votes prevents duplicate votes and enables efficient "has user voted on post?" queries.

---

## Denormalization Strategy

### Root Topic/Post Propagation

The most significant denormalization is propagating root information to comments:

```
Comment Chain Resolution:
                                      
Post A (root)  ←─┐                    
  topic: "crypto" │                    
  target: ""      │                    
                  │ walk up            
Comment B        ─┤                    
  target: "A"     │                    
                  │                    
Comment C        ─┘                    
  target: "B"                          
  root_topic: "crypto"   ← Stored directly
  root_post_id: "A"      ← Stored directly
```

**Resolution Algorithm:**

```python
def get_root_topic_for_post(self, txhash: str):
    """Walk parent chain to find root, with backfill."""
    current_id = txhash
    visited = set()
    
    for _ in range(100):  # Bounded depth
        if current_id in visited:
            break
        visited.add(current_id)
        
        row = fetch_post(current_id)
        if not row:
            break
            
        # Fast path: already denormalized
        if row.root_topic and row.root_post_id:
            return row.root_topic, row.root_post_id
            
        # Reached root (no parent)
        if not row.target:
            # Backfill and return
            update_post_root_fields(current_id, row.topic, current_id)
            return row.topic, current_id
            
        current_id = row.target
    
    return None, None
```

**Benefits:**
- Feed queries don't need recursive CTEs
- Vote weighting can lookup topic instantly
- Thread reconstruction is a single query

### Preference Scoring

User preferences use exponential decay to weight recent activity:

```python
DECAY = 0.9
new_weight = (old_weight * DECAY) + new_vote
# Clamped to [-10, 10] range
```

This means:
- Most recent vote contributes 100%
- 5 votes ago contributes ~59%
- 10 votes ago contributes ~35%
- 20 votes ago contributes ~12%

**Why exponential decay?** User interests change over time. A user who upvoted 50 crypto posts a year ago but now only engages with art shouldn't see crypto dominating their feed.

---

## Vote Weighting System

### Asymmetric Vote Power

The indexer implements an asymmetric vote weighting system where upvotes and downvotes are treated differently:

**Upvotes:** Always count at full tier weight (1.0 for free users, higher for subscribers)

**Downvotes:** Gated by topic activity - users must have standing in a topic to downvote effectively

**Rationale:** This prevents "downvote brigading" where outsiders can bury on-topic content, while still allowing positive signals to flow freely. A user who has never engaged with a topic shouldn't be able to suppress content in that topic.

### Topic Activity Factors

For downvotes, the weight is calculated from multiple factors:

```python
# Minimum requirements
if net_votes < COMMUNITY_VOTE_MIN_NET_VOTES:
    weight = COMMUNITY_VOTE_BASELINE  # Zero effective weight
else:
    topic_factor = min(vote_count / COMMUNITY_VOTE_MAX_TOPIC_VOTES, 1.0)
    age_factor = min(age_days / COMMUNITY_VOTE_MATURITY_DAYS, 1.0)
    root_factor = min(unique_root_posts / COMMUNITY_VOTE_MIN_ROOT_POSTS, 1.0)
    posts_factor = min(post_count / COMMUNITY_VOTE_MAX_POSTS, 1.0)
    
    combined = topic_factor * age_factor * root_factor * posts_factor
    weight = BASELINE + combined * (tier_max - BASELINE)
```

**Factors explained:**
- `vote_count`: How many votes has user cast in this topic?
- `net_votes`: Sum of vote directions (must be positive to have any power)
- `age_days`: How old is the account?
- `unique_root_posts`: How many distinct threads has user engaged with?
- `post_count`: How many posts/comments has user made in this topic?

### User Topic Stats Tracking

To enable efficient weight calculation, the indexer maintains per-user per-topic statistics:

```sql
user_topic_stats:
┌─────────────────────┬───────────┬────────────┬────────────┬────────────────────┬────────────┐
│ owner               │ topic     │ vote_count │ net_votes  │ unique_root_posts  │ post_count │
├─────────────────────┼───────────┼────────────┼────────────┼────────────────────┼────────────┤
│ mirage1abc...       │ crypto    │ 45         │ 38         │ 12                 │ 5          │
│ mirage1abc...       │ art       │ 3          │ 3          │ 2                  │ 0          │
└─────────────────────┴───────────┴────────────┴────────────┴────────────────────┴────────────┘
```

Stats are updated after each vote:
- `vote_count` only increments for new votes (not re-votes on same target)
- `net_votes` shifts by `new_direction - previous_direction`, **not** by the new direction. Re-casting the same vote is a no-op (delta 0), flipping `+1 → -1` applies `-2`, and clearing a vote reverses its earlier contribution. `net_votes` gates downvote power, so applying the raw direction let a user inflate their standing by re-voting.
- `unique_root_posts` tracks distinct thread engagement

---

## Profile Synchronization

### KV Sync on Startup

At startup, the indexer reconciles profiles against chain state by paginating `mirage.core.v1.Query/GetProfiles` over gRPC:

```python
def _sync_profiles_from_chain(self):
    profiles = self.chain.list_profiles_paginated()
    with self.db.transaction(label="profile_sync"):
        self.db.upsert_profiles_batch(batch, now)
        for p in profiles:
            self.db.set_enabled_agents(owner, p["enabled_agents"])
            self.db.set_followed_users(owner, p["followed_users"])
            self.db.set_followed_topics(owner, p["followed_topics"])
            # blocked_* are merged, never cleared
        self._soft_delete_absent_owners(chain_owners, now)
```

**Why sync on startup?**
- Indexer database could have stale data from delayed processing
- Profile updates via governance proposals might not emit events
- Ensures consistency after indexer downtime

**What is reconciled, and how:**

| Data | Treatment |
|------|-----------|
| Scalars (username, level, expiry, bio, avatar, banner, flair) | Authoritative from chain; overwritten |
| `enabled_agents`, `followed_users`, `followed_topics` | Authoritative from chain (hard-capped lists); replaced wholesale |
| `blocked_users`, `blocked_posts`, `blocked_topics` | **Merged, never cleared.** The chain keeps a small deque; the indexer intentionally retains the full history, so a sync must not truncate it to the chain's window |
| Profiles present in the DB but absent from chain | Soft-deleted, and their list rows removed |

The whole reconciliation runs in one transaction, and **a failure aborts startup** rather than logging "KV Sync skipped" and continuing with stale profile state. Because chain-side profile listing is authoritative here, `GetProfiles` on the chain no longer skips profiles whose JSON or list reads fail — it returns an error, so a partial response cannot be mistaken for a complete owner inventory and trigger spurious soft-deletes.

### Subscription Event Handling

EndBlock events update subscription status:

```python
def _process_subscription_events(self, result_obj, ts, height):
    for event in events:
        if event_type == "subscription_expired":
            self.processor.update_profile_level(address, 0, ts)
        elif event_type == "subscription_renewed":
            self.processor.update_profile_subscription(
                address, level, new_expiry, ts
            )
```

This keeps the indexer in sync with on-chain subscription state changes that happen during EndBlock processing (automatic renewals, expirations).

---

## Governance Proposal Handling

### Proposal Message Extraction

When a governance proposal passes, the indexer needs to process its messages:

```
Proposal Lifecycle:

 MsgSubmitProposal  ──►  Voting Period  ──►  EndBlock: proposal_passed event
                                                       │
                                                       │ Resolve + process
                                                       ▼
                                      cosmos.gov.v1.Query/Proposal (gRPC)
                                                       │
                                                       ▼
                                  process_core_message(type_url, value, ...)
```

**Challenge:** By the time a proposal passes, the submission transaction may be pruned from node history, so the messages cannot be recovered from the block that submitted them.

**Resolution is a single strategy: governance gRPC.** When a `proposal_passed` event appears, the indexer calls `cosmos.gov.v1.Query/Proposal` and reads `proposal.messages`. A v1 proposal wrapping a legacy v1beta1 `content` reports an empty `messages` list, so that case falls through to `cosmos.gov.v1beta1.Query/Proposal` and uses the single `content` Any. Both paths are gRPC on port 9090; REST (1317) is never used.

There is **no submission-time cache**. The earlier `_proposal_cache` was populated by parsing `MsgSubmitProposal` with the v1beta1 generated type, which has only `content` / `initial_deposit` / `proposer` and no `messages` field — the cache could never be populated, and the code silently fell back to REST. Both the cache and the `_skipped_proposals` no-retry set have been removed.

```python
messages = self.chain.fetch_proposal_messages(proposal_id, TYPE_URL_TO_PROTO)
for entry in messages:
    self.processor.process_core_message(
        entry["type_url"], base64.b64decode(entry["value"]), f"proposal-{proposal_id}", ts, height
    )
```

**Failure is fatal to the block.** An unresolvable passed proposal raises inside the block transaction, so the block rolls back and the checkpoint does not advance past a governance action that was never applied. The one tolerated case is a proposal whose messages the indexer does not track at all (governance-only mint/burn), which logs a warning and continues.

When a resolved proposal contains `MsgUpdateParams`, the param cache is reloaded from chain gRPC and re-stored in `chain_stats` after the block commits, so later blocks are weighted against the new governance values.

> **Since v1.20.0:** CometBFT tx indexing is disabled (`indexer = "null"`), so `tx_search` is not available and its fallback has been removed.

---

## Content Processing

### Thumbnail Discovery

For root posts, the indexer derives a preview thumbnail from content URLs. The derivation is **purely deterministic and offline** — the indexer makes no outbound request on behalf of post content:

```python
def discover_post_thumbnail(self, content: str) -> str | None:
    """Derive a thumbnail URL for root post content, or None."""
    first_url = self._extract_first_url(content)

    # Direct image URL
    if self._is_raster_image_url(first_url):
        return first_url

    # Cloudflare Stream video
    uid = self._extract_stream_uid(first_url)
    if uid:
        return f"https://videodelivery.net/{uid}/thumbnails/thumbnail.jpg"

    # Bunny Stream playlist → sibling poster on the same pull zone
    bunny = self._bunny_stream_thumbnail(first_url)
    if bunny:
        return bunny

    # YouTube video
    yt_id = self._extract_youtube_video_id(first_url)
    if yt_id:
        return f"https://img.youtube.com/vi/{yt_id}/hqdefault.jpg"

    # Unknown URL shape → no thumbnail
    return None
```

**Why no fetching.** The removed HTML-fetch and image-probe paths made the validator host issue GET requests to arbitrary user-supplied URLs (blind SSRF, redirect-to-loopback, slow-drip stalls on the block path). They also made the indexed value depend on whatever a third-party host happened to serve at index time, so two nodes indexing the same block could store different thumbnails. Both problems are gone: the value is a pure function of the post's own text.

Dimension metadata is likewise never probed. `DatabaseManager._extract_media_meta()` reads `?w=` / `?h=` from the upload URL's own query string and validates them through `_sanitize_wh` (both must be integers in `[1, 10000]`); anything else stores `{}` and the frontend lays out without a hint.

**Consequence:** posts linking to a site whose preview image is only discoverable from its HTML get no thumbnail. That is the accepted trade for taking user-controlled network access off the validator.

### Topic Content Classification

Posts can be tagged with content classifications (`sensitive`, `gore`, `violence`, `death`, `adult`). The indexer aggregates these per topic:

```sql
topic_content_stats:
┌─────────────┬─────────────┬────────────────┬──────────────┬───────────────┐
│ topic       │ total_posts │ sensitive_count│ adult_count  │ dominant_tag  │
├─────────────┼─────────────┼────────────────┼──────────────┼───────────────┤
│ random      │ 1000        │ 50             │ 600          │ adult         │
│ technology  │ 500         │ 5              │ 0            │               │
└─────────────┴─────────────┴────────────────┴──────────────┴───────────────┘
```

This enables:
- Topic safety warnings in the UI
- Content filtering by topic reputation
- Moderation prioritization

---

## Security Model

### Delete Authorization

The blockchain accepts `MsgDelete` from anyone (they pay gas), but actual authorization is enforced by the indexer:

```python
def _handle_delete(self, type_url, value, ts):
    """
    Security model (enforced HERE, not on-chain):
    - Governance (authority = gov module address): can delete any post
    - Admin (user level >= 100): can delete any post
    - Regular user: can only delete their own posts
    """
    GOV_MODULE_ADDRESS = "mirage10d07y265gmmuvt4z0w9aw880jnsr700jvealeg"
    
    is_governance = owner.lower() == GOV_MODULE_ADDRESS.lower()
    is_admin = self.db.get_user_level(owner) >= 100
    
    if is_governance:
        self.db.delete_post(target, None)  # Any post
    elif is_admin:
        self.db.delete_post(target, None)  # Any post
    else:
        self.db.delete_post(target, owner)  # Only own posts
```

**Why enforce in indexer?**

On-chain enforcement would require:
1. Storing full post ownership in state (increases state size)
2. Complex keeper queries during message handling
3. Higher gas costs for delete operations

By delegating to the indexer:
- Delete messages are cheap on-chain
- Invalid deletes just waste gas
- The indexer is the query layer anyway

### Edit Authorization

Unlike delete, edits are strictly enforced:

```python
def _handle_edit(self, type_url, value, tx_hash, ts, height):
    # Enforce ownership: only the original owner can edit (admins cannot)
    db_owner = self.db.get_post_owner(override)
    if db_owner.lower() != owner.lower():
        logger.warning("Rejected edit: owner mismatch")
        return
```

**Rationale:** Admins should delete problematic content, not modify it. Allowing admin edits would create attribution/authenticity concerns.

---

## Observability

### Structured Logging

The indexer uses structured YAML logging for all state changes:

```python
self.log_yaml("Stored post", {
    "action": "insert",
    "height": height,
    "txhash": txhash,
    "owner": owner,
    "topic": topic,
    "paid": paid,
})
```

Output:
```
================ INDEXER ==================
Stored post
action: insert
height: 12345678
txhash: abc123...
owner: mirage1...
topic: technology
paid: true
-------------------------------------------
```

### Vote Calculation Logging

Vote processing includes detailed calculation logs:

```yaml
Stored vote
vote:
  direction: -1
  topic: crypto
  target: abc123...
result:
  user_vote: -1.0
  user_weight: -0.15
calculation:
  formula: "(topic * age * roots * posts) * tier_max"
  tier_max: 1.0
  factors:
    net_votes: "5 (min: 3)"
    topic: "10/50 = 0.2"
    age: "30d/90d = 0.33"
    roots: "3/5 = 0.6"
    posts: "2/10 = 0.2"
  combined: 0.008
  weight: 0.15
  limiting: "posts(2/10)"
```

### Progress Reporting

During catch-up, progress is reported at regular intervals:

```
Catchup progress: processed 5000 / 50000 blocks (42.3 blocks/sec, ~1065 seconds remaining)
```

---

## Operational Considerations

### Startup Dependencies

The indexer requires:
1. **PostgreSQL database:** Connection URL in config
2. **Mirage node:** JSON-RPC (26657) and gRPC (9090) endpoints
3. **Node sync state:** Node must be synced and responding

### Failure Modes

| Failure | Impact | Recovery |
|---------|--------|----------|
| Database unavailable | Indexer exits | Auto-restart via supervisor |
| Node RPC unavailable | Indexer waits/retries | Automatic reconnection |
| WebSocket disconnect | Live loop reconnects with backoff | Automatic reconnection |
| Message processing error (live or catch-up) | Block rolled back, checkpoint unchanged, process exits **non-zero** | Manual investigation required |
| Another indexer holds the lock | Process exits **non-zero** with the holder PID | Stop the duplicate |
| Checkpoint `chain_id` / block hash mismatch | Startup **aborts before any write** | Restore a trusted PostgreSQL dump — see below |
| Blocks below the checkpoint were pruned | Gap recorded, indexing continues from earliest retained | Restore a dump covering the gap |

### Continuity Verification

Recovery deliberately preserves PostgreSQL (see `scripts/recover.sh`), which means rows indexed from a *diverged* chain would otherwise survive a divergence recovery and keep being served as chain truth. `_verify_chain_continuity()` runs at startup, before profile sync or any recent-block upsert, and refuses to keep indexing onto a chain that is not the one already in the database:

| Condition | Outcome |
|-----------|---------|
| Empty database | `continuity_status = fresh`; proceed |
| `meta.chain_id` != node `node_info.network` | **Fatal.** Refuse to index |
| Checkpoint height above the node head | **Fatal.** Node was rolled back or reset |
| Checkpoint below earliest retained height, `meta.chain_id` present | `continuity_status = unverified_pruned_gap`; record a `history_gaps` entry and continue |
| Checkpoint below earliest retained height, no `meta.chain_id` | **Fatal.** Nothing remains that could identify the chain the rows came from |
| Any retained `recent_blocks` hash != the node's hash at that height | **Fatal.** Rows come from a diverged chain |
| No `chain_id` / `last_block_hash`, but the node confirms `recent_blocks` at the checkpoint height | `continuity_status = adopted`; record the confirmed provenance and proceed |
| No `chain_id` / `last_block_hash` and no node-confirmed `recent_blocks` row at the checkpoint height | **Fatal.** Provenance unverifiable |
| Node's hash at the checkpoint height != `meta.last_block_hash` | **Fatal.** Rows come from a diverged chain |
| Hashes match | `continuity_status = verified`; proceed |

**Adoption of pre-provenance databases.** `meta.chain_id` and `meta.last_block_hash` are only written by `set_checkpoint`, so a database indexed before those keys existed carries a height and nothing else. That is not the same as unverifiable: the old indexer already recorded a hash per block in `recent_blocks`, including one for the checkpoint block itself. Startup verifies every retained `recent_blocks` row against the node first, and only when the row at the checkpoint height is confirmed does it adopt that hash and the node's chain ID as the recorded provenance. A database from a diverged chain fails the same hash comparison and is still refused, so the adoption path does not weaken the check — it just avoids demanding a dump restore for a database whose provenance the node can confirm. It happens once; every later start takes the `verified` path.

When the checkpoint sits below the node's earliest retained block there is nothing left to confirm, so adoption is not available and `meta.chain_id` must already be present. `scripts/reset_local_testnet.py` hits exactly that case — it restores a backup's indexer dump next to a freshly exported single-validator genesis whose `initial_height` is above the dump's checkpoint — so it stamps `meta.chain_id` from the genesis it just built. That stamp is an explicit operator decision made by a script that knows the answer, not something the indexer infers.

> **Recovery warning — read before wiping anything.**
>
> - **Preserve the indexer PostgreSQL database.** It is not reconstructable from a pruned chain: blocked-list history intentionally exceeds what the chain retains, and blocks outside the retention window cannot be replayed.
> - **A hash or chain-ID mismatch is fatal, by design.** The indexer will not start. Do not "fix" it by clearing `meta` — that discards the only evidence of the divergence. The supported response is to restore a PostgreSQL dump whose checkpoint is known to be canonical (`scripts/backup_restore.py`), or to start from a genuinely empty database and accept the recorded history gap.
> - **Pruned ranges are recorded, not hidden.** They appear in `meta.history_gaps`, flip `meta.history_complete` to `false`, and surface in the backend indexer health payload. A node with gaps serves an incomplete moderation/feed view even though every health check reads green on height.
> - **`--height` is not a replay tool.** See below.

### Replay and `--height`

`--height N` is rejected at startup whenever the database already holds a checkpoint:

```
--height 100 rejected: database already holds checkpoint height 12345.
Replay is only supported against an empty indexer database.
```

Cumulative rows — `user_topic_stats` (`vote_count`, `net_votes`, `post_count`), `topic_content_stats`, and the decaying `preferences` weights — have no per-message idempotency guard. Replaying blocks into a populated database double-counts them. The flag exists for rebuilding an empty database from a chosen height, nothing else. If the derived tables are already suspect, rebuild them from the canonical `posts`/`votes` tables with the `v1.33.0_rebuild_derived_stats` migration rather than replaying blocks.

### Database Migrations

Migrations run automatically on startup, before any block is processed:

```python
migration_count = run_migrations(self.db, self.chain)
if migration_count > 0:
    logger.info("Completed %d migrations", migration_count)
```

The `meta` table tracks migration state (`migration_<key>`), plus a `migration_<key>_checksum` for each applied file. The runner is fail-closed:

- Discovery/import errors, a missing `MIGRATION_KEY` or `run()`, and duplicate keys are **fatal** — never skipped with a warning.
- A failure reading the completed set is **fatal** — never treated as "nothing applied".
- The whole run is serialized on a PostgreSQL advisory lock, so two hosts sharing one database cannot migrate concurrently.
- Editing an already-applied migration file fails startup on the checksum mismatch.
- Database-only migrations should use `run_db_migration()`, which commits the migration's work and its completion marker in one transaction so a crash cannot leave a partially applied migration with no marker. Migrations that do RPC work must be resumable via `meta` progress keys and write the marker only when finished.

### Memory Considerations

The indexer keeps no unbounded per-transaction or per-proposal state in memory. The former `_seen_txs`, `_proposal_cache`, and `_skipped_proposals` structures were all removed: transaction-level deduplication is now the database's job (`tx_index` upserts, capped at `TX_INDEX_CAP`), and proposals are resolved from gRPC at the moment they pass rather than cached from submission. Memory usage is flat across arbitrarily long catch-up runs.

---

## API Port Usage Policy

The indexer follows a strict API usage policy:

```
✓ gRPC (9090): All chain queries (governance, bank, profiles, params)
✓ RPC (26657): Tendermint queries (status, block, block_results, websocket)
✗ REST (1317): NEVER used (not enabled, matches backend pattern)
```

This ensures consistency across all services querying the blockchain.

The policy is now actually true in code. Three REST paths existed and have been removed: governance proposal resolution (`/cosmos/gov/v1/proposals/{id}` → `cosmos.gov.v1.Query/Proposal`), profile listing (`/mirage/core/v1/profiles` → `mirage.core.v1.Query/GetProfiles` with pagination), and the `_derive_rest_url()` helper that built port-1317 URLs. Nothing in `indexer/` constructs a 1317 URL, and `indexer/message_processor.py` no longer imports `requests` at all.
