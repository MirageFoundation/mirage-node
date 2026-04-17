# Sub-Plan 06.1 — Profile

**Route:** `/profile`, `/u/:identity`
**File:** `web/frontend/src/themes/mirageapp/routes/ProfileView.js`
**Status:** ⏳ Not started — **was the deferred profile slice of Plan 04**
**Parent:** [`../06-remaining-routes-and-polish.md`](../06-remaining-routes-and-polish.md)

---

## Current state

`themes/mirageapp/routes/ProfileView.js` is a **5-line diff from `themes/oldreddit/routes/ProfileView.js`** — only `MobileHeader` was added. The view still renders in oldreddit tokens/typography and violates R1, R2, R5, and R7.

---

## Goal

Rewrite `ProfileView` with mirageapp tokens + mobile-app visuals, sitting inside the Plan 02 desktop shell. Preserve every data field bluemoon displays (R4).

---

## References

- **Mobile (visual):** `mirage-mobile-app/src/pages/user-profile-screen.tsx`, `profile-screen.tsx`
- **Web (data + structure):** `themes/bluemoon/routes/ProfileView.js`
- **Web fallback structure:** `themes/oldreddit/routes/ProfileView.js`
- **Theme primitives:** `themes/mirageapp/components/{Button,VoteSection,FilterBar,CardView,MarkdownRenderer}`

---

## Scope

### In scope
- Rewrite `routes/ProfileView.js` fully (do not leave oldreddit tokens).
- Create `components/ProfileHeader.js` (avatar, tier color, follower/following counts, follow/edit button, bio, joined date, tier info).
- Create `components/ProfileTabs.js` (profile / submissions / comments / algo — read from `theme.caps.profileTabs`).
- Reuse `CardView` + `VoteSection` for post/comment lists.
- Apply R1 (single `bg` canvas), R2 tokens, R3 dividers, R5 input focus, R7 typography.

### Out of scope
- `useProfile`, `useFollowState`, chainParams — no logic changes.
- `SortComments` / virtualization helpers — keep as-is.

---

## Requirements

### Profile header
- Avatar, username rendered with tier color.
- Followers / following counts (links to respective lists).
- Follow / unfollow button (uses `followBtnBg` + `followBtnBorder` tokens); `Edit profile` button for own profile.
- Short bio, joined date, tier info.
- Background sits on `theme.colors.bg` (R1).

### Tabs
- Tab bar matches R7: `0.75rem`, inactive `500`, active `600`, underline in `focusBlue`.
- Honor `config.profileTabs`, `config.profileDefaultTab` from the manifest.
- Preserve tab state when switching between `/profile` and `/u/:identity`.

### Feed / comment content
- Uses `CardView` (already restyled).
- `profileUsesListFeed` + `profileHideFilterSelect` caps honored.
- Comment rows match inbox/row density.

### Behavior
- Follow/unfollow, block, mute wiring unchanged.
- Dark + light verified.
- No `themes/oldreddit/*` imports.

---

## Suggested implementation steps

1. Read `themes/bluemoon/routes/ProfileView.js` and list every data field it renders.
2. Read `mirage-mobile-app/src/pages/user-profile-screen.tsx` for visual reference.
3. Scaffold `components/ProfileHeader.js` + `components/ProfileTabs.js`.
4. Rewrite `routes/ProfileView.js` using the new components + `CardView` for lists.
5. Wire `useProfile` and `useFollowState` unchanged.
6. Register new components in `themes/mirageapp/index.js` (if used cross-route).
7. Build + manual smoke (own profile + other user profile, each tab, follow/unfollow).

---

## Verification checklist

- [ ] `/profile` renders header + tabs + content with mirageapp tokens.
- [ ] `/u/:identity` renders correctly for another user.
- [ ] Every data field bluemoon shows is present.
- [ ] Follow / unfollow works; state propagates across app.
- [ ] Tab switching preserves state correctly.
- [ ] Dark + light verified.
- [ ] Desktop + tablet + mobile layouts verified.
- [ ] No `themes/oldreddit/*` imports.
- [ ] Build passes:

```bash
cd web/frontend
CI=true npm run build
```

---

## PR description template

> Rewrites `mirageapp`'s `ProfileView` with mirageapp tokens, new `ProfileHeader` + `ProfileTabs` components, and mobile-app visual language. Sits on the Plan 02 desktop shell. Data hooks unchanged. **Closes sub-plan 06.1** and the profile slice of Plan 04.
