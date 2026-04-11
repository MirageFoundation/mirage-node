# Sub-Plan 05.2 — Search

**Route:** `/search`
**File:** `web/frontend/src/themes/mirageapp/routes/SearchResultsView.js`
**Status:** ⏳ Not started
**Parent:** [`../05-inbox-search-settings-auth.md`](../05-inbox-search-settings-auth.md)

---

## Goal

Rewrite `mirageapp`'s `SearchResultsView` so the TopBar search button lands on a result page that matches the theme's visual language, with tabbed results (posts / users / topics).

---

## References

- **Mobile:** `src/pages/search-screen.tsx`
- **Web (structure):** `web/frontend/src/themes/oldreddit/routes/SearchResultsView.js`
- **Web (interactions):** `web/frontend/src/themes/onyx/routes/SearchResultsView.js`
- **Data hook (do not modify):** `useSearchResults` (verify exact path before editing)
- **Plan 03 primitives:** theme-local `CardView` for post results

---

## Scope

### In scope
- Rewrite `themes/mirageapp/routes/SearchResultsView.js`.
- Add a theme-local `SearchInput` / `SearchTabs` component if it improves clarity.
- Wire into the Plan 02 shell + TopBar search button destination.

### Out of scope
- `useSearchResults` or any search backend/query logic.
- Search indexing or ranking changes.
- TopBar search button itself (already wired in Plan 02).

---

## Requirements

- Search input prominent at top of the content column (mobile-app styling).
- Tabbed results: **posts**, **users**, **topics** — tab style aligned with Plan 03 tabs.
- Post results reuse the Plan 03 `CardView` (or a compact variant).
- User + topic results use row-style cards with avatars and metadata.
- `/search` is the destination for the TopBar search button from Plan 02.
- **Empty state** (no query), **no-results state**, **loading state**, and **error state** all styled consistently.
- Desktop width matches the shell content column; mobile is full-bleed.
- Dark + light modes both work.
- No `themes/oldreddit/*` imports inside the new file.

---

## Suggested implementation steps

1. Read `themes/oldreddit/routes/SearchResultsView.js` to understand `useSearchResults` shape and current tab logic.
2. Read `themes/onyx/routes/SearchResultsView.js` for tab styling reference.
3. Read mobile `src/pages/search-screen.tsx` for input styling + empty state cues.
4. Copy the oldreddit structure into `themes/mirageapp/routes/SearchResultsView.js`.
5. Replace search input with a mobile-styled version (reuse TopBar search input styling if extracted).
6. Rebuild tabs using Plan 03 tab primitives.
7. Wire post results through the theme-local `CardView`.
8. Style user and topic result rows.
9. Add empty / no-results / loading / error states.
10. Verify the TopBar search button routes here correctly.
11. Build + manual smoke test.

---

## Verification checklist

- [ ] `/search` renders and routes from the TopBar search button.
- [ ] Tabs (posts / users / topics) switch correctly.
- [ ] Post results render via theme-local `CardView`.
- [ ] Empty / no-results / loading / error states all styled.
- [ ] Dark + light modes verified.
- [ ] Desktop + mobile layouts verified.
- [ ] No `themes/oldreddit/*` imports.
- [ ] Build passes:

```bash
cd web/frontend
CI=true npm run build
```

---

## PR description template

> Rewrites `mirageapp`'s `SearchResultsView` with mobile-app tokens, Plan 02 shell layout, and Plan 03 card/tab primitives. Adds tabbed posts/users/topics results with styled empty/loading/error states. Visual only — `useSearchResults` and TopBar search wiring unchanged.
