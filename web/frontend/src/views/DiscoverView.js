/**
 * Theme route facade — see ./README.md. Renders the active theme's DiscoverView; no CSS here.
 */
import React from 'react';
import { useThemeRoute } from '../logic/useThemeRoute';

export default function DiscoverView(props) {
    const Route = useThemeRoute('DiscoverView');
    return <Route {...props} />;
}
