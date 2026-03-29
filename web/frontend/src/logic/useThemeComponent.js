import { useTheme } from 'styled-components';
import { getThemeComponent } from '../styled/theme';

export function useThemeComponent(key) {
    const theme = useTheme();
    return getThemeComponent(theme.themeId, key);
}
