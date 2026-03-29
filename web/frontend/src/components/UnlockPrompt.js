import React from 'react';
import { useThemeComponent } from '../logic/useThemeComponent';

export default function UnlockPrompt(props) {
    const Component = useThemeComponent('UnlockPrompt');
    return <Component {...props} />;
}
