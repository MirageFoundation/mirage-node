import React from 'react';
import { useThemeComponent } from '../logic/useThemeComponent';

export default function GifPicker(props) {
    const Component = useThemeComponent('GifPicker');
    return <Component {...props} />;
}
