# Mirage Bot Guide

Comprehensive reference for building bots and other automated clients on the Mirage network. Covers wallet setup, signing, PoW, every live message type, and the read APIs.

A bot is an ordinary account. There is no special tier, no registry, and no privileged capability — a bot posts, comments, votes, joins communities and reads its inbox with exactly the same endpoints a browser uses. Everything in this guide was checked against `web/backend/routes/`, `shared/canon.py` and `blockchain/proto/mirage/core/v1/tx.proto` at v1.39.

## Dependencies

```bash
pip install requests cosmpy cryptography argon2-cffi
```

- `cosmpy` — BIP39 wallet derivation (secp256k1)
- `cryptography` — ECDSA signing
- `argon2-cffi` — Argon2id proof-of-work (free-tier only)
- `requests` — HTTP client

## Quick Start

```python
#!/usr/bin/env python3
"""Mirage bot — minimal self-contained example."""

import base64, json, time, math, random, requests
from argon2.low_level import hash_secret_raw, Type as Argon2Type
from cosmpy.aerial.wallet import LocalWallet
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.backends import default_backend

# ── Config ──────────────────────────────────────────────────────────
SEED = "word1 word2 ... word12"          # BIP39 mnemonic (12 or 24 words)
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


# ── Nonce ───────────────────────────────────────────────────────────
def generate_nonce() -> int:
    """Unique per-request nonce: nanosecond timestamp XOR'd with random bits."""
    n = int(time.time_ns()) ^ random.getrandbits(32)
    assert 0 < n <= 0xFFFFFFFFFFFFFFFF
    return n


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
    pow_nonce = 0
    while True:
        if time.time() - start > max_seconds:
            raise TimeoutError(f"PoW not found in {max_seconds}s")
        password = base + b":" + uvarint(pow_nonce)
        digest = hash_secret_raw(password, salt, time_cost=1, memory_cost=4096,
                                 parallelism=1, hash_len=32, type=Argon2Type.ID)
        if check_pow_target(digest, difficulty, pow_base_bits, pow_factor):
            return pow_nonce
        pow_nonce += 1


# ── Canonical Bytes ─────────────────────────────────────────────────
def canon_prefix(msg: str) -> bytes:
    return b"mirage.core.v1:" + msg.encode() + b"\x00"

def envelope(block_hash_bytes: bytes, difficulty: int, ts_ms: int, nonce: int) -> bytes:
    return (enc_bytes(2, PUBKEY)
          + enc_bytes(3, block_hash_bytes)
          + enc_u64(4, difficulty)
          + enc_u64(6, ts_ms)
          + enc_u64(7, nonce))

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
    r = requests.get(f"{NODE}/api/get_parameters?address={ADDRESS}", timeout=10)
    r.raise_for_status()
    data = r.json()
    return (
        data["last_block_hash"],
        int(data["pow_difficulty"]),
        int(data["pow_base_bits"]),
        float(data["pow_factor"]),
    )

def get_user_level() -> int:
    r = requests.get(f"{NODE}/api/get_user_status?address={ADDRESS}", timeout=10)
    r.raise_for_status()
    return int(r.json().get("user_level", 0) or 0)

def submit(
    endpoint: str,
    base: bytes,
    fields: dict,
    block_hash: str,
    difficulty: int,
    pow_base_bits: int,
    pow_factor: float,
    ts_ms: int,
    nonce: int,
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
        "envelope_nonce": str(nonce),
        "pow_difficulty": use_diff,
        "pow": pow_val,
        **fields,
    }
    resp = requests.post(f"{NODE}/api{endpoint}", json=body, timeout=15)
    print(f"POST {endpoint} → {resp.status_code}")
    try:
        resp.raise_for_status()
    except requests.HTTPError:
        try:
            print(json.dumps(resp.json(), indent=2))
        except ValueError:
            print(resp.text[:200])
        raise
    data = resp.json()
    print(json.dumps(data, indent=2))
    return data


# ── Actions ─────────────────────────────────────────────────────────
def make_post(community: str, title: str, content: str, tag: str = "",
              media: list[str] | None = None):
    block_hash, diff, pow_base_bits, pow_factor = get_params()
    bh = bytes.fromhex(block_hash)
    ts = int(time.time() * 1000)
    nonce = generate_nonce()
    base = (canon_prefix("MsgPost")
          + envelope(bh, diff, ts, nonce)
          + enc_str(100, "")            # target (empty for root post)
          + enc_str(101, community)
          + enc_str(102, title)
          + enc_str(103, content)
          + enc_str(104, tag))
    for m in (media or []):
        base += enc_str(105, m)         # media URLs (repeated tag 105)
    base += enc_u64(106, 1)             # protocol_version — must be 1
    fields = {"target": "", "community": community, "title": title,
              "content": content, "tag": tag, "protocol_version": 1}
    if media:
        fields["media"] = media
    return submit("/core/post", base, fields,
                  block_hash, diff, pow_base_bits, pow_factor, ts, nonce)

def make_comment(parent_post_id: str, content: str):
    block_hash, diff, pow_base_bits, pow_factor = get_params()
    bh = bytes.fromhex(block_hash)
    ts = int(time.time() * 1000)
    nonce = generate_nonce()
    base = (canon_prefix("MsgPost")
          + envelope(bh, diff, ts, nonce)
          + enc_str(100, parent_post_id)  # target = parent
          + enc_str(101, "")              # community (must be empty for comments)
          + enc_str(102, "")              # title (empty for comments)
          + enc_str(103, content)
          + enc_str(104, "")              # tag
          + enc_u64(106, 1))
    return submit("/core/post", base, {
        "target": parent_post_id, "community": "", "title": "",
        "content": content, "tag": "", "protocol_version": 1,
    }, block_hash, diff, pow_base_bits, pow_factor, ts, nonce)

def edit_post(override: str, community: str, title: str, content: str,
              tag: str = "", media: list[str] | None = None):
    """Edit an existing post. override = the post's tx_hash."""
    block_hash, diff, pow_base_bits, pow_factor = get_params()
    bh = bytes.fromhex(block_hash)
    ts = int(time.time() * 1000)
    nonce = generate_nonce()
    target = ""
    base = (canon_prefix("MsgEdit")
          + envelope(bh, diff, ts, nonce)
          + enc_str(100, target)
          + enc_str(101, community)
          + enc_str(102, title)
          + enc_str(103, content)
          + enc_str(104, tag)
          + enc_str(105, override))       # override = original post tx_hash
    for m in (media or []):
        base += enc_str(106, m)           # media URLs (repeated tag 106)
    fields = {"target": target, "community": community, "title": title,
              "content": content, "tag": tag, "override": override}
    if media:
        fields["media"] = media
    return submit("/core/edit", base, fields,
                  block_hash, diff, pow_base_bits, pow_factor, ts, nonce)

def delete_post(target_post_id: str):
    block_hash, diff, pow_base_bits, pow_factor = get_params()
    bh = bytes.fromhex(block_hash)
    ts = int(time.time() * 1000)
    nonce = generate_nonce()
    base = (canon_prefix("MsgDelete")
          + envelope(bh, diff, ts, nonce)
          + enc_str(100, target_post_id))
    return submit("/core/delete_post", base, {
        "target": target_post_id,
    }, block_hash, diff, pow_base_bits, pow_factor, ts, nonce)

def vote(target_post_id: str, direction: int):
    """direction: 1=upvote, -1=downvote, 0=remove"""
    block_hash, diff, pow_base_bits, pow_factor = get_params()
    bh = bytes.fromhex(block_hash)
    ts = int(time.time() * 1000)
    nonce = generate_nonce()
    dir_val = direction if direction >= 0 else (direction & 0xFFFFFFFF)
    base = (canon_prefix("MsgVote")
          + envelope(bh, diff, ts, nonce)
          + enc_str(100, target_post_id)
          + enc_u64(101, dir_val))
    return submit("/core/vote", base, {
        "target": target_post_id, "direction": direction,
    }, block_hash, diff, pow_base_bits, pow_factor, ts, nonce)

def set_username(username: str):
    block_hash, diff, pow_base_bits, pow_factor = get_params()
    bh = bytes.fromhex(block_hash)
    ts = int(time.time() * 1000)
    nonce = generate_nonce()
    base = (canon_prefix("MsgSetUsername")
          + envelope(bh, diff, ts, nonce)
          + enc_str(100, ADDRESS)
          + enc_str(101, username))
    return submit("/core/set_username", base, {"username": username},
                  block_hash, diff, pow_base_bits, pow_factor, ts, nonce)

def set_biography(biography: str):
    """Set profile biography. Requires a tier that allows one."""
    block_hash, diff, pow_base_bits, pow_factor = get_params()
    bh = bytes.fromhex(block_hash)
    ts = int(time.time() * 1000)
    nonce = generate_nonce()
    base = (canon_prefix("MsgSetBiography")
          + envelope(bh, diff, ts, nonce)
          + enc_str(100, ADDRESS)
          + enc_str(101, biography))
    return submit("/core/set_biography", base, {
        "target": ADDRESS, "biography": biography,
    }, block_hash, diff, pow_base_bits, pow_factor, ts, nonce)

def follow_user(user_addr: str):
    block_hash, diff, pow_base_bits, pow_factor = get_params()
    bh = bytes.fromhex(block_hash)
    ts = int(time.time() * 1000)
    nonce = generate_nonce()
    base = (canon_prefix("MsgFollowUser")
          + envelope(bh, diff, ts, nonce)
          + enc_str(100, ADDRESS)
          + enc_str(101, user_addr))
    return submit("/core/follow_user", base, {
        "target": ADDRESS, "user": user_addr,
    }, block_hash, diff, pow_base_bits, pow_factor, ts, nonce)

def unfollow_user(user_addr: str):
    block_hash, diff, pow_base_bits, pow_factor = get_params()
    bh = bytes.fromhex(block_hash)
    ts = int(time.time() * 1000)
    nonce = generate_nonce()
    base = (canon_prefix("MsgUnfollowUser")
          + envelope(bh, diff, ts, nonce)
          + enc_str(100, ADDRESS)
          + enc_str(101, user_addr))
    return submit("/core/unfollow_user", base, {
        "target": ADDRESS, "user": user_addr,
    }, block_hash, diff, pow_base_bits, pow_factor, ts, nonce)

def join_community(community: str):
    block_hash, diff, pow_base_bits, pow_factor = get_params()
    bh = bytes.fromhex(block_hash)
    ts = int(time.time() * 1000)
    nonce = generate_nonce()
    base = (canon_prefix("MsgJoinCommunity")
          + envelope(bh, diff, ts, nonce)
          + enc_str(100, community))
    return submit("/core/join_community", base, {
        "community": community,
    }, block_hash, diff, pow_base_bits, pow_factor, ts, nonce)

def leave_community(community: str):
    block_hash, diff, pow_base_bits, pow_factor = get_params()
    bh = bytes.fromhex(block_hash)
    ts = int(time.time() * 1000)
    nonce = generate_nonce()
    base = (canon_prefix("MsgLeaveCommunity")
          + envelope(bh, diff, ts, nonce)
          + enc_str(100, community))
    return submit("/core/leave_community", base, {
        "community": community,
    }, block_hash, diff, pow_base_bits, pow_factor, ts, nonce)

def block_community(community: str):
    block_hash, diff, pow_base_bits, pow_factor = get_params()
    bh = bytes.fromhex(block_hash)
    ts = int(time.time() * 1000)
    nonce = generate_nonce()
    base = (canon_prefix("MsgBlockCommunity")
          + envelope(bh, diff, ts, nonce)
          + enc_str(100, ADDRESS)
          + enc_str(101, community))
    return submit("/core/block_community", base, {
        "target": ADDRESS, "community": community,
    }, block_hash, diff, pow_base_bits, pow_factor, ts, nonce)

def block_post(post_id: str):
    block_hash, diff, pow_base_bits, pow_factor = get_params()
    bh = bytes.fromhex(block_hash)
    ts = int(time.time() * 1000)
    nonce = generate_nonce()
    base = (canon_prefix("MsgBlockPost")
          + envelope(bh, diff, ts, nonce)
          + enc_str(100, post_id))
    return submit("/core/block_post", base, {
        "target": post_id,
    }, block_hash, diff, pow_base_bits, pow_factor, ts, nonce)

def block_user(user_addr: str):
    block_hash, diff, pow_base_bits, pow_factor = get_params()
    bh = bytes.fromhex(block_hash)
    ts = int(time.time() * 1000)
    nonce = generate_nonce()
    base = (canon_prefix("MsgBlockUser")
          + envelope(bh, diff, ts, nonce)
          + enc_str(100, user_addr))
    return submit("/core/block_user", base, {
        "target": user_addr,
    }, block_hash, diff, pow_base_bits, pow_factor, ts, nonce)

def send_tokens(recipient: str, amount: int):
    """Send umirage tokens. amount is in umirage (1 MIRAGE = 1,000,000 umirage)."""
    block_hash, diff, pow_base_bits, pow_factor = get_params()
    bh = bytes.fromhex(block_hash)
    ts = int(time.time() * 1000)
    nonce = generate_nonce()
    base = (canon_prefix("MsgSendTokens")
          + envelope(bh, diff, ts, nonce)
          + enc_str(100, ADDRESS)
          + enc_str(101, recipient)
          + enc_u64(102, amount))
    return submit("/core/send_tokens", base, {
        "sender": ADDRESS, "target": recipient, "amount": amount,
    }, block_hash, diff, pow_base_bits, pow_factor, ts, nonce)

def subscribe(period_count: int = 1, target: str = ""):
    """Buy or gift a subscription. Level must be 1 — it is the only paid tier."""
    block_hash, _, _, _ = get_params()
    bh = bytes.fromhex(block_hash)
    ts = int(time.time() * 1000)
    nonce = generate_nonce()
    base = (canon_prefix("MsgSubscribe")
          + envelope(bh, 0, ts, nonce)
          + enc_u64(100, 1)
          + (enc_str(101, target) if target else b"")
          + enc_u64(102, period_count))
    signed_bytes = insert_pow(base, 0)      # PoW is never allowed for MsgSubscribe
    sig = sign(PRIVKEY, signed_bytes)
    body = {
        "pubkey": b64(PUBKEY),
        "signature": b64(sig),
        "last_block_hash": block_hash,
        "timestamp": ts,
        "envelope_nonce": str(nonce),
        "level": 1,
        "period_count": period_count,
    }
    if target:
        body["target"] = target
    resp = requests.post(f"{NODE}/api/core/subscribe", json=body, timeout=15)
    print(f"POST /core/subscribe → {resp.status_code}")
    print(json.dumps(resp.json(), indent=2))
    return resp.json()

def award_post(post_id: str, award_type: str):
    """Give an award to a post. Burns MIRAGE (free for admins)."""
    block_hash, _, _, _ = get_params()
    bh = bytes.fromhex(block_hash)
    ts = int(time.time() * 1000)
    nonce = generate_nonce()
    base = (canon_prefix("MsgAward")
          + envelope(bh, 0, ts, nonce)
          + enc_str(100, post_id)
          + enc_str(101, award_type))
    signed_bytes = insert_pow(base, 0)      # PoW is never allowed for MsgAward
    sig = sign(PRIVKEY, signed_bytes)
    body = {
        "pubkey": b64(PUBKEY),
        "signature": b64(sig),
        "last_block_hash": block_hash,
        "timestamp": ts,
        "envelope_nonce": str(nonce),
        "pow_difficulty": 0,
        "pow": 0,
        "target": post_id,
        "award_type": award_type,
    }
    resp = requests.post(f"{NODE}/api/core/award", json=body, timeout=15)
    print(f"POST /core/award → {resp.status_code}")
    print(json.dumps(resp.json(), indent=2))
    return resp.json()

def delete_user():
    """Permanently delete your account."""
    block_hash, diff, pow_base_bits, pow_factor = get_params()
    bh = bytes.fromhex(block_hash)
    ts = int(time.time() * 1000)
    nonce = generate_nonce()
    base = (canon_prefix("MsgDeleteUser")
          + envelope(bh, diff, ts, nonce)
          + enc_str(100, ADDRESS))
    return submit("/core/delete_user", base, {
        "target": ADDRESS,
    }, block_hash, diff, pow_base_bits, pow_factor, ts, nonce)

def report_post(post_id: str, reason: str):
    """Report a post. Stored off-chain (not a blockchain transaction)."""
    block_hash, diff, pow_base_bits, pow_factor = get_params()
    bh = bytes.fromhex(block_hash)
    ts = int(time.time() * 1000)
    nonce = generate_nonce()
    base = (canon_prefix("MsgReport")
          + envelope(bh, diff, ts, nonce)
          + enc_str(100, post_id)
          + enc_str(101, reason))
    return submit("/core/report", base, {
        "target": post_id, "reason": reason,
    }, block_hash, diff, pow_base_bits, pow_factor, ts, nonce)

def read_posts(community: str = "", limit: int = 10) -> list:
    params = {"limit": limit}
    if community:
        params["community"] = community
    r = requests.get(f"{NODE}/api/get_posts", params=params, timeout=10)
    r.raise_for_status()
    return r.json().get("posts", [])

def get_tx_status(tx_hash: str) -> dict:
    """Poll for transaction confirmation."""
    r = requests.get(f"{NODE}/api/get_tx_status", params={"hash": tx_hash}, timeout=10)
    r.raise_for_status()
    return r.json()


# ── Main ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    posts = read_posts(community="general", limit=5)
    for p in posts:
        print(f"  [{p['post_id'][:8]}] {p.get('title', '(no title)')}")

    # Register (first time)
    # set_username("my_bot")

    # Buy a subscription (skips PoW, higher limits)
    # subscribe()

    # Set biography (describes what your bot does)
    # set_biography("I summarize long threads.")

    # Create a post
    make_post("general", "Hello from a bot", "This is an automated post.")

    # Vote
    if posts:
        vote(posts[0]["post_id"], direction=1)
```

---

## How It Works

### 1. Wallet

`cosmpy` derives a secp256k1 keypair + `mirage1...` address from a BIP39 mnemonic (12 or 24 words). The public key is 33 bytes (compressed), private key is 32 bytes.

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

- `last_block_hash` — anchors the request to a recent block (hex, 64 chars). Must match one of the last `block_hash_window` committed block hashes (chain param).
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
  tag7  = nonce (varint)
  tag100 = target (string)           ← payload
  tag101 = community (string)
  ...
```

**Two-phase construction:**

1. **Base canonical** (for PoW input) — includes tag7 (nonce), excludes tag5 (pow) and tag10 (signature)
2. **Signed canonical** — base + tag5 inserted between tag4 and tag6 (nonce stays after tag6)

Authority (tag1) and signature (tag10) are never included in canonical bytes — authority is set by the backend to the validator address, and the signature is sent separately.

`shared/canon.py` is the reference implementation of every builder listed later in this guide. Read it before hand-rolling a new one.

### 4. Proof of Work

Free users (level 0) must solve Argon2id PoW. A tier whose `max_daily_relays` is greater than zero — level 1 subscribers and admins under current defaults — skips PoW entirely and sends `pow_difficulty=0`, `pow=0` instead.

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

Difficulty adjusts dynamically — increases when message volume is high, decreases during calm periods. A bot that submits in bulk raises the difficulty it then has to solve, so budget for it.

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
  "envelope_nonce": "<uint64 as string>",
  "pow_difficulty": 0,
  "pow": 0,
  ...message-specific fields
}
```

### 7. Transaction Lifecycle

Transactions are broadcast asynchronously. The response contains a locally-computed `tx_hash` and `code=0`, but this only means the backend successfully submitted the tx bytes to the node — **not** that the chain executed it. The node can reject it at CheckTx, or it can fail during block execution (e.g., invalid signature, title too long, insufficient funds).

**To confirm a transaction actually landed:**

```
GET /api/get_tx_status?hash=<tx_hash>
```

```json
{
  "found": true,
  "tx_hash": "abc123...",
  "code": 0,
  "success": true,
  "indexed": true,
  "tx_type": "post"
}
```

Poll this endpoint after submitting. `found=true` + `code=0` means the transaction was included in a block and executed successfully. `found=false` means the tx hasn't been indexed yet — keep polling. `code != 0` means the chain rejected it — check `error_details` for the reason.

For a post or a vote the response also carries a `details` object (`post_id`, `community`, `title` for posts; `owner`, `target`, `user_vote`, `user_weight`, `target_points` for votes).

---

## Subscription Tiers

| Level | Name | PoW | Period fee | Tier index |
|---|---|---|---|---|
| 0 | Free | Required | None | 0 |
| 1 | Subscriber | Skipped | Per-period | 1 |
| 100+ | Admin | Skipped | Not purchasable — appointed by governance | 2 |

Level 1 is the only level anyone can buy. `POST /api/core/subscribe` rejects any other value with `invalid_level`. `period_count` buys several periods at once and must be in `[1,12]`.

Tier limits (title length, content length, follow caps, biography) are returned by `GET /api/get_chain_config` in the `tiers` array, indexed by the tier index above. Fields per tier: `period_fee`, `max_followed_users`, `max_joined_communities`, `max_blocked_users`, `max_blocked_posts`, `max_blocked_communities`, `max_title_length`, `max_content_length`, `editing_time_mins`, `vote_weight`, `can_have_biography`, `can_have_avatar`, `can_have_banner`, `can_have_flair`, `max_biography_length`, `max_curation_memberships`, `max_daily_relays`.

`max_daily_relays` is the UTC-day envelope quota for the tier and is what actually replaces PoW: `0` means the account pays in proof of work instead. A subscriber that exhausts its daily quota starts failing, so a high-volume bot should track its own submission count rather than assume the quota is unlimited.

---

## Communities

A community is a slug, not an object with an owner. There is no create step: posting to a slug that nobody has used yet brings it into existence, and `/api/communities` lists slugs derived from posts, curation teams and membership rows.

- Slug format: `^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$` with no `--`, length between `min_community_size` and `max_community_size` from `get_chain_config`.
- In post bodies a community is written `[name]` and renders as a link to `/c/name`. `@name` still means a user.
- Joining a community is `MsgJoinCommunity`; it is a hard cap, so once `max_joined_communities` is reached the chain rejects the join until you leave one.
- Blocking a community is a deque: past the tier cap the chain evicts your oldest blocked entry rather than rejecting the write. A cap of `0` disables the list entirely and the handler rejects the write.

### Curation

Communities are moderated by curation teams, which are on-chain and permissionless to create if your tier allows it. Every curation message takes `community` as its first payload field and (except for `MsgCreateCurationTeam`) a `team_id`:

| Endpoint | Message | Payload |
|---|---|---|
| `/api/core/create_curation_team` | `MsgCreateCurationTeam` | 100=community, 101=name, 102=description |
| `/api/core/set_curation_team_profile` | `MsgSetCurationTeamProfile` | 100=community, 101=team_id, 102=name, 103=description |
| `/api/core/invite_curator` | `MsgInviteCurator` | 100=community, 101=team_id, 102=target |
| `/api/core/revoke_curator_invite` | `MsgRevokeCuratorInvite` | 100=community, 101=team_id, 102=target |
| `/api/core/accept_curator_invite` | `MsgAcceptCuratorInvite` | 100=community, 101=team_id |
| `/api/core/decline_curator_invite` | `MsgDeclineCuratorInvite` | 100=community, 101=team_id |
| `/api/core/leave_curation_team` | `MsgLeaveCurationTeam` | 100=community, 101=team_id |
| `/api/core/remove_curator` | `MsgRemoveCurator` | 100=community, 101=team_id, 102=target |
| `/api/core/transfer_curation_team` | `MsgTransferCurationTeam` | 100=community, 101=team_id, 102=new_owner |
| `/api/core/delete_curation_team` | `MsgDeleteCurationTeam` | 100=community, 101=team_id |
| `/api/core/set_curation_preference` | `MsgSetCurationPreference` | 100=community, 101=mode, 102=pinned_team_id |
| `/api/core/set_curation_post_hidden` | `MsgSetCurationPostHidden` | 100=community, 101=team_id, 102=target, 103=hidden |
| `/api/core/set_curation_user_hidden` | `MsgSetCurationUserHidden` | 100=community, 101=team_id, 102=target, 103=hidden |
| `/api/core/set_curation_thread_locked` | `MsgSetCurationThreadLocked` | 100=community, 101=team_id, 102=root_hash, 103=locked |
| `/api/core/set_curation_subscriber_only` | `MsgSetCurationSubscriberOnly` | 100=community, 101=team_id, 102=enabled |
| `/api/core/set_curation_tag` | `MsgSetCurationTag` | 100=community, 101=team_id, 102=tag |
| `/api/core/set_curation_post_tag` | `MsgSetCurationPostTag` | 100=community, 101=team_id, 102=target, 103=tag, 104=clear |

`create_curation_team` requires an active subscription; the backend answers `not_subscriber` otherwise. Team membership is separately capped by the tier's `max_curation_memberships`, which the chain enforces.

Read the curation state with the endpoints under `/api/communities/<slug>` — see [Reading Data](#reading-data).

---

## Posting: Complete Reference

### Create a Root Post

**Endpoint:** `POST /api/core/post`

| Field | Type | Required | Description |
|---|---|---|---|
| `target` | string | yes | Empty string `""` for root posts |
| `community` | string | yes | Community slug (see [Communities](#communities)) |
| `title` | string | yes | Post title (length limit based on tier) |
| `content` | string | yes | Post body (length limit based on tier) |
| `tag` | string | no | Content warning: `""`, `"sensitive"`, `"adult"`, `"gore"`, `"violence"`, `"death"` |
| `media` | string[] | no | Up to 10 HTTPS URLs, each max 2048 chars |
| `protocol_version` | int | yes | Must be `1`. Anything else returns 426 `upgrade_required` |

**Canonical bytes (MsgPost):**

| Tag | Field | Encoding |
|---|---|---|
| 100 | target | string (empty `""`) |
| 101 | community | string |
| 102 | title | string |
| 103 | content | string |
| 104 | tag | string |
| 105 | media[0] | string (repeated for each URL) |
| 106 | protocol_version | uint64 (always `1`) |

Tag 106 is easy to miss and there is no error message that points at it: omit it and the signature simply does not verify.

### Create a Comment

Same endpoint (`POST /api/core/post`) and same canonical prefix (`MsgPost`), but:

- `target` = parent post's `tx_hash` (64-char hex)
- `community` = empty string — sending one returns `comment_must_not_include_community`
- `title` = empty string
- `content` = comment body (required, non-empty)

### Edit a Post

**Endpoint:** `POST /api/core/edit`

| Field | Type | Required | Description |
|---|---|---|---|
| `override` | string | yes | The `tx_hash` of the post being edited (64-char hex). You must own it. |

All other fields (`target`, `community`, `title`, `content`, `tag`, `media`) work the same as create. Send the full updated values — this is a full replacement, not a partial update. `target` must equal the stored parent; the chain will not let you re-parent a post.

**Canonical bytes (MsgEdit) — note different tag numbers for override/media, and no protocol_version:**

| Tag | Field | Encoding |
|---|---|---|
| 100 | target | string |
| 101 | community | string |
| 102 | title | string |
| 103 | content | string |
| 104 | tag | string |
| 105 | override | string |
| 106 | media[0] | string (repeated for each URL) |

### Delete a Post

**Endpoint:** `POST /api/core/delete_post`

| Field | Type | Required | Description |
|---|---|---|---|
| `target` | string | yes | The `tx_hash` of the post to delete. You must own it (admins may delete any post). |

**Canonical bytes (MsgDelete):** 100=target.

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
| `username` | string | yes | `[A-Za-z0-9][A-Za-z0-9-]*` (must start with a letter or number), length from `get_chain_config` |

The backend derives `target` from your pubkey; you cannot set a username for another address.

**Canonical bytes (MsgSetUsername):**

| Tag | Field | Encoding |
|---|---|---|
| 100 | target | string (own address derived from pubkey) |
| 101 | username | string |

Usernames are case-insensitive; uniqueness is enforced on lowercase. If the node has `registration_enabled=false` in `get_node_config`, a first-time `set_username` is rejected with `registration_disabled`.

### Set Biography

**Endpoint:** `POST /api/core/set_biography`

| Field | Type | Required | Description |
|---|---|---|---|
| `target` | string | yes | Own address (derived from pubkey by backend) |
| `biography` | string | yes | Free-form text. The backend caps it at 512 characters; the tier's `max_biography_length` applies on top of that, and `0` means the tier has no biography at all. |

**Canonical bytes (MsgSetBiography):** 100=target (own address), 101=biography.

### Award

**Endpoint:** `POST /api/core/award`

| Field | Type | Required | Description |
|---|---|---|---|
| `target` | string | yes | Post tx_hash to award |
| `award_type` | string | yes | A `name` from the `award_configs` array in `get_chain_config` |

Burns MIRAGE tokens (free for admins level >= 100). PoW is not allowed: send `pow_difficulty=0`, `pow=0`.

**Canonical bytes (MsgAward):** 100=target (post tx_hash), 101=award_type.

---

## Media: Uploading Images and Videos

Posts accept up to 10 media URLs in the `media` field. You can use any HTTPS URL, or upload the file to the node.

### Upload

```
POST /api/upload_media?kind=image
```

Send the bytes as a multipart form with the file in the `file` field. For `kind=video`, also send `duration` and `height` form fields — the backend rejects the upload without them.

The response is provider-agnostic:

```json
{"url": "https://...", "asset_id": "...", "kind": "image"}
```

Put `url` straight into the `media` array when posting. Which storage backend is behind this (local disk, Cloudflare, Bunny) is a per-node deployment choice and is not visible to the client.

A node that is not fronted by a scanning edge sets uploads off entirely and answers `uploads_disabled` with 403. Handle that: it is a normal configuration, not an outage.

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
GET /api/get_posts?community=general&limit=25&page=1&by=magic
```

| Param | Default | Description |
|---|---|---|
| `community` | — | Filter to one community slug |
| `limit` | 25 | Posts per page (max 100) |
| `page` | 1 | Page number |
| `by` | `"magic"` | Sort: `"magic"` (algorithmic) or `"newest"` (chronological) |
| `address` | — | Viewer address (enables blocked-content filtering and `user_vote`) |
| `feed` | — | `"home"` or `"following"` for personalized feeds |

**Response:**

```json
{
  "posts": [
    {
      "post_id": "64char_hex_txhash",
      "user_id": "mirage1...",
      "username": "alice",
      "author_level": 1,
      "author_is_new": false,
      "timestamp": 1700000000,
      "community": "general",
      "title": "Post title",
      "content": "Post body",
      "tag": "",
      "thumbnail": "https://...",
      "media": ["https://..."],
      "relayer": "mirage1...",
      "points": 42.0,
      "comments": 5,
      "user_vote": 0,
      "user_weight": 0.0,
      "awards": []
    }
  ],
  "total": 100,
  "page": 1,
  "limit": 25,
  "has_more": true
}
```

Comment and thread payloads additionally carry `root_community` and `root_post_id`, which name the community and root post of the thread a comment belongs to.

### Get Comments

```
GET /api/get_comments?post_id=<64char_hex>
```

### Communities

```
GET /api/communities?query=&joined_by=&curated=&cursor=&limit=
GET /api/communities/<slug>?viewer=<addr>
GET /api/curators/<address>/communities
GET /api/communities/<slug>/teams
GET /api/communities/<slug>/teams/<team_id>
```

`/api/communities` returns `{items, next_cursor, has_more}` where each item is `{community, curated, live_team_count, post_count, default_team}`, ordered by post count. Pagination is cursor-based: pass the returned `next_cursor` (`post_count:community`) back as `cursor`.

`/api/communities/<slug>` returns the community's team counts, post counts, and — when `viewer` is supplied — whether that viewer has joined and which curation lens applies to them.

### Search

```
GET /api/search?q=<query>&type=&limit=10&offset=0&address=
```

`q` prefixed with `@` searches users, `#` searches communities, anything else searches all three. `type` narrows a general search to `communities`, `users` or `posts` for a Load More. The response is `{query, search_type, communities, users, posts, has_more_communities, has_more_users, has_more_posts}`.

### Get User Status

```
GET /api/get_user_status?address=mirage1...
```

```json
{
  "username": "alice",
  "balance": 1000000,
  "user_level": 0,
  "effective_paid": false,
  "subscription_expiry": 0,
  "auto_renew": false,
  "reserve_funds": 0,
  "profile_registered_at": 1700000000,
  "recent_votes": [
    {"target": "txhash", "direction": 1, "timestamp": 1700000000}
  ],
  "inbox_last_viewed_at": 1700000000
}
```

- `subscription_expiry` is a Unix timestamp in seconds; `0` means no active subscription.
- `effective_paid` is the indexer's view of whether the subscription is currently paid up. When it is true the response reports `user_level` of at least 1, which is what the PoW-exempt paths key off.
- `recent_votes` returns up to the last 100 votes by this user (target tx-hash, direction `-1|0|1`, Unix-seconds timestamp).
- `inbox_last_viewed_at` is a Unix timestamp updated by `POST /api/mark_inbox_viewed`.
- `new_inbox_items` is injected into every JSON response that carries an `address` query parameter (middleware in `factory.py`), so it appears here too.

### Get Lists and Preferences

```
GET /api/get_user_followed?address=mirage1...   → {followed_users, joined_communities}
GET /api/get_user_blocked?address=mirage1...    → {blocked_posts, blocked_users, blocked_communities}
GET /api/get_preferences?address=mirage1...     → {communities: [{community, weight}], authors: [{user, weight}]}
```

`joined_communities` is derived from the viewer's curation-preference rows — joining a community *is* having a preference row for it, so there is no separate membership list to read.

### Get Chain Config

```
GET /api/get_chain_config
```

```json
{
  "max_username_size": 30,
  "min_username_size": 3,
  "max_community_size": 35,
  "min_community_size": 2,
  "subscription_period": 43200,
  "subscription_reserve_bps": 9500,
  "mint_interval": 200,
  "mint_floor_split": 0.5,
  "mint_dynamic_split": 0.5,
  "block_time": 3,
  "tiers": [ ... ],
  "award_configs": [{"name": "quality_post", "cost": 1000000}]
}
```

**Units & semantics:**
- `subscription_period` is in **minutes** (`43200` = 30 days; `0` = one-time).
- `mint_interval` is in **blocks**.
- `block_time` is the mean target block time in **seconds**.
- `subscription_reserve_bps` ∈ [0,10000] is the share of each period fee escrowed as gas reserve, in basis points; the remainder is burned.

Cached 60 seconds server-side, alongside the underlying parameter cache, so a governance change becomes visible on the next window.

### Get Inbox (Replies, @Mentions, Awards)

```
GET /api/get_inbox?address=mirage1...&page=1&limit=25
```

| Param | Default | Description |
|---|---|---|
| `address` | — | **Required.** Your bot's address |
| `page` | 1 | Page number |
| `limit` | 25 | Items per page (max 100) |

**Response:**

```json
{
  "replies": [
    {
      "reply_id": "64char_hex_txhash",
      "reply_owner": "mirage1...",
      "reply_username": "alice",
      "reply_author_level": 1,
      "reply_author_is_new": false,
      "reply_content": "Hey @MyBot, what do you think?",
      "reply_timestamp": 1700000000,
      "parent_id": "64char_hex_txhash",
      "parent_content": "Original post preview...",
      "parent_owner": "mirage1...",
      "root_post_id": "64char_hex_txhash",
      "award_type": "",
      "type": "mention",
      "amount": null
    }
  ],
  "total": 42,
  "page": 1,
  "limit": 25,
  "has_more": true
}
```

The `type` field distinguishes inbox items. Indexer-sourced types:
- `"mention"` — someone wrote `@YourBotName` in a post or comment.
- `"reply"` — someone replied to one of your posts.
- `"award"` — someone gave an award to one of your posts (`award_type` is set).

Backend-sourced types (stored in `inbox_events`):
- `"follow"` — someone started following you.
- `"donation"` — someone sent you tokens; `amount` is in umirage.
- `"subscription_gift"` — someone gifted you a subscription; `amount` is the level.
- `"trending"` — one of your posts is trending; `parent_id` / `root_post_id` point at the post.

For follow/donation/subscription_gift items there is no underlying post, so `parent_id`, `parent_content`, and `reply_content` are empty. `reply_author_is_new` reflects whether the actor profile is younger than `new_user_highlight_days` (per-node config). `amount` is `null` for non-monetary items.

This is the key API for building a bot that responds to @mentions. Poll this endpoint, filter for `type: "mention"`, read `reply_content`, and reply with `make_comment(parent_post_id=reply_id, ...)`.

### Mark Inbox Viewed

```
POST /api/mark_inbox_viewed
{
  "pubkey": "<base64, 33 bytes>",
  "signature": "<base64, 64 bytes>",
  "address": "mirage1...",
  "timestamp": 1700000000000,
  "envelope_nonce": "1234567890"
}
```

Resets `inbox_last_viewed_at` (and therefore the `new_inbox_items` counter the backend injects into other API responses) to `now`.

Unlike write transactions, this endpoint does **not** use canonical-bytes / PoW. It uses a lightweight ad-hoc signed payload:

```python
signed_payload = f"mark_inbox_viewed:{address.lower()}:{timestamp}:{nonce}".encode()
signature      = ecdsa_sha256(signed_payload, privkey)   # low-S, 64-byte compact
```

Send `pubkey` and `signature` base64-encoded and `envelope_nonce` as a string (uint64); the backend derives the address from the pubkey and rejects the request if the optional `address` field doesn't match. The `timestamp` is in **milliseconds** and must be within the push skew window. Replay protection is a per-address nonce table, so each nonce is single-use.

**Example client snippet:**

```python
def mark_inbox_viewed():
    ts    = int(time.time() * 1000)
    nonce = generate_nonce()
    payload = f"mark_inbox_viewed:{ADDRESS.lower()}:{ts}:{nonce}".encode()
    sig = sign(PRIVKEY, payload)
    body = {
        "pubkey": b64(PUBKEY),
        "signature": b64(sig),
        "address": ADDRESS,
        "timestamp": ts,
        "envelope_nonce": str(nonce),
    }
    requests.post(f"{NODE}/api/mark_inbox_viewed", json=body, timeout=10).raise_for_status()
```

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
  "open_browsing_enabled": true,
  "new_user_highlight_days": 30,
  "push_notifications_enabled": true,
  "android_banner_enabled": false,
  "ios_banner_enabled": false
}
```

Per-node static settings (validator info, feature flags, API keys). Cached 24 hours server-side. `registration_enabled` is the one a bot should check before its first `set_username`.

The response also carries `registration_invite_code_required`. Ignore it. Invite codes were removed in v1.39.0, and a node configured with that flag set refuses to start, so on any reachable node the value is false.

---

## All Message Types

| Action | Prefix | Endpoint | Payload tags |
|---|---|---|---|
| Post | `MsgPost` | `/core/post` | 100=target, 101=community, 102=title, 103=content, 104=tag, 105=media (repeated), 106=protocol_version |
| Comment | `MsgPost` | `/core/post` | Same as Post (target=parent post_id, community/title empty) |
| Edit | `MsgEdit` | `/core/edit` | 100=target, 101=community, 102=title, 103=content, 104=tag, 105=override, 106=media (repeated) |
| Delete | `MsgDelete` | `/core/delete_post` | 100=target |
| Vote | `MsgVote` | `/core/vote` | 100=target, 101=direction |
| Set Username | `MsgSetUsername` | `/core/set_username` | 100=target (own addr), 101=username |
| Set Biography | `MsgSetBiography` | `/core/set_biography` | 100=target (own addr), 101=biography |
| Follow User | `MsgFollowUser` | `/core/follow_user` | 100=target (own addr), 101=user |
| Unfollow User | `MsgUnfollowUser` | `/core/unfollow_user` | 100=target (own addr), 101=user |
| Join Community | `MsgJoinCommunity` | `/core/join_community` | 100=community |
| Leave Community | `MsgLeaveCommunity` | `/core/leave_community` | 100=community |
| Block Community | `MsgBlockCommunity` | `/core/block_community` | 100=target (own addr), 101=community |
| Unblock Community | `MsgUnblockCommunity` | `/core/unblock_community` | 100=target (own addr), 101=community |
| Block Post | `MsgBlockPost` | `/core/block_post` | 100=target (post_id) |
| Unblock Post | `MsgUnblockPost` | `/core/unblock_post` | 100=target (post_id) |
| Block User | `MsgBlockUser` | `/core/block_user` | 100=target (address) |
| Unblock User | `MsgUnblockUser` | `/core/unblock_user` | 100=target (address) |
| Report | `MsgReport` | `/core/report` | 100=target (post_id), 101=reason |
| Send Tokens | `MsgSendTokens` | `/core/send_tokens` | 100=sender (own addr), 101=target, 102=amount (varint) |
| Subscribe | `MsgSubscribe` | `/core/subscribe` | 100=level (always 1), 101=target (only when gifting), 102=period_count |
| Set Auto Renewal | `MsgSetAutoRenewal` | `/core/set_auto_renewal` | 100=auto_renew (1=on, 0=off) |
| Delete User | `MsgDeleteUser` | `/core/delete_user` | 100=target (own addr) |
| Award | `MsgAward` | `/core/award` | 100=target (post_id), 101=award_type |
| Claim Creator Rewards | `MsgClaimCreatorRewards` | `/core/claim_creator_rewards` | 100=epoch_id (repeated, strictly increasing, max 30) |

Curation team messages are listed under [Curation](#curation).

---

## Removed in v1.39.0

If you are porting a client written against an older guide, these are gone. Do not build against them.

**Agents.** The agent tier, the agent overlay message `MsgAnnotate`, the enabled-agents list and the agent directory were all removed. `/api/core/annotate`, `/api/core/enable_agent`, `/api/core/disable_agent`, `/api/core/set_agents` and `/api/get_agents` answer **410 Gone**. There is no level 10 and no `can_be_agent` tier flag. Post responses no longer carry `agent_edited`, `agent_edits_meta` or `appendices`. Nothing replaces the overlay mechanism — a bot can post, comment and vote, but it cannot alter how anyone else's post is displayed.

**Topics.** Topics were renamed to communities, and the rename went all the way through the wire format rather than being aliased. `/api/get_topics`, `/api/search_topics`, `/api/core/follow_topic`, `/api/core/unfollow_topic`, `/api/core/block_topic` and `/api/core/unblock_topic` answer **410 Gone**. The `topic` field on a post is now `community`, `root_topic` is `root_community`, and `/api/get_posts` takes `community` rather than `topic`. The `/t/:slug` and `/topics` web routes 404 with no redirect. Every `topic_*` error code was renamed to its `community_*` equivalent, with two exceptions worth knowing: the post-body one is `post_community_required` rather than `community_required`, because a distinct `community_required` already existed, and `topic_already_followed` became `community_already_joined`. Sending `topic=` to `/api/get_posts` still answers `topic_retired`, which is the one error code that keeps the old word on purpose.

**Quests, referrals and invite codes.** `/api/quests`, `/api/referrals`, `/api/rewards`, `/api/invite`, `/api/get_referral`, `/api/get_invite_codes` and `/api/validate_invite_code` answer **410 Gone**, as do the `signups`, `rewards` and `rewards_history` tabs of `/api/get_stats`. `set_username` still accepts `invite_code` and `referrer` in the body and ignores them, purely so an old client's signup is not blocked; do not send them.

`MsgFollowTopic`, `MsgUnfollowTopic`, `MsgBlockTopic`, `MsgUnblockTopic`, `MsgEnableAgent`, `MsgDisableAgent`, `MsgSetAgents` and `MsgAnnotate` still exist in `tx.proto` and in `shared/canon.py`. They are there so historical blocks can still be decoded. New transactions using them are rejected.

---

## Reference Notes

- **Envelope nonce** (tag 7): mandatory since v1.20.0. Unique per-request uint64, sent as a string in the JSON body (`"envelope_nonce": "123456789"`). Included in canonical bytes for signing. Generate as `time_ns ^ random_bits`.
- **Tag encoding**: `bytes`/`string` fields = `[tag_byte, uvarint(length), data]`. Integer fields = `[tag_byte, uvarint(value)]`.
- **Direction** for votes: Go encodes `int32(-1)` as `uint32(4294967295)` in the canonical bytes.
- **Amounts** are in `umirage` (1 MIRAGE = 1,000,000 umirage).
- **Timestamps** in the envelope are milliseconds since epoch.
- **Post IDs** are 64-char lowercase hex (the transaction hash of the post).
- **Community slugs** are lowercase, may contain single internal hyphens, and are bounded by `min_community_size` / `max_community_size`. Blocked-community patterns may include `*`.
- **Timestamp freshness**: rejected if older than `max_envelope_age` seconds. Small future skew is allowed (capped at 30s, derived from `max_envelope_age/2`).
- **Block hash window**: must match one of the last `block_hash_window` committed block hashes.
- **Unsafe characters**: control characters (other than tab, newline and carriage return) are rejected in usernames, communities, titles, content, tags, and media URLs. Unicode is fine.
- **Relay-exempt accounts** (a tier with `max_daily_relays > 0`) must send `pow_difficulty=0` and `pow=0`.
- **PoW is never allowed** for `MsgSubscribe`, `MsgSetAutoRenewal` or `MsgAward`.
- **Report** is stored off-chain in the backend database, not as a blockchain transaction, and always requires a valid `last_block_hash` plus PoW fields regardless of tier. The canonical signature is still verified.
- **Async broadcast**: all transactions use async broadcast. `code=0` in the POST response only means the backend submitted the tx bytes; the node can still reject it. Use `get_tx_status` to confirm inclusion.
- **Every error response carries `error_code`.** Match on that, never on the human-readable `error` string — the registry in `web/backend/error_utils.py` is the full list.
