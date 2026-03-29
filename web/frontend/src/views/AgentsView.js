/**
 * Theme route facade — see ./README.md. Renders the active theme's AgentsView; no CSS here.
 */
import React from 'react';
import { useThemeRoute } from '../logic/useThemeRoute';

export default function AgentsView(props) {
    const Route = useThemeRoute('AgentsView');
    return <Route {...props} />;
}
