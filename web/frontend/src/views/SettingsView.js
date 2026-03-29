import React from 'react';
import { useThemeRoute } from '../logic/useThemeRoute';

export default function SettingsView(props) {
    const Route = useThemeRoute('SettingsView');
    return <Route {...props} />;
}
