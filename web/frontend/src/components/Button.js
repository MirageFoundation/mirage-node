import React from 'react';
import { useThemeComponent } from '../logic/useThemeComponent';

export default function Button(props) {
    const Component = useThemeComponent('Button');
    return <Component {...props} />;
}
