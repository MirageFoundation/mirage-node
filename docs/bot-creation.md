# Building a Mirage Bot (Python)

Minimal self-contained example. One file, no project imports.

## Dependencies

```bash
pip install requests cosmpy cryptography argon2-cffi
```

## Quick Start

```python
#!/usr/bin/env python3
"""Mirage bot — minimal self-contained example."""

import base64, hashlib, json, time, math, requests
from argon2.low_level import hash_secret_raw, Type as Argon2Type
from cosmpy.aerial.wallet import LocalWallet
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.backends import default_backend

# ── Config ──────────────────────────────────────────────────────────
SEED = "word1 word2 ... word24"          # BIP39 mnemonic (24 words)
NODE = "https://mirage.talk"             # base node URL (no trailing slash)
# ────────────────────────────────────────────────────────────────────


# ── Wallet ──────────────────────────────────────────────────────────
wallet = LocalWallet.from_mnemonic(SEED, prefix="mirage")
ADDRESS = str(wallet.address()).lower()
PUBKEY  = bytes(wallet.public_key().public_key_bytes)   # 33 bytes, compressed
PRIVKEY = bytes(wallet.signer().private_key_bytes)       # 32 bytes


# ── Helpers ─────────────────────────────────────────────────────────
def b64(b: bytes) -> str:
    return base64.b64encode(b).decode()

def uvarint(n: int) -> bytes:
    n = int(n) & 0xFFFFFFFFFFFFFFFF
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | 0x80 if n else b)
        if not n:
            break
    return bytes(out)

def enc_bytes(tag: int, b: bytes) -> bytes:
    return bytes([tag]) + uvarint(len(b)) + b

def enc_str(tag: int, s: str) -> bytes:
    return enc_bytes(tag, s.encode())

def enc_u64(tag: int, v: int) -> bytes:
    return bytes([tag]) + uvarint(v)


# ── Signing ─────────────────────────────────────────────────────────
def sign(privkey: bytes, message: bytes) -> bytes:
    """ECDSA-secp256k1 compact 64-byte signature (low-S normalized)."""
    pk = ec.derive_private_key(int.from_bytes(privkey, "big"), ec.SECP256K1(), default_backend())
    der = pk.sign(message, ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der)
    N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
    if s > N // 2:
        s = N - s
    return r.to_bytes(32, "big") + s.to_bytes(32, "big")


# ── Proof of Work ───────────────────────────────────────────────────
def _round_half_up(x: float) -> int:
    return int(math.floor(x + 0.5))

def _difficulty_factor(difficulty: int, pow_factor: float) -> int:
    return _round_half_up(1000 * (1 + pow_factor) ** difficulty)

def check_pow_target(digest: bytes, difficulty: int, pow_base_bits: int, pow_factor: float) -> bool:
    if difficulty < 0 or pow_factor <= 0 or pow_factor > 1:
        return False
    base_target = 1 << (256 - pow_base_bits)
    factor = _difficulty_factor(difficulty, pow_factor)
    eff_target = base_target * 1000 // factor
    return int.from_bytes(digest, "big") <= eff_target

def compute_pow(
    base: bytes, difficulty: int, pow_base_bits: int, pow_factor: float, block_hash_hex: str, max_seconds: float = 120
) -> int:
    salt = bytes.fromhex(block_hash_hex)
    start = time.time()
    nonce = 0
    while True:
        if time.time() - start > max_seconds:
            raise TimeoutError(f"PoW not found in {max_seconds}s")
        password = base + b":" + uvarint(nonce)
        digest = hash_secret_raw(password, salt, time_cost=1, memory_cost=4096,
                                 parallelism=1, hash_len=32, type=Argon2Type.ID)
        if check_pow_target(digest, difficulty, pow_base_bits, pow_factor):
            return nonce
        nonce += 1


# ── Canonical Bytes ─────────────────────────────────────────────────
def canon_prefix(msg: str) -> bytes:
    return b"mirage.core.v1:" + msg.encode() + b"\x00"

def envelope(block_hash_bytes: bytes, difficulty: int, ts_ms: int) -> bytes:
    return (enc_bytes(2, PUBKEY)
          + enc_bytes(3, block_hash_bytes)
          + enc_u64(4, difficulty)
          + enc_u64(6, ts_ms))

def insert_pow(base: bytes, pow_val: int) -> bytes:
    """Insert tag5 (pow) between tag4 (difficulty) and tag6 (timestamp)."""
    i = base.index(b"\x00") + 1                   # end of prefix
    for expected_tag in (2, 3):                    # skip tag2 (bytes), tag3 (bytes)
        assert base[i] == expected_tag; i += 1
        length = 0; shift = 0
        while base[i] & 0x80: length |= (base[i] & 0x7F) << shift; shift += 7; i += 1
        length |= (base[i] & 0x7F) << shift; i += 1
        i += length
    assert base[i] == 4; i += 1                   # skip tag4 (varint)
    while base[i] & 0x80: i += 1
    i += 1
    return base[:i] + enc_u64(5, pow_val) + base[i:]


# ── API Helpers ─────────────────────────────────────────────────────
def get_params() -> tuple[str, int, int, float]:
    """Return (last_block_hash, pow_difficulty, pow_base_bits, pow_factor)."""
    r = requests.get(f"{NODE}/api/get_parameters?address={ADDRESS}").json()
    return (
        r["last_block_hash"],
        int(r["pow_difficulty"]),
        int(r["pow_base_bits"]),
        float(r["pow_factor"]),
    )

def get_user_level() -> int:
    r = requests.get(f"{NODE}/api/get_user_status?address={ADDRESS}").json()
    return int(r.get("user_level", 0) or 0)

def submit(
    endpoint: str,
    base: bytes,
    fields: dict,
    block_hash: str,
    difficulty: int,
    pow_base_bits: int,
    pow_factor: float,
    ts_ms: int,
):
    """Compute PoW (if needed), sign, and POST."""
    is_subscriber = get_user_level() >= 1
    if is_subscriber:
        pow_val = 0
        use_diff = 0
    else:
        pow_val = compute_pow(base, difficulty, pow_base_bits, pow_factor, block_hash)
        use_diff = difficulty

    signed_bytes = insert_pow(base, pow_val)
    sig = sign(PRIVKEY, signed_bytes)

    body = {
        "pubkey": b64(PUBKEY),
        "signature": b64(sig),
        "last_block_hash": block_hash,
        "timestamp": ts_ms,
        "pow_difficulty": use_diff,
        "pow": pow_val,
        **fields,
    }
    resp = requests.post(f"{NODE}/api{endpoint}", json=body)
    print(f"POST {endpoint} → {resp.status_code}")
    print(json.dumps(resp.json(), indent=2))
    return resp.json()


# ── Actions ─────────────────────────────────────────────────────────
def make_post(topic: str, title: str, content: str, tag: str = "",
              media: list[str] | None = None):
    block_hash, diff, pow_base_bits, pow_factor = get_params()
    bh = bytes.fromhex(block_hash)
    ts = int(time.time() * 1000)
    base = (canon_prefix("MsgPost")
          + envelope(bh, diff, ts)
          + enc_str(100, "")            # target (empty for root post)
          + enc_str(101, topic)
          + enc_str(102, title)
          + enc_str(103, content)
          + enc_str(104, tag))
    for m in (media or []):
        base += enc_str(105, m)         # media URLs (repeated tag 105)
    fields = {"target": "", "topic": topic, "title": title,
              "content": content, "tag": tag}
    if media:
        fields["media"] = media
    return submit("/core/post", base, fields,
                  block_hash, diff, pow_base_bits, pow_factor, ts)

def make_comment(parent_post_id: str, content: str):
    block_hash, diff, pow_base_bits, pow_factor = get_params()
    bh = bytes.fromhex(block_hash)
    ts = int(time.time() * 1000)
    base = (canon_prefix("MsgPost")
          + envelope(bh, diff, ts)
          + enc_str(100, parent_post_id)  # target = parent
          + enc_str(101, "")              # topic (empty for comments)
          + enc_str(102, "")              # title (empty for comments)
          + enc_str(103, content)
          + enc_str(104, ""))             # tag
    return submit("/core/post", base, {
        "target": parent_post_id, "topic": "", "title": "",
        "content": content, "tag": "",
    }, block_hash, diff, pow_base_bits, pow_factor, ts)

def edit_post(override: str, topic: str, title: str, content: str,
              tag: str = "", media: list[str] | None = None):
    """Edit an existing post. override = the post's tx_hash."""
    block_hash, diff, pow_base_bits, pow_factor = get_params()
    bh = bytes.fromhex(block_hash)
    ts = int(time.time() * 1000)
    # target is empty for root posts, or the parent post_id for comments
    target = ""
    base = (canon_prefix("MsgEdit")
          + envelope(bh, diff, ts)
          + enc_str(100, target)
          + enc_str(101, topic)
          + enc_str(102, title)
          + enc_str(103, content)
          + enc_str(104, tag)
          + enc_str(105, override))       # override = original post tx_hash
    for m in (media or []):
        base += enc_str(106, m)           # media URLs (repeated tag 106)
    fields = {"target": target, "topic": topic, "title": title,
              "content": content, "tag": tag, "override": override}
    if media:
        fields["media"] = media
    return submit("/core/edit", base, fields,
                  block_hash, diff, pow_base_bits, pow_factor, ts)

def delete_post(target_post_id: str):
    block_hash, diff, pow_base_bits, pow_factor = get_params()
    bh = bytes.fromhex(block_hash)
    ts = int(time.time() * 1000)
    base = (canon_prefix("MsgDelete")
          + envelope(bh, diff, ts)
          + enc_str(100, target_post_id))
    return submit("/core/delete_post", base, {
        "target": target_post_id,
    }, block_hash, diff, pow_base_bits, pow_factor, ts)

def vote(target_post_id: str, direction: int):
    """direction: 1=upvote, -1=downvote, 0=remove"""
    block_hash, diff, pow_base_bits, pow_factor = get_params()
    bh = bytes.fromhex(block_hash)
    ts = int(time.time() * 1000)
    dir_val = direction if direction >= 0 else (direction & 0xFFFFFFFF)
    base = (canon_prefix("MsgVote")
          + envelope(bh, diff, ts)
          + enc_str(100, target_post_id)
          + enc_u64(101, dir_val))
    return submit("/core/vote", base, {
        "target": target_post_id, "direction": direction,
    }, block_hash, diff, pow_base_bits, pow_factor, ts)

def set_username(username: str, invite_code: str = "", referrer: str = ""):
    block_hash, diff, pow_base_bits, pow_factor = get_params()
    bh = bytes.fromhex(block_hash)
    ts = int(time.time() * 1000)
    base = (canon_prefix("MsgSetUsername")
          + envelope(bh, diff, ts)
          + enc_str(100, ADDRESS)
          + enc_str(101, username))
    fields = {"username": username}
    if invite_code:
        fields["invite_code"] = invite_code
    if referrer:
        fields["referrer"] = referrer
    return submit("/core/set_username", base, fields,
                  block_hash, diff, pow_base_bits, pow_factor, ts)

def read_posts(topic: str = "", limit: int = 10) -> list:
    params = {"limit": limit}
    if topic:
        params["topic"] = topic
    r = requests.get(f"{NODE}/api/get_posts", params=params)
    return r.json().get("posts", [])


# ── Main ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # Read latest posts
    posts = read_posts(topic="general", limit=5)
    for p in posts:
        print(f"  [{p['post_id'][:8]}] {p.get('title', '(no title)')}")

    # Set username (first-time registration or rename if your tier allows it)
    # set_username("alice", invite_code="ABCD-1234", referrer="mirage1...")

    # Create a post
    make_post("general", "Hello from bot", "This is an automated post.")

    # Create a post with media
    make_post("general", "Photo post", "Check this out!", media=[
        "https://imagedelivery.net/abc123/img-uuid/public"
    ])

    # Comment on the first post
    if posts:
        make_comment(posts[0]["post_id"], "Great post!")

    # Edit a post (you must own it)
    # edit_post("txhash_of_your_post", "general", "Updated title", "Updated content")

    # Delete a post (you must own it)
    # delete_post("txhash_of_your_post")

    # Vote on the first post
    if posts:
        vote(posts[0]["post_id"], direction=1)
```

---

## How It Works

### 1. Wallet

`cosmpy` derives a secp256k1 keypair + `mirage1...` address from a BIP39 mnemonic. The public key is 33 bytes (compressed), private key is 32 bytes.

### 2. Parameters

Before every write, fetch fresh parameters:

```
GET /api/get_parameters?address=<addr>
```

Response:

```json
{
  "last_block_hash": "abc123...",
  "pow_difficulty": 0,
  "pow_base_bits": 10,
  "pow_factor": 0.25,
  "balance": 1000000
}
```

- `last_block_hash` — anchors the request to a recent block (hex, 64 chars). Must match one of the last `block_hash_window` committed block hashes (chain param; default 10).
- `pow_difficulty` — current difficulty step count (0 = base). Adjusts dynamically based on network message volume.
- `pow_base_bits` / `pow_factor` — used to compute the PoW target threshold.
- `balance` — only included if `address` is provided (in umirage; 1 MIRAGE = 1,000,000 umirage).

Cached server-side for 3 seconds.

### 3. Canonical Bytes

Every write request is a protobuf-like canonical byte string that gets PoW'd and signed:

```
b"mirage.core.v1:MsgPost\x00"       ← prefix
  tag2  = pubkey (33 bytes)          ← envelope
  tag3  = last_block_hash (bytes)
  tag4  = difficulty (varint)
  tag6  = timestamp_ms (varint)
  tag100 = target (string)           ← payload
  tag101 = topic (string)
  ...
```

**Two-phase construction:**

1. **Base canonical** (for PoW input) — excludes tag5 (pow) and tag10 (signature)
2. **Signed canonical** — base + tag5 inserted between tag4 and tag6

Authority (tag1) and signature (tag10) are never included in canonical bytes — authority is set by the backend to the validator address, and the signature is sent separately.

### 4. Proof of Work

Free users (level 0) must solve Argon2id PoW. Subscribers (level >= 1) skip PoW entirely (send `pow_difficulty=0`, `pow=0`).

**Algorithm:** Argon2id with `time_cost=1`, `memory_cost=4096` (4 MB), `parallelism=1`, `hash_len=32`.

**How it works:**

```python
password = canonical_base + b":" + uvarint(nonce)
salt = bytes.fromhex(last_block_hash)
digest = argon2id(password, salt, ...)
# Passes if int(digest) <= effective_target
```

**Target calculation:**

- `base_target = 2^(256 - pow_base_bits)`
- `factor = round(1000 * (1 + pow_factor)^difficulty)`
- `effective_target = base_target * 1000 // factor`

Difficulty adjusts dynamically — increases when message volume is high, decreases during calm periods.

### 5. Signature

ECDSA-SHA256 over the final canonical bytes (with PoW inserted). Low-S normalized, 64-byte compact format (r || s, 32 bytes each).

### 6. Submit

POST the JSON envelope plus message-specific fields. Every write request includes:

```json
{
  "pubkey": "<base64, 33 bytes>",
  "signature": "<base64, 64 bytes>",
  "last_block_hash": "<hex, 64 chars>",
  "timestamp": 1234567890000,
  "pow_difficulty": 0,
  "pow": 0,
  ...message-specific fields
}
```

**Success response:**

```json
{
  "tx_hash": "abc123...",
  "code": 0,
  "height": 12345,
  "raw_log": ""
}
```

`code=0` means success. Non-zero codes indicate chain-level rejection.

---

## Posting: Complete Reference

### Create a Root Post

**Endpoint:** `POST /api/core/post`

**Fields:**

| Field | Type | Required | Description |
|---|---|---|---|
| `target` | string | yes | Empty string `""` for root posts |
| `topic` | string | yes | Lowercase alphanumeric (`[a-z0-9]+`), 3-50 chars |
| `title` | string | yes | Post title (length limit based on tier) |
| `content` | string | yes | Post body (length limit based on tier) |
| `tag` | string | no | Content warning: `""`, `"sensitive"`, `"porn"`, `"gore"`, `"violence"`, `"death"` |
| `media` | string[] | no | Up to 10 HTTPS URLs, each max 2048 chars |

**Canonical bytes (MsgPost):**

| Tag | Field | Encoding |
|---|---|---|
| 100 | target | string (empty `""`) |
| 101 | topic | string |
| 102 | title | string |
| 103 | content | string |
| 104 | tag | string |
| 105 | media[0] | string (repeated for each URL) |

### Create a Comment

Same endpoint (`POST /api/core/post`) and same canonical prefix (`MsgPost`), but:

- `target` = parent post's `tx_hash` (64-char hex)
- `topic` = empty string
- `title` = empty string
- `content` = comment body (required, non-empty)

### Edit a Post

**Endpoint:** `POST /api/core/edit`

**Additional field:**

| Field | Type | Required | Description |
|---|---|---|---|
| `override` | string | yes | The `tx_hash` of the post being edited (64-char hex). You must own it. |

All other fields (`target`, `topic`, `title`, `content`, `tag`, `media`) work the same as create. Send the full updated values — this is a full replacement, not a partial update.

**Canonical bytes (MsgEdit) — note different tag numbers for override/media:**

| Tag | Field | Encoding |
|---|---|---|
| 100 | target | string |
| 101 | topic | string |
| 102 | title | string |
| 103 | content | string |
| 104 | tag | string |
| 105 | override | string |
| 106 | media[0] | string (repeated for each URL) |

### Delete a Post

**Endpoint:** `POST /api/core/delete_post`

| Field | Type | Required | Description |
|---|---|---|---|
| `target` | string | yes | The `tx_hash` of the post to delete. You must own it. |

**Canonical bytes (MsgDelete):**

| Tag | Field | Encoding |
|---|---|---|
| 100 | target | string |

### Vote

**Endpoint:** `POST /api/core/vote`

| Field | Type | Required | Description |
|---|---|---|---|
| `target` | string | yes | The `tx_hash` of the post to vote on |
| `direction` | int | yes | `1` = upvote, `-1` = downvote, `0` = remove vote |

**Canonical bytes (MsgVote):**

| Tag | Field | Encoding |
|---|---|---|
| 100 | target | string |
| 101 | direction | uint64 (note: `-1` is encoded as `4294967295`) |

### Set Username

**Endpoint:** `POST /api/core/set_username`

| Field | Type | Required | Description |
|---|---|---|---|
| `username` | string | yes | `[A-Za-z0-9-]+`, length from `get_chain_config` |
| `invite_code` | string | no | Required for new users if `registration_invite_code_required=true` (`XXXX-XXXX`) |
| `referrer` | string | no | Optional `mirage1...` address for referral tracking |

The backend derives `target` from your pubkey; you cannot set a username for another address via this endpoint.

**Canonical bytes (MsgSetUsername):**

| Tag | Field | Encoding |
|---|---|---|
| 100 | target | string (own address derived from pubkey) |
| 101 | username | string |

**Notes:**

- If your tier disallows name changes, the chain forces an `Anon-` prefix.
- Usernames are case-insensitive; uniqueness is enforced on lowercase.
- `invite_code` and `referrer` are NOT part of canonical bytes (do not include them in the signature).

---

## Media: Uploading Images and Videos

Posts accept up to 10 media URLs in the `media` field. You can use any HTTPS URL, or upload files directly to the node's Cloudflare-backed storage.

### Upload Flow

**Step 1:** Get an upload URL.

```
POST /api/get_upload_url
{"type": "image"}   // or "video"
```

**Image response:**

```json
{
  "uploadURL": "https://upload.imagedelivery.net/...",
  "id": "image-uuid",
  "accountHash": "abc123"
}
```

**Video response:**

```json
{
  "uploadURL": "https://upload.videodelivery.net/...",
  "provider": "stream",
  "streamCustomer": "customer-code",
  "uid": "video-uuid"
}
```

**Step 2:** Upload the file directly to the returned `uploadURL`.

- **Images:** Multipart form upload (`file` field).
- **Videos:** Multipart or TUS upload. Max duration: 60 seconds.

**Step 3:** Use the final URL in the `media` array when posting.

- **Image URL format:** `https://imagedelivery.net/{accountHash}/{id}/public`
- **Video URL format:** `https://customer-{streamCustomer}.cloudflarestream.com/{uid}/manifest/video.m3u8`

### Media Validation Rules

| Rule | Limit |
|---|---|
| Max items per post | 10 |
| Max URL length | 2048 characters |
| URL scheme | Must start with `https://` |
| Empty array | Valid (no media) |

---

## Reading Data

### Get Posts

```
GET /api/get_posts?topic=general&limit=25&page=1&by=magic
```

| Param | Default | Description |
|---|---|---|
| `topic` | — | Filter by topic. `"all"` for global feed. |
| `limit` | 25 | Posts per page (max 100) |
| `page` | 1 | Page number |
| `by` | `"magic"` | Sort: `"magic"` (algorithmic) or `"newest"` (chronological) |
| `address` | — | Viewer address (filters blocked content) |
| `allowed_tags` | `"sensitive"` | Comma-separated tags to include (default hides porn/violence/gore/death) |
| `feed` | — | `"home"` or `"following"` for personalized feeds |

**Response:**

```json
{
  "posts": [
    {
      "post_id": "64char_hex_txhash",
      "author": "mirage1...",
      "username": "alice",
      "author_level": 1,
      "timestamp": 1700000000,
      "topic": "general",
      "title": "Post title",
      "content": "Post body",
      "tag": "",
      "edited": false,
      "media": ["https://..."],
      "thumbnail": "https://...",
      "points": 42.0,
      "comments": 5,
      "unique_commenters": 3,
      "user_vote": 0
    }
  ],
  "total": 100,
  "page": 1,
  "limit": 25,
  "has_more": true
}
```

### Get User Status

```
GET /api/get_user_status?address=mirage1...
```

```json
{
  "username": "alice",
  "balance": 1000000,
  "user_level": 0,
  "subscription_expiry": 0,
  "auto_renew": false,
  "reserve_funds": 0,
  "profile_registered_at": 1700000000,
  "recent_votes": [
    {"target": "txhash", "direction": 1, "timestamp": 1700000000}
  ]
}
```

### Get Chain Config

```
GET /api/get_chain_config
```

Returns governance parameters including tier limits:

```json
{
  "max_username_size": 20,
  "min_username_size": 3,
  "max_topic_size": 50,
  "min_topic_size": 3,
  "subscription_period": 2592000,
  "mint_interval": 3600,
  "block_time": 6,
  "tiers": [
    {
      "period_fee": 0,
      "max_enabled_agents": 50,
      "max_followed_users": 50,
      "max_followed_topics": 50,
      "max_blocked_users": 50,
      "max_blocked_posts": 50,
      "max_blocked_topics": 10,
      "max_title_length": 200,
      "max_content_length": 5000,
      "editing_time_mins": 30,
      "vote_weight": 1.0,
      "can_be_agent": false,
      "can_remove_anon": false,
      "can_have_biography": false,
      "can_have_avatar": false,
      "can_have_banner": false,
      "can_have_flair": false
    }
  ]
}
```

Values vary by chain; always read the live response for current limits.

Tiers are indexed by `user_level` (0 = free, 1 = subscriber, etc.). Title/content length limits are enforced per tier.

### Get Node Config

```
GET /api/get_node_config
```

```json
{
  "validator_account_address": "mirage1...",
  "validator_operator_address": "miragevaloper1...",
  "validator_consensus_address": "miragevalcons1...",
  "validator_moniker": "my-node",
  "giphy_api_key": "...",
  "registration_enabled": true,
  "registration_invite_code_required": false,
  "quests_enabled": true,
  "quest_payouts_enabled": true
}
```

Cached 24 hours. Not needed for posting.

---

## All Message Types

| Action | Prefix | Endpoint | Payload tags |
|---|---|---|---|
| Post | `MsgPost` | `/core/post` | 100=target, 101=topic, 102=title, 103=content, 104=tag, 105=media (repeated) |
| Comment | `MsgPost` | `/core/post` | Same as Post (target=parent post_id, topic/title empty) |
| Edit | `MsgEdit` | `/core/edit` | 100=target, 101=topic, 102=title, 103=content, 104=tag, 105=override, 106=media (repeated) |
| Delete | `MsgDelete` | `/core/delete_post` | 100=target |
| Vote | `MsgVote` | `/core/vote` | 100=target, 101=direction |
| Set Username | `MsgSetUsername` | `/core/set_username` | 100=target (own addr), 101=username |
| Follow User | `MsgFollowUser` | `/core/follow_user` | 100=target (own addr), 101=user |
| Unfollow User | `MsgUnfollowUser` | `/core/unfollow_user` | 100=target (own addr), 101=user |
| Follow Topic | `MsgFollowTopic` | `/core/follow_topic` | 100=target (own addr), 101=topic |
| Unfollow Topic | `MsgUnfollowTopic` | `/core/unfollow_topic` | 100=target (own addr), 101=topic |
| Enable Agent | `MsgEnableAgent` | `/core/enable_agent` | 100=target (own addr), 101=agent |
| Disable Agent | `MsgDisableAgent` | `/core/disable_agent` | 100=target (own addr), 101=agent |
| Block Post | `MsgBlockPost` | `/core/block_post` | 100=target (post_id) |
| Unblock Post | `MsgUnblockPost` | `/core/unblock_post` | 100=target (post_id) |
| Block User | `MsgBlockUser` | `/core/block_user` | 100=target (address) |
| Unblock User | `MsgUnblockUser` | `/core/unblock_user` | 100=target (address) |
| Block Topic | `MsgBlockTopic` | `/core/block_topic` | 100=target (empty), 101=topic |
| Unblock Topic | `MsgUnblockTopic` | `/core/unblock_topic` | 100=target (empty), 101=topic |
| Report | `MsgReport` | `/core/report` | 100=target (post_id), 101=reason |
| Send Tokens | `MsgSendTokens` | `/core/send_tokens` | 100=sender (own addr), 101=target, 102=amount (varint) |
| Upgrade Level | `MsgUpgradeLevel` | `/core/upgrade_level` | 100=level (1/2/3) |
| Set Auto Renewal | `MsgSetAutoRenewal` | `/core/set_auto_renewal` | 100=auto_renew (1=on, 0=off) |
| Delete User | `MsgDeleteUser` | `/core/delete_user` | 100=target (own addr) |
| Award | `MsgAward` | `/core/award` | 100=target (post_id), 101=award_type |
| Bridge Burn | `MsgBridgeBurn` | `/bridge/burn` | 100=destination_chain, 101=destination_address, 102=amount |

---

## Reference Notes

- **Tag encoding**: `bytes`/`string` fields = `[tag_byte, uvarint(length), data]`. Integer fields = `[tag_byte, uvarint(value)]`.
- **Direction** for votes: Go encodes `int32(-1)` as `uint32(4294967295)` in the canonical bytes.
- **Amounts** are in `umirage` (1 MIRAGE = 1,000,000 umirage).
- **Timestamps** are milliseconds since epoch.
- **Post IDs** are 64-char lowercase hex (the transaction hash of the post).
- **Topic format**: Posts/follows use lowercase alphanumeric (`[a-z0-9]+`) with `min_topic_size`/`max_topic_size`. Blocked-topic patterns may include `*` (no `**`), length checks apply to the non-`*` characters.
- **Timestamp freshness**: Rejected if older than `max_envelope_age` seconds (default 60). Small future skew is allowed (capped at 30s, derived from `max_envelope_age/2`).
- **Block hash window**: Must match one of the last `block_hash_window` committed block hashes (default 10).
- **Registration gating**: Check `get_node_config`. If `registration_enabled=false`, new usernames are rejected. If `registration_invite_code_required=true`, include `invite_code` (`XXXX-XXXX`) for new users. `invite_code` and `referrer` are not part of canonical bytes.
- **Unsafe characters**: Control characters are rejected in usernames, topics, titles, content, tags, and media URLs (Unicode is fine).
- **Subscribers** (level >= 1) must send `pow_difficulty=0` and `pow=0`. The backend rejects if a subscriber sends PoW.
