# Sub-Plan 06.1 — Profile

**Route:** `/profile`, `/u/:identity`
**File:** `web/frontend/src/themes/default/routes/ProfileView.js`
**Status:** ✅ Done — RULES.md compliance pass + Reddit-style layout + interaction polish
**Parent:** [`../06-remaining-routes-and-polish.md`](../06-remaining-routes-and-polish.md)

---

## What shipped

Nine-stage pass on `themes/default/routes/ProfileView.js` plus targeted fixes in `TopBar.js`, `utils/avatar.js`, `useProfile.js`, and `ListFeedView.js` (compact-row placeholder):

1. **Stage 1** — R2 tokenization (hex/rgba → tokens).
2. **Stage 2** — R1 / R5 / R7 compliance.
3. **Stage 3** — Header + tabs re-styled to match `SettingsView` + `CreatePostView`; per-row divider removed.
4. **Stage 4** — Settings-parity polish: header divider, tab underline alignment, algo tab rebuilt with Settings-style section headers and rows.
5. **Stage 5** — Reddit-style two-column layout: left column with avatar + display name + `u/handle` header above tabs, right sidebar with banner + identity card + stats grid + settings links.
6. **Stage 6** — Tier / avatar / seed alignment with mirage-mobile-app (Free tier default color, DiceBear seed parity, hard-pinned avatar bg, banner uses brand gradient).
7. **Stage 7** — Action-button layout: Follow moved to header right + compact in aside, Gift Sub moved next to Share as a 32px ActionPill, Gift Mirage restyled with icon + compact width, bio editor Save matches `CreatePostView::PostBtn`.
8. **Stage 8** — Comments-tab fix + compact-feed placeholder swap (letter sourced from author username instead of topic, letter color hard-pinned white).
9. **Stage 9** — Responsive polish: fixed label column so value rails align, gap collapses at `<1100px` instead of at mobile, `ProfileIdentity` hidden on `<1000px`, rows stay single-line on mobile, Balance / Reserve in compact `K`/`M`/`B` with uppercase suffix.

Data wiring is unchanged (all handlers still run through `useProfile`).

### Stage 1 — R2 tokenization

- **BioTextarea `:focus`** — `accent` → `borderStrong` (R5).
- **PostItem active glow** — dropped `box-shadow: 0 0 12px rgba(102,126,234,0.25)`; now uses `layout.cardShadow`.
- **Inline hard-coded colors → R2 tokens**:
  - `'#888'` → `theme.colors.subtleText` (pref-topics / pref-authors / similar-users loading/empty/error/expand rows, tier expiry suffix, bio char-count, bio empty placeholder — 9 sites).
  - `'#ff6b6b'` / `'#f87171'` / `'#ef4444'` → `theme.colors.voteDown` (7 sites).
  - `'#22c55e'` / `'#16a34a'` → `theme.colors.voteUp` (2 sites).
  - `'#f59e0b'` + `rgba(251, 191, 36, 0.1)` (confirm banners) → `inboxHighlightRail` + `inboxHighlightBg`.
  - `rgba(34, 197, 94, 0.1)` / `rgba(239, 68, 68, 0.1)` + `#22c55e` / `#ef4444` borders (result banners) → `buttonSuccessBg` / `buttonDangerBg` + `buttonSuccessBorder` / `buttonDangerBorder`.

### Stage 2 — R1 / R5 / R7 compliance (after rules audit)

- **R1 — profile tab strip now sits on `bg`.** New local `ProfileTabsStrip = styled(OldRedditTabsStrip)` wrapper overrides the base `panel` background to `theme.colors.bg`. `OldRedditTabsStrip` itself is untouched for other themes.
- **R1 — `ProfileInfoShell` no longer paints `panel`.** Background changed to `theme.colors.bg`, keeping the per-row `border-bottom` dividers (R3).
- **R1 — `PostItem:hover` uses `hoverBg`** instead of `panelAlt` (the list-row hover tile token per R2 "Hover surfaces").
- **R5 — `BioTextarea`** background `panelAlt` → `bg`; added `::placeholder` color, `:hover` `borderStrong`, explicit `:focus box-shadow: none`. Font forced to `0.75rem / 500` per R7 "Inputs".
- **R5 — `FilterSelect`** background `panelAlt` → `bg`; dropped `box-shadow: ${focusRing}`; explicit `:hover` `borderStrong`; size forced to `0.75rem / 500`.
- **R7 — `SectionTitle`** `font-weight: 700` → `600` (pairs correctly with token `sectionSize: 0.75rem`).
- **R7 — `PostMeta`** `font-size: 0.55rem` → `0.62rem / 500` (byline metadata, not eyebrow caps).
- **R7 — `ProfileSortTab`** now explicitly `0.75rem` with `font-weight: 600` active / `500` inactive (was inherited `tabWeight: 700`).
- **R7 — inline `fontSize: '0.82rem'`** (gift-sub / gift-mirage banners, 2 sites) → `0.8rem` (on-scale).
- **R7 — donate amount `<input>`** inline `fontSize: '0.8rem', fontWeight: 700` → `0.75rem / 500` (matches rule "Inputs — 0.75rem / 500").

### Stage 3 — Header + tabs restyle (SettingsView / CreatePostView parity)

- **Added `HeaderRow` + `HeaderTitle` "Profile"** (1.1rem / 700 / -0.01em) — same primitives as `SettingsView` and `CreatePostView`.
- **Added `ProfileWrap`** (90% width desktop, 100% tablet, `margin: -0.75rem auto 0`) — mirrors `SettingsWrap`.
- **Sub-tabs rewritten** to match `CreatePostView::TabsRow` / `TabButton`:
  - Transparent row with a single `1px solid border` bottom line.
  - Transparent buttons at `0.75rem / 600 active / 500 inactive`, `subtleText` → `text` on hover.
  - 2px `focusBlue` underline indicator on active tab (`::after`, `bottom: -1px`).
  - `focus-visible::after` → `borderStrong`.
- **Removed OldReddit primitives** — `OldRedditContentBleed`, `OldRedditTabsStrip`, `OldRedditTabsRow`, `OldRedditTab`, `OLDREDDIT_SHELL_INSET_X` import dropped. Local `ProfileTabsStrip`, `ProfileTabsRow`, `ProfileSortTab` styled components deleted.
- **Removed `ProfileInfoShell`** (full-bleed wrapper) — profile-tab field rows sit directly inside `ProfileWrap`.
- **Removed per-row divider** — `ProfileFieldRow` dropped the `border-bottom: 1px solid border` and now uses `0.5rem 1rem` padding (matches `SettingsView::SettingRow`).
- **`ProfileShellBody`** now mirrors `SettingsShellBody`: `padding: 0.35rem 0 0.75rem`, `border: none`, `border-radius: 0`.
- **`LoadingRow` + `ProfilePostsTabGutter`** horizontal insets switched from `OLDREDDIT_SHELL_INSET_X` to `1rem` (consistent with Settings rows).

### Stage 4 — Settings-parity polish

- **Divider below header** — `<SectionDivider />` (1px `border`) inserted between `HeaderRow` and `TabsRow` (mirrors `SettingsView`).
- **Tab underline alignment** — `TabsRow` switched from `padding: 0 1rem` to `margin: 0 1rem`. The border-bottom now starts at the same x-coordinate as the first tab's active blue `::after` indicator (matches `CreatePostView`).
- **Breathing room between tabs and content** — new `TabContent` wrapper with `padding-top: 0.4rem` so the first row isn't touching the tabs divider.
- **Label styling** — `Label` + `HoverableLabel` rewired from `subtleText / labelWeight(700) / labelSize(0.7rem)` to `text / 500 / 0.72rem` with `padding-top: 0.15rem` + `flex-shrink: 0`. Matches `SettingsView::SettingLabel` exactly.
- **Row density** — `ProfileFieldRow` padding `0.5rem 1rem` → `0.55rem 1rem` (matches `SettingRow`); mobile override `0.5rem 0.85rem`.
- **Algo tab rebuilt** — dropped `ValueBox` + inline divs. New primitives:
  - `SectionHeader` — uppercase `0.6rem / 700 / subtleText`, `0.06em` letter-spacing, `0.85rem 1rem 0.35rem` padding. No inline rule (the old `SectionTitle::after flex: 1 height: 1px` line is gone).
  - `AlgoList` — flex column wrapper.
  - `AlgoRow` — link row, `0.45rem 1rem`, `0.72rem / 500 / text`, `hoverBg` on hover.
  - `AlgoValue` — right-side value, `0.72rem / 500`, accepts `$color` prop for success/danger tint.
  - `AlgoEmpty` — loading / empty / error copy, `0.72rem / 500`, supports `$danger` for `voteDown` color.
  - `AlgoExpandRow` — "show N more…" / "show less" buttons, `0.65rem / 500 / subtleText → text` on hover.
- **Removed unused styled components** — `ValueBox`, `SectionTitle` (old, with inline rule), `AlgoRowStatic` (orphan from intermediate edit).

### Stage 5 — Reddit-style two-column layout

- **New `ProfileGrid`** — desktop `grid-template-columns: minmax(0, 1fr) 320px` with `1.25rem` gap, capped at `1200px`. Mobile (<1000px) stacks to single column with `order: -1` on the aside so the identity card appears above the tabs.
- **`ProfileMainColumn`** — hosts the existing header + tabs + tab content (all existing Profile / Posts / Algo tab markup is unchanged).
- **`ProfileIdentity`** replaces the old `HeaderRow>HeaderTitle "Profile"`:
  - Left-aligned 64px `Avatar` (circle, `getTierColor(userLevel)` fill, first-letter of username in `buttonText`).
  - `IdentityBlock` with `DisplayName` (1.35rem / 700) + `Handle` (`u/username`, 0.82rem / 500 / subtleText).
- **New `ProfileAside`** (right column) with two `AsideCard`s:
  - **Identity card** — 96px `Banner` (gradient `followBtnBg → focusBlue`) + overlapping avatar (60px, ringed with `panel` background for the cut-out look), name, handle, optional `biography`, `AsideActions` row (Share button + Follow/Gift-Sub for non-own profile), `AsideStatsGrid` 2x2 (Tier / Balance / Registered / Reserve).
  - **Settings card** (own profile only) — `AsideSectionHeader` "SETTINGS" + three `AsideSettingRow` links to `/change_username`, `/settings`, `/subscription` with `HiChevronRight` affordance.
- **Share button** (`AsideShareBtn`) — transparent pill with border, copies `window.location.href` to clipboard on click (no state change — browser handles feedback via tooltip).
- **Removed primitives** — `ProfileWrap`, `HeaderRow`, `HeaderTitle` (no longer referenced).
- **Icons** — `HiChevronRight`, `HiShare`, `HiGift` added from `react-icons/hi2` (per R6).
- **Tokens used** — `focusBlue`, `followBtnBg`, `panel`, `border`, `borderStrong`, `hoverBg`, `buttonText`, `text`, `subtleText`. No raw hex/rgba.
- **All data flows through existing `useProfile` hook** — `getTierColor`, `getTierName`, `userLevel`, `usernameDisplay`, `profileUsername`, `profileAddress`, `shortenAddress`, `biography`, `balanceDisplay`, `registeredDisplay`, `reserveDisplay`, `isOwnProfile`, `isFollowingProfile`, `followHover`, `handleFollowToggle`, `hasValidAccount`, `handleGiftSub`, `subFeePending`, `subFeeStatus`.

### Stage 6 — Tier / avatar / seed alignment with mirage-mobile-app

Referenced branch: `mirage-mobile-app @ mesonalirajput/performance-optimizations`.

- **Free tier uses default body color** — `getTierColor(0)` returns a hardcoded `#6B7280` gray. The profile's `Tier:` row `Mono` and the right-aside `AsideStatValue` now branch on `userLevel > 0` — non-free tiers keep `getTierColor(userLevel)`, Free drops the override so the value falls through to `theme.colors.cardBodyText` / `theme.colors.text` (same color as Balance / Address / Username). Subscriber / Agent / Admin unaffected.
- **DiceBear seed parity with mobile** — `web/frontend/src/utils/avatar.js` rewritten. Dropped `normalizeAvatarSeed` (the earlier lowercasing caused seed drift vs mobile). Now passes the raw seed through `encodeURIComponent`, matching `mirage-mobile-app/src/components/atoms/avatar.tsx` (`seed ?? "default"` verbatim).
- **Seed order aligned with mobile (address-first)** — mobile's `profile-screen.tsx` uses `user?.walletAddress || username`. Updated to match:
  - `TopBar.js` avatar → `publicKey || username || 'default'`.
  - `ProfileView.js` main + aside avatars → `profileAddress || profileUsername || routeIdentity`.
  - Same user → identical seed → identical identicon across web + mobile.
- **Avatar background — hard-pinned `#232830` in both modes** — DiceBear's identicon variant returns a transparent PNG, so the styled bg shows through the pattern's negative space. We pin to the dark-mode `surface3` color in both light and dark so the avatar chip looks identical everywhere:
  - `ProfileView.js::Avatar` — main 64px header + aside 60px identity-card avatars.
  - `TopBar.js::AvatarImg` — top-right 32px (mobile 28px) header avatar.
  - Earlier experiments with `panelAlt` and `actionIconBg` were too close to the page bg in light mode and made the circle disappear.
- **Avatar's `$color` prop dropped** — the styled component no longer accepts a tier-based `$color`. Background is always `#232830`.
- **Banner uses the app's brand gradient** — `Banner` (right-aside identity card) rewritten from a blue-on-blue ramp to `linear-gradient(135deg, gradientStart → gradientEnd)` — the canonical indigo→purple Mirage gradient used by quests, new-posts, feed-type. Height `96px`, no fade-to-panel. Reads identically in light + dark.

### Stage 7 — Action-button layout + bio pill

- **Follow button moved to profile header right side** — `ProfileIdentity` now `justify-content: space-between` with a new `ProfileIdentityMain` (left: avatar + name) and `ProfileIdentityActions` (right: Follow button on other users' profiles). Removed the duplicate Follow button from the Username row.
- **Gift Sub moved to aside actions row** — removed from the Tier row in the main profile. Sits next to Share in the right-aside identity card via a new `AsideGiftSubBtn` — a 32px token-for-token clone of `AsideShareBtn` (filled `actionIconBg`, 0.62rem/500, `HiGift` icon prefix, identical hover). Share + Gift Sub are visually flush.
- **New `CompactFollowBtn`** (32px, `0.7rem / 600`) — used in both the profile header and the aside actions row. Matches `AsideShareBtn` / `AsideGiftSubBtn` height. Three states via `$active` / `$danger` props:
  - Idle → solid `followBtnBg` pill with white text.
  - Following → transparent pill with `border` outline and `text` color.
  - Hover-to-unfollow / pending unfollow → transparent pill with `voteDown` outline + text.
- **`GiftMirageBtn`** — inline pill on the Balance row. Solid `followBtnBg` pill (32px, 0.7rem/600, `HiGift` icon prefix), hugs the label (dropped the old `minWidth="follow"` full-width treatment). Replaces the generic `<Button size="sm">`.
- **Bio editor Save → PostBtn parity** — `BioPillButton` Save variant rewritten to match `CreatePostView::PostBtn` exactly (`followBtnBg` fill with matching border, `#ffffff` text, `followBtnBgHover` on hover, `0.55` disabled, `0.15s` transition). Ghost (Cancel) variant unchanged — transparent with neutral border. Removed the earlier light-mode-specific `bioSaveBg` branch.
- **Change / Copy / Edit → icon buttons** — `IconActionButton` (28×28 circle chip, `actionIconBg`) replaces the old text pills on Username / Address / Biography rows. Copy flips to `HiCheck` with green `buttonSuccessBg` + `voteUp` when copied.
- **"Show more / Show less" in Algo tab** — `AlgoExpandRow` now wraps an `AlgoExpandPill` (outlined full-radius pill, `0.65rem / 600 / subtleText → text` on hover).

### Stage 8 — Comments tab fix + compact-feed placeholder

- **Comments tab no longer renders blank** (`web/frontend/src/logic/useProfile.js`):
  - Root cause: shared `FeedRow` renderer drops any row where `title.trim() === ''` or `topic.trim() === ''`. Comments carry neither (parent post owns the title; backend explicitly forbids `topic` on comments).
  - Fix: when `effectivePostsFilter === 'comments'`, each incoming row is mapped to synthesize both fields — `title` from the body's first line (max 80 chars, truncated with `…`, fallback `"(reply)"`), `topic` set to `comment-<short-parent-id>`. Submissions / main feed untouched.
- **Compact-feed placeholder letter + color** (`web/frontend/src/themes/default/ListFeedView.js::CompactRow`):
  - Letter source: `topic` → `post.username` (fallback to author wallet address, then `#`). Posts with no media now show the author's initial on the gradient tile, not the topic initial.
  - Letter color: `theme.colors.sidebarItemActiveText` → hard-pinned `#ffffff`. `sidebarItemActiveText` flips to black in light mode, which was invisible against the brand gradient — now renders white in both modes.

### Stage 9 — Responsive polish

- **`ProfileFieldRow` — fixed label column, responsive gap**:
  - Label column: `minmax(140px, 260px)` → fixed `110px`. Every row's value starts at the same x coordinate; Username / Address / Tier / Balance / Registered / Reserve / Biography values line up like a table.
  - Value column: `minmax(0, 1fr)` so long Mono strings shrink/ellipsize without clipping.
  - Gap: `1.5rem` default (comfortable breathing room on wide desktop). Collapses to `0.5rem` at `<1100px` (the width where Mono values start clipping) and stays `0.5rem` with tightened padding on mobile.
  - Rows stay single-line in both desktop and mobile (removed the old mobile `grid-template-columns: 1fr` stack).
- **`ProfileIdentity` hidden on `<1000px`** — the right-aside identity card reorders above the main column on narrow screens and already shows avatar + name + follow, so repeating it in the main column was redundant. Added `@media (max-width: 1000px) { display: none; }` to the header block.
- **Label / value inline alignment** — `ProfileFieldRow` → `align-items: center`; `ProfileFieldValue` → `align-items: center`; `Label` / `HoverableLabel` dropped `padding-top: 0.15rem` and added explicit `line-height: 1.3`. Label baseline now lines up with value content (even when the value is a 32px icon/pill) instead of floating above.
- **Stats-grid spacing** — right-aside `AsideStatsGrid` `row-gap` bumped `0.4rem → 0.75rem` so Tier/Balance and Joined/Reserve rows aren't crowded.
- **Compact sizing in right-aside card** — name 0.82rem, handle 0.62rem, bio 0.68rem, banner 96px (with avatar overlapping via `-28px` margin), stat values 0.72rem, stat labels 0.58rem. Share pill 0.65rem / 0.75rem icon / tight padding.
- **Balance / Reserve in compact `K` format** — `compactMirageLabel(raw)` helper used for both main profile rows (Balance / Reserve) and right-aside stat cards. Goes through `formatMirageCompact` then uppercases the trailing magnitude letter (`k → K`, `m → M`, `b → B`) so it matches the `MIRAGE` uppercase label. Full precision still available via `title` tooltip.
- **Joined stat — time-ago** — right-aside Registered value renders `formatAccountAge(profileRegisteredAt)` (ported from mobile's `min`/`hr`/`d`/`mo`/`yr` format) instead of the raw timestamp. Label renamed `Registered` → `Joined`. Full timestamp on hover.
- **Bio counter shrunk** — inline `0.7rem` → `0.6rem / 500`.

### Intentionally left as-is

- `getTierColor(userLevel)` — tier colors live in `utils/tierColor.js` and are a shared visual language, not a default-specific token.
- Route-level structural primitives (`ContentGrid` / `ModernPostFeed` / `CappedPageColumn` / `TabbedContainer` / `ContainerBody`) — already R1-compliant, no changes needed.

---

## R4 references consulted

- `themes/bluemoon/routes/ProfileView.js` — data-field parity baseline. No fields added/removed; every bluemoon field is still rendered.
- `themes/default/routes/InboxView.js` — canonical `HeaderRow` / `HeaderTitle` pattern (`1.1rem / 700 / -0.01em`); used to calibrate font weights.
- `themes/default/Layout.js` — confirmed `ContainerBody` already sits on `bg` per R1 (no fix needed there).
- `../mirage-mobile-app/src/components/molecules/profile-header.tsx`, `profile-tabs.tsx`, `profile-about-tab.tsx` — mobile visual reference. No structural port attempted in this pass (see note below).

### What was intentionally not done

The original 06.1 doc called for a structural rewrite with two new components (`ProfileHeader.js`, `ProfileTabs.js`) modeled on mobile. That was **dropped by design decision** after two prior sessions where large structural changes caused visible regressions. If a dedicated header/tabs redesign is wanted in the future, it should land as a separate plan with a concrete mockup as the target.

---

## Verification

- [x] No raw hex / rgb / rgba literals remain in `ProfileView.js` except the two intentional `#232830` avatar bgs + `#ffffff` button texts (see `Avatar` / `BioPillButton` / `GiftMirageBtn`).
- [x] No `focusBlue` / `focusRing` box-shadow on BioTextarea or FilterSelect (R5).
- [x] No `font-weight: 700` on SectionTitle / input inline styles (R7).
- [x] No `0.55rem` byline, no `0.82rem` inline text (R7 off-scale).
- [x] `ProfileMainColumn` and profile tab strip both paint `theme.colors.bg` (R1).
- [x] Avatar (`ProfileView.js::Avatar` + `TopBar.js::AvatarImg`) renders identically in light and dark modes.
- [x] Same user → identical identicon between web `TopBar` + web `ProfileView` + mobile app (seed normalized to raw address-first, no casing drift).
- [x] Comments tab renders rows for users with replies (title + topic synthesized from body + parent post id).
- [x] Compact-feed placeholder letter = author initial (not topic initial), always white on gradient.
- [x] `ProfileFieldRow` values all start at the same x coordinate (fixed `110px` label column).
- [x] Profile rows stay single-line on mobile (no stacked label above value).
- [x] `ProfileIdentity` hidden when right-aside identity card reorders above main column (<1000px).
- [x] Balance / Reserve values show uppercase `K` / `M` / `B` suffix with `MIRAGE` label (e.g. `12.2K MIRAGE`).
- [x] Build passes:

```bash
cd web/frontend
CI=true npm run build
```

---

## PR description template

> default `ProfileView`: RULES.md compliance pass + Reddit-style two-column layout + interaction polish + mobile-app parity.
>
> **R1 / R2 / R5 / R7 (Stages 1–4)**
> - R1: profile tab strip + main column now paint `bg` instead of `panel`. `PostItem:hover` tile uses `hoverBg`.
> - R2: all inline hex/rgba swapped for tokens (`subtleText`, `voteDown`, `voteUp`, `buttonSuccess*`, `buttonDanger*`, `inboxHighlightRail`, `inboxHighlightBg`).
> - R5: `BioTextarea` + `FilterSelect` sit on `bg`, no focus-ring box-shadow, explicit `:hover`/`:focus` `borderStrong`.
> - R7: `SectionTitle` 700 → 600, `PostMeta` 0.55rem → 0.62rem/500, `ProfileSortTab` 0.75rem with 600 active / 500 inactive, inline `0.82rem` → `0.8rem`, donate amount input forced to `0.75rem / 500`.
> - Tabs restyled to match `CreatePostView::TabsRow` (transparent row + `focusBlue` underline indicator).
> - Algo tab rebuilt to `SettingsView` pattern (no inline rules, `0.72rem / 500` rows).
>
> **Reddit-style layout (Stage 5)**
> - New `ProfileGrid` — left column hosts header + tabs + tab content, right `ProfileAside` holds identity card (banner + avatar + stats grid) and settings card.
>
> **Mobile-app parity (Stage 6)**
> - Free tier value renders in default body color (not `#6B7280` gray).
> - `utils/avatar.js` rewritten to match `mirage-mobile-app/src/components/atoms/avatar.tsx` — raw seed, address-first order.
> - Avatar bg hard-pinned to `#232830` in both modes across `ProfileView.js::Avatar` + `TopBar.js::AvatarImg`.
> - Banner uses the app's main brand gradient (`gradientStart → gradientEnd`).
>
> **Action buttons (Stage 7)**
> - Follow moved to header right + aside (new `CompactFollowBtn` 32px).
> - Gift Sub moved next to Share as 32px ActionPill (new `AsideGiftSubBtn`).
> - Gift Mirage restyled as compact icon pill (new `GiftMirageBtn`).
> - Bio editor Save button matches `CreatePostView::PostBtn` exactly.
> - Username / Address / Biography Change/Copy/Edit converted to 28×28 icon chips (`IconActionButton`).
>
> **Comments + compact feed (Stage 8)**
> - Comments tab no longer blank — `useProfile` synthesizes `title` + `topic` for comment rows so the shared `FeedRow` renders them.
> - `ListFeedView::CompactRow` placeholder letter = author initial (not topic initial); color hard-pinned `#ffffff`.
>
> **Responsive polish (Stage 9)**
> - Fixed `110px` label column aligns every row's value at the same x coordinate.
> - Gap collapses at `<1100px` (the clipping width), not at mobile.
> - `ProfileIdentity` hidden on `<1000px` (right-aside card takes over).
> - Rows stay single-line on mobile.
> - Balance / Reserve values render in compact `K` / `M` / `B` with uppercase suffix, in both main rows and aside stats.
>
> Data wiring, API calls, and all `useProfile` handlers unchanged. Closes sub-plan 06.1.
