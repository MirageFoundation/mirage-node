import React from 'react';
import { useThemeRoute } from '../logic/useThemeRoute';

export default function AgentsView(props) {
    const Route = useThemeRoute('AgentsView');
    return <Route {...props} />;
}
