# Sub-Plan 06.1 — Profile

**Route:** `/profile`, `/u/:identity`
**File:** `web/frontend/src/themes/mirageapp/routes/ProfileView.js`
**Status:** ✅ Done — RULES.md compliance pass (R1 / R2 / R5 / R7)
**Parent:** [`../06-remaining-routes-and-polish.md`](../06-remaining-routes-and-polish.md)

---

## What shipped

Five-stage pass on `themes/mirageapp/routes/ProfileView.js`:
1. **Stage 1** — R2 tokenization (hex/rgba → tokens).
2. **Stage 2** — R1 / R5 / R7 compliance.
3. **Stage 3** — Header + tabs re-styled to match `SettingsView` + `CreatePostView`; per-row divider removed.
4. **Stage 4** — Settings-parity polish: header divider, tab underline alignment, algo tab rebuilt with Settings-style section headers and rows.
5. **Stage 5** — Reddit-style two-column layout: left column with avatar + display name + `u/handle` header above tabs, right sidebar with banner + identity card + stats grid + settings links.

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

### Intentionally left as-is

- `getTierColor(userLevel)` — tier colors live in `utils/tierColor.js` and are a shared visual language, not a mirageapp-specific token.
- Route-level structural primitives (`ContentGrid` / `ModernPostFeed` / `CappedPageColumn` / `TabbedContainer` / `ContainerBody`) — already R1-compliant, no changes needed.

---

## R4 references consulted

- `themes/bluemoon/routes/ProfileView.js` — data-field parity baseline. No fields added/removed; every bluemoon field is still rendered.
- `themes/mirageapp/routes/InboxView.js` — canonical `HeaderRow` / `HeaderTitle` pattern (`1.1rem / 700 / -0.01em`); used to calibrate font weights.
- `themes/mirageapp/Layout.js` — confirmed `ContainerBody` already sits on `bg` per R1 (no fix needed there).
- `../mirage-mobile-app/src/components/molecules/profile-header.tsx`, `profile-tabs.tsx`, `profile-about-tab.tsx` — mobile visual reference. No structural port attempted in this pass (see note below).

### What was intentionally not done

The original 06.1 doc called for a structural rewrite with two new components (`ProfileHeader.js`, `ProfileTabs.js`) modeled on mobile. That was **dropped by design decision** after two prior sessions where large structural changes caused visible regressions. If a dedicated header/tabs redesign is wanted in the future, it should land as a separate plan with a concrete mockup as the target.

---

## Verification

- [x] No raw hex / rgb / rgba literals remain in `ProfileView.js` (`grep -nE "'#[0-9a-fA-F]{3,8}'|rgba\("` → 0 matches).
- [x] No `focusBlue` / `focusRing` box-shadow on BioTextarea or FilterSelect (R5).
- [x] No `font-weight: 700` on SectionTitle / input inline styles (R7).
- [x] No `0.55rem` byline, no `0.82rem` inline text (R7 off-scale).
- [x] `ProfileInfoShell` and profile tab strip both paint `theme.colors.bg` (R1).
- [x] Build passes:

```bash
cd web/frontend
CI=true npm run build
```

---

## PR description template

> mirageapp `ProfileView`: RULES.md compliance pass (R1 / R2 / R5 / R7).
>
> - R1: profile tab strip + `ProfileInfoShell` now paint `bg` instead of `panel` (`ProfileTabsStrip` wraps `OldRedditTabsStrip` to override its fill). `PostItem:hover` tile uses `hoverBg`.
> - R2: all inline hex/rgba swapped for tokens (`subtleText`, `voteDown`, `voteUp`, `buttonSuccess*`, `buttonDanger*`, `inboxHighlightRail`, `inboxHighlightBg`).
> - R5: `BioTextarea` + `FilterSelect` sit on `bg`, no focus-ring box-shadow, explicit `:hover`/`:focus` `borderStrong`.
> - R7: `SectionTitle` 700 → 600, `PostMeta` 0.55rem → 0.62rem/500, `ProfileSortTab` 0.75rem with 600 active / 500 inactive, inline `0.82rem` → `0.8rem`, donate amount input forced to `0.75rem / 500`.
>
> Structural layout, data wiring, and behavior unchanged. Full header/tabs rewrite intentionally dropped. Closes sub-plan 06.1.
