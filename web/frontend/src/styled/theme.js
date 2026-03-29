/**
 * Theme Registry
 *
 * Central source of truth for all theme families. Each family defines
 * dark and light token sets (colors, layout, caps) plus metadata.
 *
 * Components access tokens via theme.colors.*, theme.layout.*, and
 * theme.caps.* from styled-components ThemeProvider. No component should
 * ever check theme.themeId to alter styling or behavior -- use tokens.
 *
 * HOW TO ADD A NEW THEME:
 * 1. Create src/themes/<name>/ with tokens.js, Shell.js, FeedView.js
 * 2. tokens.js exports { dark, light, caps } with colors + layout + caps
 * 3. Register an entry in THEMES below
 * 4. Done -- zero other files need changes
 */

import * as moonTokens from '../themes/moon/tokens';
import * as oldredditTokens from '../themes/oldreddit/tokens';
import MoonShell from '../themes/moon/MoonShell';
import OldRedditShell from '../themes/oldreddit/OldRedditShell';
import MoonFeedView from '../themes/moon/MoonFeedView';
import ListFeedView from '../themes/oldreddit/ListFeedView';

// ---------------------------------------------------------------------------
// Registry
// ---------------------------------------------------------------------------

export const THEMES = {
    moon: {
        id: 'moon',
        label: 'Moon',
        description: 'Modern card-based feed',
        supportsDarkLight: true,
        dark: moonTokens.dark,
        light: moonTokens.light,
        Shell: MoonShell,
        Feed: MoonFeedView,
    },
    oldreddit: {
        id: 'oldreddit',
        label: 'Classic',
        description: 'Compact list-based feed (old Reddit style)',
        supportsDarkLight: true,
        dark: oldredditTokens.dark,
        light: oldredditTokens.light,
        Shell: OldRedditShell,
        Feed: ListFeedView,
    },
};

/**
 * Resolve a concrete theme object from a family id and a resolved variant.
 * @param {string} themeId   - 'moon' | 'oldreddit' | ...
 * @param {string} themeMode - Already resolved to 'dark' or 'light'
 */
export function getResolvedTheme({ themeId, themeMode }) {
    const family = THEMES[themeId] || THEMES.moon;
    return family[themeMode === 'light' ? 'light' : 'dark'];
}

/**
 * Return the theme family metadata for a given id.
 */
export function getThemeFamily(themeId) {
    return THEMES[themeId] || THEMES.moon;
}
