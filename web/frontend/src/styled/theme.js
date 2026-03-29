/**
 * Theme Registry
 *
 * Each theme lives under src/themes/<themeId>/ and exports a manifest from
 * index.js. Visuals are theme-only: each manifest must export Style
 * (from themes/<id>/Style.js — html/body rules for that theme only), Shell, Feed, VoteSection,
 * dark/light tokens, and config. Shared code here is registry + getResolvedTheme only.
 *
 * HOW TO ADD A NEW THEME:
 * 1. Create src/themes/<name>/ with index.js, tokens.js, Style.js,
 *    Layout.js (styled primitives for that theme), Shell, Feed, etc.
 * 2. index.js default-exports a manifest (see themes/bluemoon/index.js for shape);
 *    Style is required.
 * 3. Import the manifest below and add it to the manifests array
 * 4. Done -- no other files need changes
 */

import bluemoonManifest from '../themes/bluemoon/index';
import oldredditManifest from '../themes/oldreddit/index';

const manifests = [bluemoonManifest, oldredditManifest];

export const THEMES = {};
manifests.forEach((m) => { THEMES[m.id] = m; });

/** Default when storage is missing, invalid, or an unknown id. */
export const DEFAULT_THEME_ID = 'bluemoon';

/**
 * Map legacy ids and unknown values to a registered theme id. Persists corrected values via callers.
 * @param {unknown} id
 * @returns {string}
 */
export function normalizeThemeId(id) {
    if (id == null || typeof id !== 'string') return DEFAULT_THEME_ID;
    const t = id.trim();
    if (t === 'moon') return 'bluemoon';
    if (THEMES[t]) return t;
    return DEFAULT_THEME_ID;
}

/**
 * Resolve a concrete theme object from a family id and a resolved variant.
 * @param {string} themeId   - 'bluemoon' | 'oldreddit' | ...
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
 * @param {string} themeId — e.g. 'bluemoon' | 'oldreddit'
 * @param {string} key — e.g. 'Button', 'Toast' (must exist on that theme's manifest)
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
