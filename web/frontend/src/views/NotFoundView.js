import React from 'react';
import { useThemeRoute } from '../logic/useThemeRoute';

export default function NotFoundView(props) {
    const Route = useThemeRoute('NotFoundView');
    return <Route {...props} />;
}
