# Sub-Plan 06.6 — Bridge

**Route:** `/bridge`
**File:** `themes/mirageapp/routes/BridgeView.js`
**Status:** ⏭️ Skipped — `/bridge` has no nav entry point in the `mirageapp` UI (no sidebar / top-bar / footer link). Restyle deferred until the route is surfaced or the page is repurposed. Revisit in sub-plan 06.9 polish if needed.
**Parent:** [`../06-remaining-routes-and-polish.md`](../06-remaining-routes-and-polish.md)

---

## Current state

Near-identical (2-line diff) to `themes/oldreddit/routes/BridgeView.js`. The file is ~1.9k lines; logic is dense and correct as-is. Only the visual shell is wrong.

---

## Goal

Restyle containers, inputs, buttons, and status tiles — **keep the swap / bridge logic unchanged**.

---

## References

- **Mobile:** `mirage-mobile-app/src/pages/bridge-screen.tsx` (or closest)
- **Web data:** `themes/bluemoon/routes/BridgeView.js`

---

## Requirements

- Page heading per R7.
- Step panels use `panel` + `border`.
- Inputs follow R5 (neutral focus).
- Chain selector pills use `followBtnBg` accent for selected state.
- Status tile uses `voteUp*` / `voteDown*` / neutral per state.
- No raw `#667eea` — use `gradient` token if gradients are needed.

### Out of scope
- Swap math.
- Signer / tx logic.
- Error-handling behavior.

---

## Verification checklist

- [ ] Happy-path bridge flow still works end-to-end.
- [ ] All colors from R2 tokens.
- [ ] Data parity with bluemoon.
- [ ] Dark + light verified.
- [ ] Build passes.

---

## PR description template

> Restyles `mirageapp`'s BridgeView containers/inputs/buttons using R1–R7 tokens. Swap/signer logic unchanged. Closes sub-plan 06.6.
