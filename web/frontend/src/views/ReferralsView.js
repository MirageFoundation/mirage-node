import React from 'react';
import { useThemeRoute } from '../logic/useThemeRoute';

export default function ReferralsView(props) {
    const Route = useThemeRoute('ReferralsView');
    return <Route {...props} />;
}
