import React from 'react';
import { useThemeRoute } from '../logic/useThemeRoute';

export default function FollowsView(props) {
    const Route = useThemeRoute('FollowsView');
    return <Route {...props} />;
}
