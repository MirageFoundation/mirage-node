# Awards System — Technical Specification

Complete implementation guide for the Mirage awards feature. Covers chain parameters, API endpoints, transaction signing, data models, and display logic.

---

## Overview

Awards let users spend MIRAGE to recognize posts and comments. The token cost is **burned** (permanently destroyed), not transferred. Each account can give **one award per post/comment** and **cannot award their own content**. Admins (level >= 100) give awards for free.

---

## 1. Award Types & Costs

Award types are chain-governed parameters. Current defaults:

| Name               | Cost (MIRAGE) | Cost (umirage)    | Icon | Label                    |
|--------------------|---------------|--------------------|------|--------------------------|
| `quality_post`     | 10,000        | 10,000,000,000     | 🏆   | Quality Post Award       |
| `original_content` | 5,000         | 5,000,000,000      | 💡   | Original Content Award   |
| `based`            | 5,000         | 5,000,000,000      | 💪   | Based AF Award           |
| `receipts`         | 5,000         | 5,000,000,000      | 🏷️   | Receipts Award           |

> 1 MIRAGE = 1,000,000 umirage. All costs in the API are in **umirage**.

These can change via governance proposals. Always fetch from the config endpoint; never hardcode.

---

## 2. Fetching Award Configuration

### `GET /api/get_chain_config`

No parameters. Cached 24 hours server-side.

**Response** (relevant fields):

```json
{
  "award_configs": [
    { "name": "quality_post", "cost": 10000000000 },
    { "name": "original_content", "cost": 5000000000 },
    { "name": "based", "cost": 5000000000 },
    { "name": "receipts", "cost": 5000000000 }
  ]
}
```

Each entry:
- `name` (string): Unique award type identifier. Use this when submitting an award.
- `cost` (integer): Cost in umirage. `0` for free awards (shouldn't happen for normal users).

Cache this on the client. Listen for updates infrequently (governance changes are rare).

---

## 3. Awards in Post/Comment Responses

Awards are included in post objects returned by these endpoints:

- `GET /api/get_posts` (feeds: home, following, topic, newest)
- `GET /api/get_comments` (root post + full comment tree)

**Not included in**: `GET /api/get_user_posts`

### Award field on a post object

```json
{
  "post_id": "a1b2c3...64hex",
  "title": "...",
  "content": "...",
  "awards": [
    { "type": "quality_post", "count": 3 },
    { "type": "based", "count": 1 }
  ]
}
```

- `awards` (array): Aggregated awards on this post/comment. Empty array `[]` if none.
  - `type` (string): Matches a `name` from `award_configs`.
  - `count` (integer): Number of distinct users who gave this award type.

### Display logic

For each award in the array:
1. Look up the icon/label from your local award type map.
2. If `count > 1`, display as `{count}x{icon}` (e.g. "3x🏆").
3. If `count == 1`, display just the icon.
4. Show the full label (e.g. "Quality Post Award") in a tooltip on hover/long-press.
5. Awards display inline, side by side, in the post metadata area.

---

## 4. Giving an Award

### Step 1: Fetch signing parameters

`GET /api/get_parameters`

Optional query param: `address` (user's address, to include balance in response).

**Response:**

```json
{
  "last_block_hash": "abc123...hex",
  "pow_difficulty": 5,
  "pow_base_bits": 0,
  "pow_factor": 0,
  "balance": 50000000000
}
```

You need `last_block_hash` for replay protection. For awards:
- If user level >= 1: set `pow_difficulty = 0` and `last_block_hash = ""` (PoW is skipped).
- Awards never require PoW regardless. The backend rejects `pow_difficulty != 0`.

### Step 2: Build the transaction object

```json
{
  "action": "award",
  "target": "<64-char lowercase hex txhash of the post/comment>",
  "award_type": "<award name from award_configs>",
  "last_block_hash": "<from get_parameters, or empty string if level >= 1>",
  "pow_difficulty": 0,
  "pow_base_bits": 0,
  "pow_factor": 0,
  "timestamp": "<unix milliseconds, offset -15 seconds from now>"
}
```

- `target`: The `post_id` (txhash) of the post or comment being awarded. Must be exactly 64 lowercase hex characters.
- `award_type`: Must exactly match a `name` from `award_configs`.
- `timestamp`: `Math.max(0, Date.now() - 15000)` — 15 seconds in the past to account for clock drift.

### Step 3: Sign the transaction

Build canonical bytes, hash with SHA-256, sign with secp256k1.

#### Canonical byte format

```
PREFIX || TAG2(pubkey) || TAG3(block_hash) || TAG4(difficulty) || TAG5(pow) || TAG6(timestamp) || TAG100(target) || TAG101(award_type)
```

**PREFIX**: UTF-8 bytes of `"mirage.core.v1:MsgAward"` followed by a null byte `\x00`.

**Tag encoding**: Each field is `[tag_byte] [encoded_value]`:
- Tag byte is a single byte: `2`, `3`, `4`, `5`, `6`, `100`, `101`
  - Note: tag `100` = byte `0x64`, tag `101` = byte `0x65`
- Bytes fields (tags 2, 3): `[tag] [uvarint(length)] [raw_bytes]`
- Integer fields (tags 4, 5, 6): `[tag] [uvarint(value)]`
  - Tag 6 (timestamp) uses 64-bit uvarint encoding for large values
- String fields (tags 100, 101): `[tag] [uvarint(byte_length)] [utf8_bytes]`

**uvarint encoding** (unsigned variable-length integer):
```
while value >= 0x80:
    emit (value & 0x7F) | 0x80
    value >>= 7
emit value
```

**Field values for awards:**
| Tag | Field              | Value                                                    |
|-----|--------------------|----------------------------------------------------------|
| 2   | `envelope_pubkey`  | 33-byte compressed secp256k1 public key                  |
| 3   | `envelope_block_hash` | hex-decoded `last_block_hash` (or empty bytes if "")  |
| 4   | `envelope_difficulty` | `0` (always)                                          |
| 5   | `envelope_pow`     | `0` (always)                                             |
| 6   | `envelope_timestamp` | Unix timestamp in milliseconds                         |
| 100 | `target`           | 64-char lowercase hex post/comment txhash                |
| 101 | `award_type`       | Award type name string (e.g. `"quality_post"`)           |

#### Signing

1. Build canonical bytes as described above.
2. SHA-256 hash the canonical bytes.
3. Sign the hash with the user's secp256k1 private key (compact signature format).
4. The signature must be exactly 64 bytes (if 65 bytes, truncate to first 64).
5. Base64-encode the signature and the public key for the relay payload.

### Step 4: Submit to relay endpoint

`POST /api/core/award`

**Request body (JSON):**

```json
{
  "pubkey": "<base64 33-byte compressed secp256k1 public key>",
  "signature": "<base64 64-byte secp256k1 signature>",
  "timestamp": 1700000000000,
  "last_block_hash": "<hex string or empty>",
  "pow_difficulty": 0,
  "pow": 0,
  "target": "<64-char lowercase hex txhash>",
  "award_type": "<award type name>"
}
```

All fields are required.

### Step 5: Handle the response

**Success (200):**

```json
{
  "tx_hash": "abc123...hex",
  "code": 0,
  "height": 12345,
  "raw_log": "..."
}
```

`code == 0` means the chain accepted the transaction.

**Errors:**

| HTTP | `error` string                       | Meaning                                  |
|------|--------------------------------------|------------------------------------------|
| 400  | `"timestamp required"`               | Missing timestamp field                  |
| 400  | `"invalid timestamp"`                | Timestamp is not a valid integer         |
| 400  | `"pow not allowed for award"`        | `pow_difficulty` or `pow` is non-zero    |
| 400  | `"missing required fields"`          | Missing pubkey, signature, target, or award_type |
| 400  | `"invalid target"`                   | Target is not 64 lowercase hex chars     |
| 400  | `"invalid relay fields"`             | Pubkey not 33 bytes or signature not 64 bytes |
| 400  | `"invalid pubkey"`                   | Cannot derive address from pubkey        |
| 400  | `"unknown award_type: {type}"`       | Award type not in chain params           |
| 400  | `"cannot award your own post"`       | User owns the target post/comment        |
| 400  | `"invalid signature"`                | Signature verification failed            |
| 404  | `"target not found"`                 | Post/comment txhash doesn't exist        |
| 409  | `"already awarded this post"`        | User already gave an award to this target|
| 503  | `"node_catching_up"`                 | Node is syncing, try later               |
| 503  | `"unable to verify award eligibility"` | Database error during duplicate check  |

---

## 5. Eligibility Rules

1. **One award per user per target**: A user can only give one award to a given post or comment. The award type doesn't matter for uniqueness — it's one award total, not one per type.
2. **No self-awards**: Cannot award your own post or comment.
3. **No PoW**: `pow_difficulty` and `pow` must both be `0`.
4. **Valid award type**: Must exist in the current `award_configs` chain params.
5. **Target must exist**: The txhash must reference an existing, non-deleted post or comment.
6. **Admin bypass (level >= 100)**: Award is free. The chain sets `burned_amount = 0` instead of deducting tokens.
7. **Sufficient balance**: Non-admin users must have enough umirage to cover the award cost. The burn happens on-chain; the backend doesn't check balance — the chain will reject with an insufficient funds error.

---

## 6. Optimistic Updates

For a responsive UI, apply these updates immediately after the user confirms an award (before the server responds):

### Balance

Deduct the award cost from the displayed balance:

```
displayedBalance -= costUmirage
```

Set a **balance hold** for 15 seconds to prevent a subsequent balance refresh from overwriting the optimistic value with a stale server-side balance. After 15 seconds, allow normal balance refreshes.

On error: add the cost back and refresh balance from server.

### Award badge

Add or increment the award on the post object:

```
if post.awards contains this award_type:
    increment count by 1
else:
    append { type: award_type, count: 1 }
```

On error: revert to the previous awards array.

### Success/error messages

- On success: show `"{Award Label} given!"` for 5 seconds.
- On error: show a user-friendly message for 5 seconds.

Friendly error mapping:
- Contains `"already awarded"` → `"You already gave this post an award."`
- Contains `"insufficient"` or `"not enough"` → `"Not enough MIRAGE to give this award."`
- Contains `"own post"` or `"self-award"` → `"You can't award your own post."`
- Anything else → `"Something went wrong. Please try again."`

---

## 7. Award Notifications (Inbox)

### `GET /api/get_inbox`

**Query params:**
- `address` (string, required): User's address
- `page` (integer, default: 1)
- `limit` (integer, default: 25, max: 100)

**Response:**

```json
{
  "replies": [
    {
      "reply_id": "<txhash of the awarded post>",
      "reply_owner": "<address of the award giver>",
      "reply_username": "<username of the award giver>",
      "reply_author_level": 5,
      "reply_author_is_new": false,
      "reply_content": "<content of the awarded post>",
      "reply_timestamp": 1700000000,
      "parent_id": "<txhash of the awarded post>",
      "parent_content": "<title of the awarded post>",
      "parent_owner": "<address of the post owner (you)>",
      "root_post_id": "<root post txhash for navigation>",
      "award_type": "quality_post",
      "type": "award"
    }
  ],
  "total": 42,
  "page": 1,
  "limit": 25,
  "has_more": true
}
```

The `replies` array is a unified feed of replies, mentions, and awards sorted by timestamp descending. Use the `type` field to distinguish:

| `type`      | Description                                |
|-------------|--------------------------------------------|
| `"reply"`   | Someone replied to your post/comment       |
| `"mention"` | Someone @mentioned you                     |
| `"award"`   | Someone gave your post/comment an award    |

For award items:
- `type` is `"award"`
- `award_type` contains the award name (e.g. `"quality_post"`)
- `reply_owner` / `reply_username` is the person who gave the award
- `parent_content` is the title of the post that was awarded
- `root_post_id` is the root post txhash (for navigating to the thread)

For non-award items, `award_type` is an empty string `""`.

### Display format for award notifications

```
{username} gave your {post/comment} a '{Award Label}' award
```

Use `parent_content` to show a preview of what was awarded. Truncated to 200 chars server-side.

### Inbox badge count

The unread inbox count (returned by `GET /api/get_user_status`) includes awards. The count is: all replies + mentions + awards received since `inbox_last_viewed_at`, excluding self-actions and blocked users.

### Marking inbox as viewed

`POST /api/mark_inbox_viewed`

**Body:** `{ "address": "<user address>" }`

Sets `inbox_last_viewed_at` to current time, clearing the unread badge.

---

## 8. Magic Feed Scoring

Awards contribute to the Magic (algorithmic) feed ranking:

```
score = (S + V + U + P + A) × R
```

Where `A = sqrt(unique_award_givers)` for the post.

- `unique_award_givers`: Count of distinct addresses that gave any award to this post (regardless of award type).
- The sqrt dampens the effect so the first few awards matter most.

The debug object on posts in magic feeds includes `"A": <raw_unique_awarders_count>` (the count before sqrt is applied).

---

## 9. Database Schema (Indexer)

```sql
CREATE TABLE IF NOT EXISTS awards (
    id SERIAL PRIMARY KEY,
    owner TEXT NOT NULL,
    target TEXT NOT NULL,
    award_type TEXT NOT NULL,
    burned_amount BIGINT NOT NULL DEFAULT 0,
    created_at BIGINT NOT NULL
);

CREATE UNIQUE INDEX uniq_awards_owner_target ON awards (LOWER(owner), LOWER(target));
CREATE INDEX idx_awards_target_lower ON awards (LOWER(target));
CREATE INDEX idx_awards_created_at ON awards (created_at DESC);
```

- `owner`: Address of the user who gave the award.
- `target`: txhash (post_id) of the post/comment that was awarded.
- `award_type`: Name of the award type (e.g. `"quality_post"`).
- `burned_amount`: umirage burned. `0` for admin awards.
- `created_at`: Unix timestamp (seconds) when the award was indexed.

The unique index on `(LOWER(owner), LOWER(target))` enforces one award per user per post at the database level.

---

## 10. Chain Message (Protobuf)

For reference, here is the full `MsgAward` protobuf structure. You don't construct this directly — the relay backend does — but it helps understand what's happening on-chain.

```protobuf
message MsgAward {
  string authority = 1;           // Validator/node address (set by backend)
  bytes envelope_pubkey = 2;      // 33-byte secp256k1 compressed public key
  bytes envelope_block_hash = 3;  // Last block hash for replay protection
  uint64 envelope_difficulty = 4; // Always 0 for awards
  uint64 envelope_pow = 5;        // Always 0 for awards
  uint64 envelope_timestamp = 6;  // Unix timestamp (milliseconds)
  bytes envelope_signature = 10;  // 64-byte secp256k1 signature
  string target = 100;            // Post/comment txhash (64 hex chars)
  string award_type = 101;        // Award type name
}
```

Type URL: `/mirage.core.v1.MsgAward`

### Chain-side validation

1. Derives user address from `envelope_pubkey`.
2. Validates `target` is non-empty and exactly 64 hex characters.
3. Validates `award_type` exists in chain params.
4. If user level >= 100 (admin): burn amount = 0. Otherwise: burn amount = award config cost.
5. If burn amount > 0: transfers tokens from user to module account, then burns from module account.
6. Deducts relay gas fee based on user level.

---

## 11. Sequence Diagram

```
Mobile App                    Backend (/api)                  Chain
    |                              |                            |
    |-- GET /get_chain_config ---->|                            |
    |<-- { award_configs: [...] } -|                            |
    |                              |                            |
    |-- GET /get_parameters ------>|                            |
    |<-- { last_block_hash, ... } -|                            |
    |                              |                            |
    |  [User taps Give Award]      |                            |
    |  [User picks award type]     |                            |
    |  [Build canonical bytes]     |                            |
    |  [SHA-256 + secp256k1 sign]  |                            |
    |                              |                            |
    |-- POST /core/award -------->|                            |
    |   { pubkey, signature,       |                            |
    |     timestamp, target,       |                            |
    |     award_type, ... }        |                            |
    |                              |-- Verify signature         |
    |                              |-- Check eligibility        |
    |                              |-- Build MsgAward protobuf  |
    |                              |-- Broadcast tx ----------->|
    |                              |                            |-- Verify envelope
    |                              |                            |-- Burn tokens
    |                              |                            |-- Store state
    |                              |<-- tx_hash, code, height --|
    |<-- { tx_hash, code: 0 } ----|                            |
    |                              |                            |
    |  [Apply optimistic updates]  |                            |
```

---

## 12. Edge Cases & Notes

- **Comments are targets too**: Awards can be given to any post or comment. A comment's `post_id` (txhash) is a valid `target`.
- **Award type is locked**: Once given, the award type cannot be changed. But since only one award per user per target is allowed, this is a non-issue.
- **Deleted posts**: Awards on deleted posts are still stored but won't appear in feeds (deleted posts are filtered out). Award notifications for deleted posts are also filtered.
- **Case insensitivity**: `target`, `owner`, and `award_type` are compared case-insensitively on the backend. Always lowercase `target` before sending. `award_type` should match exactly as returned by `award_configs`.
- **Timestamp**: The 15-second offset (`Date.now() - 15000`) accounts for clock drift between client and validator. The chain enforces a max envelope age (default 60 seconds) — if the timestamp is too old, the chain rejects the message.
- **Balance hold window**: 15 seconds. During this window, do not overwrite the optimistic balance with a server-fetched value unless the server balance is lower than the held minimum.
- **No undo**: Awards cannot be revoked or undone once confirmed on-chain.
