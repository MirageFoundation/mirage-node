import React from 'react';
import { useThemeComponent } from '../logic/useThemeComponent';

export default function MobileHeader(props) {
    const Component = useThemeComponent('MobileHeader');
    return <Component {...props} />;
}
