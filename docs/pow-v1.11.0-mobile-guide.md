# Mirage PoW Implementation Guide — v1.11.0

> Target audience: Mobile app developer  
> Last updated: 2026-02-14

This document describes the Proof-of-Work (PoW) system as of **v1.11.0**. It covers the full transaction lifecycle: fetching parameters, building canonical bytes, mining the PoW, signing, and submitting.

---

## Table of Contents

1. [Overview](#1-overview)
2. [Fetching Parameters](#2-fetching-parameters)
3. [Subscriber vs Free User](#3-subscriber-vs-free-user)
4. [Canonical Bytes Format](#4-canonical-bytes-format)
5. [Message Types & Payload Fields](#5-message-types--payload-fields)
6. [PoW Mining (Argon2id)](#6-pow-mining-argon2id)
7. [Difficulty Target Formula](#7-difficulty-target-formula)
8. [Signing](#8-signing)
9. [Submitting to Backend](#9-submitting-to-backend)
10. [Full Transaction Flow (Step by Step)](#10-full-transaction-flow-step-by-step)
11. [Vote Direction Encoding](#11-vote-direction-encoding)
12. [Timestamp Handling](#12-timestamp-handling)
13. [Reference: uvarint Encoding](#13-reference-uvarint-encoding)

---

## 1. Overview

Every write transaction in Mirage goes through a **relay** system. The client builds a canonical byte representation of the message, optionally mines a PoW proof, signs the result, and POSTs it to the backend. The backend relays it to the blockchain.

**Key change in v1.11.0**: PoW difficulty is now a **step-based** system with three parameters (`pow_difficulty`, `pow_base_bits`, `pow_factor`) instead of the old single `pow_difficulty` value. The mining algorithm uses **Argon2id** with a **target-based** difficulty check.

---

## 2. Fetching Parameters

Before any write transaction, fetch current chain parameters:

```
GET /api/get_parameters?address=<bech32_address>
```

Response (relevant fields):

```json
{
  "last_block_hash": "a1b2c3...64hex_chars",
  "pow_difficulty": 0,
  "pow_base_bits": 8,
  "pow_factor": 0.25,
  "balance": "1000000",
  "user_level": 0
}
```

| Field | Type | Description |
|-------|------|-------------|
| `last_block_hash` | string (hex) | Latest block hash — used as Argon2 salt and in canonical bytes |
| `pow_difficulty` | int >= 0 | Difficulty **steps** (0 = base difficulty, higher = harder) |
| `pow_base_bits` | int > 0 | Base number of leading zero bits for the PoW target |
| `pow_factor` | float in (0, 1] | Scaling factor per difficulty step |
| `user_level` | int | 0 = free user, 1+ = subscriber |

---

## 3. Subscriber vs Free User

| User Level | PoW Required? | `pow_difficulty` to send | `pow` to send |
|-----------|---------------|--------------------------|---------------|
| 0 (free) | **YES** — always, even when `pow_difficulty` from server is 0 | The value from `get_parameters` | Computed proof nonce |
| 1+ (subscriber) | **NO** | `0` | `0` (or omit) |

**Important**: `pow_difficulty = 0` for a free user does NOT mean "no PoW". It means base difficulty (0 extra steps). You still must mine a valid Argon2id hash.

Actions that **never** require PoW (regardless of user level):
- `upgrade_level` (paid with tokens)
- `set_auto_renewal` (paid with tokens)

---

## 4. Canonical Bytes Format

All transactions use a two-phase canonical byte format:

### Phase 1: Base Canonical (used for PoW mining)

```
PREFIX || tag2(pubkey) || tag3(block_hash) || tag4(difficulty) || tag6(timestamp) || payload_fields...
```

Note: **tag 5 (pow) is NOT included** in the base canonical.

### Phase 2: Signed Canonical (used for signature)

The base canonical with tag 5 (pow proof) **inserted between tag 4 and tag 6**:

```
PREFIX || tag2(pubkey) || tag3(block_hash) || tag4(difficulty) || tag5(pow) || tag6(timestamp) || payload_fields...
```

### Prefix

```
"mirage.core.v1:" + MsgName + "\x00"
```

Example for a post: `mirage.core.v1:MsgPost\x00`

### Field Encoding

Each field is encoded as: `tag_byte || encoded_value`

| Type | Encoding |
|------|----------|
| **bytes** | `tag(1 byte) + uvarint(length) + raw_bytes` |
| **string** | `tag(1 byte) + uvarint(byte_length) + utf8_bytes` |
| **uint64** | `tag(1 byte) + uvarint(value)` |

The `tag` is a single byte (e.g., `0x02` for tag 2, `0x64` for tag 100).

### Envelope Fields (all messages share these)

| Tag | Name | Type | Notes |
|-----|------|------|-------|
| 2 | `envelope_pubkey` | bytes | Compressed secp256k1 public key (33 bytes) |
| 3 | `envelope_block_hash` | bytes | `last_block_hash` decoded from hex to raw bytes |
| 4 | `envelope_difficulty` | uint64 | Difficulty steps integer |
| 5 | `envelope_pow` | uint64 | PoW proof nonce (**only in signed canonical**) |
| 6 | `envelope_timestamp` | uint64 | Millisecond Unix timestamp |

**NOT included in canonical bytes**:
- Tag 1 (`authority`) — set by the backend/node, never by the client
- Tag 10 (`signature`) — this is what we're computing

---

## 5. Message Types & Payload Fields

Payload fields start at tag 100. All fields are always included (use empty string `""` if not applicable).

### MsgPost (create_post / create_comment)

| Tag | Field | Type |
|-----|-------|------|
| 100 | `target` | string | Parent post hash (for comments) or `""` for top-level posts |
| 101 | `topic` | string | Topic/subreddit name (required for root posts, `""` for comments) |
| 102 | `title` | string | Post title (root posts only, `""` for comments) |
| 103 | `content` | string | Post/comment body |
| 104 | `tag` | string | Content tag: `""`, `"sensitive"`, `"porn"`, `"gore"`, `"violence"`, `"death"` |

### MsgVote

| Tag | Field | Type | Notes |
|-----|-------|------|-------|
| 100 | `target` | string | Post hash to vote on |
| 101 | `direction` | uint64 | `1` = upvote, `0` = remove, `4294967295` = downvote (see [Section 11](#11-vote-direction-encoding)) |

### MsgSetUsername

| Tag | Field | Type |
|-----|-------|------|
| 100 | `target` | string | The user's own bech32 address |
| 101 | `username` | string | Desired username |

### MsgEdit

| Tag | Field | Type |
|-----|-------|------|
| 100 | `target` | string | Parent post hash (for comments) or `""` for root posts |
| 101 | `topic` | string | Topic |
| 102 | `title` | string | New title |
| 103 | `content` | string | New content |
| 104 | `tag` | string | Content tag |
| 105 | `override` | string | Tx hash of the post/comment being edited (lowercase) |

### MsgDelete

| Tag | Field | Type |
|-----|-------|------|
| 100 | `target` | string | Tx hash of the post/comment to delete |

### MsgFollowUser / MsgUnfollowUser

| Tag | Field | Type |
|-----|-------|------|
| 100 | `target` | string | The user's own address (lowercase) |
| 101 | `user` | string | Address to follow/unfollow (lowercase) |

### MsgFollowTopic / MsgUnfollowTopic

| Tag | Field | Type |
|-----|-------|------|
| 100 | `target` | string | The user's own address (lowercase) |
| 101 | `topic` | string | Topic name (lowercase) |

### MsgBlockPost / MsgUnblockPost

| Tag | Field | Type |
|-----|-------|------|
| 100 | `target` | string | Tx hash of the post to block/unblock |

### MsgBlockUser / MsgUnblockUser

| Tag | Field | Type |
|-----|-------|------|
| 100 | `target` | string | Address of the user to block/unblock |

### MsgSendTokens

| Tag | Field | Type |
|-----|-------|------|
| 100 | `sender` | string | Sender's bech32 address |
| 101 | `target` | string | Recipient's bech32 address |
| 102 | `amount` | uint64 | Amount in umirage (1 MIRAGE = 1,000,000 umirage) |

### MsgReport

| Tag | Field | Type |
|-----|-------|------|
| 100 | `target` | string | Tx hash of the post to report |
| 101 | `reason` | string | Reason for reporting |

### MsgUpgradeLevel (no PoW — fee only)

| Tag | Field | Type |
|-----|-------|------|
| 100 | `level` | uint64 | Subscription tier (1, 2, or 3) |

### MsgSetAutoRenewal (no PoW — fee only)

| Tag | Field | Type |
|-----|-------|------|
| 100 | `auto_renew` | uint64 | `1` to enable, `0` to disable |

### MsgBridgeBurn

| Tag | Field | Type |
|-----|-------|------|
| 100 | `destination_chain` | string |
| 101 | `destination_address` | string |
| 102 | `amount` | uint64 | Amount in umirage |

---

## 6. PoW Mining (Argon2id)

### Algorithm

```
for proof = 0, 1, 2, ...:
    password = base_canonical_bytes + ":" + uvarint(proof)
    salt     = hex_decode(last_block_hash)
    digest   = argon2id(password, salt, params)
    if check_pow_target(digest, pow_difficulty, pow_base_bits, pow_factor):
        return proof
```

### Argon2id Parameters (fixed, not configurable)

| Parameter | Value |
|-----------|-------|
| `time_cost` | 1 |
| `memory_cost` | 4096 KiB (4 MiB) |
| `parallelism` | 1 |
| `hash_len` | 32 bytes |
| `type` | Argon2id |

### Input Construction

- **password**: `base_canonical_bytes` + `":"` (ASCII 0x3A) + `uvarint(proof)`
- **salt**: raw bytes from `hex_decode(last_block_hash)`

The `proof` starts at 0 (or a random uint32 for variance) and increments until a valid hash is found.

---

## 7. Difficulty Target Formula

```
BASE_DIFFICULTY_FACTOR = 1000
MAX_SAFE_DIFFICULTY_FACTOR = 2^53 - 1

difficulty_factor(steps, pow_factor):
    if steps == 0: return 1000
    factor = 1000 * (1 + pow_factor) ^ steps
    return round_half_up(factor)        // clamped to [1000, MAX_SAFE]

check_pow_target(digest_bytes, difficulty, pow_base_bits, pow_factor):
    factor = difficulty_factor(difficulty, pow_factor)
    base_target = 2^(256 - pow_base_bits)
    effective_target = base_target * 1000 / factor     // integer division
    hash_int = int.from_bytes(digest_bytes, big_endian)
    return hash_int <= effective_target
```

### Example

With `pow_base_bits=8`, `pow_factor=0.25`, `pow_difficulty=0`:

```
factor = 1000
base_target = 2^(256-8) = 2^248
effective_target = 2^248 * 1000 / 1000 = 2^248
→ Hash must have its top 8 bits all zero (≈ 1/256 chance per attempt)
```

With `pow_difficulty=3`:

```
factor = round(1000 * 1.25^3) = round(1953.125) = 1953
effective_target = 2^248 * 1000 / 1953 ≈ 2^248 * 0.512
→ ~2x harder than base
```

---

## 8. Signing

1. Build the **signed canonical** bytes (base canonical + tag 5 with proof inserted)
2. Compute `SHA256(signed_canonical_bytes)`
3. Sign the SHA256 digest with **ECDSA secp256k1** using the private key
4. Output a **64-byte compact signature** (r[32] + s[32])
5. **Low-S normalization**: if `s > n/2`, set `s = n - s`
   - `n = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141`

---

## 9. Submitting to Backend

POST the transaction as JSON to the appropriate endpoint:

| Action | Endpoint |
|--------|----------|
| Post / Comment | `POST /api/core/post` |
| Vote | `POST /api/core/vote` |
| Set Username | `POST /api/core/set_username` |
| Edit | `POST /api/core/edit` |
| Delete | `POST /api/core/delete_post` |
| Follow User | `POST /api/core/follow_user` |
| Unfollow User | `POST /api/core/unfollow_user` |
| Follow Topic | `POST /api/core/follow_topic` |
| Unfollow Topic | `POST /api/core/unfollow_topic` |
| Block Post | `POST /api/core/block_post` |
| Unblock Post | `POST /api/core/unblock_post` |
| Block User | `POST /api/core/block_user` |
| Unblock User | `POST /api/core/unblock_user` |
| Send Tokens | `POST /api/core/send_tokens` |
| Report | `POST /api/core/report` |
| Upgrade Level | `POST /api/core/upgrade_level` |
| Set Auto Renewal | `POST /api/core/set_auto_renewal` |

### JSON Payload Structure

Common fields present in every request:

```json
{
  "pubkey": "<base64 compressed public key, 33 bytes>",
  "signature": "<base64 compact signature, 64 bytes>",
  "last_block_hash": "<hex string>",
  "timestamp": 1707900000000,
  "pow_difficulty": 0,
  "pow": 42
}
```

Plus message-specific fields:

**Post example:**

```json
{
  "pubkey": "Azf8K3...",
  "signature": "MEUC...",
  "last_block_hash": "a1b2c3...",
  "timestamp": 1707900000000,
  "pow_difficulty": 0,
  "pow": 42,
  "target": "",
  "topic": "general",
  "title": "Hello World",
  "content": "My first post!",
  "tag": ""
}
```

**Subscriber post example** (no PoW):

```json
{
  "pubkey": "Azf8K3...",
  "signature": "MEUC...",
  "last_block_hash": "",
  "timestamp": 1707900000000,
  "pow_difficulty": 0,
  "target": "",
  "topic": "general",
  "title": "Subscriber post",
  "content": "No PoW needed!",
  "tag": ""
}
```

**Vote example:**

```json
{
  "pubkey": "Azf8K3...",
  "signature": "MEUC...",
  "last_block_hash": "a1b2c3...",
  "timestamp": 1707900000000,
  "pow_difficulty": 0,
  "pow": 17,
  "target": "abcd1234...",
  "direction": 1
}
```

### Response

```json
{
  "tx_hash": "e4f5a6..."
}
```

Or on error (HTTP 400+):

```json
{
  "error": "insufficient pow (precheck)"
}
```

---

## 10. Full Transaction Flow (Step by Step)

Here is the complete flow for a **free user creating a post**:

### Step 1: Fetch Parameters

```
GET /api/get_parameters?address=mirage1abc...
→ { last_block_hash: "aa11bb22...", pow_difficulty: 0, pow_base_bits: 8, pow_factor: 0.25 }
```

### Step 2: Build Base Canonical Bytes

```
bytes = "mirage.core.v1:MsgPost\x00"           // prefix
     || 0x02 || uvarint(33) || <pubkey_33_bytes>    // tag 2: pubkey
     || 0x03 || uvarint(32) || <block_hash_bytes>   // tag 3: block hash
     || 0x04 || uvarint(0)                          // tag 4: difficulty
     || 0x06 || uvarint64(1707900000000)             // tag 6: timestamp
     || 0x64 || uvarint(0) || ""                     // tag 100: target (empty for root post)
     || 0x65 || uvarint(7) || "general"              // tag 101: topic
     || 0x66 || uvarint(11) || "Hello World"         // tag 102: title
     || 0x67 || uvarint(14) || "My first post!"      // tag 103: content
     || 0x68 || uvarint(0) || ""                     // tag 104: tag
```

### Step 3: Mine PoW

```
proof = 0
loop:
    password = base_bytes + ":" + uvarint(proof)
    salt = hex_to_bytes("aa11bb22...")
    digest = argon2id(password, salt, t=1, m=4096, p=1, len=32)
    if int(digest) <= effective_target:
        break
    proof++
```

### Step 4: Build Signed Canonical (insert tag 5)

```
signed_bytes = base_bytes_before_tag6
            || 0x05 || uvarint(proof)        // tag 5: pow proof
            || base_bytes_from_tag6_onward
```

### Step 5: Sign

```
hash = SHA256(signed_bytes)
signature = ecdsa_sign(hash, private_key)   // secp256k1, compact 64-byte, low-S
```

### Step 6: Submit

```
POST /api/core/post
{
  "pubkey": base64(compressed_pubkey),
  "signature": base64(signature_64_bytes),
  "last_block_hash": "aa11bb22...",
  "timestamp": 1707900000000,
  "pow_difficulty": 0,
  "pow": 42,
  "target": "",
  "topic": "general",
  "title": "Hello World",
  "content": "My first post!",
  "tag": ""
}
```

---

## 11. Vote Direction Encoding

The vote `direction` field is an `int32` in protobuf but encoded as `uint32` in the canonical bytes:

| User Intent | JSON `direction` | Canonical uvarint value |
|-------------|------------------|-------------------------|
| Upvote | `1` | `1` |
| Remove vote | `0` | `0` |
| Downvote | `-1` | `4294967295` (0xFFFFFFFF) |

In code:

```
if direction >= 0:
    canonical_value = direction
else:
    canonical_value = direction & 0xFFFFFFFF    // two's complement uint32
```

---

## 12. Timestamp Handling

- Timestamps are in **milliseconds** (Unix epoch).
- The backend validates envelope age — timestamps too far in the past or future are rejected.
- Recommended: use `Date.now() - 15000` (15 seconds in the past) to avoid rejection due to clock skew between client and server.
- The same timestamp must be used in both the canonical bytes (tag 6) and the JSON payload (`timestamp` field).

---

## 13. Reference: uvarint Encoding

Unsigned variable-length integer encoding (same as Protocol Buffers):

```
def uvarint(n):
    n = n & 0xFFFFFFFFFFFFFFFF  // uint64
    out = []
    while True:
        byte = n & 0x7F
        n >>= 7
        if n > 0:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            break
    return bytes(out)
```

Examples:

| Value | Encoded bytes |
|-------|---------------|
| 0 | `0x00` |
| 1 | `0x01` |
| 127 | `0x7F` |
| 128 | `0x80 0x01` |
| 300 | `0xAC 0x02` |
| 1707900000000 | 7 bytes |

For timestamps (large values), you need a 64-bit capable uvarint implementation.

---

## Quick Reference: Tag Byte Values

| Tag Number | Hex Byte | Used For |
|-----------|----------|----------|
| 2 | `0x02` | envelope_pubkey |
| 3 | `0x03` | envelope_block_hash |
| 4 | `0x04` | envelope_difficulty |
| 5 | `0x05` | envelope_pow |
| 6 | `0x06` | envelope_timestamp |
| 100 | `0x64` | First payload field (target/sender/level) |
| 101 | `0x65` | Second payload field (username/topic/user/direction/target) |
| 102 | `0x66` | Third payload field (title/amount) |
| 103 | `0x67` | content |
| 104 | `0x68` | tag (content tag) |
| 105 | `0x69` | override (edit only) |
