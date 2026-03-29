/**
 * useThemeComponent — resolve a themed implementation by manifest key
 *
 * Theme routes import **`themes/<id>/components/...`** directly. A few globals (`Toast`,
 * `UnlockPrompt`, `Tooltip` in `src/components/`) use this hook with a string key. The hook
 * reads `theme.themeId` from styled-components' ThemeProvider and returns the component
 * registered on that theme's manifest under `components[key]` (manifests listed in `themes/manifests.js`).
 *
 * @see ../components/README.md
 * @see ../registry/theme.js — getThemeComponent
 */
import { useTheme } from 'styled-components';
import { getThemeComponent } from '../registry/theme';

/**
 * @param {string} key — must be registered on the manifest when used (see REQUIRED_THEME_COMPONENT_KEYS in registry/theme.js for App-level globals)
 * @returns {React.ComponentType}
 */
export function useThemeComponent(key) {
    const theme = useTheme();
    return getThemeComponent(theme.themeId, key);
}
