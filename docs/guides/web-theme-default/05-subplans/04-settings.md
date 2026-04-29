# Sub-Plan 05.3 — Settings

**Route:** `/settings`
**File:** `web/frontend/src/themes/default/routes/SettingsView.js`
**Status:** ✅ Done
**Parent:** [`../05-inbox-search-settings-auth.md`](../05-inbox-search-settings-auth.md)

---

## Goal

Rewrite `default`'s `SettingsView` as a section-based panel layout matching the mobile-app feel, while keeping the existing save/apply flow and theme picker behavior.

---

## References

- **Web (structure):** `web/frontend/src/themes/oldreddit/routes/SettingsView.js`
- **Web (modern layout):** `web/frontend/src/themes/onyx/routes/SettingsView.js`
- **Theme registry (do not modify):** `web/frontend/src/registry/theme.js` — read `THEMES` map
- **Data hooks (do not modify):** `useSettings` (verify exact path)

---

## Scope

### In scope
- Rewrite `themes/default/routes/SettingsView.js`.
- Add theme-local `SettingsSection` / `SettingsRow` / `FormField` components as needed.
- Integrate with existing `THEMES` map for the theme picker.

### Out of scope
- `useSettings` or any settings persistence logic.
- Theme registry changes.
- New settings fields (only restyling existing ones).

---

## Requirements

- Section-based layout using **panel containers** (mobile-app tokens).
- Sections (non-exhaustive, align order with existing themes):
  1. **Theme** (theme picker using `THEMES` map)
  2. **Appearance** (density, compact mode, etc.)
  3. **Notifications**
  4. **Privacy**
  5. **Content preferences**
  6. **Account**
  7. **Advanced**
- Theme picker renders each theme option as a selectable card/row with preview swatch if possible.
- Form fields (toggles, selects, inputs) use shared `Button` + field styling.
- Save / Apply flow **identical** to current theme's behavior — no hook or state change.
- Sticky section nav on desktop (optional, nice-to-have).
- Desktop width matches shell content column; mobile is full-bleed with collapsible sections.
- Dark + light modes both work.
- No `themes/oldreddit/*` imports inside the new file.

---

## Suggested implementation steps

1. Read `themes/oldreddit/routes/SettingsView.js` for current structure + hook wiring.
2. Read `themes/onyx/routes/SettingsView.js` for modern section layout.
3. Read `registry/theme.js` to confirm `THEMES` map shape.
4. Copy oldreddit structure into `themes/default/routes/SettingsView.js`.
5. Extract a reusable `SettingsSection` component (panel header + children).
6. Extract `SettingsRow` for label + control pairs.
7. Rebuild the theme picker section using `THEMES` map iteration.
8. Apply panel containers and mobile-app tokens throughout.
9. Verify Save/Apply still works (do not touch the handler).
10. Verify switching **to** and **from** `default` via the picker works.
11. Build + manual test across sections.

---

## Verification checklist

- [ ] `/settings` renders every section and saves changes.
- [ ] Theme picker in Settings works (switching to/from `default`).
- [ ] Panel-based sections styled with mobile-app tokens.
- [ ] Form controls use shared `Button` + field styling.
- [ ] Dark + light modes verified.
- [ ] Desktop + mobile layouts verified.
- [ ] No `themes/oldreddit/*` imports.
- [ ] Build passes:

```bash
cd web/frontend
CI=true npm run build
```

---

## Risks

- **Theme picker breakage** → always read `THEMES` from `src/registry/theme.js`; never hard-code the list.
- **Settings persistence regression** → do not wrap or replace the existing save handler.
- **Section drift** → keep section ordering aligned with other themes so users have the same mental model.

---

## PR description template

> Rewrites `default`'s `SettingsView` with panel-based sections, mobile-app tokens, and Plan 02 shell layout. Rebuilds the theme picker using the existing `THEMES` map. Visual only — `useSettings`, save/apply, and theme registry unchanged.
