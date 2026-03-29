import React from 'react';
import { useThemeRoute } from '../logic/useThemeRoute';

export default function DiscoverView(props) {
    const Route = useThemeRoute('DiscoverView');
    return <Route {...props} />;
}
