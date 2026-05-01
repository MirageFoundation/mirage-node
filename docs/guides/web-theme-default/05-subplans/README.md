# Plan 05 — Sub-Plans Index

Plan 05 is too broad to ship in one PR. This folder splits it into focused, one-PR sub-plans so we can land them one at a time.

**Parent plan:** [`../05-inbox-search-settings-auth.md`](../05-inbox-search-settings-auth.md)

---

## Order & status

| # | Sub-plan | Route(s) | Status | Doc |
|---|---|---|---|---|
| 0 | Auth flows | `/login`, `/signup`, `/welcome` | ✅ Done (`ceef3d7`) | _see parent plan_ |
| 1 | Inbox | `/inbox` | ✅ Done | [`01-inbox.md`](./01-inbox.md) |
| 2 | Search | `/search` + TopBar dropdown | ✅ Done | [`02-search.md`](./02-search.md) |
| 3 | Post Details | `/p/:postId` | ✅ Done | [`03-post-details.md`](./03-post-details.md) |
| 4 | Settings | `/settings` | ✅ Done | [`04-settings.md`](./04-settings.md) |
| 5 | Create Post | `/create_post` | ✅ Done | [`05-create-post.md`](./05-create-post.md) |
| 6 | Change Username | `/change_username` | ✅ Done | [`06-change-username.md`](./06-change-username.md) |
| 7 | Sign Out | `/sign_out` | ✅ Done — closes Plan 05 | [`07-sign-out.md`](./07-sign-out.md) |

Each sub-plan is one PR. Order is **recommended**, not strictly required — any can be reordered if priorities shift. Post Details was pulled forward after Search because the search results + home feed both navigate into `/p/:postId`, so polishing it unlocks a consistent end-to-end feed experience.

---

## Shared rules (apply to every sub-plan)

> **📐 Read [`../RULES.md`](../RULES.md) before starting any sub-plan.** R1 (single `bg`), R2 (dark↔light color pairs), R3 (divider = `theme.colors.border`), and R4 (bluemoon + mobile reference check) are mandatory.

- Live inside the Plan 02 desktop shell (TopBar + Sidebar + content column).
- Reuse theme-local primitives: `Button`, `MarkdownEditor`, `MarkdownRenderer`, panel containers, `AuthPageShell` where relevant.
- Never import from `themes/oldreddit/*` or `themes/bluemoon/*` inside `default`.
- **Visual only** — do not modify data hooks (`useInbox`, `useSearchResults`, `useSettings`, `useCreatePost`, `useChangeUsername`, etc.) or seed-vault/unlock behavior.
- **Data parity:** every field bluemoon shows for the route must also show in default (R4).
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
