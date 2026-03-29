import React from 'react';
import { useThemeComponent } from '../logic/useThemeComponent';

export function ProfileMenuContent(props) {
    const Component = useThemeComponent('ProfileMenuContent');
    return <Component {...props} />;
}

export default function TopBar(props) {
    const Component = useThemeComponent('TopBar');
    return <Component {...props} />;
}
