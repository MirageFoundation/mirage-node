/**
 * Fail-fast access to styled-components theme color tokens. No global fallbacks.
 * @param {object} theme - Resolved theme from ThemeProvider
 * @param {string} key
 * @returns {string}
 */
export function requireThemeColor(theme, key) {
    const v = theme?.colors?.[key];
    if (v === undefined || v === null || v === '') {
        const id = theme?.themeId != null ? String(theme.themeId) : 'unknown';
        throw new Error(`Theme "${id}" missing color token "${key}"`);
    }
    return v;
}
