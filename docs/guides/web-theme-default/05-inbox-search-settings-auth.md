# Plan 05 — Inbox, Search, Settings, Auth Flows

**Goal:** Rework the account-facing screens so `default` is usable day-to-day: inbox, search, settings, create post, and auth flows.

**Depends on:** Plans 01, 02, 03, 04.
**Unblocks:** Plan 06.

**Status:** ✅ Done — all sub-plans 05.1–05.7 shipped (Inbox, Search, Post Details, Settings, Create Post, Change Username, Sign Out). Auth slice (`/login`, `/signup`, `/welcome`) shipped earlier in commit `ceef3d7` with styled components, new `AuthPageShell`, theme-aware light/dark backgrounds, and reusable header/brand primitives. `default` is now the default theme when available in the registry.

**Sub-plans:** The remaining work is split into one-PR sub-plans under [`05-subplans/`](./05-subplans/README.md). Order: Inbox → Search → Settings → CreatePost → ChangeUsername → SignOut. **Next:** [`05-subplans/01-inbox.md`](./05-subplans/01-inbox.md).

---

## Scope

### In scope
Inside `web/frontend/src/themes/default/routes/`, rewrite:
- `InboxView.js`
- `SearchResultsView.js`
- `SettingsView.js`
- `CreatePostView.js`
- `LoginView.js`
- `CreateAccountView.js`
- `WelcomeView.js`
- `ChangeUsernameView.js`
- `SignOutView.js`

### Out of scope
- Remaining secondary routes (Plan 06).
- Any behavior/data changes (`useInbox`, `useSearchResults`, `useSettings`, etc.).

---

## General rules

- All these routes must live inside the desktop shell from Plan 02 (TopBar + Sidebar + content column).
- Reuse the theme’s `Button`, `MarkdownEditor`, `MarkdownRenderer`, panel containers, and form styling.
- Use the panel/section pattern for settings and info blocks.
- Align spacing and typography with the mobile app.

---

## Inbox

Reference: mobile `src/pages/inbox-screen.tsx`, web `themes/oldreddit/routes/InboxView.js`.

Requirements:
- List of notifications / replies with clear unread vs read states.
- Subtle background highlight for unread items (use `inboxReplyUnreadBg` tokens from Plan 01).
- Avatars, timestamps, and truncated content.
- Mark-as-read interactions preserved.
- Clearly styled empty state.
- Desktop width matches the shell content column; mobile uses full-bleed rows.

---

## Search

Reference: mobile `src/pages/search-screen.tsx`, web `themes/oldreddit/routes/SearchResultsView.js`.

Requirements:
- Search input prominent at top of the content column.
- Tabbed results (posts / users / communities) using the new tab style.
- Result cards reuse Plan 03 card primitives where appropriate.
- Desktop shortcut: `/search` is the destination for the TopBar search button from Plan 02.
- Empty state, loading state, and error state styled consistently.

---

## Settings

Reference: existing `themes/oldreddit/routes/SettingsView.js` and `themes/onyx/routes/SettingsView.js`.

Requirements:
- Section-based layout with panel containers.
- Sections to cover (non-exhaustive): theme, appearance, notifications, privacy, content preferences, account, advanced.
- Theme picker uses `THEMES` map like existing themes do.
- Use the shared `Button` + form field styling.
- Keep Save / Apply flow identical to the current theme’s behavior.

---

## Create post

Reference: mobile `src/pages/create-screen.tsx`, web `themes/onyx/routes/CreatePostView.js`.

Requirements:
- Form container styled like a panel.
- Community selector using theme-local `CommunitySelector` (renamed from `TopicSelector` in v1.39.0).
- Title + body inputs aligned with mobile typography.
- `MarkdownEditor` with sticky toolbar on desktop.
- Media attach row styled with theme tokens.
- Submit flow unchanged (uses existing `useCreatePost`).

---

## Auth flows (Login / CreateAccount / Welcome) ✅ Done

> Shipped in commit `ceef3d7`. Redesigned with styled components, a new `AuthPageShell`, theme-aware light/dark background helpers, and reusable header/brand primitives (`Header`, `BrandMark`, `Eyebrow`, `AuthTitle`). `default` is now the default theme when available in the registry.

References:
- mobile `app/(auth)/login.tsx`, `recovery-phrase.tsx`, `username.tsx`
- web `themes/oldreddit/routes/LoginView.js`, `CreateAccountView.js`, `WelcomeView.js`

Requirements:
- Centered card on desktop, full-bleed on mobile.
- Panel container styled with mobile tokens.
- Clear step indicators where applicable.
- Preserve existing behavior (seed vault, unlock flow, etc.) — do not touch `useLogin`, `useCreateAccount`, or `SeedVault`.
- Submit/confirmation buttons reuse the theme’s `Button`.

---

## Verification checklist

- [ ] `/inbox` renders with proper unread/read styling and updates counts.
- [ ] `/search` renders and routes from the TopBar search button.
- [ ] `/settings` renders every section and saves changes.
- [ ] Theme picker in Settings works (switching to/from `default`).
- [ ] `/create_post` composes and submits successfully.
- [x] `/login`, `/signup`, `/welcome` render and behave like the current theme. _(commit `ceef3d7`)_
- [ ] `/change_username`, `/sign_out` all render and behave like the current theme.
- [ ] No `themes/oldreddit/*` imports inside the new theme.
- [ ] Build passes:

```bash
cd web/frontend
CI=true npm run build
```

---

## Risks & mitigations

- **Seed vault / unlock regression** → do not modify the `UnlockPrompt` behavior; only restyle the theme’s `UnlockPrompt` component.
- **Settings sections drifting** → align section ordering with the existing themes so users have the same mental model.
- **Theme picker breaking** → keep reading `THEMES` from `src/registry/theme.js`.
- **CreatePost media upload regression** → reuse existing media helpers from `src/utils/ImageUpload.js` and `VideoUpload.js`.

---

## PR description template

> Rewrites `default` for the day-to-day account flows: inbox, search, settings, create post, and auth routes. Visual only — data hooks, seed vault, and theme picker logic are unchanged.
