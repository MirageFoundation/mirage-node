/**
 * Theme route facade — see ./README.md. Renders the active theme's SearchResultsView; no CSS here.
 */
import React from 'react';
import { useThemeRoute } from '../logic/useThemeRoute';

export default function SearchResultsView(props) {
    const Route = useThemeRoute('SearchResultsView');
    return <Route {...props} />;
}
