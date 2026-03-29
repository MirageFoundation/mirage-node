/**
 * Theme facade — see ./README.md. Renders the active theme's Toast; no CSS here.
 */
import React from 'react';
import { useThemeComponent } from '../logic/useThemeComponent';

export default function Toast(props) {
    const Component = useThemeComponent('Toast');
    return <Component {...props} />;
}
