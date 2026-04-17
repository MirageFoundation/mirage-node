# Sub-Plan 06.7 — Agents, Discover, NotFound

**Routes:** `/agents`, `/discover` (topics), fallback 404
**Files:** `themes/mirageapp/routes/{AgentsView,DiscoverView,NotFoundView}.js`
**Status:** ⏳ Not started
**Parent:** [`../06-remaining-routes-and-polish.md`](../06-remaining-routes-and-polish.md)

---

## Current state

All three are near-identical (2–3 line diffs) copies of `themes/oldreddit/routes/*`. Oldreddit tokens everywhere.

---

## Goal

Finish the low-volume routes so every route key in the manifest uses mirageapp tokens.

---

## References

- **Mobile:** `mirage-mobile-app/src/pages/topics-screen.tsx`, `agents-screen.tsx`
- **Web data:** `themes/bluemoon/routes/{AgentsView,DiscoverView,NotFoundView}.js`

---

## Requirements

### AgentsView
- Grid / list of agents with avatar + name + short description + follow/subscribe action.
- Reuse the sub-plan 03 list-row pattern for list mode.

### DiscoverView
- Topic cards: 2-col grid on desktop, 1-col on mobile, using `cardAlt` tiles.
- Topic icon / color may come from existing topic utility — do not hard-code.
- Section heading per R7.

### NotFoundView
- Centered 404 layout on desktop; full-bleed on mobile.
- Heading `1.1rem/700`, body `0.9rem/500 subtleText`.
- Primary CTA (Go home) uses restyled `Button`.

---

## Out of scope

- Topic model changes.
- Agent list filtering beyond what bluemoon shows.

---

## Verification checklist

- [ ] All three routes render on `bg` canvas (R1).
- [ ] No `themes/oldreddit/*` imports.
- [ ] Data parity with bluemoon.
- [ ] Dark + light verified.
- [ ] Build passes.

---

## PR description template

> Rewrites `mirageapp`'s Agents / Discover / NotFound routes with R1–R7 tokens and mobile-app visuals. Visual only. Closes sub-plan 06.7.
