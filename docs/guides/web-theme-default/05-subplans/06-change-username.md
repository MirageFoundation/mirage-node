# Sub-Plan 05.6 — Change Username

**Route:** `/change_username`
**File:** `web/frontend/src/themes/default/routes/ChangeUsernameView.js`
**Status:** ✅ Done
**Parent:** [`../05-inbox-search-settings-auth.md`](../05-inbox-search-settings-auth.md)

---

## Goal

Rewrite `default`'s `ChangeUsernameView` with a Settings-style header, centered title/description text, auth-slice panel primitives for the form body, and composer-matched input styling.

---

## References

- **Mobile:** `app/(auth)/username.tsx`
- **Web (structure):** `web/frontend/src/themes/oldreddit/routes/ChangeUsernameView.js`
- **Web (canonical data):** `web/frontend/src/themes/bluemoon/routes/ChangeUsernameView.js`
- **Auth primitives (reuse):** `themes/default/components/AuthPageShell.js`
- **Settings header pattern:** `themes/default/routes/SettingsView.js` (`HeaderRow` + `HeaderTitle` + divider)
- **Composer input style:** `themes/default/routes/ViewPostView.js` (`StyledReply` textarea overrides)
- **Data hook (not modified):** `useChangeUsername` in `logic/useChangeUsername`

---

## Scope

### In scope
- Rewrite `themes/default/routes/ChangeUsernameView.js`.
- Settings-style header (`HeaderRow` / `HeaderTitle` / divider) with title "Edit Username".
- Centered title + description text below the header.
- Auth-slice primitives (`AuthPanel`, `AuthStack`, `AuthLabel`, `AuthHelperText`, `AuthErrorMessage`, `AuthButtonRow`) for form layout.
- Composer-matched input (`bg` background, `10px` radius, `borderStrong` hover/focus, `0.12s` transitions).
- Gradient `PrimaryButton` matching login/signup CTA.
- Amber `WarningPanel` for free-tier upgrade prompt.
- Themed success state with `voteUp` color + monospace handle.

### Out of scope
- `useChangeUsername` or any username-validation / submit logic.
- Backend username-change flow.

---

## What shipped

- **Header:** Settings-style `HeaderRow` with "Edit Username" title + `border` divider.
- **Content:** Centered `PageWrapper` (max-width 28 rem) with title "Change your username" and description "This is how users will find you on Mirage."
- **Input:** Composer-style `InputRow` — `bg` background, `10px` radius, `borderStrong` on hover/focus, `0.12s` transition.
- **Labels left-aligned:** "New username" label and "Letters, numbers, and hyphens only." helper text are left-aligned within the centered panel.
- **Error state:** `AuthErrorMessage` for submit errors.
- **Submit:** Gradient `PrimaryButton` with status text (Checking / Preparing / Submitting / Verifying).
- **Success:** Themed panel with `voteUp` check icon, monospace handle display, redirect subtext.
- **No oldreddit/bluemoon imports.**
- **Build passes:** `CI=true npm run build` clean.

---

## Verification checklist

- [x] `/change_username` renders with Settings-style header.
- [x] Auth-slice primitives used for form layout.
- [x] Input matches composer textarea style.
- [x] Validation + error states styled.
- [x] Dark + light modes work (tokens only, no hard-coded colors outside R2 pairs).
- [x] No `themes/oldreddit/*` or `themes/bluemoon/*` imports.
- [x] Build passes:

```bash
cd web/frontend
CI=true npm run build
```

---

## PR description template

> Rewrites `default`'s `ChangeUsernameView` with a Settings-style header ("Edit Username"), centered title/description, auth-slice panel primitives, and composer-matched input styling. Visual only — `useChangeUsername` unchanged.
