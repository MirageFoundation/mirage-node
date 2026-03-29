import React from 'react';
import { useTheme, css } from 'styled-components';
import { getThemeComponent, getThemeComponentFromTheme } from '../styled/theme';

export const tooltipStyles = () => css`
    ${({ theme }) => {
        const fn = getThemeComponentFromTheme(theme, 'tooltipStyles');
        return fn();
    }}
`;

export const Tooltip = React.forwardRef(function Tooltip(props, ref) {
    const theme = useTheme();
    const Component = getThemeComponent(theme.themeId, 'Tooltip');
    return <Component ref={ref} {...props} />;
});

export const InfoIcon = React.forwardRef(function InfoIcon(props, ref) {
    const theme = useTheme();
    const Component = getThemeComponent(theme.themeId, 'InfoIcon');
    return <Component ref={ref} {...props} />;
});

export default Tooltip;
