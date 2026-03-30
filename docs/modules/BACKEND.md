# Mirage Web Backend

This document provides a comprehensive technical overview of the Mirage web backend, a Flask-based Python service that acts as the relay layer between frontend clients and the blockchain. It is intended for senior engineers, architects, and project managers who need to understand the system's design philosophy, transaction flow, and the rationale behind key implementation choices.

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture Philosophy](#architecture-philosophy)
3. [Component Structure](#component-structure)
4. [Runtime Initialization](#runtime-initialization)
5. [Transaction Relay Flow](#transaction-relay-flow)
6. [Proof-of-Work Validation](#proof-of-work-validation)
7. [Canonical Message Serialization](#canonical-message-serialization)
8. [Signature Verification](#signature-verification)
9. [Gas Estimation and Broadcasting](#gas-estimation-and-broadcasting)
10. [API Endpoints](#api-endpoints)
11. [Chain Query Helpers](#chain-query-helpers)
12. [Database Integration](#database-integration)
13. [Bridge Endpoints](#bridge-endpoints)
14. [Security Model](#security-model)
15. [Observability](#observability)
16. [Operational Considerations](#operational-considerations)

---

## Overview

The backend serves as the "relay" layer in Mirage's meta-transaction architecture. Users sign messages client-side but don't directly interact with the blockchain. Instead, the backend:

1. Receives meta-signed messages from clients
2. Validates signatures, PoW (for free users), and content
3. Wraps messages in proper Cosmos SDK transactions
4. Pays gas fees on behalf of users (from validator funds)
5. Broadcasts transactions to the blockchain
6. Queries the indexer database for read operations

**Key Design Principle:** The backend enables a gas-free user experience. Users never need to hold tokens for gas fees - validators relay their transactions and charge fees from subscription reserves (paid users) or accept PoW spam protection (free users).

---

## Architecture Philosophy

### Why a Relay Backend?

Traditional blockchain apps require users to:
1. Manage private keys for signing
2. Hold tokens for gas fees
3. Understand transaction mechanics

Mirage abstracts all of this:

```
┌─────────────┐      ┌─────────────┐      ┌─────────────┐      ┌─────────────┐
│   Client    │      │   Backend   │      │  Blockchain │      │   Indexer   │
│  (Browser)  │      │   (Flask)   │      │   (Cosmos)  │      │ (PostgreSQL)│
├─────────────┤      ├─────────────┤      ├─────────────┤      ├─────────────┤
│ - Sign msg  │ ───► │ - Validate  │ ───► │ - Verify    │ ───► │ - Index     │
│ - Compute   │      │ - Wrap tx   │      │ - Execute   │      │ - Query     │
│   PoW       │      │ - Pay gas   │      │ - Store     │      │ - Aggregate │
│             │ ◄─── │ - Broadcast │ ◄─── │             │ ◄─── │             │
└─────────────┘      └─────────────┘      └─────────────┘      └─────────────┘
```

**Benefits:**
- No gas token management for users
- Consistent UX across subscription tiers
- Backend can enforce additional validation
- Single point for rate limiting and monitoring

### Validator as Fee Payer

Each backend instance is tightly coupled to a validator node:

```python
@dataclass
class Runtime:
    rpc_url: str                    # Tendermint RPC
    api_url: str                    # gRPC-gateway REST
    grpc_target: str                # gRPC endpoint
    validator_payer_addr: str       # Fee payer address
    validator_pubkey_bytes: bytes   # Validator's secp256k1 pubkey
```

The validator's account pays all gas fees. This is recouped through:
- **Free users:** Accept PoW as spam protection (gas is validator's operating cost)
- **Paid users:** Chain deducts from user's escrowed reserve during AnteHandler

---

## Component Structure

### Core Modules

```
web/backend/
├── app.py              # Entry point (Flask app)
├── factory.py          # App factory, blueprint registration, push listener startup
├── node.py             # Runtime initialization, validator key resolution
├── chain.py            # Chain queries (difficulty, block hashes)
├── pow.py              # PoW helpers, canonical message building
├── tx.py               # Transaction building, simulation, broadcast
├── bank.py             # Balance queries
├── params.py           # Chain parameter loading/caching
├── db.py               # Database connections (indexer RO + backend RW) and schema init
├── quest_tracker.py    # Quest progress tracking (backend-owned)
├── quest_settings.py   # Quest system constants
├── quests.yaml         # Quest definitions
├── reward_distributor.py # Token reward distribution
├── similarity.py       # User similarity cache
├── user_last_seen.py   # DAU/MAU tracking via authenticated API hits
├── push_events.py      # Push notification deduplication helpers
├── push_listener.py    # Background thread polling indexer for cross-node push events
├── routes/
│   ├── public.py       # Read-only endpoints (feeds, profiles, search, stats)
│   ├── core.py         # Write endpoints (post, vote, username, etc.)
│   ├── quests.py       # Quest/reward endpoints
│   └── bridge.py       # Bridge endpoints (attested transfers)
└── logging_utils.py    # Structured logging
```

### Blueprint Organization

Routes are organized into three Flask blueprints:

| Blueprint | Prefix | Purpose |
|-----------|--------|---------|
| `public_bp` | `/api/` | Read operations, no auth required |
| `core_bp` | `/api/core/` | Write operations, requires meta-signature |
| `quests_bp` | `/api/rewards/` | Quest/reward endpoints |
| `bridge_bp` | `/api/bridge/` | Cross-chain operations |

---

## Runtime Initialization

### Startup Sequence

```python
def initialize_runtime() -> Runtime:
    # 1. Verify node home directory and config files
    assert_node_home_ready()
    
    # 2. Resolve URLs from config
    rpc_url = get_rpc_url()      # http://localhost:26657
    api_url = get_api_url()      # http://localhost:1317
    grpc_target = get_grpc_target()  # localhost:9090
    
    # 3. Resolve validator key from keyring
    validator_payer_addr = resolve_validator_payer_address()
    validator_pubkey_bytes = resolve_validator_pubkey_bytes()
    
    # 4. Wait for gRPC to be ready (up to 1 hour with retries)
    assert_grpc_ready(timeout_s=2.0, max_retries=360)
    
    # 5. Load chain parameters
    load_params()
    
    return Runtime(...)
```

**Key Files Required:**
- `~/.mirage/config/app.toml` - gRPC address, minimum gas prices
- `~/.mirage/config/config.toml` - RPC address
- `~/.mirage/config/priv_validator_key.json` - Consensus pubkey
- `~/.mirage/keyring-*` - Validator account key

### Address Derivation

The backend derives user addresses from their public keys:

```python
def derive_address_from_pubkey(pubkey_bytes: bytes, hrp: str = "mirage") -> str:
    # Standard Cosmos address derivation:
    # SHA256 -> RIPEMD160 -> Bech32
    sha = hashlib.sha256(pubkey_bytes).digest()
    ripemd = hashlib.new("ripemd160")
    ripemd.update(sha)
    digest20 = ripemd.digest()
    data5 = convertbits(digest20, 8, 5)
    return bech32_encode(hrp, data5)
```

This allows the backend to identify the sender without requiring them to explicitly provide their address.

---

## Transaction Relay Flow

### Complete Flow for Core Messages

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                         TRANSACTION RELAY FLOW                                │
├──────────────────────────────────────────────────────────────────────────────┤
│  1. Client Request                                                            │
│     POST /api/core/post                                                       │
│     {                                                                         │
│       "pubkey": "A1B2...",        // Base64 compressed secp256k1              │
│       "signature": "R3S4...",     // Base64 64-byte (r||s)                    │
│       "last_block_hash": "ABC...", // Recent block hash for replay protection │
│       "timestamp": 1700000000,    // Unix seconds                             │
│       "pow_difficulty": 3,        // Difficulty steps (free users)            │
│       "pow": 98765,               // Nonce that produces valid hash           │
│       "topic": "technology",                                                  │
│       "title": "Hello World",                                                 │
│       "content": "..."                                                        │
│     }                                                                         │
│                                                                               │
│  2. Backend Validation                                                        │
│     a. Check node sync status (reject if catching up)                         │
│     b. Decode pubkey and signature                                            │
│     c. Derive user address from pubkey                                        │
│     d. Check subscription status:                                             │
│        - Subscriber: Skip PoW validation                                      │
│        - Free user: Validate PoW proof                                        │
│     e. Validate content (length, format)                                      │
│     f. Build canonical message bytes                                          │
│     g. Verify secp256k1 signature over SHA256(canonical_bytes)                │
│                                                                               │
│  3. Transaction Building                                                      │
│     a. Create protobuf message (MsgPost)                                      │
│     b. Set authority = validator_payer_addr                                   │
│     c. Set envelope fields (pubkey, signature, pow, timestamp, block_hash)    │
│     d. Wrap in TxBody with memo=""                                            │
│     e. Estimate gas limit                                                     │
│     f. Simulate transaction (REST)                                            │
│     g. Build TxRaw with fee (paid by validator)                               │
│                                                                               │
│  4. Broadcast                                                                 │
│     a. Compute tx_hash = SHA256(tx_bytes)                                     │
│     b. Broadcast via REST (sync)                                              │
│     c. Return tx_hash immediately (don't wait for inclusion)                  │
│                                                                               │
│  5. Response                                                                  │
│     {"tx_hash": "...", "code": 0, "height": 0, "raw_log": ""}                 │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## Proof-of-Work Validation

### Free User PoW Flow

Free users must compute Argon2id PoW to submit transactions:

```python
def argon2_digest(base: bytes, last_block_hash: str, proof: int) -> bytes:
    """Compute Argon2id hash for PoW validation."""
    salt = bytes.fromhex(last_block_hash)
    return hash_secret_raw(
        base + b":" + uvarint(proof),  # Message with nonce
        salt,                           # Recent block hash as salt
        time_cost=1,
        memory_cost=4096,              # 4MB
        parallelism=1,
        hash_len=32,
        type=Argon2Type.ID,
    )

import math

def check_pow_target(digest: bytes, difficulty: int, pow_base_bits: int, pow_factor: float) -> bool:
    """Target-based PoW check. difficulty is steps (0=base, 1=+step, 2=+step^2)."""
    if difficulty < 0 or pow_factor <= 0 or pow_factor > 1:
        return False
    base_target = 1 << (256 - pow_base_bits)
    factor = int(math.floor(1000 * (1 + pow_factor) ** difficulty + 0.5))
    eff_target = base_target * 1000 // factor
    return int.from_bytes(digest, "big") <= eff_target
```

**Validation Steps:**

1. **Difficulty Steps:** `declared_difficulty` is a step count (0 = base)
2. **Block Hash Check:** `last_block_hash` is in recent window (configurable, typically 5 blocks)
3. **Hash Verification:** `check_pow_target(argon2_digest(...), effective_difficulty, pow_base_bits, pow_factor)`

### Difficulty Allowance

The chain has a "difficulty allowance" period after difficulty changes:

```python
def _effective_difficulty(declared: int) -> int:
    """Mirror chain's validatePoWBytesArgon2 threshold logic (step counts)."""
    info = get_difficulty_info()
    current = info["current_difficulty"]
    prev = info["previous_difficulty"]
    last_change = info["last_change_height"]
    height = info["current_height"]
    allowance = params["pow_difficulty_grace_period"]
    
    min_required = current
    if allowance > 0 and height - last_change <= allowance:
        # Accept either current or previous difficulty
        min_required = min(current, prev)
    
    return max(declared, min_required)
```

**Rationale:** When difficulty increases, users who computed PoW with the old difficulty shouldn't have their work invalidated immediately.

---

## Canonical Message Serialization

### Building Canonical Bytes

Each message type has a canonical serialization for signing:

```python
def canon_base_post(
    pub_dec: bytes,
    last_block_hash: str,
    difficulty: int,
    timestamp: int,
    target: str,
    topic: str,
    title: str,
    content: str,
    tag: str = "",
) -> bytes:
    return canon_shared.canon_base_post(
        pub_dec,
        hex_to_bytes(last_block_hash),
        difficulty,
        timestamp,
        target, topic, title, content, tag
    )
```

The shared `canon` module (in `shared/canon.py`) builds deterministic byte sequences:

```
Canonical Format:
┌─────────────────────────────────────────────────────────────────────────┐
│  MsgName: "MsgPost"                                                      │
│  Fields (sorted by tag number):                                          │
│    Tag 2: envelope_pubkey (33 bytes)                                     │
│    Tag 3: envelope_block_hash (32 bytes)                                 │
│    Tag 4: envelope_difficulty (varint)                                   │
│    Tag 5: envelope_timestamp (varint)                                    │
│    Tag 100: target (length-prefixed string)                              │
│    Tag 101: topic (length-prefixed string)                               │
│    Tag 102: title (length-prefixed string)                               │
│    Tag 103: content (length-prefixed string)                             │
│    Tag 104: tag (length-prefixed string)                                 │
└─────────────────────────────────────────────────────────────────────────┘
```

**Critical:** The `authority` field (tag 1) is NOT included in canonical bytes. It's set by the backend to the validator's address.

### Signed Bytes with PoW

For signature verification, the canonical bytes are combined with the PoW proof:

```python
def canon_signed_with_pow(base: bytes, proof: int) -> bytes:
    """Combine canonical bytes with PoW nonce for signing."""
    return base + b":" + uvarint(proof)
```

---

## Signature Verification

### secp256k1 Signature Verification

```python
def _verify_signature(pub_dec: bytes, sig_dec: bytes, signed_bytes: bytes) -> bool:
    """Verify compact 64-byte (r||s) signature over SHA256(signed_bytes)."""
    # 1. Hash the signed bytes
    digest = hashlib.sha256(signed_bytes).digest()
    
    # 2. Parse compact signature (r||s) to DER
    r = int.from_bytes(sig_dec[:32], "big")
    s = int.from_bytes(sig_dec[32:], "big")
    der = encode_der_signature(r, s)
    
    # 3. Load public key and verify
    pub = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256K1(), pub_dec)
    pub.verify(der, digest, ec.ECDSA(Prehashed(hashes.SHA256())))
    return True
```

### Signature Normalization

The backend handles various signature formats:

```python
def normalize_compact_signature(sig: bytes) -> bytes | None:
    """Normalize signature to 64-byte compact format with low-S."""
    if len(sig) == 64:
        # Enforce low-S per secp256k1 rules
        r, s = sig[:32], sig[32:]
        s_int = int.from_bytes(s, "big")
        if s_int > HALF_N:
            s_int = N - s_int
            s = s_int.to_bytes(32, "big")
        return r + s
    if len(sig) == 65:
        # Strip recovery byte
        return sig[:64]
    if sig[0] == 0x30:
        # Parse DER to compact
        return parse_der_to_compact(sig)
    return None
```

---

## Gas Estimation and Broadcasting

### Gas Estimation

Gas is estimated using a combination of heuristics and simulation:

```python
def estimate_total_gas_limit(body_bytes: bytes, content_len: int) -> int:
    """Heuristic gas estimator."""
    tx_size_ppb = get_tx_size_cost_per_byte()  # From auth module params
    
    def txraw_len(gas_lim: int) -> int:
        # Build mock TxRaw to measure size
        fee = Fee(gas_limit=gas_lim, amount=[Coin(...)])
        auth = AuthInfo(signer_infos=[...], fee=fee)
        tx_raw = TxRaw(body_bytes=body_bytes, auth_info_bytes=auth.SerializeToString())
        return len(tx_raw.SerializeToString())
    
    # Iterative estimation
    gas_guess = 1
    for _ in range(2):
        size_gas = tx_size_ppb * txraw_len(gas_guess)
        store_gas = 1000 + 2000 + (30 * content_len)
        new_gas = size_gas + store_gas + 1024
        gas_guess = round_up_to_64(new_gas)
    
    return gas_guess
```

### Transaction Building

```python
def build_tx_bytes(body_bytes: bytes, gas_limit: int) -> bytes:
    """Construct TxRaw bytes with validator as fee payer."""
    min_gas_price = min_gas_price_umirage()
    fee_amt = ceil(gas_limit * min_gas_price)
    
    fee = Fee(gas_limit=gas_limit)
    fee.amount.append(Coin(denom="umirage", amount=str(fee_amt)))
    fee.payer = require_runtime().validator_payer_addr  # Validator pays
    
    # Get validator's current sequence number
    sequence = get_account_sequence(validator_payer_addr)
    
    # Build AuthInfo with validator's pubkey
    pub_any = AnyPB()
    pub_any.Pack(SecpPubKey(key=validator_pubkey_bytes))
    si = SignerInfo(public_key=pub_any, sequence=sequence)
    auth = AuthInfo(signer_infos=[si], fee=fee)
    
    # Placeholder signature (chain validates envelope signature, not SDK signature)
    return TxRaw(
        body_bytes=body_bytes,
        auth_info_bytes=auth.SerializeToString(),
        signatures=[b"\x00"]  # Placeholder
    ).SerializeToString()
```

### Broadcasting

Transactions are broadcast synchronously via the Cosmos tx REST service:

```python
def broadcast_tx(tx_bytes: bytes) -> Tuple[str, int, int, str]:
    """Broadcast transaction via REST (BROADCAST_MODE_SYNC)."""
    tx_hash = hashlib.sha256(tx_bytes).hexdigest().lower()
    payload = {
        "tx_bytes": base64.b64encode(tx_bytes).decode(),
        "mode": "BROADCAST_MODE_SYNC",
    }
    resp = requests.post(f"{api_url}/cosmos/tx/v1beta1/txs", json=payload, timeout=10)
    resp.raise_for_status()
    body = resp.json()
    tx_resp = body.get("tx_response") or {}
    return (
        tx_resp.get("txhash", tx_hash).lower(),
        int(tx_resp.get("code", 0) or 0),
        int(tx_resp.get("height", 0) or 0),
        str(tx_resp.get("raw_log", "") or ""),
    )
```

**Why sync?** It returns the CheckTx result immediately while staying non-blocking on DeliverTx. The frontend still polls `GET /api/get_tx_status` for indexing.

---

## API Endpoints

### Public Endpoints (Read-Only)

| Endpoint | Purpose |
|----------|---------|
| `GET /api/get_parameters` | Block hash, difficulty, pow_base_bits, pow_factor, optional balance |
| `GET /api/get_chain_config` | Chain governance params (tiers, limits, periods) |
| `GET /api/get_node_config` | Per-node static settings (validator info, flags) |
| `GET /api/get_user_status` | User status (level, balance, subscription) |
| `GET /api/get_tx_status` | Transaction status with enrichment |
| `GET /api/get_topics` | Most active topics |
| `GET /api/get_posts` | Recent posts with aggregates |
| `GET /api/get_user_posts` | Posts by specific user |
| `GET /api/get_comments` | Comment tree for a post |
| `GET /api/get_profile` | User profile with lists |
| `GET /api/search` | Full-text search |
| `GET /api/get_welcome_stats` | Public stats: registered users, posts 24h, DAU |
| `GET /api/get_stats` | Admin stats (overview, signups tabs) |
| `POST /api/signup` | Account creation (validates invite code) |
| `GET /api/validate_invite_code` | Check invite code validity |
| `GET /api/get_inbox` | Push notification inbox |
| `POST /api/mark_inbox_viewed` | Mark inbox items as read |
| `GET /api/rewards/summary` | Quest/reward progress |
| `GET /api/rewards/achievements` | Achievement list |
| `POST /api/rewards/claim` | Claim pending reward |
| `GET /api/referral/stats` | Referrer's invite stats |

### Core Endpoints (Write)

| Endpoint | Message Type |
|----------|--------------|
| `POST /api/core/post` | MsgPost |
| `POST /api/core/edit` | MsgEdit |
| `POST /api/core/vote` | MsgVote |
| `POST /api/core/set_username` | MsgSetUsername |
| `POST /api/core/follow_user` | MsgFollowUser |
| `POST /api/core/unfollow_user` | MsgUnfollowUser |
| `POST /api/core/follow_topic` | MsgFollowTopic |
| `POST /api/core/unfollow_topic` | MsgUnfollowTopic |
| `POST /api/core/enable_agent` | MsgEnableAgent |
| `POST /api/core/disable_agent` | MsgDisableAgent |
| `POST /api/core/block_post` | MsgBlockPost |
| `POST /api/core/block_user` | MsgBlockUser |
| `POST /api/core/delete` | MsgDelete |
| `POST /api/core/send_tokens` | MsgSendTokens |
| `POST /api/core/subscribe` | MsgSubscribe |
| `POST /api/core/set_auto_renewal` | MsgSetAutoRenewal |
| `POST /api/core/award` | MsgAward (burn MIRAGE to award a post/comment) |
| `POST /api/core/report` | Content reporting |

### Bridge Endpoints

| Endpoint | Purpose |
|----------|---------|
| `GET /api/bridge/config` | Enabled chains, fees |
| `POST /api/bridge/burn` | Burn for attested bridge (Solana) |
| `GET /api/bridge/status` | Query bridge status and attestation progress |

---

## Chain Query Helpers

### Difficulty Information

```python
def get_difficulty_info(timeout: float = 3.0) -> Dict[str, Any]:
    """Get full difficulty state from chain via gRPC."""
    with grpc.insecure_channel(grpc_target) as channel:
        method = channel.unary_unary(
            "/mirage.core.v1.Query/GetDifficulty",
            request_serializer=lambda msg: msg.SerializeToString(),
            response_deserializer=QueryDifficultyResponse.ParseFromString,
        )
        resp = method(QueryDifficultyRequest(), timeout=timeout)
    
    return {
        "current_difficulty": resp.current_difficulty,
        "previous_difficulty": resp.previous_difficulty,
        "last_change_height": resp.last_change_height,
        "pow_message_count": resp.pow_message_count,
        "latest_block_hash": resp.latest_block_hash,
        "current_height": resp.current_height,
    }
```

### Recent Block Hashes

```python
def get_recent_block_hashes(timeout_s: int = 5) -> list[str]:
    """Get recent block hashes for PoW validation."""
    window = get_block_hash_window()  # From chain params
    
    # Get latest from /status
    status = fetch_rpc_status()
    latest_height = status["sync_info"]["latest_block_height"]
    
    # Fetch each block's hash
    hashes = []
    for i in range(window):
        h = latest_height - i
        block = fetch_block(h)
        hashes.append(block["block_id"]["hash"])
    
    return hashes
```

---

## Database Integration

### Dual-Database Architecture

The backend uses two separate PostgreSQL databases with strict ownership boundaries:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         DATABASE ARCHITECTURE                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Indexer DB (mirage_indexer)      Backend DB (mirage_backend)                │
│  ┌──────────────────────┐         ┌──────────────────────────────┐          │
│  │ posts, votes, awards │         │ invite_codes, referral_*     │          │
│  │ profiles, balances   │         │ user_daily_quests, pending_  │          │
│  │ followed_*, blocked_*│         │   rewards, user_quest_state  │          │
│  │ preferences          │         │ push_tokens, push_throttle   │          │
│  │ bridge_transactions  │         │ push_event_cursor/seen       │          │
│  │ supply_history       │         │ reports, user_similarity_    │          │
│  │ mentions, tx_index   │         │   cache, user_last_seen      │          │
│  │ (chain-indexed data) │         │ user_inbox_state             │          │
│  └──────────┬───────────┘         └──────────────┬───────────────┘          │
│             │                                    │                          │
│     READ-ONLY access                    READ-WRITE access                   │
│     (mirage_indexer_ro role)            (mirage_backend role)                │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Connection helpers in `db.py`:**

```python
def connect_db() -> psycopg.Connection:
    """READ-ONLY connection to the indexer DB (via mirage_indexer_ro role)."""
    url = cfg.get_indexer_ro_url()  # INDEXER_DB_RO_URL env var
    return psycopg.connect(url, autocommit=True)

def connect_backend_db() -> psycopg.Connection:
    """READ-WRITE connection to the backend-owned DB."""
    url = cfg.get_backend_db_url()  # BACKEND_DB_URL env var
    return psycopg.connect(url, autocommit=True)
```

**Required environment variables:**

| Variable | Example | Purpose |
|----------|---------|---------|
| `INDEXER_DB_URL` | `postgresql://mirage_indexer:mirage_indexer@127.0.0.1:5432/mirage_indexer` | Indexer read-write (used by indexer process) |
| `INDEXER_DB_RO_URL` | `postgresql://mirage_indexer_ro:mirage_indexer_ro@127.0.0.1:5432/mirage_indexer` | Backend read-only access to indexer |
| `BACKEND_DB_URL` | `postgresql://mirage_backend:mirage_backend@127.0.0.1:5432/mirage_backend` | Backend-owned tables |

The backend **never writes** to the indexer DB. The `mirage_indexer_ro` PostgreSQL role enforces this at the database level — any accidental write attempt results in `permission denied`.

### Schema Initialization

`init_backend_schema()` runs at backend startup and creates all backend-owned tables idempotently (`CREATE TABLE IF NOT EXISTS`). It also validates existing table schemas via `_assert_table_schema()`, which raises `RuntimeError` if columns are missing or types don't match.

### Common Query Patterns

```python
# Read from indexer DB (chain-indexed data)
def is_subscriber(addr: str) -> bool:
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT level FROM profiles WHERE LOWER(owner) = LOWER(%s)", (addr,))
        row = cur.fetchone()
        return row and row[0] >= 1

# Write to backend DB (operational data)
def update_user_last_seen(addr: str) -> None:
    with connect_backend_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO user_last_seen (owner, last_seen_at) VALUES (%s, %s) "
            "ON CONFLICT (owner) DO UPDATE SET last_seen_at = EXCLUDED.last_seen_at",
            (addr, int(time.time())),
        )
```

### Push Listener

The backend runs a background thread (`push_listener.py`) that polls the indexer DB for new posts and awards, triggering push notifications for cross-node activity (e.g., someone replies to your post via a different node). The listener uses `push_event_seen` and `push_event_cursor` tables for deduplication and cursor tracking. Only one listener runs across all Gunicorn workers (gated by `fcntl.flock`).

### User Activity Tracking

`user_last_seen.py` updates a timestamp in the backend DB on every authenticated API hit, throttled to one DB write per user per 60 seconds via an in-memory cache. This powers the DAU/MAU metrics in `/api/get_welcome_stats` and `/api/get_stats`.

---

## Bridge Endpoints

### Attested Bridge (Solana)

For validator-attested chains:

```python
@bridge_bp.route("/api/bridge/burn", methods=["POST"])
def bridge_burn():
    # 1. Validate request
    destination_chain = data["destination_chain"]  # e.g., "solana"
    destination_address = data["destination_address"]
    amount = data["amount"]
    
    # 2. Verify chain is enabled
    if not _resolve_enabled_attested_chain(destination_chain):
        return error("destination_chain not enabled")
    
    # 3. Chain-specific address validation
    if destination_chain == "solana":
        decoded = base58_decode(destination_address)
        if len(decoded) != 32:
            return error("invalid solana address")
    
    # 4. Build and broadcast MsgBridgeBurn
    msg = MsgBridgeBurn()
    msg.destination_chain = destination_chain
    msg.destination_address = destination_address
    msg.amount = amount
    # ... envelope fields, broadcast
```

---

## Security Model

### Request Validation

All write endpoints validate:

1. **Node Sync Status:** Reject if node is catching up
2. **Required Fields:** All mandatory fields present
3. **Field Formats:** Length limits, address formats
4. **Pubkey/Signature:** Valid lengths and formats
5. **Content Limits:** Title, content, topic within chain params
6. **Subscription/PoW:** Appropriate authorization model

### PoW vs Subscription

```python
user_is_sub = is_subscriber(user_addr)

if not user_is_sub:
    # Free user: require valid PoW
    if proof is None:
        return error("pow_required")
    if difficulty < get_current_pow_difficulty():
        return error("insufficient pow")
    if not is_valid_recent_block_hash(last_block_hash):
        return error("invalid last_block_hash")
else:
    pass  # Subscriber: PoW fields ignored; chain handles via reserve
```

### Error Response Format

Failed broadcasts return structured errors:

```python
def _tx_error(rid, endpoint, msg_type, code, tx_hash, raw_log, extra=None):
    info = classify_reject(raw_log)  # Parse common reject reasons
    info.update({
        "code": code,
        "tx_type": msg_type,
        "endpoint": endpoint,
        "tx_hash": tx_hash,
    })
    log_event(rid, f"{endpoint}.reject", ...)
    return jsonify({"error": info["message"], "details": info}), 400
```

The `classify_reject` function parses common error patterns:
- `out_of_gas`: Gas limit exceeded
- `payer_insufficient_funds`: Validator account needs funding
- `invalid_relay_fields`: Signature or envelope validation failed

---

## Observability

### Structured Logging

Every request is assigned a unique ID and logged:

```python
@core_bp.route("/api/core/post", methods=["POST"])
def core_post():
    rid = next_request_id()
    log_event(rid, "post.begin")
    
    # ... processing ...
    
    log_event(rid, "post.parsed", 
              pubkey_len=len(pub_b64),
              topic=topic,
              content_len=len(content))
    
    # ... validation ...
    
    log_event(rid, "post.success", tx_hash=tx_hash)
    return jsonify({"tx_hash": tx_hash})
```

### Request Tracing

Request IDs allow correlating log entries:

```
[2024-01-15 12:34:56] req-12345 post.begin
[2024-01-15 12:34:56] req-12345 post.parsed pubkey_len=44 topic=technology content_len=256
[2024-01-15 12:34:57] req-12345 post.success tx_hash=abc123...
```

---

## Operational Considerations

### Deployment

The backend is deployed via Gunicorn:

```bash
gunicorn --bind 0.0.0.0:5000 --workers 4 app:app
```

### Dependencies

Required at runtime:
- PostgreSQL — two databases: `mirage_indexer` (indexer) and `mirage_backend` (backend)
- `mirage_indexer_ro` PostgreSQL role with read-only access to the indexer DB
- Mirage node (RPC, gRPC)
- Validator keyring with "validator" key

### Configuration

Environment variables (set in `~/.mirage/env/backend.env`):
- `BACKEND_PORT` - Listen port (default: 5000)
- `BACKEND_HOST` - Bind address (default: 127.0.0.1)
- `INDEXER_DB_URL` - Indexer DB connection string (used by indexer, not backend directly)
- `INDEXER_DB_RO_URL` - Read-only connection to indexer DB (used by backend)
- `BACKEND_DB_URL` - Backend-owned DB connection string
- `CLIENT_HASH_SALT` - Salt for hashing client identifiers (compliance)
- `REFERRALS_ENABLED` - Enable referral system endpoints (default: false)
- `PUSH_NOTIFICATIONS_ENABLED` - Enable push notification system (default: false)
- `PUSH_LISTENER_LOCK_PATH` - Lock file path for push listener singleton

### Health Checks

The backend doesn't have a dedicated health endpoint, but `GET /api/get_parameters` serves this purpose - it queries the chain and returns quickly.

### Rate Limiting

Rate limiting is currently handled at the infrastructure level (nginx, cloud provider). The PoW mechanism provides natural spam protection for free users.

### Failure Modes

| Failure | Impact | Recovery |
|---------|--------|----------|
| Indexer DB unavailable | Read endpoints fail | Automatic reconnection |
| Backend DB unavailable | Quests, push, stats fail | Automatic reconnection |
| Node RPC unavailable | All endpoints fail 503 | Backend waits for node |
| Validator underfunded | Broadcasts fail | Fund validator account |
| Chain params unavailable | Backend won't start | Chain must be accessible |
