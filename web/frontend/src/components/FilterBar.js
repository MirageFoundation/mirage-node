import React from 'react';
import { useThemeComponent } from '../logic/useThemeComponent';

export default function FilterBar(props) {
    const Component = useThemeComponent('FilterBar');
    return <Component {...props} />;
}
