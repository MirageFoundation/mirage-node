/**
 * Theme route facade — see ./README.md. Renders the active theme's NetworkView; no CSS here.
 */
import React from 'react';
import { useThemeRoute } from '../logic/useThemeRoute';

export default function NetworkView(props) {
    const Route = useThemeRoute('NetworkView');
    return <Route {...props} />;
}
