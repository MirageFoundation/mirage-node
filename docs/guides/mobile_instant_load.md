# Mobile Instant Load Guide

How to make cold start, inbox taps, and notification opens feel instant —
one round trip, no layout shift.

Read [`api_bootstrap.md`](./api_bootstrap.md) for the wire contract. This doc
is the implementation and UX rules.

## The one-call cold start

A launch issues exactly **one** request. Build `view` from the launch intent
**before** anything renders:

| Launch intent | Request |
|---|---|
| Normal launch | `GET /api/bootstrap?address=X&view=feed:home&by=<sort>&allowed_tags=<tags>&limit=15` |
| Notification tap | `GET /api/bootstrap?address=X&view=thread:<replyId>` |
| Deep link to a thread | `view=thread:<postId>` |
| Launch onto inbox | `view=inbox` |
| Topic deep link | `view=topic:<name>` |

Anonymous launch omits `address` and still gets `node_config`, `chain_config`,
and the feed.

The `replyId` / `rootPostId` for the thread case are already in the push
payload (`shared/push.py` → `data.replyId`, `data.rootPostId`).

`by` and `allowed_tags` must come from the user's locally persisted preferences.
Without them the first painted feed can be sorted or filtered differently from
every refresh after it.

**Retire the old two-request launch** (`bootstrap` then `get_posts`). That
pattern is obsolete.

## Preventing layout shift

Hard requirement, not polish. Failure mode to design against: feed paints,
then the rewards card arrives seconds later and shoves the feed down.

Root cause historically: a section's **arrival** decided whether a card
existed. With one response that is fixable by rule:

1. **Existence of any above-feed card is decided by `node_config` feature
   flags only.** `node_config` is non-null on every successful bootstrap, so
   the full above-feed layout is known before first commit.
2. **`rewards_summary.disabled === true` counts as flag-off.** It arrives in
   the same response — a disabled-rewards node must never render the card
   and then remove it.
3. **A null section is not permission to collapse.** If a sub-handler
   errored but its flag is on, render the card at its natural height in a
   placeholder state and fill it in. Never collapse-then-expand.
4. **Nothing outside bootstrap may mount above existing content.** Late
   surfaces go below the fold, into reserved fixed-height space, or into an
   overlay. Never insert above the current scroll position.
5. **Hold the splash until the single response resolves, then commit the
   whole first screen at once.** Painting the feed early to *look* fast is
   what creates the shift. One commit is both faster and stable.
6. **Skeletons must match final heights**, and list items need stable keys
   so nothing reorders after paint.

## Thread screens

One `get_comments` call renders a complete thread. Response shape:

```json
{
  "root": { "...focused comment..." },
  "children": [ "...reply subtree..." ],
  "ancestors": [ "...root post first...", "...immediate parent last..." ],
  "ancestors_omitted": 0
}
```

Map onto the screen:

- `ancestors[0]` → the OP header
- `ancestors[1..]` → the parent chain, indenting toward the focused comment
- `root` → the focused comment (highlighted)
- `children` → the reply subtree (already nested)

Show "N more replies above" when `ancestors_omitted > 0`. A root post returns
`ancestors: []` and `ancestors_omitted: 0` — same renderer, no branching.

Because the payload is complete, scroll to the focused comment in the same
pass as first render — no post-layout correction, no debounce.

`get_comment_context` and `get_root_post_id` remain live for older builds.
New builds should not call them.

## Notification prefetch

On notification **receipt** (background / data-only push), not on tap: fire
`get_comments?post_id=<replyId>` and park it in a short-TTL cache. Tap then
reads from cache and paints instantly, revalidating behind the render.

If the app is cold, the launch `view=thread:<replyId>` covers it instead —
the two paths **must share one cache** so they never double-fetch.

**Bound this aggressively.** Each prefetch is a full thread query (~13
server queries). Naive receipt-prefetch turns a 50-notification burst into
50 thread fetches for threads nobody opens.

Required limits:

- Prefetch only the **single most recent** notification; a newer one
  replaces the pending prefetch rather than adding to it.
- Skip entirely when several notifications arrive within a short window
  (a burst means an active thread the user is probably already viewing).
- Never prefetch on a metered connection or in low-power mode.
- One in-flight prefetch at a time, shared with the cold-launch cache.

`inboxReply` in the push payload already carries `parent_content` and author
info — enough to paint a truthful skeleton at zero latency even when
prefetch is skipped.

## Freshness

| Section | Client cache | Invalidate when |
|---|---|---|
| `node_config` | 24h | Node/validator URL changed |
| `chain_config` | 4h | Governance param change (rare) |
| `user_status` | session | Balance-affecting tx |
| `user_followed` | 24h | Follow / unfollow / agent change |
| `user_blocked` | session | Block / unblock |
| `invite_codes` | session | Claim / redeem |
| `rewards_summary` | screen-driven | Rewards screen refresh / claim |
| `view` | **first paint only** | Never persist across launches |

Once the screen mounts it owns its own refresh cadence (`get_posts`,
`get_comments`, `get_inbox`).

## Calls that become unnecessary

| Old call | Status |
|---|---|
| Separate `get_chain_config` at launch | Covered by bootstrap `chain_config` |
| Separate `get_posts` at launch | Covered by `view=feed:*` |
| `get_comment_context` | Covered by `ancestors` on `get_comments` |
| `get_root_post_id` | Covered by `ancestors[0]` |
| `POST /api/get_upload_url` | **Removed** — use `/api/upload_media` |

Old routes (except `get_upload_url`) stay live so adoption can be incremental.
