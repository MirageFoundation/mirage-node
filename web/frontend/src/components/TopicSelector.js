import React from 'react';
import { useThemeComponent } from '../logic/useThemeComponent';

export function TopicSelector(props) {
    const Component = useThemeComponent('TopicSelector');
    return <Component {...props} />;
}

export default function TopicSelectorDefault(props) {
    return <TopicSelector {...props} />;
}
