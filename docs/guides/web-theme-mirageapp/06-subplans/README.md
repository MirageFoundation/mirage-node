# Plan 06 — Sub-Plans Index

Plan 06 is too broad to ship in one PR. This folder splits it into focused one-PR sub-plans so they can land incrementally without blocking each other.

**Parent plan:** [`../06-remaining-routes-and-polish.md`](../06-remaining-routes-and-polish.md)

---

## Order & status

| # | Sub-plan | Scope | Status | Doc |
|---|---|---|---|---|
| 1 | Profile | `ProfileView.js` + header/tabs (was Plan 04 leftover) | ⏳ Not started | [`01-profile.md`](./01-profile.md) |
| 2 | Component restyle pass | Button, Toast, Tooltip, InlineMedia, MediaGallery, UnlockPrompt, MarkdownRenderer, QuestHeroCard + finish passes on FilterBar / MarkdownEditor / MediaAttachmentLayout | ⏳ Not started | [`02-component-restyle.md`](./02-component-restyle.md) |
| 3 | Social routes | Follows, Blocks, Reports (list-row pattern) | ⏳ Not started | [`03-social-routes.md`](./03-social-routes.md) |
| 4 | Network + Stats | Node info + chart containers (info-panel pattern) | ⏳ Not started | [`04-network-stats.md`](./04-network-stats.md) |
| 5 | Subscription + Referrals | Plan/tier summary + invite share block | ⏳ Not started | [`05-subscription-referrals.md`](./05-subscription-referrals.md) |
| 6 | Bridge | Restyle containers only; keep logic | ⏳ Not started | [`06-bridge.md`](./06-bridge.md) |
| 7 | Agents + Discover + NotFound | List + empty-state styling | ⏳ Not started | [`07-agents-discover-notfound.md`](./07-agents-discover-notfound.md) |
| 8 | MobileBottomNav | Full restyle (deferred from Plan 02) | ⏳ Not started | [`08-mobile-bottom-nav.md`](./08-mobile-bottom-nav.md) |
| 9 | Polish + QA | Spacing / typography / state / responsive / a11y + QA + optional default-theme switch | ⏳ Not started | [`09-polish-and-qa.md`](./09-polish-and-qa.md) |

Each sub-plan is one PR. Recommended order is **2 → 1 → 3 → 4 → 5 → 7 → 6 → 8 → 9** because:

- Sub-plan 2 (component restyle) unblocks every other sub-plan — Button/Toast/Tooltip leak into every route, so fixing them first avoids double-work.
- Profile (1) is highest user-visible impact after components.
- Bridge (6) has the most complex existing logic; it goes late so we aren't churning on restyle + logic at once.
- Polish + QA (9) closes the plan.

---

## Shared rules (apply to every sub-plan)

> 📐 Read [`../RULES.md`](../RULES.md) before starting. R1–R7 are mandatory.

- Live inside the Plan 02 desktop shell (TopBar + Sidebar + content column).
- Reuse theme-local primitives: `Button`, `MarkdownEditor`, `MarkdownRenderer`, panel containers, `AuthPageShell` where relevant — **after sub-plan 2** these must be the restyled mirageapp versions.
- Never import from `themes/oldreddit/*` or `themes/bluemoon/*` inside `mirageapp`.
- **Visual only** — do not modify data hooks or seed-vault/unlock behavior.
- **Data parity:** every field bluemoon shows must also appear in mirageapp (R4).
- **Visuals:** align spacing, typography, and tokens with `mirage-mobile-app` (R4).
- Dark + light modes must both be verified.
- Each PR must pass:

```bash
cd web/frontend
CI=true npm run build
```

---

## When done

When all nine sub-plans ship, update:

- `../06-remaining-routes-and-polish.md` → status = ✅ Done
- `../README.md` → Plan 06 row = ✅ Done
- `../04-post-detail-and-profile.md` → status = ✅ Done (profile portion closed by sub-plan 1)
- Announce in `docs/whats-new.md`.
- Optionally flip `THEME_MANIFESTS[0]` to `mirageappManifest` in a separate PR.
