/**
 * Theme route facade — see ./README.md. Renders the active theme's ProfileView; no CSS here.
 */
import React from 'react';
import { useThemeRoute } from '../logic/useThemeRoute';

export default function ProfileView(props) {
    const Route = useThemeRoute('ProfileView');
    return <Route {...props} />;
}
