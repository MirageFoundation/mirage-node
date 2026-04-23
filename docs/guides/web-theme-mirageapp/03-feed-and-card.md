# Plan 03 — Feed, CardView, Vote & Action Row

**Goal:** Replace the home/following/topic feed rendering and the post card visuals inside `mirageapp` so the most-visited surface matches the mobile app feel.

**Depends on:** Plans 01 and 02.
**Unblocks:** Plan 04 (post detail reuses these primitives).
**Status:** ✅ Done — shipped in `mirageapp`. A manual cross-theme browser regression pass is still recommended.

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

- [x] Home feed on `mirageapp` renders posts using the new card layout.
- [x] Following and topic feeds use the same layout.
- [x] Upvote/downvote buttons work and persist color state.
- [x] Comment count, share, and more menu open correctly.
- [x] Markdown body is truncated in feed and full on detail (Plan 04 will verify detail view).
- [x] Media blocks still render (images, video, gallery, blur).
- [x] Spacing and typography visibly match the mobile app rhythm.
- [ ] No regressions on other themes (`bluemoon`, `onyx`, `oldreddit`). _(needs manual in-browser verification)_
- [x] Build passes:

```bash
cd web/frontend
CI=true npm run build
```

---

## Implementation notes (post-rewrite)

Beyond the original scope, the following refinements were applied during iteration and are shipped in the current `mirageapp` theme:

- **Feed header** — Home/Following tabs and Create-post button removed. Only a Sort button (`Best` / `New`) and a View icon-button (Card / Compact) remain, both styled as transparent chevron buttons with `feedCtrlText` / `feedCtrlHoverBg` tokens. View mode persists via `Storage` at `mirageapp_feed_view_mode`.
- **Compact mode** — 2-column grid (84px thumbnail + stacked text), inline expand chip that reveals `InlineMedia` + `MarkdownRenderer` in place without navigating away. Comment/Share buttons share the 32px filled-chip height with the vote pill.
- **Shared dropdown system** — Sort / View / Follow / Post-options / Block popovers share one style (`menuBg`, `menuSelectedBg`, `menuHeaderText`, `menuItemHoverBg/Text`, `menuDangerText`), edge-to-edge option bg, `max-content` width, `z-index: 100`.
- **Post card** — Pressable whole-card navigation (`isInteractiveTarget` skips links/buttons/popovers), follow pill opens a Follow topic / Follow user popover, dedicated red Block icon opens a Block & report popover, 3-dot menu carries Copy / Edit / Delete / Follow / Unfollow / Gift flows (Award/Gift Mirage/Gift Subscription currently navigate to `/u/:user?action=...` instead of opening inline modals — flagged as a follow-up).
- **Divider** — rendered by `RowSlot` in `ListFeedView` so it sits outside the card's rounded hover area.
- **Tokens added** — `feedCtrlText/HoverBg`, `menuBg/SelectedBg/HeaderText/ItemHoverBg/ItemHoverText/DangerText`, `followBtnBg/BgHover/Border/BorderHover`, `actionIconBg/HoverBg`.
- **Hidden-sidebar feed behavior** — when the desktop sidebar is collapsed, card view stays centered while compact view stays left-aligned and stretches to `80%` width.
- **Compact-row polish** — compact mode now shows the same inline feed-bucket label as card mode, uses the Mirage gradient for the no-media placeholder tile, and swaps the old expand glyphs for a smaller chevron that is hidden when there is no extra media/body content to reveal.
- **Metadata polish** — the top metadata row in both card and compact views now uses the compact action-row text color for topic / time / separators / feed tag, keeps usernames tier-colored, and uses a slightly smaller separator dot.

### Known follow-ups

- Award / Gift Mirage / Gift Subscription use a temporary `navigate('/u/...?action=...')` fallback; bluemoon's full inline modals still need to be ported.
- Cross-theme regression check (`bluemoon`, `onyx`, `oldreddit`) still needs a manual browser pass.

---

## Risks & mitigations

- **CardView prop drift** → diff against existing theme CardViews before shipping; keep the prop surface identical.
- **Vote animation jank on low-end devices** → use CSS transforms, not layout-affecting animations.
- **Media regression** → keep media helpers (`InlineMedia`, `MediaGallery`) inside the theme and restyle their containers instead of rewriting media logic.
- **Feed density too tight on desktop** → allow a single `--card-gap` variable in `Layout.js` so it’s easy to tune.

---

## PR description template

> Rewrites `mirageapp`’s feed, CardView, FilterBar, and VoteSection to match the mobile app’s post layout and action row, while keeping data hooks and prop shape unchanged. Post detail and profile follow in Plan 04.
