# Mobile Client: `/api/bootstrap` Integration

## Overview

`GET /api/bootstrap` is a single combined endpoint that returns everything the
mobile app needs for its first paint. Use it instead of fanning out separate
calls to `get_node_config`, `get_user_status`, `get_user_followed`,
`get_user_blocked`, `get_invite_codes`, and `/rewards/summary`. One round-trip
replaces six.

**Why this exists:** The web client previously fired ~7 `/api/*` requests in the
first ~50ms of a cold load and routinely tripped the production node's Caddy
rate limiter (10 req/s/IP). Bootstrap collapses the per-session/per-user calls
into one and dramatically improves Time-To-First-Byte. Mirroring this on
mobile gives the same wins on cold app launch and after sign-in/sign-up.

**Key rules:**

- Bootstrap is **additive**. Every per-endpoint route (`/api/get_node_config`,
  `/api/get_user_status`, …) stays live, returns the same shape, and is the
  source of truth on demand. Bootstrap is just a "warm the caches in one shot"
  optimization.
- Any sub-section may be `null` if its sub-handler errored. Mobile MUST treat
  `null` as "fall through and call the per-endpoint route." Do not surface a
  user-facing error for a partial bootstrap.
- Bootstrap is read-only. There are no signed parameters and no side-effects.
- The whole response is `503` if the node is catching up — same semantics as
  `/api/get_user_status` today. Retry with backoff.

## Endpoint Contract

```
GET /api/bootstrap
GET /api/bootstrap?address=<bech32>
```

| Parameter | Type   | Required | Notes                                                             |
| --------- | ------ | -------- | ----------------------------------------------------------------- |
| `address` | string | no       | Active wallet address. Omit for anonymous app launches.           |

**Status codes:**

| Code | Meaning                                                                                                  |
| ---- | -------------------------------------------------------------------------------------------------------- |
| 200  | Success. Per-section nulls indicate sub-handler failure — fall through to the per-endpoint route.        |
| 503  | `node_catching_up`. The node hasn't caught up to the chain yet. Retry with the same backoff as today.    |
| 5xx  | Treat as full failure: skip the optimization and let the per-endpoint hooks fire on their own.            |

The response body always has the **same six top-level keys**, even on the
anonymous variant. `node_config` is non-null whenever the request succeeds;
the five `user_*` / `*_summary` keys are non-null only when `address` is
supplied AND that section's sub-handler succeeded.

```json
{
  "node_config":     { ... } | null,
  "user_status":     { ... } | null,
  "user_followed":   { ... } | null,
  "user_blocked":    { ... } | null,
  "invite_codes":    { ... } | null,
  "rewards_summary": { ... } | null
}
```

## When to Call

Call **once** at each of these moments:

1. **Cold app launch** — right after the splash, before the home feed
   request. If a logged-in `address` is in secure storage, pass it; otherwise
   omit.
2. **Sign-in / sign-up / wallet switch** — immediately after the new
   `address` is persisted, with that address as the query param.
3. **Sign-out** — call once with no `address` so you re-prime `node_config`
   for the now-anonymous session.

Do **NOT** call on:

- Background refresh
- Pull-to-refresh on the feed (call `get_posts` directly)
- Tab/screen change
- Foreground from background (rely on per-screen refresh instead — bootstrap
  is for cold starts, not session continuity)

A typical mobile cold launch should issue exactly two `/api/*` requests:
**`bootstrap` + `get_posts`**. Search trending topics, agents, profile
detail, etc. all stay lazy and load when their surface mounts.

## What to Do With Each Section

Each section's shape is identical to the per-endpoint response — what you
already parse for `/api/get_node_config`, `/api/get_user_status`, etc. The
only difference is that bootstrap **omits the `balance` field** that the
per-endpoint routes inject as a convenience (it's already inside
`user_status.balance`, so duplicating it would be wasted bytes).

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
- **Cache:** session. Invalidate after a quest claim that grants codes
  (web equivalent: the `inviteCodesUpdated` event fired from the rewards
  flow). Also invalidate when a code's `used_by` field changes.
- **Drives:** the Invites screen — list of codes, available count,
  redemption status. Only meaningful on hosts where the backend's
  invite-code system is active (`mirage.talk` and localhost as of writing).
  Treat an empty list as "no invites available" rather than an error.

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
| `user_status`      | none         | session       | Post, vote, claim, gift, subscribe, renew, balance-affecting tx |
| `user_followed`    | none         | 24h           | Follow / unfollow user or topic, agent enable/disable/reorder   |
| `user_blocked`     | none         | session       | Block / unblock user, post, or topic                            |
| `invite_codes`     | none         | session       | Quest claim that granted codes; code redeemed                   |
| `rewards_summary`  | none         | screen-driven | Rewards screen refresh; quest progress update; claim            |

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

  if (resp.invite_codes)    cache.setInviteCodes(resp.invite_codes);
  else                      scheduleInviteCodesFetch();

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
- **Feed** (`GET /api/get_posts`) — driven by feed state (sort, page,
  topic). Bootstrap does NOT include feed posts; keep your existing loader.
- **Profile detail** (`/api/get_user_profile`) — load when a profile page
  opens, not at app launch.

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
  "invite_codes":    null,
  "rewards_summary": null
}
```

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
  "invite_codes": {
    "codes":     [],
    "total":     0,
    "available": 0
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
