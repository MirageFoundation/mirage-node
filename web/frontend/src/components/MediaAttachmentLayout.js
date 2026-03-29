import React from 'react';
import { useThemeComponent } from '../logic/useThemeComponent';

export function MediaRow(props) {
    const Component = useThemeComponent('MediaRow');
    return <Component {...props} />;
}

export function MediaIconButton(props) {
    const Component = useThemeComponent('MediaIconButton');
    return <Component {...props} />;
}

export function MediaPreviewWrapper(props) {
    const Component = useThemeComponent('MediaPreviewWrapper');
    return <Component {...props} />;
}

export function MediaPreviewImage(props) {
    const Component = useThemeComponent('MediaPreviewImage');
    return <Component {...props} />;
}

export function MediaSpinner(props) {
    const Component = useThemeComponent('MediaSpinner');
    return <Component {...props} />;
}

export function MediaRemoveButton(props) {
    const Component = useThemeComponent('MediaRemoveButton');
    return <Component {...props} />;
}
