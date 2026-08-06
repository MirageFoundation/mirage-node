# Mobile Client: `/api/bootstrap` Integration

## Overview

`GET /api/bootstrap` is a single combined endpoint that returns everything the
mobile app needs for its first paint. Use it instead of fanning out separate
calls to `get_node_config`, `get_chain_config`, `get_user_status`,
`get_user_followed`, `get_user_blocked`, `/rewards/summary`, and (with `view=`)
the initial screen payload (`get_posts` / `get_comments` / `get_inbox`). One
round-trip replaces the cold-start fan-out. Invite codes are included only when
the node has `registration_invite_code_required` enabled.

**Why this exists:** The web client previously fired ~7 `/api/*` requests in the
first ~50ms of a cold load and routinely tripped the production node's Caddy
rate limiter (10 req/s/IP). Bootstrap collapses the per-session/per-user calls
into one and dramatically improves Time-To-First-Byte. Mirroring this on
mobile gives the same wins on cold app launch and after sign-in/sign-up.

**Key rules:**

- Bootstrap is **additive**. Every per-endpoint route stays live, returns the
  same shape, and is the source of truth on demand. Bootstrap is just a
  "warm the caches in one shot" optimization.
- Any sub-section may be `null` if its sub-handler errored. Mobile MUST treat
  `null` as "fall through and call the per-endpoint route." Do not surface a
  user-facing error for a partial bootstrap.
- Bootstrap is read-only. There are no signed parameters and no side-effects.
- The whole response is `503` if the node is catching up — same semantics as
  `/api/get_user_status` today. Retry with backoff.

For UX rules (layout shift, notification prefetch bounds), see
[`mobile_instant_load.md`](./mobile_instant_load.md).

## Endpoint Contract

```
GET /api/bootstrap
GET /api/bootstrap?address=<bech32>
GET /api/bootstrap?address=<bech32>&view=feed:home&by=magic&allowed_tags=sensitive&limit=15
GET /api/bootstrap?address=<bech32>&view=thread:<post_id>
GET /api/bootstrap?address=<bech32>&view=inbox
```

| Parameter | Type | Required | Notes |
| --------- | ---- | -------- | ----- |
| `address` | string | no | Active wallet address. Omit for anonymous app launches. |
| `view` | string | no | Initial screen: `feed:home`, `feed:following`, `topic:<name>`, `thread:<post_id>`, `inbox`. Absent → `"view": null`. |
| `by` | string | no | Feed sort: `magic` (default) or `newest`. Only used with feed views. |
| `allowed_tags` | string | no | Comma-separated tag allowlist (default `sensitive`). Only used with feed views. |
| `limit` | int | no | Feed/inbox page size (default 15, max 100). |

**Status codes:** unchanged from before (200 / 503 / 5xx).

The response body always has these top-level keys (except `invite_codes`,
which is omitted entirely while invite codes are disabled on the node):

```json
{
  "node_config":     { ... } | null,
  "chain_config":    { ... } | null,
  "user_status":     { ... } | null,
  "user_followed":   { ... } | null,
  "user_blocked":    { ... } | null,
  "invite_codes":    { ... } | null,   // only when registration_invite_code_required
  "rewards_summary": { ... } | null,
  "view":            { ... } | null
}
```

### `view` shapes

```json
{ "kind": "feed", "feed": "home", "posts": [...], "total": N, "page": 1, "limit": 15, "has_more": true }
{ "kind": "feed", "topic": "mirage", "posts": [...], "total": N, "page": 1, "limit": 15, "has_more": true }
{ "kind": "thread", "found": true, "root": {...}, "children": [...], "ancestors": [...], "ancestors_omitted": 0 }
{ "kind": "thread", "found": false }
{ "kind": "inbox", "replies": [...], "total": N, "page": 1, "limit": 25, "has_more": false }
```

`get_comments` also returns `ancestors` / `ancestors_omitted` on every call
(root-first, immediate parent last; empty for root posts).

## When to Call

Call **once** at each of these moments:

1. **Cold app launch** — right after the splash, with `view=` set from the
   launch intent (see [`mobile_instant_load.md`](./mobile_instant_load.md)).
2. **Sign-in / sign-up / wallet switch** — immediately after the new
   `address` is persisted.
3. **Sign-out** — call once with no `address` so you re-prime `node_config`
   for the now-anonymous session.

Do **NOT** call on background refresh, pull-to-refresh, tab change, or
foreground-from-background.

A typical mobile cold launch should issue exactly **one** `/api/*` request:
**`bootstrap` with `view=`**. Search trending, profile detail, etc. stay lazy.

## What to Do With Each Section

Each section's shape is identical to the per-endpoint response — what you
already parse for `/api/get_node_config`, `/api/get_user_status`, etc. The
only difference is that bootstrap **omits the `balance` field** that the
per-endpoint routes inject as a convenience (it's already inside
`user_status.balance`, so duplicating it would be wasted bytes).

### `chain_config`

- **Source of truth:** same as `GET /api/get_chain_config`.
- **Cache:** 4h. Governance params change rarely.
- **Drives:** tier limits, award configs, username/topic size bounds,
  subscription period.

### `node_config`

- **Source of truth:** same as `GET /api/get_node_config`.
- **Cache:** 24h. Survives app relaunch. Backend caches identically (24h),
  so longer client TTLs only burn the bytes once a day.
- **Invalidate on:** validator switch (rare; usually a node URL change).
- **Drives:** feature flags
  (`registration_enabled`, `quests_enabled`, `push_notifications_enabled`,
  `quest_payouts_enabled`, `new_user_highlight_days`,
  `android_banner_enabled`, `ios_banner_enabled`,
  `registration_invite_code_required`), validator addresses, the GIPHY API
  key, and the validator moniker shown in node-picker UI.

### `user_status`

- **Source of truth:** same as `GET /api/get_user_status?address=…`.
- **Cache:** session-scoped (memory + secure storage backup). Refresh on
  any user-visible balance-affecting action (post, vote, claim, gift,
  subscription renewal). The web client also pulls a fresh copy on cold
  reload via this endpoint — bootstrap satisfies that path.
- **`recent_votes`** (up to 100 entries) is the same payload that powers
  web's local upvote/downvote highlight cache. Persist this to seed the
  feed view's highlight rendering before the on-chain `user_vote` field
  arrives in `get_posts` results.
- **Drives:** balance display, level/tier-gated UI, subscription expiry +
  auto-renew toggle, `inbox_last_viewed_at` for the inbox dot,
  `referral_precheck_enabled` for the referral form.

### `user_followed`

- **Source of truth:** same as `GET /api/get_user_followed?address=…`.
- **Cache:** 24h, mirroring the web's `profile_followed_cache`. Invalidate
  on follow/unfollow / agent enable/disable / agent reorder.
- **Drives:** sidebar followed users, followed topics list, and the
  enabled-agents list on the agent picker.

### `user_blocked`

- **Source of truth:** same as `GET /api/get_user_blocked?address=…`.
- **Cache:** session. Invalidate on block/unblock for any of the three
  axes.
- **Drives:** client-side feed filtering and the "blocked" badge on
  profile / topic pages.

### `invite_codes`

- **Source of truth:** same as `GET /api/get_invite_codes?address=…`.
- **Present only when** the node's `registration_invite_code_required`
  flag is true. While the flag is false (fleet-wide default), this
  key is **omitted entirely** from the bootstrap response — not an
  empty object, not null. Clients must treat a missing key as
  "invite codes disabled on this node".
- **When the flag is true**, the section is filled only if the bootstrap
  request itself carries a valid signed read
  (`get_invite_codes:<address>:<timestamp>:<nonce>` as query params).
  An unsigned bootstrap still returns 200 for everything else, with
  `invite_codes: null`; hydrate via signed `GET /api/get_invite_codes`.
- **Cache:** session. Invalidate after a quest claim that grants codes
  (web equivalent: the `inviteCodesUpdated` event fired from the rewards
  flow). Also invalidate when a code's `used_by` field changes.
- **Drives:** the Invites screen — list of codes, available count,
  redemption status. Unused codes are bearer credentials, so unsigned
  reads are never served.

### `rewards_summary`

- **Source of truth:** same as `GET /api/rewards/summary?owner=…`.
- **Cache:** treat as session, but the rewards screen has its own
  refresh cadence — bootstrap just gives a free initial snapshot.
- **Disabled / suspended states:** the body still has the same shape;
  check `disabled === true` or `suspended === true` and render the
  appropriate empty state. These short-circuits already match the
  per-endpoint response.

## Per-Section Freshness Contract

Don't burn the bootstrap win by over-fetching downstream. Backend cache TTL
is what the server itself memoizes; client TTL is the longest you should go
between explicit refreshes.

| Section            | Server cache | Client cache  | Invalidate when                                                 |
| ------------------ | ------------ | ------------- | --------------------------------------------------------------- |
| `node_config`      | 24h          | 24h           | Node/validator URL changed                                      |
| `chain_config`     | 24h          | 4h            | Governance param change (rare)                                  |
| `user_status`      | none         | session       | Post, vote, claim, gift, subscribe, renew, balance-affecting tx |
| `user_followed`    | none         | 24h           | Follow / unfollow user or topic, agent enable/disable/reorder   |
| `user_blocked`     | none         | session       | Block / unblock user, post, or topic                            |
| `invite_codes`     | none         | session       | Quest claim that granted codes; code redeemed                   |
| `rewards_summary`  | none         | screen-driven | Rewards screen refresh; quest progress update; claim            |
| `view`             | none         | first-paint only | Never persist across launches; screen owns refresh after mount |

## Fallback Rules

Per-section nulls are not errors — they're routine. The recommended
pseudocode:

```ts
const resp = await api.get('/api/bootstrap', address ? { address } : undefined);

if (resp.node_config) cache.setNodeConfig(resp.node_config);
else                  scheduleNodeConfigFetch(); // hits /api/get_node_config

if (address) {
  if (resp.user_status)     cache.setUserStatus(resp.user_status);
  else                      scheduleUserStatusFetch();

  if (resp.user_followed)   cache.setFollowed(resp.user_followed);
  else                      scheduleUserFollowedFetch();

  if (resp.user_blocked)    cache.setBlocked(resp.user_blocked);
  else                      scheduleUserBlockedFetch();

  // invite_codes is omitted while the feature is off — do not fan out to
  // /api/get_invite_codes (it 404s). Only hydrate when the section is present.
  if (resp.invite_codes)    cache.setInviteCodes(resp.invite_codes);

  if (resp.rewards_summary) cache.setRewardsSummary(resp.rewards_summary);
  // No need to schedule rewards_summary fetch — the rewards screen will pull
  // its own fresh copy when the user opens it.
}
```

If the **whole** request fails (network error, 5xx, 503), proceed exactly as
you do today: each per-endpoint hook fires when its surface mounts. The
bootstrap optimization is best-effort.

## Lazy-Fetch Guidance

Mirror the web client's lazy-loading discipline for surfaces *not* covered
by bootstrap:

- **Search trending** (`GET /api/get_topics`) — fire only when the search
  surface opens or the search input is focused. Cache the result for ~5
  minutes within the session. Don't preload on app launch.
- **Discover topics** (`/topics` route) — already lazy; load on route entry
  and cache.
- **Feed / thread / inbox** — prefer `view=` on bootstrap for cold start.
  After first paint, use `get_posts` / `get_comments` / `get_inbox` for
  refresh and pagination. `get_comments` now includes `ancestors`.
- **Profile detail** (`/api/get_profile`) — load when a profile page
  opens, not at app launch. Response includes `following_count` and
  `follower_count` (see below).

## Profile follow counts (v1.30.0)

`GET /api/get_profile?address=<addr>` includes two additive integers:

- `following_count` — how many users this account follows
- `follower_count` — how many users follow this account

Both are non-negative ints from indexed `COUNT`s on `followed_users`. Always
present (including missing-profile responses, where both are `0`). Additive
for older clients that ignore unknown keys.

## Example Responses

### Anonymous (no `address`)

```bash
curl -s http://127.0.0.1/api/bootstrap | jq
```

```json
{
  "node_config": {
    "android_banner_enabled": true,
    "giphy_api_key": "<redacted>",
    "ios_banner_enabled": true,
    "new_user_highlight_days": 7,
    "push_notifications_enabled": true,
    "quest_payouts_enabled": false,
    "quests_enabled": false,
    "registration_enabled": true,
    "registration_invite_code_required": false,
    "validator_account_address": "mirage1vkdacfe…",
    "validator_consensus_address": "miragevalcons199…",
    "validator_moniker": "https://mirage.vote",
    "validator_operator_address": "miragevaloper1vkdacfe…"
  },
  "user_status":     null,
  "user_followed":   null,
  "user_blocked":    null,
  "rewards_summary": null
}
```

`invite_codes` is omitted here because `registration_invite_code_required` is
false on this node.

### Logged in (with `address`)

```bash
curl -s "http://127.0.0.1/api/bootstrap?address=mirage1p9te3c5fgjjw4dkg4kmm6g4yy62a3z3003l0td" | jq
```

```json
{
  "node_config":   { /* same as above */ },
  "user_status": {
    "username": "Mirage",
    "balance": 1748425662000,
    "user_level": 100,
    "subscription_expiry": 1771651501,
    "auto_renew": true,
    "reserve_funds": 0,
    "profile_registered_at": 1761955200,
    "recent_votes": [
      { "target": "167ad2…", "direction": 1, "timestamp": 1774742232 },
      { "target": "508789…", "direction": 1, "timestamp": 1774742217 }
    ],
    "inbox_last_viewed_at": 0,
    "referral_precheck_enabled": false
  },
  "user_followed": {
    "enabled_agents":  [],
    "followed_topics": ["arischemadchen"],
    "followed_users":  []
  },
  "user_blocked": {
    "blocked_posts":  ["d9bb85…", "636264…"],
    "blocked_users":  [],
    "blocked_topics": []
  },
  "rewards_summary": {
    "disabled":                       true,
    "daily_quests":                   [],
    "flash_quest":                    null,
    "pending_rewards":                [],
    "seconds_until_reset":            0,
    "reward_multiplier":              1,
    "total_mirage":                   0,
    "total_mirage_after_multiplier":  0,
    "pending_invite_codes":           0,
    "claiming_available":             false,
    "debug":                          false
  }
}
```

When `registration_invite_code_required` is true, the response also includes
an `invite_codes` object (`codes` / `total` / `available`). When the flag is
false (fleet default), that key is absent.

(Note: `new_inbox_items` may also appear in the response — that's a
backend-wide middleware that injects into every JSON response for
logged-in users; ignore here, it's already handled by your existing
inbox-count plumbing.)

## Migration Notes

- Per-endpoint routes (`/api/get_node_config`, `/api/get_user_status`, etc.)
  stay live, so mobile can ship bootstrap as a follow-up release with no
  coordination — old clients continue to work, new clients get the win.
- No chain version coupling. The endpoint is pure backend.
- No new auth, no new params, no new error codes. The existing
  `node_catching_up` 503 is the only special case.
- The web client's bootstrap stash is `localStorage`-keyed and discarded
  after consumption. Mobile equivalents should use whatever in-memory
  cache layer already powers the per-endpoint hooks (no need for a
  separate "bootstrap stash" abstraction — write directly into the same
  caches the per-endpoint responses populate).
