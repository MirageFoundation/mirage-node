import React from 'react';
import { useThemeRoute } from '../logic/useThemeRoute';

export default function WelcomeView(props) {
    const Route = useThemeRoute('WelcomeView');
    return <Route {...props} />;
}
