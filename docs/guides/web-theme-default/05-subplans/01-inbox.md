# Sub-Plan 05.1 — Inbox

**Route:** `/inbox`
**File:** `web/frontend/src/themes/default/routes/InboxView.js`
**Status:** ✅ Done
**Parent:** [`../05-inbox-search-settings-auth.md`](../05-inbox-search-settings-auth.md)

> Shipped across several iterations. Final state: minimal mobile-app-style inbox with feed-width shell, tight header, single-line "N unread / Mark all as read" info row, full-bleed reply rows with action icons + body + hover-revealed mark-read pill, lifted neutral tiles on unread rows, and all colors routed through tokens per `../RULES.md`.

---

## Final shipped state

### Layout

- **Width:** `InboxWrap` caps at `max-width: 720px` (= card-view feed) and left-aligns by default. When the sidebar is hidden on desktop (`[data-sidebar-hidden='true']` + `min-width: 1001px`), it expands to `width: 80%` and stays left-pinned (no auto margins).
- **Top offset:** `margin-top: -0.75rem` (desktop) / `-0.5rem` (mobile) cancels half of `ContainerBody`'s vertical padding so the header sits directly under the TopBar divider.
- **Canvas:** Lives inside `ContainerBody` which was fixed in Plan 05 to use `theme.colors.bg` (R1 fix, see `RULES.md` changelog).

### Header

- `HeaderRow` holds only the plain text title **"Inbox"** (hard-coded, no `titleText` from `useInbox`).
- Title: `font-size: 1.1rem`, `font-weight: 700`, `letter-spacing: -0.01em`.
- **No envelope icon, no unread pill, no bottom divider.**

### Unread info row (`UnreadInfoRow`)

- Rendered directly below `HeaderRow` whenever `replies.length > 0`.
- **Left:** `UnreadCountText` shows `"N unread"` or `"No unread"` in `subtleText`.
- **Right:** `MarkAllButton` — plain text only, no icon, no background, no border.
  - Rest color: new token `inboxMarkAllText` (`rgb(221,228,232)` dark / `rgb(25,28,31)` light).
  - Hover color: `sidebarItemActiveText` (`#FFFFFF` dark / `#000000` light). No hover background.
  - Font: `0.68rem`, weight `600`.
  - Disabled state: `opacity: 0.45`.
- This row owns the single visible divider (`border-bottom: 1px solid theme.colors.border`) before the reply list.

### Reply rows (`ReplyItem`)

- Full-bleed, `padding: 0.5rem 1rem` (desktop) / `0.45rem 0.85rem` (mobile).
- Row backgrounds via tokens (see `RULES.md` R2):
  - Read rest: `inboxReplyReadBg` (`transparent`)
  - Read hover: `inboxReplyReadBgHover` (= `hoverBg`)
  - Unread rest: `inboxReplyUnreadBg` (`rgb(34,39,42)` dark / `rgb(239,241,243)` light)
  - Unread hover: `inboxReplyUnreadBgHover` (`rgb(44,50,54)` dark / `rgb(230,235,238)` light)
- Divider between rows: `1px solid theme.colors.border` (R3).

#### Row 1 — `HeaderTextRow`

- **Action icon** (`ActionIcon`, 18px): `HiArrowUturnLeft` / `HiAtSymbol` / `HiGift` / `HiUserPlus` / `HiSparkles` per reply type.
- **Header text** (`HeaderTextBlock`, 0.7rem, weight 600 unread / 400 read):
  - `ReplyUsername` with tier color + hover tooltip.
  - `ActionText` (subtle): `" replied to "`, `" mentioned you in "`, `" gave you a "X" award for your post/comment"`, `" followed you"`, `" donated to you"`, `" gifted you a subscription"`.
  - `ParentPreview` in curly quotes for non-special non-award types.
- **Timestamp** (`TimeText`, 0.62rem) on the far right via shared `formatTimeAgo` from `useAgents.js`.

#### Row 2 — `BodyRow` (only rendered if `hasBody || isUnread`)

- `display: flex; justify-content: space-between; align-items: flex-end`, indented `margin-left: 1.65rem` (desktop) / `1.55rem` (mobile) to align under the header text.
- **Left:** reply body (or `<span />` placeholder for follow / subscription events).
  - `ReplyContent` — plain reply text, 0.68rem.
  - `DonationAmount` — `voteUp` green, 0.7rem weight 700.
  - `QuoteBlock` — italicized, left-bordered, 0.64rem (award quote).
- **Right:** `MarkReadButton` pill (unread only).
  - `padding: 0.15rem 0.5rem`, `border-radius: 999px`, transparent background.
  - `font-size: 0.55rem`, `font-weight: 500`.
  - Rest: transparent border, text = `sidebarItemText`.
  - Hover: border lifts to `followBtnBorder` (`rgb(140,141,143)` dark / `rgb(124,125,125)` light), text → `sidebarItemActiveText`.
  - **Desktop:** `opacity: 0` at rest, revealed via `ReplyItem:hover .mark-read { opacity: 1 }`.
  - **Mobile:** always visible (no hover available).

### State blocks

- `StateBlock` + `StateIcon` + `StateTitle` + `StateMessage` for loading / empty / error.
- Empty copy: **"No replies yet"** / "When someone replies to your posts or comments, follows you, or sends you an award, it will show up here."
- Empty icon: `HiOutlineBellAlert`.
- Error icon: `HiExclamationTriangle` tinted with `voteDown`.
- Loading: `LoadingSpinner` with `focusBlue` ring.

### Load more

- `LoadMoreWrap` below the reply list, uses the theme `Button` component (secondary, fullWidth, sm) wired to `handleLoadMore` + `isLoadingMore`.

---

## Rules compliance (see `../RULES.md`)

- ✅ **R1 single-bg canvas** — rows sit directly on `theme.colors.bg`; `ContainerBody` fix shipped theme-wide.
- ✅ **R2 tokens only** — every color routed through tokens. No raw hex or rgba in `InboxView.js`. Added one new token `inboxMarkAllText` documented in the RULES table.
- ✅ **R3 feed divider** — only `1px solid theme.colors.border` used; no custom hex/rgba dividers anywhere in the file.
- ✅ **R4 reference check** — bluemoon `InboxView.js` used as data parity source; mobile `inbox-item.tsx` / `inbox-screen.tsx` used for visual parity. Labels + action types + mark-read flow match bluemoon. Indent / icon / timestamp placement match mobile.

---

## Verification

- [x] `/inbox` renders with proper unread/read styling and updates counts.
- [x] All colors via tokens; no raw hex/rgba.
- [x] Empty, loading, and error states styled.
- [x] Mark-as-read (single + all) still works (`useInbox` untouched).
- [x] Build passes: `cd web/frontend && CI=true npm run build` — ✅ Compiled successfully, no warnings.
- [ ] Dark + light modes final manual browser check (recommended before merge).
- [ ] Desktop + mobile layouts final manual browser check (recommended before merge).

---

## Files changed

- `web/frontend/src/themes/default/routes/InboxView.js` — full rewrite + multiple UI iterations.
- `web/frontend/src/themes/default/Layout.js` — `ContainerBody` bg `panel` → `bg` (R1 fix, theme-wide).
- `web/frontend/src/themes/default/tokens.js` — inbox row token values updated (neutral tile style) + new `inboxMarkAllText` token added in both modes.
- `docs/guides/web-theme-default/RULES.md` — inbox row table updated, `inboxMarkAllText` added, changelog entries.

---

## PR description template

> Rewrites `default`'s `InboxView` per `RULES.md` R1–R4. Mobile-app-style action icons + indented bodies, 720px card-feed width with sidebar-hidden expansion, hover-revealed Mark-read pill inline with reply body, neutral-tile unread rows, and a plain-text "N unread / Mark all as read" info row. Also fixes theme-wide `ContainerBody` background to `bg` (R1). Adds `inboxMarkAllText` token pair. Visual only — `useInbox` and mark-as-read behavior unchanged.
