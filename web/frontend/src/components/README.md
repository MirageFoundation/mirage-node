# `src/components`

This directory contains the stable global entry points imported by `App.js`
and shared logic:

- `Toast.js`
- `UnlockPrompt.js`
- `Tooltip.js`

Their implementations live in `src/themes/default/components/` and resolve
through the default manifest. `REQUIRED_THEME_COMPONENT_KEYS` in
`src/registry/theme.js` enforces the required registrations at startup.

Route-specific UI should import components from `src/themes/default/components/`
directly. Route screens live in `src/themes/default/routes/`.
