# Sub-Plan 05.6 — Sign Out

**Route:** `/sign_out`
**File:** `web/frontend/src/themes/mirageapp/routes/SignOutView.js`
**Status:** ✅ Done
**Parent:** [`../05-inbox-search-settings-auth.md`](../05-inbox-search-settings-auth.md)

---

## Goal

Rewrite `mirageapp`'s `SignOutView` as a short confirmation screen that reuses the auth-slice `AuthPageShell` primitives, so the sign-out flow feels intentional and on-brand.

---

## References

- **Web (structure):** `web/frontend/src/themes/oldreddit/routes/SignOutView.js`
- **Auth shell (reuse):** `themes/mirageapp/components/AuthPageShell.js` (from commit `ceef3d7`)
- **Data hook (do not modify):** sign-out handler from existing theme (verify exact import)

---

## Scope

### In scope
- Rewrite `themes/mirageapp/routes/SignOutView.js`.
- Reuse `AuthPageShell` and header primitives from the auth slice.

### Out of scope
- Sign-out handler logic or session clearing.
- Seed vault behavior.

---

## Requirements

- **Centered card** on desktop, **full-bleed** on mobile.
- Clear confirmation message + short warning about what happens on sign out.
- **Primary destructive button** (Sign Out) + **secondary cancel** using theme `Button` variants.
- Redirects correctly after successful sign-out (behavior unchanged).
- Preserve existing behavior — do not modify handler or session logic.
- Dark + light modes both work.
- No `themes/oldreddit/*` imports inside the new file.

---

## Suggested implementation steps

1. Read `themes/oldreddit/routes/SignOutView.js` for handler wiring + current UI.
2. Read `themes/mirageapp/routes/LoginView.js` for `AuthPageShell` usage.
3. Copy auth-slice structure into `themes/mirageapp/routes/SignOutView.js`.
4. Wrap in `AuthPageShell` with confirmation copy.
5. Add primary destructive button + secondary cancel.
6. Verify sign-out flow and redirect unchanged.
7. Build + manual smoke test.

---

## Verification checklist

- [ ] `/sign_out` renders and behaves like the current theme.
- [ ] Uses `AuthPageShell` from the auth slice.
- [ ] Destructive primary + cancel buttons styled.
- [ ] Sign-out handler + redirect unchanged.
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

> Rewrites `mirageapp`'s `SignOutView` as a focused confirmation screen using the auth slice's `AuthPageShell` primitives. Visual only — sign-out handler and session logic unchanged. **Closes Plan 05.**
