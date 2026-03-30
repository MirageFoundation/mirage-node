/**
 * Theme route facade — see ./README.md. Renders the active theme's CreatePostView; no CSS here.
 */
import React from 'react';
import { useThemeRoute } from '../logic/useThemeRoute';

export default function CreatePostView(props) {
    const Route = useThemeRoute('CreatePostView');
    return <Route {...props} />;
}
