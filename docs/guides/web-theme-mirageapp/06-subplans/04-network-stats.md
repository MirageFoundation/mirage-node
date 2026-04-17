# Sub-Plan 06.4 — Network + Stats

**Routes:** `/network`, `/stats`
**Files:** `themes/mirageapp/routes/{NetworkView,StatsView}.js`
**Status:** ⏳ Not started
**Parent:** [`../06-remaining-routes-and-polish.md`](../06-remaining-routes-and-polish.md)

---

## Current state

Both routes are near-identical copies of `themes/oldreddit/routes/*` (2–3 line diffs). Oldreddit tokens everywhere.

---

## Goal

Rewrite as panel-based info pages that match the mobile "info" screens.

---

## References

- **Mobile:** `mirage-mobile-app/src/pages/stats-screen.tsx`, `network-screen.tsx` (or closest)
- **Web data:** `themes/bluemoon/routes/{NetworkView,StatsView}.js`

---

## Requirements

### Shared
- Page heading `1.1rem/700` per R7.
- Panels use `panel` + `border`, radius `8–10px`.
- Data row: label left (`0.7rem/500 subtleText`), value right (`0.8rem/600 text`).
- Charts (Stats) keep their existing library — only restyle the container and the legend colors (use R2 tokens).
- Status indicators use `voteUp` / `voteDown` / neutral tokens.

### NetworkView
- Stacked info panels: node info, peers, block height, sync status.
- Status pill uses `voteUpBg` / `voteDownBg` / neutral `accent`.

### StatsView
- Panel groups for user stats, network stats, and charts.
- Chart axis/grid colors pull from `border` / `subtleText`.

---

## Out of scope

- Chart logic changes.
- Data hook changes.

---

## Verification checklist

- [ ] Panels use R2 tokens only.
- [ ] Chart containers match panel styling.
- [ ] Data parity with bluemoon.
- [ ] Dark + light verified (chart lines remain legible in both).
- [ ] Build passes.

---

## PR description template

> Rewrites `mirageapp`'s Network + Stats routes with R1–R7 tokens and info-panel pattern. Chart logic untouched; only containers/colors restyled. Closes sub-plan 06.4.
