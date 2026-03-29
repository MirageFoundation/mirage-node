import React from 'react';
import { useThemeRoute } from '../logic/useThemeRoute';

export default function StatsView(props) {
    const Route = useThemeRoute('StatsView');
    return <Route {...props} />;
}
