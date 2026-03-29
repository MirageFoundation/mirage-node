import React from 'react';
import { useThemeComponent } from '../logic/useThemeComponent';

export default function InlineMedia(props) {
    const Component = useThemeComponent('InlineMedia');
    return <Component {...props} />;
}
