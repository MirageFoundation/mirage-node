# Plan 06 — Remaining Routes, Polish, QA

**Goal:** Finish every remaining theme route, perform a polish pass across the whole `mirageapp` theme, and verify it is ready to be the default.

**Depends on:** Plans 01–05.
**Unblocks:** making `mirageapp` the default theme (optional — can happen later).

---

## Scope

### In scope — remaining routes
Inside `web/frontend/src/themes/mirageapp/routes/`, rewrite:
- `FollowsView.js`
- `BlocksView.js`
- `ReportsView.js`
- `SubscriptionView.js`
- `NetworkView.js`
- `ReferralsView.js`
- `BridgeView.js`
- `StatsView.js`
- `AgentsView.js`
- `NotFoundView.js`
- `DiscoverView.js` (topics)

### In scope — polish
- Spacing consistency pass across all routes.
- Typography pass (sizes, weights, line-heights).
- Hover/focus/active state pass.
- Dark/light verification on every page.
- Responsive verification at desktop, tablet, and mobile widths.
- Scrollbar, selection, and focus ring styling.
- Icon alignment and sizing consistency.

### In scope — QA
- Smoke test every route by clicking through navigation.
- Theme toggle (dark ↔ light) on every route.
- Switch between `mirageapp`, `onyx`, `bluemoon`, `oldreddit` without breaking.
- Mobile-only: verify MobileHeader + MobileBottomNav interactions.
- Verify the build passes in CI mode.

### Out of scope
- New features.
- Data layer changes.

---

## Per-route notes

### Follows / Blocks / Reports
- Use list rows with the same density as the inbox from Plan 05.
- Each row: avatar, username/identifier, timestamp, action button.
- Empty states styled consistently with other empty states.

### Subscription
- Panel-based layout: plan/tier summary, benefits, billing/upgrade action.
- Align colors with mobile subscription screen.

### Network
- Node info as stacked info panels.
- Status indicators use `success` / `warning` / `danger` tokens from Plan 01.

### Referrals
- Reference: `mirage-mobile-app/src/pages/invite-and-earn-screen.tsx` and `referrals-screen.tsx`.
- Share link block + stats block + history list.

### Bridge
- The bridge route is complex. Keep the existing logic; restyle containers only.
- Reuse the theme’s `Button`, input, and panel styling.

### Stats
- Panel-based layout with data rows and charts.
- Restyle chart containers; don’t rewrite chart logic.

### Agents
- List of agents with follow/subscribe affordances styled like other list rows.

### NotFound / Discover
- Simple centered layout on desktop.
- Consistent with the empty-state styling used elsewhere.

---

## Polish pass checklist

Do a focused sweep across the whole theme:

### Spacing
- [ ] No ad-hoc pixel values inside components. Everything comes from `Layout.js` / token helpers.
- [ ] Page top padding respects the Plan 02 sticky TopBar.
- [ ] Page bottom padding respects the mobile bottom nav.

### Typography
- [ ] Consistent heading scale across routes.
- [ ] Body text uses the same base size everywhere.
- [ ] Mono font only where intentional (code, hashes, etc.).

### Interaction states
- [ ] Hover: subtle color shift only.
- [ ] Focus: visible ring via `focusBorder` token.
- [ ] Active: consistent across nav + buttons.
- [ ] Disabled: consistent via `accentDisabled` + reduced opacity.

### Dark/light
- [ ] Toggle on every route; no invisible text or missing borders.
- [ ] Input background stays readable in both modes.
- [ ] Scrollbars look correct in both.

### Responsive
- [ ] 1920px, 1400px, 1200px, 1000px, 800px, 600px, 420px.
- [ ] TopBar, Sidebar, MobileHeader, MobileBottomNav all behave correctly at breakpoints.

### Accessibility
- [ ] Color contrast meets basic WCAG AA for body text.
- [ ] Interactive elements have focus styles.
- [ ] Icon-only buttons have `aria-label`.

---

## QA checklist

- [ ] Click through every nav item in TopBar + Sidebar + MobileBottomNav.
- [ ] Perform a vote, comment, follow, and block while on `mirageapp`.
- [ ] Create and delete a test post.
- [ ] Switch to each other theme (`bluemoon`, `onyx`, `oldreddit`) and back.
- [ ] Toggle dark/light at least 3 different routes.
- [ ] Run the build with:

```bash
cd web/frontend
CI=true npm run build
```

- [ ] Run existing frontend smoke tests / manual smoke where applicable.
- [ ] Confirm no errors thrown from the theme registry at startup.

---

## Risks & mitigations

- **Regression in other themes** → do a side-by-side test; shared logic must not be touched.
- **Polish pass scope creep** → limit Plan 06 to styling/QA; any new behavior becomes a follow-up.
- **Default theme switch risk** → do **not** make `mirageapp` the default in this PR. That is an operational decision to be made later once users have had a chance to opt in.

---

## Optional follow-up (separate PR)

Once Plan 06 lands and is validated:

- Move `mirageappManifest` to index 0 in `THEME_MANIFESTS` to make it the default.
- Add a legacy-id mapping if needed.
- Announce the new theme in `docs/whats-new.md`.

---

## PR description template

> Finishes the remaining `mirageapp` routes, performs a spacing/typography/state/responsive polish pass, and completes QA. Theme is now feature-complete but not yet the default.
