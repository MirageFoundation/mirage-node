import React from 'react';
import { useThemeRoute } from '../logic/useThemeRoute';

export default function BridgeView(props) {
    const Route = useThemeRoute('BridgeView');
    return <Route {...props} />;
}
