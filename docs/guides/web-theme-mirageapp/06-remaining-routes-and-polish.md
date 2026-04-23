# Plan 06 — Remaining Routes, Components, Polish, QA

**Goal:** Finish every route and every component that still renders in `oldreddit` style, perform a polish pass across the whole `mirageapp` theme, and verify it is ready to be the default.

**Depends on:** Plans 01–05.
**Unblocks:** making `mirageapp` the default theme (optional — can happen later).

**Status:** ⏳ Not started. Split into sub-plans under [`06-subplans/`](./06-subplans/README.md).

---

## Why this plan expanded (2026-04-18 audit)

A full diff of `themes/mirageapp/**` vs `themes/oldreddit/**` revealed that a large set of routes and components were **copied from `oldreddit` with only `MobileHeader` mounted** and never actually restyled. They still use oldreddit tokens, spacing, and typography — which means every one of these screens currently violates R1, R2, R5, and R7 from [`RULES.md`](./RULES.md).

Per-route current state (from the audit):

| Route | File | Diff vs oldreddit | State |
|---|---|---|---|
| Profile | `routes/ProfileView.js` | 5 lines | **oldreddit clone** (was Plan 04 leftover) |
| Discover | `routes/DiscoverView.js` | 2 lines | oldreddit clone |
| Agents | `routes/AgentsView.js` | 3 lines | oldreddit clone |
| Follows | `routes/FollowsView.js` | 2 lines | oldreddit clone |
| Blocks | `routes/BlocksView.js` | 2 lines | oldreddit clone |
| Reports | `routes/ReportsView.js` | 6 lines | oldreddit clone |
| Network | `routes/NetworkView.js` | 2 lines | oldreddit clone |
| Stats | `routes/StatsView.js` | 3 lines | oldreddit clone |
| Subscription | `routes/SubscriptionView.js` | 2 lines | oldreddit clone |
| Referrals | `routes/ReferralsView.js` | 2 lines | oldreddit clone |
| Bridge | `routes/BridgeView.js` | 2 lines | oldreddit clone (logic complex) |
| NotFound | `routes/NotFoundView.js` | 2 lines | oldreddit clone |

Per-component current state:

| Component | File | Diff vs oldreddit | State |
|---|---|---|---|
| Button | `components/Button.js` | restyled in 06.2 | used everywhere |
| Toast | `components/Toast.js` | restyled in 06.2 | required theme component |
| Tooltip | `components/Tooltip.js` | restyled in 06.2 | required theme component |
| UnlockPrompt | `components/UnlockPrompt.js` | restyled in 06.2 | required theme component |
| MobileBottomNav | `components/MobileBottomNav.js` | 10 lines | near-identical (deferred from Plan 02, tracked in sub-plan 08) |

> `InlineMedia`, `MediaGallery`, `MarkdownRenderer`, `QuestHeroCard`, `FilterBar`, `MediaAttachmentLayout`, and `MarkdownEditor` are intentionally left as-is and are **not** part of Plan 06's restyle scope.

---

## Scope

See the sub-plan index: [`06-subplans/README.md`](./06-subplans/README.md). Summary:

1. **Profile** — `ProfileView` + header/tabs (Plan 04 leftover)
2. **Component restyle pass** — Button, Toast, Tooltip, UnlockPrompt (globals only) — ✅ Done
3. **Social routes** — Follows, Blocks, Reports
4. **Network + Stats**
5. **Subscription + Referrals**
6. **Bridge**
7. **Agents + Discover + NotFound**
8. **MobileBottomNav** (deferred from Plan 02)
9. **Polish + QA** (spacing, typography, state, responsive, accessibility, optional default-theme switch)

### Out of scope

- New features.
- Data layer changes (no modifications to hooks in `logic/` or shared utils).

---

## Global rules for every sub-plan

> 📐 Read [`RULES.md`](./RULES.md) before touching any file. R1–R7 are mandatory.

- Every sub-plan must apply the R2 color tokens, R3 dividers, R5 input focus style, R6 chevron, and R7 font scale.
- No `themes/oldreddit/*` or `themes/bluemoon/*` imports inside `themes/mirageapp/*`.
- Data parity with `bluemoon` (R4) — nothing bluemoon shows may be dropped.
- Visual reference from `mirage-mobile-app` (R4) — spacing, icons, typography.
- Dark + light must both be verified manually in the browser.
- Build must pass:

```bash
cd web/frontend
CI=true npm run build
```

---

## Polish pass (sub-plan 09) checklist

Applied as a single sweep once all routes + components are restyled.

### Spacing
- [ ] No ad-hoc pixel values inside components. Everything comes from `Layout.js` / token helpers.
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
- [ ] Focus: R5 style (neutral `borderStrong`, no blue ring) on every input.
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

## QA checklist (sub-plan 09)

- [ ] Click through every nav item in TopBar + Sidebar + MobileBottomNav.
- [ ] Perform a vote, comment, follow, and block while on `mirageapp`.
- [ ] Create and delete a test post.
- [ ] Switch to each other theme (`bluemoon`, `onyx`, `oldreddit`) and back.
- [ ] Toggle dark/light at least 3 different routes.
- [ ] Run the build with `CI=true npm run build`.
- [ ] Confirm no errors thrown from the theme registry at startup.

---

## Risks & mitigations

- **Regression in other themes** → do side-by-side testing; shared logic must not be touched.
- **Polish pass scope creep** → limit sub-plan 09 to styling/QA; any new behavior becomes a follow-up.
- **Default theme switch risk** → do **not** flip `mirageapp` to index 0 in `THEME_MANIFESTS` until sub-plan 09 is merged and validated.

---

## Optional follow-up (separate PR after sub-plan 09)

- Move `mirageappManifest` to index 0 in `THEME_MANIFESTS` to make it the default.
- Add a legacy-id mapping if needed.
- Announce the new theme in `docs/whats-new.md`.

---

## PR description template (per sub-plan)

> [Sub-plan NN / short title] — restyles `<routes|components>` in `mirageapp` to use R1–R7 tokens and mobile-app visuals. Visual only. Closes sub-plan NN of Plan 06.
