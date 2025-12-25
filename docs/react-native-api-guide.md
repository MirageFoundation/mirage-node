## Mirage React Native API Guide

This document is a complete, implementation-oriented guide for building a Mirage client in React Native.

It covers:
- All backend HTTP endpoints exposed by `web/backend/`
- Exact request and response shapes (as implemented)
- How to create identities (mnemonic, keys, address)
- How to build canonical bytes and signatures (no placeholders)
- How to compute PoW (free tier)
- End-to-end flows: create account, set username, post, comment, vote, follow, block, delete, send tokens, subscribe


NODE_DOMAIN can be any Mirage server, it should be changeable at runtime.
For now: use `mirage.vote` (this is subject to change once we go live)

Implementation note: in the app, keep a list of base URLs and fail over on network errors and 5xx.

---

## Base URLs

- **API base**: `https://<NODE_DOMAIN>/api`
- **Local docker (default)**: `http://127.0.0.1:8080/api` (depends on your deployment)

All endpoints below are relative to `/api`.

---

## High-level architecture (what your RN app talks to)

- **Backend HTTP API (this doc)**: provides read models from the indexer DB and accepts “meta-signed” write requests.
- **Chain gRPC gateway (optional)**: `/mirage/core/v1/*` exists, but the RN app should generally use the backend read endpoints because they join and shape content for feeds.

---

## Identity, keys, and addresses (Cosmos standard)

### Mnemonic generation

Use BIP39 to generate a 12 or 24-word mnemonic. Store it securely on-device.

Important: the mnemonic (seed phrase) must never be sent to the backend.

### Deriving the Mirage account key

Use the Cosmos standard derivation:
- **Curve**: secp256k1
- **BIP44 coin type**: 118
- **Derivation path**: `m/44'/118'/0'/0/0`
- **Bech32 prefix**: `mirage`

From that derivation you will have:
- **private key**: 32 bytes
- **public key**: secp256k1 point
- **compressed pubkey**: 33 bytes, starts with `0x02` or `0x03` (this is what Mirage uses everywhere)

### Deriving the `mirage1...` address from a compressed pubkey

Mirage uses the Cosmos standard address derivation:

1. `sha256(compressed_pubkey_33)` -> 32 bytes
2. `ripemd160(sha256_result)` -> 20 bytes
3. Bech32-encode that 20-byte value with HRP `mirage` -> `mirage1...`

This is implemented in the repo at `indexer/address_utils.py` (`addr_from_pubkey`).

### React Native: reference libraries for key derivation and addresses

Use these libraries (or equivalents):
- `@scure/bip39` for mnemonic and seed
- `@scure/bip32` for BIP32 derivation
- `@noble/secp256k1` for pubkey and signatures
- `@noble/hashes` (`sha256`, `ripemd160`) for address hashing
- `bech32` for bech32 encoding

Minimal example (derive address from a mnemonic using the standard Cosmos path):

```ts
import { mnemonicToSeedSync } from '@scure/bip39';
import { HDKey } from '@scure/bip32';
import * as secp from '@noble/secp256k1';
import { sha256 } from '@noble/hashes/sha256';
import { ripemd160 } from '@noble/hashes/ripemd160';
import { bech32 } from 'bech32';

export function derivePrivkeyFromMnemonic(mnemonic: string): Uint8Array {
  const seed = mnemonicToSeedSync(mnemonic); // 64 bytes
  const hd = HDKey.fromMasterSeed(seed);
  const child = hd.derive("m/44'/118'/0'/0/0");
  if (!child.privateKey) throw new Error('missing privateKey');
  return child.privateKey; // 32 bytes
}

export function mirageAddressFromPrivkey(privKey32: Uint8Array): string {
  const pub33 = secp.getPublicKey(privKey32, true); // compressed
  const h1 = sha256(pub33);
  const h2 = ripemd160(h1); // 20 bytes
  const words = bech32.toWords(h2);
  return bech32.encode('mirage', words);
}
```

### React Native: base64 helpers

In RN, prefer using `Buffer` (via `buffer` polyfill) for base64:

```ts
import { Buffer } from 'buffer';

export function b64encode(u8: Uint8Array): string {
  return Buffer.from(u8).toString('base64');
}
export function b64decode(s: string): Uint8Array {
  return new Uint8Array(Buffer.from(s, 'base64'));
}
```

---

## Meta-signed transactions: the core client protocol

Mirage write endpoints accept JSON with:
- an **envelope** (pubkey, signature, timestamp, and optionally PoW inputs)
- **message-specific fields** (post content, vote direction, etc.)

The backend relays your request to the chain by wrapping it in a real Cosmos SDK transaction. The chain verifies your signature using deterministic “canonical bytes”.

### Envelope fields (sent in JSON)

These appear on almost every `/api/core/*` write endpoint:

- **pubkey**: base64 of the **33-byte compressed** secp256k1 pubkey
- **signature**: base64 of the **64-byte compact signature** `r || s`
- **timestamp**: integer, **milliseconds since epoch** (must be close to chain time)
- **last_block_hash**: hex string (lowercase recommended). Required for free-tier PoW, still recommended for paid users.
- **pow_difficulty**: integer. Required for free-tier PoW, must be `0` for paid users.
- **pow**: integer. Required for free-tier PoW, must be `0` for paid users.

### Replay protection: `timestamp` is mandatory

The chain enforces that `envelope_timestamp`:
- is not older than `max_envelope_age` seconds (chain param, default 60 seconds)
- is not too far in the future (small skew allowed)

If you see errors about timestamp being too old or in the future, the device clock is wrong.

### Free-tier vs paid-tier rules

Mirage uses two modes:

- **Free tier (level 0)**: must provide valid PoW for most actions.
- **Paid tier (level >= 1)**: must not use PoW. Gas is covered by the user’s reserve (escrow).

How to detect:
- Call `GET /api/get_user_status?address=mirage1...` and check `user_level`.

Rule summary:
- **If `user_level == 0`**: include `last_block_hash`, set `pow_difficulty` to current required difficulty, compute `pow`.
- **If `user_level >= 1`**: set `pow_difficulty = 0` and `pow = 0`.

---

## Canonical bytes: exactly what you sign

This is the most important section. Mirage does NOT sign JSON and does NOT sign protobuf bytes.

Canonical bytes are defined in:
- `shared/canon.py` (Python reference)
- `blockchain/app/ante_metasig.go` (chain verification)

### Canonical byte layout

Canonical bytes are:

1. **Prefix**: ASCII bytes

`"mirage.core.v1:" + <MsgName> + "\x00"`

Example prefix for a post:
- `mirage.core.v1:MsgPost\x00`

2. **Fields** in ascending tag order (proto field numbers), encoded as:

- **tag byte**: single byte equal to the field number (example: tag 2 is `0x02`)
- then:
  - for **bytes** and **string**: `uvarint(length)` + raw bytes
  - for **uint64/int32/bool**: `uvarint(value)`

3. **Authority (tag 1) is NOT included** in the canonical bytes.
4. **Signature (tag 10) is NOT included** in the canonical bytes.

### Unsigned varint (uvarint) encoding

Uvarint is standard base-128 varint. Pseudocode:

```javascript
function uvarint(n) {
  n = BigInt(n);
  const out = [];
  while (true) {
    const b = Number(n & 0x7Fn);
    n >>= 7n;
    if (n !== 0n) out.push(b | 0x80);
    else { out.push(b); break; }
  }
  return Uint8Array.from(out);
}
```

### Vote direction encoding gotcha (critical)

`direction` is `int32` in protobuf, but in canonical bytes it is encoded as:

- `uvarint(uint32(direction))`

That means:
- `1` -> `1`
- `0` -> `0`
- `-1` -> `4294967295`

If you do not match this, signatures will fail.

### Signed bytes vs PoW base bytes

For PoW and signature, we use two closely related byte streams:

- **PoW base bytes**: envelope fields `2,3,4,6` and payload fields, but **no tag 5**.
- **Signed bytes**: same as PoW base, but insert `envelope_pow` as **tag 5** between tag 4 and tag 6.

This is implemented by `canon_signed_with_pow(base, pow)` in `shared/canon.py`.

Important: signed bytes include tag 5 even if `pow == 0`.

### Signature algorithm (exact)

- **Hash**: SHA-256 over the canonical **signed bytes**
- **Signature**: ECDSA over secp256k1
- **Format**: 64-byte compact `r (32 bytes big-endian) || s (32 bytes big-endian)`
- **Low-S normalization**: required (enforced by the chain)

### Base64 encoding (exact)

`pubkey` and `signature` in JSON are:
- standard base64 (not hex)
- padding allowed/expected (`=` may appear)

---

## Proof of Work (PoW) for free tier

PoW is defined in `blockchain/app/ante_pow.go` and mirrored in the backend.

### PoW digest

Given:
- `base = canonical bytes without tag 5`
- `pow = integer proof`
- `last_block_hash = hex string`

Compute:

- `password = base + b":" + uvarint(pow)`
- `salt = bytes.fromhex(last_block_hash)`
- `digest = Argon2id(password, salt, t=1, m=4096 KiB, p=1, outLen=32)`

Condition:
- `leading_zero_bits(digest) >= required_bits`

For free tier, `required_bits` is effectively:
- at least the chain’s current dynamic difficulty
- and also respects a short allowance window after difficulty changes

Practical client rule:
- Always use `pow_difficulty` from `GET /api/get_parameters` as your declared difficulty and required threshold.

### Leading zero bits

Count leading zero bits in the digest:

```javascript
function leadingZeroBits(bytes) {
  let total = 0;
  for (const b of bytes) {
    if (b === 0) { total += 8; continue; }
    for (let i = 7; i >= 0; i--) {
      if (((b >> i) & 1) === 0) total++;
      else return total;
    }
  }
  return total;
}
```

---

## Canonical payload tags per message (what the RN app signs)

These match `shared/canon.py` and the chain ante handler.

All messages include envelope fields:
- **2**: `envelope_pubkey` (bytes, 33)
- **3**: `envelope_block_hash` (bytes, raw bytes of `last_block_hash` hex)
- **4**: `envelope_difficulty` (uvarint)
- **5**: `envelope_pow` (uvarint) (signed bytes only, inserted between 4 and 6)
- **6**: `envelope_timestamp` (uvarint, ms since epoch)

### `MsgSetUsername`

- **100**: `target` (string, must equal your derived `mirage1...` address)
- **101**: `username` (string)

### `MsgPost` (post or comment)

- **100**: `target` (string)
  - empty string for root posts
  - parent post txhash (64 hex) for comments
- **101**: `topic` (string)
  - required for root posts, must be empty for comments
- **102**: `title` (string) (posts only, empty for comments)
- **103**: `content` (string)
- **104**: `tag` (string, one of: `""`, `sensitive`, `porn`, `gore`, `violence`, `death`)

### `MsgEdit`

- **100**: `target` (string) (empty for root posts, set for comments)
- **101**: `topic` (string) (required for root posts, empty for comments)
- **102**: `title` (string)
- **103**: `content` (string)
- **104**: `tag` (string)
- **105**: `override` (string, txhash being edited, 64 hex)

### `MsgVote`

- **100**: `target` (string, txhash 64 hex)
- **101**: `direction` (uvarint of uint32(int32(direction))) (1, 0, -1)

### `MsgFollowModerator`

- **100**: `target` (string, must equal your derived `mirage1...` address)
- **101**: `moderator` (string, `mirage1...`)

### `MsgUnfollowModerator`

- **100**: `target` (string, must equal your derived `mirage1...` address)
- **101**: `moderator` (string, `mirage1...`)

### `MsgFollowUser`

- **100**: `target` (string, must equal your derived `mirage1...` address)
- **101**: `user` (string, `mirage1...`)

### `MsgUnfollowUser`

- **100**: `target` (string, must equal your derived `mirage1...` address)
- **101**: `user` (string, `mirage1...`)

### `MsgFollowTopic`

- **100**: `target` (string, must equal your derived `mirage1...` address)
- **101**: `topic` (string, lowercase topic)

### `MsgUnfollowTopic`

- **100**: `target` (string, must equal your derived `mirage1...` address)
- **101**: `topic` (string, lowercase topic)

### `MsgBlockPost`

- **100**: `target` (string, txhash 64 hex)

### `MsgUnblockPost`

- **100**: `target` (string, txhash 64 hex)

### `MsgBlockUser`

- **100**: `target` (string, `mirage1...`)

### `MsgUnblockUser`

- **100**: `target` (string, `mirage1...`)

### `MsgDelete`

- **100**: `target` (string, txhash 64 hex)

### `MsgSendTokens`

- **100**: `sender` (string, must equal your derived `mirage1...` address)
- **101**: `target` (string, `mirage1...`)
- **102**: `amount` (uvarint, integer umirage)

### `MsgUpgradeLevel` (paid tiers only)

- **100**: `level` (uvarint, 1..3)

Rules:
- `pow_difficulty` must be `0`
- `pow` must be `0`

### `MsgSetAutoRenewal` (paid tiers only)

- **100**: `auto_renew` (uvarint, `1` for true, `0` for false)

Rules:
- `pow_difficulty` must be `0`
- `pow` must be `0`

---

## React Native implementation reference (JS/TS)

This is a minimal “signing core” you can port into RN. Use it to build any request.

### Canonical encoding helpers

```ts
import { sha256 } from '@noble/hashes/sha256';
import { bytesToHex } from '@noble/hashes/utils';

export function uvarint(n: number | bigint): Uint8Array {
  let x = BigInt(n);
  const out: number[] = [];
  while (true) {
    const b = Number(x & 0x7fn);
    x >>= 7n;
    if (x !== 0n) out.push(b | 0x80);
    else { out.push(b); break; }
  }
  return Uint8Array.from(out);
}

function concat(...parts: Uint8Array[]) {
  const total = parts.reduce((s, p) => s + p.length, 0);
  const out = new Uint8Array(total);
  let off = 0;
  for (const p of parts) { out.set(p, off); off += p.length; }
  return out;
}

function tagByte(tag: number) {
  return Uint8Array.from([tag & 0xff]);
}

function encBytes(tag: number, b: Uint8Array) {
  return concat(tagByte(tag), uvarint(b.length), b);
}

function encString(tag: number, s: string) {
  const b = new TextEncoder().encode(s ?? '');
  return concat(tagByte(tag), uvarint(b.length), b);
}

function encU64(tag: number, v: number | bigint) {
  return concat(tagByte(tag), uvarint(v));
}

export function prefix(msgName: string) {
  return new TextEncoder().encode(`mirage.core.v1:${msgName}\x00`);
}

// Insert pow (tag 5) between difficulty(tag 4) and timestamp(tag 6) in the canonical base.
// Use this for signed bytes in ALL messages (pow may be 0).
export function canonSignedWithPow(base: Uint8Array, pow: number | bigint) {
  // Find the first byte 0x00 after the prefix and then parse tags 2,3,4 to locate tag6.
  // For simplicity and correctness, mirror the Python behavior: search for the first tag 6 after tag 4.
  let i = 0;
  while (i < base.length && base[i] !== 0) i++;
  if (i < base.length && base[i] === 0) i++;

  function readUvarint(buf: Uint8Array, idx: number): [bigint, number] {
    let n = 0n;
    let shift = 0n;
    while (true) {
      if (idx >= buf.length) throw new Error('uvarint overflow');
      const b = BigInt(buf[idx++]);
      n |= (b & 0x7fn) << shift;
      if ((b & 0x80n) === 0n) break;
      shift += 7n;
    }
    return [n, idx];
  }

  // tag2 bytes
  if (base[i] !== 2) throw new Error('expected tag2');
  i++;
  let len2; [len2, i] = readUvarint(base, i);
  i += Number(len2);
  // tag3 bytes
  if (base[i] !== 3) throw new Error('expected tag3');
  i++;
  let len3; [len3, i] = readUvarint(base, i);
  i += Number(len3);
  // tag4 uvarint
  if (base[i] !== 4) throw new Error('expected tag4');
  i++;
  [, i] = readUvarint(base, i); // skip difficulty value
  const tag4End = i;

  // find tag 6 position
  let tag6Pos = -1;
  if (tag4End < base.length && base[tag4End] === 6) tag6Pos = tag4End;
  else {
    for (let j = tag4End; j < base.length; j++) {
      if (base[j] === 6) { tag6Pos = j; break; }
    }
  }
  if (tag6Pos < 0) {
    // fallback: append (should never happen if base is built correctly)
    return concat(base, encU64(5, pow));
  }
  return concat(base.slice(0, tag6Pos), encU64(5, pow), base.slice(tag6Pos));
}

export function sha256Hex(b: Uint8Array) {
  return bytesToHex(sha256(b));
}
```

### Message-specific canonical base builders

Build **base** bytes without pow (tag 5), then call `canonSignedWithPow(base, pow)` before signing.

```ts
export function canonBaseSetUsername(args: {
  pubkey33: Uint8Array;
  lastBlockHashBytes: Uint8Array;
  difficulty: number;
  timestampMs: number;
  target: string; // must equal derived address
  username: string;
}) {
  return concat(
    prefix('MsgSetUsername'),
    encBytes(2, args.pubkey33),
    encBytes(3, args.lastBlockHashBytes),
    encU64(4, args.difficulty),
    encU64(6, args.timestampMs),
    encString(100, args.target),
    encString(101, args.username),
  );
}

export function canonBasePost(args: {
  pubkey33: Uint8Array;
  lastBlockHashBytes: Uint8Array;
  difficulty: number;
  timestampMs: number;
  target: string; // '' for root post, parent txhash for comment
  topic: string;  // required for root, '' for comment
  title: string;
  content: string;
  tag: string;    // '' or allowed tags
}) {
  return concat(
    prefix('MsgPost'),
    encBytes(2, args.pubkey33),
    encBytes(3, args.lastBlockHashBytes),
    encU64(4, args.difficulty),
    encU64(6, args.timestampMs),
    encString(100, args.target ?? ''),
    encString(101, args.topic ?? ''),
    encString(102, args.title ?? ''),
    encString(103, args.content ?? ''),
    encString(104, args.tag ?? ''),
  );
}

export function canonBaseVote(args: {
  pubkey33: Uint8Array;
  lastBlockHashBytes: Uint8Array;
  difficulty: number;
  timestampMs: number;
  target: string; // txhash
  direction: number; // 1, 0, -1
}) {
  const u32 = args.direction < 0 ? (args.direction >>> 0) : args.direction; // -1 -> 4294967295
  return concat(
    prefix('MsgVote'),
    encBytes(2, args.pubkey33),
    encBytes(3, args.lastBlockHashBytes),
    encU64(4, args.difficulty),
    encU64(6, args.timestampMs),
    encString(100, args.target),
    encU64(101, u32),
  );
}
```

For the remaining messages, follow the “payload tag” mapping section above.

### Signing (noble-secp256k1)

Use `@noble/secp256k1` (or an equivalent secp256k1 library) and ensure low-S signatures.

Pseudo:

```ts
import * as secp from '@noble/secp256k1';
import { sha256 } from '@noble/hashes/sha256';

export async function signCanonical(privKey32: Uint8Array, signedBytes: Uint8Array): Promise<Uint8Array> {
  const digest = sha256(signedBytes);
  // Prefer an API that returns compact 64-byte signature and enforces lowS.
  // In noble, ensure you enable lowS normalization.
  const sig = await secp.sign(digest, privKey32, { der: false, lowS: true });
  return sig; // 64 bytes r||s
}

export function compressedPubkey(privKey32: Uint8Array): Uint8Array {
  return secp.getPublicKey(privKey32, true); // 33 bytes
}
```

---

## Read endpoints (GET/POST)

### `GET /get_parameters`

Used for:
- newest `last_block_hash` for PoW
- current PoW difficulty
- optional quick balance read

Query:
- `address` (optional): `mirage1...`

Response:
- `last_block_hash`: string (hex)
- `pow_difficulty`: integer
- `balance`: integer (optional, umirage)

Curl:

```bash
curl "https://<NODE_DOMAIN>/api/get_parameters"
curl "https://<NODE_DOMAIN>/api/get_parameters?address=mirage1..."
```

### `GET /get_config`

Static-ish config snapshot (safe to cache in the app).

Response:
- chain params: `max_username_size`, `min_username_size`, `max_topic_size`, `min_topic_size`, `subscription_period`, `mint_interval`, `tiers`
- difficulty snapshot: `pow_difficulty`, `pow_message_count`, `pow_calm_sequence`, `pow_last_change_height`, `current_height`, `block_time`
- validator info for this backend: `validator_account_address`, `validator_operator_address`, `validator_consensus_address`, `validator_moniker`

Curl:

```bash
curl "https://<NODE_DOMAIN>/api/get_config"
curl "https://<NODE_DOMAIN>/api/get_config?address=mirage1..."
```

### `GET /get_user_status`

Query:
- `address` (required): `mirage1...`

Response:
- `username`: string|null
- `balance`: int (umirage)
- `user_level`: int
- `subscription_expiry`: int (unix seconds or 0)
- `auto_renew`: bool
- `reserve_funds`: int (umirage)
- `profile_registered_at`: int|null (unix seconds)
- `recent_votes`: array of `{ target, direction, timestamp }`

Curl:

```bash
curl "https://<NODE_DOMAIN>/api/get_user_status?address=mirage1..."
```

### `GET /get_profile`

Query:
- `address` (required): `mirage1...`

Response (chain profile, full lists):
- `owner`, `username`, `level`, `created_at`, `subscription_expiry`, `auto_renew`, `reserve_funds`
- `is_moderator`, `biography`, `avatar`, `banner`
- lists: `followed_users`, `followed_topics`, `followed_moderators`, `blocked_users`, `blocked_posts`, `quality_posts`

Curl:

```bash
curl "https://<NODE_DOMAIN>/api/get_profile?address=mirage1..."
```

### `GET /get_user_followed`

Query:
- `address` (required)

Response:
- `followed_moderators`: string[]
- `followed_topics`: string[]
- `followed_users`: string[]

Curl:

```bash
curl "https://<NODE_DOMAIN>/api/get_user_followed?address=mirage1..."
```

### `GET /get_user_blocked`

Query:
- `address` (required)

Response:
- `blocked_posts`: string[] (txhash)
- `blocked_users`: string[] (mirage1...)

Curl:

```bash
curl "https://<NODE_DOMAIN>/api/get_user_blocked?address=mirage1..."
```

### `GET /get_blocked_users`

Query:
- `address` (required)

Response:
- `blocked_users`: string[] (only the user’s own, not inherited from followed moderators)

Curl:

```bash
curl "https://<NODE_DOMAIN>/api/get_blocked_users?address=mirage1..."
```

### `GET /get_preferences`

Query:
- `address` (required)

Response:
- `topics`: array of `{ topic, weight }`
- `authors`: array of `{ user, weight }`

Curl:

```bash
curl "https://<NODE_DOMAIN>/api/get_preferences?address=mirage1..."
```

### `GET /get_similar_users`

Query:
- `address` (required)

Response:
- `similar_users`: array of `{ address, username, similarity, shared_dimensions }`

Curl:

```bash
curl "https://<NODE_DOMAIN>/api/get_similar_users?address=mirage1..."
```

### `GET /get_topics`

Query:
- `limit` (optional, max 200)

Response:
- `topics`: array of objects, at minimum includes `topic` and counts/flags (varies)

Curl:

```bash
curl "https://<NODE_DOMAIN>/api/get_topics"
curl "https://<NODE_DOMAIN>/api/get_topics?limit=50"
```

### `GET /search_topics`

Query:
- `q` (required, min 2 chars)
- `limit` (optional, max 50)
- `offset` (optional)

Response:
- `topics`: array of `{ topic, post_count, count, flags, dominant_tag, dominant_ratio }`

Curl:

```bash
curl "https://<NODE_DOMAIN>/api/search_topics?q=ge&limit=20&offset=0"
```

### `GET /search`

Query:
- `q` (required)
- `type` (optional): `topics` | `users` | `posts`
- `limit` (optional, max 50)
- `offset` (optional)
- `address` (optional viewer address for blocked filtering)

Response:
- `query`, `search_type`
- `topics`: array
- `users`: array
- `posts`: array (post-shaped objects)
- `has_more_topics`, `has_more_users`, `has_more_posts`

Curl:

```bash
curl "https://<NODE_DOMAIN>/api/search?q=%40alice"
curl "https://<NODE_DOMAIN>/api/search?q=%23general"
curl "https://<NODE_DOMAIN>/api/search?q=hello&limit=10&offset=0"
```

### `GET /get_posts`

Query:
- `limit` (optional, max 100)
- `page` (optional)
- `topic` (optional, topic name or `all`)
- `address` (optional viewer address for blocked filtering and user_vote)
- `allowed_tags` (optional comma-separated, default `sensitive`)
- `feed` (optional): `home` | `following`
- `by` (optional sort mode, default `magic`)

Response:
- `posts`: array of:
  - `post_id` (txhash lowercase)
  - `user_id` (owner address)
  - `username` (string)
  - `timestamp` (int)
  - `topic`
  - `root_topic`
  - `root_post_id`
  - `title`
  - `content`
  - `tag`
  - `edited_at` (int, 0 if never edited)
  - `thumbnail` (string)
  - `points` (number, sum of user_weight contributions)
  - `comments` (int)
  - `user_vote` (int: -1,0,1, viewer's vote direction)
  - `user_weight` (number, viewer's weighted contribution to this post)
- pagination: `total`, `page`, `limit`, `has_more`
- optional: `latest_inbox_timestamp`

Note on vote display: to show the user their perceived contribution (+1/-1), calculate:
`displayPoints = Math.round(points - user_weight + user_vote)`

Curl:

```bash
curl "https://<NODE_DOMAIN>/api/get_posts?limit=25&page=1"
curl "https://<NODE_DOMAIN>/api/get_posts?topic=general&limit=25&page=1"
curl "https://<NODE_DOMAIN>/api/get_posts?feed=home&address=mirage1...&limit=25&page=1"
curl "https://<NODE_DOMAIN>/api/get_posts?feed=following&address=mirage1...&limit=25&page=1"
```

### `GET /get_user_posts`

Query:
- `owner` (required)
- `address` (optional viewer address)
- `type` (optional): `submissions` | `comments`
- `page` (optional)
- `limit` (optional, max 50)

Response:
- `posts`: array of post-shaped objects (similar to `/get_posts`)
- `page`, `limit`, `has_more`, `total`

Curl:

```bash
curl "https://<NODE_DOMAIN>/api/get_user_posts?owner=mirage1...&type=submissions&page=1&limit=10"
curl "https://<NODE_DOMAIN>/api/get_user_posts?owner=mirage1...&type=comments&page=1&limit=10"
```

### `GET /get_comments`

Query:
- `post_id` (required root txhash)
- `address` (optional viewer address)

Response:
- `root`: post-shaped object + `user_vote` + `user_weight`
- `children`: recursive tree of objects like `root` plus `children`
- optional: `latest_inbox_timestamp`

Curl:

```bash
curl "https://<NODE_DOMAIN>/api/get_comments?post_id=<root_txhash>"
curl "https://<NODE_DOMAIN>/api/get_comments?post_id=<root_txhash>&address=mirage1..."
```

### `GET /get_root_post_id`

Query:
- `comment_id` (required)

Response:
- `root_post_id`
- `comment_id`

Curl:

```bash
curl "https://<NODE_DOMAIN>/api/get_root_post_id?comment_id=<comment_txhash>"
```

### `GET /get_comment_context`

Query:
- `comment_id` (required)
- `address` (optional viewer)
- `max_depth` (optional, 1..10)

Response:
- `context`: array of parent posts (post-shaped)
- `comment_id`

Curl:

```bash
curl "https://<NODE_DOMAIN>/api/get_comment_context?comment_id=<comment_txhash>&max_depth=6"
```

### `GET /get_inbox`

Query:
- `address` (required)
- `page` (optional)
- `limit` (optional, max 100)

Response:
- `replies`: array of `{ reply_id, reply_owner, reply_username, reply_content, reply_timestamp, parent_id, parent_content, parent_owner, root_post_id }`
- `total`, `page`, `limit`, `has_more`
- `_perf_ms`, `_query_ms` (debug/perf fields)

Curl:

```bash
curl "https://<NODE_DOMAIN>/api/get_inbox?address=mirage1...&page=1&limit=25"
```

### `GET /get_address_from_username`

Query:
- `username` (required)

Response:
- `{ exists: bool, address: string|null, username: string }`

Curl:

```bash
curl "https://<NODE_DOMAIN>/api/get_address_from_username?username=alice"
```

Bulk POST:

```bash
curl -X POST "https://<NODE_DOMAIN>/api/get_address_from_username" \
  -H "Content-Type: application/json" \
  -d '{"usernames":["alice","bob"]}'
```

### `GET /get_username_from_address`

Query:
- `address` (required)

Response:
- `{ username: string|null, address: string }`

Curl:

```bash
curl "https://<NODE_DOMAIN>/api/get_username_from_address?address=mirage1..."
```

Bulk POST:

```bash
curl -X POST "https://<NODE_DOMAIN>/api/get_username_from_address" \
  -H "Content-Type: application/json" \
  -d '{"addresses":["mirage1...","mirage1..."]}'
```

### `GET /get_users`

Query:
- `limit` (optional, max 500)
- `page` (optional)
- `has_username` (optional): true/false

Response:
- `{ users: [{ address, username }], page, limit, has_more, total }`

Curl:

```bash
curl "https://<NODE_DOMAIN>/api/get_users?limit=100&page=1&has_username=true"
```

### `GET /get_tx_status`

Unified transaction status endpoint with type-specific enrichment.

Query:
- `hash` (required 64 hex tx hash)

Response:
- if missing: `{ "found": false }`
- if found:
  - `found`: true
  - `tx_hash`: the transaction hash
  - `height`: block height
  - `code`: result code (0 = success)
  - `success`: boolean
  - `indexed`: boolean, whether indexer has processed that height
  - `tx_type`: detected type ("vote", "post", "profile", "follow_user", "follow_topic", "unknown")
  - `details`: type-specific data (only when indexed and success)
    - For votes: `{ owner, target, user_vote, user_weight, target_points }`
    - For posts: `{ post_id, topic, title }`
    - For profiles: `{ owner, username }`
    - For follows: `{ owner, target }` or `{ owner, topic }`
  - `error_details`: present when `code != 0`

Polling pattern: wait 4s after tx submission, then poll every 2s, up to 5 attempts.

Curl:

```bash
curl "https://<NODE_DOMAIN>/api/get_tx_status?hash=<tx_hash_64hex>"
```

### `GET /get_network_stats`

Response:
- `server_balance`
- `block_time`
- `pow_difficulty`, `pow_message_count`, `pow_calm_sequence`, `pow_last_change_height`, `current_height`
- `difficulty_history`: array of `{ height, difficulty, msg_count, timestamp }`

Curl:

```bash
curl "https://<NODE_DOMAIN>/api/get_network_stats"
```

### `GET /get_circulation_stats`

Response:
- `total_supply`
- `top_accounts`: array of `{ address, username, balance }`

Curl:

```bash
curl "https://<NODE_DOMAIN>/api/get_circulation_stats"
```

### `GET /get_peers`

Response:
- `peers`: array of `{ ip, moniker }`

Curl:

```bash
curl "https://<NODE_DOMAIN>/api/get_peers"
```

### `GET /leaderboard`

Query:
- `days` (optional 1..30)
- `limit` (optional, max 500)
- `page` (optional)
- weights: `comment_weight`, `post_weight`, `points_received_weight`, `votes_cast_weight`, `deleted_post_weight`, `deleted_comment_weight`

Response:
- `since_ts`, `days`, `limit`, `page`, `total`
- `leaderboard`: array of `{ rank, address, username, post_count, comment_count, votes_cast, points_received, deleted_post_count, deleted_comment_count, score }`

Curl:

```bash
curl "https://<NODE_DOMAIN>/api/leaderboard?days=7&limit=100&page=1"
```

### `GET /get_reports` (admin only)

Query:
- `address` (required, must be admin level)
- `limit` (optional, max 500)

Response:
- `{ reports: [{ id, reporter_owner, reporter_username, target, reason, timestamp, post_owner, post_username, title, content }] }`

Curl:

```bash
curl "https://<NODE_DOMAIN>/api/get_reports?address=mirage1...&limit=100"
```

### `POST /get_upload_url`

Body:
- `type`: `"image"` (default) or `"video"`

Response (image):
- `uploadURL`, `id`, `accountHash`

Response (video):
- `uploadURL`, `provider: "stream"`, `streamCustomer`, `uid`

Curl:

```bash
curl -X POST "https://<NODE_DOMAIN>/api/get_upload_url" \
  -H "Content-Type: application/json" \
  -d '{"type":"image"}'

curl -X POST "https://<NODE_DOMAIN>/api/get_upload_url" \
  -H "Content-Type: application/json" \
  -d '{"type":"video"}'
```

### `GET /stream_proxy/<video_uid>[/<path>]`

Proxy for Cloudflare Stream manifests and segments (HLS).

### `POST /stats/event`

Body:
- `event_type`: `visit` | `session_start` | `session_end` | `page_view`
- `session_id`: string
- `user_address` (optional)
- `user_agent` (optional)
- `referrer` (optional)
- `page_path` (optional)

Response: `{ "success": true }`

Curl:

```bash
curl -X POST "https://<NODE_DOMAIN>/api/stats/event" \
  -H "Content-Type: application/json" \
  -d '{"event_type":"visit","session_id":"abc123","page_path":"/"}'
```

### `GET /get_stats`

Response: a JSON object with keys including:
- `registered_users`, `unregistered_users`, `total_users`
- `total_posts`, `total_comments`, `total_votes`
- `paid_posts`, `free_posts`, `mirage_funded_ratio`
- `upvotes`, `downvotes`
- `edit_frequency`, `delete_rate`
- `subscribers`, `new_registrations_7d`
- `average_posts_per_user`, `average_votes_per_user`, `average_comments_per_post`
- `most_active_topics`, `tag_counts`
- traffic: `dau_today`, `dau_yesterday`, `dau_registered_today`, `maus`, `dau_any_today`
- breakdowns: `browser_breakdown`, `os_breakdown`, `device_breakdown`

Curl:

```bash
curl "https://<NODE_DOMAIN>/api/get_stats"
```

### `GET /referral/stats`

Query:
- `address` (required)

Response:
- `pending_total`, `paid_total`
- `total_referrals`
- `referral_tree` (nested)
- `referred_by` (optional)
- `last_update_ts`, `next_update_ts`

Curl:

```bash
curl "https://<NODE_DOMAIN>/api/referral/stats?address=mirage1..."
```

### `POST /reload_params` (debug/admin)

Response:
- `{ status: "ok", params: { ... } }`

Curl:

```bash
curl -X POST "https://<NODE_DOMAIN>/api/reload_params"
```

---

## Write endpoints (`POST /core/*`) and expected responses

All successful on-chain relayed writes return:

```json
{ "tx_hash": "<64-hex>", "code": 0, "height": 0, "raw_log": "" }
```

Notes:
- The backend broadcasts with async mode, so `height` is often `0` initially.
- Use `GET /get_tx_status?hash=<tx_hash>` to poll for confirmation.

### Fully runnable write examples (no pubkey/signature placeholders)

For copy-pasteable write requests, use the helper script `scripts/rn_signed_request.py`. It:
- derives pubkey and address from a mnemonic
- fetches `last_block_hash` and `pow_difficulty`
- computes PoW when needed
- builds canonical bytes and signs them (64-byte compact `r||s`, low-S)
- prints the final JSON payload (which you can pipe into curl)

All commands below assume you are in the repo root and using the project conda env.

```bash
conda activate mirage-node

export NODE_DOMAIN="mirage.vote"
export API_BASE="https://${NODE_DOMAIN}/api"

MNEMONIC="word1 word2 ... word24"
```

Tip: PoW can take time. You can increase the timeout via `--pow-max-seconds 120`.

#### Poll for confirmation after any write

```bash
TX_HASH="..."
curl "${API_BASE}/get_tx_status?hash=${TX_HASH}"
```

#### Set username

```bash
python3 scripts/rn_signed_request.py --api-base "${API_BASE}" --mnemonic "${MNEMONIC}" set-username --username "alice" \
  | curl -X POST "${API_BASE}/core/set_username" -H "Content-Type: application/json" -d @-
```

#### Post

```bash
python3 scripts/rn_signed_request.py --api-base "${API_BASE}" --mnemonic "${MNEMONIC}" post \
  --topic "general" --title "Hello" --content "First post" --tag "" \
  | curl -X POST "${API_BASE}/core/post" -H "Content-Type: application/json" -d @-
```

#### Comment

```bash
PARENT="<root_post_txhash>"
python3 scripts/rn_signed_request.py --api-base "${API_BASE}" --mnemonic "${MNEMONIC}" comment \
  --parent "${PARENT}" --content "Nice post" \
  | curl -X POST "${API_BASE}/core/post" -H "Content-Type: application/json" -d @-
```

#### Vote (1, 0, -1)

```bash
TARGET="<post_txhash>"
python3 scripts/rn_signed_request.py --api-base "${API_BASE}" --mnemonic "${MNEMONIC}" vote \
  --target "${TARGET}" --direction 1 \
  | curl -X POST "${API_BASE}/core/vote" -H "Content-Type: application/json" -d @-
```

#### Edit

```bash
OVERRIDE="<txhash_being_edited>"
python3 scripts/rn_signed_request.py --api-base "${API_BASE}" --mnemonic "${MNEMONIC}" edit \
  --override "${OVERRIDE}" --target "" --topic "general" --title "Updated" --content "Updated" --tag "" \
  | curl -X POST "${API_BASE}/core/edit" -H "Content-Type: application/json" -d @-
```

#### Delete post or comment

```bash
TARGET="<txhash_to_delete>"
python3 scripts/rn_signed_request.py --api-base "${API_BASE}" --mnemonic "${MNEMONIC}" delete-post \
  --target "${TARGET}" \
  | curl -X POST "${API_BASE}/core/delete_post" -H "Content-Type: application/json" -d @-
```

#### Follow and unfollow moderator

```bash
MOD="mirage1..."
python3 scripts/rn_signed_request.py --api-base "${API_BASE}" --mnemonic "${MNEMONIC}" follow-moderator --moderator "${MOD}" \
  | curl -X POST "${API_BASE}/core/follow_moderator" -H "Content-Type: application/json" -d @-

python3 scripts/rn_signed_request.py --api-base "${API_BASE}" --mnemonic "${MNEMONIC}" unfollow-moderator --moderator "${MOD}" \
  | curl -X POST "${API_BASE}/core/unfollow_moderator" -H "Content-Type: application/json" -d @-
```

#### Follow and unfollow user

```bash
USER="mirage1..."
python3 scripts/rn_signed_request.py --api-base "${API_BASE}" --mnemonic "${MNEMONIC}" follow-user --user "${USER}" \
  | curl -X POST "${API_BASE}/core/follow_user" -H "Content-Type: application/json" -d @-

python3 scripts/rn_signed_request.py --api-base "${API_BASE}" --mnemonic "${MNEMONIC}" unfollow-user --user "${USER}" \
  | curl -X POST "${API_BASE}/core/unfollow_user" -H "Content-Type: application/json" -d @-
```

#### Follow and unfollow topic

```bash
TOPIC="general"
python3 scripts/rn_signed_request.py --api-base "${API_BASE}" --mnemonic "${MNEMONIC}" follow-topic --topic "${TOPIC}" \
  | curl -X POST "${API_BASE}/core/follow_topic" -H "Content-Type: application/json" -d @-

python3 scripts/rn_signed_request.py --api-base "${API_BASE}" --mnemonic "${MNEMONIC}" unfollow-topic --topic "${TOPIC}" \
  | curl -X POST "${API_BASE}/core/unfollow_topic" -H "Content-Type: application/json" -d @-
```

#### Block and unblock post

```bash
TARGET="<post_txhash>"
python3 scripts/rn_signed_request.py --api-base "${API_BASE}" --mnemonic "${MNEMONIC}" block-post --target "${TARGET}" \
  | curl -X POST "${API_BASE}/core/block_post" -H "Content-Type: application/json" -d @-

python3 scripts/rn_signed_request.py --api-base "${API_BASE}" --mnemonic "${MNEMONIC}" unblock-post --target "${TARGET}" \
  | curl -X POST "${API_BASE}/core/unblock_post" -H "Content-Type: application/json" -d @-
```

#### Block and unblock user

```bash
TARGET="mirage1..."
python3 scripts/rn_signed_request.py --api-base "${API_BASE}" --mnemonic "${MNEMONIC}" block-user --target "${TARGET}" \
  | curl -X POST "${API_BASE}/core/block_user" -H "Content-Type: application/json" -d @-

python3 scripts/rn_signed_request.py --api-base "${API_BASE}" --mnemonic "${MNEMONIC}" unblock-user --target "${TARGET}" \
  | curl -X POST "${API_BASE}/core/unblock_user" -H "Content-Type: application/json" -d @-
```

#### Send tokens

```bash
RECIP="mirage1..."
python3 scripts/rn_signed_request.py --api-base "${API_BASE}" --mnemonic "${MNEMONIC}" send-tokens --target "${RECIP}" --amount 1000000 \
  | curl -X POST "${API_BASE}/core/send_tokens" -H "Content-Type: application/json" -d @-
```

#### Upgrade level (paid tiers, PoW not allowed)

```bash
python3 scripts/rn_signed_request.py --api-base "${API_BASE}" --mnemonic "${MNEMONIC}" upgrade-level --level 1 \
  | curl -X POST "${API_BASE}/core/upgrade_level" -H "Content-Type: application/json" -d @-
```

#### Set auto-renewal (paid tiers, PoW not allowed)

```bash
python3 scripts/rn_signed_request.py --api-base "${API_BASE}" --mnemonic "${MNEMONIC}" set-auto-renewal --auto-renew true \
  | curl -X POST "${API_BASE}/core/set_auto_renewal" -H "Content-Type: application/json" -d @-
```

#### Report (DB-backed, PoW required as implemented)

```bash
TARGET="<txhash_to_report>"
python3 scripts/rn_signed_request.py --api-base "${API_BASE}" --mnemonic "${MNEMONIC}" report --target "${TARGET}" --reason "spam" \
  | curl -X POST "${API_BASE}/core/report" -H "Content-Type: application/json" -d @-
```

### Common required fields (always send these)

- `pubkey` (base64 compressed 33 bytes)
- `signature` (base64 64 bytes r||s)
- `timestamp` (ms)
- `last_block_hash` (hex) (always send)
- `pow_difficulty`, `pow` (free tier only, 0 for paid tier)

### `POST /core/set_username`

Body fields:
- `username` (string)
- optional: `referrer` (`mirage1...`)

Canonical message: `MsgSetUsername` (target must be your address)

### `POST /core/post`

Body fields:
- `target` (string): `""` for post, parent txhash for comment
- `topic` (string): required for post, must be `""` for comment
- `title` (string): used for post
- `content` (string)
- `tag` (string): `""`, `sensitive`, `porn`, `gore`, `violence`, `death`

Canonical message: `MsgPost`

### `POST /core/edit`

Body fields:
- `target` (string): `""` for post edit, parent txhash for comment edit
- `topic` (string): required for root post edits, must be empty for comments
- `title` (string)
- `content` (string)
- `tag` (string)
- `override` (string): txhash being edited

Canonical message: `MsgEdit`

### `POST /core/vote`

Body fields:
- `target` (string): txhash
- `direction` (int): `1`, `0`, `-1`

Canonical message: `MsgVote` (direction encoding rules apply)

### `POST /core/follow_moderator` and `/core/unfollow_moderator`

Body fields:
- `moderator` (string): `mirage1...`

Canonical message: `MsgFollowModerator` / `MsgUnfollowModerator` (target must be your address)

### `POST /core/follow_user` and `/core/unfollow_user`

Body fields:
- `target` (string): must be your address
- `user` (string): address to follow

Canonical message: `MsgFollowUser` / `MsgUnfollowUser`

### `POST /core/follow_topic` and `/core/unfollow_topic`

Body fields:
- `target` (string): must be your address
- `topic` (string): lowercase

Canonical message: `MsgFollowTopic` / `MsgUnfollowTopic`

### `POST /core/block_post` and `/core/unblock_post`

Body fields:
- `target` (string): txhash

Canonical message: `MsgBlockPost` / `MsgUnblockPost`

### `POST /core/block_user` and `/core/unblock_user`

Body fields:
- `target` (string): `mirage1...`

Canonical message: `MsgBlockUser` / `MsgUnblockUser`

### `POST /core/delete_post`

Body fields:
- `target` (string): txhash to delete

Canonical message: `MsgDelete`

### `POST /core/send_tokens`

Body fields:
- `target` (string): recipient address
- `amount` (int): umirage

Canonical message: `MsgSendTokens` (sender must be your derived address)

### `POST /core/upgrade_level`

Body fields:
- `level` (int): 1..3

Rules:
- `pow_difficulty` must be 0
- `pow` must be 0

Canonical message: `MsgUpgradeLevel`

### `POST /core/set_auto_renewal`

Body fields:
- `auto_renew` (bool)

Rules:
- only paid users can enable it
- `pow_difficulty` must be 0
- `pow` must be 0

Canonical message: `MsgSetAutoRenewal` (bool encoded as 1 or 0 at tag 100)

### `POST /core/report` (DB-backed, not on-chain)

Body fields:
- `target` (string): txhash (64 hex)
- `reason` (string, max 200)

Requires PoW for free tier and requires signature verification.

Response:
- `{ "success": true, "id": <int> }`

### `POST /core/resolve_report` (admin only)

Body fields:
- `address` (admin address, `mirage1...`)
- `id` (int)

Response: `{ "success": true }`

### `POST /core/fp` (device fingerprint, DB-backed)

Body fields:
- `user_address` (required)
- plus fingerprint fields (web-style naming):
  - `screenWidth`, `screenHeight`, `colorDepth`, `pixelRatio`, `timezone`, `timezoneOffset`, `language`, `languages`, `platform`
  - `hardwareConcurrency`, `deviceMemory`, `touchSupport`
  - `canvasHash`, `webglVendor`, `webglRenderer`, `webglHash`
  - `attributes` (object, stored as JSONB)

Response:
- `{ "success": true }` (or an error)

---

## End-to-end flows (what to implement in the app)

### Flow: create account (identity only)

1. Generate mnemonic (BIP39)
2. Derive privkey using `m/44'/118'/0'/0/0`
3. Compute compressed pubkey (33 bytes)
4. Derive `mirage1...` address
5. Store mnemonic securely, store address and pubkey for display and requests

There is no dedicated “create account” endpoint. Your account exists as soon as it has an address. A profile is created on-chain when you perform actions like follow, set username, etc.

### Flow: set username (recommended first write)

1. `GET /get_parameters` for `last_block_hash` and `pow_difficulty`
2. `GET /get_user_status?address=...` to determine tier
3. Build canonical bytes for `MsgSetUsername` with `target = your_address`
4. If free tier, compute PoW. If paid tier, set pow=0 and difficulty=0.
5. Sign the canonical signed bytes.
6. POST to `/core/set_username`
7. Poll `/get_tx_status?hash=...` until `{found:true, success:true, indexed:true}`

### Flow: post and comment

Same as set username, but:
- posts: `target=""`, include topic and title
- comments: `target="<parent_txhash>"`, topic must be empty, title empty

### Flow: vote

Same as set username, but direction is `1`, `0`, or `-1` and must be encoded as uint32 in canonical bytes.

---

## Python reference implementation (already in this repo)

If you want a working, end-to-end reference that:
- derives keys from mnemonic
- calls the backend
- computes PoW
- builds canonical bytes
- signs correctly (compact 64-byte + low-S)

See `shared/client.py`.

Example usage:

```python
from shared.client import create_wallet_from_seed, set_username, post, vote

backend = "https://<NODE_DOMAIN>"
wallet = create_wallet_from_seed("your mnemonic words here", prefix="mirage")

print(set_username(backend, wallet, "alice"))
txh = post(backend, wallet, topic="general", title="Hello", content="First post", tag="")
print("post tx:", txh)
print(vote(backend, wallet, target=txh, direction=1))
```

---

## Troubleshooting

### “invalid signature”

Almost always one of:
- you signed the wrong bytes (must match canonical format, not JSON, not protobuf)
- you forgot to insert pow tag 5 in the signed bytes
- you used DER signatures instead of compact 64-byte `r||s`
- you did not normalize low-S
- you encoded vote direction incorrectly (`-1` must be `4294967295` in canonical bytes)
- your `timestamp` differs between what you signed and what you sent

### “envelope_timestamp too old” or “in future”

Device clock drift. Fix NTP/time settings.

### “pow not allowed for subscribers”

If `user_level >= 1`, send `pow_difficulty=0` and `pow=0`.

### “insufficient pow”

Your PoW is computed against:
- the wrong base bytes (must be base without pow tag 5)
- the wrong salt (must be raw bytes from hex-decoding `last_block_hash`)
- wrong argon2 parameters (must be t=1, m=4096 KiB, p=1, outLen=32)
- wrong difficulty (use `/get_parameters.pow_difficulty`)


