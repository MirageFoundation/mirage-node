# `src/views` — theme route facades (not the real pages)

## Why this folder exists

`App.js` lazy-loads **`src/views/<Name>.js`** with stable paths. Each file is a **thin wrapper**: it calls `useThemeRoute('<Name>')` and renders whatever the **active theme** registered on its manifest’s **`routes`** map.

**Real screens** (layout, copy, styled-components) live under **`src/themes/<themeId>/routes/`** — e.g. `themes/bluemoon/routes/MainView.js` vs `themes/oldreddit/routes/MainView.js`.

## Mental model

```
App (lazy import)
    import('./views/MainView')
         │
         ▼
    views/MainView.js                    ← facade (few lines)
         │
         ▼
    useThemeRoute('MainView')
         │
         ▼
    getThemeRoute(themeId, 'MainView')
         │
         ▼
    themes/bluemoon/index.js   →  routes: { MainView: …, … }
    themes/oldreddit/...     →  routes: { MainView: …, … }
```

Switching **theme** swaps the resolved page component **without** changing `App`’s import paths.

## Related

- **`src/components/README.md`** — global **`Toast` / `UnlockPrompt` / `Tooltip`**; all other UI lives under **`themes/*/components`**.
