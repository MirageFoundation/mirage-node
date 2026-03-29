# `src/components` — a few global entrypoints only

## Where themed UI actually lives

**All real UI** for each look is under **`src/themes/<themeId>/components/`** and **`routes/`**. Themes are **not** skins: each manifest can define **any** structure and styling; only **backend/chain behavior** stays in **`logic/`** and **`utils/`**.

Theme routes import theme-local paths, e.g. `themes/bluemoon/routes/MainView.js` → `../components/Button.js`.

Each theme’s **`index.js`** registers **`components`** on the manifest (see **`themes/manifests.js`**). Hooks use **`useThemeComponent('Button')`** / **`getThemeComponent(themeId, key)`** (`src/styled/theme.js`) when something outside a themed subtree must resolve by name.

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
