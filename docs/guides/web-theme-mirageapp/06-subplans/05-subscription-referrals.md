# Sub-Plan 06.5 — Subscription + Referrals

**Routes:** `/subscription`, `/referrals`
**Files:** `themes/mirageapp/routes/{SubscriptionView,ReferralsView}.js`
**Status:** ✅ Done — Subscription ✅ and Referrals ✅ both shipped.
**Parent:** [`../06-remaining-routes-and-polish.md`](../06-remaining-routes-and-polish.md)

---

## Current state

**Subscription** ✅ rewritten against mirageapp R1–R7 tokens: `SubscriptionPageShell` (ContentGrid → ModernPostFeed → CappedPageColumn → TabbedContainer → wrap), 1.1rem/700 page heading matching `SettingsView`, uppercase `SectionHeader` groups (Active plan / Available plans), `ActivePlanCard` on `cardAlt` with tier-colored name + `StatusBadge` (success/danger tokens) wired to `handleCancelAutoRenew` + Balance/Reserve tiles, stacked `TierCard`s on `cardAlt` with tier-colored border when active, `TierFeatureItem` dot list, `DetailsToggle` using `HiChevronDown` (R6), inline `TierDetailsPanel` with `borderSubtle` + left-border accent. Subscribe CTA now uses mirageapp `Button` `primary`/`ghost` variants (no raw linear-gradient). State blocks (loading / tier-config-failed) standardised. Zero raw hex/rgba in JSX — TIER_COLORS stays as shared tier visual language per sub-plan 06.1 / StatsView.

**Referrals** ✅ section-list rewrite against R1–R7 tokens: `ReferralsPageShell` (ContentGrid → ModernPostFeed → CappedPageColumn → TabbedContainer → wrap) mirroring `SubscriptionPageShell`, 1.1rem/700 page heading with optional monospace address aside (when viewing another user's referrals), uppercase `SectionHeader` groups (Your share link / Week / Overview / Weekly activity / Referrals). Share link box on `bg` with monospace `ShareUrl` input (borderless, select-on-click) + `Button` ghost variant that swaps between `HiClipboardDocument` / `HiCheck` on copy. Week controls: ghost pill `WeekNavButton`s with `HiChevronLeft` / `HiChevronRight`, native `select` restyled as a pill with `HiChevronDown` overlay (R5 neutral focus, R6 chevron), week-range + UTC-note meta row. Stats row: three tiles (Total referred / Active this week / Inactive) on `bg` with monospace 1.1rem/700 values. Weekly-activity chart re-wrapped in a `ChartCard`; all SVG colors routed through `useTheme()` (stroke → `link`, area → `buttonSuccessBg`, axes → `border` / `subtleText` — no hard-coded `#667eea` / `#444`). Referral list ported to the shared sub-plan 03 `Row` pattern: DiceBear avatar + `IdentityTitle` Link + monospace meta (`N actions · N posts · N comments`) + `StatusBadge` (success tokens for active, neutral `accent` for inactive), cmd/ctrl-click opens user route in new tab. Empty / loading / error / not-signed-in all rendered through the shared `StateBlock` pattern with `HiUsers` / `HiExclamationTriangle` icons. Pagination uses `Button` ghost `Load more`. Zero raw hex/rgba in JSX; `OldRedditContentBleed` + `layout.containerBg/Radius/Padding` removed from imports.

---

## Goal

Align both routes with the mobile tier / invite screens.

---

## References

- **Mobile:** `mirage-mobile-app/src/pages/invite-and-earn-screen.tsx`, `referrals-screen.tsx`, `subscription-screen.tsx`
- **Web data:** `themes/bluemoon/routes/{SubscriptionView,ReferralsView}.js`

---

## Requirements

### SubscriptionView
- Plan/tier summary panel at top: tier name, price, benefits list.
- Benefits grid using `cardAlt` tiles with icon + label + copy.
- Primary CTA (upgrade / billing) uses the restyled `Button` primary variant (depends on sub-plan 02).
- Tier color comes from the existing tier utility; do not hard-code.

### ReferralsView
- Share link block: monospace link + copy button (ghost variant).
- Stats block: three tiles for invites sent / accepted / earned.
- History list using the shared list-row pattern from sub-plan 03.

---

## Out of scope

- Billing / payment logic.
- Tier model changes.

---

## Verification checklist

- [ ] Data parity with bluemoon.
- [ ] Copy button actually copies (preserve behavior).
- [ ] Dark + light verified.
- [ ] Build passes.

---

## PR description template

> Rewrites `mirageapp`'s Subscription + Referrals routes with R1–R7 tokens and mobile-app tile/list patterns. Visual only. Closes sub-plan 06.5.
