import React from 'react';
import { useThemeComponent } from '../logic/useThemeComponent';

export default function AuthPageShell(props) {
    const Component = useThemeComponent('AuthPageShell');
    return <Component {...props} />;
}
