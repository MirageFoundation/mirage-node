/**
 * Theme route facade — see ./README.md. Renders the active theme's StatsView; no CSS here.
 */
import React from 'react';
import { useThemeRoute } from '../logic/useThemeRoute';

export default function StatsView(props) {
    const Route = useThemeRoute('StatsView');
    return <Route {...props} />;
}
