# Sub-Plan 06.11 — Admin UI Pass

**Routes / surfaces:**
`/stats`, `/reports`, `/subscription` (admin branch), `/p/:id` (post-detail admin menu + admin confirm banners), `TopBar` profile dropdown, `MobileBottomNav` profile group, feed row menus (`CardView` / `PostMenu`).
**Files (default theme):**
- `themes/default/components/TopBar.js` (`ProfileMenuContent`)
- `themes/default/components/MobileBottomNav.js`
- `themes/default/components/CardView.js`
- `themes/default/components/PostMenu.js`
- `themes/default/routes/SubscriptionView.js` (admin branch ~L886–L912)
- `themes/default/routes/ReportsView.js`
- `themes/default/routes/StatsView.js`
- `themes/default/routes/ViewPostView.js` (`renderPostMenu` admin items ~L2696–L2718, `displayConfirmation` suspend/unsuspend banners ~L2398–L2476)
- `themes/default/tokens.js` (new admin token, see R2 update)

**Status:** 🚧 In progress — A/B/C ✅ done, D/E/F remain
**Parent:** [`../06-remaining-routes-and-polish.md`](../06-remaining-routes-and-polish.md)
**Depends on:** 06.1 (Profile), 06.2 (Components — `Button`, `ConfirmDialog`), 06.4 (Stats), 06.5 (Subscription) — all ✅ done.

---

## Why this sub-plan exists

Admin UI was never treated as a first-class slice during Plan 06. Pieces of it shipped along with the routes that surfaced them (Stats / Reports tokenized in 06.4; Subscription admin branch tokenized in 06.5), but there are still **four admin gaps** that drift from `RULES.md`:

1. **Feed-row admin actions are missing in default.** `themes/bluemoon/`, `themes/onyx/`, and `themes/oldreddit/` all expose admin moderation in `CardView.js` (mark-deleted / suspend / unsuspend on every feed row). `themes/default/components/CardView.js` and `themes/default/components/PostMenu.js` have **zero `isAdmin` references** — admins can only moderate from the post-detail page (`ViewPostView`), not the feed.
2. **The post-detail admin confirm banners use raw hex.** `displayConfirmation` in `themes/default/routes/ViewPostView.js` paints the suspend/unsuspend confirmation strip and the success toast with hard-coded values (`#d97706`, `#fef3c7`, `#92400e`, `rgba(22, 163, 74, 0.18)`, `#16A34A`, etc.) instead of routing through R2 tokens. They also use emoji (`🛡️`, `✓`) where the rest of the theme uses `react-icons/hi2`.
3. **Admin-only entries in `ProfileMenuContent` (`TopBar.js` L843–L897) and `MobileBottomNav.js`** ship without a tier indicator. Bluemoon shows an "Admin" pill next to admin-only menu groups; default does not. They also don't wear the canonical R6 `HiChevronDown` / R7 typography treatment that the rest of the menu got in 06.2.
4. **`ADMIN_COLOR` is hard-coded in shared logic.** `logic/useSubscription.js` exports `ADMIN_COLOR = '#EF4444'` and `useProfile.js` repeats `'#EF4444'` inline. Default uses this color in `ProfileView` / `SubscriptionView` headlines via `getTierColor(userLevel)`. Per R2, dark↔light pairing should live in `tokens.js` so the admin red can shift in light mode if design wants it (today the dark hex bleeds through).

---

## Audit — every admin-gated surface in default

> Generated from a `userLevel >= 100` / `isAdmin` / `/admin/` grep across `web/frontend/src/themes/default/**` and `web/frontend/src/logic/**`. Use this as the canonical checklist when verifying coverage.

### Admin-only routes
| Route        | File                                     | Gate                                                | Notes                                                                                  |
| ------------ | ---------------------------------------- | --------------------------------------------------- | -------------------------------------------------------------------------------------- |
| `/reports`   | `routes/ReportsView.js`                  | `useReports` returns early when `userLevel < 100`; view also renders a `Forbidden` `StateBlock` (L354–L367) | Already tokenized in 06.3 — only needs the menu-entry/admin-pill part of this sub-plan. |
| `/stats`     | `routes/StatsView.js`                    | Surfaced only via the admin nav group              | Tokenized in 06.4 — same as Reports, only the entry-point work applies here.            |

### Admin-conditional UI inside shared routes
| Surface                                  | File / line                                                | Behavior gated by `userLevel >= 100`                                                                                                            |
| ---------------------------------------- | ---------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| `ProfileMenuContent` (TopBar dropdown)   | `components/TopBar.js` L843–L897                            | Renders extra `<MenuDivider />` + `Stats` + `Reports` items.                                                                                    |
| `MobileBottomNav` profile group          | `components/MobileBottomNav.js` (uses `ProfileMenuContent`) | Same admin block surfaces in the profile sheet.                                                                                                  |
| Subscription page                        | `routes/SubscriptionView.js` L886–L912                      | Admin branch hides the tier grid + auto-renew controls and shows a single "Active plan" card + "Admin status is managed via governance" copy.   |
| Subscription "auto-renew" toggle         | `routes/SubscriptionView.js` L737                           | `showAutoRenew = userLevel > 0 && userLevel < 100` — admins never see auto-renew.                                                                |
| Post detail menu                         | `routes/ViewPostView.js` L2696–L2718                        | Admin-only `MenuItem`s: **Mark post/comment deleted**, **Suspend from quests**, **Unsuspend from quests**.                                       |
| Post detail confirm banners              | `routes/ViewPostView.js` L2398–L2476                        | Inline `BlockConfirmMessage` for the suspend duration picker and the unsuspend prompt; success toast for both.                                   |
| Suspension fetch on menu open            | `routes/ViewPostView.js` L2584                              | `fetchUserSuspensionStatus` only fires when `isAdmin && questsEnabled`.                                                                          |

### Admin-conditional UI **missing** in default (parity gaps)
| Surface                                | Where it exists today                                                              | Default file that needs it                                                                                                |
| -------------------------------------- | ---------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| Feed-row "Mark post deleted"           | `themes/bluemoon/components/CardView.js` ~L919, ~L2330 (and `onyx` / `oldreddit` mirrors) | `themes/default/components/CardView.js` + `themes/default/components/PostMenu.js` (`MoreMenuChip`).                       |
| Feed-row "Suspend / Unsuspend from quests" | Same (`bluemoon` / `onyx` / `oldreddit` `CardView.js`)                            | `themes/default/components/CardView.js` + `themes/default/components/PostMenu.js`.                                        |
| Suspension status pre-fetch in feed    | Same                                                                                | `themes/default/components/CardView.js` (mirror `fetchUserSuspensionStatus` wiring).                                      |

### Shared logic (do not modify in this sub-plan)
| File                                | Concern                                                                                                                  |
| ----------------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| `logic/useSubscription.js` L21–L30  | `ADMIN_COLOR`, `getTierName(level)`, `getTierColor(level)`, `isAdmin(level)`. Visual change happens via the new R2 token, not here. |
| `logic/useProfile.js` L565, L574    | Repeats `'#EF4444'` for the Admin chip. Refactor in a follow-up — out of scope for this sub-plan.                         |
| `logic/useReports.js`               | Auth gate (`userLevel < 100` returns early). Used by `ReportsView`.                                                       |
| `logic/useViewPost.js` L984–L1067   | `/admin/rewards/suspend` + `/admin/rewards/unsuspend` API calls. Visual restyle of callers only — no API change.          |

---

## Goal

Bring every admin-only surface in `default` up to `RULES.md` (R1–R7) parity with the rest of the theme, close the feed-row moderation gap, and standardize the admin red on a token instead of inline hex. **No behavior changes** — the gates, API calls, and copy stay identical.

---

## References (R4 reading list — read before changing each file)

- **Web (data parity):** `themes/bluemoon/components/CardView.js`, `themes/bluemoon/routes/{ViewPostView,SubscriptionView}.js`, `themes/bluemoon/components/TopBar.js`.
- **Visuals:** `mirage-mobile-app/src/pages/post-screen.tsx` (suspend / mark-deleted action sheet), `src/components/molecules/post-card-header.tsx` (overflow menu), `src/pages/profile-screen.tsx` for the admin chip color.
- **Already-shipped default patterns to reuse:**
  - Confirm dialogs → `themes/default/components/ConfirmDialog.js` (replace inline `BlockConfirmMessage` strips).
  - Menu items → `themes/default/components/PostMenu.js` (`MenuItemBtn`, `data-danger="true"`).
  - Form inputs → R5 (the suspend-duration `<select>` must follow the canonical input style).
  - Status banners → R2 `voteUpBg` / `voteUp` for success, `inboxHighlightRail` / `inboxHighlightBg` for warning.

---

## Requirements

### A. Tokenize the admin red (R2) — ✅ Done

Add a new token pair to `themes/default/tokens.js` and document it in the R2 table inside `RULES.md`:

| Token       | Dark      | Light     | Use                                                           |
| ----------- | --------- | --------- | ------------------------------------------------------------- |
| `tierAdmin` | `#EF4444` | `#DC2626` | Admin tier label (`getTierName(userLevel) === 'Admin'`), admin chip, admin section accents. |

Replacement scope inside `themes/default/**`:
- Anywhere `getTierColor(userLevel)` is rendered when the user is an admin (e.g. `ProfileView` `Mono` fields, `SubscriptionView` `ActivePlanName`), prefer reading `theme.colors.tierAdmin` over the value returned by the shared helper. The helper itself stays in `logic/useSubscription.js` for cross-theme parity.
- Replace any inline `#EF4444` inside `themes/default/**` with `tierAdmin`.

### B. Profile menu — admin group polish (TopBar + MobileBottomNav) — ✅ Done

In `themes/default/components/TopBar.js` `ProfileMenuContent` (the same component is rendered by `MobileBottomNav.js`):
- Wrap the admin block in a labelled section. Add a small uppercase eyebrow row (`MenuHeader` style — `0.55rem/500 menuHeaderText`) reading `Admin` above the divider.
- Keep the existing `Stats` + `Reports` items unchanged in label and target. Apply the canonical `MenuItem` typography (R7 `0.78rem/500`, `600` on hover).
- Add an `Admin` pill (small `tierAdmin` border, `0.55rem/600` text) next to `@username` in `DropdownHeader` when `isAdmin`. Mirrors the bluemoon affordance.
- All chevrons stay `HiChevronDown` per R6.

### C. Subscription admin branch (`SubscriptionView.js` L886–L912) — ✅ Done

- Replace the bare "Active plan" `Section` with the same `ActivePlanCard` pattern used by the non-admin branch. Tier name uses `theme.colors.tierAdmin`.
- Move the descriptive copy ("Admin accounts have full access…") into a muted `InfoText` block sitting on `bg` (R1) with a 1px `border` divider above it.
- Confirm `ActivePlanLabel` + `ActivePlanName` follow R7: label `0.62rem/500 subtleText`, name `1.1rem/700 tierAdmin`.
- Verify `userLevel > 0 && userLevel < 100` still gates the auto-renew banner so admins keep seeing nothing for it.

### D. Post-detail admin menu + confirm banners (`ViewPostView.js`) — ✅ Done

Two passes — one structural, one visual:

**D1. Replace inline confirm strips with `ConfirmDialog`.**
- The `confirmSuspendQuests` block (L2398–L2434) becomes a `ConfirmDialog` call:
  - Title: `Suspend user from quests`.
  - Body: existing copy + the duration `<select>` styled per R5 (rest border `border`, hover/focus `borderStrong`, `0.75rem/500`, `bg` background). No raw hex on the select.
  - Primary action: `Button variant="danger"` → "Suspend".
  - Secondary action: `Button variant="ghost"` → "Cancel".
- Same treatment for `confirmUnsuspendQuests` (L2436–L2458) with primary copy "Unsuspend".
- The success toast (L2460–L2476) becomes a `Toast` (success variant) — drop the inline `rgba(22,163,74,0.18)` + `#16A34A` styling. Reuse `themes/default/components/Toast.js`.
- Remove the `🛡️` emoji from both prompts. Use `HiOutlineShieldExclamation` (already imported at the top of `ViewPostView.js`) inside the dialog title.

**D2. Tokenize the admin menu items (L2696–L2718).**
- "Mark post/comment deleted", "Suspend from quests", "Unsuspend from quests" already use `MenuItem data-danger="true"`. Verify `data-danger` rule in `MenuDropdown` resolves to `menuDangerText` per RULES R2.
- Order: `Mark deleted` → `Suspend` → `Unsuspend` (current order is fine; just confirm).

### E. Feed-row admin parity (CardView + PostMenu) — closes the parity gap — ⏳ Pending

In `themes/default/components/CardView.js`:
- Add the admin computation at the top of the component (mirror bluemoon's `userLevel` + `isAdmin = hasValidAccount && userLevel >= 100` block).
- Wire `userSuspendedStatus` state + `fetchUserSuspensionStatus` (lift the implementation from bluemoon and route the API call through `utils/api.js` like the existing imports).
- Pass `isAdmin`, `userSuspendedStatus`, `fetchUserSuspensionStatus`, `handleSuspendFromQuests`, `handleUnsuspendFromQuests`, `handleDeletePost`, `questsEnabled` to `PostMenu`'s `MoreMenuChip`.

In `themes/default/components/PostMenu.js` `MoreMenuChip`:
- After the existing non-owner items (Follow / Gift / Award), append an admin block matching the post-detail ordering: **Mark deleted** → **Suspend from quests** → **Unsuspend from quests**.
- Each item uses `MenuItemBtn data-danger="true"` with `HiOutlineShieldExclamation` icons (already imported in `ViewPostView.js`; add the import in `PostMenu.js`).
- The suspend / unsuspend flows reuse the same `ConfirmDialog` + `Toast` pattern from D1. Hoist the dialog state into `MoreMenuChip` so every feed-row can fire its own dialog without bleeding into siblings.
- `fetchUserSuspensionStatus(post.user_id)` fires only when the menu opens **and** `isAdmin && questsEnabled` (mirror bluemoon).

### F. Visual cleanup — ⏳ Pending

- No raw hex / rgba in any admin path inside `themes/default/**` after this sub-plan.
- All admin-related buttons funnel through `themes/default/components/Button.js` (`variant="danger"` / `variant="ghost"`).
- All admin-related inputs (the duration `<select>`) follow R5 (no blue ring).
- All admin chevrons / icons use `react-icons/hi2` per R6 — no emoji, no inline polyline SVGs.
- Page heading / row title typography follows R7.

---

## Out of scope

- Refactoring `logic/useSubscription.js` `ADMIN_COLOR` / `logic/useProfile.js` inline `#EF4444` — those are shared across all themes and deserve their own cross-theme PR.
- Adding new admin features (e.g. ban-user, force-unsubscribe). This sub-plan is **visual + parity** only.
- Touching `themes/bluemoon/` / `themes/onyx/` / `themes/oldreddit/` admin UI.
- Backend / API changes (`/admin/rewards/suspend`, `/admin/rewards/unsuspend`).
- Mobile bottom nav full restyle — sub-plan 06.8 owns that. Only the `ProfileMenuContent` admin section is in scope here.

---

## Verification checklist

Before opening the PR:

- [ ] Read `themes/bluemoon/components/CardView.js` admin block (R4 — web data parity).
- [ ] Read `mirage-mobile-app/src/pages/post-screen.tsx` for the moderation action sheet visuals (R4 — mobile visual parity).
- [ ] `tierAdmin` token added to `themes/default/tokens.js` with both dark + light values, and documented in `RULES.md` R2.
- [ ] `grep -nE "#EF4444|#DC2626" web/frontend/src/themes/default/` returns 0 matches.
- [ ] `grep -nE "#d97706|#fef3c7|#92400e|rgba\\(22, 163, 74" web/frontend/src/themes/default/routes/ViewPostView.js` returns 0 matches.
- [ ] `grep -n "🛡️\\|✓" web/frontend/src/themes/default/routes/ViewPostView.js` returns 0 matches inside the suspend / unsuspend banners.
- [ ] `grep -n "isAdmin" web/frontend/src/themes/default/components/CardView.js` returns ≥1 match (parity gap closed).
- [ ] `grep -n "isAdmin" web/frontend/src/themes/default/components/PostMenu.js` returns ≥1 match.
- [ ] All admin menu items render `react-icons/hi2` icons (no emoji, no inline polyline).
- [ ] R5 input style applied to the suspend-duration `<select>` (no blue ring, neutral `borderStrong` focus).
- [ ] R7 typography on the new admin pill, eyebrow, dialog title, and menu rows.
- [ ] Admin-only routes (`/stats`, `/reports`) still gate-render the `Forbidden` `StateBlock` for non-admins.
- [ ] `SubscriptionView` admin branch shows `tierAdmin` headline, hides the tier grid, and hides the auto-renew banner.
- [ ] `ProfileMenuContent` admin block renders identical labels (`Stats`, `Reports`) and routes (`/stats`, `/reports`) — no scope creep.
- [ ] Dark + light verified manually on every touched route + the post-detail moderation flow.
- [ ] No `themes/oldreddit/*` or `themes/bluemoon/*` imports inside `themes/default/*`.
- [ ] Build passes:

```bash
cd web/frontend
CI=true npm run build
```

### Manual QA (admin account required)

Run with a `user_level >= 100` account:

1. Open the avatar dropdown → confirm the new `Admin` eyebrow + pill render and the `Stats` / `Reports` items still navigate correctly.
2. Open `MobileBottomNav` profile sheet at ≤600px — confirm the admin block surfaces identically.
3. Visit `/subscription` — confirm the admin branch shows `tierAdmin`-colored "Admin" name + governance copy, no tier grid.
4. Open any feed-row menu (home + topic + profile feed) — confirm `Mark deleted` / `Suspend from quests` / `Unsuspend from quests` appear, and that suspend status is fetched on menu open.
5. Trigger Suspend / Unsuspend from a feed row → `ConfirmDialog` appears, success → success `Toast`. No layout shift.
6. Trigger Suspend / Unsuspend from the post-detail page → same dialog, same toast.
7. `/reports` and `/stats` render normally; signed-out + non-admin viewers still see the `Forbidden` block (or the home redirect for `/reports`).
8. Re-run the test above with a non-admin account — every admin item is hidden and no `/admin/rewards/*` request fires.

---

## PR description template

> Sub-plan 06.11 — admin UI pass for the `default` theme. Closes the feed-row moderation parity gap, retires inline hex / emoji on the post-detail suspend confirm banners (now `ConfirmDialog` + `Toast`), tokenizes the admin red on a new `tierAdmin` R2 token, and adds an `Admin` eyebrow + pill to the profile menu. No behavior or API changes — gates and copy unchanged. Verified on dark + light with an admin and a non-admin account.
