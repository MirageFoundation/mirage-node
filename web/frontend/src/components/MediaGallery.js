import React from 'react';
import { useThemeComponent } from '../logic/useThemeComponent';

export default function MediaGallery(props) {
    const Component = useThemeComponent('MediaGallery');
    return <Component {...props} />;
}
