# Sub-Plan 06.7 — Discover, NotFound

**Routes:** `/communities` (discover), fallback 404
**Files:** `themes/default/routes/{DiscoverView,NotFoundView}.js`
**Status:** ✅ Done
**Parent:** [`../06-remaining-routes-and-polish.md`](../06-remaining-routes-and-polish.md)

> **Trimmed in v1.39.0.** This sub-plan originally covered a third route, `/agents`
> (`AgentsView.js`). Agents were removed from Mirage entirely in v1.39.0: the route
> is gone, `AgentsView.js` was deleted, and `/agents` now 404s with no redirect. The
> agent sections of this file have been removed rather than left describing a screen
> that no longer exists. The Discover and NotFound work below still shipped and is
> still accurate, so the file is kept for that.

---

## Current state (pre-rewrite)

Both were near-identical (2–3 line diffs) copies of `themes/oldreddit/routes/*`. Oldreddit tokens everywhere.

---

## Goal

Finish the low-volume routes so every route key in the manifest uses default tokens.

---

## References

- **Mobile:** `mirage-mobile-app/src/pages/topics-list-screen.tsx`, `topic-feed-screen.tsx`
- **Web data:** `themes/bluemoon/routes/{DiscoverView,NotFoundView}.js`

---

## What shipped

### DiscoverView (`/communities`)
- 720px wrap (80% when sidebar hidden) with `-0.75rem` negative top margin, plus the heading pattern ("Communities") at `1.1rem / 700 / -0.01em` — matches Inbox / Follows / Settings rhythm.
- Pill-shaped `SearchField`: `HiMagnifyingGlass` icon + input + custom `HiXMark` clear button (18px).
  - Native webkit clear hidden via `::-webkit-search-cancel-button { display: none }` so only the custom cross shows.
  - Focus uses `borderStrong`, no blue ring (R5).
- Section headers with count badges for "All communities" / "Matching communities" / communities with fewer than 10 posts.
- Community rows: `#` icon circle + community link (`0.75rem / 500`) + optional tag badge (via shared `tagColors` from `useDiscover`) + meta `N posts · M comments` (`0.62rem / 500 / subtleText`) + Join/Joined/Leave `Button` with hover-to-Leave.
- States: loading spinner, error panel, empty (hashtag icon circle with search-aware copy), inline "Searching for more communities…" spinner for the long-tail search, footer hint counting remaining small communities.
- No full-bleed dividers; hover on `hoverBg` provides visual separation.

### NotFoundView
- Centered empty-state block inside the standard `TabbedContainer` / `ContainerBody` shell.
- `IconCircle` (64px, `border` only) with `HiOutlineMagnifyingGlass`.
- Hero **`404`** `2rem / 700 / -0.02em`.
- Title **"Page not found"** `1.1rem / 700`.
- Message `0.75rem / 500 / subtleText` max-width 24rem.
- Attempted path rendered in a monospace `PathPill` (`surface2` + `border`, `0.62rem / 500`) with `word-break: break-all`.
- Actions: `Go back` (subtle) + `Go home` (primary) using restyled `Button`.

This is the page the retired `/t/:slug`, `/topics` and `/agents` paths land on. There is no redirect from them.

---

## Out of scope (still true)

- Community model changes.

---

## Verification checklist

- [x] Both routes render on `bg` canvas (R1).
- [x] No `themes/oldreddit/*` imports.
- [x] Data parity with bluemoon preserved.
- [x] Build passes (`cd web/frontend && CI=true npm run build`).
- [ ] Dark + light manual QA (rolled into sub-plan 06.9).

---

## PR description template

> Rewrites `default`'s Discover / NotFound routes with R1–R7 tokens and mobile-app visuals. Visual only. Closes sub-plan 06.7.
