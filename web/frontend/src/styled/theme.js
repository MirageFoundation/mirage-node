/**
 * Theme Registry
 *
 * Each theme lives under src/themes/<name>/ and exports a manifest from
 * index.js containing: id, label, dark/light tokens, Shell, Feed,
 * VoteSection, and a config object for structural behavior.
 *
 * HOW TO ADD A NEW THEME:
 * 1. Create src/themes/<name>/ with index.js, tokens.js, Shell, Feed, etc.
 * 2. index.js default-exports a manifest (see moon/index.js for shape)
 * 3. Import the manifest below and add it to the manifests array
 * 4. Done -- no other files need changes
 */

import moonManifest from '../themes/moon/index';
import oldredditManifest from '../themes/oldreddit/index';

const manifests = [moonManifest, oldredditManifest];

export const THEMES = {};
manifests.forEach((m) => { THEMES[m.id] = m; });

/**
 * Resolve a concrete theme object from a family id and a resolved variant.
 * @param {string} themeId   - 'moon' | 'oldreddit' | ...
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
    return family;
}

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
