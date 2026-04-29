# Sub-Plan 06.8 — MobileBottomNav full restyle

**Component:** `themes/default/components/MobileBottomNav.js`
**Status:** ⏳ Not started — **deferred from Plan 02**
**Parent:** [`../06-remaining-routes-and-polish.md`](../06-remaining-routes-and-polish.md)

---

## Current state

10-line diff from `themes/oldreddit/components/MobileBottomNav.js`. The mobile bottom nav still looks like oldreddit while the rest of the mobile experience has been moved to default visuals.

---

## Goal

Align the bottom nav with the mobile app's tab bar (`app/(tabs)/_layout.tsx`).

---

## References

- **Mobile:** `mirage-mobile-app/app/(tabs)/_layout.tsx` + `mirage-mobile-app/src/components/molecules/*tab*`
- **Theme primitives:** TopBar profile menu (`ProfileMenuContent`), `Sidebar`

---

## Requirements

- Bar sits on `bg` with a `headerBorder` top divider (R3).
- 5 items: Home, Search, Create, Inbox, Profile (match mobile).
- Icons from `react-icons/hi2`; active state uses `focusBlue` icon color + small dot indicator.
- Label typography per R7: `0.6rem/500` active `600`.
- Safe-area padding honored.
- Opening the profile tab reuses `ProfileMenuContent` in a bottom sheet (or navigates to `/profile`, matching mobile).
- No blue-ring focus; tap highlight uses `hoverBg`.

---

## Out of scope

- Changing navigation targets for TopBar / Sidebar.
- Adding new routes.

---

## Verification checklist

- [ ] Bar visible at ≤600px, hidden above.
- [ ] Active indicator matches the current route.
- [ ] Create button routes to `/create_post`.
- [ ] Profile tab opens profile menu / profile page correctly.
- [ ] Dark + light verified.
- [ ] Build passes.

---

## PR description template

> Restyles `default`'s MobileBottomNav to match the mobile app tab bar (icons, labels, active state). Closes sub-plan 06.8 and the deferred item from Plan 02.
