/**
 * Theme route facade — see ./README.md. Renders the active theme's MainView; no CSS here.
 */
import React from 'react';
import { useThemeRoute } from '../logic/useThemeRoute';

export default function MainView(props) {
    const Route = useThemeRoute('MainView');
    return <Route {...props} />;
}
