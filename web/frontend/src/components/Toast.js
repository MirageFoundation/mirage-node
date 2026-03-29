import React from 'react';
import { useThemeComponent } from '../logic/useThemeComponent';

export default function Toast(props) {
    const Component = useThemeComponent('Toast');
    return <Component {...props} />;
}
