# API Request Signing (Mobile)

This guide is for the external mobile developer. It covers the **one endpoint**
you must change for the v1.32.0 backend auth hardening:
`POST /api/rewards/claim`.

The signing scheme is the same one already used for `mark_inbox_viewed`,
`seen_posts`, and push-token registration. Reuse that code path.

---

## 1. Why claim needs a signature

`/api/rewards/claim` is a **write**. The MIRAGE payout always goes to the named
`owner`, so this is not about theft. The reward multiplier
(`1.0x` at 0 completed quests → `5.0x` at 50) is applied **at claim time**.
Whoever calls claim chooses the multiplier the owner is stuck with. An
unsigned claim lets a stranger lock someone else's pending rewards in at 1.0x.

Admin moderation routes (`get_reports`, `resolve_report`, reward suspend /
unsuspend) also require signatures now, but the mobile app has no moderation
UI — you can ignore those.

---

## 2. Wire contract

```http
POST /api/rewards/claim
Content-Type: application/json
```

```json
{
  "owner": "mirage1abc...",
  "pubkey": "<base64, 33-byte compressed secp256k1>",
  "signature": "<base64, 64-byte compact r||s>",
  "timestamp": 1775432400000,
  "envelope_nonce": 8123456789012345
}
```

| Field | Notes |
|---|---|
| `owner` | Mirage bech32 address. Same field name as before. |
| `pubkey` | Compressed secp256k1 public key, base64. Must derive to `owner`. |
| `signature` | Compact 64-byte `r\|\|s` over `SHA-256(payload)`, base64. A 65-byte form with recovery byte is accepted and truncated. |
| `timestamp` | **Milliseconds** since epoch (UTC). Must be within **±5 minutes** of server time. |
| `envelope_nonce` | Unique uint64 per request. Replays are rejected. |

**Signed UTF-8 string (exact):**

```
rewards_claim:<owner-lowercased>:<timestamp>:<nonce>
```

Example:

```
rewards_claim:mirage1uadw6y798u6wp7ljpc3qnjmrgzgmrdz94a73uu:1775432400000:8123456789012345
```

---

## 3. How to produce the signature

1. Derive the compressed 33-byte pubkey from the user's seed (same key used for
   every other Mirage signed request).
2. Build the payload string above with `owner.toLowerCase()`, the current
   millisecond timestamp, and a fresh nonce.
3. `SHA-256` the UTF-8 bytes of that string.
4. Sign the digest with secp256k1; emit compact 64-byte `r||s`.
5. Base64-encode pubkey and signature; send them with `owner`, `timestamp`,
   and `envelope_nonce` in the JSON body.

Web reference (`signPlainPayload`):

```javascript
const sig = await signPlainPayload(
  (ts, n) => `rewards_claim:${userAddress.toLowerCase()}:${ts}:${n}`
);
await Api.post('rewards/claim', { owner: userAddress, ...sig });
```

TypeScript sketch:

```typescript
import { sha256 } from "@noble/hashes/sha256";
import { secp256k1 } from "@noble/curves/secp256k1";

function signClaim(privKey: Uint8Array, owner: string) {
  const timestamp = Date.now();
  const nonce = /* unique uint64 */;
  const payload = `rewards_claim:${owner.toLowerCase()}:${timestamp}:${nonce}`;
  const digest = sha256(new TextEncoder().encode(payload));
  const sig = secp256k1.sign(digest, privKey); // compact 64 bytes
  const pub = secp256k1.getPublicKey(privKey, true); // 33-byte compressed
  return {
    owner,
    pubkey: Buffer.from(pub).toString("base64"),
    signature: Buffer.from(sig.toCompactRawBytes()).toString("base64"),
    timestamp,
    envelope_nonce: nonce,
  };
}
```

Worked curl (replace the four signed fields with values from your signer):

```bash
curl -s -X POST 'http://127.0.0.1/api/rewards/claim' \
  -H 'Content-Type: application/json' \
  -d '{
    "owner": "mirage1abc...",
    "pubkey": "<base64>",
    "signature": "<base64>",
    "timestamp": 1775432400000,
    "envelope_nonce": 8123456789012345
  }'
```

---

## 4. Error responses you will see

| HTTP | `error` | Cause / fix |
|---|---|---|
| 401 | `signature required` | Grace period over; unsigned body rejected. Sign it. |
| 401 | `missing required fields` | `pubkey` / `signature` absent. |
| 401 | `invalid signature` | Wrong payload string, wrong key, or mangled base64. |
| 401 | `address does not match pubkey` | `owner` is not the address derived from `pubkey`. |
| 401 | `timestamp outside allowed window` | Device clock skew > ±5 minutes. Sync the clock. |
| 401 | `timestamp must be milliseconds` | You sent seconds. Multiply by 1000. |
| 401 | `replayed envelope_nonce` | Retried the exact same signed body. **Re-sign** with a fresh timestamp and nonce. |
| 200 | `no_rewards` (`success: false`) | Nothing pending — not an auth failure. |
| 403 | suspended | Owner is reward-suspended. |
| 503 | not configured / pool errors | Node rewards pool not ready. |

A retry that reuses the previous signature will always fail with
`replayed envelope_nonce`. Always re-sign.

---

## 5. Grace period

Until **2026-09-05** (UTC), unsigned claims are still accepted so installed
builds keep working. Every unsigned claim is logged as
`authz.legacy_unsigned` so adoption is measurable.

**On and after 2026-09-05, unsigned claims are a hard 401.** Ship the signed
client before that date.

---

## 6. Invite-code endpoints

`GET /api/get_invite_codes` and `POST /api/validate_invite_code` now return
**404** while `REGISTRATION_INVITE_CODE_REQUIRED=false` (fleet-wide default).
Do not call them. If a node ever turns the flag back on, `get_invite_codes`
will require a signed read (`get_invite_codes:<address>:<timestamp>:<nonce>`)
and `validate_invite_code` will no longer return the code owner's address.

---

## 7. Integration checklist

- [ ] Sign `POST /api/rewards/claim` with payload `rewards_claim:<addr>:<ts>:<nonce>`.
- [ ] Re-sign on every retry (fresh timestamp + nonce).
- [ ] Keep device clock within ±5 minutes of UTC.
- [ ] Ship before **2026-09-05**.
- [ ] Stop calling invite-code endpoints (they 404).
- [ ] No change needed for `get_inbox`, `rewards/summary`, bootstrap, or other reads.
