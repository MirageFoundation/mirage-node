/**
 * Theme route facade — see ./README.md. Renders the active theme's SettingsView; no CSS here.
 */
import React from 'react';
import { useThemeRoute } from '../logic/useThemeRoute';

export default function SettingsView(props) {
    const Route = useThemeRoute('SettingsView');
    return <Route {...props} />;
}
