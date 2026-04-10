# Plan 02 — Shell, Top Nav, Sidebar, Mobile Nav

**Goal:** Replace the Shell, top navigation, and sidebar inside the `mirageapp` theme so the site gets a Reddit-style desktop chrome with mobile-app visuals. This is the phase where the app starts to **look** different.

**Depends on:** Plan 01 (theme must exist and be registered).
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
