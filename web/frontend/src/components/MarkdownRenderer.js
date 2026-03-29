import React from 'react';
import { useThemeComponent } from '../logic/useThemeComponent';

export default function MarkdownRenderer(props) {
    const Component = useThemeComponent('MarkdownRenderer');
    return <Component {...props} />;
}
