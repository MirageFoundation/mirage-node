/**
 * Theme route facade — see ./README.md. Renders the active theme's BlocksView; no CSS here.
 */
import React from 'react';
import { useThemeRoute } from '../logic/useThemeRoute';

export default function BlocksView(props) {
    const Route = useThemeRoute('BlocksView');
    return <Route {...props} />;
}
