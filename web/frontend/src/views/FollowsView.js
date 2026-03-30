/**
 * Theme route facade — see ./README.md. Renders the active theme's FollowsView; no CSS here.
 */
import React from 'react';
import { useThemeRoute } from '../logic/useThemeRoute';

export default function FollowsView(props) {
    const Route = useThemeRoute('FollowsView');
    return <Route {...props} />;
}
