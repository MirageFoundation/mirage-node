import React from 'react';
import { useThemeRoute } from '../logic/useThemeRoute';

export default function CreateAccountView(props) {
    const Route = useThemeRoute('CreateAccountView');
    return <Route {...props} />;
}
