# Sub-Plan 06.5 — Subscription + Referrals

**Routes:** `/subscription`, `/referrals`
**Files:** `themes/mirageapp/routes/{SubscriptionView,ReferralsView}.js`
**Status:** ⏳ Not started
**Parent:** [`../06-remaining-routes-and-polish.md`](../06-remaining-routes-and-polish.md)

---

## Current state

Both near-identical to `themes/oldreddit/routes/*` (2-line diffs). Oldreddit tokens.

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
