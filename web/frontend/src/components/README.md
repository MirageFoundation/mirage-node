# `src/components` — a few global shells only

## Where themed UI actually lives

**All real UI** for each look is under **`src/themes/<themeId>/components/`** (styled-components, tokens, layout). Theme routes import those files directly, e.g. `themes/bluemoon/routes/MainView.js` → `../components/Button.js` (theme-local path).

Each theme’s **`index.js`** registers implementations on the manifest’s **`components`** map. Shared hooks use **`useThemeComponent('Button')`** / **`getThemeComponent(themeId, key)`** (see `src/styled/theme.js`) so code that does not know the active theme can still resolve the right implementation.

## What stays in this folder

Only modules that **`App.js`** or cross-cutting **logic** import from a stable **`src/components/...`** path:

| File | Role |
|------|------|
| **`Toast.js`** | Global toast host; `useThemeComponent('Toast')`. |
| **`UnlockPrompt.js`** | Global unlock flow; `useThemeComponent('UnlockPrompt')`. |
| **`Tooltip.js`** | `forwardRef` + `getThemeComponentFromTheme` for tooltips and **`tooltipStyles`**; still theme-resolved. |

Everything else was removed: routes already depended on **`themes/.../components`**, not duplicate facades here.

## Related

- **`src/views/README.md`** — lazy route wrappers (`useThemeRoute`) for whole pages.
