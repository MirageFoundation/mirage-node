/**
 * Theme route facade — see ./README.md. Renders the active theme's FAQView; no CSS here.
 */
import React from 'react';
import { useThemeRoute } from '../logic/useThemeRoute';

export default function FAQView(props) {
    const Route = useThemeRoute('FAQView');
    return <Route {...props} />;
}
