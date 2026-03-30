/**
 * Theme route facade — see ./README.md. Renders the active theme's BridgeView; no CSS here.
 */
import React from 'react';
import { useThemeRoute } from '../logic/useThemeRoute';

export default function BridgeView(props) {
    const Route = useThemeRoute('BridgeView');
    return <Route {...props} />;
}
