/**
 * Theme registry — resolve manifests, routes, components, tokens by theme id.
 *
 * @see ../themes/manifests.js — import manifests there only; this file builds lookups + helpers.
 */

import { THEME_MANIFESTS } from '../themes/manifests';

export const THEMES = {};
THEME_MANIFESTS.forEach((m) => { THEMES[m.id] = m; });

/** Cross-app entrypoints resolved via `useThemeComponent` from `App` / `Tooltip` facades only. */
export const REQUIRED_THEME_COMPONENT_KEYS = Object.freeze([
    'Toast',
    'UnlockPrompt',
    'Tooltip',
    'InfoIcon',
    'tooltipStyles',
]);

(function assertRequiredThemeComponents() {
    for (const m of THEME_MANIFESTS) {
        const map = m.components || {};
        for (const key of REQUIRED_THEME_COMPONENT_KEYS) {
            if (!map[key]) {
                throw new Error(`Theme "${m.id}" manifest must register components["${key}"]`);
            }
        }
    }
}());

/**
 * Default theme when storage is missing, invalid, or an unknown id.
 *
 * ============================================================================
 * HARD FAIL RULE — READ THIS BEFORE CHANGING ANYTHING BELOW.
 * ============================================================================
 *
 * 1. The default theme is ALWAYS `default`. No exceptions. No "pick the
 *    first manifest", no env-var override, no A/B flag, no user-id-based
 *    gating. If you think you need to change this, talk to nik first.
 *
 *    History: the default was `bluemoon` until 2026-04-25. Per nik's call,
 *    `default` is now the single shipped theme experience for every user,
 *    and `normalizeThemeId` below force-overrides any persisted selection
 *    (see point 4). The other theme manifests (`bluemoon`, `onyx`,
 *    `oldreddit`) are kept in the registry only so that legacy `theme_id`
 *    values don't blow up `getThemeFamily` calls during migration; they are
 *    intentionally NOT reachable as a runtime visual.
 *
 * 2. If `default` is not registered in `THEME_MANIFESTS`, THIS MODULE MUST
 *    THROW at import time. Do NOT fall back to another theme. Do NOT default
 *    to `THEME_MANIFESTS[0]`. A missing `default` manifest is a build-time
 *    bug and must surface immediately — silent fallbacks hide regressions and
 *    have burned us before.
 *
 * 3. No fallbacks anywhere in this file. Per `RULES.md` → "Do not use
 *    fallbacks. Fail hard." This export is the single source of truth for
 *    every caller (`normalizeThemeId`, storage migration, App bootstrap);
 *    one silent fallback here cascades into every surface.
 *
 * 4. `normalizeThemeId` ALWAYS returns `DEFAULT_THEME_ID` regardless of the
 *    persisted value. This deliberately overrides any user-selected theme
 *    that was saved in localStorage before this rule landed. The settings
 *    UI's theme dropdown is now visual-only: any change there is mapped
 *    back to `default` on the next normalization pass and the storage
 *    value is rewritten by the App / bootstrap rewrite logic.
 *
 * If you are adding a new theme, add it to `themes/manifests.js` and leave
 * THIS line alone. The default does not change when new themes ship.
 * ============================================================================
 */
if (!THEMES.default) {
    throw new Error('DEFAULT_THEME_ID: "default" manifest is missing from THEME_MANIFESTS — the default theme must always be default; no fallback is permitted.');
}
export const DEFAULT_THEME_ID = 'default';

/**
 * Map legacy ids and unknown values to a registered theme id.
 * Falls back to DEFAULT_THEME_ID for missing/unknown values.
 * @param {unknown} id
 * @returns {string}
 */
export function normalizeThemeId(_id) {
    // Other families are unregistered. Any persisted theme_id is rewritten
    // to default so a leftover `onyx` / `bluemoon` / `oldreddit` value
    // cannot reach getThemeFamily and blow up first paint.
    return DEFAULT_THEME_ID;
}

/**
 * Resolve a concrete theme object from a family id and a resolved variant.
 * @param {string} themeId   - any registered manifest id (see themes/manifests.js)
 * @param {string} themeMode - Already resolved to 'dark' or 'light'
 */
export function getResolvedTheme({ themeId, themeMode }) {
    const family = THEMES[themeId];
    if (!family) {
        throw new Error(`Unknown theme: ${themeId}`);
    }
    if (themeMode !== 'light' && themeMode !== 'dark') {
        throw new Error(`Unknown theme mode: ${themeMode}`);
    }
    const base = family[themeMode];
    const config = family.config || {};
    const layout = base.layout || {};
    return {
        ...base,
        caps: {
            ...config,
            flatMode: layout.flatMode,
            inboxFullWidth: layout.inboxFullWidth,
            profilePostsFullWidth: layout.profilePostsFullWidth,
        },
    };
}

/**
 * Return the theme family metadata + config for a given id.
 */
export function getThemeFamily(themeId) {
    const family = THEMES[themeId];
    if (!family) {
        throw new Error(`Unknown theme: ${themeId}`);
    }
    if (!family.Style) {
        throw new Error(`Theme "${themeId}" manifest must export Style`);
    }
    return family;
}

/**
 * Resolve a **themed** UI component by logical name. Implementations live only under
 * `src/themes/<themeId>/components/` and are registered on the manifest `components` map.
 * This registry function is shared logic; it does not render or style anything.
 *
 * @param {string} themeId — registered manifest id
 * @param {string} key — logical name; must exist if registered (see REQUIRED_THEME_COMPONENT_KEYS for globals).
 */
export function getThemeComponent(themeId, key) {
    const family = THEMES[themeId];
    if (!family) {
        console.debug('[theme] missing theme family', { themeId, key });
        throw new Error(`Unknown theme: ${themeId}`);
    }
    const component = family.components && family.components[key];
    if (!component) {
        console.debug('[theme] missing component', { themeId, key });
        throw new Error(`Missing component "${key}" for theme "${themeId}"`);
    }
    return component;
}

/**
 * Same as getThemeComponent but takes the resolved theme object from ThemeProvider.
 * Used where `useTheme()` is already available (e.g. tooltipStyles helper).
 */
export function getThemeComponentFromTheme(theme, key) {
    if (!theme || !theme.themeId) {
        throw new Error('Theme object missing themeId');
    }
    return getThemeComponent(theme.themeId, key);
}

export function getThemeRoute(themeId, key) {
    const family = THEMES[themeId];
    if (!family) {
        console.debug('[theme] missing theme family', { themeId, key });
        throw new Error(`Unknown theme: ${themeId}`);
    }
    const route = family.routes && family.routes[key];
    if (!route) {
        console.debug('[theme] missing route', { themeId, key });
        throw new Error(`Missing route "${key}" for theme "${themeId}"`);
    }
    return route;
}
