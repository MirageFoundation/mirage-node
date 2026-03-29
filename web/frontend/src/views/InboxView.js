/**
 * Theme route facade — see ./README.md. Renders the active theme's InboxView; no CSS here.
 */
import React from 'react';
import { useThemeRoute } from '../logic/useThemeRoute';

export default function InboxView(props) {
    const Route = useThemeRoute('InboxView');
    return <Route {...props} />;
}
