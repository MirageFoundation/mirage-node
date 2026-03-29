import React from 'react';
import { useThemeRoute } from '../logic/useThemeRoute';

export default function ProfileView(props) {
    const Route = useThemeRoute('ProfileView');
    return <Route {...props} />;
}
