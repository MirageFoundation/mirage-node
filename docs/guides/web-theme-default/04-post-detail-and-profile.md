# Plan 04 — Post Detail & Profile

**Goal:** Rework the post detail page (`/p/:postId`) and the profile page (`/u/:identity`, `/profile`) inside `default` so they match the new shell and feed look.

**Depends on:** Plans 01, 02, 03.
**Unblocks:** Plan 05.

---

## Scope

### In scope
- Rewrite `routes/ViewPostView.js` inside `default`.
- Rewrite `routes/ProfileView.js` inside `default`.
- Add any profile-specific components needed (header, tabs, avatar block, etc.).
- Reuse `CardView`, `VoteSection`, and action row from Plan 03.

### Out of scope
- Inbox / search / settings / auth (Plan 05).
- Remaining secondary routes (Plan 06).
- Changing `useViewPost` / `useProfile` logic.

---

## Files to create or change

Inside `web/frontend/src/themes/default/`:

### Rewrite
- `routes/ViewPostView.js`
- `routes/ProfileView.js`

### Create (if needed)
- `components/ProfileHeader.js` (avatar, tier, stats, follow button)
- `components/ProfileTabs.js` (profile / submissions / comments / algo)
- `components/CommentThread.js` or similar (if existing comment rendering doesn’t match the new style)

---

## Post detail requirements

Reference: mobile app `app/post/[id].tsx` + web `themes/oldreddit/routes/ViewPostView.js`.

### Layout
1. **Back / breadcrumb** — subtle back affordance on mobile, breadcrumb on desktop.
2. **Post block** — reuses the new `CardView` visual but shows the full body and full media.
3. **Action row** — same upvote/downvote/comment/share/more pattern as the feed.
4. **Comment composer** — inline on desktop, collapsible on mobile.
5. **Comment list** — nested threads with subtle indent and separators.
6. **Context panel (optional)** — in desktop sidebar, show community context / post metadata.

### Behavior
- Keep existing sort controls (best, new, old, etc.) — restyle them with `FilterBar`.
- Nested reply form interactions stay the same; just restyle.
- Preserve deep-link scroll-to-comment behavior if the existing theme implements it.
- Markdown rendering uses the theme’s `MarkdownRenderer`.

---

## Profile requirements

Reference: mobile app `user-profile-screen.tsx` + `profile-screen.tsx`, web `themes/oldreddit/routes/ProfileView.js`.

### Layout
1. **Profile header**
   - avatar
   - username with tier color
   - followers / following counts
   - follow / unfollow button (or “edit profile” if own profile)
   - short bio / joined date / tier info
2. **Tabs**
   - `profile`, `submissions`, `comments`, `algo` (matches `config.profileTabs` in the manifest)
3. **Tab content**
   - Uses the theme’s Feed / list layout from Plan 03 when showing posts and comments.
4. **Sidebar panels** (desktop)
   - quick stats
   - moderation shortcuts (for own profile)

### Behavior
- Use `useProfile` data hooks unchanged.
- Preserve tab state when switching routes via `/profile` vs `/u/:identity`.
- Honor `config.profileDefaultTab`, `profileUsesListFeed`, `profileHideFilterSelect` on the manifest so feed integration works consistently.
- Follow / unfollow state uses existing hooks (`useFollowState`).

---

## Shared styling

- All panels reuse the panel treatment from Plan 02’s sidebar.
- All text uses the typography scale from Plan 01.
- All buttons reuse the theme’s `Button` component.
- Spacing uses mobile tokens so post detail and profile feel consistent with the feed.

---

## Verification checklist

- [ ] Opening `/p/:postId` on `default` shows the new layout with full body and comments.
- [ ] Upvote/downvote on the post detail match the feed action row.
- [ ] Comment composer submits successfully.
- [ ] Nested comment replies render with correct indent.
- [ ] `/u/:identity` renders profile header + tabs + feed/comments lists.
- [ ] `/profile` (own profile) renders correctly and offers edit/settings affordances.
- [ ] Follow/unfollow works and reflects state across the app.
- [ ] Dark and light modes verified.
- [ ] Build passes:

```bash
cd web/frontend
CI=true npm run build
```

---

## Risks & mitigations

- **Nested comment performance** → keep existing virtualization or sort helpers from `src/utils/SortComments.js`; do not rewrite them.
- **Profile tab config drift** → read tab list from `theme.caps.profileTabs` instead of hard-coding.
- **ChainParams / username limits** → continue using `src/utils/chainParams.js`; no theme-local forks.
- **Scroll jump when switching tabs** → replicate the existing theme’s behavior if any.

---

## PR description template

> Rewrites `default`’s post detail and profile pages on top of Plan 03’s feed primitives, with a desktop sidebar context panel and mobile-app styling. Uses existing `useViewPost` / `useProfile` hooks unchanged.
