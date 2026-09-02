# `src/themes`

Mirage ships one UI family: `default`.

The default family owns layout, typography, navigation, route screens,
styled-components, global CSS, tokens, the shell, feeds, and vote UI. Shared
behavior remains in `src/logic/` and `src/utils/`.

## Runtime structure

- `src/themes/default/index.js` exports the UI manifest.
- `src/themes/default/tokens.js` exports the dark and light token sets.
- `src/themes/default/DefaultShell.js` owns the root layout.
- `src/themes/default/components/` contains presentation components.
- `src/themes/default/routes/` contains route screens.
- `src/views/` contains lazy route facades used by `App.js`.
- `src/registry/theme.js` resolves the default manifest and validates its
  required component contract.
- `src/registry/bootstrapThemeId.js` normalizes old stored theme IDs to
  `default` before React starts.

Dark and light modes are token variants of the default UI, not separate themes.
Use `theme.colors`, `theme.layout`, and `theme.caps` in styled-components.
`requireThemeColor(theme, key)` fails when a required color token is missing.

## Adding routes or components

A top-level route requires an `App.js` route, a `src/views/<Route>.js` facade,
and the corresponding entry in the default manifest's `routes` map.

Global component facades resolve implementations from the default manifest.
The keys enforced by `REQUIRED_THEME_COMPONENT_KEYS` in `src/registry/theme.js`
must remain registered.

## Verification

```bash
cd web/frontend && CI=true npm run build
```
