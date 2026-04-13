# Seen Posts Tracking — Integration Guide

This document defines the viewability protocol that clients (web and mobile) must implement to track which posts a user has seen, so the server can filter them from future feed responses.

## Architecture

```
Client                              Server
┌──────────────────────┐           ┌───────────────────────────┐
│ IntersectionObserver  │           │ GET /api/get_posts        │
│ or onViewableItems    │           │   ?feed=home              │
│         ↓             │           │   &seen=<id:reason,...>   │
│ State machine:        │  ──────> │         ↓                 │
│  not_seen → exposed   │           │ 1. Ingest seen IDs        │
│           → seen      │           │ 2. Load seen set (cached) │
│         ↓             │           │ 3. Filter candidates      │
│ In-memory buffer      │           │ 4. Return fresh posts     │
│         ↓             │           └───────────────────────────┘
│ Piggyback on next     │
│ get_posts request     │           ┌───────────────────────────┐
│         ↓             │           │ POST /api/seen_posts      │
│ sendBeacon / onPause  │  ──────> │ (fallback flush endpoint) │
│ flush on background   │           └───────────────────────────┘
└──────────────────────┘
```

## Post ID Format

All post IDs are full 64-character tx hashes (lowercase hex). Always normalize client-side by trimming whitespace and lowercasing.

## Viewability State Machine

Each post card transitions through three states:

```
not_seen ──→ exposed ──→ seen
```

- **not_seen**: Default. Post has not entered the viewport.
- **exposed**: Post has been in the viewport at least once but hasn't met any "seen" threshold yet. Track exposure count here.
- **seen**: Post crossed a threshold. Emit a seen event **once** and stop tracking.

### Transition Rules (not_seen → seen)

| Trigger | Condition | Reason string |
|---------|-----------|---------------|
| Click / open | User taps post to view detail | `open` |
| Vote | User up/downvotes the post | `vote` |
| Reply | User replies to the post | `reply` |
| Dwell | ≥50% of card visible in center 40% of viewport for ≥3 seconds, tab/app in foreground | `dwell` |
| Repeated glance | 2+ exposures of ≥500ms each with ≥40% card visibility | `glance` |

### Rules

1. **Foreground only**: Only count visibility time when the app is in the foreground.
   - Web: `document.visibilityState === 'visible'`
   - Mobile: track `onResume` / `onPause` lifecycle events
2. **Center band**: For dwell detection, only count time when the card is in the middle 40% of the viewport (top 30% and bottom 30% are excluded). This avoids counting posts that are barely on-screen at the edges.
3. **Pause timers on background**: If the app goes to background mid-dwell, cancel the timer. Resume fresh when the app comes back.
4. **Deduplicate**: Keep a `Set<string>` of already-reported IDs. Never emit the same ID twice in a single session. Persist this set in `sessionStorage` (web) or equivalent (mobile) so it survives page refreshes. Cap at 2000 IDs; if exceeded, clear and start fresh.
5. **Interactions are immediate**: Click/vote/reply transitions happen instantly with no visibility check needed.
6. **First trigger wins**: Dwell and glance timers run in parallel. Whichever fires first marks the post as seen; cancel the other timer immediately. For example, if glance reaches 2 exposures before the 3s dwell elapses, cancel the dwell timer (and vice versa).

## Reporting Protocol

### Primary: Piggyback on `get_posts`

When the client makes a feed request, attach buffered seen IDs as a query parameter (include the reason per entry):

```
GET /api/get_posts?feed=home&page=1&address=mirage1...&seen=<txhash>:open,<txhash>:glance
```

- Comma-separated `id:reason` pairs (full txhash)
- Maximum **100 IDs** per request
- The server ingests them as a side-effect and filters them from the response
- Piggyback works on **all** `get_posts` calls (any feed). Ingestion always happens; server-side filtering of seen posts currently applies to **home** and **following** feeds only.
- **Zero extra HTTP requests** — the data rides along with requests you're already making

Requests must include a signed payload to authenticate the address:

```
seen_pubkey=<base64 pubkey>
seen_signature=<base64 signature>
seen_timestamp=<ms>
seen_envelope_nonce=<uint64>
```

Signature payload string (client-side):

```
seen_posts:<address-lowercase>:<timestamp-ms>:<envelope_nonce>
```

### Fallback: Beacon flush on background

When the app goes to background (tab close, app pause), flush any remaining buffered IDs via:

```
POST /api/seen_posts
Content-Type: application/json

{
  "address": "mirage1abc...",
  "posts": [
    {"id": "<txhash>", "reason": "dwell"},
    {"id": "<txhash>", "reason": "glance"}
  ],
  "pubkey": "<base64 pubkey>",
  "signature": "<base64 signature>",
  "timestamp": 1712940000000,
  "envelope_nonce": 123456789
}
```

- Web: use `navigator.sendBeacon()` on `visibilitychange` / `pagehide`
- Mobile: call this endpoint from `onPause` or equivalent lifecycle callback
- **Periodic flush**: In addition to background-triggered flushes, run a **10-second interval timer** that flushes the buffer if non-empty. This timer should start on the first `markSeen` call and run for the lifetime of the app session (not tied to any single screen).
- Maximum **100 entries** per batch
- Response: `{"ok": true, "ingested": <count>}`

## Mobile Implementation Guide

Seen reporting must be signed. Use the user's key to sign the payload string:

```
seen_posts:<address-lowercase>:<timestamp-ms>:<envelope_nonce>
```

Include `pubkey`, `signature`, `timestamp`, and `envelope_nonce` with both piggyback GET requests and the beacon POST.

### React Native (FlatList / FlashList)

Use `onViewableItemsChanged` with a custom viewability config:

```javascript
const viewabilityConfig = {
  itemVisiblePercentThreshold: 40,
  minimumViewTime: 500,
};

const onViewableItemsChanged = useCallback(({ viewableItems }) => {
  if (AppState.currentState !== 'active') return;
  for (const item of viewableItems) {
    const pid = item.item?.post_id;
    if (!pid) continue;
    recordExposure(pid); // increment glance count, mark at 2
  }
}, []);
```

For dwell detection, start a 3-second timer when a post becomes viewable and cancel it when it leaves. Only count time while `AppState.currentState === 'active'`.

### Native Android (RecyclerView)

Attach an `OnScrollListener` or use a custom `LayoutManager` callback to track which `ViewHolder` items have ≥40% visibility. Use `Lifecycle.Event.ON_PAUSE` / `ON_RESUME` to gate tracking.

### Native iOS (UICollectionView)

Use `UICollectionViewDelegate` methods (`willDisplay` / `didEndDisplaying`) combined with a periodic check for center-band positioning. Gate on `UIApplication.State.active`.

### Mark on Navigation

When the user taps a post to open the detail view, immediately call `markSeen(postId, "open")`. This must work regardless of which screen the user is on — the buffer and flush timer are global, not tied to the feed screen.

Similarly, call `markSeen(postId, "vote")` on vote and `markSeen(postId, "reply")` on reply. These are instant transitions — no visibility check needed.

### Flush on Background

```javascript
// React Native
useEffect(() => {
  const sub = AppState.addEventListener('change', (state) => {
    if (state === 'background' || state === 'inactive') {
      flushSeenBuffer(); // POST /api/seen_posts
    }
  });
  return () => sub.remove();
}, []);
```

## Error Handling

- **Bounded retries**: Maximum 2 retries for the beacon/flush endpoint. Drop buffer after that.
- **No infinite loops**: If flush fails twice, discard the buffer and move on.
- **Graceful degradation**: If seen tracking fails entirely, the feed still works — users just see some repeat posts.
- **No blocking**: Seen ingestion must never block the feed response or the UI thread.

## Server Behavior

- The server stores full post IDs per user and keeps only the **most recent 1000** entries (deque semantics).
- Each seen entry tracks a **view count** that increments on every subsequent report of the same post. Re-sending an already-seen ID is not a no-op — it bumps the counter and refreshes the timestamp.
- On feed requests, the server loads the user's seen map and filters matching candidates from the response.
- The user's **own posts from the last hour are never filtered**. Own posts older than 1 hour are treated like any other post (subject to seen filtering, tag filtering, etc.).
- Guest users have no seen tracking.
- If all candidates are seen, the server reintroduces seen posts **sorted by view count ascending** (least-viewed first) to avoid empty feeds.
- The seen map (post ID → view count) is cached in-memory on the server (120s TTL) so repeated page loads don't hit the database.
