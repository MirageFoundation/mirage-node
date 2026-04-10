# Plan 01 — Theme Skeleton & Tokens

**Goal:** Register a new `mirageapp` theme that is selectable from Settings, renders every route without crashing, and uses visual tokens ported from `mirage-mobile-app`. No final visuals yet — this plan just establishes the foundation.

**Depends on:** nothing. This is the first PR.
**Unblocks:** Plans 02–06.

---

## Scope

### In scope
- Create `web/frontend/src/themes/mirageapp/` with a complete, valid manifest.
- Port color/spacing/radius/typography tokens from the mobile app.
- Register the theme in `themes/manifests.js`.
- Ensure the theme builds and every route facade resolves (routes may still look like `oldreddit` visually at this stage).
- Implement `Style.js` with base body, link, scrollbar, and form element styling using the new tokens.

### Out of scope
- Top nav / sidebar redesign — that is Plan 02.
- Feed and card redesign — that is Plan 03.
- Post detail / profile rework — Plan 04.
- Inbox / search / settings / auth rework — Plan 05.

---

## Starting base

Copy the full `web/frontend/src/themes/oldreddit/` folder to `web/frontend/src/themes/mirageapp/`. Then:

- Rename the default-exported manifest variable to `mirageappManifest`.
- Change `id: 'oldreddit'` → `id: 'mirageapp'`.
- Change `label` and `description` to something like:
  - `label: 'Mirage App'`
  - `description: 'Mobile-app visuals on a Reddit-style desktop layout'`
- Update every `themeId` string inside `tokens.js` (`dark` / `light`) to `'mirageapp'`.
- Rename the shell file (for example `MirageAppShell.js`) and update the import in `index.js`.
- Make sure **all imports inside the new folder** point to theme-local paths (nothing should import from `themes/oldreddit/...`).

---

## Files to create or change

### Create
```
web/frontend/src/themes/mirageapp/
  index.js
  tokens.js
  Style.js
  MirageAppShell.js
  Layout.js
  ListFeedView.js                 (renamed as needed; used as manifest Feed for now)
  components/                     (copied from oldreddit/components and renamed where appropriate)
  routes/                         (copied from oldreddit/routes; imports updated)
  utils/                          (if oldreddit has one)
```

### Edit
- `web/frontend/src/themes/manifests.js`
  - Import `mirageappManifest` from `./mirageapp/index`.
  - Append it to `THEME_MANIFESTS`.
  - **Do not** move it to index 0 yet (so it never becomes the default until the work is done).

---

## Token port from `mirage-mobile-app`

### Inputs
- `mirage-mobile-app/src/config/theme.ts`
- `mirage-mobile-app/src/config/sizing.ts`

### Colors to map (dark + light) in `themes/mirageapp/tokens.js`
Use this mapping as the starting point:

| Mobile key | Web token field(s) |
|---|---|
| `base.primary` | `colors.text`, primary accent where appropriate |
| `surfaces.background` | `colors.bg`, base background |
| `surfaces.border` (adjusted) | `colors.border`, `colors.borderSubtle` |
| `text.default` | `colors.text` |
| neutral / muted derived | `colors.subtleText`, `colors.muted` |
| `base.brand` | link/active states |
| `base.success` / `warning` / `error` | `colors.success` / `warning` / `danger` (+ bg variants) |
| card surfaces | `colors.card`, `colors.panel`, `colors.panelAlt` |

Derive soft backgrounds (`successBg`, `warningBg`, `dangerBg`) as low-alpha versions of the base color, matching the look in existing themes.

### Spacing / radius / typography
Mirror the mobile scales in `tokens.js` or `Layout.js` so they are reusable inside the theme:

```js
// pseudo-code, values straight from sizing.ts
const spacing = { none:0, xs:4, sm:8, md:16, lg:24, xl:32, xxl:40 };
const radius  = { none:0, sm:4, md:8, lg:12, xl:16, xxl:20, full:9999 };
const fontSize = { xs:10, sm:12, md:14, lg:16, xl:18, xxl:20, mega:24 };
```

Expose these as part of the resolved theme so styled-components in this theme can use them (for example `theme.layout.spacingMd`, or a dedicated `theme.scale.*` group — keep the naming consistent with the existing theme layout object shape).

### Style.js
Set base document styling using the new tokens:
- `body { background, color, font-family }`
- links
- scrollbar
- form defaults (input/textarea/select) so downstream components inherit the mobile look

---

## Verification checklist

- [ ] `web/frontend/src/themes/manifests.js` imports and registers `mirageappManifest`.
- [ ] The theme appears in the Settings theme picker (existing code iterates `THEMES`).
- [ ] Switching to `mirageapp` renders every route without the registry throwing (required component keys present, all routes implemented).
- [ ] Dark and light both render without missing-token crashes (`requireThemeColor` throws on missing keys).
- [ ] Base body/link/scrollbar styling reflects mobile tokens.
- [ ] Build passes:

```bash
cd web/frontend
CI=true npm run build
```

---

## Risks & mitigations

- **Missing `REQUIRED_THEME_COMPONENT_KEYS`** → copy from `oldreddit` first; the registry throws at load time if anything is missing.
- **Token drift between dark and light** → keep the same key set in both and only change values.
- **Cross-theme imports slipping in** → grep inside `themes/mirageapp` for `themes/oldreddit` and remove any leftover references.

---

## PR description template

> Adds a new `mirageapp` web theme scaffold cloned from `oldreddit` with tokens ported from `mirage-mobile-app`. Registered in the theme manifest but not set as default. No visual layout changes yet — follow-up PRs will replace shell, nav, feed, and routes.
