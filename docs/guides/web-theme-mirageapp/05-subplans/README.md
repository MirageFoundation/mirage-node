# Plan 05 — Sub-Plans Index

Plan 05 is too broad to ship in one PR. This folder splits it into focused, one-PR sub-plans so we can land them one at a time.

**Parent plan:** [`../05-inbox-search-settings-auth.md`](../05-inbox-search-settings-auth.md)

---

## Order & status

| # | Sub-plan | Route(s) | Status | Doc |
|---|---|---|---|---|
| 0 | Auth flows | `/login`, `/signup`, `/welcome` | ✅ Done (`ceef3d7`) | _see parent plan_ |
| 1 | Inbox | `/inbox` | ✅ Done | [`01-inbox.md`](./01-inbox.md) |
| 2 | Search | `/search` | ⏳ Not started — **next** | [`02-search.md`](./02-search.md) |
| 3 | Settings | `/settings` | ⏳ Not started | [`03-settings.md`](./03-settings.md) |
| 4 | Create Post | `/create_post` | ⏳ Not started | [`04-create-post.md`](./04-create-post.md) |
| 5 | Change Username | `/change_username` | ⏳ Not started | [`05-change-username.md`](./05-change-username.md) |
| 6 | Sign Out | `/sign_out` | ⏳ Not started | [`06-sign-out.md`](./06-sign-out.md) |

Each sub-plan is one PR. Order is **recommended**, not strictly required — any can be reordered if priorities shift, but Inbox/Search/Settings bring the most daily-use value.

---

## Shared rules (apply to every sub-plan)

> **📐 Read [`../RULES.md`](../RULES.md) before starting any sub-plan.** R1 (single `bg`), R2 (dark↔light color pairs), R3 (divider = `theme.colors.border`), and R4 (bluemoon + mobile reference check) are mandatory.

- Live inside the Plan 02 desktop shell (TopBar + Sidebar + content column).
- Reuse theme-local primitives: `Button`, `MarkdownEditor`, `MarkdownRenderer`, panel containers, `AuthPageShell` where relevant.
- Never import from `themes/oldreddit/*` or `themes/bluemoon/*` inside `mirageapp`.
- **Visual only** — do not modify data hooks (`useInbox`, `useSearchResults`, `useSettings`, `useCreatePost`, `useChangeUsername`, etc.) or seed-vault/unlock behavior.
- **Data parity:** every field bluemoon shows for the route must also show in mirageapp (R4).
- **Visuals:** align spacing, typography, and tokens with `mirage-mobile-app` (R4).
- Dark + light modes must both work.
- Each PR must pass:

```bash
cd web/frontend
CI=true npm run build
```

---

## When done

When all six sub-plans ship, update:
- `../05-inbox-search-settings-auth.md` → status = ✅ Done
- `../README.md` → Plan 05 row = ✅ Done, next focus = Plan 04 or Plan 06
