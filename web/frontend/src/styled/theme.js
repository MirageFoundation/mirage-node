/**
 * Theme Registry
 *
 * Central source of truth for all theme families. Each family defines
 * dark and light token sets plus metadata (label, description, capabilities).
 *
 * Components continue to access tokens via `theme.colors.xxx` from
 * styled-components ThemeProvider. The fallback modules in colors/dark.js
 * and colors/light.js are still used by pickThemeColor in components that
 * need extended tokens not present in the base set.
 *
 * HOW TO ADD A NEW THEME:
 * 1. Define dark + light token objects (same shape as moonDark/moonLight).
 *    Required fields: name ('dark'|'light'), themeId (your id string), colors.
 *    Optional: fontFamily (defaults to Noto Sans via GlobalStyle).
 * 2. Create a shell component in src/shells/ (can copy MoonShell as a base).
 * 3. Create a feed component (MoonFeedView/ListFeedView-style) for that theme.
 * 4. Add an entry to THEMES below with id, label, description,
 *    supportsDarkLight, dark, light, Shell, and Feed.
 * 5. No other files need changes -- the registry, App.js, and SettingsView
 *    discover new themes automatically.
 */

import MoonShell from '../shells/MoonShell';
import OldRedditShell from '../shells/OldRedditShell';
import MoonFeedView from '../components/MoonFeedView';
import ListFeedView from '../components/ListFeedView';

// ---------------------------------------------------------------------------
// Moon theme - current Mirage look
// These values are the exact tokens that App.js previously passed to
// ThemeProvider. Changing them would change the rendered UI.
// ---------------------------------------------------------------------------

const moonDark = {
    name: 'dark',
    themeId: 'moon',
    colors: {
        bg: '#1A1A1A',
        text: '#FFFFFF',
        subtleText: '#CCCCCC',
        panel: '#23272C',
        panelAlt: '#33373C',
        border: '#444',
        accent: '#2E3238',
        accentHover: '#3A3F46',
        accentDisabled: '#4A4F55',
        buttonText: '#FFFFFF',
        link: '#FFFFFF',
        linkHover: '#CCCCCC',
        scrollbar: '#CCCCCC',
        cardShadow: 'none',
        cardShadowHover: 'none',
    },
};

const moonLight = {
    name: 'light',
    themeId: 'moon',
    colors: {
        bg: '#FFFFFF',
        text: '#111827',
        subtleText: '#4B5563',
        panel: '#F7F7F8',
        panelAlt: '#EFEFF1',
        border: '#D1D5DB',
        accent: '#E5E7EB',
        accentHover: '#D1D5DB',
        accentDisabled: '#F3F4F6',
        buttonText: '#111827',
        link: '#111827',
        linkHover: '#374151',
        scrollbar: '#9CA3AF',
        cardShadow: '0 4px 12px rgba(0, 0, 0, 0.1)',
        cardShadowHover: '0 6px 20px rgba(0, 0, 0, 0.15)',
    },
};

// ---------------------------------------------------------------------------
// Old Reddit theme - compact list-based feed, dense information layout
// Verdana/system sans-serif, tight spacing, no card shadows, text links
// ---------------------------------------------------------------------------

const oldredditDark = {
    name: 'dark',
    themeId: 'oldreddit',
    fontFamily: "Verdana, Geneva, 'DejaVu Sans', sans-serif",
    colors: {
        bg: '#1a1a1b',
        text: '#d7dadc',
        subtleText: '#818384',
        panel: '#1a1a1b',
        panelAlt: '#272729',
        border: '#343536',
        accent: '#272729',
        accentHover: '#3a3a3c',
        accentDisabled: '#3a3a3c',
        buttonText: '#d7dadc',
        link: '#4fbcff',
        linkHover: '#7fcfff',
        scrollbar: '#4a4a4c',
        card: '#1a1a1b',
        cardAlt: '#222224',
        cardBorder: '#343536',
        sidebarBg: '#1a1a1b',
        headerBg: '#1a1a1b',
        voteUp: '#ff4500',
        voteUpHover: '#ff5722',
        voteUpBg: 'rgba(255, 69, 0, 0.15)',
        voteDown: '#7193ff',
        voteDownHover: '#5a7cff',
        voteDownBg: 'rgba(113, 147, 255, 0.15)',
        cardShadow: 'none',
        cardShadowHover: 'none',
    },
};

const oldredditLight = {
    name: 'light',
    themeId: 'oldreddit',
    fontFamily: "Verdana, Geneva, 'DejaVu Sans', sans-serif",
    colors: {
        bg: '#dae0e6',
        text: '#1c1c1c',
        subtleText: '#7c7c7c',
        panel: '#ffffff',
        panelAlt: '#f6f7f8',
        border: '#ccc',
        accent: '#f6f7f8',
        accentHover: '#e8e8e8',
        accentDisabled: '#eee',
        buttonText: '#1c1c1c',
        link: '#0079d3',
        linkHover: '#0059a3',
        scrollbar: '#c1c1c1',
        card: '#ffffff',
        cardAlt: '#f6f7f8',
        cardBorder: '#ccc',
        sidebarBg: '#ffffff',
        headerBg: '#f6f7f8',
        voteUp: '#ff4500',
        voteUpHover: '#cc3700',
        voteUpBg: 'rgba(255, 69, 0, 0.1)',
        voteDown: '#7193ff',
        voteDownHover: '#4a6cff',
        voteDownBg: 'rgba(113, 147, 255, 0.1)',
        cardShadow: 'none',
        cardShadowHover: 'none',
    },
};

// ---------------------------------------------------------------------------
// Registry
// ---------------------------------------------------------------------------

export const THEMES = {
    moon: {
        id: 'moon',
        label: 'Moon',
        description: 'Modern card-based feed',
        supportsDarkLight: true,
        dark: moonDark,
        light: moonLight,
        Shell: MoonShell,
        Feed: MoonFeedView,
    },
    oldreddit: {
        id: 'oldreddit',
        label: 'Classic',
        description: 'Compact list-based feed (old Reddit style)',
        supportsDarkLight: true,
        dark: oldredditDark,
        light: oldredditLight,
        Shell: OldRedditShell,
        Feed: ListFeedView,
    },
};

/**
 * Resolve a concrete theme object from a family id and a resolved variant.
 * @param {string} themeId   - 'moon' | 'oldreddit' | ...
 * @param {string} themeMode - Already resolved to 'dark' or 'light'
 *                             (not 'system' or 'time' — resolve those first).
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
