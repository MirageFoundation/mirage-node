import React from 'react';
import { useThemeRoute } from '../logic/useThemeRoute';

export default function LoginView(props) {
    const Route = useThemeRoute('LoginView');
    return <Route {...props} />;
}
