# Sub-Plan 06.5 — Subscription + Referrals

**Routes:** `/subscription`, `/referrals`
**Files:** `themes/mirageapp/routes/{SubscriptionView,ReferralsView}.js`
**Status:** 🟡 In progress — Subscription ✅ done; Referrals ⏳ pending.
**Parent:** [`../06-remaining-routes-and-polish.md`](../06-remaining-routes-and-polish.md)

---

## Current state

**Subscription** ✅ rewritten against mirageapp R1–R7 tokens: `SubscriptionPageShell` (ContentGrid → ModernPostFeed → CappedPageColumn → TabbedContainer → wrap), 1.1rem/700 page heading matching `SettingsView`, uppercase `SectionHeader` groups (Active plan / Available plans), `ActivePlanCard` on `cardAlt` with tier-colored name + `StatusBadge` (success/danger tokens) wired to `handleCancelAutoRenew` + Balance/Reserve tiles, stacked `TierCard`s on `cardAlt` with tier-colored border when active, `TierFeatureItem` dot list, `DetailsToggle` using `HiChevronDown` (R6), inline `TierDetailsPanel` with `borderSubtle` + left-border accent. Subscribe CTA now uses mirageapp `Button` `primary`/`ghost` variants (no raw linear-gradient). State blocks (loading / tier-config-failed) standardised. Zero raw hex/rgba in JSX — TIER_COLORS stays as shared tier visual language per sub-plan 06.1 / StatsView.

**Referrals** ⏳ still near-identical to `themes/oldreddit/routes/ReferralsView.js` (2-line diff). To be done as the second PR of 06.5.

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
