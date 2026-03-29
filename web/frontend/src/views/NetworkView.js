import React from 'react';
import { useThemeRoute } from '../logic/useThemeRoute';

export default function NetworkView(props) {
    const Route = useThemeRoute('NetworkView');
    return <Route {...props} />;
}
