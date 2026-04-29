import React, { useCallback } from 'react';
import styled, { css } from 'styled-components';

const FLIP_THRESHOLD_PX = 80;

/**
 * CSS mixin for tooltip behavior via data-tooltip attribute.
 * Default: above. Flips below when data-tooltip-pos="below" is set.
 * For auto-detection, use the Tooltip React component instead.
 */
export const tooltipStyles = () => css`
    position: relative;
    -webkit-tap-highlight-color: transparent;

    &:hover,
    &:focus,
    &:active {
        outline: none;
    }

    &::after {
        content: attr(data-tooltip);
        position: absolute;
        bottom: 100%;
        left: 0;
        margin-bottom: 0.3rem;
        background: ${({ theme }) => theme.colors.menuBg};
        border: 1px solid ${({ theme }) => theme.colors.border};
        color: ${({ theme }) => theme.colors.text};
        padding: 0.45rem 0.65rem;
        border-radius: 6px;
        font-size: 0.65rem;
        font-weight: 500;
        white-space: pre-wrap;
        width: max-content;
        max-width: 260px;
        z-index: 1000;
        box-shadow: ${({ theme }) =>
            theme.name === 'light'
                ? '0 6px 16px rgba(15, 23, 42, 0.08)'
                : '0 8px 20px rgba(0, 0, 0, 0.32)'};
        line-height: 1.45;
        opacity: 0;
        pointer-events: none;
        transition: opacity 0.15s ease;
        text-align: left;
        text-transform: none;
    }

    &[data-tooltip-pos="below"]::after {
        bottom: auto;
        top: 100%;
        margin-bottom: 0;
        margin-top: 0.3rem;
    }

    &[data-tooltip]:not([data-tooltip=""]):hover::after,
    &[data-tooltip]:not([data-tooltip=""]):focus::after,
    &[data-tooltip]:not([data-tooltip=""]):active::after {
        opacity: 1;
        pointer-events: auto;
    }
`;

function autoPosition(e) {
    const rect = e.currentTarget.getBoundingClientRect();
    if (rect.top < FLIP_THRESHOLD_PX) {
        e.currentTarget.setAttribute('data-tooltip-pos', 'below');
    } else {
        e.currentTarget.removeAttribute('data-tooltip-pos');
    }
}

const StyledTooltip = styled.span`
    ${() => tooltipStyles()}
    ${({ $dotted }) => $dotted && css`
        text-decoration: underline;
        text-decoration-style: dotted;
        white-space: nowrap;
    `}
    ${({ $subtle }) => $subtle && css`
        color: ${({ theme }) => theme.colors.subtleText};
    `}
`;

/**
 * Single tooltip component. Auto-positions above/below based on viewport.
 *
 * Props:
 *   data-tooltip="text"   — the tooltip content
 *   $dotted               — adds dotted underline to trigger text
 *   $subtle               — uses subtle text color
 */
export const Tooltip = React.forwardRef(function Tooltip({ onMouseEnter, ...props }, ref) {
    const handleEnter = useCallback((e) => {
        autoPosition(e);
        if (onMouseEnter) onMouseEnter(e);
    }, [onMouseEnter]);

    return <StyledTooltip ref={ref} onMouseEnter={handleEnter} {...props} />;
});

/**
 * InfoIcon — small "?" circle with tooltip. Same positioning logic.
 */
export const InfoIcon = styled(Tooltip)`
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 0.5rem;
    height: 0.5rem;
    border-radius: 50%;
    background-color: ${({ theme }) => theme.colors.accent};
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.4rem;
    flex-shrink: 0;
    margin-left: 0.1rem;
    vertical-align: super;

    &::after {
        width: 250px;
        white-space: normal;
        font-size: 0.525rem;
    }
`;

export default Tooltip;
