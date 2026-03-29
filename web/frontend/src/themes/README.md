# `src/themes` — full UI families (not skins)

## Boundary

- **Themes** own **whatever presentation you want**: layout, typography, navigation, page structure, styled-components, per-route screens under `routes/`, shared pieces under `components/`, document CSS in `Style.js`, tokens, Shell, Feed, etc.
- **Not in themes**: cross-cutting **behavior** that talks to the chain/backend, crypto, storage helpers, and route-level **data** hooks — that lives in **`src/logic/`**, **`src/utils/`** (e.g. `api`, `tx`, `Storage`), and thin **`src/views/`** wrappers that only delegate to `useThemeRoute`.

Each theme is a **separate implementation** registered on the manifest; switching `theme_id` swaps that entire tree, not a color preset.

## Registering a theme (single checklist)

1. Add a folder **`themes/<id>/`** with a default-exported **manifest** from **`index.js`** (see `bluemoon` / `oldreddit`).
2. **Import that manifest in `manifests.js`** and append it to **`THEME_MANIFESTS`** (only file that lists installed themes).
3. If you **rename** a theme id and users may still have the old value in `localStorage`, add a mapping in **`LEGACY_THEME_IDS`** in the same file.

**Default theme** for missing/invalid storage: **`THEME_MANIFESTS[0]`** — keep your preferred default first in the array.

Registry resolution (`getThemeComponent`, `getThemeRoute`, `getResolvedTheme`) is in **`src/styled/theme.js`**.

## Pre-React `data-theme-id`

**`src/bootstrapTheme.js`** runs before React (imported first from **`index.js`**) and sets **`document.documentElement`** using the same **`normalizeThemeId`** rules — no duplicate theme lists in **`public/index.html`**.
