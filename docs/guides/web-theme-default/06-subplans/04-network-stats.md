# Sub-Plan 06.4 — Network + Stats

**Routes:** `/network`, `/server`, `/stats`
**Files:** `web/frontend/src/themes/default/routes/{NetworkView,StatsView}.js`
**Status:** ✅ Done
**Parent:** [`../06-remaining-routes-and-polish.md`](../06-remaining-routes-and-polish.md)

---

## What shipped

Both routes were rewritten from near-identical copies of `oldreddit` into **flat section-list pages** matching the `SettingsView` + `ProfileView` pattern. All data wiring (`useNetwork`, `useStats`, polling, pagination) is unchanged — the rewrite is visual only.

The initial pass used a panel-based (`InfoPanel`) layout with lifted surfaces. That was replaced in a follow-up refinement with a fully flat section-list layout so NetworkView / StatsView read like Settings (section headers + rows on `bg`, dividers via `border`) and adopt ProfileView's label/value row typography.

### Shared primitives (applied to both routes)

- **Shell** — `NetworkWrap` / `StatsWrap` (90% width desktop, 100% tablet, `-0.75rem auto 0` margin), mirroring `SettingsView` / `FollowsView`.
- **Header** — `HeaderRow` + `HeaderTitle` at `1.1rem / 700 / -0.01em` (R7 page heading).
- **Divider** — `SectionDivider` between header and tabs (R3 `1px solid border`).
- **Tabs** — grid-based `TabsRow` with animated `TabIndicator` underline (2px `focusBlue`), matches `FollowsView` / `CreatePostView`. Inactive `0.75rem / 500 / subtleText`, active `0.75rem / 600 / text`.
- **`Section` / `SectionHeader` / `SectionBody`** — flat containers on `theme.colors.bg` (R1). No lifted background, no border, no radius.
  - `SectionHeader`: `0.6rem / 700 uppercase subtleText`, `0.06em` letter-spacing — identical to SettingsView's group labels.
  - `SectionBody`: row container with `0.35rem 1rem` vertical padding.
- **`FieldRow`** (ProfileView pattern) — grid `160px minmax(0, 1fr)`, `1.5rem` gap, `align-items: center`, padding `0.55rem 1rem`. Collapses gap on tablet, stacks on mobile.
- **`FieldLabel`** — `0.72rem / 500 / text`.
- **`FieldValue`** / **`ValueText`** — `0.72rem / 500 / cardBodyText`. No monospace (matches Profile's label/value rows).
- **`Placeholder`** — `0.72rem / 500 / subtleText` for `(loading…)` states.

### NetworkView (`/network`, `/server`)

- **Tabs:** `Network` / `Server` (wired to `/network` and `/server` routes via `handleTabChange` from `useNetwork`).
- **Chain Info section** — Circulation, Block Time, Difficulty, Msgs/Window, Calm Streak, Height as `FieldRow`s.
- **Chart rows** — `ChartRow` (grid `160px minmax(0, 1fr)`, `align-items: start`, padding `0.55rem 1rem`) places the chart title on the left as a `ChartRowLabel` (`0.72rem / 500 / text`, `white-space: nowrap`) and the chart on the right on the same top line as the legend. Replaced the earlier `Section` + `SectionHeader` wrapping for every chart. Used for:
  - **Difficulty History** — `DifficultyChart` (difficulty line → `focusBlue`, msgs line + area → `voteUp` + `voteUpBg`).
  - **Minted vs Burned** — `BurnMintChart` (`voteUp`/`voteUpBg` + `voteDown`/`voteDownBg`).
  - **Total Supply** — `SupplyChart` colored by delta sign.
  - **Node Balance** (Server tab) — `NodeBalanceChart`.
  - **Earned vs Spent** (Server tab) — `NodeMintBurnChart`.
- **Sites section** — `PeerRow`s flush-left, no row divider.
- **Top Holders section** — `AccountRow` restructured from a 3-column grid to flex so the rank aligns flush with the Sites list (`AccountRank` `flex-shrink: 0`, `min-width: 1.25rem`), no row divider.
- **Validator Balance section** (Server tab) — Staked, Balance, Earned (24h), Spent (24h).
  - Earned (24h) renders as a **`StatusPill`** with `voteUp` tone when positive (`voteUpBg` + `voteUp` text).
  - Spent (24h) renders as a **`StatusPill`** with `voteDown` tone when positive (`voteDownBg` + `voteDown` text).
  - Values use `formatMirageCompact` → K/M/B suffixes.
- **Validator Addresses section** (Server tab) — Address / Valoper / Valcons rows. Copy action is now an **`IconActionButton`** (28×28 pill, `actionIconBg` / `actionIconHoverBg`, `buttonSuccessBg` + `voteUp` on success, `HiClipboardDocument` → `HiCheck`) — matches ProfileView's address-copy pattern. The old `Button` text ("Copy" / "Copied!") is gone.

All charts use a shared `chartColors(theme)` helper that reads from R2 tokens so colors stay in sync across dark / light modes. Chart grey text (`ChartLabel`, `LegendItem`, `chartColors.text`, `chartColors.neutral`) now uses `cardBodyText` instead of `subtleText` so axis + legend labels match the color of `FieldValue` text throughout the page.

Dropped: `OldRedditContentBleed`, `OldRedditTabsStrip`, `OldRedditTabsRow`, `OldRedditTab`, `Button` import, `ChartSectionBody`, `InfoPanel`, `PanelHeader`, `PanelBody`, `ChartPanelBody`, `PanelBodyPadded`, `DataRow`, `DataLabel`, `DataValue` (no more oldreddit imports, no more lifted panel primitives). Dropped hard-coded `#667eea` / `#48bb78` / `#f56565` / `#888` / `#444` hex values from SVG charts. Swapped `formatMirage` → `formatMirageCompact` for all balance displays.

### StatsView (`/stats`)

- **Tabs:** `Overview` / `Signups` / `Subscribers` / `Accounts` / `Rewards` (5 tabs, all wired through `useStats::activeTab` + `setActiveTab`).
- **Overview tab** — flat sections:
  - **Usage** — DAUs, MAUs, Total Registered, New Registrations, Subscribers. Tier subscribers render as indented `SubRow` with tier-colored `SubLabel` (`TIER_COLORS`, kept per 06.1 intentional decision).
  - **Content** — Posts / Comments / Votes.
  - **Engagement** — Votes (↑/↓), Avg Posts/User, Avg Comments/Post, Avg Votes/User, Edit %, Delete %.
  - **Active Topics** + **Content Tags** — data rows using `FieldRow` pattern.
  - **Trend indicator** — up/down/same arrow uses `voteUp` / `voteDown` / `subtleText` tokens.
- **Signups tab** — Invite Code Summary (`SummaryGrid` of 3 tiles with transparent background), Top Referrers table, Recent Signups table.
- **Subscribers tab** — Subscriber Summary tiles, per-tier sections with tier-colored `TierBadge` (`#F59E0B` / `#EF4444` kept as tier visual language per 06.1).
- **Accounts tab** — Total Accounts summary tile + Top 100 accounts table.
- **Rewards tab** —
  - Reward Pool Status (3 tiles).
  - Overall Statistics (4 tiles).
  - Per-User Breakdown table with expandable rows. Expanded rows show Claimed (`voteUp`) / Pending (`inboxHighlightRail`) / Reward Count / First Reward / Last Reward / Account Created.
  - Reward History list — each `RewardRow` has a transparent background with a left-rail accent (`voteUp` when claimed, `inboxHighlightRail` when pending) and a subtle `borderSubtle` outline.
  - `LoadMoreBtn` — dashed `border` pill that lifts to `borderStrong` on hover.
- **Loading / Error / Empty states** — `StateBlock` with `LoadingSpinner` (uses `focusBlue` top stroke), `ErrorMessage` (uses `buttonDangerBg` / `buttonDangerBorder` / `voteDown`), and `SectionEmpty` italic notes.
- **Tables** — `Th` at `0.6rem / 700 uppercase / subtleText` with `0.06em` letter-spacing (matches `SectionHeader`); `Td` at `0.72rem / 500 / cardBodyText` with `borderSubtle` between rows.
- **Badges** — `SUB` / flair badges routed through `voteUpBg` / `voteDownBg` tokens.
- **K/M/B format** — every umirage value renders via `formatMirageCompact` (pool balance, daily rate, total/claimed/pending, per-user earned, earnings per day, reward amounts). The destructured `formatMirage` from `useStats()` is no longer used.

Dropped: all `OldReddit*` imports and primitives, the old `SectionTitle` / `SectionNote` / `SummaryBox` / `SummaryItem` components, the legacy `Row` / `Label` / `ValueBox` / `Mono` / `StatList` / `StatItem` primitives, `InfoPanel` and the panel-lifted look (`SummaryTile` / `RewardRow` / `ExpandedRow` all sit on `bg` with transparent backgrounds), and every raw hex/rgba (`#dc2626`, `#22c55e`, `#f59e0b`, `#888`, `#666`, `rgba(102, 126, 234, …)`) from inline styles.

---

## Layout refinements applied after initial ship

1. **Panel → flat section-list.** Removed `InfoPanel` (lifted `panel` bg + border + 10px radius). Sections are now flush on `bg`, matching `SettingsView`.
2. **ProfileView-style rows.** `FieldRow` mirrors `ProfileFieldRow`: grid `160px minmax(0, 1fr)`, 0.72rem / 500 labels + values, `cardBodyText` values, no monospace.
3. **K/M/B formatting.** All balance / supply / rate displays on both routes now use `formatMirageCompact` so `1,234,567 MIRAGE` becomes `1.2M MIRAGE`.
4. **Chart layout.** Introduced `ChartRow` + `ChartRowLabel`: chart title sits on the left at the same top line as the chart's legend (via `align-items: start` + matching typography to `FieldLabel`). Label column widened from `110px` → `160px` so multi-word titles ("Difficulty History:", "Earned vs Spent:") no longer wrap.
5. **Top Holders indent.** `AccountRow` switched from grid (`2rem 1fr auto`) to flex so the rank starts flush with the Sites list's left padding. Row dividers removed from both `PeerRow` and `AccountRow`.
6. **Copy button.** Server-tab validator address copy actions use `IconActionButton` (ProfileView pattern) with `HiClipboardDocument` / `HiCheck` icons, replacing the text `Button`.
7. **Chart grey text → value color.** `ChartLabel`, `LegendItem`, and both `chartColors.text` / `chartColors.neutral` swapped from `subtleText` to `cardBodyText` so axis + legend labels match `FieldValue` color.

---

## R4 references consulted

- `themes/bluemoon/routes/NetworkView.js`, `StatsView.js` — data-field parity baseline. No fields dropped (every chart, row, tile, and table bluemoon shows is still rendered in default).
- `themes/default/routes/SettingsView.js` — canonical section-list pattern (`SectionHeader` 0.6rem/700 uppercase + rows on `bg`).
- `themes/default/routes/ProfileView.js` — canonical `FieldRow` (label/value) + `IconActionButton` (copy-address) patterns.
- `themes/default/routes/FollowsView.js`, `CreatePostView.js` — `HeaderRow` / `HeaderTitle` / `SectionDivider` / `TabsRow` / `TabButton` / `TabIndicator` pattern.
- `themes/default/RULES.md` — R1 (bg canvas — no lifted panels for full-column content), R2 (tokens only), R3 (border divider), R7 (font scale).

---

## Verification

- [x] Sections use R2 tokens only (no raw hex / rgba remain except the three `TIER_COLORS` values kept per 06.1 intentional decision).
- [x] No `InfoPanel` / lifted surfaces — entire page sits on `theme.colors.bg`.
- [x] Field rows match ProfileView's 160px label / value grid + 0.72rem / 500 typography.
- [x] Section headers match SettingsView's 0.6rem / 700 uppercase / subtleText / 0.06em pattern.
- [x] All umirage values render via `formatMirageCompact` (K/M/B).
- [x] Chart axes / grid colors read from `border`; chart text + legend read from `cardBodyText`.
- [x] Chart series read from `focusBlue` / `voteUp` / `voteDown` + matching `*Bg` tints.
- [x] `ChartRow` puts title on the left, aligned to the top of the chart, without wrapping.
- [x] `AccountRow` (Top Holders) aligns flush-left with the Sites list; no row dividers.
- [x] Server-tab copy actions use `IconActionButton` + `HiClipboardDocument` / `HiCheck`.
- [x] Data parity with bluemoon for both NetworkView and StatsView.
- [x] Dark + light remain legible (chart lines use tokenized colors that have both dark + light values in `tokens.js`).
- [x] Build passes:

```bash
cd web/frontend
CI=true npm run build
```

Output: `Compiled successfully.`

---

## PR description template

> default `NetworkView` + `StatsView`: flat section-list rewrite per sub-plan 06.4.
>
> - New shared shell: `HeaderRow` / `HeaderTitle` (1.1rem/700) + `SectionDivider` + `TabsRow` with `focusBlue` `TabIndicator` underline, matching `SettingsView` / `FollowsView` / `CreatePostView`.
> - Flat section-list layout (R1): `Section` / `SectionHeader` / `SectionBody` on `theme.colors.bg`, no lifted `InfoPanel` surfaces.
> - `FieldRow` adopts ProfileView's label/value grid: `160px minmax(0, 1fr)`, 0.72rem / 500 labels + values, `cardBodyText` values.
> - NetworkView: 2 tabs (Network / Server). `ChartRow` places chart titles on the left aligned with the chart's top line. Server-tab Earned/Burned render as `StatusPill`; validator-address copy actions use `IconActionButton` with `HiClipboardDocument` / `HiCheck`.
> - StatsView: 5 tabs (Overview / Signups / Subscribers / Accounts / Rewards). Summary tiles, per-tier subscriber tables, expandable reward breakdown, and reward history list — all transparent / flat / tokenized.
> - Every umirage value now renders via `formatMirageCompact` (K/M/B).
> - Charts keep their existing SVG logic; container, grid, axis, legend, and series colors all read from R2 tokens via a shared `chartColors(theme)` helper. Grey axis / legend text now uses `cardBodyText` to match field values.
> - Dropped all `OldReddit*` Layout imports, the `Button` text copy control, the `InfoPanel` / `PanelHeader` / `PanelBody` / `ChartPanelBody` primitives, and every raw hex/rgba. Tier colors kept per 06.1 intentional decision.
> - Data wiring, API calls, and `useNetwork` / `useStats` hooks untouched.
>
> Closes sub-plan 06.4.
