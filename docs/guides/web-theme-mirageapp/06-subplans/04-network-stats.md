# Sub-Plan 06.4 — Network + Stats

**Routes:** `/network`, `/server`, `/stats`
**Files:** `web/frontend/src/themes/mirageapp/routes/{NetworkView,StatsView}.js`
**Status:** ✅ Done
**Parent:** [`../06-remaining-routes-and-polish.md`](../06-remaining-routes-and-polish.md)

---

## What shipped

Both routes were rewritten from near-identical copies of `oldreddit` into panel-based info pages with the shared `mirageapp` header / tabs / `InfoPanel` pattern. All data wiring (`useNetwork`, `useStats`, polling, pagination) is unchanged — the rewrite is visual only.

### Shared primitives (applied to both routes)

- **Shell** — `NetworkWrap` / `StatsWrap` (90% width desktop, 100% tablet, `-0.75rem auto 0` margin), mirroring `SettingsView` / `FollowsView`.
- **Header** — `HeaderRow` + `HeaderTitle` at `1.1rem / 700 / -0.01em` (R7 page heading).
- **Divider** — `SectionDivider` between header and tabs (R3 `1px solid border`).
- **Tabs** — grid-based `TabsRow` with animated `TabIndicator` underline (2px `focusBlue`), matches `FollowsView` / `CreatePostView`. Inactive `0.75rem / 500 / subtleText`, active `0.75rem / 600 / text`.
- **`InfoPanel`** — `panel` background, `1px solid border`, `10px` radius, `overflow: hidden`. This is the only lifted surface on the page; the column itself stays on `bg` (R1).
- **`PanelHeader`** — `0.62rem / 700 / subtleText`, uppercase, `0.06em` letter-spacing, bottom border divider.
- **`PanelBody` / `ChartPanelBody` / `PanelBodyPadded`** — row containers with different paddings depending on content type (data rows, charts, summary tiles).
- **`DataRow`** — 2-column grid (label left / value right), `1px solid borderSubtle` between rows, collapses to single column on mobile.
- **`DataLabel`** — `0.7rem / 500 / subtleText`.
- **`DataValue`** — `0.8rem / 600 / text`, Monaco mono font for numeric / address values.
- **`Placeholder`** — `0.8rem / 500 / subtleText` mono for `(loading…)` states.

### NetworkView (`/network`, `/server`)

- **Tabs:** `Network` / `Server` (wired to `/network` and `/server` routes via `handleTabChange` from `useNetwork`).
- **Chain Info panel** — Circulation, Block Time, Difficulty, Msgs/Window, Calm Streak, Height.
- **Difficulty History panel** — `DifficultyChart` with restyled colors (grid → `border`, text → `subtleText`, difficulty line → `focusBlue`, msgs line + area → `voteUp` + `voteUpBg`).
- **Minted vs Burned panel** — `BurnMintChart` with `voteUp`/`voteUpBg` and `voteDown`/`voteDownBg`.
- **Total Supply panel** — `SupplyChart` colored by delta sign (up/down tokens).
- **Sites panel** — `PeerList` + `PeerRow` (link → `link` token, meta → `subtleText`). No custom `#667eea` hover.
- **Top Holders panel** — `AccountList` with rank, username link, compact balance (Monaco mono).
- **Validator Balance panel** (Server tab) — Staked, Balance, Earned (24h), Burned (24h).
  - Earned (24h) renders as a **`StatusPill`** with `voteUp` tone when positive (`voteUpBg` + `voteUp` text).
  - Burned (24h) renders as a **`StatusPill`** with `voteDown` tone when positive (`voteDownBg` + `voteDown` text).
  - Neutral tone falls back to `accent` + `text`.
- **Validator Addresses panel** (Server tab) — Address / Valoper / Valcons rows with inline mono + `Copy` button (`Button` component from `mirageapp/components`).
- **Node Balance panel** (Server tab) — `NodeBalanceChart` colored by delta sign.
- **Earned vs Spent panel** (Server tab) — `NodeMintBurnChart` with `voteUp` / `voteDown`.

All charts use a shared `chartColors(theme)` helper that reads from R2 tokens so colors stay in sync across dark / light modes.

Dropped: `OldRedditContentBleed`, `OldRedditTabsStrip`, `OldRedditTabsRow`, `OldRedditTab` (no more oldreddit imports). Dropped hard-coded `#667eea` / `#48bb78` / `#f56565` / `#888` / `#444` hex values from SVG charts.

### StatsView (`/stats`)

- **Tabs:** `Overview` / `Signups` / `Subscribers` / `Accounts` / `Rewards` (5 tabs, all wired through `useStats::activeTab` + `setActiveTab`).
- **Overview tab** — four panels:
  - **Usage** — DAUs, MAUs, Total Registered, New Registrations, Subscribers. Tier subscribers render as indented `SubRow` with tier-colored `SubLabel` (`TIER_COLORS`, kept per 06.1 intentional decision).
  - **Content** — Posts / Comments / Votes.
  - **Engagement** — Votes (↑/↓), Avg Posts/User, Avg Comments/Post, Avg Votes/User, Edit %, Delete %.
  - **Active Topics** + **Content Tags** — data rows using `DataRow` pattern.
  - **Trend indicator** — up/down/same arrow now uses `voteUp` / `voteDown` / `subtleText` tokens (was `#22c55e` / `#dc2626` / `#888`).
- **Signups tab** — Invite Code Summary (`SummaryGrid` of 3 tiles), Top Referrers table, Recent Signups table.
- **Subscribers tab** — Subscriber Summary tiles, per-tier panels with tier-colored `TierBadge` in the panel header (`#F59E0B` / `#EF4444` kept as tier visual language per 06.1).
- **Accounts tab** — Total Accounts summary tile + Top 100 accounts table.
- **Rewards tab** —
  - Reward Pool Status (3 tiles).
  - Overall Statistics (4 tiles).
  - Per-User Breakdown table with expandable rows. Expanded rows show Claimed (`voteUp`) / Pending (`inboxHighlightRail`) / Reward Count / First Reward / Last Reward / Account Created.
  - Reward History list — each `RewardRow` has a left-rail accent (`voteUp` when claimed, `inboxHighlightRail` when pending) on a `voteUpBg` / `inboxHighlightBg` tile.
  - `LoadMoreBtn` — dashed `border` pill that lifts to `borderStrong` on hover.
- **Loading / Error / Empty states** — `StateBlock` with `LoadingSpinner` (uses `focusBlue` top stroke), `ErrorMessage` (uses `buttonDangerBg` / `buttonDangerBorder` / `voteDown`), and `SectionEmpty` italic notes.
- **Tables** — `Th` at `0.62rem / 700 uppercase / subtleText` with `border` bottom; `Td` at `0.72rem / text` with `borderSubtle` between rows. `MonoText` helper for numeric cells.
- **Badges** — `SUB` / flair badges now routed through `voteUpBg` / `voteDownBg` tokens (was raw `#F59E0B20` / `#EF444420`).

Dropped: all `OldReddit*` imports and primitives, the old `SectionTitle` / `SectionNote` / `SummaryBox` / `SummaryItem` components, the legacy `Row` / `Label` / `ValueBox` / `Mono` / `StatList` / `StatItem` primitives, and every raw hex/rgba (`#dc2626`, `#22c55e`, `#f59e0b`, `#888`, `#666`, `rgba(102, 126, 234, …)`) from inline styles.

---

## R4 references consulted

- `themes/bluemoon/routes/NetworkView.js`, `StatsView.js` — data-field parity baseline. No fields dropped (every chart, row, tile, and table bluemoon shows is still rendered in mirageapp).
- `themes/mirageapp/routes/SettingsView.js`, `FollowsView.js`, `CreatePostView.js` — canonical `HeaderRow` / `HeaderTitle` / `SectionDivider` / `TabsRow` / `TabButton` / `TabIndicator` pattern.
- `themes/mirageapp/RULES.md` — R1 (bg canvas), R2 (tokens only), R3 (border divider), R5 (input focus — N/A here), R7 (font scale).

---

## Verification

- [x] Panels use R2 tokens only (no raw hex / rgba remain except the three `TIER_COLORS` values kept per 06.1 intentional decision).
- [x] Chart containers match panel styling (`InfoPanel` wrap + `ChartPanelBody` padding).
- [x] Chart axes / grid colors read from `border`; chart text from `subtleText`.
- [x] Chart series read from `focusBlue` / `voteUp` / `voteDown` + matching `*Bg` tints.
- [x] Data parity with bluemoon for both NetworkView and StatsView.
- [x] Dark + light should remain legible (chart lines use tokenized colors that have both dark + light values in `tokens.js`).
- [x] Build passes:

```bash
cd web/frontend
CI=true npm run build
```

Output: `Compiled successfully.`

---

## PR description template

> mirageapp `NetworkView` + `StatsView`: panel-based rewrite per sub-plan 06.4.
>
> - New shared shell: `HeaderRow` / `HeaderTitle` (1.1rem/700) + `SectionDivider` + `TabsRow` with `focusBlue` `TabIndicator` underline, matching `SettingsView` / `FollowsView` / `CreatePostView`.
> - New `InfoPanel` pattern — `panel` bg, `border` outline, `10px` radius; only lifted surface on the page (R1 keeps the column on `bg`).
> - `DataRow` layout: `0.7rem / 500 subtleText` label + `0.8rem / 600 text` mono value (R7).
> - NetworkView: 2 tabs (Network / Server). Server-tab Earned/Burned render as `StatusPill` with `voteUp` / `voteDown` tokens.
> - StatsView: 5 tabs (Overview / Signups / Subscribers / Accounts / Rewards). Summary tiles, per-tier subscriber tables, expandable reward breakdown, and reward history list — all tokenized.
> - Charts keep their existing SVG logic; only container, grid, axis, and series colors swapped for R2 tokens via a shared `chartColors(theme)` helper.
> - Dropped all `OldReddit*` Layout imports, `#667eea` / `#48bb78` / `#f56565` / `#888` / `#444` hex values, and the `#F59E0B20` / `#EF444420` badge raws. Tier colors kept per 06.1 intentional decision.
> - Data wiring, API calls, and `useNetwork` / `useStats` hooks untouched.
>
> Closes sub-plan 06.4.
