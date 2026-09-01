# Sub-Plan 05.2 — Search

**Routes / surfaces:**
- `/search?q=...` → full results view
- TopBar search input → dropdown sheet (recents + trending + live results)

**Files:**
- `web/frontend/src/themes/default/routes/SearchResultsView.js` (rewritten)
- `web/frontend/src/themes/default/components/SearchDropdown.js` (new)
- `web/frontend/src/themes/default/components/TopBar.js` (search input wired to dropdown)
- `web/frontend/src/logic/useSearchDropdown.js` (new hook — visual infra only, `useSearchResults` untouched)

**Status:** ✅ Done
**Parent:** [`../05-inbox-search-settings-auth.md`](../05-inbox-search-settings-auth.md)

> Shipped the full mobile-app-style search flow: TopBar input opens a dropdown sheet showing recent searches + trending communities on focus, debounces live search results while typing, and on submit navigates to `/search?q=...` where results are presented in a tabbed layout (Posts / Communities / Users) matching the mobile `search-screen.tsx` visuals.

---

## Final shipped state

### 1. TopBar dropdown sheet (new behaviour)

When the user focuses the TopBar search input in `themes/default/components/TopBar.js`, a `SearchDropdown` sheet opens directly below the input with:

**Idle (empty query):**
- **Recent** section — localStorage-backed list (`mirage_recent_searches`, max 8).
  - Each row: clock icon + query + per-row remove button (×).
  - "Clear all" button in the section header.
  - Click a recent row → repeats the search (navigates to `/search?q=...`).
- **Trending communities** — top 10 communities from `Api.get('communities', ...)`, sorted by `post_count`. Each row: fire icon + community name + post count. Click → `/c/{community}`.

**Typing (non-empty query):**
- Debounced (300 ms) call to `Api.get('search', { q, limit: 5 })` returning `{ posts, users, communities }`.
- Grouped sections: **Communities**, **Users**, **Posts** (up to 5 each), separated by the feed divider (`theme.colors.border`).
- Each row navigates to its destination (`/c/{community}`, `/u/{username}`, `/p/{post_id}`).
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
- 3-column grid `TabsRow` (`Posts / Communities / Users`) with:
  - Active tab: `theme.colors.text`, weight 600.
  - Inactive tab: `theme.colors.subtleText`, weight 500.
  - Count badge per tab: `focusBlue` fill + `buttonText` text when active, `accent` fill + `subtleText` text when inactive. Shows `99+` cap.
  - `TabIndicator` — 2px tall `focusBlue` bar positioned by `transform: translateX({index * 100%})` with a 200 ms transition.
  - `border-bottom: 1px solid theme.colors.border` (R3).
- If the default tab (`posts`) is empty but another tab has results, auto-jumps to the first tab that has hits (keeps the page useful for `@user` or `#community` queries).

**Posts tab:**
- Renders via the theme-local `CardView` component (no custom post row). Spreads the useSearchResults post shape into the full `CardView` post object (same fields bluemoon uses).
- "Load more posts" button below the list → calls `loadMorePosts` from the hook.
- Empty state: `HiOutlineDocumentText` + "No posts found".

**Communities tab:**
- Full-bleed `RowItem` rows (`Link`), divider `1px solid theme.colors.border`, hover `theme.colors.hoverBg`.
- Each row: `HiOutlineHashtag` icon (28×28), community name primary line (0.78rem / weight 600), post count meta line (0.62rem / `subtleText`).
- "Load more communities" button.
- Empty state: `HiOutlineHashtag` + "No communities found".

**Users tab:**
- Full-bleed rows (same style as communities).
- Each row: `HiOutlineUser` icon, tier-colored `@username` with hover tooltip (`getAuthorColor` + `getAuthorTooltip`), meta line `{postCount} posts · joined {formatDate(created_at)}`.
- "Load more users" button.
- Empty state: `HiOutlineUser` + "No users found".

**State blocks:** shared `StateBlock` primitives with `StateIcon` / `StateTitle` / `StateMessage`:
- Loading: `LoadingSpinner` centered with "Searching for \"q\"…" sub-header.
- Error: `HiExclamationTriangle` tinted `voteDown` + "Something went wrong".
- Empty / no query: `HiOutlineMagnifyingGlass` + friendly copy.
- No results: `HiOutlineMagnifyingGlass` + helpful suggestions (`@name`, `#community`).
- Logged-out: reuses existing `LoggedOutPromptCard` from Plan 04.

### 3. `useSearchDropdown.js` — visual infrastructure hook

New hook at `web/frontend/src/logic/useSearchDropdown.js`. Purpose: own all dropdown-sheet state so `TopBar.js` stays small. Does **not** touch `useSearchResults.js`.

**Returns:**
```
{
    rawQuery, setQuery, resetQuery,
    debouncedQuery, isSearching, liveResults, liveError,
    hasQuery, hasLiveResults,
    trendingCommunities, isLoadingTrending,
    recentSearches, addRecentSearch, removeRecentSearch, clearRecentSearches
}
```

**Internals:**
- Debounces `rawQuery` → `debouncedQuery` at 300 ms.
- Calls `Api.get('search', { q, limit: 5, address?, allowed_tags })` on every debounced change.
- Loads trending communities once per `viewerAddress` via `Api.get('communities', ...)`, sorts by `post_count`, keeps top 10, and caches the result for 5 minutes.
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
  - Read `themes/bluemoon/routes/SearchResultsView.js` — data fields preserved (communities + users + posts + load-more per tab + tier colors + join date).
  - Read `mirage-mobile-app/src/pages/search-screen.tsx` — visuals mirror the mobile screen: idle sheet (recent + trending), tabbed results with underline indicator + count badges, row-style community/user results, post cards via shared card component.
  - `useSearchResults` **untouched** (visual only).

---

## Verification

- [x] Dropdown opens on focus, closes on click-outside / Escape / route change.
- [x] Recent searches persist in localStorage across reloads.
- [x] Trending communities load once and render even for guest viewers.
- [x] Debounced live results render posts / users / communities grouped with dividers.
- [x] "See all" footer submits the query and navigates to `/search?q=...`.
- [x] `/search?q=...` renders in the shell with Posts / Communities / Users tabs.
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
- `web/frontend/src/themes/default/components/SearchDropdown.js` — new, ~508 lines.
- `web/frontend/src/themes/default/components/TopBar.js` — search input wired to the dropdown (focus / blur / click-outside / Escape, submit goes through `useSearchDropdown.addRecentSearch`).
- `web/frontend/src/themes/default/routes/SearchResultsView.js` — full rewrite, tabbed layout, reuses `useSearchResults`.

No token changes, no RULES.md changes.

---

## PR description template

> Ships Plan 05.2 Search: adds a TopBar dropdown sheet (recent searches + trending communities + debounced live results) and rewrites `/search` with a mobile-app-style tabbed layout (Posts / Communities / Users). Introduces a new `useSearchDropdown` hook for dropdown infrastructure — `useSearchResults` untouched. All colors routed through existing R2 tokens, dividers via `theme.colors.border` (R3), visuals from `mirage-mobile-app/src/pages/search-screen.tsx` with full bluemoon data parity (R4).

---

## Polish follow-ups (shipped after initial PR)

Additional iterations landed on top of the initial ship during design review. All of them are visual-only and remain RULES-compliant.

### Dropdown sheet polish

- **Canvas + hover tokens.** Dropdown uses `menuBg` (`rgb(25,28,31)` dark / `rgb(255,255,255)` light). Row text at rest uses `sidebarItemText` (same as CardView post-options menu) and lifts to `menuItemHoverText` on hover. Hover background uses `menuSelectedBg` (the stronger pair) so rows have a visible tile under the cursor. Row leading icons inherit the text color lift on hover.
- **Typography tightened.** Section labels `0.55rem / 500` with tighter tracking. Result row primary `0.66rem / 500`, secondary `0.56rem / 500`. Empty-state copy `0.62rem / 500`. Footer `SeeAllRow` `0.58rem / 500` with a tighter `gap: 0.3rem` so the magnifier and label read as one cluster (new `SeeAllIcon` inline primitive replaces the fixed-width `RowIcon` slot for the footer).
- **Community rows.** Removed the `#` prefix from community primary text (both trending and live sections). The leading hashtag / fire icon already signals the row type — matches the mobile app pattern.
- **Post-row thumbnails.** Added a `PostThumb` slot (28×28, `border-radius: 6px`). Prefers `post.thumbnail`, falls back to the first URL in `post.media[]` (strings or `{url|thumbnail|src}` objects). If no image → renders a `theme.colors.gradient` tile with the uppercase first letter of `post.username`. Image `onError` hides the broken asset so the gradient initial shows through.
- **Always-reopenable input.** `SearchInput` also calls `setSearchFocused(true)` on `onMouseDown` + `onClick` (not just `onFocus`), so clicking a result → navigating → clicking back into the input reliably reopens the sheet. Previously the `preventDefault` on row `onMouseDown` kept the input focused, so subsequent clicks didn't fire `onFocus` again.
- **"Search-as-you-type" stale-result fix.** `useSearchDropdown.js` now flips `isSearching` to `true` **immediately** on every non-empty raw-query change (before the debounce fires). Prevents the "No matches / press Enter" flash when typing `xyz → xyzabc` during the 300 ms debounce window. Empty-state copy also updated to `No matches for "q". Press Enter to see all results.`

### Full results view polish

- **Feed view toggle on Posts tab.** Imported standalone `FeedViewToggle` from `ListFeedView` (new exported primitive). Rendered in a `HeaderSubRow` flex row alongside the `Results for "q"` caption. Button ships the same `CtrlButton` + Card/Compact menu as the home feed and persists to the same `default_feed_view_mode` localStorage key, so switching view in Search syncs with the home feed.
- **No layout shift on tab switch.** `HeaderSubRow` carries `min-height: 28px` (matches `CtrlButton` height). The toggle is wrapped in a `ViewToggleSlot` that stays mounted on every tab and flips between `visibility: visible/hidden` + `pointer-events: none` + `aria-hidden` based on whether the Posts tab is active with results. Prevents the tab bar from moving when switching between Posts / Communities / Users.
- **Clicking empty tabs now works.** New `userPickedTab` flag gates the auto-jump `useEffect`. Once the user clicks a tab, their explicit pick wins — the per-tab "No posts / communities / users found" empty state renders instead of silently auto-jumping back to the first non-empty tab. Flag resets on `query` change so a fresh search can still auto-jump.
- **Default view = compact.** `VIEW_MODE_DEFAULT` in `ListFeedView.js` flipped from `'card'` → `'compact'` (applies theme-wide, including Search + all feeds).
- **Posts get feed dividers.** Post results now render inside the shared `RowSlot` primitive (exported from `ListFeedView`) which carries the `1px solid theme.colors.border` between-row divider used by the home feed. Compact / card rendering is picked by `viewMode === 'compact' ? MemoCompactRow : CardView`.
- **Constant tab font weight.** `TabButton` weight is a constant `500` for both active and inactive states (was `600` / `500`). Prevents label reflow on tab switch — contrast is now carried entirely by color (`text` vs `subtleText`) + the `TabIndicator` underline.
- **Plain `(N)` tab counts.** Dropped the `TabCountBadge` pill (blue fill). New `TabCount` is inline text (`0.68rem / 500`, `color: inherit`, `opacity: 0.75`) rendered as `{label} ({count})`. No background, no border, no blue.
- **Inbox-matched row typography.** Community / User rows use `RowPrimary` at `0.7rem / 500` and `RowMeta` at `0.6rem / 500`. Matches `InboxView.HeaderTextBlock` so full-bleed list routes share one typography rhythm.
- **Community prefix removed.** Full results Communities tab drops the `#{community}` prefix — same rationale as the dropdown.

### Theme-wide knock-ons

- **`CardView` typography shrink.** `TitleLink` desktop `1rem → 0.88rem` (mobile `0.8 → 0.74`). `Body` desktop `0.85 → 0.74` (mobile `0.75 → 0.68`). Affects every feed / post-detail / profile render that uses `CardView`.
- **Feed toolbar title.** New `ToolbarTitle` primitive in `ListFeedView`; `ListFeedView` now accepts a `feedTitle` prop. `MainView` wires it up for all feed routes: `Home`, `Following`, `All`, and the community feed. Title anchors left; sort + view controls get right-aligned via `ToolbarTitle + * { margin-left: auto; }`. Sort popover now conditionally renders inside the toolbar (only when `showSortTabs` is true) so community feeds get title + view toggle without a sort button.
- **`ContainerBody` single-canvas fix.** Earlier Inbox work fixed `ContainerBody` to use `theme.colors.bg` instead of `theme.colors.panel` — the whole Search view inherits this correctly.

### Files touched by polish

- `web/frontend/src/themes/default/components/SearchDropdown.js`
- `web/frontend/src/themes/default/components/TopBar.js`
- `web/frontend/src/themes/default/routes/SearchResultsView.js`
- `web/frontend/src/themes/default/ListFeedView.js` (exports + `FeedViewToggle` + `ToolbarTitle` + `feedTitle` prop + default `VIEW_MODE_DEFAULT: 'compact'`)
- `web/frontend/src/themes/default/components/CardView.js` (typography shrink)
- `web/frontend/src/themes/default/routes/MainView.js` (wires `feedTitle` per route)
- `web/frontend/src/logic/useSearchDropdown.js` (immediate `isSearching` flip)

No token changes. No RULES.md changes. Build still clean: `cd web/frontend && CI=true npm run build`.
