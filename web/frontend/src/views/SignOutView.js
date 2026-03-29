import React from 'react';
import { useThemeRoute } from '../logic/useThemeRoute';

export default function SignOutView(props) {
    const Route = useThemeRoute('SignOutView');
    return <Route {...props} />;
}
