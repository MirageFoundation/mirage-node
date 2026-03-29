import React from 'react';
import { useThemeRoute } from '../logic/useThemeRoute';

export default function CreatePostView(props) {
    const Route = useThemeRoute('CreatePostView');
    return <Route {...props} />;
}
