import React from 'react';
import { useThemeComponent } from '../logic/useThemeComponent';

export default function StickerPicker(props) {
    const Component = useThemeComponent('StickerPicker');
    return <Component {...props} />;
}
