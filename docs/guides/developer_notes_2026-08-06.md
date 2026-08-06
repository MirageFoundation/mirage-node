# Mirage Developer Notes — 2026-08-06

For the external mobile developer. Two topics:

1. **Request volume — read this first.** The app is making several times more
   HTTP calls than it needs to, including hundreds a day to a feature that is
   switched off. This is the more urgent of the two.
2. **Claim signing.** `POST /api/rewards/claim` needs a signature. Deadline
   **2026-10-05**; until then a bad or missing signature is still served.

---

## 1. Cut your request volume

Measured on the production node (`mirage.talk`), native clients only
(`okhttp/4.12.0` on Android, `Mirage/78`–`Mirage/88` on iOS), over one 9-hour
window on 2026-08-06 — **5,761 requests**. Most of them did not need to happen.

| Calls | Endpoint | What to do instead |
|---|---|---|
| 1,701 | `POST /api/seen_posts` | **Batch.** The endpoint accepts **up to 100 post IDs per call**. You are sending roughly one call per post. This should be a few dozen calls. |
| 879 | `GET /api/get_inbox` | **Stop polling it for unread state.** Every JSON response the backend sends a logged-in user already carries `new_inbox_items`. Fetch the inbox when the user opens it, not on a timer. |
| 413 | `GET /api/get_invite_codes` | **Stop calling it.** Invite codes are off fleet-wide, so every one of these fetched nothing. When the feature is on, the codes arrive in `bootstrap`. |
| 311 | `GET /api/get_root_post_id` | **Delete this call entirely.** Every inbox item already contains `root_post_id`, and so does every post in `get_posts` / `get_comments`. You are asking for a field you were just handed — once per item. |
| 258 | `GET /api/get_user_status` | Already in `bootstrap` as `user_status`. |
| 192 | `POST /api/core/register_push_token` | Register when Expo hands you a **new** token, not on every launch. |
| 192 | `GET /api/rewards/summary` | Already in `bootstrap` as `rewards_summary`. |
| 128 | `GET /api/get_node_config` | Already in `bootstrap` as `node_config`. |
| 63 | `GET /api/get_parameters` | Already in `bootstrap` as `chain_config`. |
| 22 / 17 | `get_user_blocked` / `get_user_followed` | Already in `bootstrap` as `user_blocked` / `user_followed`. |

Those rows total **4,176 requests**. In the same window the things users actually
did — 414 votes and 265 posts — accounted for 679. You are spending six requests
on bookkeeping for every one that carries a user action.

### Cold start is one request

`GET /api/bootstrap?address=<addr>&view=feed` returns `node_config`,
`chain_config`, `user_status`, `user_followed`, `user_blocked`,
`rewards_summary`, and the first screen's payload in a single round trip.
`view=` also accepts `thread` and `inbox`.

There were 159 `bootstrap` calls in the window **and** 128 `get_node_config`,
258 `get_user_status`, 192 `rewards/summary`, 63 `get_parameters` — so the app
is calling bootstrap and then fanning out to the same data anyway. Pick one.

### Rules of thumb

- **One call per screen, not one per item.** If you are looping over a list and
  issuing a request per element, the data is almost always already in the list
  payload (`root_post_id` is the current example) or there is a batch form.
- **Do not poll.** Inbox state rides along on every response
  (`new_inbox_items`). Nothing needs a timer.
- **Cache config for the session.** `node_config` and `chain_config` do not
  change under a running app.
- **A disabled feature is not worth a request.** Read the flags in
  `node_config` (`registration_invite_code_required`, `quests_enabled`,
  `push_notifications_enabled`, `open_browsing_enabled`) and skip the whole
  code path when a flag is false.

This traffic lands on a single node behind one Caddy instance with a per-IP rate
limit. The top four rows alone are 3,304 of the 5,761 requests (57%), and nearly
all of that is removable without the app losing a single feature.

---

## 2. Why claim needs a signature

`/api/rewards/claim` is a **write**. The MIRAGE payout always goes to the named
`owner`, so this is not about theft. The reward multiplier
(`1.0x` at 0 completed quests → `5.0x` at 50) is applied **at claim time**.
Whoever calls claim chooses the multiplier the owner is stuck with. An
unsigned claim lets a stranger lock someone else's pending rewards in at 1.0x.

Admin moderation routes (`get_reports`, `resolve_report`, reward suspend /
unsuspend) also require signatures now, but the mobile app has no moderation
UI — you can ignore those.

---

## 3. Wire contract

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

## 4. How to produce the signature

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

## 5. Error responses you will see

These are the responses **after** the grace period ends. While it is open, every
401 below is served as a normal claim instead (see §6).

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

## 6. Grace period

Until **2026-10-05** (UTC), a claim is served even when its identity proof is
absent **or fails verification** — a wrong payload string, an old signing
scheme, a stale clock, a replayed nonce. Anything that would be a 401 in §5 is
served instead, and logged as `authz.legacy_unsigned` with a `reason=` field
naming the failure, so adoption and mistakes are both measurable.

The window covers failed proofs, not just missing ones, on purpose: gating it on
whether `pubkey`/`signature` were *present* rejected every installed build that
signs under an older scheme, which is exactly the population the window exists
to protect. Accepting an unverifiable proof is no weaker than accepting none —
the payout always goes to `owner`.

**On and after 2026-10-05, an absent or invalid proof is a hard 401.** Ship the
signed client before that date, and check your integration against the `reason=`
values in the node's logs rather than assuming a 200 means your signature
verified. The deadline moved out from the originally announced 2026-09-05
because the first month of the window was unusable: any client that sent a
signature the backend could not verify was rejected outright.

---

## 7. Invite-code endpoints

Gate this whole feature on `node_config.registration_invite_code_required` and
make **zero** requests while it is false. That flag is false fleet-wide today,
which is why the 413 `get_invite_codes` calls in §1 all fetched nothing.

While `REGISTRATION_INVITE_CODE_REQUIRED=false` (fleet-wide default):

- `GET /api/get_invite_codes` returns `200` with an empty list
  (`{"codes": [], "total": 0, "available": 0}`). This exists so an old build
  degrades to an empty Invites screen instead of an error — it is not an
  invitation to keep calling it. It returned 404 briefly in v1.33.0; that is
  fixed.
- `POST /api/validate_invite_code` returns **404**. Do not call it.

If a node ever turns the flag back on, the codes arrive in the `bootstrap`
response, `get_invite_codes` requires a signed read
(`get_invite_codes:<address>:<timestamp>:<nonce>`), and `validate_invite_code`
no longer returns the code owner's address.

---

## 8. Integration checklist

Request volume (§1):

- [ ] Delete every call to `get_invite_codes` and `validate_invite_code`; gate
      the feature on `registration_invite_code_required`.
- [ ] Delete every call to `get_root_post_id` — read `root_post_id` off the item.
- [ ] Batch `seen_posts` up to 100 IDs per request.
- [ ] Stop polling `get_inbox`; use `new_inbox_items` from any response.
- [ ] Cold start via one `bootstrap?address=&view=` call; drop the separate
      `get_node_config`, `get_parameters`, `get_user_status`, `rewards/summary`,
      `get_user_followed`, `get_user_blocked` calls.

Claim signing (§2–§6):

- [ ] Sign `POST /api/rewards/claim` with payload `rewards_claim:<addr>:<ts>:<nonce>`.
- [ ] Re-sign on every retry (fresh timestamp + nonce).
- [ ] Keep device clock within ±5 minutes of UTC.
- [ ] Ship before **2026-10-05**.
- [ ] Confirm in the node logs that your claims are **not** landing on
      `authz.legacy_unsigned` — a 200 alone does not mean the signature verified.
