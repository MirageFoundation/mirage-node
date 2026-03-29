import React from 'react';
import { useThemeRoute } from '../logic/useThemeRoute';

export default function SubscriptionView(props) {
    const Route = useThemeRoute('SubscriptionView');
    return <Route {...props} />;
}
