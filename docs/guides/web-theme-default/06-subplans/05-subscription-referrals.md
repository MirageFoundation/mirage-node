# Sub-Plan 06.5 — Subscription

**Routes:** `/subscription`
**Files:** `themes/default/routes/SubscriptionView.js`
**Status:** ✅ Done — Subscription ✅ shipped.
**Parent:** [`../06-remaining-routes-and-polish.md`](../06-remaining-routes-and-polish.md)

> **Trimmed in v1.39.0.** This sub-plan also covered `/referrals` (`ReferralsView.js`).
> Referrals and invite codes were removed from Mirage in v1.39.0: the route is gone,
> `ReferralsView.js` was deleted, and the referral APIs answer 410 Gone. Those
> sections have been removed rather than left describing a screen that no longer
> exists. The Subscription work below still shipped and is still accurate.

---

## Current state

**Subscription** ✅ rewritten against default R1–R7 tokens: `SubscriptionPageShell` (ContentGrid → ModernPostFeed → CappedPageColumn → TabbedContainer → wrap), 1.1rem/700 page heading matching `SettingsView`, uppercase `SectionHeader` groups (Active plan / Available plans), `ActivePlanCard` on `cardAlt` with tier-colored name + `StatusBadge` (success/danger tokens) wired to `handleCancelAutoRenew` + Balance/Reserve tiles, stacked `TierCard`s on `cardAlt` with tier-colored border when active, `TierFeatureItem` dot list, `DetailsToggle` using `HiChevronDown` (R6), inline `TierDetailsPanel` with `borderSubtle` + left-border accent. Subscribe CTA now uses default `Button` `primary`/`ghost` variants (no raw linear-gradient). State blocks (loading / tier-config-failed) standardised. Zero raw hex/rgba in JSX — TIER_COLORS stays as shared tier visual language per sub-plan 06.1 / StatsView.

---

## Goal

Align the route with the mobile tier screen.

---

## References

- **Mobile:** `mirage-mobile-app/src/pages/subscription-screen.tsx`
- **Web data:** `themes/bluemoon/routes/SubscriptionView.js`

---

## Requirements

### SubscriptionView
- Plan/tier summary panel at top: tier name, price, benefits list.
- Benefits grid using `cardAlt` tiles with icon + label + copy.
- Primary CTA (upgrade / billing) uses the restyled `Button` primary variant (depends on sub-plan 02).
- Tier color comes from the existing tier utility; do not hard-code.

---

## Out of scope

- Billing / payment logic.
- Tier model changes.

---

## Verification checklist

- [x] Data parity with bluemoon.
- [x] Dark + light verified.
- [x] Build passes.

---

## PR description template

> Rewrites `default`'s Subscription route with R1–R7 tokens and mobile-app tile/list patterns. Visual only. Closes sub-plan 06.5.
