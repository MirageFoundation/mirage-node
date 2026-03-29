import React from 'react';
import { useThemeComponent } from '../logic/useThemeComponent';

export default function MarkdownEditor(props) {
    const Component = useThemeComponent('MarkdownEditor');
    return <Component {...props} />;
}
