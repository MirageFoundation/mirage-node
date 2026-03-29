import React from 'react';
import { useThemeComponent } from '../logic/useThemeComponent';

export default function QuestHeroCard(props) {
    const Component = useThemeComponent('QuestHeroCard');
    return <Component {...props} />;
}
