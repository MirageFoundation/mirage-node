# Plan 02 — Shell, Top Nav, Sidebar, Mobile Nav

**Goal:** Replace the Shell, top navigation, and sidebar inside the `mirageapp` theme so the site gets a Reddit-style desktop chrome with mobile-app visuals. This is the phase where the app starts to **look** different.

**Status:** 🟡 In progress — Shell + TopBar shipped and polished; Sidebar UI polish is the next subtask.

**Depends on:** Plan 01 (theme must exist and be registered). ✅
**Unblocks:** Plans 03–06 (all content surfaces live inside this shell).

---

## Scope

### In scope
- Rewrite `MirageAppShell.js` with a Reddit-inspired desktop layout (sticky top bar + sidebar + content column).
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
- `MirageAppShell.js` rewritten from a 345-line clone into a ~76-line composer.
- Desktop grid: `240px / 1fr`, max-width `1400px`, centered.
- Breakpoints:
  - `> 1000px` → TopBar + Sidebar + content
  - `601–1000px` → TopBar + content (sidebar hidden)
  - `≤ 600px` → MobileHeader + content (TopBar hidden) + bottom padding for `MobileBottomNav`
- Reserves space for the fixed mobile bottom nav via `padding-bottom`.
- `flatMode` turned **off** in `tokens.js` because the global `border-radius: 0 !important` reset in `Style.js` was silently flattening every rounded TopBar / Sidebar element. Mirageapp is mobile-inspired — pills and rounded panels are on-brand.

### ✅ TopBar — done (heavily iterated)
Implemented in `web/frontend/src/themes/mirageapp/components/TopBar.js`.

Layout:
- Structure: `[Brand] [LeftSpacer] [Search (centered)] [RightSpacer: Create, Inbox, Avatar]`
- Brand mark "M" removed; brand is just the word "Mirage"
- Primary nav links (`Home`, `Following`, `Topics`) removed from TopBar — nav lives only in Sidebar now
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

### 🟡 Sidebar — built, needs UI polish
Implemented in `components/Sidebar.js` as a desktop-only sticky rail (hidden below 1000px) with four sections:
- **Feeds** — Home, Following, Topics, Create post, Search
- **Account** — Profile, Inbox, Subscription, Settings
- **Moderation** — Follows, Blocks, Agents, Reports
- **Network** — This node, Stats, Referrals, Bridge
- Footer "About Mirage" link
- Inline SVG icons, 10px radius items, active state via pathname matching

**Pending:** UI polish to align with the mobile app. See **"Next subtask — Sidebar UI polish"** below.

### ✅ MobileHeader — done
Implemented in `components/MobileHeader.js` as a replacement for the previous null placeholder. Renders on `≤ 600px` only. Menu button + brand + search button + inbox icon with badge. Bottom border uses the new `headerBorder` token. Mirrors `mirage-mobile-app/src/components/molecules/feed-header.tsx`.

### 🟡 MobileBottomNav — deferred
Currently the oldreddit clone is still in place but theme tokens resolve correctly. Full mobile-app-style bottom nav restyling is a small follow-up and can land alongside the sidebar polish.

---

## Next subtask — Sidebar UI polish

**Goal:** Refine `components/Sidebar.js` to match the mobile app's visual feel and improve structure / hierarchy of the sections on desktop.

**Planned tweaks** (to be filled in as the user provides specifics — typical targets):
- Section density and grouping
- Row padding / radius / hover treatment using new `hoverBg` token
- Icon size and color alignment with TopBar icons
- Active-state styling (background, color, border/accent)
- Section headers (typography, color, optional dividers)
- Footer / node info panel styling
- Possibly new or removed sections based on mobile app drawer content

**Files likely touched:**
- `web/frontend/src/themes/mirageapp/components/Sidebar.js`
- `web/frontend/src/themes/mirageapp/tokens.js` (only if new tokens are needed — prefer reusing `hoverBg`, `border`, `text`, `subtleText`, `focusBlue`)

**Verification:**
```bash
cd web/frontend && CI=true npm run build
```

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

Inside `web/frontend/src/themes/mirageapp/`:

### Rewrite
- `MirageAppShell.js`
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
- **Left:** Mirage logo/brand, current page title/breadcrumb, primary nav links (`home`, `following`, `topics`, `create`)
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
- Topics / discovery
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

- [ ] Switching to `mirageapp` shows the new TopBar and Sidebar on desktop.
- [ ] Resizing below 1000px hides the Sidebar.
- [ ] Resizing below 600px switches to MobileHeader + MobileBottomNav.
- [ ] Primary nav active states update on route changes.
- [ ] Inbox unread badge updates when `inboxCount` event fires.
- [ ] User menu opens, closes on outside click, and navigates correctly.
- [ ] Nothing from `themes/oldreddit/*` is imported.
- [ ] Build passes:

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

> Replaces the `mirageapp` shell with a Reddit-style desktop layout: sticky TopBar + Sidebar + content column, plus a mobile-app-inspired MobileHeader and MobileBottomNav. No feed/card changes yet — those follow in Plan 03.
