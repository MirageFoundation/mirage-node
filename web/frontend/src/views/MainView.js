import React from 'react';
import { useThemeRoute } from '../logic/useThemeRoute';

export default function MainView(props) {
    const Route = useThemeRoute('MainView');
    return <Route {...props} />;
}
