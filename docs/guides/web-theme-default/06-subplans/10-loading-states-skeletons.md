# Sub-Plan 06.10 — Loading states + skeletons

**Status:** ✅ Done
**Parent:** [`../06-remaining-routes-and-polish.md`](../06-remaining-routes-and-polish.md)

---

## Goal

Replace the inherited `oldreddit`-style "loading…" text (and any ad-hoc spinners) across the `default` theme with consistent, token-driven loading states that match `mirage-mobile-app`:

- **Feed-like lists** → skeleton rows that mirror the real card/row layout.
- **Detail pages** → skeleton headers + body blocks sized to the real content.
- **Small controls** → subtle pulse on pill/button placeholders, not plain text.
- **Inline / async content** (markdown previews, media) → skeleton that reserves the final height to avoid layout shift.

Perceived performance > actual performance — a well-shaped skeleton should make every route feel ~200ms faster without any data-layer change.

---

## Current state (audit targets)

Routes / components that currently render `Loading…`, an empty panel, or a bare spinner while data is in flight. **Before coding, grep to confirm the latest list** — some of these may have been tightened during 06.1–06.8:

```bash
rg -n "Loading|Loading\.\.\.|isLoading|loading\b|Spinner" web/frontend/src/themes/default
```

Likely candidates (to verify):

- `ListFeedView.js` / `CardView.js` — initial feed fetch + pagination.
- `routes/ProfileView.js` — profile header + submissions / comments tabs.
- `routes/InboxView.js` — reply list.
- `routes/ViewPostView.js` — post body + comment tree.
- `routes/SearchResultsView.js` — results list.
- `routes/NetworkView.js`, `routes/StatsView.js` — info panels + charts.
- `routes/AgentsView.js`, `routes/DiscoverView.js` — topic / agent lists.
- `routes/FollowsView.js`, `routes/BlocksView.js`, `routes/ReportsView.js` — list rows.
- `routes/SubscriptionView.js`, `routes/ReferralsView.js` — tier / invite panels.
- `components/SearchDropdown.js` — typeahead results.
- `components/TopicSelector.js` — topic menu fetch.

---

## References

- **Mobile:** `mirage-mobile-app/src/components/atoms/skeleton.tsx` (or the closest analogue) + any `*-placeholder.tsx` molecules.
- **Web tokens:** default `panel` / `panelAlt` / `borderSubtle` / `hoverBg` for the two-stop pulse gradient.
- **Existing patterns:** oldreddit / bluemoon handle loading with plain text — do NOT copy those. Build skeletons fresh in `default`.

---

## Deliverables

### 1. New primitive — `components/Skeleton.js`

A small, tokenized building block reused by every route. Minimum API:

```js
<Skeleton width="100%" height="1rem" radius="4px" />
<SkeletonText lines={3} />            // stacked lines with varying widths
<SkeletonCircle size={32} />          // avatars
<SkeletonBlock aspect="16/9" />       // media placeholders
```

Requirements:

- Pulse animation driven by `@keyframes`; respects `prefers-reduced-motion` (fallback = flat tile, no animation).
- Background uses `panelAlt`; shimmer uses `hoverBg` / `borderSubtle` at 40–60% opacity.
- Radius matches the component it's standing in for (`4px` default, `50%` for circle, `12px` for card).
- No fixed colors — read from theme so dark + light both work.

### 2. Route-level skeleton components

For each audited route, add a sibling loader component next to the real view (co-located, not shared):

- `FeedCardSkeleton` — mirrors `CardView` row (avatar + title + meta + actions).
- `CommentSkeleton` — mirrors comment tree indent + body.
- `InfoPanelSkeleton` — label + value rows (Network / Stats / Subscription).
- `ListRowSkeleton` — used by Follows / Blocks / Reports / Agents / Discover / Referrals.
- `ProfileHeaderSkeleton` — avatar circle + display name + stats row.

Render N skeletons (typically 3–6) while `isLoading && !data`. Once real data arrives, fade in — don't pop.

### 3. Replace inline "Loading…" text

Every `"Loading"` / `"Loading..."` string in `themes/default/**` must be either:

- Replaced with the appropriate skeleton, OR
- Deleted if the skeleton already covers the same area.

Empty states (no results) are **not** skeletons — keep the existing empty-card pattern (`EmptyCard` / `EmptyTitle` / `EmptyBody` in `Layout.js`).

### 4. Pagination / "loading more" state

Infinite feeds (home, profile submissions, inbox) use a single `FeedCardSkeleton` appended at the bottom of the list while the next page is in flight. No centered spinner.

---

## Out of scope

- Data-fetching changes (timings, caching, prefetching).
- Error states — those stay as-is (tracked separately in 06.9 polish).
- Optimistic-update UI for votes/comments (already handled).
- Animations beyond the pulse + fade-in.

---

## Requirements (R1–R7 recap)

- **R1 (single canvas):** skeletons sit on `bg`. The skeleton tile itself uses `panelAlt` so it reads as a lifted placeholder, not a second canvas.
- **R2 (tokens only):** no raw hex values; use `panelAlt` / `hoverBg` / `borderSubtle`.
- **R3 (dividers):** if a skeleton row implies a divider (e.g. list rows), use the same `border` / `headerBorder` tokens the real row will use.
- **R5 (no blue ring):** skeleton is non-interactive; no focus ring, no hover state.
- **R7 (typography):** reserve heights that match the real type scale (`1rem` for body, `1.25rem` for headings) so there's zero layout shift on hydration.

---

## Verification checklist

- [ ] `components/Skeleton.js` exists and is exported from `themes/default/index.js`.
- [ ] Every audited route shows a shape-matched skeleton on cold load (throttle network to Slow 3G and reload).
- [ ] No `Loading…` / `Loading...` strings remain in `themes/default/**` outside of tests.
- [ ] No centered `Spinner` component rendered as a page-level loader.
- [ ] Pulse animation disabled when `prefers-reduced-motion: reduce`.
- [ ] Dark + light verified on at least 3 routes (feed, profile, inbox).
- [ ] No cross-theme component imports introduced.
- [ ] Build passes:

```bash
cd web/frontend
CI=true npm run build
```

---

## Ordering

Runs **after 06.8** and **before 06.9**. Polish + QA (06.9) should sweep the finished skeletons as part of its dark/light + breakpoint pass.

---

## PR description template

> Adds a tokenized `Skeleton` primitive and per-route skeleton loaders across `default`, replacing the inherited `Loading…` text and bare spinners. No data-layer changes. Closes sub-plan 06.10.
