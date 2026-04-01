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
11. [Bridge Transaction Indexing](#bridge-transaction-indexing)
12. [Content Processing](#content-processing)
13. [Security Model](#security-model)
14. [Observability](#observability)
15. [Operational Considerations](#operational-considerations)

---

## Overview

The indexer is a Python service that transforms raw blockchain data into a denormalized, query-optimized PostgreSQL database. While the blockchain stores the authoritative state, its key-value storage model is not optimized for the complex queries needed by a social platform (feeds, recommendations, search, analytics). The indexer bridges this gap by:

- Consuming blocks via JSON-RPC (historical catch-up) and WebSocket (live streaming)
- Decoding protobuf transactions and extracting relevant messages
- Applying business logic (validation, authorization, denormalization)
- Persisting processed data to PostgreSQL with appropriate indexes

**Key Design Principle:** The indexer is the single source of truth for chain-derived data. It enforces authorization rules that the blockchain intentionally delegates (e.g., who can delete which posts), applies complex vote weighting algorithms, and maintains derived data structures (preferences, topic stats) that enable personalized feeds.

**Database Ownership:** The indexer writes exclusively to the `mirage_indexer` database. All backend-owned operational data (quests, rewards, push notifications, invite codes, reports, similarity cache, user activity tracking) lives in a separate `mirage_backend` database that the indexer never touches. The backend reads from the indexer DB via a read-only PostgreSQL role (`mirage_indexer_ro`).

---

## Architecture Philosophy

### Why an Indexer?

The blockchain's Cosmos SDK storage model uses a key-value store optimized for consensus and state proofs, not for application queries. Consider a simple query: "Get the 50 most recent posts in topic X, excluding blocked users, weighted by vote score." On-chain, this would require:

1. Iterating all posts (no topic index)
2. Checking each post's topic field
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

### Eventual Consistency Model

The indexer operates on an eventual consistency model:

- **Blockchain is authoritative:** If the indexer database is lost, it can be rebuilt from the chain
- **Indexer may lag:** During catch-up or network issues, the database trails the chain
- **Idempotent processing:** Re-processing a block produces identical results (safe for restarts)
- **Best-effort enrichment:** Some operations (thumbnail discovery, chain queries) may fail without blocking indexing

### Single-Instance Execution

The indexer enforces single-instance execution per node using a file lock (`/tmp/mirage-indexer.lock`). This prevents race conditions from duplicate indexers processing the same chain data:

```python
# File lock ensures only one indexer runs per node
lock_path = "/tmp/mirage-indexer.lock"
self._lock_file = open(lock_path, "w")
fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
```

**Rationale:** Multiple indexers would cause duplicate writes, inconsistent vote counting, and database corruption. The lock is placed in `/tmp` so it clears automatically on container restart.

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
│  3. KV Sync: Reload all profiles from chain state                           │
│  4. Catch-up: Process blocks from last_height to current_height             │
│  5. Transition to live mode (WebSocket subscription)                        │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Phase 1: Historical Catch-Up**

During catch-up, the indexer processes blocks sequentially via JSON-RPC:

```python
for height in range(start, end + 1):
    self._process_block(height)
    self.db.set_last_height(height)
```

Key behaviors:
- Respects node pruning window (can't fetch blocks older than ~7 days)
- Configurable max lookback (`INDEXER_MAX_LOOKBACK_DAYS`)
- Progress logging every N blocks for monitoring
- Proposal message resolution uses chain gRPC (live data still available)

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
- Records difficulty and supply history at each block
- Automatic reconnection with backoff on WebSocket disconnect
- Gap detection: if WebSocket delivers height N but we're at N-5, process N-4 through N

### Block Processing Pipeline

For each block, the processing pipeline is:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         BLOCK PROCESSING PIPELINE                            │
├─────────────────────────────────────────────────────────────────────────────┤
│  1. Fetch block via /block?height=N                                         │
│  2. Fetch block_results via /block_results?height=N                         │
│  3. For each transaction:                                                    │
│     a. Decode TxRaw protobuf                                                │
│     b. Check tx_results.code == 0 (skip failed txs)                         │
│     c. For each message in tx_body:                                         │
│        - Route to appropriate handler by type_url                           │
│        - Process tx_events for bridge confirmations                         │
│  4. Process end_block_events:                                               │
│     - Governance proposals (passed/executed)                                │
│     - Subscription events (expired/renewed)                                 │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Critical Detail:** Failed transactions (code != 0) are skipped entirely. The blockchain accepted the transaction but the message handler rejected it. Including these would create inconsistent state.

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
- Business logic validation (content length, topic format)
- Database operations via DatabaseManager
- Event processing for bridge and subscription updates

**DatabaseManager (database.py)**
- Schema initialization (idempotent CREATE TABLE IF NOT EXISTS)
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

1. **Validation:** Content length, topic format, title requirements
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

-- Agent edit overlays (MsgAnnotate)
CREATE TABLE agent_edits (
    post_txhash TEXT NOT NULL,
    agent_address TEXT NOT NULL,
    edit_txhash TEXT NOT NULL,
    topic TEXT,             -- NULL = no change; '' = clear
    title TEXT,
    content TEXT,
    tag TEXT,
    media TEXT,             -- JSON list or NULL
    appendix TEXT,          -- Agent commentary note
    edited_at BIGINT NOT NULL,
    PRIMARY KEY (post_txhash, agent_address)
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
- `net_votes` adjusts by vote direction for every vote
- `unique_root_posts` tracks distinct thread engagement

---

## Profile Synchronization

### KV Sync on Startup

At startup, the indexer performs a full profile sync from chain KV storage:

```python
def _sync_profiles_from_chain(self):
    """Full KV reload for profiles from blockchain at startup."""
    profiles = self.chain.list_profiles_subspace()
    for p in profiles:
        self.db.upsert_profile_full(
            owner=p.owner,
            username=p.username,
            level=p.level,
            subscription_expiry=p.subscription_expiry,
            # ... all fields
        )
```

**Why sync on startup?**
- Indexer database could have stale data from delayed processing
- Profile updates via governance proposals might not emit events
- Ensures consistency after indexer downtime
- Lists (followed users/topics/agents) are NOT synced (tracked via messages)

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
      │                                              │
      │ Cache messages                               │ Process messages
      ▼                                              ▼
 _proposal_cache[pid] = messages           process_core_message(type_url, value, ...)
```

**Challenge:** By the time a proposal passes, the submission transaction may be pruned from node history. The indexer uses two resolution strategies:

1. **Cache on submission:** During live mode, cache proposal messages when `MsgSubmitProposal` is seen in a block
2. **gRPC query:** Fetch proposal content via governance gRPC endpoint (works in both live and catch-up modes)

> **Since v1.20.0:** CometBFT tx indexing is disabled (`indexer = "null"`), so `tx_search` is no longer available. Proposal resolution is gRPC-only when the cache is empty. The `tx_search` fallback has been removed.

```python
messages = self._proposal_cache.pop(proposal_id, None)
if not messages:
    messages = self.chain.fetch_proposal_messages(proposal_id, TYPE_URL_TO_PROTO)
```

---

## Bridge Transaction Indexing

### Transaction Types

The indexer tracks three bridge message types:

| Message | Direction | Purpose |
|---------|-----------|---------|
| `MsgBridgeBurn` | Outbound | User burns tokens on Mirage to receive on external chain |
| `MsgBridgeAttestBurned` | Inbound | Validator attests burn on external chain |
| `MsgBridgeAttestMinted` | Outbound | Validator attests mint on external chain |

### Status Tracking

Bridge transactions have a multi-step confirmation process tracked via events:

```python
def process_tx_events(self, events):
    for ev_type, attrs in self.decode_events(events):
        if ev_type == "bridge_attest":
            # Inbound: external burn confirmed, Mirage mint threshold reached
            if attrs.get("minted") == "true":
                self.db.update_bridge_attestation_minted(source_chain, burn_id, True)
                
        elif ev_type == "bridge_attest_minted":
            # Outbound: Mirage burn confirmed minted on external chain
            if attrs.get("minted") == "true":
                self.db.update_bridge_mint_attestation_confirmed(burn_id, True)
```

### Query Support

The indexed data enables bridge status queries:

```python
# Inbound: "Is my Solana burn confirmed on Mirage?"
result = db.get_bridge_attestation("solana", burn_signature)
# Returns: {found: True, minted: True, tx_hash: "...", recipient: "mirage1..."}

# Outbound: "Is my Mirage burn minted on Solana?"
result = db.get_bridge_burn(mirage_tx_hash)
# Returns: {found: True, minted: True, destination_tx: "...", destination_chain: "solana"}
```

---

## Content Processing

### Thumbnail Discovery

For root posts, the indexer attempts to extract a preview thumbnail from content URLs:

```python
def discover_post_thumbnail(self, content: str) -> str | None:
    """Discover thumbnail for root post content."""
    first_url = self._extract_first_url(content)
    
    # Direct image URL
    if self._is_raster_image_url(first_url):
        return first_url
        
    # Cloudflare Stream video
    uid = self._extract_stream_uid(first_url)
    if uid:
        return f"https://videodelivery.net/{uid}/thumbnails/thumbnail.jpg"
        
    # YouTube video
    yt_id = self._extract_youtube_video_id(first_url)
    if yt_id:
        return f"https://img.youtube.com/vi/{yt_id}/hqdefault.jpg"
        
    # Fetch and parse HTML for og:image
    html = self._fetch_html(first_url)
    # ... parse meta tags, probe image dimensions
```

**Security considerations:**
- Only public HTTP(S) URLs are processed
- Private/loopback IPs are rejected
- HTML fetch has timeout and size limits
- Image probing has byte limits

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
| WebSocket disconnect | Falls back to polling | Automatic reconnection |
| Message processing error | Block skipped | Manual investigation required |

### Database Migrations

Migrations run automatically on startup:

```python
migration_count = run_migrations(self.db, self.chain)
if migration_count > 0:
    logger.info(f"Completed {migration_count} migrations")
```

Migrations are idempotent and versioned. The `meta` table tracks migration state.

### Memory Considerations

The indexer maintains several in-memory structures:
- `_seen_txs`: Set of processed transaction hashes (bounded to ~10K entries)
- `_proposal_cache`: Pending proposal messages (cleared on execution)
- `_skipped_proposals`: Proposals that couldn't be resolved

For very long catch-up periods, memory usage remains bounded due to cleanup routines.

---

## API Port Usage Policy

The indexer follows a strict API usage policy:

```
✓ gRPC (9090): All chain queries (governance, bank, profiles, params)
✓ RPC (26657): Tendermint queries (status, block, block_results, websocket)
✗ REST (1317): NEVER used (not enabled, matches backend pattern)
```

This ensures consistency across all services querying the blockchain.
