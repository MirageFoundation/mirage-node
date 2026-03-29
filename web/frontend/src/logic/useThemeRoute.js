import { useTheme } from 'styled-components';
import { getThemeRoute } from '../styled/theme';

export function useThemeRoute(key) {
    const theme = useTheme();
    return getThemeRoute(theme.themeId, key);
}
