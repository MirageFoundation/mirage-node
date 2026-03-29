import React from 'react';
import { useThemeRoute } from '../logic/useThemeRoute';

export default function ViewPostView(props) {
    const Route = useThemeRoute('ViewPostView');
    return <Route {...props} />;
}
