import React from 'react';
import { useThemeRoute } from '../logic/useThemeRoute';

export default function ReportsView(props) {
    const Route = useThemeRoute('ReportsView');
    return <Route {...props} />;
}
