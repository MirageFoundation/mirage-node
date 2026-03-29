/**
 * Theme route facade — see ./README.md. Renders the active theme's LoginView; no CSS here.
 */
import React from 'react';
import { useThemeRoute } from '../logic/useThemeRoute';

export default function LoginView(props) {
    const Route = useThemeRoute('LoginView');
    return <Route {...props} />;
}
