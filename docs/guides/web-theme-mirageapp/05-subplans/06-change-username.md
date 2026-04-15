# Sub-Plan 05.5 — Change Username

**Route:** `/change_username`
**File:** `web/frontend/src/themes/mirageapp/routes/ChangeUsernameView.js`
**Status:** ✅ Done
**Parent:** [`../05-inbox-search-settings-auth.md`](../05-inbox-search-settings-auth.md)

---

## Goal

Rewrite `mirageapp`'s `ChangeUsernameView` as a focused, panel-styled form that reuses the auth-slice `AuthPageShell` primitives and matches the onboarding redesign.

---

## References

- **Mobile:** `app/(auth)/username.tsx`
- **Web (structure):** `web/frontend/src/themes/oldreddit/routes/ChangeUsernameView.js`
- **Auth shell (reuse):** `themes/mirageapp/components/AuthPageShell.js` (from commit `ceef3d7`)
- **Data hook (do not modify):** `useChangeUsername` (verify exact path)

---

## Scope

### In scope
- Rewrite `themes/mirageapp/routes/ChangeUsernameView.js`.
- Reuse `AuthPageShell` and header primitives (`Header`, `BrandMark`, `Eyebrow`, `AuthTitle`) from the auth slice.

### Out of scope
- `useChangeUsername` or any username-validation / submit logic.
- Backend username-change flow.

---

## Requirements

- **Centered card** on desktop, **full-bleed** on mobile (reuse auth shell pattern).
- Panel container with mobile tokens.
- Clear **current username** display + **new username** input.
- Validation feedback (too short, taken, invalid chars) styled consistently with auth slice.
- Submit button uses theme's `Button` primary variant.
- Cancel / back action returns to previous screen.
- Preserve existing behavior — do not touch `useChangeUsername`.
- Dark + light modes both work.
- No `themes/oldreddit/*` imports inside the new file.

---

## Suggested implementation steps

1. Read `themes/oldreddit/routes/ChangeUsernameView.js` for hook wiring + current UI.
2. Read `themes/mirageapp/routes/LoginView.js` or `CreateAccountView.js` for `AuthPageShell` usage pattern.
3. Read mobile `app/(auth)/username.tsx` for tone + layout cues.
4. Copy auth-slice structure into `themes/mirageapp/routes/ChangeUsernameView.js`.
5. Wrap in `AuthPageShell` with appropriate header/eyebrow.
6. Wire input + validation states.
7. Verify submit flow unchanged.
8. Build + manual smoke test.

---

## Verification checklist

- [ ] `/change_username` renders and behaves like the current theme.
- [ ] Uses `AuthPageShell` from the auth slice.
- [ ] Validation + error states styled.
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

> Rewrites `mirageapp`'s `ChangeUsernameView` to reuse the auth slice's `AuthPageShell` primitives, giving the username change flow visual parity with login/signup. Visual only — `useChangeUsername` unchanged.
