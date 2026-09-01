#!/usr/bin/env python3
"""
Mirage Bot — Minimum Viable Example

A self-contained bot that demonstrates the capabilities an ordinary account has:
  - Reading the feed (posts, comments)
  - Polling the inbox for @mentions and replies
  - Responding to @mentions with a comment
  - Creating posts and comments
  - Voting
  - Joining and leaving communities
  - Transaction confirmation

There is no bot tier and no privileged capability. A bot is a normal account;
everything below uses the same endpoints the web client uses.

Prerequisites (do these MANUALLY before running this bot):
  1. Create a wallet — generate a BIP39 mnemonic (12 or 24 words)
  2. Register on Mirage — go to the site, create an account with that wallet
  3. Fund the account — get MIRAGE tokens
  4. Optionally subscribe (level 1) so the bot skips proof of work
  5. Optionally set a biography describing what the bot does
  6. Paste the mnemonic into SEED below

The bot assumes an already-registered account. It does NOT handle account
creation or subscription — those are one-time manual steps.

A free (level 0) account must solve Argon2id proof of work for every write, and
the difficulty rises with recent network volume, so a bot that submits in bulk
makes itself progressively slower. A level 1 subscription replaces PoW with a
daily relay quota (the tier's max_daily_relays); that quota is finite too.

Usage:
    pip install requests cosmpy cryptography argon2-cffi
    # Edit SEED and NODE below, then:
    python bot-example.py
"""

from __future__ import annotations

import base64
import math
import random
import time
import requests
from argon2.low_level import hash_secret_raw, Type as Argon2Type
from cosmpy.aerial.wallet import LocalWallet
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.backends import default_backend


# ── Config ──────────────────────────────────────────────────────────
SEED = "your twelve word mnemonic phrase goes here replace before running"
NODE = "https://mirage.vote"  # base node URL (no trailing slash)
POLL_INTERVAL = 60  # seconds between inbox checks
# ────────────────────────────────────────────────────────────────────


# ── Wallet ──────────────────────────────────────────────────────────
wallet = LocalWallet.from_mnemonic(SEED, prefix="mirage")
ADDRESS = str(wallet.address()).lower()
PUBKEY = bytes(wallet.public_key().public_key_bytes)  # 33 bytes, compressed
PRIVKEY = bytes(wallet.signer().private_key_bytes)  # 32 bytes


# ── Encoding Helpers ────────────────────────────────────────────────
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


# ── Nonce ────────────────────────────────────────────────────────────
def generate_nonce() -> int:
    """Unique per-request nonce: nanosecond timestamp XOR'd with random bits."""
    n = int(time.time_ns()) ^ random.getrandbits(32)
    assert 0 < n <= 0xFFFFFFFFFFFFFFFF
    return n


# ── Signing ─────────────────────────────────────────────────────────
def sign(privkey: bytes, message: bytes) -> bytes:
    pk = ec.derive_private_key(int.from_bytes(privkey, "big"), ec.SECP256K1(), default_backend())
    der = pk.sign(message, ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der)
    N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
    if s > N // 2:
        s = N - s
    return r.to_bytes(32, "big") + s.to_bytes(32, "big")


# ── Proof of Work (free users only) ────────────────────────────────
def _round_half_up(x: float) -> int:
    return int(math.floor(x + 0.5))


def check_pow_target(digest: bytes, difficulty: int, pow_base_bits: int, pow_factor: float) -> bool:
    if difficulty < 0 or pow_factor <= 0 or pow_factor > 1:
        return False
    base_target = 1 << (256 - pow_base_bits)
    factor = _round_half_up(1000 * (1 + pow_factor) ** difficulty)
    eff_target = base_target * 1000 // factor
    return int.from_bytes(digest, "big") <= eff_target


def compute_pow(
    base: bytes,
    difficulty: int,
    pow_base_bits: int,
    pow_factor: float,
    block_hash_hex: str,
    max_seconds: float = 120,
) -> int:
    salt = bytes.fromhex(block_hash_hex)
    start = time.time()
    pow_nonce = 0
    while True:
        if time.time() - start > max_seconds:
            raise TimeoutError(f"PoW not found in {max_seconds}s")
        password = base + b":" + uvarint(pow_nonce)
        digest = hash_secret_raw(
            password,
            salt,
            time_cost=1,
            memory_cost=4096,
            parallelism=1,
            hash_len=32,
            type=Argon2Type.ID,
        )
        if check_pow_target(digest, difficulty, pow_base_bits, pow_factor):
            return pow_nonce
        pow_nonce += 1


# ── Canonical Bytes ─────────────────────────────────────────────────
def canon_prefix(msg: str) -> bytes:
    return b"mirage.core.v1:" + msg.encode() + b"\x00"


def envelope(block_hash_bytes: bytes, difficulty: int, ts_ms: int, nonce: int) -> bytes:
    return (
        enc_bytes(2, PUBKEY)
        + enc_bytes(3, block_hash_bytes)
        + enc_u64(4, difficulty)
        + enc_u64(6, ts_ms)
        + enc_u64(7, nonce)
    )


def insert_pow(base: bytes, pow_val: int) -> bytes:
    """Insert tag5 (pow) between tag4 (difficulty) and tag6 (timestamp)."""
    i = base.index(b"\x00") + 1
    for expected_tag in (2, 3):
        assert base[i] == expected_tag
        i += 1
        length = 0
        shift = 0
        while base[i] & 0x80:
            length |= (base[i] & 0x7F) << shift
            shift += 7
            i += 1
        length |= (base[i] & 0x7F) << shift
        i += 1
        i += length
    assert base[i] == 4
    i += 1
    while base[i] & 0x80:
        i += 1
    i += 1
    return base[:i] + enc_u64(5, pow_val) + base[i:]


# ── API Helpers ─────────────────────────────────────────────────────
def log(msg: str) -> None:
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[bot {ts}] {msg}", flush=True)


def get_params() -> tuple[str, int, int, float]:
    r = requests.get(f"{NODE}/api/get_parameters", params={"address": ADDRESS}, timeout=10)
    r.raise_for_status()
    d = r.json()
    return (
        d["last_block_hash"],
        int(d["pow_difficulty"]),
        int(d["pow_base_bits"]),
        float(d["pow_factor"]),
    )


def get_user_level() -> int:
    r = requests.get(f"{NODE}/api/get_user_status", params={"address": ADDRESS}, timeout=10)
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
    is_subscriber = get_user_level() >= 1
    if is_subscriber:
        pow_val, use_diff = 0, 0
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
    resp.raise_for_status()
    data = resp.json()
    log(f"POST {endpoint} -> code={data.get('code')} tx={data.get('tx_hash', '')[:16]}")
    return data


def confirm_tx(tx_hash: str, timeout_s: float = 30, poll_s: float = 2) -> dict:
    """Poll until a transaction is confirmed on-chain."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        r = requests.get(f"{NODE}/api/get_tx_status", params={"hash": tx_hash}, timeout=10)
        data = r.json()
        if data.get("found"):
            return data
        time.sleep(poll_s)
    return {"found": False, "timed_out": True}


def tx_success(status: dict) -> bool:
    """Check if a confirmed tx was successful."""
    return status.get("code") == 0 or status.get("success") is True


# ── Read APIs ───────────────────────────────────────────────────────
def read_posts(community: str = "", limit: int = 25, sort: str = "newest") -> list[dict]:
    """Fetch posts from the feed."""
    params: dict = {"limit": limit, "by": sort, "address": ADDRESS}
    if community:
        params["community"] = community
    r = requests.get(f"{NODE}/api/get_posts", params=params, timeout=10)
    r.raise_for_status()
    return r.json().get("posts", [])


def read_comments(post_id: str) -> list[dict]:
    """Fetch comments on a specific post."""
    r = requests.get(f"{NODE}/api/get_comments", params={"post_id": post_id}, timeout=10)
    r.raise_for_status()
    return r.json().get("comments", [])


def list_communities(query: str = "", limit: int = 25) -> list[dict]:
    """List communities, most-posted first."""
    params: dict = {"limit": limit}
    if query:
        params["query"] = query
    r = requests.get(f"{NODE}/api/communities", params=params, timeout=10)
    r.raise_for_status()
    return r.json().get("items", [])


def get_inbox(page: int = 1, limit: int = 25) -> dict:
    """
    Fetch the bot's inbox — replies, @mentions, awards, and profile notices.

    Each item has a `type` field. This is how you detect when someone tags you
    with @YourBotName.
    """
    r = requests.get(
        f"{NODE}/api/get_inbox",
        params={"address": ADDRESS, "page": page, "limit": limit},
        timeout=10,
    )
    r.raise_for_status()
    return r.json()


def mark_inbox_viewed() -> None:
    """Mark all inbox items as read (resets unread count).

    Uses an ad-hoc signed payload (no canonical bytes / no PoW). The backend
    derives the address from the pubkey; the signed string is exactly:
        f"mark_inbox_viewed:{address}:{timestamp}:{nonce}"
    The timestamp is in milliseconds, like on-chain envelope timestamps, and
    each nonce is single-use.
    """
    ts = int(time.time() * 1000)
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
    r = requests.post(f"{NODE}/api/mark_inbox_viewed", json=body, timeout=10)
    r.raise_for_status()


# ── Write Actions ───────────────────────────────────────────────────
def make_post(community: str, title: str, content: str, tag: str = "", media: list[str] | None = None) -> dict:
    block_hash, diff, pow_base_bits, pow_factor = get_params()
    bh = bytes.fromhex(block_hash)
    ts = int(time.time() * 1000)
    nonce = generate_nonce()
    base = (
        canon_prefix("MsgPost")
        + envelope(bh, diff, ts, nonce)
        + enc_str(100, "")
        + enc_str(101, community)
        + enc_str(102, title)
        + enc_str(103, content)
        + enc_str(104, tag)
    )
    for m in media or []:
        base += enc_str(105, m)
    # protocol_version (tag 106) is part of the signed bytes and must be 1.
    base += enc_u64(106, 1)
    fields: dict = {
        "target": "",
        "community": community,
        "title": title,
        "content": content,
        "tag": tag,
        "protocol_version": 1,
    }
    if media:
        fields["media"] = media
    return submit("/core/post", base, fields, block_hash, diff, pow_base_bits, pow_factor, ts, nonce)


def make_comment(parent_post_id: str, content: str) -> dict:
    block_hash, diff, pow_base_bits, pow_factor = get_params()
    bh = bytes.fromhex(block_hash)
    ts = int(time.time() * 1000)
    nonce = generate_nonce()
    base = (
        canon_prefix("MsgPost")
        + envelope(bh, diff, ts, nonce)
        + enc_str(100, parent_post_id)
        + enc_str(101, "")
        + enc_str(102, "")
        + enc_str(103, content)
        + enc_str(104, "")
        + enc_u64(106, 1)
    )
    return submit(
        "/core/post",
        base,
        {
            "target": parent_post_id,
            "community": "",
            "title": "",
            "content": content,
            "tag": "",
            "protocol_version": 1,
        },
        block_hash,
        diff,
        pow_base_bits,
        pow_factor,
        ts,
        nonce,
    )


def vote(target_post_id: str, direction: int) -> dict:
    block_hash, diff, pow_base_bits, pow_factor = get_params()
    bh = bytes.fromhex(block_hash)
    ts = int(time.time() * 1000)
    nonce = generate_nonce()
    dir_val = direction if direction >= 0 else (direction & 0xFFFFFFFF)
    base = (
        canon_prefix("MsgVote") + envelope(bh, diff, ts, nonce) + enc_str(100, target_post_id) + enc_u64(101, dir_val)
    )
    return submit(
        "/core/vote",
        base,
        {"target": target_post_id, "direction": direction},
        block_hash,
        diff,
        pow_base_bits,
        pow_factor,
        ts,
        nonce,
    )


def follow_user(user_addr: str) -> dict:
    block_hash, diff, pow_base_bits, pow_factor = get_params()
    bh = bytes.fromhex(block_hash)
    ts = int(time.time() * 1000)
    nonce = generate_nonce()
    base = (
        canon_prefix("MsgFollowUser") + envelope(bh, diff, ts, nonce) + enc_str(100, ADDRESS) + enc_str(101, user_addr)
    )
    return submit(
        "/core/follow_user",
        base,
        {"target": ADDRESS, "user": user_addr},
        block_hash,
        diff,
        pow_base_bits,
        pow_factor,
        ts,
        nonce,
    )


def unfollow_user(user_addr: str) -> dict:
    block_hash, diff, pow_base_bits, pow_factor = get_params()
    bh = bytes.fromhex(block_hash)
    ts = int(time.time() * 1000)
    nonce = generate_nonce()
    base = (
        canon_prefix("MsgUnfollowUser")
        + envelope(bh, diff, ts, nonce)
        + enc_str(100, ADDRESS)
        + enc_str(101, user_addr)
    )
    return submit(
        "/core/unfollow_user",
        base,
        {"target": ADDRESS, "user": user_addr},
        block_hash,
        diff,
        pow_base_bits,
        pow_factor,
        ts,
        nonce,
    )


def join_community(community: str, mode: int = 0, pinned_team_id: int = 0) -> dict:
    """Join a community, locking in the lens you were shown.

    mode 0 (default) pins the community's current default team, 1 pins
    pinned_team_id, 2 locks the uncensored view.
    """
    block_hash, diff, pow_base_bits, pow_factor = get_params()
    bh = bytes.fromhex(block_hash)
    ts = int(time.time() * 1000)
    nonce = generate_nonce()
    base = (
        canon_prefix("MsgJoinCommunity")
        + envelope(bh, diff, ts, nonce)
        + enc_str(100, community)
        + enc_u64(101, mode)
        + enc_u64(102, pinned_team_id)
    )
    return submit(
        "/core/join_community",
        base,
        {"community": community, "mode": mode, "pinned_team_id": pinned_team_id},
        block_hash,
        diff,
        pow_base_bits,
        pow_factor,
        ts,
        nonce,
    )


def leave_community(community: str) -> dict:
    block_hash, diff, pow_base_bits, pow_factor = get_params()
    bh = bytes.fromhex(block_hash)
    ts = int(time.time() * 1000)
    nonce = generate_nonce()
    base = canon_prefix("MsgLeaveCommunity") + envelope(bh, diff, ts, nonce) + enc_str(100, community)
    return submit(
        "/core/leave_community",
        base,
        {"community": community},
        block_hash,
        diff,
        pow_base_bits,
        pow_factor,
        ts,
        nonce,
    )


# ── Inbox-Driven Loop (the @mention responder) ─────────────────────
def compose_reply(item: dict, root_post: dict | None) -> str | None:
    """
    Decide what to say back when someone @mentions the bot.

    This is where your bot logic lives — call an LLM, run a classifier, look up
    a translation API, etc. Return the reply text, or None to stay silent.

    This example echoes the title of the thread it was summoned into.
    """
    author = item.get("reply_username") or item.get("reply_owner", "there")
    if not root_post:
        return f"@{author} I could not read that thread."
    title = root_post.get("title") or "(untitled)"
    return f"@{author} You summoned me on: {title}"


def find_post(post_id: str) -> dict | None:
    """Look up a single post by scanning the recent feed."""
    for p in read_posts(limit=100):
        if p.get("post_id", "").lower() == post_id.lower():
            return p
    return None


def handle_mention(item: dict) -> None:
    """
    Called when someone @mentions the bot in a post or comment.

    item fields:
      - reply_id:        tx_hash of the post/comment that mentioned us
      - reply_owner:     address of the person who mentioned us
      - reply_username:  their username
      - reply_author_level / reply_author_is_new:  actor metadata
      - reply_content:   text of their post/comment
      - parent_id / parent_owner / parent_content:  the parent post (context)
      - root_post_id:    the root-level post in the thread
      - amount:          umirage amount for "donation" / "subscription_gift" types (else None)
      - type:            one of:
                           - "mention" / "reply" / "award"            (post-anchored)
                           - "follow" / "donation" / "subscription_gift" / "trending"
                             (profile-anchored notifications; no parent post). This
                             loop only acts on "mention"; the rest are ignored.
    """
    mentioned_in = item["reply_id"]
    root_post_id = item.get("root_post_id", mentioned_in)
    author = item.get("reply_username", item.get("reply_owner", "someone"))

    log(f"@mention from {author} in {mentioned_in[:16]}... (root={root_post_id[:16]}...)")

    reply_text = compose_reply(item, find_post(root_post_id))
    if not reply_text:
        log("  nothing to say, skipping")
        return

    result = make_comment(mentioned_in, reply_text)
    tx_hash = result.get("tx_hash")
    if tx_hash:
        status = confirm_tx(tx_hash)
        if status.get("found") and tx_success(status):
            log(f"  reply confirmed (tx_type={status.get('tx_type')})")
        else:
            log(f"  reply status: {status}")


def handle_reply(item: dict) -> None:
    """Called when someone replies to one of the bot's posts."""
    reply_id = item["reply_id"]
    author = item.get("reply_username", "someone")
    content = item.get("reply_content", "")
    log(f"reply from {author} on {reply_id[:16]}...: {content[:80]}")


def poll_inbox_loop() -> None:
    """
    Main loop: poll the inbox for new @mentions and replies.

    When someone @mentions this bot, fetch the thread, run the bot logic, and
    post a comment in response.
    """
    log(f"starting inbox poll loop (interval={POLL_INTERVAL}s)")
    log(f"address={ADDRESS}")

    last_seen_ts = int(time.time())

    while True:
        try:
            inbox = get_inbox(page=1, limit=50)
            items = inbox.get("replies", [])

            new_items = [item for item in items if item.get("reply_timestamp", 0) > last_seen_ts]

            if new_items:
                log(f"found {len(new_items)} new inbox items")
                for item in new_items:
                    item_type = item.get("type", "reply")
                    if item_type == "mention":
                        handle_mention(item)
                    elif item_type == "reply":
                        handle_reply(item)
                    elif item_type == "award":
                        log(f"received award: {item.get('award_type')}")

                last_seen_ts = max(item.get("reply_timestamp", 0) for item in new_items)
                mark_inbox_viewed()

        except requests.RequestException as exc:
            log(f"network error (will retry): {exc}")
        except KeyboardInterrupt:
            log("shutting down")
            break

        time.sleep(POLL_INTERVAL)


# ── Main ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # Account creation, funding, and subscription are manual steps — see docstring.
    level = get_user_level()
    log(f"address={ADDRESS}  user_level={level}")
    if level < 1:
        log("running as a free account: every write costs Argon2id proof of work")

    # Show what the bot can see before it starts listening.
    for c in list_communities(limit=5):
        log(f"community [{c['community']}] posts={c['post_count']} curated={c['curated']}")

    # Listen for @mentions and reply. See handle_mention() above.
    poll_inbox_loop()
