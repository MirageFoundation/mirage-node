# `src/themes` — full UI families (not skins)

> **As of 2026-08-27:** only the **`default`** theme is registered.
> `normalizeThemeId` always returns `default`. The other families stay on
> disk under `themes/` but are not imported, so they are not in the bundle
> and do not need to stay in sync. To restore theming, add the manifests
> back to `themes/manifests.js` and re-add the picker UI.
>
> Until then: product UI feedback targets **`default`** only.

A **theme** is a complete visual and structural implementation: layout, typography, navigation, route screens, styled-components, global CSS (`Style`), tokens, shell, feed, and vote UI. Switching `theme_id` swaps that entire tree. Shared **behavior** (API, txs, crypto, storage) stays in **`src/logic/`**, **`src/utils/`**, and **`src/views/`** facades.

---

## 1. Architecture (mental model)

| Layer | Responsibility |
|--------|----------------|
| **`src/registry/theme.js`** | Builds lookups from **`manifests.js`**: `THEMES`, `normalizeThemeId`, `getResolvedTheme`, `getThemeFamily`, `getThemeRoute`, `getThemeComponent`. Asserts **required** manifest `components` at startup. |
| **`src/themes/manifests.js`** | **Only** place that lists installed themes (`THEME_MANIFESTS`) and legacy id aliases (`LEGACY_THEME_IDS`). |
| **`src/themes/<id>/index.js`** | Default export = **manifest** (metadata + `dark` / `light` + `Style` + `Shell` + `Feed` + `VoteSection` + `components` + `routes` + `config`). |
| **`src/views/<Route>.js`** | Thin wrappers: `useThemeRoute('<RouteName>')` → renders the active theme’s route component. **`App.js`** lazy-imports these; do not add routes only under `themes/` without a matching `views/` facade and `<Route>` in **`App.js`**. |
| **`src/logic/`** | Data hooks (`useMain`, `useProfile`, …). They must **not** own presentation; theme-specific layout choices belong in **`themes/<id>/routes/`** or tokens. |
| **`src/components/`** | Only global hosts that resolve implementations via **`useThemeComponent`** (`Toast`, `UnlockPrompt`, `Tooltip`). Implementations still live on each manifest. |

**Pre-React:** **`src/registry/bootstrapThemeId.js`** is imported first from **`src/index.js`**. It reads `Storage` `theme_id`, normalizes with **`normalizeThemeId`**, persists corrections, and sets **`document.documentElement.setAttribute('data-theme-id', id)`** so first paint can target `html[data-theme-id="…"]` (see **`public/index.html`**).

---

## 2. Registering a new theme (checklist)

1. **Create** `src/themes/<your-id>/` with a **default-exported manifest** from **`index.js`** (copy **`bluemoon`** or **`oldreddit`** as a template — see §4).
2. **Import** that manifest in **`src/themes/manifests.js`** and **append** it to **`THEME_MANIFESTS`**.
   - **`DEFAULT_THEME_ID`** is hard-coded to **`default`** in **`registry/theme.js`** (since 2026-04-25); manifest order in **`THEME_MANIFESTS`** does **not** determine the default. New themes are not auto-promoted to default.
3. If you **rename** a theme id and users may still have the old value in **`localStorage`**, add **`LEGACY_THEME_IDS: { oldId: 'newId' }`** in **`manifests.js`**.
4. Run **`CI=true npm run build`** in **`web/frontend`** — startup asserts **`REQUIRED_THEME_COMPONENT_KEYS`** on every manifest (§5).

No other “registration” files: **`registry/theme.js`** imports **`manifests.js`** only.

---

## 3. Manifest shape (required fields)

Default export is a plain object. Existing themes illustrate the full pattern; minimum contract:

| Field | Purpose |
|--------|---------|
| **`id`** | Stable string persisted as **`Storage` `theme_id`**. Must match **`dark.themeId`** / **`light.themeId`** in **`tokens.js`**. |
| **`label`** | Short user-facing name (settings UI). |
| **`description`** | Optional subtitle for choosers. |
| **`supportsDarkLight`** | If `true`, app toggles dark/light; both **`dark`** and **`light`** must exist. |
| **`dark`**, **`light`** | Objects passed into **`getResolvedTheme`**: must include **`themeId`**, **`colors`**, **`layout`**, and **`name`** (`'dark'` / `'light'`). See **`themes/bluemoon/tokens.js`**. |
| **`Style`** | React component (no props required) that injects global/theme CSS (styled-components or imports). **`getThemeFamily`** requires **`Style`** on the manifest. |
| **`Shell`** | Root layout wrapping **`App`**’s `<Routes>`; receives **`state={appState}`** from **`App`**. |
| **`Feed`** | Home/community/following feed component; resolved via **`getThemeFamily(themeId).Feed`** from **`MainView`** / **`useProfile`**. |
| **`VoteSection`** | Registered on manifest; **`CardView`** resolves **`getThemeFamily(themeId).VoteSection`**. |
| **`components`** | Map of string keys → React components. **Must** include every key in **`REQUIRED_THEME_COMPONENT_KEYS`** (§5). Optional keys are only needed if something calls **`useThemeComponent(key)`**. |
| **`routes`** | Map of **route facade names** → components. Keys must match **`useThemeRoute('…')`** in **`src/views/*.js`** (§6). |
| **`config`** | Family-specific flags merged into **`theme.caps`** (with **`layout.flatMode`**, **`layout.inboxFullWidth`**, **`layout.profilePostsFullWidth`**). Hooks read **`theme.caps`** (e.g. **`mapHomeSortMode`**, **`profileTabs`**, **`profileDefaultTab`**, **`profileUsesListFeed`**, **`profileHideFilterSelect`**, **`showHeroCards`**). Add only what your theme and shared hooks need. |

**Runtime theme object** (from **`styled-components` `ThemeProvider`**): **`getResolvedTheme({ themeId, themeMode })`** merges the selected **`dark`** or **`light`** token object with **`caps`** from **`config`** + layout flags. Use **`theme.colors`**, **`theme.layout`**, **`theme.caps`**, **`theme.themeId`** in styled-components and components.

**Colors:** Shared helpers like **`requireThemeColor(theme, key)`** (`src/utils/themeColor.js`) expect tokens on **`theme.colors`** — no silent fallbacks; missing keys throw.

---

## 4. Suggested folder layout (`themes/<id>/`)

```
themes/<id>/
  index.js          # manifest (default export)
  tokens.js         # export { dark, light } — set themeId to your manifest id
  Style.js          # global styles
  <Something>Shell.js
  <Something>FeedView.js   # or ListFeedView.js — referenced as Feed on manifest
  components/       # buttons, cards, tooltips, …
  routes/           # MainView, SettingsView, … — one file per view name in App
```

- **Copy** from **`bluemoon`** (card UI) or **`oldreddit`** (compact list) and rename imports/paths.
- **Search-and-replace** the **`themeId`** string inside **`tokens.js`** **`dark` / `light`** exports so it equals **`id`**.
- **Imports** inside a theme should stay **theme-local** (e.g. `../components/Button`), not cross-import another theme’s files.

---

## 5. Required `components` keys (enforced)

Defined in **`src/registry/theme.js`** as **`REQUIRED_THEME_COMPONENT_KEYS`**. Every manifest must register:

- **`Toast`**, **`UnlockPrompt`**, **`Tooltip`**, **`InfoIcon`**, **`tooltipStyles`**

Other keys (**`Button`**, **`CardView`**, **`Sidebar`**, …) are optional at registry level; they are required only if code calls **`getThemeComponent`** / **`useThemeComponent`** with that name. **`App`** uses the three global **`src/components`** facades, which delegate to these themed implementations.

If a theme does not use a component (e.g. no top bar), you may register a no-op component (see **`oldreddit`** **`NullComponent`** for **`MobileHeader`** / **`TopBar`** / **`Sidebar`**) **only** where something still resolves that key — prefer omitting optional keys if nothing asks for them.

---

## 6. `routes` map — must match `src/views/` and `App.js`

Each file under **`src/views/`** is a facade named **`X.js`** that calls **`useThemeRoute('X')`**. Your manifest **`routes`** object must export a component for **every** such name the app uses.

As of this writing, manifests include at least:

`BlocksView`, `ChangeUsernameView`, `CreateAccountView`, `CreatePostView`, `DiscoverView`, `FollowsView`, `InboxView`, `LoginView`, `MainView`, `NetworkView`, `NotFoundView`, `ProfileView`, `ReportsView`, `SearchResultsView`, `SettingsView`, `SignOutView`, `StatsView`, `SubscriptionView`, `ViewPostView`, `WelcomeView`.

Adding a **new** top-level URL requires **`App.js`** `<Route>`, a **`src/views/NewThing.js`** facade, and **`routes.NewThing`** on **every** theme manifest.

---

## 7. Listing themes in the UI

Import **`THEMES`** from **`src/registry/theme.js`** (or iterate **`THEME_MANIFESTS`** from **`manifests.js`**) to build a theme picker: each entry has **`id`**, **`label`**, **`description`**, etc.

---

## 8. Verification

```bash
cd web/frontend && CI=true npm run build
```

Fix any ESLint issues (e.g. unused destructured props). Registry assertions run at bundle load — missing required **`components`** or **`Style`** throws immediately.

---

## 9. Related docs

- **`src/views/README.md`** — lazy route facades and **`useThemeRoute`**.
- **`src/components/README.md`** — global **`Toast` / `UnlockPrompt` / `Tooltip`** facades.
- **`src/registry/theme.js`** — **`REQUIRED_THEME_COMPONENT_KEYS`**, **`getResolvedTheme`**, **`getThemeRoute`**.
