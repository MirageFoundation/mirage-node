import React from 'react';
import { useThemeComponent } from '../logic/useThemeComponent';

export default function CardView(props) {
    const Component = useThemeComponent('CardView');
    return <Component {...props} />;
}
