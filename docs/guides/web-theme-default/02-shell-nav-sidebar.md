# Plan 02 — Shell, Top Nav, Sidebar, Mobile Nav

**Goal:** Replace the Shell, top navigation, and sidebar inside the `default` theme so the site gets a Reddit-style desktop chrome with mobile-app visuals. This is the phase where the app starts to **look** different.

**Status:** ✅ Done — Shell, TopBar, Sidebar (polished), MobileHeader all shipped. Only `MobileBottomNav` full restyle is deferred to a later polish pass.

**Depends on:** Plan 01 (theme must exist and be registered). ✅
**Unblocks:** Plans 03–06 (all content surfaces live inside this shell).

---

## Scope

### In scope
- Rewrite `DefaultShell.js` with a Reddit-inspired desktop layout (sticky top bar + sidebar + content column).
- Build a theme-local `TopBar` component that matches the mobile app’s visual language.
- Build a theme-local `Sidebar` component for desktop contextual nav.
- Build a theme-local `MobileHeader` and `MobileBottomNav` aligned with the mobile app.
- Register all of these on the manifest’s `components` map.
- Ensure responsive behavior at desktop, tablet, and mobile widths.

### Out of scope
- Feed rendering and post card visuals (Plan 03).
- Post detail / profile layouts (Plan 04).
- Supporting routes (Plans 05–06).

---

## Progress log

This section tracks what has actually been implemented across iterations so future PRs don't re-do finished work.

### ✅ Shell — done
- `DefaultShell.js` rewritten from a 345-line clone into a ~76-line composer.
- Desktop grid: `240px / 1fr`, max-width `1400px`, centered.
- Breakpoints:
  - `> 1000px` → TopBar + Sidebar + content
  - `601–1000px` → TopBar + content (sidebar hidden)
  - `≤ 600px` → MobileHeader + content (TopBar hidden) + bottom padding for `MobileBottomNav`
- Reserves space for the fixed mobile bottom nav via `padding-bottom`.
- `flatMode` turned **off** in `tokens.js` because the global `border-radius: 0 !important` reset in `Style.js` was silently flattening every rounded TopBar / Sidebar element. Default is mobile-inspired — pills and rounded panels are on-brand.

### ✅ TopBar — done (heavily iterated)
Implemented in `web/frontend/src/themes/default/components/TopBar.js`.

Layout:
- Structure: `[Brand] [LeftSpacer] [Search (centered)] [RightSpacer: Create, Inbox, Avatar]`
- Brand mark "M" removed; brand is just the word "Mirage"
- Primary nav links (`Home`, `Following`, `Communities`) removed from TopBar — nav lives only in Sidebar now
- Sticky top, background = `theme.colors.bg` (matches mobile app surface), vertical padding reduced to `0.3rem 1rem`
- Bottom border uses new `theme.colors.headerBorder` token
- `@username` text removed from trigger — avatar-only trigger

Search input:
- Fully centered between left/right flex spacers
- Pill shape (`border-radius: 9999px`)
- **1px** gradient border ring using the main Mirage gradient (`#667eea → #764ba2`)
- Border width stays constant on focus — only color changes: default gradient → solid `focusBlue` (`#4285f4`, matching `mirage-mobile-app` button blue)
- Inner background = `theme.colors.bg` (same as header) so it reads as a cut-out
- Hover: inner fill tints to `theme.colors.hoverBg`; focus snaps inner back to `bg` so the blue ring reads cleanly
- Font size `0.76rem` for both input text and placeholder
- Vertical padding: `calc(0.4rem + 1px)` on each side (= baseline + 2px taller)
- Native WebKit `::-webkit-search-cancel-button` hidden in favor of a custom SVG clear button
- Custom `ClearButton`: 30×30 round, 5px padding (inner icon ~20×20), SVG X glyph (`M6 6l12 12M18 6L6 18`, stroke 2.2, round caps), appears only when `query.length > 0`, hover bg from `theme.colors.inputIconHoverBg`, color from `theme.colors.inputIconColor`

Avatar:
- Uses mobile app's **DiceBear identicon** (`https://api.dicebear.com/9.x/identicon/png?seed={username||publicKey}&size={2x}`), matching `mirage-mobile-app/src/components/atoms/avatar.tsx`
- Perfect circle (`border-radius: 9999px`)
- Borderless in every state (no outline, no focus ring, no box-shadow on click)
- **Blurred-halo hover**: second copy of the same DiceBear image (48×48, `filter: blur(10px)`, `opacity: 0 → 0.85` on hover, scale `0.95 → 1`) sits behind the visible 32×32 avatar and fades in as a soft colored border picked from the identicon's own palette
- Gradient ring when menu is open removed — dropdown itself is the only "menu active" affordance

Create button:
- Ghost style: `background: transparent`, `border: none`
- Normal font weight (`400`), smaller text (`0.78rem`)
- Smaller `+` icon (18×18, `strokeWidth: 2`)
- Hover bg: `theme.colors.hoverBg`

Inbox icon button:
- Enlarged to 40×40 wrapper / 24×24 icon
- Color: `theme.colors.text` (matches Create text color)
- Red unread badge unchanged, reads `inbox_count` event
- Hover bg: `theme.colors.hoverBg`

Tokens added/updated (`tokens.js`):
- `gradientStart: #667eea` / `gradientEnd: #764ba2` / `gradient: linear-gradient(135deg, ...)`
- `focusBlue: #4285f4` (mobile app brand)
- `hoverBg`: dark `rgb(25, 28, 31)` / light `rgb(246, 248, 249)`
- `border` (app-wide dividers): dark `rgb(39, 40, 42)` / light `rgb(230, 230, 230)`
- `headerBorder` (header-specific bottom divider): dark `rgb(63, 65, 66)` / light `rgb(204, 204, 204)`
- `inputIconColor`: dark `rgb(143, 161, 172)` / light `rgb(95, 108, 115)`
- `inputIconHoverBg`: dark `rgb(53, 61, 65)` / light `rgb(221, 238, 232)`

### ✅ Sidebar — done (polished)
Implemented in `components/Sidebar.js` as a desktop-only sticky rail (hidden below 1000px). Restructured and restyled in full during the polish pass:

Structure:
- **Primary nav (no section header)** — Home, Following, Communities, Create post, Search
- **Communities** — collapsible list of joined communities (ported pattern from the `bluemoon` theme; `fetchJoinedCommunities` / `loadSubscriptions`, persists expand state via `Storage`, `+N more` toggle with `sidebar_communities_limit`, renamed from `sidebar_topics_limit` in v1.39.0 and migrated by `Storage.migrateRenamedKeys`)
- **Users** — collapsible list of followed users (`fetchFollowedUsers` / `loadFollowedAuthors` / `resolveUsernames`, same `+N more` pattern via `sidebar_users_limit`, renamed from `sidebar_people_limit` in v1.39.0)
- All previous `Account` / `Moderation` / `Network` sections and the "About Mirage" footer removed — those routes live on TopBar and deeper pages now.

Styling:
- Font sizes reduced: items `0.72rem`, section labels `0.6rem`, community/user rows `0.68rem`.
- Active state no longer changes font weight; uses **filled** (solid) icon variants.
- Hover bg = `theme.colors.hoverBg` (`rgb(25,28,31)` dark / `rgb(246,248,249)` light).
- Active bg uses new `sidebarItemActiveBg` token (`rgb(44,50,54)` dark / `rgb(230,235,238)` light).
- Inactive text color = new `sidebarItemText` (`rgb(221,228,232)` dark / `rgb(34,39,42)` light).
- Active text color = new `sidebarItemActiveText` (white on dark / black on light).
- Section headers: `font-weight: 400`, hover bg only (text + chevron colors stay unchanged on hover). Section dividers drawn with `border-top: 1px solid theme.colors.border`, matching the rest of the app.
- Row height is **hard-locked** at `32px` (fixed `height`, `line-height: 1`, `IconBox { line-height: 0; svg { display: block; width: 18px; height: 18px } }`) so outline↔filled icon swaps can never shift row position.

Icons:
- Migrated from inline SVG paths to **Heroicons v2** via `react-icons/hi2`:
  - Home → `HiOutlineHome` / `HiHome`
  - Following → `HiOutlineHeart` / `HiHeart`
  - Communities → `HiOutlineHashtag` / `HiHashtag`
  - Create → `HiOutlinePlusCircle` / `HiPlusCircle`
  - Search → `HiOutlineMagnifyingGlass` / `HiMagnifyingGlass`
  - Section chevron → `HiChevronDown` (rotates `-90deg → 0deg` on expand)
- `react-icons@^5.6.0` added to `web/frontend/package.json`.

Shell integration (`DefaultShell.js`):
- New `DividerCol` grid track (1px `border-left` + 16px right gap) between `SidebarCol` and `Main`, using the same `theme.colors.headerBorder` as the TopBar divider.
- New sticky `ToggleButton` pinned next to the TopBar (`position: sticky; top: calc(2.5rem + 1px + 14px)`, centered on the divider line via `margin-left: -16px`), so the collapse handle stays visible while the feed scrolls. Renders `HiBars3` from Heroicons; 32×32 circle; border `rgb(128,128,128)` inactive / black hover in light mode, `rgb(134,136,137)` inactive / white hover in dark mode; bg always matches main bg; icon color white (dark) / black (light) in both states.
- Collapse state persisted to `Storage` (`default_sidebar_hidden`) with a smooth grid-template-columns transition; divider + toggle stay mounted when collapsed so it can be reopened.
- `Layout` gets `min-height: calc(100vh - 2.5rem - 1px)` so the divider fills the viewport on short routes (Create Post, Search, loading states).

Wobble / jump fixes:
- `Bar` (TopBar) now has an explicit `height: calc(2.5rem + 1px)` + `box-sizing: border-box`, so the Sidebar's sticky `top` offset always matches the real header box regardless of font-size clamp. Kills the "sidebar jumps up on Create Post / Search / loading" bug.
- `BarInner` fills that locked height (`height: 100%; padding: 0 0.5rem`) so the header content stays vertically centered.
- `Sidebar.Aside` and `Layout.min-height` updated in lockstep to `calc(2.5rem + 1px)` / `calc(100vh - 2.5rem - 1px)`.
- `Style.js` globals add `html { scrollbar-gutter: stable }` so the TopBar / Sidebar never shift horizontally when a scrollable vs non-scrollable route mounts.
- `Style.js` globals also hide the viewport scrollbar indicator itself (`html { scrollbar-width: none }` + `html::-webkit-scrollbar { display: none }`) while keeping the gutter reserved — the feed still scrolls, just with no visible indicator.

Alignment:
- TopBar's `BarInner` constrained to `max-width: 1400px; margin: 0 auto; padding: 0 0.5rem` so the "Mirage" brand lines up with the sidebar rail's left edge on wide viewports.

New tokens (`tokens.js`):
- `sidebarItemText`, `sidebarItemActiveText`, `sidebarItemActiveBg`
- `menuBtnBorder`, `menuBtnBorderHover`, `menuBtnIcon` (both themes)

### ✅ MobileHeader — done
Implemented in `components/MobileHeader.js` as a replacement for the previous null placeholder. Renders on `≤ 600px` only. Menu button + brand + search button + inbox icon with badge. Bottom border uses the new `headerBorder` token. Mirrors `mirage-mobile-app/src/components/molecules/feed-header.tsx`.

### 🟡 MobileBottomNav — deferred
Currently the oldreddit clone is still in place but theme tokens resolve correctly. Full mobile-app-style bottom nav restyling is a small follow-up and can land alongside the sidebar polish.

---

## Next subtask — move to Plan 03 (Feed & Card view)

Plan 02 is now complete apart from the deferred `MobileBottomNav` full restyle (tracked inline above — can land as a small follow-up PR). The next active work item is **Plan 03 — Feed, card view, vote / action row**. See [`03-feed-and-card.md`](./03-feed-and-card.md).

---

## Target structure (desktop)

```
┌──────────────────────────────────────────────────────────────┐
│ TopBar (sticky)                                              │
│  [logo] [nav]           [search]   [inbox]  [user menu]      │
├────────────────┬─────────────────────────────────────────────┤
│                │                                             │
│                │                                             │
│   Sidebar      │   Main Content Column                       │
│   (desktop)    │   (feed / route output)                     │
│                │                                             │
│                │                                             │
└────────────────┴─────────────────────────────────────────────┘
```

### Target structure (mobile)

```
┌──────────────────────────────┐
│ MobileHeader (sticky)        │
├──────────────────────────────┤
│                              │
│   Main Content Column        │
│                              │
├──────────────────────────────┤
│ MobileBottomNav (fixed)      │
└──────────────────────────────┘
```

Breakpoints to target:
- Desktop: `> 1000px` → TopBar + Sidebar + Content
- Tablet: `601–1000px` → TopBar + Content (sidebar hidden or collapsed)
- Mobile: `≤ 600px` → MobileHeader + Content + MobileBottomNav

---

## Files to create or change

Inside `web/frontend/src/themes/default/`:

### Rewrite
- `DefaultShell.js`
  - Responsive layout: fixed TopBar, desktop sidebar, central content column.
  - Show/hide `MobileHeader` and `MobileBottomNav` by breakpoint.
  - Handle `padding-bottom` for bottom nav safe area.

### Create / replace
- `components/TopBar.js`
- `components/Sidebar.js`
- `components/MobileHeader.js`
- `components/MobileBottomNav.js`

### Update
- `index.js` — register the new components on the manifest’s `components` map:
  - `TopBar`, `ProfileMenuContent`
  - `Sidebar`
  - `MobileHeader`
  - `MobileBottomNav`
- Keep required global keys (`Toast`, `UnlockPrompt`, `Tooltip`, `InfoIcon`, `tooltipStyles`) from Plan 01.

---

## Component requirements

### `TopBar` (desktop)
Reference: `mirage-mobile-app/src/components/molecules/feed-header.tsx` (visual language), existing `themes/oldreddit/OldRedditShell.js` (structural patterns).

Required slots:
- **Left:** Mirage logo/brand, current page title/breadcrumb, primary nav links (`home`, `following`, `communities`, `create`)
- **Right:** search entry, inbox icon with unread badge, user menu trigger
- Sticky at top, panel background, subtle bottom border
- Active-link state tied to current pathname

Implementation notes:
- Use `react-router-dom` `Link` and `useLocation` for active-state detection.
- Read unread count from the same place `oldreddit` does (see `localStorage` `inbox_count` event listener in the existing shell).
- Use `ProfileMenuContent` from the theme for the user menu dropdown body.
- Use `styled-components` with new theme tokens (no hard-coded colors).

### `Sidebar` (desktop)
Reference: `themes/oldreddit/components/Sidebar.js`.

Required sections:
- Primary nav (mirrors TopBar but with full labels)
- Communities / discovery
- Account shortcuts (profile, settings, subscription)
- Moderation / follows / blocks / reports
- Optional info panel (node info / about Mirage)

Behavior:
- Visible ≥ 1000px, hidden below.
- Sections are stacked panels with rounded corners and subtle borders.
- Each panel inherits spacing/radius from mobile tokens (Plan 01).

### `MobileHeader`
Reference: `mirage-mobile-app/src/components/molecules/feed-header.tsx`.

Required:
- Compact sticky top bar
- Menu button (opens a drawer or nav overlay — drawer itself can be a stub in this PR if needed)
- Title / feed-mode switch (feed-mode switch logic can be wired later; render the shell and dropdown skeleton now)
- Search button → navigates to `/search`
- Matches mobile app icon sizing and spacing

### `MobileBottomNav`
Reference: `mirage-mobile-app/app/(tabs)/_layout.tsx`.

Required:
- Fixed to the bottom on mobile
- Icons + labels for: Home, Following, Create, Inbox, Profile
- Active state styling aligned with mobile app
- Inbox unread badge
- Auth gating: the existing web theme already handles this — mirror the current behavior (tapping a protected tab while logged out routes to `/login`)

---

## Responsive rules

- Use CSS breakpoints: 1000px and 600px (match `oldreddit` for consistency).
- Hide the desktop Sidebar below 1000px.
- Hide the TopBar below 600px; show `MobileHeader` + `MobileBottomNav` instead.
- Never show both TopBar and MobileHeader at the same time.
- Content column should respect a max-width for readability (see `oldreddit/Layout.js` `CappedPageColumn` for the existing pattern).

---

## Verification checklist

- [x] Switching to `default` shows the new TopBar and Sidebar on desktop.
- [x] Resizing below 1000px hides the Sidebar.
- [x] Resizing below 600px switches to MobileHeader + MobileBottomNav.
- [x] Primary nav active states update on route changes.
- [x] Inbox unread badge updates when `inboxCount` event fires.
- [x] User menu opens, closes on outside click, and navigates correctly.
- [x] Nothing from `themes/oldreddit/*` is imported.
- [x] Sidebar does not jump vertically between routes / during loading.
- [x] Divider between Sidebar and Main fills the viewport on short routes.
- [x] TopBar + Sidebar do not shift horizontally when scrollable vs non-scrollable routes mount.
- [x] Sidebar collapse button stays pinned next to the TopBar while the feed scrolls.
- [x] Files parse cleanly with `@babel/parser` (`Sidebar.js`, `TopBar.js`, `DefaultShell.js`, `Style.js`, `tokens.js`).
- [ ] Full build passes (run before merging the polish pass):

```bash
cd web/frontend
CI=true npm run build
```

---

## Risks & mitigations

- **Layout shifts from sticky header/footer** → reserve space via `padding-top` / `padding-bottom` on the content column.
- **Body scroll locking mobile nav** → don’t use fixed positioning without testing scroll on iOS Safari and Chrome Android.
- **Active-state mismatch** → use `useLocation().pathname` prefix matching consistent with the existing themes.
- **User menu regression** → reuse `ProfileMenuContent` from the theme instead of re-implementing user menu logic.

---

## PR description template

> Replaces the `default` shell with a Reddit-style desktop layout: sticky TopBar + Sidebar + content column, plus a mobile-app-inspired MobileHeader and MobileBottomNav. No feed/card changes yet — those follow in Plan 03.
