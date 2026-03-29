import React from 'react';
import { useThemeRoute } from '../logic/useThemeRoute';

export default function InboxView(props) {
    const Route = useThemeRoute('InboxView');
    return <Route {...props} />;
}
