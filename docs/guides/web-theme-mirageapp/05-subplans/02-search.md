# Sub-Plan 05.2 — Search

**Routes / surfaces:**
- `/search?q=...` → full results view
- TopBar search input → dropdown sheet (recents + trending + live results)

**Files:**
- `web/frontend/src/themes/mirageapp/routes/SearchResultsView.js` (rewritten)
- `web/frontend/src/themes/mirageapp/components/SearchDropdown.js` (new)
- `web/frontend/src/themes/mirageapp/components/TopBar.js` (search input wired to dropdown)
- `web/frontend/src/logic/useSearchDropdown.js` (new hook — visual infra only, `useSearchResults` untouched)

**Status:** ✅ Done
**Parent:** [`../05-inbox-search-settings-auth.md`](../05-inbox-search-settings-auth.md)

> Shipped the full mobile-app-style search flow: TopBar input opens a dropdown sheet showing recent searches + trending topics on focus, debounces live search results while typing, and on submit navigates to `/search?q=...` where results are presented in a tabbed layout (Posts / Topics / Users) matching the mobile `search-screen.tsx` visuals.

---

## Final shipped state

### 1. TopBar dropdown sheet (new behaviour)

When the user focuses the TopBar search input in `themes/mirageapp/components/TopBar.js`, a `SearchDropdown` sheet opens directly below the input with:

**Idle (empty query):**
- **Recent** section — localStorage-backed list (`mirage_recent_searches`, max 8).
  - Each row: clock icon + query + per-row remove button (×).
  - "Clear all" button in the section header.
  - Click a recent row → repeats the search (navigates to `/search?q=...`).
- **Trending topics** — top 10 topics from `Api.get('get_topics', { limit: 40, min_posts: 10 })`, sorted by `post_count`. Each row: fire icon + `#topic` + post count. Click → `/t/{topic}`.

**Typing (non-empty query):**
- Debounced (300 ms) call to `Api.get('search', { q, limit: 5 })` returning `{ posts, users, topics }`.
- Grouped sections: **Topics**, **Users**, **Posts** (up to 5 each), separated by the feed divider (`theme.colors.border`).
- Each row navigates to its destination (`/t/{topic}`, `/u/{username}`, `/p/{post_id}`).
- **"See all results for \"q\""** footer row pinned at the bottom — submits the query (adds to recents + navigates to `/search?q=...`).
- Empty state: "No quick results. Press Enter to search everywhere."
- Loading state: "Searching…"
- Error state: friendly error message.

**Interactions:**
- `onFocus` → open dropdown.
- Click outside (via `mousedown` listener on the search wrapper ref) → close.
- `Escape` key → close + blur input.
- Route change → close (listens to `location.pathname` + `location.search`).
- Clicking any row uses `onMouseDown preventDefault` so focus stays on the input until after navigation.
- Clear button (`×`) inside the input resets the query without closing the sheet.

### 2. `/search` full results view — `SearchResultsView.js`

Complete rewrite. Still consumes the existing `useSearchResults` hook (untouched — data parity with bluemoon preserved).

**Layout:**
- Lives inside `ContainerBody` → `SearchWrap` (same 720px max-width + sidebar-hidden 80% expansion pattern as `InboxWrap`).
- Header row: plain "Search" title (1.1rem / weight 700 / letter-spacing -0.01em) — matches Inbox header.
- Sub-header: `Results for "{displayQuery}"` in `subtleText`.

**Tabs:**
- 3-column grid `TabsRow` (`Posts / Topics / Users`) with:
  - Active tab: `theme.colors.text`, weight 600.
  - Inactive tab: `theme.colors.subtleText`, weight 500.
  - Count badge per tab: `focusBlue` fill + `buttonText` text when active, `accent` fill + `subtleText` text when inactive. Shows `99+` cap.
  - `TabIndicator` — 2px tall `focusBlue` bar positioned by `transform: translateX({index * 100%})` with a 200 ms transition.
  - `border-bottom: 1px solid theme.colors.border` (R3).
- If the default tab (`posts`) is empty but another tab has results, auto-jumps to the first tab that has hits (keeps the page useful for `@user` or `#topic` queries).

**Posts tab:**
- Renders via the theme-local `CardView` component (no custom post row). Spreads the useSearchResults post shape into the full `CardView` post object (same fields bluemoon uses).
- "Load more posts" button below the list → calls `loadMorePosts` from the hook.
- Empty state: `HiOutlineDocumentText` + "No posts found".

**Topics tab:**
- Full-bleed `RowItem` rows (`Link`), divider `1px solid theme.colors.border`, hover `theme.colors.hoverBg`.
- Each row: `HiOutlineHashtag` icon (28×28), `#topic` primary line (0.78rem / weight 600), post count meta line (0.62rem / `subtleText`).
- "Load more topics" button.
- Empty state: `HiOutlineHashtag` + "No topics found".

**Users tab:**
- Full-bleed rows (same style as topics).
- Each row: `HiOutlineUser` icon, tier-colored `@username` with hover tooltip (`getAuthorColor` + `getAuthorTooltip`), meta line `{postCount} posts · joined {formatDate(created_at)}`.
- "Load more users" button.
- Empty state: `HiOutlineUser` + "No users found".

**State blocks:** shared `StateBlock` primitives with `StateIcon` / `StateTitle` / `StateMessage`:
- Loading: `LoadingSpinner` centered with "Searching for \"q\"…" sub-header.
- Error: `HiExclamationTriangle` tinted `voteDown` + "Something went wrong".
- Empty / no query: `HiOutlineMagnifyingGlass` + friendly copy.
- No results: `HiOutlineMagnifyingGlass` + helpful suggestions (`@name`, `#topic`).
- Logged-out: reuses existing `LoggedOutPromptCard` from Plan 04.

### 3. `useSearchDropdown.js` — visual infrastructure hook

New hook at `web/frontend/src/logic/useSearchDropdown.js`. Purpose: own all dropdown-sheet state so `TopBar.js` stays small. Does **not** touch `useSearchResults.js`.

**Returns:**
```
{
    rawQuery, setQuery, resetQuery,
    debouncedQuery, isSearching, liveResults, liveError,
    hasQuery, hasLiveResults,
    trendingTopics, isLoadingTrending,
    recentSearches, addRecentSearch, removeRecentSearch, clearRecentSearches
}
```

**Internals:**
- Debounces `rawQuery` → `debouncedQuery` at 300 ms.
- Calls `Api.get('search', { q, limit: 5, address?, allowed_tags })` on every debounced change.
- Loads trending topics once per `viewerAddress` via `Api.get('get_topics', { limit: 40, min_posts: 10 })`, sorts by `post_count`, keeps top 10.
- Persists recents to `localStorage` under `mirage_recent_searches` (capped at 8, mirror of mobile's zustand store shape: `{ id, query, timestamp }[]`).
- Deduplicates recents by lowercased query.
- Mount-guard flag via `mountedRef` to prevent state updates after unmount.

---

## Rules compliance (`../RULES.md`)

- ✅ **R1 single-bg canvas** — SearchResultsView sits on `theme.colors.bg` via the shared `ContainerBody` (already fixed in Plan 05.1). No page-level `panel` fill. `SearchDropdown` is a **contained surface** (menu popover) so it legitimately uses `menuBg` per R1's "lifted surfaces" carve-out.
- ✅ **R2 tokens only** — every color routed through existing tokens:
  - `bg`, `text`, `subtleText`, `border`, `hoverBg`, `focusBlue`, `buttonText`, `accent`, `voteDown`, `panel`, `menuBg`, `menuItemHoverBg`, `menuItemHoverText`, `menuHeaderText`, `sidebarItemText`, `sidebarItemActiveText`, `scrollbar`, `inputIconHoverBg`.
  - No raw hex / rgba in either new file.
  - **No new tokens added** — everything mapped cleanly to existing R2 pairs.
- ✅ **R3 feed divider** — only `1px solid theme.colors.border` used. Applied to: TabsRow bottom, RowItem bottom, SectionDivider inside dropdown, SeeAllRow top border, dropdown outer border.
- ✅ **R4 reference check**:
  - Read `themes/bluemoon/routes/SearchResultsView.js` — data fields preserved (topics + users + posts + load-more per tab + tier colors + join date).
  - Read `mirage-mobile-app/src/pages/search-screen.tsx` — visuals mirror the mobile screen: idle sheet (recent + trending), tabbed results with underline indicator + count badges, row-style topic/user results, post cards via shared card component.
  - `useSearchResults` **untouched** (visual only).

---

## Verification

- [x] Dropdown opens on focus, closes on click-outside / Escape / route change.
- [x] Recent searches persist in localStorage across reloads.
- [x] Trending topics load once and render even for guest viewers.
- [x] Debounced live results render posts / users / topics grouped with dividers.
- [x] "See all" footer submits the query and navigates to `/search?q=...`.
- [x] `/search?q=...` renders in the shell with Posts / Topics / Users tabs.
- [x] Tab indicator slides to the active tab, count badges update correctly.
- [x] Auto-jumps to the first tab with results if default tab is empty.
- [x] Load-more buttons work per tab (hook untouched).
- [x] Empty / loading / error states styled via shared `StateBlock`.
- [x] Logged-out prompt card still shown.
- [x] Build passes: `cd web/frontend && CI=true npm run build` → ✅ Compiled successfully, no warnings.
- [ ] Dark + light mode final manual browser check (recommended).
- [ ] Desktop + mobile layouts final manual browser check (recommended — mobile TopBar hides ≤800px so the dropdown is desktop-first; mobile MobileHeader already links to `/search`).

---

## Files changed

- `web/frontend/src/logic/useSearchDropdown.js` — new, 238 lines.
- `web/frontend/src/themes/mirageapp/components/SearchDropdown.js` — new, ~508 lines.
- `web/frontend/src/themes/mirageapp/components/TopBar.js` — search input wired to the dropdown (focus / blur / click-outside / Escape, submit goes through `useSearchDropdown.addRecentSearch`).
- `web/frontend/src/themes/mirageapp/routes/SearchResultsView.js` — full rewrite, tabbed layout, reuses `useSearchResults`.

No token changes, no RULES.md changes.

---

## PR description template

> Ships Plan 05.2 Search: adds a TopBar dropdown sheet (recent searches + trending topics + debounced live results) and rewrites `/search` with a mobile-app-style tabbed layout (Posts / Topics / Users). Introduces a new `useSearchDropdown` hook for dropdown infrastructure — `useSearchResults` untouched. All colors routed through existing R2 tokens, dividers via `theme.colors.border` (R3), visuals from `mirage-mobile-app/src/pages/search-screen.tsx` with full bluemoon data parity (R4).
