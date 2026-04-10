# mirageapp Web Theme — Plan Overview

This folder contains the plan for building a new Mirage web theme named **`mirageapp`** that combines:

- **Mobile app visual language** — colors, spacing, radius, typography (from `mirage-mobile-app`)
- **Reddit-style desktop layout** — top nav, sidebar, structured feed, discussion-forum framing

The work is split across six per-PR plans so each phase ships independently and stays reviewable.

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
| 02 | Shell, top nav, sidebar, mobile nav | ✅ Done (MobileBottomNav full restyle deferred) | [`02-shell-nav-sidebar.md`](./02-shell-nav-sidebar.md) |
| 03 | Feed, card view, vote / action row | ⏳ Not started — **next** | [`03-feed-and-card.md`](./03-feed-and-card.md) |
| 04 | Post detail + profile | ⏳ Not started | [`04-post-detail-and-profile.md`](./04-post-detail-and-profile.md) |
| 05 | Inbox, search, settings, auth flows | ⏳ Not started | [`05-inbox-search-settings-auth.md`](./05-inbox-search-settings-auth.md) |
| 06 | Remaining routes, polish, QA | ⏳ Not started | [`06-remaining-routes-and-polish.md`](./06-remaining-routes-and-polish.md) |

Each plan is designed to be one PR. Later plans depend on earlier ones landing first.

### Current focus

**Plan 03 → Feed, card view, vote / action row.** Plan 02 is complete: Shell, TopBar, and Sidebar are fully iterated. The sidebar was restructured (Feeds primary nav + collapsible Topics/Users sections), restyled with new `sidebarItem*` tokens, migrated to Heroicons v2 via `react-icons`, and got a sticky collapse button + divider column inside `MirageAppShell`. Layout/scrollbar jump-fixes landed (`scrollbar-gutter: stable`, locked TopBar height, `Layout` `min-height`). Only `MobileBottomNav` full restyle is deferred. Next up: start Plan 03 — restyle the feed and card view. Details in [`03-feed-and-card.md`](./03-feed-and-card.md).

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

The mirageapp theme is considered done when:

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
- **Cross-theme component imports cause long-term pain** — copy components into `mirageapp` and evolve them locally.
- **Route coverage gaps break navigation** — every theme route key from the registry must be implemented.
- **Mobile/desktop tension** — apply the hybrid rule above whenever there is a conflict.
