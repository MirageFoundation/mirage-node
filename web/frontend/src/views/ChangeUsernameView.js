/**
 * Theme route facade — see ./README.md. Renders the active theme's ChangeUsernameView; no CSS here.
 */
import React from 'react';
import { useThemeRoute } from '../logic/useThemeRoute';

export default function ChangeUsernameView(props) {
    const Route = useThemeRoute('ChangeUsernameView');
    return <Route {...props} />;
}
