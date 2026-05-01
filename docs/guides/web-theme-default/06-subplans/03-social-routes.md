# Sub-Plan 06.3 — Social Routes (Follows / Blocks / Reports)

**Routes:** `/follows`, `/blocks`, `/reports`
**Files:** `themes/default/routes/{FollowsView,BlocksView,ReportsView}.js`
**Status:** ✅ Done
**Parent:** [`../06-remaining-routes-and-polish.md`](../06-remaining-routes-and-polish.md)

---

## Current state

All three routes are near-identical copies of `themes/oldreddit/routes/*` (2–6 line diffs — just `MobileHeader` added). They render with oldreddit tokens/typography.

---

## Goal

Rewrite each route as a list-row page inside the Plan 02 shell, matching the inbox row density from sub-plan 05.1.

---

## References

- **Mobile:** `mirage-mobile-app/src/pages/blocked-users-screen.tsx`, `follow-screen.tsx`
- **Web data:** `themes/bluemoon/routes/{FollowsView,BlocksView,ReportsView}.js`
- **Structure fallback:** `themes/oldreddit/routes/*`

---

## Requirements

### Shared row pattern
- Row = avatar + identity block (username / identifier + secondary meta) + right-aligned action button.
- Row divider: `1px solid theme.colors.border` (R3).
- Row hover: `hoverBg` background tile.
- Typography per R7: title `0.78rem/600`, meta `0.62rem/500 subtleText`.

### FollowsView (`/follows`)
- Tabs for `Followers` / `Following` / `Mutuals` if bluemoon exposes them.
- Action button uses `followBtnBg` / "Following" outline variant.
- Empty state uses consistent empty-state typography (`0.9rem/500 subtleText`).

### BlocksView (`/blocks`)
- Row action = `Unblock` (danger variant of `Button`).
- Confirm dialog (if bluemoon has one) uses the restyled panel + buttons.

### ReportsView (`/reports`)
- Columns: reporter, target, reason, status, timestamp.
- Status chips use `voteUpBg` / `voteDownBg` / neutral tile based on state.

---

## Out of scope

- Data hook changes.
- New filtering / sort affordances beyond what bluemoon already shows.

---

## Verification checklist

- [ ] Each route lives on `theme.colors.bg` canvas (R1).
- [ ] All colors come from R2 tokens.
- [ ] Row dividers use `border`.
- [ ] Action buttons use the restyled `Button` component (depends on sub-plan 02).
- [ ] Data parity with bluemoon.
- [ ] Dark + light verified.
- [ ] No `themes/oldreddit/*` imports.
- [ ] Build passes:

```bash
cd web/frontend
CI=true npm run build
```

---

## PR description template

> Rewrites `default`'s Follows / Blocks / Reports routes with R1–R7 tokens and the shared list-row pattern. Visual only; data hooks unchanged. Closes sub-plan 06.3.
