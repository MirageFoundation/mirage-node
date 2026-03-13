# Mobile Client: Adding `envelope_nonce` for Replay Protection

## Overview

Starting with chain v1.19.0, every transaction can include an `envelope_nonce` field.
When present and > 0, the chain enforces replay protection — the same nonce cannot be
used twice by the same pubkey. When missing or 0, the chain falls back to legacy
verification (no replay protection). This legacy fallback will be removed in v1.20.0,
at which point `envelope_nonce` becomes mandatory.

**Your goal**: generate a nonce for every transaction, include it in the signed canonical
bytes, and send it to the backend in the HTTP payload.

---

## 1. Generating a Nonce

The nonce is a positive integer. It must be:
- **> 0** (zero is treated as "no nonce" / legacy)
- **Unique per transaction** (for a given pubkey)
- **<= 2^53 - 1** if you represent it as a JS-compatible number (the backend accepts it as a string)

Recommended generation:

```
nonce = (unix_timestamp_nanoseconds) + (random_uint32)
```

Example in pseudocode:
```
timestamp_ns = current_time_milliseconds() * 1_000_000
rand32       = random_uint32()   // 0..0xFFFFFFFF
nonce        = timestamp_ns + rand32
if nonce <= 0 or nonce > 2^53-1:
    nonce = current_time_milliseconds() * 1000 + (random(0..999)) + 1
```

Swift example:
```swift
func generateEnvelopeNonce() -> UInt64 {
    let tsNs = UInt64(Date().timeIntervalSince1970 * 1_000_000_000)
    let rand = UInt64(arc4random())
    let nonce = tsNs + rand
    guard nonce > 0, nonce <= (1 << 53) - 1 else {
        return UInt64(Date().timeIntervalSince1970 * 1000) * 1000 + UInt64(arc4random_uniform(999)) + 1
    }
    return nonce
}
```

Kotlin example:
```kotlin
fun generateEnvelopeNonce(): Long {
    val tsNs = System.currentTimeMillis() * 1_000_000L
    val rand = (Math.random() * 0xFFFFFFFFL).toLong() and 0xFFFFFFFFL
    val nonce = tsNs + rand
    return if (nonce > 0 && nonce <= (1L shl 53) - 1) nonce
    else System.currentTimeMillis() * 1000 + (0..999).random() + 1
}
```

---

## 2. Including Nonce in Canonical Bytes

Canonical bytes are what you sign. They follow this structure:

```
prefix || tag2(pubkey) || tag3(block_hash) || tag4(difficulty) || tag5(pow) || tag6(timestamp) || tag7(nonce) || tag100+(payload...)
```

**Tag 7 is the nonce.** It goes right after tag 6 (timestamp), before any payload tags (100+).

### Encoding Rules

Each field is encoded as:

| Type | Encoding |
|---|---|
| bytes | `[tag_byte] + uvarint(length) + raw_bytes` |
| string | `[tag_byte] + uvarint(length) + utf8_bytes` |
| uint64 | `[tag_byte] + uvarint(value)` |

`uvarint` is standard unsigned variable-length integer encoding (same as protobuf).

### Tag 7 Encoding

Tag 7 is a uint64:
```
byte(7) + uvarint(nonce_value)
```

### Full Canonical Byte Order

The prefix is always: `"mirage.core.v1:" + MsgName + "\0"`

For **every** message type, the envelope portion is identical:

| Tag | Field | Type | Notes |
|-----|-------|------|-------|
| 2 | `envelope_pubkey` | bytes | 33-byte compressed secp256k1 |
| 3 | `envelope_block_hash` | bytes | recent block hash |
| 4 | `envelope_difficulty` | uint64 | PoW difficulty (0 for subscribers) |
| 5 | `envelope_pow` | uint64 | PoW proof (0 for subscribers) |
| 6 | `envelope_timestamp` | uint64 | millisecond unix timestamp |
| **7** | **`envelope_nonce`** | **uint64** | **NEW — the nonce you generated** |

Then payload fields starting at tag 100+. These vary by message type:

| Message | Payload Tags |
|---------|-------------|
| MsgPost | 100:target, 101:topic, 102:title, 103:content, 104:tag, 105:media (repeated) |
| MsgEdit | 100:target, 101:topic, 102:title, 103:content, 104:tag, 105:override, 106:media (repeated) |
| MsgAnnotate | 100:appendix, 101:topic, 102:title, 103:content, 104:tag, 105:override, 106:media (repeated) |
| MsgVote | 100:target, 101:direction (uint32) |
| MsgSetUsername | 100:target, 101:username |
| MsgSetBiography | 100:target, 101:biography |
| MsgEnableAgent | 100:target, 101:agent |
| MsgDisableAgent | 100:target, 101:agent |
| MsgSetAgents | 100:target, 101:agents (repeated) |
| MsgFollowUser | 100:target, 101:user |
| MsgUnfollowUser | 100:target, 101:user |
| MsgFollowTopic | 100:target, 101:topic |
| MsgUnfollowTopic | 100:target, 101:topic |
| MsgBlockPost | 100:target |
| MsgUnblockPost | 100:target |
| MsgBlockUser | 100:target |
| MsgUnblockUser | 100:target |
| MsgBlockTopic | 100:target, 101:topic |
| MsgUnblockTopic | 100:target, 101:topic |
| MsgDelete | 100:target |
| MsgDeleteUser | 100:target |
| MsgSendTokens | 100:sender, 101:target, 102:amount (uint64) |
| MsgReport | 100:target, 101:reason |
| MsgUpgradeLevel | 100:level (uint64) |
| MsgSetAutoRenewal | 100:auto_renew (uint64: 0 or 1) |
| MsgAward | 100:target, 101:award_type |
| MsgBridgeBurn | 100:destination_chain, 101:destination_address, 102:amount (uint64) |

### Concrete Example: MsgPost

```
canonical_bytes =
    b"mirage.core.v1:MsgPost\0"       // prefix
    + byte(2)  + len_prefixed(pubkey)  // 33-byte compressed pubkey
    + byte(3)  + len_prefixed(block_hash)
    + byte(4)  + uvarint(difficulty)
    + byte(5)  + uvarint(pow_proof)
    + byte(6)  + uvarint(timestamp_ms)
    + byte(7)  + uvarint(nonce)        // <-- NEW
    + byte(100) + len_prefixed(target)
    + byte(101) + len_prefixed(topic)
    + byte(102) + len_prefixed(title)
    + byte(103) + len_prefixed(content)
    + byte(104) + len_prefixed(tag)
    // for each media URL:
    + byte(105) + len_prefixed(media_url)
```

### PoW Canonical Bytes

If your app computes PoW client-side, the PoW base bytes also include tag 7 (nonce)
between tag 6 and tag 100. The only difference from signing bytes is that tag 5
(envelope_pow) is omitted in the PoW base (since that's what you're computing).

---

## 3. Sending Nonce to the Backend

Add `envelope_nonce` as a **string** to every HTTP POST payload:

```json
{
    "pubkey": "<base64>",
    "signature": "<base64>",
    "timestamp": 1710000000000,
    "last_block_hash": "abc123...",
    "pow_difficulty": 5,
    "pow": 12345,
    "envelope_nonce": "1710000000000042",
    "target": "...",
    "content": "..."
}
```

Key rules:
- The value can be a JSON number or a string (both work)
- It must be the **exact same value** used in the canonical bytes you signed
- It must be **> 0** (sending `0` will be rejected with HTTP 400)

---

## 4. Signing Flow Summary

```
1. Generate nonce = generateEnvelopeNonce()
2. Build canonical_bytes with tag 7 = nonce
3. digest = sha256(canonical_bytes)
4. signature = secp256k1_sign(digest, private_key)  // 64-byte R||S
5. POST to backend with envelope_nonce = str(nonce)
```

---

## 5. Verifying It Works

### Quick Test

After implementing, try any transaction (e.g., a vote or post). If the backend returns
HTTP 200 with a `tx_hash`, the nonce was accepted.

### Replay Test

Send the exact same signed payload twice (same nonce, same signature, same everything).
The first request should succeed (200). The second should fail with an error containing
`"envelope replay"` — this confirms replay protection is active.

### Common Errors

| Error | Cause |
|-------|-------|
| `"envelope_nonce must be > 0"` | You sent `"0"` or a negative number |
| `"invalid envelope_nonce"` | Not a valid integer string |
| `"envelope replay: nonce already used"` | You reused a nonce (expected on replay test) |
| Signature verification failed | Tag 7 in canonical bytes doesn't match the `envelope_nonce` in the payload, or tag 7 is in the wrong position |

### Debugging Checklist

1. Is the nonce > 0?
2. Is tag 7 placed between tag 6 (timestamp) and tag 100 (first payload field)?
3. Is tag 7 encoded as `byte(7) + uvarint(nonce_value)`?
4. Is the same nonce value in both the signed canonical bytes AND the HTTP payload?
5. Is `envelope_nonce` sent as a string in the JSON payload?

---

## 6. Timeline

- **v1.19.0**: `envelope_nonce` was optional with legacy fallback.
- **v1.20.0 (current)**: `envelope_nonce` is **mandatory**. Requests without it are
  rejected with HTTP 400. All clients must include a valid nonce in every request.
