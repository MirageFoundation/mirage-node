# Sub-Plan 06.9 — Polish + QA (closes Plan 06)

**Status:** ⏳ Not started — **runs after sub-plans 06.1–06.8**
**Parent:** [`../06-remaining-routes-and-polish.md`](../06-remaining-routes-and-polish.md)

---

## Goal

A single focused sweep across the whole `mirageapp` theme to catch drift, verify every route behaves correctly in dark/light and at every breakpoint, and (optionally, in a follow-up PR) flip it to the default.

---

## Polish sweep

### Spacing
- [ ] No ad-hoc pixel values. Everything comes from `Layout.js` / token helpers.
- [ ] Page top padding respects the Plan 02 sticky TopBar.
- [ ] Page bottom padding respects the mobile bottom nav.

### Typography (R7)
- [ ] Consistent heading scale across routes (`1.1rem/700` page heading).
- [ ] Body text uses the same base size everywhere.
- [ ] All inputs at `0.75rem/500`.
- [ ] No `>1.1rem` body text, no `font-weight: 800`.
- [ ] Mono font only where intentional (code, hashes, etc.).

### Interaction states
- [ ] Hover: subtle color shift only.
- [ ] Focus: R5 style on every input (no blue ring).
- [ ] Active: consistent across nav + buttons.
- [ ] Disabled: `accentDisabled` + reduced opacity.

### Dark/light
- [ ] Toggle on every route; no invisible text or missing borders.
- [ ] Input background stays readable in both modes.
- [ ] Scrollbars look correct in both.

### Responsive
- [ ] 1920px, 1400px, 1200px, 1000px, 800px, 600px, 420px.
- [ ] TopBar, Sidebar, MobileHeader, MobileBottomNav all behave correctly at breakpoints.

### Accessibility
- [ ] Color contrast meets WCAG AA for body text.
- [ ] Interactive elements have focus styles.
- [ ] Icon-only buttons have `aria-label`.

---

## QA sweep

- [ ] Click through every nav item in TopBar + Sidebar + MobileBottomNav.
- [ ] Perform a vote, comment, follow, block, and report while on `mirageapp`.
- [ ] Create and delete a test post (text / image / link).
- [ ] Switch to each other theme (`bluemoon`, `onyx`, `oldreddit`) and back.
- [ ] Toggle dark/light on at least 5 different routes.
- [ ] Run the build: `CI=true npm run build`.
- [ ] Confirm no errors thrown from the theme registry at startup.
- [ ] `grep -r "themes/oldreddit" web/frontend/src/themes/mirageapp/` returns 0 results.
- [ ] `grep -r "themes/bluemoon" web/frontend/src/themes/mirageapp/` returns 0 results.

---

## Optional follow-up PR — default theme switch

Once this sub-plan lands and bakes for a short period:

1. In `web/frontend/src/themes/manifests.js`, move `mirageappManifest` to position 0 in `THEME_MANIFESTS`.
2. Update `LEGACY_THEME_IDS` only if we need to migrate any users off a stale id.
3. Announce in `docs/whats-new.md` with a short user-facing note.

Keep this in a separate PR — it is an operational/rollout decision, not a code-style one.

---

## Verification checklist

- [ ] Every checkbox above ticked.
- [ ] Screenshots for every route captured in dark + light at ≥2 breakpoints and attached to the PR.
- [ ] No regressions in other themes (spot-check oldreddit + bluemoon on 3 routes each).
- [ ] Build passes.

---

## PR description template

> Final polish sweep + QA on the `mirageapp` theme. No behavior changes. Closes sub-plan 06.9 and Plan 06 entirely. Theme is now feature-complete and ready for an optional default-theme switch follow-up.
