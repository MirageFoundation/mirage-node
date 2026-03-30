/**
 * Theme route facade — see ./README.md. Renders the active theme's SubscriptionView; no CSS here.
 */
import React from 'react';
import { useThemeRoute } from '../logic/useThemeRoute';

export default function SubscriptionView(props) {
    const Route = useThemeRoute('SubscriptionView');
    return <Route {...props} />;
}
