import React from 'react';
import { useThemeRoute } from '../logic/useThemeRoute';

export default function ChangeUsernameView(props) {
    const Route = useThemeRoute('ChangeUsernameView');
    return <Route {...props} />;
}
