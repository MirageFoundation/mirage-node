/**
 * Theme facades — see ./README.md. Tooltip / InfoIcon use getThemeComponent + useTheme
 * (forwardRef). tooltipStyles() delegates to the theme's `tooltipStyles` helper for use
 * inside styled-components css`` blocks. No visual rules in this file.
 */
import React from 'react';
import { useTheme, css } from 'styled-components';
import { getThemeComponent, getThemeComponentFromTheme } from '../registry/theme';

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
