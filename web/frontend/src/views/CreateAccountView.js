/**
 * Theme route facade — see ./README.md. Renders the active theme's CreateAccountView; no CSS here.
 */
import React from 'react';
import { useThemeRoute } from '../logic/useThemeRoute';

export default function CreateAccountView(props) {
    const Route = useThemeRoute('CreateAccountView');
    return <Route {...props} />;
}
