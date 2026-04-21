# Sub-Plan 06.7 — Agents, Discover, NotFound

**Routes:** `/agents`, `/topics` (discover), fallback 404
**Files:** `themes/mirageapp/routes/{AgentsView,DiscoverView,NotFoundView}.js`
**Status:** ✅ Done
**Parent:** [`../06-remaining-routes-and-polish.md`](../06-remaining-routes-and-polish.md)

---

## Current state (pre-rewrite)

All three were near-identical (2–3 line diffs) copies of `themes/oldreddit/routes/*`. Oldreddit tokens everywhere.

---

## Goal

Finish the low-volume routes so every route key in the manifest uses mirageapp tokens.

---

## References

- **Mobile:** `mirage-mobile-app/src/pages/topics-list-screen.tsx`, `topic-feed-screen.tsx`
- **Web data:** `themes/bluemoon/routes/{AgentsView,DiscoverView,NotFoundView}.js`

---

## What shipped

### AgentsView
- 720px `AgentsWrap` (80% when sidebar hidden) with `-0.75rem` negative top margin — matches Inbox / Follows / Settings rhythm.
- Heading **"Agents"** `1.1rem / 700 / -0.01em`.
- Intro block: three paragraphs at `0.75rem / 500 / cardBodyText` explaining Mirage's open moderation model; `<strong>` / `<em>` emphasis routed through `text` token.
- Section headers (`SectionLabel`) adapted from `SettingsView`: `0.6rem / 700 / uppercase / 0.06em`, followed by a `CountBadge` pill (`surface2` / `subtleText`).
- Reorder bar (only when `enabledCount > 1`): `HiArrowsUpDown` icon + hint + inline **Apply Order** `Button`.
- Each row is a flex column — `RowHeader` line (avatar + `Identity` + `Actions`) center-aligned, `Bio` below spanning the full row width:
  - Avatar: 36px dicebear, `surface3` fallback.
  - Name: `NameLink` `0.75rem / 500`, hover → `link`.
  - `AgentBadge` uses `voteDownBg` + `voteDown` pill (red).
  - `LastActive` `0.62rem / 500 / subtleText`.
  - Bio: `0.7rem / 500 / cardBodyText` (matches post body color).
- Reorder buttons use `HiChevronDown` rotated 180° for up (per R6 icon-normalization); neutral `borderStrong` focus on hover (R5).
- Enable / Enabled↔Disable uses `Button` `primary` / `subtle` / `primaryDanger` variants with hover swap for destructive intent.
- **No dividers** on Intro / Reorder / Rows (matches the decision for AgentsView to lean on hover-only separation).
- States: loading spinner, error panel (`HiExclamationTriangle` + `voteDown`), empty (`HiUserGroup`).
- Removed the old `<Navigate to="/home" replace />` for logged-out users — page now stays browsable, buttons just disable when there's no signer.

### DiscoverView (`/topics`)
- Same 720px wrap + heading pattern ("Topics").
- Pill-shaped `SearchField`: `HiMagnifyingGlass` icon + input + custom `HiXMark` clear button (18px).
  - Native webkit clear hidden via `::-webkit-search-cancel-button { display: none }` so only the custom cross shows.
  - Focus uses `borderStrong`, no blue ring (R5).
- Section headers with count badges for "All topics" / "Matching topics" / "Topics with fewer than 10 posts".
- Topic rows: `#` icon circle + `#topic` link (`0.75rem / 500`) + optional tag badge (via shared `tagColors` from `useDiscover`) + meta `N posts · M comments` (`0.62rem / 500 / subtleText`) + Follow/Following/Unfollow `Button` with hover-to-Unfollow.
- States: loading spinner, empty (hashtag icon circle with search-aware copy), inline "Searching for more topics…" spinner for the long-tail search, footer hint counting remaining small topics.
- No full-bleed dividers; hover on `hoverBg` provides visual separation.

### NotFoundView
- Centered empty-state block inside the standard `TabbedContainer` / `ContainerBody` shell.
- `IconCircle` (64px, `border` only) with `HiOutlineMagnifyingGlass`.
- Hero **`404`** `2rem / 700 / -0.02em`.
- Title **"Page not found"** `1.1rem / 700`.
- Message `0.75rem / 500 / subtleText` max-width 24rem.
- Attempted path rendered in a monospace `PathPill` (`surface2` + `border`, `0.62rem / 500`) with `word-break: break-all`.
- Actions: `Go back` (subtle) + `Go home` (primary) using restyled `Button`.

---

## Out of scope (still true)

- Topic model changes.
- Agent list filtering beyond what bluemoon shows.

---

## Verification checklist

- [x] All three routes render on `bg` canvas (R1).
- [x] No `themes/oldreddit/*` imports.
- [x] Data parity with bluemoon preserved.
- [x] Build passes (`cd web/frontend && CI=true npm run build`).
- [ ] Dark + light manual QA (rolled into sub-plan 06.9).

---

## PR description template

> Rewrites `mirageapp`'s Agents / Discover / NotFound routes with R1–R7 tokens and mobile-app visuals. Visual only. Closes sub-plan 06.7.
