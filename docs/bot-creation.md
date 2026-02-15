# Building a Mirage Bot (Python)

Minimal self-contained example. One file, no project imports.

## Dependencies

```bash
pip install requests cosmpy cryptography argon2-cffi
```

## Full Example

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
SEED = "word1 word2 word3 word4 word5 word6 word7 word8 word9 word10 word11 word12 word13 word14 word15 word16 word17 word18 word19 word20 word21 word22 word23 word24"
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
# difficulty is a step count (0 = base). Effective factor = 1000 * (1 + step)^difficulty.
# pow_base_bits defines the base target: base_target = 2^(256 - pow_base_bits).
# A hash passes if int(hash) <= base_target * 1000 // factor.

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
#
# Every write request is a protobuf-like canonical byte string:
#   prefix + envelope fields + payload fields
#
# Prefix:    b"mirage.core.v1:<MsgName>\x00"
# Envelope:  tag2=pubkey, tag3=block_hash, tag4=difficulty, tag6=timestamp
# Payload:   tags 100+ (message-specific)
#
# The PoW nonce (tag5) is inserted between tag4 and tag6 AFTER mining,
# producing the final "signed bytes" that get ECDSA-signed.

def canon_prefix(msg: str) -> bytes:
    return b"mirage.core.v1:" + msg.encode() + b"\x00"

def envelope(block_hash_bytes: bytes, difficulty: int, ts_ms: int) -> bytes:
    return (enc_bytes(2, PUBKEY)
          + enc_bytes(3, block_hash_bytes)
          + enc_u64(4, difficulty)
          + enc_u64(6, ts_ms))

def insert_pow(base: bytes, pow_val: int) -> bytes:
    """Insert tag5 (pow) between tag4 (difficulty) and tag6 (timestamp)."""
    # Find the \x06 byte that starts the timestamp field
    # Walk: prefix...\x00, tag2+data, tag3+data, tag4+data, then tag6
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

    # Create a post
    make_post("general", "Hello from bot", "This is an automated post.")

    # Vote on the first post (if any)
    if posts:
        vote(posts[0]["post_id"], direction=1)
```

## How It Works

1. **Wallet** — `cosmpy` derives a secp256k1 keypair + `mirage1...` address from a BIP39 mnemonic.

2. **Parameters** — `GET /api/get_parameters?address=<addr>` returns `last_block_hash`, `pow_difficulty` (step count), `pow_factor`, `pow_base_bits`, and optionally `balance`. These anchor every request to a recent block. A separate `GET /api/get_node_config` provides static node info (validator addresses, feature flags).

3. **Canonical bytes** — Each message type has a deterministic byte encoding:

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

4. **Proof of Work** — Free users must solve Argon2id PoW using a target-based system. The hash (as a 256-bit integer) must be <= `base_target * 1000 / factor`, where `factor = 1000 * (1 + pow_factor)^difficulty`. The nonce is inserted as `tag5` between difficulty and timestamp. Subscribers (level >= 1) skip PoW.

5. **Signature** — ECDSA-SHA256 over the final canonical bytes (with PoW inserted). Low-S normalized, 64-byte compact format.

6. **Submit** — POST the JSON envelope (`pubkey`, `signature`, `last_block_hash`, `timestamp`, `pow_difficulty`, `pow`) plus message-specific fields.

## Message Types Quick Reference

| Action | Prefix | Endpoint | Payload tags |
|---|---|---|---|
| Post | `MsgPost` | `/core/post` | 100=target, 101=topic, 102=title, 103=content, 104=tag, 105=media (repeated) |
| Vote | `MsgVote` | `/core/vote` | 100=target, 101=direction |
| Comment | `MsgPost` | `/core/post` | Same as Post (target=parent post_id, topic/title empty) |
| Edit | `MsgEdit` | `/core/edit` | 100=target, 101=topic, 102=title, 103=content, 104=tag, 105=override |
| Delete | `MsgDelete` | `/core/delete_post` | 100=target |
| Set Username | `MsgSetUsername` | `/core/set_username` | 100=target (own addr), 101=username |
| Follow User | `MsgFollowUser` | `/core/follow_user` | 100=target (own addr), 101=user |
| Unfollow User | `MsgUnfollowUser` | `/core/unfollow_user` | 100=target (own addr), 101=user |
| Follow Topic | `MsgFollowTopic` | `/core/follow_topic` | 100=target (own addr), 101=topic |
| Unfollow Topic | `MsgUnfollowTopic` | `/core/unfollow_topic` | 100=target (own addr), 101=topic |
| Follow Moderator | `MsgFollowModerator` | `/core/follow_moderator` | 100=target (own addr), 101=moderator |
| Unfollow Moderator | `MsgUnfollowModerator` | `/core/unfollow_moderator` | 100=target (own addr), 101=moderator |
| Block Post | `MsgBlockPost` | `/core/block_post` | 100=target (post_id) |
| Unblock Post | `MsgUnblockPost` | `/core/unblock_post` | 100=target (post_id) |
| Block User | `MsgBlockUser` | `/core/block_user` | 100=target (address) |
| Unblock User | `MsgUnblockUser` | `/core/unblock_user` | 100=target (address) |
| Report | `MsgReport` | `/core/report` | 100=target (post_id), 101=reason |
| Send Tokens | `MsgSendTokens` | `/core/send_tokens` | 100=sender (own addr), 101=target, 102=amount (varint) |
| Upgrade Level | `MsgUpgradeLevel` | `/core/upgrade_level` | 100=level (1/2/3) |
| Set Auto Renewal | `MsgSetAutoRenewal` | `/core/set_auto_renewal` | 100=auto_renew (1=on, 0=off) |
| Bridge Burn | `MsgBridgeBurn` | `/core/bridge_burn` | 100=destination_chain, 101=destination_address, 102=amount |

## Notes

- **Tag encoding**: `bytes`/`string` fields = `[tag_byte, uvarint(length), data]`. Integer fields = `[tag_byte, uvarint(value)]`.
- **Direction** for votes: Go encodes `int32(-1)` as `uint32(4294967295)` in the canonical bytes.
- **Amounts** are in `umirage` (1 MIRAGE = 1,000,000 umirage).
- **Timestamps** are milliseconds since epoch.
- **Post IDs** are 64-char lowercase hex (the transaction hash of the post).
- **Write responses** return `{"tx_hash", "code", "height", "raw_log"}`. `code=0` means success.
- **`GET /api/get_node_config`** returns static per-node settings (validator info, feature flags, giphy API key, registration settings). Cached 24h server-side. Not needed for posting.
- **Registration gating**: If the node requires invite codes, pass `invite_code` (format `XXXX-XXXX`) in the `set_username` POST body. This is not part of canonical bytes.
- **Media**: MsgPost accepts up to 10 HTTPS URLs in the `media` field (tag 105, repeated). Each URL max 2048 chars.
