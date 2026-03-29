import React from 'react';
import { useThemeComponent } from '../logic/useThemeComponent';

export default function Sidebar(props) {
    const Component = useThemeComponent('Sidebar');
    return <Component {...props} />;
}
