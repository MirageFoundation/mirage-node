# default Web Theme — Plan Overview

This folder contains the plan for building a new Mirage web theme named **`default`** that combines:

- **Mobile app visual language** — colors, spacing, radius, typography (from `mirage-mobile-app`)
- **Reddit-style desktop layout** — top nav, sidebar, structured feed, discussion-forum framing

The work is split across six per-PR plans so each phase ships independently and stays reviewable.

> **📐 Style rules:** Before touching any UI in `default`, read [`RULES.md`](./RULES.md). It covers background tokens, dark↔light color pairs, divider rules, and the required bluemoon + mobile reference check.

---

## Why a new theme family (not a restyle)

Mirage web themes are **full UI families**, not skins. They own:

- `Style`, `Shell`, `Feed`, `VoteSection`
- all route components
- theme-local components (TopBar, Sidebar, CardView, etc.)
- tokens (colors, layout, typography)

Because of that, mobile-like colors + Reddit-like layout cannot be achieved with token-only edits. The theme system is already designed for this use case — we just need to add a new entry.

Shared behavior (API, tx, crypto, storage, data hooks) stays in `web/frontend/src/logic/` and `web/frontend/src/utils/` and is **not** modified by this theme.

---

## Hybrid design rule

Whenever desktop structure and mobile visuals conflict:

- **Desktop layout/structure** → take cues from Reddit / the existing `oldreddit` theme
- **Visual tokens + mobile feel** → take cues from `mirage-mobile-app`

---

## Plans in this folder

| Plan | Scope | Status | Doc |
|---|---|---|---|
| 01 | Theme skeleton, tokens, registration | ✅ Done | [`01-skeleton-and-tokens.md`](./01-skeleton-and-tokens.md) |
| 02 | Shell, top nav, sidebar, mobile nav | ✅ Done (MobileBottomNav full restyle deferred → Plan 06) | [`02-shell-nav-sidebar.md`](./02-shell-nav-sidebar.md) |
| 03 | Feed, card view, vote / action row | ✅ Done (manual cross-theme browser regression still recommended) | [`03-feed-and-card.md`](./03-feed-and-card.md) |
| 04 | Post detail + profile | ✅ Done — post-detail shipped as sub-plan 05.3; profile closed by sub-plan 06.1 (tokenization pass) | [`04-post-detail-and-profile.md`](./04-post-detail-and-profile.md) |
| 05 | Inbox, search, settings, auth flows | ✅ Done | [`05-inbox-search-settings-auth.md`](./05-inbox-search-settings-auth.md) |
| 06 | Remaining routes, components, polish, QA | ✅ Done — all sub-plans landed (06.6 ⏭️ skipped) | [`06-remaining-routes-and-polish.md`](./06-remaining-routes-and-polish.md) |

Each plan is designed to be one PR (or a series of one-PR sub-plans). Later plans depend on earlier ones landing first.

### Current focus

**Onboarding UI is shipped.** `/login`, `/signup`, and `/welcome` in `default` were redesigned with styled components, a new `AuthPageShell`, theme-aware light/dark backgrounds, and reusable header/brand primitives (commit `ceef3d7`). `default` is now the default theme when available in the registry.

**Plan 05 sub-plans** under [`05-subplans/`](./05-subplans/README.md) (order reshuffled: Post Details pulled forward so the feed → post flow is visually consistent end-to-end):

1. [Inbox](./05-subplans/01-inbox.md) — ✅ Done
2. [Search](./05-subplans/02-search.md) — ✅ Done
3. [Post Details](./05-subplans/03-post-details.md) — ✅ Done
4. [Settings](./05-subplans/04-settings.md) — ✅ Done
5. [Create Post](./05-subplans/05-create-post.md) — ✅ Done
6. [Change Username](./05-subplans/06-change-username.md) — ✅ Done
7. [Sign Out](./05-subplans/07-sign-out.md) — ✅ Done (closes Plan 05)

**Next focus:** Plan 06 is closed. All sub-plans 06.1 – 06.5, 06.7 – 06.11 ✅ done; 06.6 ⏭️ skipped. Sub-plan [`06-subplans/11-admin-ui.md`](./06-subplans/11-admin-ui.md) (Admin UI pass) landed last — A (`tierAdmin` token), B (profile menu), C (Subscription admin branch), D (post-detail `ConfirmDialog`/`Toast`), E (feed-row admin parity via the new `useAdminQuestActions` hook in `CardView`/`PostMenu`), and F (cleanup + grep gates) all green. Optional follow-up: flip `defaultManifest` to index 0 in `THEME_MANIFESTS` to make `default` the registry default.

Plan 04 (post detail + profile) was originally deferred; the post-detail slice shipped as sub-plan 05.3, and the profile slice closed via a tokenization-only pass in sub-plan [`06-subplans/01-profile.md`](./06-subplans/01-profile.md) (full header/tabs rewrite dropped by design decision). Plans 02 and 03 stay complete (with the `MobileBottomNav` full restyle still deferred).

---

### ⚠️ 2026-04-18 audit — pending work that wasn't in the original plan

A full diff of `themes/default/**` vs `themes/oldreddit/**` revealed that a large number of routes and components are still **byte-identical or near-identical copies of `oldreddit`** (only the `MobileHeader` import + mount was added). They were never restyled with default tokens/typography. The [`06-subplans/`](./06-subplans/README.md) folder captures the full follow-up work. Summary:

**Routes still rendering in oldreddit style** (need full default restyle):

- `DiscoverView.js`, `AgentsView.js`
- `SubscriptionView.js`, `ReferralsView.js`
- `NotFoundView.js`

> `FollowsView.js`, `BlocksView.js`, `ReportsView.js` were restyled in sub-plan 06.3. `NetworkView.js`, `StatsView.js` were restyled in sub-plan 06.4.

**Components still identical (or ≤10-line diff) to oldreddit** — not yet ported to default tokens/typography (R1/R2/R5/R7):

- `MobileBottomNav.js` (10-line diff — full restyle deferred from Plan 02, tracked in sub-plan 08)

> `Button.js`, `Toast.js`, `Tooltip.js`, `UnlockPrompt.js` were ported in sub-plan 06.2 Slice A.
>
> `InlineMedia.js`, `MediaGallery.js`, `MarkdownRenderer.js`, `QuestHeroCard.js`, `FilterBar.js`, `MediaAttachmentLayout.js`, and `MarkdownEditor.js` are intentionally left as-is and are **not** part of Plan 06's restyle scope.

**New Plan 06 sub-plans** (each a PR):

1. [`01-profile.md`](./06-subplans/01-profile.md) — `ProfileView` + profile header/tabs (was Plan 04 leftover)
2. [`02-component-restyle.md`](./06-subplans/02-component-restyle.md) — Button, Toast, Tooltip, InlineMedia, MediaGallery, UnlockPrompt, MarkdownRenderer, QuestHeroCard + finish passes on FilterBar / MarkdownEditor / MediaAttachmentLayout
3. [`03-social-routes.md`](./06-subplans/03-social-routes.md) — Follows, Blocks, Reports (list-row pattern)
4. [`04-network-stats.md`](./06-subplans/04-network-stats.md) — Network + Stats (info-panel + chart container)
5. [`05-subscription-referrals.md`](./06-subplans/05-subscription-referrals.md) — Subscription + Referrals
6. ~~Bridge~~ — removed permanently in v1.31.0 (no UI)
7. [`07-agents-discover-notfound.md`](./06-subplans/07-agents-discover-notfound.md) — Agents, Discover (topics), NotFound
8. [`08-mobile-bottom-nav.md`](./06-subplans/08-mobile-bottom-nav.md) — MobileBottomNav full restyle (deferred from Plan 02)
9. [`09-polish-and-qa.md`](./06-subplans/09-polish-and-qa.md) — spacing / typography / state / responsive / accessibility polish + QA + optional default-theme switch
10. [`10-loading-states-skeletons.md`](./06-subplans/10-loading-states-skeletons.md) — tokenized `Skeleton` primitive + per-route skeleton loaders; replaces inherited `Loading…` text (runs after 08, before 09)
11. [`11-admin-ui.md`](./06-subplans/11-admin-ui.md) — admin UI parity pass: profile menu admin group, Subscription admin branch, post-detail confirm banners → `ConfirmDialog`/`Toast`, feed-row admin parity (`CardView` + `PostMenu`), new `tierAdmin` R2 token (runs after 10, before 09)

---

## Source references (used across all plans)

### Web theme architecture
- `web/frontend/src/themes/README.md`
- `web/frontend/src/registry/theme.js`
- `web/frontend/src/themes/manifests.js`
- `web/frontend/src/views/README.md`
- `web/frontend/src/components/README.md`

### Structural starting point (desktop layout)
- `web/frontend/src/themes/oldreddit/`

### Secondary references (modern interactions)
- `web/frontend/src/themes/onyx/`
- `web/frontend/src/themes/bluemoon/`

### Mobile visual reference (`mirage-mobile-app`)
- `src/config/theme.ts`
- `src/config/sizing.ts`
- `src/components/molecules/feed-header.tsx`
- `src/components/molecules/post-card.tsx`
- `src/components/molecules/post-card-header.tsx`
- `src/components/molecules/post-actions.tsx`
- `app/(tabs)/_layout.tsx`

---

## Overall acceptance criteria

The default theme is considered done when:

- It is registered in `themes/manifests.js` and selectable from Settings.
- It has its own `Style`, `Shell`, `Feed`, `VoteSection`, `components`, and `routes`.
- Desktop layout is clearly Reddit-inspired (persistent top nav + sidebar + content column).
- Colors, spacing, typography, and overall tone are aligned with `mirage-mobile-app`.
- All theme route keys are implemented (no fallback failures at runtime).
- Dark and light modes both work.
- Responsive behavior is correct at desktop, tablet, and mobile widths.
- Build passes cleanly:

```bash
cd web/frontend
CI=true npm run build
```

---

## Global risks (applies to every plan)

- **CSS-only approach will fail** — treat this as a full theme family.
- **Cross-theme component imports cause long-term pain** — copy components into `default` and evolve them locally.
- **Route coverage gaps break navigation** — every theme route key from the registry must be implemented.
- **Mobile/desktop tension** — apply the hybrid rule above whenever there is a conflict.
