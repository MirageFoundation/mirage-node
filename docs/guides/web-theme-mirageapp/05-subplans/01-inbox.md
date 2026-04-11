# Sub-Plan 05.1 — Inbox

**Route:** `/inbox`
**File:** `web/frontend/src/themes/mirageapp/routes/InboxView.js`
**Status:** ✅ Done
**Parent:** [`../05-inbox-search-settings-auth.md`](../05-inbox-search-settings-auth.md)

> Shipped: rewrote `InboxView` with avatar-left row layout, larger mobile-app typography, unread dot + pill count, theme-local state blocks for loading/empty/error using `HiInbox` / `HiOutlineBellAlert` / `HiExclamationTriangle` icons, hover-revealed mark-read button, and styled quote/donation/follow content blocks. Still uses `inboxReplyUnreadBg` tokens. `useInbox` untouched.

---

## Goal

Rewrite `mirageapp`'s `InboxView` so notifications and replies feel native to the theme: mobile-app visual tokens + desktop shell layout.

---

## References

- **Mobile:** `src/pages/inbox-screen.tsx`
- **Web (structure):** `web/frontend/src/themes/oldreddit/routes/InboxView.js`
- **Web (interactions):** `web/frontend/src/themes/onyx/routes/InboxView.js`
- **Data hook (do not modify):** `web/frontend/src/logic/useInbox.js` (or equivalent — verify path before editing)
- **Tokens from Plan 01:** `inboxReplyUnreadBg`, panel container tokens, typography scale

---

## Scope

### In scope
- Rewrite `themes/mirageapp/routes/InboxView.js`.
- Add/extend any theme-local components needed (e.g., `InboxRow`, `InboxEmptyState`) inside `themes/mirageapp/components/`.
- Wire into the Plan 02 shell (TopBar + Sidebar + content column).

### Out of scope
- `useInbox` or any data/behavior change.
- Notification delivery, mark-as-read API, or counts logic.
- Inbox entry points in TopBar (badge already exists from Plan 02).

---

## Requirements

- List of notifications / replies with clearly distinct **unread** vs **read** states.
- Unread items use a subtle background highlight via `inboxReplyUnreadBg` tokens from Plan 01.
- Each row shows: avatar, author, action (replied/mentioned/etc.), truncated content preview, timestamp.
- Mark-as-read interaction preserved (click row / button → calls existing handler).
- **Empty state** styled clearly with mobile-app tone (icon + short message).
- **Loading state** and **error state** styled consistently with other Plan 03 surfaces.
- Desktop width matches the shell content column; mobile uses full-bleed rows.
- Dark + light modes both work.
- No `themes/oldreddit/*` imports inside the new file.

---

## Suggested implementation steps

1. Read `themes/oldreddit/routes/InboxView.js` to understand current structure and data shape from `useInbox`.
2. Read `themes/onyx/routes/InboxView.js` for a modern layout reference.
3. Read mobile `src/pages/inbox-screen.tsx` for visual cues (row layout, spacing, empty state).
4. Copy the oldreddit structure into `themes/mirageapp/routes/InboxView.js` as a starting skeleton.
5. Replace inline classes/styles with `mirageapp` tokens + styled components.
6. Extract row into a theme-local `InboxRow` component if it helps readability.
7. Add unread background highlight using `inboxReplyUnreadBg`.
8. Style empty / loading / error states.
9. Verify build + manual smoke test on desktop + mobile widths.

---

## Verification checklist

- [x] `/inbox` renders with proper unread/read styling and updates counts.
- [x] Unread background highlight uses `inboxReplyUnreadBg` token.
- [x] Empty, loading, and error states all styled.
- [x] Mark-as-read still works (hook untouched).
- [ ] Dark + light modes verified _(manual browser check recommended)_.
- [ ] Desktop (shell content column) + mobile (full-bleed) layouts verified _(manual browser check recommended)_.
- [x] No `themes/oldreddit/*` imports.
- [x] Build passes:

```bash
cd web/frontend
CI=true npm run build
```

---

## PR description template

> Rewrites `mirageapp`'s `InboxView` with mobile-app tokens and Plan 02 shell layout. Adds unread/read states, empty/loading/error styling, and theme-local row component. Visual only — `useInbox` and mark-as-read behavior unchanged.
