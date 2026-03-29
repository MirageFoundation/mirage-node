/**
 * useThemeComponent — resolve a themed implementation by manifest key
 *
 * Theme routes import **`themes/<id>/components/...`** directly. A few globals (`Toast`,
 * `UnlockPrompt`, `Tooltip` in `src/components/`) use this hook with a string key. The hook
 * reads `theme.themeId` from styled-components' ThemeProvider and returns the component
 * registered on that theme's manifest under `components[key]`.
 *
 * @see ../components/README.md
 * @see ../styled/theme.js — getThemeComponent
 */
import { useTheme } from 'styled-components';
import { getThemeComponent } from '../styled/theme';

/**
 * @param {string} key — must match a key on `family.components` in the active theme manifest
 * @returns {React.ComponentType}
 */
export function useThemeComponent(key) {
    const theme = useTheme();
    return getThemeComponent(theme.themeId, key);
}
