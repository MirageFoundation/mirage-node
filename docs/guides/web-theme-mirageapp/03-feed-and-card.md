# Plan 03 — Feed, CardView, Vote & Action Row

**Goal:** Replace the home/following/topic feed rendering and the post card visuals inside `mirageapp` so the most-visited surface matches the mobile app feel.

**Depends on:** Plans 01 and 02.
**Unblocks:** Plan 04 (post detail reuses these primitives).

---

## Scope

### In scope
- Rewrite `components/CardView.js` in the new theme.
- Rewrite `components/VoteSection.js` in the new theme.
- Create an action row (upvote / downvote / comment / share / menu) aligned with the mobile `PostActions`.
- Replace `ListFeedView.js` (or the theme’s equivalent `Feed` component) with a layout that fits the new shell.
- Wire `manifest.Feed` and `manifest.VoteSection` to the new components.
- Rewrite `routes/MainView.js` inside `mirageapp` to use the new feed layout.
- Update `components/FilterBar.js` for the new typography/spacing.

### Out of scope
- Post detail page (Plan 04).
- Profile / inbox / search / settings (Plans 04 / 05).
- Media preview overhaul (keep existing behavior; only restyle if cheap).

---

## Files to create or change

Inside `web/frontend/src/themes/mirageapp/`:

### Replace / rewrite
- `components/CardView.js`
- `components/VoteSection.js`
- `components/FilterBar.js`
- `ListFeedView.js` (or the equivalent file referenced by `manifest.Feed`)
- `routes/MainView.js`

### Update
- `index.js` — make sure `CardView`, `VoteSection`, `FilterBar` are registered on the manifest `components` map and `Feed: ...` points at the new feed component.

---

## Design direction

### Card structure (mobile-app inspired)
Reference: `mirage-mobile-app/src/components/molecules/post-card.tsx` + `post-card-header.tsx` + `post-actions.tsx`.

Layout from top to bottom:
1. **Header row** — `#topic • time ago • @username` with follow affordance on the right.
2. **Award badges row** (only if awards exist).
3. **Title + body** — title bold, markdown body trimmed to ~700 chars in feed, full in detail.
4. **Media block** — image/video/gallery with optional blur for sensitive content.
5. **Appendices / agent-edited badge** (if present).
6. **Action row** — upvote, score, downvote, comment count, share, more menu.

Styling rules:
- Subtle bottom border between posts instead of heavy card shadows.
- Padding uses mobile spacing tokens (Plan 01).
- Corner radii use mobile radius tokens.
- Hover states are allowed on desktop but must stay minimal.

### Vote section
Reference: `mirage-mobile-app/src/components/molecules/post-actions.tsx`.

Requirements:
- Upvote / downvote + numeric score inline (not a tall vote column).
- Colors: green for upvote, red/purple for downvote, subtle default otherwise.
- Active vote state persists (color on both arrow and count).
- Animates on press (small bounce) on desktop and mobile.
- Exposes the same props/callbacks the existing `CardView` expects so no data-layer changes are needed.

### Feed layout
Reference: `themes/oldreddit/ListFeedView.js` for structure + `themes/bluemoon/BlueMoonFeedView.js` for modern layout choices.

Requirements:
- Single-column list inside the content column from Plan 02.
- Post spacing tighter than `bluemoon`, closer to mobile density.
- No giant card shadows.
- Empty state, loading state, and error state all styled with the new tokens.
- Works cleanly with and without the desktop sidebar.

### Filter bar
Requirements:
- Sort tabs (Hot / New / Top / etc.) styled like the mobile app’s feed-mode selector.
- Sticky or inline — pick whichever fits better with the Plan 02 TopBar without double-stacking headers.

---

## Behavior & integration notes

- Keep all data wiring in `useMain` / `useViewPost` / etc. unchanged — this is a presentation-only change.
- Props on `CardView` must remain **compatible** with other themes’ `CardView` because shared hooks (`useMain`, `useProfile`) import via the theme family resolver — mismatched props will break shared code.
- Re-use existing helpers from `src/utils/` (`formatters`, `tierColors`, `media`, `SortComments`, etc.). Do not fork them into the theme.
- Use `getThemeFamily(theme.themeId).VoteSection` inside `CardView` the same way existing themes do, so the vote component stays theme-resolved.

---

## Verification checklist

- [ ] Home feed on `mirageapp` renders posts using the new card layout.
- [ ] Following and topic feeds use the same layout.
- [ ] Upvote/downvote buttons work and persist color state.
- [ ] Comment count, share, and more menu open correctly.
- [ ] Markdown body is truncated in feed and full on detail (Plan 04 will verify detail view).
- [ ] Media blocks still render (images, video, gallery, blur).
- [ ] Spacing and typography visibly match the mobile app rhythm.
- [ ] No regressions on other themes (`bluemoon`, `onyx`, `oldreddit`).
- [ ] Build passes:

```bash
cd web/frontend
CI=true npm run build
```

---

## Risks & mitigations

- **CardView prop drift** → diff against existing theme CardViews before shipping; keep the prop surface identical.
- **Vote animation jank on low-end devices** → use CSS transforms, not layout-affecting animations.
- **Media regression** → keep media helpers (`InlineMedia`, `MediaGallery`) inside the theme and restyle their containers instead of rewriting media logic.
- **Feed density too tight on desktop** → allow a single `--card-gap` variable in `Layout.js` so it’s easy to tune.

---

## PR description template

> Rewrites `mirageapp`’s feed, CardView, FilterBar, and VoteSection to match the mobile app’s post layout and action row, while keeping data hooks and prop shape unchanged. Post detail and profile follow in Plan 04.
