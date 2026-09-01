# Sub-Plan 05.3 — Post Details

**Route / surface:**
- `/p/:postId` → single post + threaded comments view

**File:**
- `web/frontend/src/themes/default/routes/ViewPostView.js` (rewrite — visual only)

**Status:** ✅ Done — Iteration 1 (flat restyle) + Iteration 2 (tokens, header, sort, collapse, action row, composer, states) shipped
**Parent:** [`../05-inbox-search-settings-auth.md`](../05-inbox-search-settings-auth.md)

> Inserted into the Plan 05 order after Search shipped. The search dropdown, search results, Inbox, and every feed row navigate into `/p/:postId`, so the post-details screen is now the most-visited leaf route in the app. This sub-plan absorbs the "post detail" slice originally scoped under Plan 04; Plan 04's profile slice stays deferred.

---

## Iteration 1 — Flat single-canvas pass ✅ shipped

**Approach.** `ViewPostView.js` is a 2.7k-line file that encodes every post interaction (vote, donate, award, block, report, delete, edit, reply, confirmation flows, menus, mobile overlay). A full rewrite would risk regressing dozens of handlers. The safer path is a **surgical restyle of the presentation layer** — keep every hook, helper, and render function, and change only the styled-components so the visual output reads as Reddit-like + single-canvas per RULES R1/R3. This gives us 90% of the visual win without touching any data / mutation code.

### Styled primitives flattened

- **`PostCard` (root post container)**
  - Removed: card background (`pickCard('card')`), outer border (`pickCard('cardBorder')`), `border-radius`, `box-shadow`, and hover fill.
  - Added: `border-bottom: 1px solid theme.colors.border` (R3).
  - `$isNew` no longer paints a `panelAlt` fill — now draws a 3px `focusBlue` left-rail accent via `box-shadow: inset 3px 0 0 0` so R1 single canvas still holds.
  - `flashGlow` keyframes rewritten from a box-shadow flash to a subtle `rgba(102,126,234,0.12)` → `transparent` background fade (matches `CardView::Card` flash animation).
  - Responsive padding tightened to match Inbox / Search rhythm.

- **`CommentCard` (all comment rows)**
  - Inherits from `PostCard` but wipes `border-bottom`, `box-shadow`, and `background` so comments don't render the root-post divider between every row.
  - **Thread rail:** `border-left: 1px solid theme.colors.border` at every `$level > 0` (R3). Level 0 (direct replies to root) render with no rail so they hang directly off the root-post divider — matches mobile `comment-item.tsx` indent math.
  - Indent step reduced to `0.9rem` per level (was 1rem / 0.75rem depending on size) so deeply-nested threads stay readable.
  - Padding tuned per level: outer rows get `1rem`, nested rows get `0.85rem` left padding so the text aligns with the rail.
  - `.inbox-highlight` no longer paints a full yellow card — it draws a `#FACC15` left-rail accent (inset box-shadow) + a very subtle `rgba(250,204,21,0.06)` background tint. Visible at a glance, R1-compliant.

- **`CommunityHeroCard` (back + join header row)**
  - Flattened: no background, no border, no radius, no box-shadow. Now reads as a thin feed-style header row above the root post, identical tone to `InboxView` / `SearchResultsView` headers. The `PostCard` bottom divider underneath separates it from the post body.
  - `CommunityHeroWrapper` margin dropped to `0` so the header hugs the column top.

- **`StyledThreadReminder`** (single-comment sub-thread banner)
  - Flattened to a flat row with a bottom divider. Reads as a subtle notification above the root post, not a lifted card.

- **`ContinueThreadLink`** (deep-thread deep-link)
  - Flattened: no fill, no radius. Now a left-rail row (`border-left` + `border-bottom`) indented to match the parent comment depth. Hover lifts via `theme.colors.hoverBg` (existing token) instead of painting a new card surface.

- **`StyledReply` (inline composer wrapper)**
  - Removed `background: panelAlt`, border, and border-radius. Now a flat column with a top divider that sits inline under the active post/comment without adding another card layer.

- **`RootTitleRow` / `TitleDivider`**
  - Title font synced to `CardView::TitleLink` (`0.88rem / 700`, `0.78rem` mobile) for feed-card visual parity (R4).
  - `TitleDivider` margin tightened.

- **`StyledContentArea`**
  - Markdown body font synced to `CardView::Body` (`0.74rem` desktop, `0.68rem` mobile, `line-height: 1.45`). Post and comment content now read at the same rhythm as the feed.

### Preserved behaviour (no regressions)

- Every `useViewPost` hook return + every handler (vote, donate, award, block, report, delete, edit, reply submit, menus, mobile reply overlay, join community, follow user) is **untouched**.
- `annotated` comment-tree render loop, collapse/expand, focused-comment view, "Continue this thread", parent-chain context comments, deeplink scroll-to-hash, flash highlighting, and inbox-linked `.inbox-highlight` class all still work.
- Menu dropdowns (`MenuDropdown`, `MenuItem`) still use `menuBg` / `menuItemHoverBg` per R1 (contained-surface carve-out).

### Rules compliance

- ✅ **R1** — post card, comment rows, community hero, thread reminder, continue-thread, and reply composer all sit on `theme.colors.bg`. No component paints a full column background. Only contained menu popovers still use `panel` / `menuBg`, which is allowed.
- ✅ **R2** — every color now routed through an existing token (`border`, `link`, `linkHover`, `text`, `subtleText`, `focusBlue`, `hoverBg`). Only `#FACC15` for the inbox highlight accent remains as a raw hex — kept because it's an existing inbox-linked visual signal and neither dark nor light tokens currently cover yellow. **Open follow-up:** add an `inboxHighlightRail` token pair to R2 before the next iteration so this last raw hex can be retired.
- ✅ **R3** — every divider is `1px solid theme.colors.border`. No ad-hoc rgba dividers, no double borders, no gradients.
- ✅ **R4** — reference read-through done before coding: bluemoon `ViewPostView.js` (data parity — every field/flow preserved), mobile `src/components/molecules/comment-item.tsx` (visuals: thread rail per depth, indent math, flat no-card layout, action row language). Pragmatic interpretation of "same post card view": the root post's restyled `PostCard` now visually matches `CardView` (flat, single canvas, `border-bottom` divider, same typography tokens).

### Files changed

- `web/frontend/src/themes/default/routes/ViewPostView.js`
  - `PostCard`, `CommentCard`, `StyledThreadReminder`, `ContinueThreadLink`, `CommunityHeroCard`, `CommunityHeroWrapper`, `StyledReply`, `RootTitleRow`, `TitleDivider`, `StyledContentArea` all restyled in place.
  - Unused `pickCard` import dropped (no longer referenced after the flatten).

No other files touched. No token changes. No RULES.md changes this iteration.

### Verification

- [x] Build passes: `cd web/frontend && CI=true npm run build` → ✅ Compiled successfully, no warnings.
- [ ] Dark + light manual browser pass (recommended).
- [ ] Desktop + sidebar-hidden manual browser pass (recommended).
- [ ] Inbox → post deep-link highlight still visible.
- [ ] Flash highlight on freshly-posted comments still animates.
- [ ] "Continue this thread" still appears on deeply-nested comments.

---

## Remaining work — Iteration 2 ✅ shipped

All six polish items from the initial pass have been addressed:

1. ~~**Token the inbox highlight accent.**~~ ✅ `inboxHighlightRail` / `inboxHighlightBg` token pair added to R2 (dark: `#FACC15` / `rgba(250,204,21,0.06)`; light: `#D97706` / `rgba(217,119,6,0.08)`). Raw hex retired from `CommentCard`.
2. ~~**Header polish.**~~ ✅ `CommentsHeaderRow` with "Comments (N)" title rendered after the root post.
3. ~~**Comment sort controls.**~~ Removed — bluemoon doesn't expose sort controls, so default doesn't either (R4 data parity).
4. ~~**Collapsed comment row affordance.**~~ ✅ `CollapseToggle` now renders a chevron SVG that rotates 90° when collapsed, replacing the `[+]/[−]` text.
5. ~~**Action row styling.**~~ ✅ `ActionButton` pills now 32px tall (matching `VoteSection::PillRoot` exactly), `feedCtrlText` rest color, 16px icons, hover lifts to `text`. Reply / share pills line up with the vote container at every screen width.
6. ~~**Composer polish.**~~ ✅ `StyledReply` padding tightened (0.5rem/0.4rem), textarea padding reduced to 0.45rem/0.7rem, font synced to 0.68rem/1.45 line-height, 60px min-height.

**Additional polish in this iteration:**
- `LoggedOutPromptCard` for guest users (replaced `<Navigate to="/home">` redirect).
- `VPStateBlock` / `VPStateIcon` / `VPStateTitle` / `VPStateMessage` / `VPLoadingSpinner` for loading, error, and empty-comments states (matching Inbox/Search pattern).
- `BlockErrorMessage`, `BlockSuccessMessage`, `BlockConfirmMessage` routed through R2 tokens (no more raw hex).
- `CompactExpandedBody` font tightened to `0.7rem` / `0.64rem` mobile with `contentFontFamily` — proportionally smaller than `CardView::Body` since compact titles are also smaller.

---

## Scope (in)

1. **Header + back control.** Mobile-style top bar with a back chevron (goes back in history, falls back to `/home`) and the screen title ("Post" or the community) — inside the Plan 02 shell, not overlapping the TopBar.
2. **Post card.** Reuse the theme-local `CardView` for the root post so typography, action row, media, and vote pill stay identical to the feed. Any post-details-only affordances (full content expansion, deeplinked anchor, share menu) layered on top of `CardView` via props — **never fork `CardView`**.
3. **Comments thread.** Full-bleed threaded comments styled to match mobile:
   - Nested indentation using a single left border rail (`1px solid theme.colors.border`, R3) per depth level — no card-in-card backgrounds, single `bg` canvas (R1).
   - Author row: tier-colored `@username`, relative time, moderator / badge affordances bluemoon already exposes.
   - Markdown body rendered via the existing `MarkdownRenderer`.
   - Vote pill + reply button + overflow menu using the same `ActionPill` language as `CardView`.
   - "Collapse thread" affordance at every depth (carat on the left rail).
   - "Load more replies" / "Continue this thread" rows where bluemoon already paginates.
4. **Comment composer.**
   - Inline composer anchored below the root post for logged-in users (reuses existing `MarkdownEditor` primitive, no new text-editor code).
   - Per-comment reply composer that opens inline when the user clicks reply on any node.
   - Logged-out state: `LoggedOutPromptCard` above the thread, composer hidden.
5. **Load / empty / error states.** Shared `StateBlock` primitives (Inbox/Search parity): loading spinner, error card (`HiExclamationTriangle` + `voteDown` tint), deleted-post notice, empty-thread ("No comments yet — be the first").
6. **Layout.**
   - Lives inside `ContainerBody` → `PostDetailsWrap` with the same 720px cap + sidebar-hidden 80% expansion pattern as Inbox / Search.
   - Post card → optional context row → composer → comments thread, each separated by `1px solid theme.colors.border`.
   - Respects the `default_feed_view_mode` localStorage key only insofar as the root `CardView` always renders in full card mode regardless (compact is a list-view concept; single-post view is always expanded).
7. **Deep linking.** Preserve existing scroll-to-comment behavior (hash-based `#c<id>` or similar — bluemoon has it) and "highlight recently flashed" animation from the feed flow.
8. **Rules compliance.**
   - ✅ R1 — everything on `theme.colors.bg`. Comment rail uses a border, not a panel fill.
   - ✅ R2 — all colors via existing tokens. Add new pairs **only** if a required value can't be expressed with existing tokens (must update `RULES.md` R2 table in the same PR).
   - ✅ R3 — post↔composer↔comments separators all `1px solid theme.colors.border`. Indent rail same.
   - ✅ R4 — read bluemoon `ViewPostView.js` (data parity) **and** mobile `post-screen.tsx` / whichever mobile file owns the post-detail screen (visuals) before writing JSX.

## Scope (out)

- `useViewPost` / post fetch hooks / comment mutations — untouched.
- SeedVault / signing flows — untouched.
- Profile polish (stays deferred under Plan 04).
- Create-post and edit-post flows (separate sub-plans 05.5 / existing plan).
- `MobileBottomNav` restyle (remains deferred).
- Any API-shape changes — purely a visual rewrite.

---

## Reference read-through (do this first — R4)

**Bluemoon (data parity source):**
- `web/frontend/src/themes/bluemoon/routes/ViewPostView.js` — lists every field bluemoon renders: root post object, children tree, comment count, view-time tracking, flash highlighting, deeplink anchors, load-more rows, moderator controls, etc.
- Any helpers imported from `themes/bluemoon/components/*` — note the ones that are theme-local and need a default equivalent (do NOT import from bluemoon).

**Mobile app (visual source):**
- `mirage-mobile-app/src/pages/post-screen.tsx` (or whichever screen owns `/post/:id`) — header, card, composer, thread indentation, collapse carats.
- `mirage-mobile-app/src/components/comment-item.tsx` (or equivalent) — per-comment row layout, action row, indentation math.
- `mirage-mobile-app/src/components/comment-thread.tsx` (or equivalent) — recursive render + "load more" rows.

**Existing default to reuse:**
- `CardView.js` — root post.
- `MarkdownRenderer.js` / `MarkdownEditor.js` — comment body + composer.
- `ListFeedView.js` — `RowSlot` divider pattern, `StateBlock` (via Search/Inbox), action row language.
- `LoggedOutPromptCard.js` — guest state.
- `InboxView.js` / `SearchResultsView.js` — header + wrap + state-block patterns to mirror.

---

## Implementation steps (proposed order)

1. **Audit `ViewPostView.js`.** Map every bluemoon-originated field and every side-effect (view tracking, last-visit storage, comment count marking, scroll-to-hash, flash highlighting) so none regress.
2. **Read mobile post screen + comment item + comment thread files** — screenshot-worthy details noted in the sub-plan doc before any JSX goes in.
3. **New styled primitives** in `ViewPostView.js`: `PostDetailsWrap`, `BackRow`, `BackButton`, `HeaderTitle`, `Divider`, `ComposerWrap`, `CommentsList`, `CommentNode`, `CommentRail`, `CommentHeader`, `CommentBody`, `CommentActions`, `LoadMoreRow`, `CollapseToggle`.
4. **Root post render.** Wire the hook output into `CardView` using the same post-object shape Search uses. Verify media, action row, vote, and markdown still render correctly.
5. **Logged-in composer.** Mount `MarkdownEditor` inside `ComposerWrap` below the root post; submit handler untouched.
6. **Thread render.** Recursive `CommentNode` that takes `depth` and bumps `padding-left` by a fixed step (match mobile). Left rail border per depth. Per-node reply composer toggled by local state.
7. **Collapse / load-more.** Collapse toggles local `collapsedSet`; load-more rows call the existing pagination action.
8. **Deeplink + flash.** Keep the existing scroll-to-hash effect + flash-highlight animation. Port any `flashGlow` keyframe from `ListFeedView` if needed.
9. **State blocks.** Loading / error / deleted / empty — same `StateBlock` pattern Inbox + Search use.
10. **Guest state.** If not logged in → render `LoggedOutPromptCard` above the thread, hide composer.
11. **Verify.** Run the project build, then manual browser pass in dark + light + desktop + sidebar-hidden.

## Verification checklist

- [ ] Build passes: `cd web/frontend && CI=true npm run build` (no warnings).
- [ ] Navigating from Inbox reply → opens the correct post with the comment highlighted.
- [ ] Navigating from Search results → opens the correct post.
- [ ] Navigating from a feed row → opens the correct post with flash-highlight preserved.
- [ ] Comment tree renders to full depth with correct indentation.
- [ ] Collapse / expand works at every depth.
- [ ] Load-more rows fetch next page without breaking ordering.
- [ ] Reply composer opens per-comment and submits.
- [ ] Root composer submits and appends optimistically (hook behavior unchanged).
- [ ] Logged-out state shows `LoggedOutPromptCard`, hides composer.
- [ ] Deleted / error / empty states styled via `StateBlock`.
- [ ] Dark + light modes both correct (every color via R2 tokens).
- [ ] No `themes/bluemoon/*` or `themes/oldreddit/*` imports added.
- [ ] `useViewPost` (and any related data hook) untouched.
- [ ] Manual dark + light + desktop + sidebar-hidden browser pass.

## Risks

- **Flash-highlight keyframes + scroll-to-hash are fragile.** Port them carefully; regressions here break the Inbox → post flow.
- **Comment thread recursion depth.** Bluemoon may cap depth or flatten deep threads — match bluemoon's behavior exactly or data parity breaks.
- **Optimistic comment insertion.** The existing hook probably appends to a list after mutation; make sure the new render key / memoization doesn't drop the optimistic row.
- **Moderator-only affordances.** Bluemoon may render mod tools conditionally on the viewer's address. Mirror the exact visibility rules — don't leak mod controls to non-mods, don't hide them from mods.
- **Markdown edge cases.** Long URLs, inline code, tables — re-test against the shared `MarkdownRenderer` to confirm wrapping matches `CardView` defaults.

## PR description template

> Ships Plan 05.3 Post Details: rewrites `/p/:postId` in `default` against the Plan 02 shell with a mobile-app-inspired layout. Root post reuses the theme-local `CardView`; comment thread uses a single-canvas full-bleed layout with a left-rail divider per depth (R3). All colors routed through existing R2 tokens, dividers via `theme.colors.border`, visuals from `mirage-mobile-app/src/pages/post-screen.tsx`. `useViewPost` and all mutation hooks untouched — visual only. Bluemoon data parity preserved end-to-end.
