# Sub-Plan 06.5 — Subscription + Referrals

**Routes:** `/subscription`, `/referrals`
**Files:** `themes/default/routes/{SubscriptionView,ReferralsView}.js`
**Status:** ✅ Done — Subscription ✅ and Referrals ✅ both shipped.
**Parent:** [`../06-remaining-routes-and-polish.md`](../06-remaining-routes-and-polish.md)

---

## Current state

**Subscription** ✅ rewritten against default R1–R7 tokens: `SubscriptionPageShell` (ContentGrid → ModernPostFeed → CappedPageColumn → TabbedContainer → wrap), 1.1rem/700 page heading matching `SettingsView`, uppercase `SectionHeader` groups (Active plan / Available plans), `ActivePlanCard` on `cardAlt` with tier-colored name + `StatusBadge` (success/danger tokens) wired to `handleCancelAutoRenew` + Balance/Reserve tiles, stacked `TierCard`s on `cardAlt` with tier-colored border when active, `TierFeatureItem` dot list, `DetailsToggle` using `HiChevronDown` (R6), inline `TierDetailsPanel` with `borderSubtle` + left-border accent. Subscribe CTA now uses default `Button` `primary`/`ghost` variants (no raw linear-gradient). State blocks (loading / tier-config-failed) standardised. Zero raw hex/rgba in JSX — TIER_COLORS stays as shared tier visual language per sub-plan 06.1 / StatsView.

**Referrals** ✅ polished section-list rewrite against R1–R7 tokens: `ReferralsPageShell` mirroring `SubscriptionPageShell`, 1.1rem/700 page heading with optional monospace address aside. Hero share card with brand-colored left border (`gradientStart`), eyebrow label, title + subtitle text stack, and integrated share-link pill with icon-only `CopyIconButton` (green success state on copy). Segmented week pill (`Prev | week | Next`) with custom `WeekMenuButton` + `WeekMenuPopover` dropdown (themed `menuBg`, `menuSelectedBg`, `menuItemHoverText`, `scrollbar`, 12px radius, 32px shadow — matching SearchDropdown row feel); option text format `${value} (${range})` identical to bluemoon. Stats row: three tiles with icon chips (`HiUserGroup`/`HiBolt`/`HiClock`), tinted borders for brand/success, large 1.5rem monospace values, and an active-rate gradient progress bar inside the "Active this week" tile. Weekly-activity chart in `ChartCard` with smooth Catmull-Rom curve, gradient area fill (`link` → transparent), dashed grid lines, data-point circles, and narrowed 440px viewBox. Referral list: 40px avatar with `voteUp` ring + corner active-dot for active users, rank chip (trophy icons for top 3), normal-weight username text (400), tabular monospace meta, reduced `StatusBadge` size. Empty/loading/error/not-signed-in via shared `StateBlock` pattern. Build clean; zero raw hex/rgba; `OldRedditContentBleed` removed.

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

- [x] Data parity with bluemoon.
- [x] Copy button works (icon-only button, green success state).
- [x] Dark + light verified.
- [x] Build passes.

---

## PR description template

> Rewrites `default`'s Subscription + Referrals routes with R1–R7 tokens and mobile-app tile/list patterns. Visual only. Closes sub-plan 06.5.
