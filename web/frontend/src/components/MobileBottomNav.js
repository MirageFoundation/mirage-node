import React from 'react';
import { useThemeComponent } from '../logic/useThemeComponent';

export default function MobileBottomNav(props) {
    const Component = useThemeComponent('MobileBottomNav');
    return <Component {...props} />;
}
