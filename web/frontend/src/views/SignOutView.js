/**
 * Theme route facade — see ./README.md. Renders the active theme's SignOutView; no CSS here.
 */
import React from 'react';
import { useThemeRoute } from '../logic/useThemeRoute';

export default function SignOutView(props) {
    const Route = useThemeRoute('SignOutView');
    return <Route {...props} />;
}
