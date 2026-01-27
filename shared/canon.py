#!/usr/bin/env python3
"""
Shared canonical bytes builder for Mirage relay/PoW messages.

IMPORTANT: Authority field is NOT included in canonical bytes!

The authority field (tag 1) in the protobuf message represents the validator/node address
that is relaying the transaction. It is set by the backend/node, NOT by the user/client.
Canonical bytes for relay signature verification EXCLUDE authority - they only include:
- Envelope fields: envelope_pubkey(2), envelope_block_hash(3), envelope_difficulty(4),
  envelope_pow(5), envelope_timestamp(6)
- Payload fields starting at tag 100: target(100), username(101), topic(101), etc.

Rules (for all messages):
- Prefix: b"mirage.core.v1:" + MsgName + b"\x00"
- Fields are written in increasing tag order, EXCLUDING:
  - authority (tag 1) - NOT included in canonical bytes, set by backend to validator address
  - signature (tag 10) - NOT included in canonical bytes
- Types:
  - bytes: tag + uvarint(len) + raw bytes
  - string: tag + uvarint(len) + UTF-8 bytes
  - uint64/int32: tag + uvarint(value)

Order (envelope + payload, NO authority):
- Envelope: envelope_pubkey(2), envelope_block_hash(3), envelope_difficulty(4),
            envelope_pow(5), envelope_timestamp(6)
- Payload starts at 100: target(100), username(101), etc.
- envelope_pow tag is 5 when present for signature canonical; not included in base
"""

from __future__ import annotations


def uvarint(n: int) -> bytes:
    n = int(n) & 0xFFFFFFFFFFFFFFFF
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            break
    return bytes(out)


def _enc_tag(tag: int) -> bytes:
    return bytes([tag & 0xFF])


def _enc_str(tag: int, s: str) -> bytes:
    b = (s or "").encode("utf-8")
    return _enc_tag(tag) + uvarint(len(b)) + b


def _enc_bytes(tag: int, b: bytes) -> bytes:
    b = bytes(b or b"")
    return _enc_tag(tag) + uvarint(len(b)) + b


def _enc_u64(tag: int, v: int) -> bytes:
    return _enc_tag(tag) + uvarint(int(v))


def _prefix(msg_name: str) -> bytes:
    return b"mirage.core.v1:" + msg_name.encode("utf-8") + b"\x00"


# Base (no pow/signature) canonical used for PoW
def canon_base_set_username(
    pubkey: bytes,
    last_block_hash: bytes,
    difficulty: int,
    timestamp: int,
    target: str,
    username: str,
) -> bytes:
    out = bytearray(_prefix("MsgSetUsername"))
    out += _enc_bytes(2, pubkey)
    out += _enc_bytes(3, last_block_hash)
    out += _enc_u64(4, difficulty)
    out += _enc_u64(6, timestamp)
    out += _enc_str(100, target)
    out += _enc_str(101, username)
    return bytes(out)


# NOTE: Authority (tag 1) is NOT included - it's set by backend to validator address
# NOTE: Pow (tag 5) is included AFTER envelope fields (2-4) but BEFORE timestamp (6)
# to match Go ante_metasig.go canonical order
def canon_base_post(
    pubkey: bytes,
    last_block_hash: bytes,
    difficulty: int,
    timestamp: int,
    target: str,
    topic: str,
    title: str,
    content: str,
    tag: str = "",
    pow_val: int = 0,
) -> bytes:
    out = bytearray(_prefix("MsgPost"))
    out += _enc_bytes(2, pubkey)
    out += _enc_bytes(3, last_block_hash)
    out += _enc_u64(4, difficulty)
    if pow_val > 0:
        out += _enc_u64(5, pow_val)
    out += _enc_u64(6, timestamp)
    out += _enc_str(100, target)
    out += _enc_str(101, topic or "")
    out += _enc_str(102, title)
    out += _enc_str(103, content)
    out += _enc_str(104, tag)
    return bytes(out)


def canon_base_edit(
    pubkey: bytes,
    last_block_hash: bytes,
    difficulty: int,
    timestamp: int,
    target: str,
    topic: str,
    title: str,
    content: str,
    tag: str,
    override: str,
) -> bytes:
    out = bytearray(_prefix("MsgEdit"))
    out += _enc_bytes(2, pubkey)
    out += _enc_bytes(3, last_block_hash)
    out += _enc_u64(4, difficulty)
    out += _enc_u64(6, timestamp)
    out += _enc_str(100, target)
    out += _enc_str(101, topic or "")
    out += _enc_str(102, title)
    out += _enc_str(103, content)
    out += _enc_str(104, tag)
    out += _enc_str(105, override)
    return bytes(out)


def canon_base_vote(
    pubkey: bytes,
    last_block_hash: bytes,
    difficulty: int,
    timestamp: int,
    target: str,
    direction: int,
) -> bytes:
    out = bytearray(_prefix("MsgVote"))
    out += _enc_bytes(2, pubkey)
    out += _enc_bytes(3, last_block_hash)
    out += _enc_u64(4, difficulty)
    out += _enc_u64(6, timestamp)
    out += _enc_str(100, target)
    # Direction is int32 in proto, but Go converts to uint32 before encoding
    # int32(-1) -> uint32(4294967295)
    dir_val = direction if direction >= 0 else (direction & 0xFFFFFFFF)
    out += _enc_u64(101, dir_val)
    return bytes(out)


def canon_base_follow_moderator(
    pubkey: bytes,
    last_block_hash: bytes,
    difficulty: int,
    timestamp: int,
    target: str,
    moderator: str,
) -> bytes:
    out = bytearray(_prefix("MsgFollowModerator"))
    out += _enc_bytes(2, pubkey)
    out += _enc_bytes(3, last_block_hash)
    out += _enc_u64(4, difficulty)
    out += _enc_u64(6, timestamp)
    out += _enc_str(100, target)
    out += _enc_str(101, moderator)
    return bytes(out)


def canon_base_unfollow_moderator(
    pubkey: bytes,
    last_block_hash: bytes,
    difficulty: int,
    timestamp: int,
    target: str,
    moderator: str,
) -> bytes:
    out = bytearray(_prefix("MsgUnfollowModerator"))
    out += _enc_bytes(2, pubkey)
    out += _enc_bytes(3, last_block_hash)
    out += _enc_u64(4, difficulty)
    out += _enc_u64(6, timestamp)
    out += _enc_str(100, target)
    out += _enc_str(101, moderator)
    return bytes(out)


def canon_base_follow_user(
    pubkey: bytes,
    last_block_hash: bytes,
    difficulty: int,
    timestamp: int,
    target: str,
    user: str,
) -> bytes:
    out = bytearray(_prefix("MsgFollowUser"))
    out += _enc_bytes(2, pubkey)
    out += _enc_bytes(3, last_block_hash)
    out += _enc_u64(4, difficulty)
    out += _enc_u64(6, timestamp)
    out += _enc_str(100, target)
    out += _enc_str(101, user)
    return bytes(out)


def canon_base_unfollow_user(
    pubkey: bytes,
    last_block_hash: bytes,
    difficulty: int,
    timestamp: int,
    target: str,
    user: str,
) -> bytes:
    out = bytearray(_prefix("MsgUnfollowUser"))
    out += _enc_bytes(2, pubkey)
    out += _enc_bytes(3, last_block_hash)
    out += _enc_u64(4, difficulty)
    out += _enc_u64(6, timestamp)
    out += _enc_str(100, target)
    out += _enc_str(101, user)
    return bytes(out)


def canon_base_follow_topic(
    pubkey: bytes,
    last_block_hash: bytes,
    difficulty: int,
    timestamp: int,
    target: str,
    topic: str,
) -> bytes:
    out = bytearray(_prefix("MsgFollowTopic"))
    out += _enc_bytes(2, pubkey)
    out += _enc_bytes(3, last_block_hash)
    out += _enc_u64(4, difficulty)
    out += _enc_u64(6, timestamp)
    out += _enc_str(100, target)
    out += _enc_str(101, topic)
    return bytes(out)


def canon_base_unfollow_topic(
    pubkey: bytes,
    last_block_hash: bytes,
    difficulty: int,
    timestamp: int,
    target: str,
    topic: str,
) -> bytes:
    out = bytearray(_prefix("MsgUnfollowTopic"))
    out += _enc_bytes(2, pubkey)
    out += _enc_bytes(3, last_block_hash)
    out += _enc_u64(4, difficulty)
    out += _enc_u64(6, timestamp)
    out += _enc_str(100, target)
    out += _enc_str(101, topic)
    return bytes(out)


def canon_base_block_post(
    pubkey: bytes,
    last_block_hash: bytes,
    difficulty: int,
    timestamp: int,
    target: str,
) -> bytes:
    out = bytearray(_prefix("MsgBlockPost"))
    out += _enc_bytes(2, pubkey)
    out += _enc_bytes(3, last_block_hash)
    out += _enc_u64(4, difficulty)
    out += _enc_u64(6, timestamp)
    out += _enc_str(100, target)
    return bytes(out)


def canon_base_unblock_post(
    pubkey: bytes,
    last_block_hash: bytes,
    difficulty: int,
    timestamp: int,
    target: str,
) -> bytes:
    out = bytearray(_prefix("MsgUnblockPost"))
    out += _enc_bytes(2, pubkey)
    out += _enc_bytes(3, last_block_hash)
    out += _enc_u64(4, difficulty)
    out += _enc_u64(6, timestamp)
    out += _enc_str(100, target)
    return bytes(out)


def canon_base_block_user(
    pubkey: bytes,
    last_block_hash: bytes,
    difficulty: int,
    timestamp: int,
    target: str,
) -> bytes:
    out = bytearray(_prefix("MsgBlockUser"))
    out += _enc_bytes(2, pubkey)
    out += _enc_bytes(3, last_block_hash)
    out += _enc_u64(4, difficulty)
    out += _enc_u64(6, timestamp)
    out += _enc_str(100, target)
    return bytes(out)


def canon_base_unblock_user(
    pubkey: bytes,
    last_block_hash: bytes,
    difficulty: int,
    timestamp: int,
    target: str,
) -> bytes:
    out = bytearray(_prefix("MsgUnblockUser"))
    out += _enc_bytes(2, pubkey)
    out += _enc_bytes(3, last_block_hash)
    out += _enc_u64(4, difficulty)
    out += _enc_u64(6, timestamp)
    out += _enc_str(100, target)
    return bytes(out)


def canon_base_delete(
    pubkey: bytes,
    last_block_hash: bytes,
    difficulty: int,
    timestamp: int,
    target: str,
) -> bytes:
    out = bytearray(_prefix("MsgDelete"))
    out += _enc_bytes(2, pubkey)
    out += _enc_bytes(3, last_block_hash)
    out += _enc_u64(4, difficulty)
    out += _enc_u64(6, timestamp)
    out += _enc_str(100, target)
    return bytes(out)


def canon_base_send_tokens(
    pubkey: bytes,
    last_block_hash: bytes,
    difficulty: int,
    timestamp: int,
    sender: str,
    target: str,
    amount: int,
) -> bytes:
    out = bytearray(_prefix("MsgSendTokens"))
    out += _enc_bytes(2, pubkey)
    out += _enc_bytes(3, last_block_hash)
    out += _enc_u64(4, difficulty)
    out += _enc_u64(6, timestamp)
    out += _enc_str(100, sender)
    out += _enc_str(101, target)
    out += _enc_u64(102, amount)
    return bytes(out)


def canon_base_report(
    pubkey: bytes,
    last_block_hash: bytes,
    difficulty: int,
    timestamp: int,
    target: str,
    reason: str,
) -> bytes:
    out = bytearray(_prefix("MsgReport"))
    out += _enc_bytes(2, pubkey)
    out += _enc_bytes(3, last_block_hash)
    out += _enc_u64(4, difficulty)
    out += _enc_u64(6, timestamp)
    out += _enc_str(100, target)
    out += _enc_str(101, reason)
    return bytes(out)


def canon_base_upgrade_level(
    pubkey: bytes,
    last_block_hash: bytes,
    difficulty: int,
    timestamp: int,
    level: int,
) -> bytes:
    out = bytearray(_prefix("MsgUpgradeLevel"))
    out += _enc_bytes(2, pubkey)
    out += _enc_bytes(3, last_block_hash)
    out += _enc_u64(4, difficulty)
    out += _enc_u64(6, timestamp)
    out += _enc_u64(100, level)
    return bytes(out)


def canon_base_set_auto_renewal(
    pubkey: bytes,
    last_block_hash: bytes,
    difficulty: int,
    timestamp: int,
    auto_renew: bool,
) -> bytes:
    out = bytearray(_prefix("MsgSetAutoRenewal"))
    out += _enc_bytes(2, pubkey)
    out += _enc_bytes(3, last_block_hash)
    out += _enc_u64(4, difficulty)
    out += _enc_u64(6, timestamp)
    out += _enc_u64(100, 1 if auto_renew else 0)
    return bytes(out)


def canon_base_bridge_burn(
    pubkey: bytes,
    last_block_hash: bytes,
    difficulty: int,
    timestamp: int,
    destination_chain: str,
    destination_address: str,
    amount: int,
) -> bytes:
    out = bytearray(_prefix("MsgBridgeBurn"))
    out += _enc_bytes(2, pubkey)
    out += _enc_bytes(3, last_block_hash)
    out += _enc_u64(4, difficulty)
    out += _enc_u64(6, timestamp)
    out += _enc_str(100, destination_chain)
    out += _enc_str(101, destination_address)
    out += _enc_u64(102, amount)
    return bytes(out)


def canon_signed_with_pow(base: bytes, pow_val: int) -> bytes:
    """
    Insert pow (tag 5) between difficulty (tag 4) and timestamp (tag 6)
    for any of the envelope-based messages.

    Envelope layout in *base* (no pow) is always:
      prefix, tag2(pubkey bytes), tag3(last_block_hash bytes),
      tag4(difficulty uvarint), tag6(timestamp uvarint), payload tags (100+)
    """
    base_arr = bytearray(base)

    def _read_uvarint(buf: bytearray, idx: int) -> tuple[int, int]:
        n = 0
        shift = 0
        while True:
            if idx >= len(buf):
                raise ValueError("uvarint overflow")
            b = buf[idx]
            idx += 1
            n |= (b & 0x7F) << shift
            if not (b & 0x80):
                break
            shift += 7
        return n, idx

    # Skip prefix "mirage.core.v1:MsgX\x00"
    i = 0
    while i < len(base_arr) and base_arr[i] != 0:
        i += 1
    if i < len(base_arr) and base_arr[i] == 0:
        i += 1

    try:
        # tag 2: pubkey bytes
        if i >= len(base_arr) or base_arr[i] != 2:
            raise ValueError("expected tag2")
        i += 1
        length_2, i = _read_uvarint(base_arr, i)
        i += length_2

        # tag 3: last_block_hash bytes
        if i >= len(base_arr) or base_arr[i] != 3:
            raise ValueError("expected tag3")
        i += 1
        length_3, i = _read_uvarint(base_arr, i)
        i += length_3

        # tag 4: difficulty uvarint
        if i >= len(base_arr) or base_arr[i] != 4:
            raise ValueError("expected tag4")
        i += 1
        # skip difficulty value
        _, i = _read_uvarint(base_arr, i)
        tag_4_end = i

        # tag 6: timestamp uvarint (should immediately follow, but
        # fall back to searching from tag_4_end to be robust)
        tag_6_pos = -1
        if tag_4_end < len(base_arr) and base_arr[tag_4_end] == 6:
            tag_6_pos = tag_4_end
        else:
            for j in range(tag_4_end, len(base_arr)):
                if base_arr[j] == 6:
                    tag_6_pos = j
                    break

        if tag_6_pos >= 0:
            pow_bytes = _enc_u64(5, int(pow_val))
            return bytes(base_arr[:tag_6_pos] + pow_bytes + base_arr[tag_6_pos:])

    except Exception:
        # On any unexpected layout, fall through to append-at-end.
        pass

    # Fallback: append pow if we could not safely locate tag4/tag6
    return bytes(base_arr + _enc_u64(5, int(pow_val)))
