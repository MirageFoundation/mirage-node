import React from 'react';
import { useThemeRoute } from '../logic/useThemeRoute';

export default function BlocksView(props) {
    const Route = useThemeRoute('BlocksView');
    return <Route {...props} />;
}
