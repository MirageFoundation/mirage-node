/**
 * Theme route facade — see ./README.md. Renders the active theme's WelcomeView; no CSS here.
 */
import React from 'react';
import { useThemeRoute } from '../logic/useThemeRoute';

export default function WelcomeView(props) {
    const Route = useThemeRoute('WelcomeView');
    return <Route {...props} />;
}
